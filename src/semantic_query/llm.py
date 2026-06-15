from __future__ import annotations

import os
from typing import Any

from .common import BEDROCK_MODELS, DEFAULT_LLM_PROVIDER, DEFAULT_MODEL
from .graph import StandaloneSemanticGraph
from .prompts import build_system_prompt, extract_sql, validate_sql


def resolve_llm_provider(provider: str, model: str) -> str:
    if provider != "auto":
        return provider
    if model.startswith(("gpt-", "o1", "o3", "o4")) or os.getenv("OPENAI_API_KEY", ""):
        if not (os.getenv("AWS_ACCESS_KEY_ID", "") and os.getenv("AWS_SECRET_ACCESS_KEY", "")) and not os.getenv("ANTHROPIC_API_KEY", ""):
            return "openai"
    return DEFAULT_LLM_PROVIDER


def create_llm_client(model: str, provider: str) -> tuple[Any, str, str]:
    resolved_provider = resolve_llm_provider(provider, model)
    if resolved_provider == "openai":
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("openai package is required when llm_provider=openai") from exc
        if not os.getenv("OPENAI_API_KEY", ""):
            raise RuntimeError("OPENAI_API_KEY is required when llm_provider=openai")
        return OpenAI(), model, resolved_provider

    try:
        from anthropic import Anthropic, AnthropicBedrock
    except ImportError as exc:
        raise RuntimeError("anthropic package is required when llm_provider=anthropic") from exc

    aws_access_key = os.getenv("AWS_ACCESS_KEY_ID", "")
    aws_secret_key = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    aws_region = os.getenv("AWS_REGION", "us-east-2")
    anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")

    if aws_access_key and aws_secret_key:
        resolved_model = BEDROCK_MODELS.get(
            model,
            model if "anthropic." in model else BEDROCK_MODELS[DEFAULT_MODEL],
        )
        client = AnthropicBedrock(
            aws_access_key=aws_access_key,
            aws_secret_key=aws_secret_key,
            aws_region=aws_region,
        )
        return client, resolved_model, resolved_provider

    if anthropic_api_key:
        return Anthropic(api_key=anthropic_api_key), model, resolved_provider

    raise RuntimeError(
        "No Anthropic credentials found. Set AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY or ANTHROPIC_API_KEY."
    )


def llm_text_response(
    *,
    client: Any,
    provider: str,
    model: str,
    system_prompt: str,
    messages: list[dict[str, str]],
    max_tokens: int,
) -> str:
    if provider == "openai":
        response = client.responses.create(
            model=model,
            input=[{"role": "system", "content": system_prompt}, *messages],
            max_output_tokens=max_tokens,
        )
        return (response.output_text or "").strip()

    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=messages,
    )
    text_blocks = [block.text for block in response.content if getattr(block, "type", "") == "text"]
    return "\n".join(text_blocks).strip()


def generate_sql(
    *,
    question: str,
    graph: StandaloneSemanticGraph,
    model: str,
    dialect: str,
    llm_provider: str,
) -> tuple[str | None, list[str], str]:
    system_prompt, matched_tables = build_system_prompt(question=question, graph=graph, dialect=dialect)
    client, resolved_model, resolved_provider = create_llm_client(model, llm_provider)
    response_text = llm_text_response(
        client=client,
        provider=resolved_provider,
        model=resolved_model,
        system_prompt=system_prompt,
        messages=[{"role": "user", "content": question}],
        max_tokens=1200,
    )
    sql = extract_sql(response_text)
    if not sql:
        return None, matched_tables, response_text
    return validate_sql(sql), matched_tables, response_text


def generate_answer(
    *,
    question: str,
    sql: str,
    rows: list[dict[str, Any]],
    model: str,
    llm_provider: str,
) -> str:
    if not rows:
        return "No matching data was found for that request."

    if len(rows) == 1 and len(rows[0]) == 1:
        value = next(iter(rows[0].values()))
        return f"The answer is {value}."

    client, resolved_model, resolved_provider = create_llm_client(model, llm_provider)
    display_rows = rows[:50]
    system_prompt = (
        "Respond in plain text only. No markdown, no SQL, no tables, no bullet points. "
        "Write 1-3 concise sentences answering the user's question from the query results."
    )
    answer = llm_text_response(
        client=client,
        provider=resolved_provider,
        model=resolved_model,
        system_prompt=system_prompt,
        messages=[
            {"role": "user", "content": question},
            {"role": "assistant", "content": f"I ran this SQL:\n```sql\n{sql}\n```"},
            {
                "role": "user",
                "content": (
                    f"Here are the query results: {display_rows}. "
                    f"Total rows: {len(rows)}. Give a direct chatbot-style answer."
                ),
            },
        ],
        max_tokens=300,
    )
    return answer or f"Results returned ({len(rows)} rows)."


def generate_execution_failure_answer(
    *,
    question: str,
    sql: str,
    error_str: str,
    model: str,
    llm_provider: str,
) -> str:
    client, resolved_model, resolved_provider = create_llm_client(model, llm_provider)
    system_prompt = (
        "Respond in plain text only. No markdown, no SQL, no bullet points. "
        "Write 1-2 helpful sentences for an end user."
    )
    answer = llm_text_response(
        client=client,
        provider=resolved_provider,
        model=resolved_model,
        system_prompt=system_prompt,
        messages=[
            {"role": "user", "content": question},
            {"role": "assistant", "content": f"I attempted this SQL:\n```sql\n{sql}\n```\nDatabase error: {error_str}"},
            {
                "role": "user",
                "content": (
                    "The SQL failed after several repair attempts. Explain that the request could not be completed, "
                    "briefly mention that the query needs refinement, and offer to try a simpler or rephrased question."
                ),
            },
        ],
        max_tokens=220,
    )
    return answer or (
        "I couldn't complete that database request after a few repair attempts. "
        "Try a simpler or more specific version of the question."
    )
