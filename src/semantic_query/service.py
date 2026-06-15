from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import create_engine

from dotenv import load_dotenv

from .common import DEFAULT_LLM_PROVIDER, DEFAULT_MODEL, QueryResult, resolve_sync_db_url
from .execution import execute_sql_with_retries, postgres_table_has_rows, run_sql_file_on_engine
from .graph import StandaloneSemanticGraph
from .llm import generate_answer, generate_execution_failure_answer, generate_sql

logger = logging.getLogger(__name__)


def run_query(
    *,
    query: str,
    schema_dir: str | Path,
    routing_yaml: str | Path,
    db_seed_path: str | Path | None = None,
    db_url: str | None = None,
    model: str = DEFAULT_MODEL,
    llm_provider: str = DEFAULT_LLM_PROVIDER,
    graph_yaml: str | Path | None = None,
    patterns_yaml: str | Path | None = None,
    rules_yaml: str | Path | None = None,
    mappings_yaml: str | Path | None = None,
    db_init_schema: str | Path | None = None,
    db_seed_postgres: str | Path | None = None,
    skip_seed_if_data_exists: bool = False,
    seed_check_table: str = "facilities",
    env_file: str | Path | None = None,
    load_default_env_files: bool = True,
) -> QueryResult:
    if env_file:
        load_dotenv(dotenv_path=env_file)
    elif load_default_env_files:
        load_dotenv()
    if bool(db_seed_path) == bool(db_url):
        raise ValueError("Provide exactly one of db_seed_path or db_url")
    if db_seed_path and db_seed_postgres:
        raise ValueError("Postgres seed options cannot be used with db_seed_path/SQLite mode")

    graph = StandaloneSemanticGraph(
        schema_dir=Path(schema_dir),
        routing_yaml=Path(routing_yaml),
        graph_yaml=Path(graph_yaml) if graph_yaml else None,
        patterns_yaml=Path(patterns_yaml) if patterns_yaml else None,
        rules_yaml=Path(rules_yaml) if rules_yaml else None,
        mappings_yaml=Path(mappings_yaml) if mappings_yaml else None,
    )

    if db_seed_path:
        dialect = "sqlite"
        sql, matched_tables, raw_response = generate_sql(
            question=query,
            graph=graph,
            model=model,
            dialect=dialect,
            llm_provider=llm_provider,
        )
        if sql is None:
            return QueryResult(
                answer=raw_response,
                sql="",
                rows=[],
                row_count=0,
                dialect=dialect,
                matched_tables=matched_tables,
                error=None,
            )
        sql, rows, execution_error = execute_sql_with_retries(
            sql=sql,
            question=query,
            graph=graph,
            dialect=dialect,
            model=model,
            llm_provider=llm_provider,
            sqlite_seed_path=Path(db_seed_path),
            sqlite_init_schema=Path(db_init_schema) if db_init_schema else None,
        )
    else:
        engine = create_engine(resolve_sync_db_url(db_url), future=True)
        dialect = engine.dialect.name
        try:
            should_skip_bootstrap = False
            if skip_seed_if_data_exists and (db_init_schema or db_seed_postgres):
                should_skip_bootstrap = postgres_table_has_rows(engine, seed_check_table)
                if should_skip_bootstrap:
                    logger.info(
                        "Skipping Postgres bootstrap because table '%s' already has data",
                        seed_check_table,
                    )

            if db_init_schema and not should_skip_bootstrap:
                run_sql_file_on_engine(Path(db_init_schema), engine)
            if db_seed_postgres and not should_skip_bootstrap:
                run_sql_file_on_engine(Path(db_seed_postgres), engine)

            sql, matched_tables, raw_response = generate_sql(
                question=query,
                graph=graph,
                model=model,
                dialect=dialect,
                llm_provider=llm_provider,
            )
            if sql is None:
                return QueryResult(
                    answer=raw_response,
                    sql="",
                    rows=[],
                    row_count=0,
                    dialect=dialect,
                    matched_tables=matched_tables,
                    error=None,
                )
            sql, rows, execution_error = execute_sql_with_retries(
                sql=sql,
                question=query,
                graph=graph,
                dialect=dialect,
                model=model,
                llm_provider=llm_provider,
                engine=engine,
            )
        finally:
            engine.dispose()

    if execution_error:
        answer = generate_execution_failure_answer(
            question=query,
            sql=sql,
            error_str=execution_error,
            model=model,
            llm_provider=llm_provider,
        )
    else:
        answer = generate_answer(
            question=query,
            sql=sql,
            rows=rows,
            model=model,
            llm_provider=llm_provider,
        )

    return QueryResult(
        answer=answer,
        sql=sql,
        rows=rows,
        row_count=len(rows),
        dialect=dialect,
        matched_tables=matched_tables,
        error=execution_error,
    )
