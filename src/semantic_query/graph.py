from __future__ import annotations

import re
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from .common import MAX_TRAVERSAL_DEPTH, SQLITE_TYPE_MAP, identifier_terms, load_yaml, tokenize


class StandaloneSemanticGraph:
    """Parameterized semantic graph loader for standalone usage."""

    def __init__(
        self,
        *,
        schema_dir: Path,
        routing_yaml: Path,
        graph_yaml: Path | None = None,
        patterns_yaml: Path | None = None,
        rules_yaml: Path | None = None,
        mappings_yaml: Path | None = None,
    ) -> None:
        self.schema_dir = schema_dir
        self.routing_yaml = routing_yaml
        semantic_dir = routing_yaml.parent
        self.graph_yaml = graph_yaml or semantic_dir / "graph.yaml"
        self.patterns_yaml = patterns_yaml or semantic_dir / "patterns.yaml"
        self.rules_yaml = rules_yaml or semantic_dir / "rules.yaml"
        self.mappings_yaml = mappings_yaml or self._default_mappings_yaml(semantic_dir)

        self.tables: dict[str, dict[str, Any]] = {}
        self.edges: list[dict[str, Any]] = []
        self.adj: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.routes: list[dict[str, Any]] = []
        self.patterns: dict[str, dict[str, Any]] = {}
        self.pattern_index: dict[str, list[str]] = defaultdict(list)
        self.rules: list[dict[str, Any]] = []
        self.rule_index: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.global_rules: list[dict[str, Any]] = []
        self.supplemental_mappings: list[Any] = []
        self._route_patterns: list[tuple[dict[str, Any], list[re.Pattern[str]]]] = []
        self._table_terms: dict[str, set[str]] = {}
        self._load()

    def _default_mappings_yaml(self, semantic_dir: Path) -> Path:
        generic = semantic_dir / "mappings.yaml"
        if generic.exists():
            return generic
        return semantic_dir / "loc_mappings.yaml"

    def _load_supplemental_mappings(self) -> list[Any]:
        raw = load_yaml(self.mappings_yaml)
        if isinstance(raw, list):
            return raw
        if not isinstance(raw, dict):
            return []
        for key in ("mappings", "levels", "values", "items"):
            value = raw.get(key)
            if isinstance(value, list):
                return value
        return [raw] if raw else []

    def _load(self) -> None:
        for filepath in sorted(self.schema_dir.glob("*.yaml")):
            domain = filepath.stem
            data = load_yaml(filepath)
            for table_name, table_def in data.get("tables", {}).items():
                table_def["_domain"] = domain
                self.tables[table_name] = table_def

        graph_data = load_yaml(self.graph_yaml)
        self.edges = graph_data.get("edges", [])
        for edge in self.edges:
            self.adj[edge["from"]].append(edge)
            reverse_edge = {**edge, "from": edge["to"], "to": edge["from"]}
            self.adj[edge["to"]].append(reverse_edge)

        routing_data = load_yaml(self.routing_yaml)
        self.routes = routing_data.get("routes", [])
        for route in self.routes:
            terms = [str(route["term"]).lower(), *[str(a).lower() for a in route.get("aliases", [])]]
            compiled = [re.compile(r"\b" + re.escape(term) + r"\b") for term in terms]
            self._route_patterns.append((route, compiled))

        patterns_data = load_yaml(self.patterns_yaml)
        if not patterns_data:
            patterns_data = load_yaml(self.patterns_yaml.with_name("query_patterns.yaml"))
        for name, pattern in patterns_data.get("patterns", {}).items():
            self.patterns[name] = pattern
            applies_to = pattern.get("applies_to", [])
            if isinstance(applies_to, str):
                applies_to = [applies_to]
            for table in applies_to:
                self.pattern_index[table].append(name)

        rules_data = load_yaml(self.rules_yaml)
        if not rules_data:
            fallback_rules = self.rules_yaml.with_name("constraints.yaml")
            rules_data = load_yaml(fallback_rules)
            rules_list = rules_data.get("constraints", [])
        else:
            rules_list = rules_data.get("rules", [])

        for rule in rules_list:
            table = rule.get("table")
            if table:
                self.rule_index[table].append(rule)
                self.rules.append(rule)
            else:
                self.global_rules.append(rule)

        self.supplemental_mappings = self._load_supplemental_mappings()
        self._build_table_term_index()

    def _build_table_term_index(self) -> None:
        for table_name, table_def in self.tables.items():
            terms = set()
            terms.update(identifier_terms(table_name))
            summary = table_def.get("summary")
            if isinstance(summary, str):
                terms.update(tokenize(summary))

            for column_name, column_def in table_def.get("columns", {}).items():
                terms.update(identifier_terms(column_name))
                if isinstance(column_def, dict):
                    for key in ("summary", "description"):
                        value = column_def.get(key)
                        if isinstance(value, str):
                            terms.update(tokenize(value))
                    for sample in column_def.get("sample_values", []):
                        if isinstance(sample, str):
                            terms.update(tokenize(sample))

            self._table_terms[table_name] = terms

    def match_tables(self, question: str) -> set[str]:
        q_lower = question.lower()
        matched: set[str] = set()
        for route, compiled_patterns in self._route_patterns:
            for pattern in compiled_patterns:
                if pattern.search(q_lower):
                    matched.update(route.get("tables", []))
                    matched.update(route.get("traversal_hint", []))
                    break
        if not matched:
            matched = self._schema_fallback(question)
        return {table for table in matched if table in self.tables}

    def _schema_fallback(self, question: str) -> set[str]:
        question_terms = tokenize(question)
        if not question_terms:
            return set(self.tables.keys())

        scores: list[tuple[int, str]] = []
        for table_name, table_terms in self._table_terms.items():
            overlap = question_terms & table_terms
            if overlap:
                scores.append((len(overlap), table_name))

        if not scores:
            return set(self.tables.keys())

        scores.sort(reverse=True)
        best_score = scores[0][0]
        selected = {table_name for score, table_name in scores if score == best_score}

        if len(selected) < 3:
            selected.update(
                table_name
                for score, table_name in scores
                if score >= max(1, best_score - 1)
            )
        return selected

    def traverse(self, seed_tables: set[str], max_depth: int = MAX_TRAVERSAL_DEPTH) -> dict[str, Any]:
        visited: set[str] = set()
        relevant_tables: dict[str, dict[str, Any]] = {}
        relevant_edges: list[dict[str, Any]] = []
        queue: deque[tuple[str, int]] = deque()

        for table in seed_tables:
            if table in self.tables:
                queue.append((table, 0))
                visited.add(table)

        while queue:
            table_name, depth = queue.popleft()
            relevant_tables[table_name] = self.tables[table_name]

            if depth >= max_depth:
                continue

            for edge in self.adj.get(table_name, []):
                neighbor = edge["to"]
                if neighbor in visited or neighbor not in self.tables:
                    continue
                weight = edge.get("weight", 0.5)
                should_follow = neighbor in seed_tables or (depth == 0 and weight >= 0.8)
                if not should_follow:
                    continue
                visited.add(neighbor)
                queue.append((neighbor, depth + 1))

                original = next(
                    (
                        e for e in self.edges
                        if (e["from"] == table_name and e["to"] == neighbor)
                        or (e["from"] == neighbor and e["to"] == table_name)
                    ),
                    None,
                )
                if original and original not in relevant_edges:
                    relevant_edges.append(original)

        for edge in self.edges:
            if edge["from"] in visited and edge["to"] in visited and edge not in relevant_edges:
                relevant_edges.append(edge)

        relevant_patterns: dict[str, dict[str, Any]] = {}
        for table_name in visited:
            for pattern_name in self.pattern_index.get(table_name, []):
                relevant_patterns[pattern_name] = self.patterns[pattern_name]

        relevant_rules: list[dict[str, Any]] = []
        for table_name in visited:
            relevant_rules.extend(self.rule_index.get(table_name, []))
        relevant_rules.extend(self.global_rules)

        return {
            "tables": relevant_tables,
            "edges": relevant_edges,
            "patterns": relevant_patterns,
            "rules": relevant_rules,
        }

    def build_prompt_section(self, question: str) -> tuple[str, list[str]]:
        seed_tables = self.match_tables(question)
        subgraph = self.traverse(seed_tables)
        parts: list[str] = ["## Database Schema"]

        domain_tables: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
        for table_name, table_def in subgraph["tables"].items():
            domain = table_def.get("_domain", "misc")
            domain_tables[domain].append((table_name, table_def))

        for domain in sorted(domain_tables):
            for table_name, table_def in sorted(domain_tables[domain]):
                is_seed = table_name in seed_tables
                summary = table_def.get("summary", "")
                parts.append(f"\n### {table_name} ({summary})" if summary else f"\n### {table_name}")

                columns = table_def.get("columns", {})
                if is_seed:
                    for column_name, column_def in columns.items():
                        if not isinstance(column_def, dict):
                            continue
                        col_type = SQLITE_TYPE_MAP.get(str(column_def.get("type", "")), column_def.get("type", ""))
                        line = f"- {column_name}"
                        if col_type:
                            line += f" [{col_type}]"
                        col_summary = column_def.get("summary")
                        if col_summary:
                            line += f": {col_summary}"
                        sample_values = column_def.get("sample_values")
                        if sample_values and len(sample_values) <= 8:
                            line += f" — values: {', '.join(repr(v) for v in sample_values)}"
                        parts.append(line)
                else:
                    parts.append("- Related table; use only if needed for joins or disambiguation.")

        if subgraph["edges"]:
            parts.append("\n## Join Paths")
            for edge in subgraph["edges"]:
                via = edge.get("via", {})
                left = via.get("left", "?")
                right = via.get("right", "?")
                join_text = edge["cast"] if edge.get("cast") else f"{edge['from']}.{left} = {edge['to']}.{right}"
                if edge.get("extra_conditions"):
                    join_text += f" AND {edge['extra_conditions']}"
                if "facility_id" in edge.get("scoped", []):
                    join_text += f" AND {edge['from']}.facility_id = {edge['to']}.facility_id"
                parts.append(f"- {edge['from']} -> {edge['to']}: {join_text}")

        if subgraph["patterns"]:
            parts.append("\n## Query Patterns")
            for name, pattern in subgraph["patterns"].items():
                formula = pattern.get("formula", "")
                alias = pattern.get("alias")
                desc = pattern.get("description", "")
                line = f"- {name}: {formula}"
                if alias:
                    line += f' AS "{alias}"'
                if desc:
                    line += f" — {desc}"
                parts.append(line)

        if subgraph["rules"]:
            parts.append("\n## Rules")
            for rule in subgraph["rules"]:
                target = rule.get("table", "")
                if rule.get("column"):
                    target = f"{target}.{rule['column']}" if target else rule["column"]
                prefix = f"{target}: " if target else ""
                parts.append(f"- {prefix}{rule.get('rule', '')}")

        route_meanings: list[str] = []
        q_lower = question.lower()
        for route, compiled_patterns in self._route_patterns:
            if route.get("meaning") and any(pattern.search(q_lower) for pattern in compiled_patterns):
                route_meanings.append(f"- {route['term']}: {route['meaning']}")
        if route_meanings:
            parts.append("\n## Business Context")
            parts.extend(route_meanings)

        if self.supplemental_mappings:
            parts.append("\n## Supplemental Mappings")
            for mapping in self.supplemental_mappings:
                if not isinstance(mapping, dict):
                    parts.append(f"- {mapping}")
                    continue
                rendered = ", ".join(
                    f"{key}={value}"
                    for key, value in mapping.items()
                    if value not in (None, "", [], {})
                )
                if rendered:
                    parts.append(f"- {rendered}")

        parts.append("\n- If the requested data is not represented in the available schema, say so plainly instead of inventing columns or tables.")
        return "\n".join(parts), sorted(seed_tables)
