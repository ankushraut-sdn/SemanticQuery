# SemanticQuery

Welcome to **SemanticQuery**. This project is a metadata-driven natural-language-to-SQL (Text-to-SQL) engine. It uses a graph-based representation of database schemas, pre-verified query patterns, safety rules, and canonical level of care (LOC) translations to dynamically construct precise prompts for LLMs (Anthropic Claude / AWS Bedrock / OpenAI) and run the generated SQL on a database.

---

## 🚀 Key Features
* **Metadata-Driven Prompts**: Dynamically structures contexts using `graph.yaml`, `patterns.yaml`, `rules.yaml`.
* **Smart Schema Traversal**: Traverses related tables automatically starting from matched seed tables, protecting LLM context lengths.
* **Auto-Repair Loop**: Detects SQL errors and automatically feeds them back into the LLM for real-time query repair.
* **Multi-Database Support**: Operates locally using in-memory **SQLite** (populated via SQL seed files) or connects to production **PostgreSQL** instances.
* **Multi-Provider LLM Integration**: Seamless support for Anthropic Claude (direct API & AWS Bedrock) and OpenAI GPT/o-series models.

---

## 🛠️ Environment Setup

### 1. Create a Virtual Environment
This codebase runs on Python 3.9+. Create and activate a virtual environment in the project root:

```bash
# Create the virtual environment
python3 -m venv .venv

# Activate it
source .venv/bin/activate
```

### 2. Install Dependencies & Package
Install the project in editable mode so you can run the CLI tool globally:

```bash
pip install -e .
```

---

## 🔑 Credentials Configuration

Create a `.env` file in the root directory (or update the existing one) to configure your LLM credentials:

### For OpenAI (GPT-4o, o-series, etc.)
```env
OPENAI_API_KEY=your_openai_api_key_here
```

### For Direct Anthropic Claude API
```env
ANTHROPIC_API_KEY=your_anthropic_api_key_here
```

### For AWS Bedrock Anthropic Claude Integration
```env
AWS_ACCESS_KEY_ID=your_aws_access_key_id
AWS_SECRET_ACCESS_KEY=your_aws_secret_access_key
AWS_REGION=us-east-2
```

---

## 🏃 Run Guide (CLI)

The CLI acts as a query runner. After installing the package, it is registered globally as:
```bash
semantic-query [arguments]
```
Or you can run it as a python module:
```bash
python -m semantic_query [arguments]
```

### 1. Local Development (In-Memory SQLite Mode)
To run a local query, use `--db-seed` with a schema or dev data seed file (e.g. `dev_seed_data.sql` or `init_schema.sql`). The engine creates a temporary in-memory database, builds the schema, runs the query, synthesizes a natural language answer, and tears down the database.

> [!NOTE]
> Make sure to pass the appropriate paths to the `semantic` folder contents.

```bash
semantic-query \
  --query "What is the average length of stay for active patients?" \
  --schema-dir semantic/schema \
  --routing-yaml semantic/routing.yaml \
  --db-seed dev_seed_data.sql \
  --pretty
```

*To output **only the natural-language answer** (chatbot style):*
```bash
semantic-query \
  --query "What is the average length of stay for active patients?" \
  --schema-dir semantic/schema \
  --routing-yaml semantic/routing.yaml \
  --db-seed dev_seed_data.sql \
  --answer-only
```

---

### 2. External Database (PostgreSQL Mode)
To connect to an external SQL database, supply `--db-url` instead of `--db-seed`. 

```bash
semantic-query \
  --query "What is the total revenue collected per payer this month?" \
  --schema-dir semantic/schema \
  --routing-yaml semantic/routing.yaml \
  --db-url "postgresql://postgres:postgres@localhost:5432/semantic_db" \
  --pretty
```

#### Smart Database Seeding & Bootstrapping
When working with an external database, you can automatically initialize the schema and seed the database using `--db-init-schema` and `--db-seed-postgres`:

```bash
semantic-query \
  --query "What is the claims collection rate?" \
  --schema-dir semantic/schema \
  --routing-yaml semantic/routing.yaml \
  --db-url "postgresql://postgres:postgres@localhost:5432/semantic_db" \
  --db-init-schema init_schema.sql \
  --db-seed-postgres dev_seed_data.sql \
  --pretty
```

*To skip bootstrapping on future runs if the database already contains data:*
Use `--skip-seed-if-data-exists` to examine a specific table (default is `facilities` or set via `--seed-check-table`) and skip bootstrapping if data is detected:

```bash
semantic-query \
  --query "What is the claims collection rate?" \
  --schema-dir semantic/schema \
  --routing-yaml semantic/routing.yaml \
  --db-url "postgresql://postgres:postgres@localhost:5432/semantic_db" \
  --db-init-schema init_schema.sql \
  --db-seed-postgres dev_seed_data.sql \
  --skip-seed-if-data-exists \
  --seed-check-table facilities \
  --pretty
```

---

## ⚙️ CLI Parameter Reference

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| **`--query`** | `str` | *Required* | The natural language question to ask the database. |
| **`--schema-dir`** | `str` | *Required* | Path to the directory containing domain schema YAML files. |
| **`--routing-yaml`** | `str` | *Required* | Path to `routing.yaml` for initial intent/keyword table matching. |
| **`--db-seed`** | `str` | `None` | Path to a `.sql` seed file to spin up a local in-memory SQLite database. |
| **`--db-url`** | `str` | `None` | JDBC/SQLAlchemy connection URL (e.g. `postgresql://user:pass@host:5432/db`) for external databases. |
| **`--llm-provider`** | `str` | `"auto"` | LLM client backend to use: `auto`, `anthropic`, or `openai`. |
| **`--model`** | `str` | `claude-sonnet-4-20250514` | Model identifier for the selected provider. |
| **`--openai-model`** | `str` | `None` | OpenAI model identifier (e.g. `gpt-4o`, `o1`). Auto-selects `openai` provider. |
| **`--anthropic-model`**| `str` | `None` | Anthropic model identifier. Auto-selects `anthropic` provider. |
| **`--db-init-schema`** | `str` | `None` | Optional SQL schema file to run on an external database before query. |
| **`--db-seed-postgres`**| `str` | `None` | Optional SQL seed file to run on an external database before query. |
| **`--skip-seed-if-data-exists`**| `bool` | `False` | Skips `--db-init-schema` and `--db-seed-postgres` if checking a table shows it has rows. |
| **`--seed-check-table`**| `str` | `"facilities"` | Table to query for rows when using `--skip-seed-if-data-exists`. |
| **`--graph-yaml`** | `str` | `semantic/graph.yaml`| Custom override for schema graph relationships YAML file. |
| **`--patterns-yaml`** | `str` | `semantic/patterns.yaml`| Custom override for reusable SQL formulas YAML file. |
| **`--rules-yaml`** | `str` | `semantic/rules.yaml`| Custom override for usage rules and constraints YAML file. |
| **`--answer-only`** | `bool` | `False` | Directs the CLI to output ONLY the final synthesized string response. |
| **`--pretty`** | `bool` | `False` | Pretty prints the full output JSON details. |

---

## 📊 CLI Output JSON Structure

When `--answer-only` is not provided, the CLI prints a structured JSON response containing execution details:

```json
{
  "answer": "The average length of stay (LOS) for active patients at Pinnacle Peak Recovery is 45.2 days.",
  "sql": "SELECT AVG(EXTRACT(EPOCH FROM (discharge_date - admission_date)) / 86400.0) AS \"Average LOS\" FROM kipu_patients WHERE discharge_date IS NOT NULL AND mr_number IS NOT NULL AND mr_number != '' AND id != 983;",
  "rows": [
    {
      "Average LOS": 45.21054
    }
  ],
  "row_count": 1,
  "dialect": "postgresql",
  "matched_tables": [
    "kipu_patients"
  ],
  "error": null
}
```
