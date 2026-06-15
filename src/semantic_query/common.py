from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

MAX_TRAVERSAL_DEPTH = 2
DEFAULT_LLM_PROVIDER = "auto"
DEFAULT_MODEL = "claude-sonnet-4-20250514"
MAX_SQL_REPAIR_ATTEMPTS = 3

BEDROCK_MODELS = {
    "claude-haiku-4-5-20251001": "us.anthropic.claude-3-5-haiku-20241022-v1:0",
    "claude-sonnet-4-20250514": "us.anthropic.claude-sonnet-4-20250514-v1:0",
    "claude-sonnet-4-5-20250929": "us.anthropic.claude-sonnet-4-20250514-v1:0",
    "claude-3-5-haiku-20241022": "us.anthropic.claude-3-5-haiku-20241022-v1:0",
    "claude-3-5-sonnet-20241022": "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
}

FORBIDDEN_SQL = {
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE",
    "CREATE", "GRANT", "REVOKE", "EXEC", "EXECUTE",
}

SQLITE_TYPE_MAP = {
    "timestamptz": "timestamp",
    "timestamp with time zone": "timestamp",
    "timestamp without time zone": "timestamp",
    "boolean": "integer",
    "jsonb": "text",
}


@dataclass
class QueryResult:
    answer: str
    sql: str
    rows: list[dict[str, Any]]
    row_count: int
    dialect: str
    matched_tables: list[str]
    error: str | None = None


def tokenize(text: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9_]+", text.lower()) if token}


def identifier_terms(name: str) -> set[str]:
    parts = tokenize(name.replace("-", "_"))
    collapsed = name.lower().replace("-", "_")
    if collapsed:
        parts.add(collapsed)
        parts.update(piece for piece in collapsed.split("_") if piece)
    return parts


def load_yaml(filepath: Path) -> dict[str, Any]:
    if not filepath.exists():
        return {}
    with filepath.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def resolve_sync_db_url(db_url: str) -> str:
    if db_url.startswith("postgresql+asyncpg://"):
        return db_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    return db_url
