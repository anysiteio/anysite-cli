"""LLM-powered descriptions for database catalogs."""

from __future__ import annotations

import logging
from typing import Any

import orjson

from anysite.db.discovery import DatabaseCatalog, ImplicitRelationship

logger = logging.getLogger(__name__)


async def llm_describe_catalog(
    catalog: DatabaseCatalog,
    *,
    provider_override: str | None = None,
    model_override: str | None = None,
    no_cache: bool = False,
) -> None:
    """Enrich a catalog with LLM-generated descriptions in place.

    Steps:
    1. Describe each table (name + columns + sample → one-sentence description)
    2. Describe columns per table (all columns in one prompt → per-column descriptions)
    3. Detect implicit relationships (naming patterns like user_id → users.id)
    4. Generate overall database description
    """
    from anysite.llm import get_api_key, load_llm_config
    from anysite.llm.cache import LLMCache as _LLMCache
    from anysite.llm.providers import create_provider

    llm_config = load_llm_config()
    provider_name = provider_override or llm_config.default_provider
    provider_config = llm_config.providers.get(provider_name)
    if not provider_config:
        raise ValueError(f"LLM provider '{provider_name}' not configured. Run 'anysite llm setup'.")

    api_key = get_api_key(provider_config)
    model = model_override or provider_config.default_model
    provider = create_provider(provider_name, api_key, model=model)

    cache = _LLMCache() if llm_config.cache_enabled and not no_cache else None

    try:
        # 1. Describe each table
        for table in catalog.tables:
            table.description = await _describe_table(provider, cache, table, no_cache)

        # 2. Describe columns per table
        for table in catalog.tables:
            col_descs = await _describe_columns(provider, cache, table, no_cache)
            for col in table.columns:
                if col.name in col_descs:
                    col.description = col_descs[col.name]

        # 3. Detect implicit relationships
        catalog.implicit_relationships = await _detect_relationships(
            provider, cache, catalog, no_cache
        )

        # 4. Overall database description
        catalog.description = await _describe_database(provider, cache, catalog, no_cache)

        catalog.llm_enriched = True
    finally:
        await provider.close()


async def _describe_table(
    provider: Any,
    cache: Any,
    table: Any,
    no_cache: bool,
) -> str:
    """Generate a one-sentence table description."""
    from anysite.llm.models import StructuredSchema
    from anysite.llm.prompts import BUILTIN_PROMPTS

    columns_text = ", ".join(
        f"{c.name} ({c.type}{'PK' if c.primary_key else ''})" for c in table.columns
    )
    sample_text = ""
    if table.sample_rows:
        sample_text = "\n\nSample data:\n" + orjson.dumps(
            table.sample_rows[:3], option=orjson.OPT_INDENT_2
        ).decode()

    prompt = BUILTIN_PROMPTS["describe_table"].format(
        table_name=table.name,
        columns=columns_text,
        row_count=table.row_count or "unknown",
        sample_data=sample_text,
    )

    schema = StructuredSchema(
        name="table_description",
        schema={
            "type": "object",
            "properties": {
                "description": {"type": "string"},
            },
            "required": ["description"],
            "additionalProperties": False,
        },
    )

    result = await _llm_call(provider, cache, prompt, schema, no_cache, "describe_table")
    return result.get("description", "")


async def _describe_columns(
    provider: Any,
    cache: Any,
    table: Any,
    no_cache: bool,
) -> dict[str, str]:
    """Generate descriptions for all columns in a table."""
    from anysite.llm.models import StructuredSchema
    from anysite.llm.prompts import BUILTIN_PROMPTS

    columns_text = "\n".join(
        f"  - {c.name}: {c.type}"
        + (" (PK)" if c.primary_key else "")
        + (" NOT NULL" if not c.nullable else "")
        + (f" DEFAULT {c.default}" if c.default else "")
        for c in table.columns
    )
    sample_text = ""
    if table.sample_rows:
        sample_text = orjson.dumps(
            table.sample_rows[:3], option=orjson.OPT_INDENT_2
        ).decode()

    prompt = BUILTIN_PROMPTS["describe_columns"].format(
        table_name=table.name,
        columns=columns_text,
        sample_data=sample_text,
    )

    col_names = [c.name for c in table.columns]
    schema = StructuredSchema(
        name="column_descriptions",
        schema={
            "type": "object",
            "properties": {
                "columns": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "description": {"type": "string"},
                        },
                        "required": ["name", "description"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["columns"],
            "additionalProperties": False,
        },
    )

    result = await _llm_call(provider, cache, prompt, schema, no_cache, "describe_columns")
    descs: dict[str, str] = {}
    for item in result.get("columns", []):
        if item.get("name") in col_names:
            descs[item["name"]] = item["description"]
    return descs


async def _detect_relationships(
    provider: Any,
    cache: Any,
    catalog: DatabaseCatalog,
    no_cache: bool,
) -> list[ImplicitRelationship]:
    """Detect implicit relationships from naming patterns."""
    from anysite.llm.models import StructuredSchema
    from anysite.llm.prompts import BUILTIN_PROMPTS

    if len(catalog.tables) < 2:
        return []

    # Build a compact schema overview
    tables_text = ""
    for t in catalog.tables:
        cols = ", ".join(c.name for c in t.columns)
        tables_text += f"  {t.name}: {cols}\n"

    prompt = BUILTIN_PROMPTS["detect_relationships"].format(tables=tables_text)

    schema = StructuredSchema(
        name="implicit_relationships",
        schema={
            "type": "object",
            "properties": {
                "relationships": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "from_table": {"type": "string"},
                            "from_column": {"type": "string"},
                            "to_table": {"type": "string"},
                            "to_column": {"type": "string"},
                            "confidence": {"type": "number"},
                            "reason": {"type": "string"},
                        },
                        "required": [
                            "from_table",
                            "from_column",
                            "to_table",
                            "to_column",
                            "confidence",
                            "reason",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["relationships"],
            "additionalProperties": False,
        },
    )

    result = await _llm_call(provider, cache, prompt, schema, no_cache, "detect_relationships")

    # Filter to only tables/columns that exist
    table_names = {t.name for t in catalog.tables}
    table_columns: dict[str, set[str]] = {
        t.name: {c.name for c in t.columns} for t in catalog.tables
    }
    # Also exclude already-declared FKs
    existing_fks: set[tuple[str, str, str, str]] = set()
    for t in catalog.tables:
        for fk in t.foreign_keys:
            for fc, rc in zip(fk.constrained_columns, fk.referred_columns, strict=False):
                existing_fks.add((t.name, fc, fk.referred_table, rc))

    relationships: list[ImplicitRelationship] = []
    for r in result.get("relationships", []):
        ft = r.get("from_table", "")
        fc = r.get("from_column", "")
        tt = r.get("to_table", "")
        tc = r.get("to_column", "")
        if (
            ft in table_names
            and tt in table_names
            and fc in table_columns.get(ft, set())
            and tc in table_columns.get(tt, set())
            and (ft, fc, tt, tc) not in existing_fks
        ):
            relationships.append(
                ImplicitRelationship(
                    from_table=ft,
                    from_column=fc,
                    to_table=tt,
                    to_column=tc,
                    confidence=r.get("confidence", 0.0),
                    reason=r.get("reason", ""),
                )
            )
    return relationships


async def _describe_database(
    provider: Any,
    cache: Any,
    catalog: DatabaseCatalog,
    no_cache: bool,
) -> str:
    """Generate an overall database description."""
    from anysite.llm.models import StructuredSchema
    from anysite.llm.prompts import BUILTIN_PROMPTS

    tables_text = ""
    for t in catalog.tables:
        row_info = f" ({t.row_count:,} rows)" if t.row_count is not None else ""
        desc = f" — {t.description}" if t.description else ""
        tables_text += f"  {t.name}{row_info}{desc}\n"

    prompt = BUILTIN_PROMPTS["describe_database"].format(
        connection_name=catalog.connection_name,
        database_type=catalog.database_type,
        tables=tables_text,
    )

    schema = StructuredSchema(
        name="database_description",
        schema={
            "type": "object",
            "properties": {
                "description": {"type": "string"},
            },
            "required": ["description"],
            "additionalProperties": False,
        },
    )

    result = await _llm_call(provider, cache, prompt, schema, no_cache, "describe_database")
    return result.get("description", "")


async def _llm_call(
    provider: Any,
    cache: Any,
    user_prompt: str,
    structured: Any,
    no_cache: bool,
    cache_prefix: str,
) -> dict[str, Any]:
    """Make a single LLM call with optional caching."""
    from anysite.llm.cache import LLMCache
    from anysite.llm.models import LLMMessage

    # Check cache
    cache_key = None
    if cache and not no_cache:
        cache_key = LLMCache.make_key(
            provider.__class__.__name__,
            cache_prefix,
            user_prompt,
        )
        cached = cache.get(cache_key)
        if cached is not None:
            try:
                return orjson.loads(cached["content"])
            except (orjson.JSONDecodeError, ValueError):
                pass

    messages = [LLMMessage(role="user", content=user_prompt)]

    response = await provider.complete(
        messages,
        temperature=0.0,
        max_tokens=4096,
        structured=structured,
    )

    # Cache response
    if cache and cache_key:
        cache.put(
            cache_key,
            response.model,
            response.content,
            response.input_tokens,
            response.output_tokens,
        )

    try:
        return orjson.loads(response.content)
    except (orjson.JSONDecodeError, ValueError):
        logger.warning("Failed to parse LLM response as JSON: %s", response.content[:200])
        return {}
