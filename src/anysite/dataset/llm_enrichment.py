"""Bridge between dataset collection pipeline and LLM subsystem.

Applies per-source LLM enrichment steps (enrich, classify, summarize, generate)
after API collection, before Parquet write. Enriched fields are stored in Parquet
alongside raw data and flow to the database via db_load.fields.
"""

from __future__ import annotations

import logging
from typing import Any

from anysite.dataset.errors import DatasetError
from anysite.dataset.models import LLMStepConfig

logger = logging.getLogger(__name__)


async def enrich_records(
    records: list[dict[str, Any]],
    steps: list[LLMStepConfig],
    *,
    quiet: bool = False,
) -> list[dict[str, Any]]:
    """Apply LLM enrichment steps to records in sequence.

    Each step adds columns to the records. Steps run in order so
    later steps can reference fields added by earlier steps.

    Returns the records with enriched fields merged in.
    """
    from anysite.llm import check_llm_deps, load_llm_config

    check_llm_deps()
    llm_config = load_llm_config()

    for step in steps:
        try:
            records = await _run_step(records, step, llm_config, quiet=quiet)
        except Exception as e:
            logger.warning("LLM step '%s' failed: %s — skipping", step.type, e)
            if not quiet:
                from anysite.output.console import print_warning

                print_warning(f"LLM {step.type} step failed: {e} — skipping")
            # Set enriched fields to None for this step
            _set_none_fields(records, step)

    return records


async def _run_step(
    records: list[dict[str, Any]],
    step: LLMStepConfig,
    llm_config: Any,
    *,
    quiet: bool = False,
) -> list[dict[str, Any]]:
    """Run a single LLM step, dispatch by type."""
    from anysite.llm import get_api_key
    from anysite.llm.cache import LLMCache
    from anysite.llm.providers import create_provider

    # Resolve provider
    provider_name = step.provider or llm_config.default_provider
    if provider_name not in llm_config.providers:
        raise DatasetError(
            f"LLM provider '{provider_name}' not configured. Run 'anysite llm setup'."
        )
    pconfig = llm_config.providers[provider_name]
    api_key = get_api_key(pconfig)
    model = step.model or pconfig.default_model
    provider = create_provider(pconfig.provider, api_key, model=model)

    cache = LLMCache() if llm_config.cache_enabled else None

    try:
        if step.type == "enrich":
            return await _run_enrich_step(records, step, provider, cache, llm_config, quiet=quiet)
        elif step.type == "classify":
            return await _run_classify_step(records, step, provider, cache, llm_config, quiet=quiet)
        elif step.type == "summarize":
            return await _run_summarize_step(records, step, provider, cache, llm_config, quiet=quiet)
        elif step.type == "generate":
            return await _run_generate_step(records, step, provider, cache, llm_config, quiet=quiet)
        else:
            raise DatasetError(f"Unknown LLM step type: {step.type}")
    finally:
        await provider.close()
        if cache:
            cache.close()


# ── Step implementations ────────────────────────────────────────────────────


async def _run_enrich_step(
    records: list[dict[str, Any]],
    step: LLMStepConfig,
    provider: Any,
    cache: Any,
    llm_config: Any,
    *,
    quiet: bool = False,
) -> list[dict[str, Any]]:
    """Run an enrich step: extract structured attributes from each record."""
    from anysite.llm.models import StructuredSchema
    from anysite.llm.processor import LLMProcessor
    from anysite.llm.prompts import PromptBuilder

    field_specs = _parse_add_specs(step.add)
    field_descriptions = "\n".join(f"- {name}: {desc}" for name, desc in field_specs.items())
    variables = {"field_descriptions": field_descriptions}

    builder = PromptBuilder(builtin_key="enrich")
    system_prompt = "You are a data analyst. Extract the requested attributes precisely."

    # Build structured schema from specs
    properties, required = _build_schema_from_specs(field_specs)
    structured = StructuredSchema(
        name="enrich_output",
        schema={
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    )

    temperature = step.temperature if step.temperature is not None else llm_config.default_temperature
    max_tokens = step.max_tokens or llm_config.default_max_tokens

    processor = LLMProcessor(
        provider,
        cache=cache,
        rate_limit=llm_config.rate_limit,
        parallel=5,
        on_error="skip",
    )

    result = await processor.process_records(
        records,
        builder,
        system_prompt=system_prompt,
        structured=structured,
        batch_size=1,
        temperature=temperature,
        max_tokens=max_tokens,
        fields=step.fields or None,
        variables=variables,
    )

    _log_stats(result, step, quiet)
    return _merge_results(records, result, list(field_specs.keys()))


async def _run_classify_step(
    records: list[dict[str, Any]],
    step: LLMStepConfig,
    provider: Any,
    cache: Any,
    llm_config: Any,
    *,
    quiet: bool = False,
) -> list[dict[str, Any]]:
    """Run a classify step: categorize each record."""
    from anysite.llm.models import StructuredSchema
    from anysite.llm.processor import LLMProcessor
    from anysite.llm.prompts import BUILTIN_PROMPTS, PromptBuilder

    output_col = step.output_column or "category"
    system_prompt = "You are a data classifier. Be precise and consistent."
    categories = step.categories or "auto"

    # Auto-detect categories if not provided
    if step.categories is None:
        if not quiet:
            from anysite.output.console import print_info

            print_info("  Auto-detecting categories from first 20 records...")

        auto_builder = PromptBuilder(template=BUILTIN_PROMPTS["classify_auto_detect"])
        auto_proc = LLMProcessor(provider, cache=cache, parallel=1, on_error="stop")
        auto_result = await auto_proc.process_records(
            records[:20],
            auto_builder,
            system_prompt=system_prompt,
            batch_size=20,
            temperature=0.0,
            max_tokens=500,
        )
        if auto_result.results:
            detected = auto_result.results[0]
            categories = detected.get("_llm_response", str(detected))
            if not quiet:
                from anysite.output.console import print_info

                print_info(f"  Detected categories: {categories}")

    variables: dict[str, Any] = {"categories": categories}
    builder = PromptBuilder(builtin_key="classify")

    # Structured schema for batch classification
    result_item = {
        "type": "object",
        "properties": {
            "index": {"type": "integer"},
            "category": {"type": "string"},
            "confidence": {"type": "number"},
        },
        "required": ["index", "category", "confidence"],
        "additionalProperties": False,
    }
    structured = StructuredSchema(
        name="classify_output",
        schema={
            "type": "object",
            "properties": {
                "results": {"type": "array", "items": result_item},
            },
            "required": ["results"],
            "additionalProperties": False,
        },
    )

    temperature = step.temperature if step.temperature is not None else llm_config.default_temperature
    max_tokens = step.max_tokens or llm_config.default_max_tokens

    processor = LLMProcessor(
        provider,
        cache=cache,
        rate_limit=llm_config.rate_limit,
        parallel=5,
        on_error="skip",
    )

    result = await processor.process_records(
        records,
        builder,
        system_prompt=system_prompt,
        structured=structured,
        batch_size=5,
        temperature=temperature,
        max_tokens=max_tokens,
        fields=step.fields or None,
        variables=variables,
    )

    _log_stats(result, step, quiet)

    # Merge classify results into records
    confidence_col = f"{output_col}_confidence"
    for i, rec in enumerate(records):
        if i < len(result.results):
            res = result.results[i]
            rec[output_col] = res.get("category")
            rec[confidence_col] = res.get("confidence")
        else:
            rec[output_col] = None
            rec[confidence_col] = None

    return records


async def _run_summarize_step(
    records: list[dict[str, Any]],
    step: LLMStepConfig,
    provider: Any,
    cache: Any,
    llm_config: Any,
    *,
    quiet: bool = False,
) -> list[dict[str, Any]]:
    """Run a summarize step: generate a concise summary per record."""
    from anysite.llm.models import StructuredSchema
    from anysite.llm.processor import LLMProcessor
    from anysite.llm.prompts import PromptBuilder

    output_col = step.output_column or "summary"
    builder = PromptBuilder(builtin_key="summarize")
    system_prompt = "You are a data analyst. Produce concise summaries."
    variables = {"max_length": str(step.max_length)}

    structured = StructuredSchema(
        name="summarize_output",
        schema={
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
            "additionalProperties": False,
        },
    )

    temperature = step.temperature if step.temperature is not None else llm_config.default_temperature
    max_tokens = step.max_tokens or llm_config.default_max_tokens

    processor = LLMProcessor(
        provider,
        cache=cache,
        rate_limit=llm_config.rate_limit,
        parallel=5,
        on_error="skip",
    )

    result = await processor.process_records(
        records,
        builder,
        system_prompt=system_prompt,
        structured=structured,
        batch_size=1,
        temperature=temperature,
        max_tokens=max_tokens,
        fields=step.fields or None,
        variables=variables,
    )

    _log_stats(result, step, quiet)

    for i, rec in enumerate(records):
        if i < len(result.results):
            rec[output_col] = result.results[i].get("summary")
        else:
            rec[output_col] = None

    return records


async def _run_generate_step(
    records: list[dict[str, Any]],
    step: LLMStepConfig,
    provider: Any,
    cache: Any,
    llm_config: Any,
    *,
    quiet: bool = False,
) -> list[dict[str, Any]]:
    """Run a generate step: produce text from a custom prompt template."""
    from anysite.llm.models import StructuredSchema
    from anysite.llm.processor import LLMProcessor
    from anysite.llm.prompts import PromptBuilder

    output_col = step.output_column or "text"
    builder = PromptBuilder(template=step.prompt)
    system_prompt = "You are a helpful assistant. Generate the requested content."

    structured = StructuredSchema(
        name="generate_output",
        schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
    )

    # Generate defaults to higher temperature
    temperature = step.temperature if step.temperature is not None else 0.7
    max_tokens = step.max_tokens or llm_config.default_max_tokens

    processor = LLMProcessor(
        provider,
        cache=cache,
        rate_limit=llm_config.rate_limit,
        parallel=5,
        on_error="skip",
    )

    result = await processor.process_records(
        records,
        builder,
        system_prompt=system_prompt,
        structured=structured,
        batch_size=1,
        temperature=temperature,
        max_tokens=max_tokens,
        fields=step.fields or None,
    )

    _log_stats(result, step, quiet)

    for i, rec in enumerate(records):
        if i < len(result.results):
            rec[output_col] = result.results[i].get("text")
        else:
            rec[output_col] = None

    return records


# ── Helpers ─────────────────────────────────────────────────────────────────


def _parse_add_specs(specs: list[str]) -> dict[str, str]:
    """Parse add field specs like 'sentiment:positive/negative/neutral'."""
    result: dict[str, str] = {}
    for spec in specs:
        if ":" not in spec:
            raise DatasetError(
                f"Invalid LLM enrich spec '{spec}', expected 'name:type_or_values'"
            )
        name, _, type_spec = spec.partition(":")
        result[name.strip()] = type_spec.strip()
    return result


def _build_schema_from_specs(
    field_specs: dict[str, str],
) -> tuple[dict[str, Any], list[str]]:
    """Build JSON Schema properties and required list from add specs."""
    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, spec in field_specs.items():
        if "/" in spec:
            options = [s.strip() for s in spec.split("/")]
            properties[name] = {"type": "string", "enum": options}
        elif spec == "string":
            properties[name] = {"type": "string"}
        elif spec == "integer" or "-" in spec:
            properties[name] = {"type": "integer"}
        elif spec == "number":
            properties[name] = {"type": "number"}
        elif spec == "boolean":
            properties[name] = {"type": "boolean"}
        else:
            properties[name] = {"type": "string"}
        required.append(name)
    return properties, required


def _merge_results(
    records: list[dict[str, Any]],
    result: Any,
    output_keys: list[str],
) -> list[dict[str, Any]]:
    """Merge LLM-produced fields back into original records."""
    for i, rec in enumerate(records):
        if i < len(result.results):
            res = result.results[i]
            for key in output_keys:
                rec[key] = res.get(key)
        else:
            for key in output_keys:
                rec[key] = None
    return records


def _set_none_fields(records: list[dict[str, Any]], step: LLMStepConfig) -> None:
    """Set enriched fields to None when a step fails entirely."""
    if step.type == "enrich":
        specs = _parse_add_specs(step.add)
        keys = list(specs.keys())
    elif step.type == "classify":
        col = step.output_column or "category"
        keys = [col, f"{col}_confidence"]
    elif step.type == "summarize":
        keys = [step.output_column or "summary"]
    elif step.type == "generate":
        keys = [step.output_column or "text"]
    else:
        return
    for rec in records:
        for key in keys:
            rec[key] = None


def _log_stats(result: Any, step: LLMStepConfig, quiet: bool) -> None:
    """Log LLM processing statistics."""
    if quiet:
        return
    try:
        from anysite.output.console import print_info

        print_info(
            f"  LLM {step.type}: {result.llm_calls} calls, "
            f"{result.cache_hits} cache hits, "
            f"{result.total_input_tokens} in / {result.total_output_tokens} out tokens"
        )
        if result.errors:
            from anysite.output.console import print_warning

            print_warning(f"  {len(result.errors)} LLM errors (skipped)")
    except ImportError:
        pass
