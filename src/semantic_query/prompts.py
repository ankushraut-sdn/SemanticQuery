from __future__ import annotations

import re

from .common import FORBIDDEN_SQL
from .graph import StandaloneSemanticGraph


def dialect_rules(dialect: str) -> str:
    if dialect == "sqlite":
        return """
## SQL Dialect Rules
- Target dialect: SQLite.
- Use SQLite-compatible syntax only.
- Prefer strftime('%Y-%m', date_column) for month grouping.
- Use julianday(end_date) - julianday(start_date) for day differences.
- Use COALESCE for null handling.
- Do not use PostgreSQL-only syntax such as ILIKE, date_trunc, FILTER, ::casts, or INTERVAL.
"""
    return """
## SQL Dialect Rules
- Target dialect: PostgreSQL.
- You may use ILIKE, date_trunc, EXTRACT, FILTER, and ::type casts when helpful.
- Prefer standard PostgreSQL syntax and human-readable aliases.
"""


def build_system_prompt(*, question: str, graph: StandaloneSemanticGraph, dialect: str) -> tuple[str, list[str]]:
    schema_section, matched_tables = graph.build_prompt_section(question)
    prompt = f"""You are a careful data analyst that translates natural language into SQL.

Return exactly one SQL query wrapped in a ```sql``` code block.

## Safety Rules
- Generate SELECT statements only.
- Never generate INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, CREATE, GRANT, REVOKE, EXEC, or EXECUTE.
- Limit results to 100 rows unless the user explicitly asks for more.
- Prefer explicit joins instead of implicit comma joins.
- Use only tables and columns that exist in the provided schema context.
- If the request is ambiguous, choose the most direct interpretation supported by the matched tables.
- If the request cannot be answered from the provided schema, respond with a short plain-text explanation and no SQL block.

{dialect_rules(dialect)}

{schema_section}
"""
    return prompt, matched_tables


def extract_sql(response_text: str) -> str | None:
    match = re.search(r"```sql\s*(.*?)\s*```", response_text, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else None


def validate_sql(sql: str) -> str:
    sql_stripped = re.sub(r"^\s*(--[^\n]*\n)+\s*", "", sql, flags=re.MULTILINE).strip()
    statements = re.split(r";(?=(?:[^']*'[^']*')*[^']*$)", sql_stripped)
    statements = [statement.strip() for statement in statements if statement.strip()]
    if not statements:
        raise ValueError("No SQL statement was generated")
    sql_stripped = statements[0]
    upper = sql_stripped.upper()
    if not upper.startswith("SELECT") and not upper.startswith("WITH"):
        raise ValueError("Only SELECT queries are allowed")
    for keyword in FORBIDDEN_SQL:
        if re.search(rf"\b{keyword}\b", upper):
            raise ValueError(f"Forbidden SQL keyword: {keyword}")
    return sql_stripped.rstrip().rstrip(";")
