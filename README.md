# SemanticQuery

## 1. Project Overview

**Project Name:** SemanticQuery
**Project Type:** CLI / Backend (Python library + console tool)
**Version:** 0.1.0 (from `pyproject.toml`)
**Status:** Development

### Description

SemanticQuery is a metadata-driven natural-language-to-SQL (Text-to-SQL) engine. It uses a graph-based representation of database schemas, pre-verified query patterns, safety rules, and canonical level-of-care (LOC) translations to dynamically construct precise prompts for LLMs (Anthropic Claude, AWS Bedrock, or OpenAI), run the generated SQL against a database, and synthesize a natural-language answer with the result.

## 2. Core Features

- Metadata-driven prompts: dynamically structures LLM context using `graph.yaml`, `patterns.yaml`, and `rules.yaml`.
- Smart schema traversal: walks related tables starting from matched seed tables, keeping prompts within LLM context limits.
- Auto-repair loop: detects SQL execution errors and feeds them back to the LLM for real-time query correction.
- Multi-database support: runs locally against an in-memory SQLite database seeded from SQL files, or connects to a production PostgreSQL instance.
- Multi-provider LLM integration: supports Anthropic Claude (direct API and AWS Bedrock) and OpenAI GPT/o-series models, selectable via CLI flags or auto-detected from available credentials.
- CLI tool with structured JSON output (SQL, rows, matched tables, natural-language answer) or an answer-only mode for chatbot-style responses.

## 3. Tech Stack

| Component | Technology |
|---|---|
| Language | Python >= 3.9 |
| Local database | SQLite (in-memory) |
| External database | PostgreSQL (via `psycopg2-binary`, SQLAlchemy-style connection URLs) |
| LLM providers | Anthropic Claude API, AWS Bedrock, OpenAI API |
| Configuration | YAML (`graph.yaml`, `patterns.yaml`, `rules.yaml`, `routing.yaml`) |
| Env management | `python-dotenv` |
| Packaging | `setuptools`, console-script entry point |

## 4. Project Structure

```
SemanticQuery/
├── src/semantic_query/
│   ├── cli.py          # CLI entry point and argument parsing
│   ├── service.py      # Orchestration: schema matching -> prompt build -> LLM -> SQL exec -> answer
│   ├── graph.py         # Schema graph traversal
│   ├── prompts.py       # Prompt construction from graph/patterns/rules
│   ├── execution.py      # SQL execution against SQLite/PostgreSQL
│   ├── llm.py           # Multi-provider LLM client (Anthropic/Bedrock/OpenAI)
│   └── common.py
├── semantic/             # graph.yaml, patterns.yaml, rules.yaml, routing.yaml, schema/
├── semantic_config_significance.md
├── pyproject.toml
└── requirements.txt
```

## 5. Prerequisites

- Python 3.9+
- An API key/credentials for at least one supported LLM provider (OpenAI, Anthropic direct, or AWS Bedrock)
- Optional: a PostgreSQL instance if not using the in-memory SQLite mode

## 6. How to Run

### Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Configure credentials

Create a `.env` file in the project root (see [Environment Variables](#7-environment-variables--credentials) below).

### Run a query

The CLI is registered globally as `semantic-query`, or can be run as a module with `python -m semantic_query`.

**In-memory SQLite (local dev data):**

```bash
semantic-query \
  --query "What is the average length of stay for active patients?" \
  --schema-dir semantic/schema \
  --routing-yaml semantic/routing.yaml \
  --db-seed dev_seed_data.sql \
  --pretty
```

Add `--answer-only` to print just the synthesized natural-language answer.

**External PostgreSQL database:**

```bash
semantic-query \
  --query "What is the total revenue collected per payer this month?" \
  --schema-dir semantic/schema \
  --routing-yaml semantic/routing.yaml \
  --db-url "postgresql://postgres:postgres@localhost:5432/semantic_db" \
  --pretty
```

Use `--db-init-schema` and `--db-seed-postgres` to bootstrap an external database automatically, and `--skip-seed-if-data-exists` (with `--seed-check-table`) to avoid reseeding a database that already has data.

#### Key CLI parameters

| Parameter | Default | Description |
| :--- | :--- | :--- |
| `--query` | *required* | Natural language question to ask the database. |
| `--schema-dir` | *required* | Path to domain schema YAML files. |
| `--routing-yaml` | *required* | Path to `routing.yaml` for intent/keyword table matching. |
| `--db-seed` | `None` | SQL seed file for a local in-memory SQLite database. |
| `--db-url` | `None` | Connection URL for an external database. |
| `--llm-provider` | `"auto"` | `auto`, `anthropic`, or `openai`. |
| `--model` | `claude-sonnet-4-20250514` | Model identifier for the selected provider. |
| `--openai-model` | `None` | OpenAI model (e.g. `gpt-4o`); also forces `--llm-provider openai`. |
| `--anthropic-model` | `None` | Anthropic model (e.g. `claude-sonnet-4-20250514`); also forces `--llm-provider anthropic`. |
| `--env-file` | `None` | Optional env file to load before running. |
| `--no-default-env-files` | `False` | Skip auto-loading `.env` files from the default project layout. |
| `--db-init-schema` / `--db-seed-postgres` | `None` | Bootstrap an external database with schema/seed SQL before querying. |
| `--skip-seed-if-data-exists` | `False` | Skip bootstrapping if `--seed-check-table` already has rows. |
| `--seed-check-table` | `"facilities"` | Table checked for existing data when `--skip-seed-if-data-exists` is set. |
| `--graph-yaml` / `--patterns-yaml` / `--rules-yaml` | `None` | Optional override paths for the corresponding config file (defaults resolved from `--schema-dir`). |
| `--mappings-yaml` (alias `--loc-mappings-yaml`) | `None` | Optional supplemental LOC mappings YAML file. |
| `--answer-only` | `False` | Print only the final natural-language answer. |
| `--pretty` | `False` | Pretty-print the full JSON output. |

Full output (without `--answer-only`) is structured JSON containing the answer, generated SQL, returned rows, matched tables, and any error.

## 7. Environment Variables / Credentials

```env
# OpenAI (GPT-4o, o-series, etc.)
OPENAI_API_KEY=your_openai_api_key_here

# Direct Anthropic Claude API
ANTHROPIC_API_KEY=your_anthropic_api_key_here

# AWS Bedrock Anthropic Claude integration
AWS_ACCESS_KEY_ID=your_aws_access_key_id
AWS_SECRET_ACCESS_KEY=your_aws_secret_access_key
AWS_REGION=us-east-2
```

Only the credentials for the provider(s) you intend to use are required; the CLI auto-detects an available provider when `--llm-provider auto` (the default) is used.

## 8. Known Limitations

- No automated test suite is present in this repository.
- `--llm-provider auto` detection depends on which credentials are present in the environment; behavior can be ambiguous if multiple providers' keys are set without an explicit `--llm-provider`.

## 9. License

`pyproject.toml` declares an MIT License classifier, but no `LICENSE` file is present in the repository.
