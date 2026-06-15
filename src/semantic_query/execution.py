from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .common import MAX_SQL_REPAIR_ATTEMPTS
from .graph import StandaloneSemanticGraph
from .llm import create_llm_client, llm_text_response
from .prompts import build_system_prompt, extract_sql, validate_sql

import re

logger = logging.getLogger(__name__)


def sanitize_postgresql_for_sqlite(sql_script: str) -> str:
    # Remove lines starting with SET (Postgres config parameters)
    sql_script = re.sub(r"(?i)^\s*SET\s+[^;]+;$", "", sql_script, flags=re.MULTILINE)
    # Remove DO $$ ... $$; procedural blocks
    sql_script = re.sub(r"(?i)DO\s+\$\$.*?\$\$;?", "", sql_script, flags=re.DOTALL)
    # Remove CREATE TYPE ... AS ENUM (...)
    sql_script = re.sub(r"(?i)CREATE\s+TYPE\s+\S+\s+AS\s+ENUM\s*\([^)]*\);?", "", sql_script)
    # Remove sequence commands
    sql_script = re.sub(r"(?i)CREATE\s+SEQUENCE\s+[^;]+;?", "", sql_script)
    sql_script = re.sub(r"(?i)ALTER\s+SEQUENCE\s+[^;]+;?", "", sql_script)
    # Remove SELECT pg_catalog...
    sql_script = re.sub(r"(?i)SELECT\s+pg_catalog\.[^;]+;?", "", sql_script)
    # Remove Postgres-specific setval sequence operations
    sql_script = re.sub(r"(?i)SELECT\s+setval\([^)]*\);?", "", sql_script)
    # Remove schema prefixes (e.g., public.facilities -> facilities)
    sql_script = re.sub(r"\bpublic\.", "", sql_script)
    # Remove ALL ALTER TABLE statements (not needed or supported in SQLite sandbox)
    sql_script = re.sub(r"(?i)ALTER\s+TABLE\s+[^;]+;?", "", sql_script)
    # Remove CREATE POLICY statements
    sql_script = re.sub(r"(?i)CREATE\s+POLICY\s+[^;]+;?", "", sql_script)
    # Strip USING btree from INDEX statements
    sql_script = re.sub(r"(?i)\bUSING\s+btree\b", "", sql_script)
    # Remove DEFAULT nextval(...)
    sql_script = re.sub(r"(?i)DEFAULT\s+nextval\([^)]*\)", "", sql_script)
    # Strip Postgres ::casts (e.g. '{}'::jsonb -> '{}')
    sql_script = re.sub(r"::[a-zA-Z0-9_.]+(?:\s+[a-zA-Z0-9_.]+)*", "", sql_script)
    # Inline primary keys for SQLite compatibility (so ON CONFLICT matches a PK)
    sql_script = re.sub(r"\bid\s+integer(?:\s+NOT\s+NULL)?\b", "id integer PRIMARY KEY", sql_script)
    # Strip now() and NOW() functions
    sql_script = re.sub(r"(?i)\bnow\(\)", "CURRENT_TIMESTAMP", sql_script)
    # Strip psql backslash directives (e.g. \connect, \set, \restrict)
    sql_script = re.sub(r"^\s*\\[a-zA-Z].*$", "", sql_script, flags=re.MULTILINE)
    return sql_script


def execute_sqlite(
    sql: str,
    db_seed_path: Path,
    db_init_schema: Path | None = None,
) -> list[dict[str, Any]]:
    init_sql = db_init_schema.read_text(encoding="utf-8") if db_init_schema else ""
    seed_sql = db_seed_path.read_text(encoding="utf-8")
    full_sql = init_sql + "\n" + seed_sql
    sanitized_sql = sanitize_postgresql_for_sqlite(full_sql)
    with sqlite3.connect(":memory:") as connection:
        connection.row_factory = sqlite3.Row
        connection.executescript(sanitized_sql)
        cursor = connection.execute(sql)
        return [dict(row) for row in cursor.fetchall()]


def execute_engine(sql: str, engine: Engine) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        result = connection.execute(text(sql))
        return [dict(row) for row in result.mappings().all()]


def repair_sql_after_error(
    *,
    question: str,
    failed_sql: str,
    error_str: str,
    graph: StandaloneSemanticGraph,
    dialect: str,
    model: str,
    llm_provider: str,
) -> str:
    system_prompt, _ = build_system_prompt(question=question, graph=graph, dialect=dialect)
    client, resolved_model, resolved_provider = create_llm_client(model, llm_provider)
    response_text = llm_text_response(
        client=client,
        provider=resolved_provider,
        model=resolved_model,
        system_prompt=system_prompt,
        messages=[
            {"role": "user", "content": question},
            {"role": "assistant", "content": f"```sql\n{failed_sql}\n```"},
            {
                "role": "user",
                "content": (
                    "The SQL above failed during execution.\n"
                    f"Database error: {error_str}\n\n"
                    f"Generate a corrected {dialect.upper()} SELECT query for the same user request. "
                    "Return only SQL in a ```sql``` block."
                ),
            },
        ],
        max_tokens=1400,
    )
    repaired_sql = extract_sql(response_text)
    if not repaired_sql:
        raise ValueError(f"Model did not return repaired SQL. Raw response: {response_text}")
    return validate_sql(repaired_sql)


def execute_sql_with_retries(
    *,
    sql: str,
    question: str,
    graph: StandaloneSemanticGraph,
    dialect: str,
    model: str,
    llm_provider: str,
    sqlite_seed_path: Path | None = None,
    sqlite_init_schema: Path | None = None,
    engine: Engine | None = None,
    max_attempts: int = MAX_SQL_REPAIR_ATTEMPTS,
) -> tuple[str, list[dict[str, Any]], str | None]:
    current_sql = sql
    last_error: str | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            if sqlite_seed_path is not None:
                rows = execute_sqlite(current_sql, sqlite_seed_path, sqlite_init_schema)
            elif engine is not None:
                rows = execute_engine(current_sql, engine)
            else:
                raise ValueError("Either sqlite_seed_path or engine must be provided")
            return current_sql, rows, None
        except Exception as exc:
            last_error = str(exc)
            logger.error(
                "Query execution failed on attempt %d/%d: %s\nSQL: %s",
                attempt,
                max_attempts,
                exc,
                current_sql,
            )
            if attempt == max_attempts:
                break
            try:
                current_sql = repair_sql_after_error(
                    question=question,
                    failed_sql=current_sql,
                    error_str=last_error,
                    graph=graph,
                    dialect=dialect,
                    model=model,
                    llm_provider=llm_provider,
                )
                logger.info("Retrying repaired SQL on attempt %d/%d", attempt + 1, max_attempts)
            except Exception as repair_exc:
                logger.error("SQL repair failed on attempt %d/%d: %s", attempt, max_attempts, repair_exc)

    return current_sql, [], last_error


def run_sql_file_on_engine(sql_file: Path, engine: Engine) -> None:
    script = sql_file.read_text(encoding="utf-8")
    # Strip psql client-side backslash commands (e.g. \restrict, \connect, \set)
    script = re.sub(r"^\s*\\[a-zA-Z].*$", "", script, flags=re.MULTILINE)
    raw_connection = engine.raw_connection()
    try:
        cursor = raw_connection.cursor()
        try:
            cursor.execute(script)
        finally:
            cursor.close()
        raw_connection.commit()
    except Exception:
        raw_connection.rollback()
        raise
    finally:
        raw_connection.close()


def postgres_table_has_rows(engine: Engine, table_name: str) -> bool:
    exists_sql = text("""
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = :table_name
        )
    """)
    with engine.connect() as connection:
        table_exists = bool(connection.execute(exists_sql, {"table_name": table_name}).scalar())
        if not table_exists:
            return False
        row = connection.execute(text(f'SELECT 1 FROM "{table_name}" LIMIT 1')).first()
        return row is not None
