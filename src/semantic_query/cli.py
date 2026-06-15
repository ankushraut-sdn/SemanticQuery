from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict

from .common import DEFAULT_LLM_PROVIDER, DEFAULT_MODEL
from .service import run_query


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Standalone natural-language-to-SQL query runner")
    parser.add_argument("--query", required=True, help="Natural-language question to answer")
    parser.add_argument("--schema-dir", required=True, help="Directory containing schema YAML files")
    parser.add_argument("--routing-yaml", required=True, help="Path to routing.yaml")
    parser.add_argument(
        "--llm-provider",
        default=DEFAULT_LLM_PROVIDER,
        choices=["auto", "anthropic", "openai"],
        help="LLM backend to use for SQL generation and answer synthesis",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Model identifier for the selected LLM provider")
    parser.add_argument(
        "--openai-model",
        help="OpenAI model identifier (e.g. gpt-4o, gpt-4o-mini). Automatically sets --llm-provider to openai",
    )
    parser.add_argument(
        "--anthropic-model",
        help="Anthropic model identifier (e.g. claude-sonnet-4-20250514, claude-3-5-sonnet-20241022). Automatically sets --llm-provider to anthropic",
    )
    parser.add_argument("--env-file", help="Optional env file to load before running")
    parser.add_argument(
        "--no-default-env-files",
        action="store_true",
        help="Do not auto-load .env files from the current project layout",
    )
    parser.add_argument("--db-seed", dest="db_seed_path", help="Path to .sql seed file for in-memory SQLite")
    parser.add_argument("--db-url", help="Connection string for external database")
    parser.add_argument("--db-init-schema", help="Optional schema SQL to run before querying an external database")
    parser.add_argument("--db-seed-postgres", help="Optional seed SQL to run before querying an external database")
    parser.add_argument(
        "--skip-seed-if-data-exists",
        action="store_true",
        help="Skip Postgres schema/seed bootstrap when the check table already contains data",
    )
    parser.add_argument(
        "--seed-check-table",
        default="facilities",
        help="Table name to check for existing data when --skip-seed-if-data-exists is set",
    )
    parser.add_argument("--graph-yaml", help="Optional override path for graph.yaml")
    parser.add_argument("--patterns-yaml", help="Optional override path for patterns.yaml")
    parser.add_argument("--rules-yaml", help="Optional override path for rules.yaml")
    parser.add_argument(
        "--mappings-yaml",
        "--loc-mappings-yaml",
        dest="mappings_yaml",
        help="Optional supplemental mappings YAML file",
    )
    parser.add_argument("--answer-only", action="store_true", help="Print only the chatbot-style answer")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    return parser


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    parser = build_arg_parser()
    args = parser.parse_args()

    if args.openai_model and args.anthropic_model:
        parser.error("Cannot specify both --openai-model and --anthropic-model")

    llm_provider = args.llm_provider
    model = args.model

    if args.openai_model:
        llm_provider = "openai"
        model = args.openai_model
    elif args.anthropic_model:
        llm_provider = "anthropic"
        model = args.anthropic_model

    result = run_query(
        query=args.query,
        schema_dir=args.schema_dir,
        routing_yaml=args.routing_yaml,
        db_seed_path=args.db_seed_path,
        db_url=args.db_url,
        model=model,
        llm_provider=llm_provider,
        graph_yaml=args.graph_yaml,
        patterns_yaml=args.patterns_yaml,
        rules_yaml=args.rules_yaml,
        mappings_yaml=args.mappings_yaml,
        db_init_schema=args.db_init_schema,
        db_seed_postgres=args.db_seed_postgres,
        skip_seed_if_data_exists=args.skip_seed_if_data_exists,
        seed_check_table=args.seed_check_table,
        env_file=args.env_file,
        load_default_env_files=not args.no_default_env_files,
    )
    if args.answer_only:
        print(result.answer)
        return 0
    indent = 2 if args.pretty else None
    print(json.dumps(asdict(result), indent=indent, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
