"""CLI commands for the LLM analysis subsystem."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console

from anysite.llm import check_llm_deps
from anysite.llm.errors import ConfigError, LLMError

app = typer.Typer(
    help="LLM-powered analysis of collected data",
    invoke_without_command=True,
    epilog="Run 'anysite llm <command> --help' for details on each command.",
)


@app.callback(invoke_without_command=True)
def llm_callback(ctx: typer.Context) -> None:
    """Check LLM dependencies and handle discovery."""
    if ctx.invoked_subcommand is None:
        from anysite.cli.discovery import build_command_detail, is_pipe_mode

        if is_pipe_mode():
            import json

            typer.echo(json.dumps(build_command_detail("llm", ctx), indent=2))
            raise typer.Exit(0)
        typer.echo(ctx.get_help())
        raise typer.Exit(0)
    # Only check deps when an actual subcommand will run
    check_llm_deps()


# ── Helpers ──────────────────────────────────────────────────────────────────


def _load_dataset_config(path: Path) -> Any:
    """Load dataset config (requires [data] extra)."""
    from anysite.dataset import check_data_deps

    check_data_deps()

    from anysite.dataset.models import DatasetConfig

    if not path.exists():
        typer.echo(f"Error: dataset config not found: {path}", err=True)
        raise typer.Exit(1)
    try:
        return DatasetConfig.from_yaml(path)
    except Exception as e:
        typer.echo(f"Error parsing dataset config: {e}", err=True)
        raise typer.Exit(1) from None


def _read_source_records(config: Any, source_id: str) -> list[dict[str, Any]]:
    """Read all records from a dataset source's Parquet files."""
    from anysite.dataset.storage import get_source_dir, read_parquet

    base_path = config.storage_path()
    source_dir = get_source_dir(base_path, source_id)

    if not source_dir.exists():
        typer.echo(f"Error: no data for source '{source_id}'", err=True)
        raise typer.Exit(1)

    parquet_files = sorted(source_dir.glob("*.parquet"))
    if not parquet_files:
        typer.echo(f"Error: no parquet files for source '{source_id}'", err=True)
        raise typer.Exit(1)

    # Read the latest snapshot
    records = read_parquet(parquet_files[-1])
    return records


def _get_provider_and_cache(
    provider_name: str | None,
    model: str | None,
    no_cache: bool,
) -> tuple[Any, Any]:
    """Create LLM provider and optional cache from config."""
    from anysite.llm import get_api_key, load_llm_config
    from anysite.llm.cache import LLMCache
    from anysite.llm.providers import create_provider

    llm_config = load_llm_config()
    pname = provider_name or llm_config.default_provider

    if pname not in llm_config.providers:
        raise ConfigError(f"Provider '{pname}' not configured. Run 'anysite llm setup' first.")

    pconfig = llm_config.providers[pname]
    api_key = get_api_key(pconfig)
    provider = create_provider(pconfig.provider, api_key, model=model or pconfig.default_model)

    cache = LLMCache() if llm_config.cache_enabled and not no_cache else None
    return provider, cache


def _get_llm_config_defaults() -> tuple[float, int, str | None]:
    """Get default temperature, max_tokens, rate_limit from config."""
    try:
        from anysite.llm import load_llm_config

        cfg = load_llm_config()
        return cfg.default_temperature, cfg.default_max_tokens, cfg.rate_limit
    except ConfigError:
        return 0.0, 4096, "50/m"


def _output_results(
    data: list[dict[str, Any]],
    format: str = "json",
    output: Path | None = None,
    fields: str | None = None,
) -> None:
    """Output results using the existing formatter pipeline."""
    from anysite.cli.options import parse_fields
    from anysite.output.formatters import OutputFormat, format_output

    try:
        fmt = OutputFormat(format.lower())
    except ValueError:
        typer.echo(f"Error: invalid format '{format}', use json/jsonl/csv/table", err=True)
        raise typer.Exit(1) from None

    include_fields = parse_fields(fields)
    format_output(data, fmt, include_fields, output, quiet=False)


def _show_dry_run(prompt: str, system_prompt: str = "") -> None:
    """Show prompt without calling LLM."""
    console = Console()
    if system_prompt:
        console.print("[bold]System prompt:[/bold]")
        console.print(system_prompt)
        console.print()
    console.print("[bold]User prompt:[/bold]")
    console.print(prompt)


def _show_stats(result: Any, quiet: bool) -> None:
    """Show processing statistics."""
    if quiet:
        return
    console = Console()
    console.print(
        f"\n[bold]Stats:[/bold] "
        f"{result.llm_calls} LLM calls, "
        f"{result.cache_hits} cache hits, "
        f"{result.total_input_tokens} input tokens, "
        f"{result.total_output_tokens} output tokens"
    )
    if result.errors:
        console.print(f"[yellow]{len(result.errors)} errors[/yellow]")


def _read_prompt_file(prompt_file: Path | None) -> str | None:
    """Read prompt from file if specified."""
    if prompt_file is None:
        return None
    if not prompt_file.exists():
        typer.echo(f"Error: prompt file not found: {prompt_file}", err=True)
        raise typer.Exit(1)
    return prompt_file.read_text().strip()


# ── Commands ─────────────────────────────────────────────────────────────────


@app.command("setup")
def setup(
    provider_opt: Annotated[
        str | None,
        typer.Option("--provider", help="LLM provider: openai or anthropic"),
    ] = None,
    api_key_opt: Annotated[
        str | None,
        typer.Option("--api-key", help="API key value"),
    ] = None,
    api_key_env_opt: Annotated[
        str | None,
        typer.Option("--api-key-env", help="Environment variable name for API key"),
    ] = None,
    model_opt: Annotated[
        str | None,
        typer.Option("--model", help="Default model ID"),
    ] = None,
    no_test: Annotated[
        bool,
        typer.Option("--no-test", help="Skip connection test"),
    ] = False,
) -> None:
    """Configure LLM provider settings.

    \b
    Interactive (human):
      anysite llm setup

    \b
    Non-interactive (agent):
      anysite llm setup --provider openai --api-key sk-xxx --no-test
      anysite llm setup --provider anthropic --api-key-env ANTHROPIC_API_KEY
    """
    import os

    import yaml

    from anysite.cli.json_output import is_non_interactive
    from anysite.config.paths import ensure_config_dir, get_config_path
    from anysite.config.settings import load_yaml_config

    console = Console()

    _DEFAULTS: dict[str, tuple[str, str]] = {
        "openai": ("OPENAI_API_KEY", "gpt-4.1-mini"),
        "anthropic": ("ANTHROPIC_API_KEY", "claude-sonnet-4-5-20250514"),
    }

    non_interactive = is_non_interactive()

    # --- Resolve provider ---
    if non_interactive:
        if not provider_opt:
            typer.echo(
                "Error: --provider is required in non-interactive mode.\n"
                "  anysite llm setup --provider openai --api-key <key>",
                err=True,
            )
            raise typer.Exit(1)
        if provider_opt not in _DEFAULTS:
            typer.echo(
                f"Error: invalid provider '{provider_opt}'. Use 'openai' or 'anthropic'.",
                err=True,
            )
            raise typer.Exit(1)
        provider = provider_opt
    else:
        console.print("[bold]LLM Setup[/bold]\n")
        if provider_opt and provider_opt in _DEFAULTS:
            provider = provider_opt
        else:
            provider = typer.prompt(
                "Provider",
                default=provider_opt or "openai",
                type=typer.Choice(["openai", "anthropic"]),
            )

    default_env, default_model = _DEFAULTS[provider]

    # --- Resolve model ---
    if non_interactive:
        model = model_opt or default_model
    elif model_opt:
        model = model_opt
    else:
        model = typer.prompt("Default model", default=default_model)

    # --- Resolve API key ---
    api_key = api_key_opt or ""
    api_key_env = api_key_env_opt or ""

    if non_interactive:
        if not api_key and not api_key_env:
            typer.echo(
                "Error: --api-key or --api-key-env is required in non-interactive mode.\n"
                f"  anysite llm setup --provider {provider} --api-key <key>\n"
                f"  anysite llm setup --provider {provider} --api-key-env {default_env}",
                err=True,
            )
            raise typer.Exit(1)
    elif not api_key:
        api_key = typer.prompt(
            "API key (paste key or press Enter to use env var)",
            default="",
            hide_input=True,
        )
        if not api_key:
            api_key_env = api_key_env or typer.prompt(
                "API key environment variable", default=default_env,
            )
            if os.environ.get(api_key_env):
                console.print(f"[green]Found[/green] {api_key_env} in environment")
            else:
                console.print(
                    f"[yellow]Warning:[/yellow] {api_key_env} not set in environment. "
                    f"Set it before using LLM commands."
                )

    if not api_key_env and not api_key:
        api_key_env = api_key_env_opt or default_env

    # --- Connection test ---
    test_key = api_key or os.environ.get(api_key_env, "")

    if test_key and not no_test:
        should_test = non_interactive or typer.confirm("Test the connection?", default=True)
        if should_test:
            try:
                from anysite.llm.providers import create_provider

                p = create_provider(provider, test_key, model=model)
                from anysite.llm.models import LLMMessage

                async def _test() -> Any:
                    try:
                        return await p.complete(
                            [LLMMessage(role="user", content="Say 'ok'")],
                            max_tokens=10,
                        )
                    finally:
                        await p.close()

                result = asyncio.run(_test())
                if not non_interactive:
                    console.print(f"[green]Connection successful[/green] (model: {result.model})")
            except Exception as e:
                if non_interactive:
                    typer.echo(f"Error: connection test failed: {e}", err=True)
                    raise typer.Exit(1) from None
                console.print(f"[red]Connection failed:[/red] {e}")
                if not typer.confirm("Save configuration anyway?", default=False):
                    raise typer.Exit(1) from None

    # --- Write to config ---
    ensure_config_dir()
    config_path = get_config_path()

    config = load_yaml_config()
    llm_config = config.get("llm", {})
    llm_config["default_provider"] = provider
    providers = llm_config.get("providers", {})
    provider_data: dict[str, Any] = {
        "provider": provider,
        "default_model": model,
    }
    if api_key:
        provider_data["api_key"] = api_key
    if api_key_env:
        provider_data["api_key_env"] = api_key_env
    providers[provider] = provider_data
    llm_config["providers"] = providers
    llm_config.setdefault("cache_enabled", True)
    llm_config.setdefault("default_temperature", 0.0)
    llm_config.setdefault("default_max_tokens", 4096)
    llm_config.setdefault("rate_limit", "50/m")
    config["llm"] = llm_config

    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

    if non_interactive:
        typer.echo(f"Saved LLM config to {config_path}")
    else:
        console.print(f"\n[green]Saved[/green] LLM config to {config_path}")


@app.command("summarize")
def summarize(
    config_path: Annotated[Path, typer.Argument(help="Path to dataset.yaml")],
    source: Annotated[str, typer.Option("--source", "-s", help="Source to summarize")],
    # LLM options
    provider: Annotated[str | None, typer.Option("--provider", help="LLM provider")] = None,
    model: Annotated[str | None, typer.Option("--model", help="Model ID")] = None,
    parallel: Annotated[int, typer.Option("--parallel", "-j", help="Concurrent LLM calls")] = 5,
    rate_limit: Annotated[str | None, typer.Option("--rate-limit", help="Rate limit")] = None,
    temperature: Annotated[
        float | None, typer.Option("--temperature", help="LLM temperature")
    ] = None,
    max_tokens: Annotated[
        int | None, typer.Option("--max-tokens", help="Max response tokens")
    ] = None,
    no_cache: Annotated[bool, typer.Option("--no-cache", help="Skip cache lookup")] = False,
    # Output options
    format: Annotated[str, typer.Option("--format", "-f", help="Output format")] = "json",
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Write to file")] = None,
    fields: Annotated[
        str | None, typer.Option("--fields", help="Record fields to include in prompt")
    ] = None,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress progress")] = False,
    # Summarize-specific
    prompt: Annotated[str | None, typer.Option("--prompt", help="Custom prompt override")] = None,
    prompt_file: Annotated[
        Path | None, typer.Option("--prompt-file", help="Read prompt from file")
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Show prompt without calling LLM")
    ] = False,
    max_length: Annotated[int, typer.Option("--max-length", help="Max words in summary")] = 100,
    output_column: Annotated[
        str, typer.Option("--output-column", help="Column name for summary")
    ] = "summary",
) -> None:
    """Summarize each record in a dataset source using an LLM.

    \b
    Examples:
      anysite llm summarize dataset.yaml --source profiles --fields "name,headline" --format table
      anysite llm summarize dataset.yaml --source posts --fields "text" --output summaries.json
      anysite llm summarize dataset.yaml --source profiles --dry-run
    """
    config = _load_dataset_config(config_path)
    records = _read_source_records(config, source)

    file_prompt = _read_prompt_file(prompt_file)
    template = file_prompt or prompt
    from anysite.llm.prompts import PromptBuilder

    builder = PromptBuilder(template=template, builtin_key="summarize" if not template else None)

    system_prompt = "You are a data analyst. Produce concise summaries."
    variables = {"max_length": str(max_length)}

    if dry_run:
        field_list = [f.strip() for f in fields.split(",")] if fields else None
        from anysite.llm.prompts import filter_record_fields

        sample = filter_record_fields(records[0], field_list) if field_list else records[0]
        _show_dry_run(builder.build(sample, variables), system_prompt)
        return

    structured = _make_structured_schema(
        "summarize_output",
        {"summary": {"type": "string"}},
        ["summary"],
    )

    defaults = _get_llm_config_defaults()
    prov, cache = _get_provider_and_cache(provider, model, no_cache)

    from anysite.llm.processor import LLMProcessor

    processor = LLMProcessor(
        prov,
        cache=cache,
        rate_limit=rate_limit or defaults[2],
        parallel=parallel,
        on_error="skip",
    )

    async def _run() -> Any:
        try:
            return await processor.process_records(
                records,
                builder,
                system_prompt=system_prompt,
                structured=structured,
                batch_size=1,
                temperature=temperature if temperature is not None else defaults[0],
                max_tokens=max_tokens or defaults[1],
                no_cache=no_cache,
                fields=[f.strip() for f in fields.split(",")] if fields else None,
                variables=variables,
            )
        finally:
            await prov.close()

    try:
        result = asyncio.run(_run())
    except LLMError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from None

    # Rename _llm_response or summary field
    for r in result.results:
        if output_column != "summary" and "summary" in r:
            r[output_column] = r.pop("summary")

    _show_stats(result, quiet)
    _output_results(result.results, format, output)


@app.command("classify")
def classify(
    config_path: Annotated[Path, typer.Argument(help="Path to dataset.yaml")],
    source: Annotated[str, typer.Option("--source", "-s", help="Source to classify")],
    categories: Annotated[
        str | None,
        typer.Option("--categories", "-c", help="Comma-separated categories"),
    ] = None,
    # LLM options
    provider: Annotated[str | None, typer.Option("--provider", help="LLM provider")] = None,
    model: Annotated[str | None, typer.Option("--model", help="Model ID")] = None,
    parallel: Annotated[int, typer.Option("--parallel", "-j", help="Concurrent LLM calls")] = 5,
    rate_limit: Annotated[str | None, typer.Option("--rate-limit", help="Rate limit")] = None,
    temperature: Annotated[
        float | None, typer.Option("--temperature", help="LLM temperature")
    ] = None,
    max_tokens: Annotated[
        int | None, typer.Option("--max-tokens", help="Max response tokens")
    ] = None,
    no_cache: Annotated[bool, typer.Option("--no-cache", help="Skip cache lookup")] = False,
    # Output
    format: Annotated[str, typer.Option("--format", "-f", help="Output format")] = "json",
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Write to file")] = None,
    fields: Annotated[str | None, typer.Option("--fields", help="Record fields for prompt")] = None,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress progress")] = False,
    # Classify-specific
    prompt: Annotated[str | None, typer.Option("--prompt", help="Custom prompt")] = None,
    prompt_file: Annotated[
        Path | None, typer.Option("--prompt-file", help="Prompt from file")
    ] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show prompt only")] = False,
    multi: Annotated[
        bool, typer.Option("--multi", help="Allow multiple categories per record")
    ] = False,
    output_column: Annotated[str, typer.Option("--output-column", help="Column name")] = "category",
) -> None:
    """Classify records into categories using an LLM.

    \b
    Examples:
      anysite llm classify dataset.yaml --source posts --categories "positive,negative,neutral" --format table
      anysite llm classify dataset.yaml --source posts --fields "text,headline" --output classified.json
      anysite llm classify dataset.yaml --source profiles --dry-run
    """
    config = _load_dataset_config(config_path)
    records = _read_source_records(config, source)

    cat_list = categories or "auto"
    system_prompt = "You are a data classifier. Be precise and consistent."

    file_prompt = _read_prompt_file(prompt_file)
    template = file_prompt or prompt
    from anysite.llm.prompts import PromptBuilder

    variables: dict[str, Any] = {"categories": cat_list}
    if multi:
        variables["multi_note"] = "A record may belong to multiple categories."

    builder = PromptBuilder(template=template, builtin_key="classify" if not template else None)

    if dry_run:
        sample = records[:5]
        _show_dry_run(builder.build_for_batch(sample, variables), system_prompt)
        return

    # Auto-detect categories flag
    needs_auto_detect = categories is None and not template

    defaults = _get_llm_config_defaults()
    prov, cache = _get_provider_and_cache(provider, model, no_cache)

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

    from anysite.llm.processor import LLMProcessor

    async def _run() -> Any:
        try:
            # Auto-detect categories if not provided
            if needs_auto_detect:
                if not quiet:
                    Console().print("[dim]Auto-detecting categories from first 20 records...[/dim]")
                from anysite.llm.prompts import BUILTIN_PROMPTS

                auto_builder = PromptBuilder(template=BUILTIN_PROMPTS["classify_auto_detect"])
                auto_proc = LLMProcessor(prov, cache=cache, parallel=1, on_error="stop")
                auto_result = await auto_proc.process_records(
                    records[:20],
                    auto_builder,
                    system_prompt=system_prompt,
                    batch_size=20,
                    temperature=0.0,
                    max_tokens=500,
                    no_cache=no_cache,
                )
                if auto_result.results:
                    detected = auto_result.results[0]
                    cat_str = detected.get("_llm_response", str(detected))
                    if not quiet:
                        Console().print(f"[dim]Detected categories: {cat_str}[/dim]")
                    variables["categories"] = cat_str

            processor = LLMProcessor(
                prov,
                cache=cache,
                rate_limit=rate_limit or defaults[2],
                parallel=parallel,
                on_error="skip",
            )
            return await processor.process_records(
                records,
                builder,
                system_prompt=system_prompt,
                structured=structured,
                batch_size=5,
                temperature=temperature if temperature is not None else defaults[0],
                max_tokens=max_tokens or defaults[1],
                no_cache=no_cache,
                fields=[f.strip() for f in fields.split(",")] if fields else None,
                variables=variables,
            )
        finally:
            await prov.close()

    try:
        result = asyncio.run(_run())
    except LLMError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from None

    # Rename category column if needed
    for r in result.results:
        if output_column != "category" and "category" in r:
            r[output_column] = r.pop("category")

    _show_stats(result, quiet)
    _output_results(result.results, format, output)


@app.command("match")
def match(
    config_path: Annotated[Path, typer.Argument(help="Path to dataset.yaml")],
    source_a: Annotated[str, typer.Option("--source-a", help="First source")],
    source_b: Annotated[str, typer.Option("--source-b", help="Second source")],
    # LLM options
    provider: Annotated[str | None, typer.Option("--provider", help="LLM provider")] = None,
    model: Annotated[str | None, typer.Option("--model", help="Model ID")] = None,
    parallel: Annotated[int, typer.Option("--parallel", "-j", help="Concurrent LLM calls")] = 5,
    rate_limit: Annotated[str | None, typer.Option("--rate-limit", help="Rate limit")] = None,
    temperature: Annotated[
        float | None, typer.Option("--temperature", help="LLM temperature")
    ] = None,
    max_tokens: Annotated[
        int | None, typer.Option("--max-tokens", help="Max response tokens")
    ] = None,
    no_cache: Annotated[bool, typer.Option("--no-cache", help="Skip cache lookup")] = False,
    # Output
    format: Annotated[str, typer.Option("--format", "-f", help="Output format")] = "json",
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Write to file")] = None,
    fields_a: Annotated[str | None, typer.Option("--fields-a", help="Fields from source A")] = None,
    fields_b: Annotated[str | None, typer.Option("--fields-b", help="Fields from source B")] = None,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress progress")] = False,
    # Match-specific
    prompt: Annotated[str | None, typer.Option("--prompt", help="Custom prompt")] = None,
    prompt_file: Annotated[
        Path | None, typer.Option("--prompt-file", help="Prompt from file")
    ] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show prompt only")] = False,
    top_k: Annotated[int, typer.Option("--top-k", help="Max matches per source-a record")] = 3,
    threshold: Annotated[float, typer.Option("--threshold", help="Min match score")] = 0.5,
) -> None:
    """Match records between two dataset sources using an LLM.

    \b
    Examples:
      anysite llm match dataset.yaml --source-a profiles --source-b companies --top-k 3
      anysite llm match dataset.yaml --source-a profiles --source-b companies --threshold 0.7 --format table
    """
    config = _load_dataset_config(config_path)
    records_a = _read_source_records(config, source_a)
    records_b = _read_source_records(config, source_b)

    from anysite.llm.prompts import PromptBuilder, filter_record_fields

    file_prompt = _read_prompt_file(prompt_file)
    template = file_prompt or prompt

    system_prompt = "You are an expert at matching related records. Be precise with scores."

    if dry_run:
        variables = {
            "source_a_name": source_a,
            "source_b_name": source_b,
            "source_a_record": str(records_a[0]),
            "source_b_records": str(records_b[:3]),
        }
        if template:
            builder = PromptBuilder(template=template)
        else:
            builder = PromptBuilder(builtin_key="match")
        _show_dry_run(builder.build(records_a[0], variables), system_prompt)
        return

    defaults = _get_llm_config_defaults()
    prov, cache = _get_provider_and_cache(provider, model, no_cache)

    from anysite.llm.processor import LLMProcessor

    # For matching, we process one source-a record at a time with batches of source-b
    all_matches: list[dict[str, Any]] = []
    batch_size_b = 10

    processor = LLMProcessor(
        prov,
        cache=cache,
        rate_limit=rate_limit or defaults[2],
        parallel=parallel,
        on_error="skip",
    )

    builder = PromptBuilder(template=template) if template else PromptBuilder(builtin_key="match")

    field_list_a = [f.strip() for f in fields_a.split(",")] if fields_a else None
    field_list_b = [f.strip() for f in fields_b.split(",")] if fields_b else None

    structured = StructuredSchema(
        name="match_output",
        schema={
            "type": "object",
            "properties": {
                "matches": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "index": {"type": "integer"},
                            "score": {"type": "number"},
                            "reason": {"type": "string"},
                        },
                        "required": ["index", "score", "reason"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["matches"],
            "additionalProperties": False,
        },
    )

    total_input_tokens = 0
    total_output_tokens = 0
    total_calls = 0
    total_cache_hits = 0

    async def _run() -> list[dict[str, Any]]:
        nonlocal total_input_tokens, total_output_tokens, total_calls, total_cache_hits
        try:
            for rec_a in records_a:
                rec_a_filtered = (
                    filter_record_fields(rec_a, field_list_a) if field_list_a else rec_a
                )

                # Process in chunks of source_b
                for b_start in range(0, len(records_b), batch_size_b):
                    b_chunk = records_b[b_start : b_start + batch_size_b]
                    if field_list_b:
                        b_chunk = [filter_record_fields(r, field_list_b) for r in b_chunk]

                    variables = {
                        "source_a_name": source_a,
                        "source_b_name": source_b,
                        "source_a_record": str(rec_a_filtered),
                        "source_b_records": "\n".join(f"[{i}] {r}" for i, r in enumerate(b_chunk)),
                    }

                    result = await processor.process_records(
                        [rec_a_filtered],
                        builder,
                        system_prompt=system_prompt,
                        structured=structured,
                        batch_size=1,
                        temperature=temperature if temperature is not None else defaults[0],
                        max_tokens=max_tokens or defaults[1],
                        no_cache=no_cache,
                        variables=variables,
                    )

                    total_input_tokens += result.total_input_tokens
                    total_output_tokens += result.total_output_tokens
                    total_calls += result.llm_calls
                    total_cache_hits += result.cache_hits

                    for m in result.results:
                        score = m.get("score", 0)
                        if score >= threshold:
                            idx = m.get("index", 0)
                            actual_idx = b_start + idx
                            if actual_idx < len(records_b):
                                all_matches.append(
                                    {
                                        **rec_a,
                                        "matched_record": records_b[actual_idx],
                                        "score": score,
                                        "reason": m.get("reason", ""),
                                    }
                                )

            # Sort by score descending and limit to top_k
            all_matches.sort(key=lambda x: x.get("score", 0), reverse=True)
            return all_matches[: top_k * len(records_a)]
        finally:
            await prov.close()

    try:
        all_matches = asyncio.run(_run())
    except LLMError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from None

    if not quiet:
        Console().print(
            f"\n[bold]Stats:[/bold] {total_calls} LLM calls, "
            f"{total_cache_hits} cache hits, "
            f"{total_input_tokens} input tokens, "
            f"{total_output_tokens} output tokens"
        )

    _output_results(all_matches, format, output)


@app.command("deduplicate")
def deduplicate(
    config_path: Annotated[Path, typer.Argument(help="Path to dataset.yaml")],
    source: Annotated[str, typer.Option("--source", "-s", help="Source to deduplicate")],
    # LLM options
    provider: Annotated[str | None, typer.Option("--provider", help="LLM provider")] = None,
    model: Annotated[str | None, typer.Option("--model", help="Model ID")] = None,
    parallel: Annotated[int, typer.Option("--parallel", "-j", help="Concurrent LLM calls")] = 5,
    rate_limit: Annotated[str | None, typer.Option("--rate-limit", help="Rate limit")] = None,
    temperature: Annotated[
        float | None, typer.Option("--temperature", help="LLM temperature")
    ] = None,
    max_tokens: Annotated[
        int | None, typer.Option("--max-tokens", help="Max response tokens")
    ] = None,
    no_cache: Annotated[bool, typer.Option("--no-cache", help="Skip cache lookup")] = False,
    # Output
    format: Annotated[str, typer.Option("--format", "-f", help="Output format")] = "json",
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Write to file")] = None,
    fields: Annotated[str | None, typer.Option("--fields", help="Fields for comparison")] = None,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress progress")] = False,
    # Dedup-specific
    prompt: Annotated[str | None, typer.Option("--prompt", help="Custom prompt")] = None,
    prompt_file: Annotated[
        Path | None, typer.Option("--prompt-file", help="Prompt from file")
    ] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show prompt only")] = False,
    key: Annotated[str, typer.Option("--key", "-k", help="Field to use for blocking")] = "name",
    threshold: Annotated[
        float, typer.Option("--threshold", help="Min confidence for duplicate")
    ] = 0.8,
) -> None:
    """Find semantic duplicates in a dataset source using an LLM.

    \b
    Examples:
      anysite llm deduplicate dataset.yaml --source profiles --key name --threshold 0.8
      anysite llm deduplicate dataset.yaml --source profiles --key name --format table
    """
    config = _load_dataset_config(config_path)
    records = _read_source_records(config, source)

    from anysite.llm.prompts import PromptBuilder

    file_prompt = _read_prompt_file(prompt_file)
    template = file_prompt or prompt
    builder = PromptBuilder(template=template, builtin_key="deduplicate" if not template else None)

    system_prompt = "You are a data quality expert. Identify semantic duplicates."

    # Blocking pass: group by first 3 chars of key field
    blocks: dict[str, list[dict[str, Any]]] = {}
    for i, rec in enumerate(records):
        rec["_dedup_index"] = i
        key_val = str(rec.get(key, "")).lower()[:3]
        blocks.setdefault(key_val, []).append(rec)

    # Filter blocks with only 1 record
    blocks = {k: v for k, v in blocks.items() if len(v) > 1}

    if dry_run:
        if blocks:
            first_block = next(iter(blocks.values()))[:5]
            _show_dry_run(builder.build_for_batch(first_block), system_prompt)
        else:
            Console().print("[dim]No blocking groups found — no potential duplicates.[/dim]")
        return

    structured = StructuredSchema(
        name="dedup_output",
        schema={
            "type": "object",
            "properties": {
                "duplicates": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "ids": {"type": "array", "items": {"type": "integer"}},
                            "confidence": {"type": "number"},
                            "reason": {"type": "string"},
                        },
                        "required": ["ids", "confidence", "reason"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["duplicates"],
            "additionalProperties": False,
        },
    )

    defaults = _get_llm_config_defaults()
    prov, cache = _get_provider_and_cache(provider, model, no_cache)

    from anysite.llm.processor import LLMProcessor

    processor = LLMProcessor(
        prov,
        cache=cache,
        rate_limit=rate_limit or defaults[2],
        parallel=parallel,
        on_error="skip",
    )

    all_duplicates: list[dict[str, Any]] = []

    async def _run() -> list[dict[str, Any]]:
        try:
            for _block_key, block_records in blocks.items():
                # Process up to 20 records per block
                for i in range(0, len(block_records), 20):
                    chunk = block_records[i : i + 20]
                    result = await processor.process_records(
                        chunk,
                        builder,
                        system_prompt=system_prompt,
                        structured=structured,
                        batch_size=len(chunk),
                        temperature=temperature if temperature is not None else defaults[0],
                        max_tokens=max_tokens or defaults[1],
                        no_cache=no_cache,
                        fields=[f.strip() for f in fields.split(",")] if fields else None,
                    )

                    for dup in result.results:
                        conf = dup.get("confidence", 0)
                        if conf >= threshold:
                            all_duplicates.append(dup)
            return all_duplicates
        finally:
            await prov.close()

    try:
        all_duplicates = asyncio.run(_run())
    except LLMError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from None

    # Clean up temp index
    for rec in records:
        rec.pop("_dedup_index", None)

    if not quiet:
        Console().print(f"\n[bold]Found {len(all_duplicates)} duplicate groups[/bold]")

    _output_results(all_duplicates, format, output)


@app.command("enrich")
def enrich(
    config_path: Annotated[Path, typer.Argument(help="Path to dataset.yaml")],
    source: Annotated[str, typer.Option("--source", "-s", help="Source to enrich")],
    add: Annotated[
        list[str],
        typer.Option("--add", help="Field spec: 'name:type_or_values'"),
    ],
    # LLM options
    provider: Annotated[str | None, typer.Option("--provider", help="LLM provider")] = None,
    model: Annotated[str | None, typer.Option("--model", help="Model ID")] = None,
    parallel: Annotated[int, typer.Option("--parallel", "-j", help="Concurrent LLM calls")] = 5,
    rate_limit: Annotated[str | None, typer.Option("--rate-limit", help="Rate limit")] = None,
    temperature: Annotated[
        float | None, typer.Option("--temperature", help="LLM temperature")
    ] = None,
    max_tokens: Annotated[
        int | None, typer.Option("--max-tokens", help="Max response tokens")
    ] = None,
    no_cache: Annotated[bool, typer.Option("--no-cache", help="Skip cache lookup")] = False,
    # Output
    format: Annotated[str, typer.Option("--format", "-f", help="Output format")] = "json",
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Write to file")] = None,
    fields: Annotated[str | None, typer.Option("--fields", help="Fields for prompt")] = None,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress progress")] = False,
    # Enrich-specific
    prompt: Annotated[str | None, typer.Option("--prompt", help="Custom prompt")] = None,
    prompt_file: Annotated[
        Path | None, typer.Option("--prompt-file", help="Prompt from file")
    ] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show prompt only")] = False,
) -> None:
    """Enrich records with LLM-extracted attributes.

    \b
    Examples:
      anysite llm enrich dataset.yaml --source profiles \\
          --add "sentiment:positive/negative/neutral" \\
          --add "language:string" \\
          --add "quality_score:1-10"
    """
    config = _load_dataset_config(config_path)
    records = _read_source_records(config, source)

    # Parse --add specs
    field_specs = _parse_add_specs(add)
    field_descriptions = "\n".join(f"- {name}: {desc}" for name, desc in field_specs.items())

    file_prompt = _read_prompt_file(prompt_file)
    template = file_prompt or prompt
    from anysite.llm.prompts import PromptBuilder

    variables = {"field_descriptions": field_descriptions}
    builder = PromptBuilder(template=template, builtin_key="enrich" if not template else None)

    system_prompt = "You are a data analyst. Extract the requested attributes precisely."

    if dry_run:
        sample = records[0]
        _show_dry_run(builder.build(sample, variables), system_prompt)
        return

    # Build structured schema from specs
    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, spec in field_specs.items():
        if "/" in spec:
            # Enum: "positive/negative/neutral"
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

    structured = _make_structured_schema("enrich_output", properties, required)

    defaults = _get_llm_config_defaults()
    prov, cache = _get_provider_and_cache(provider, model, no_cache)

    from anysite.llm.processor import LLMProcessor

    processor = LLMProcessor(
        prov,
        cache=cache,
        rate_limit=rate_limit or defaults[2],
        parallel=parallel,
        on_error="skip",
    )

    async def _run() -> Any:
        try:
            return await processor.process_records(
                records,
                builder,
                system_prompt=system_prompt,
                structured=structured,
                batch_size=1,
                temperature=temperature if temperature is not None else defaults[0],
                max_tokens=max_tokens or defaults[1],
                no_cache=no_cache,
                fields=[f.strip() for f in fields.split(",")] if fields else None,
                variables=variables,
            )
        finally:
            await prov.close()

    try:
        result = asyncio.run(_run())
    except LLMError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from None

    _show_stats(result, quiet)
    _output_results(result.results, format, output)


@app.command("generate")
def generate(
    config_path: Annotated[Path, typer.Argument(help="Path to dataset.yaml")],
    source: Annotated[str, typer.Option("--source", "-s", help="Source to process")],
    prompt: Annotated[
        str | None, typer.Option("--prompt", help="Prompt with {field} placeholders")
    ] = None,
    prompt_file: Annotated[
        Path | None, typer.Option("--prompt-file", help="Prompt from file")
    ] = None,
    # LLM options
    provider: Annotated[str | None, typer.Option("--provider", help="LLM provider")] = None,
    model: Annotated[str | None, typer.Option("--model", help="Model ID")] = None,
    parallel: Annotated[int, typer.Option("--parallel", "-j", help="Concurrent LLM calls")] = 5,
    rate_limit: Annotated[str | None, typer.Option("--rate-limit", help="Rate limit")] = None,
    temperature: Annotated[
        float | None, typer.Option("--temperature", help="LLM temperature")
    ] = None,
    max_tokens: Annotated[
        int | None, typer.Option("--max-tokens", help="Max response tokens")
    ] = None,
    no_cache: Annotated[bool, typer.Option("--no-cache", help="Skip cache lookup")] = False,
    # Output
    format: Annotated[str, typer.Option("--format", "-f", help="Output format")] = "json",
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Write to file")] = None,
    fields: Annotated[str | None, typer.Option("--fields", help="Fields for prompt")] = None,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress progress")] = False,
    # Generate-specific
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show prompt only")] = False,
    output_column: Annotated[str, typer.Option("--output-column", help="Column name")] = "text",
) -> None:
    """Generate text for each record using an LLM with a custom prompt.

    \b
    Examples:
      anysite llm generate dataset.yaml --source profiles \\
          --prompt "Write a LinkedIn message for {name} who works as {headline}" \\
          --temperature 0.7
    """
    file_prompt = _read_prompt_file(prompt_file)
    template = file_prompt or prompt
    if not template:
        typer.echo("Error: --prompt or --prompt-file is required for generate", err=True)
        raise typer.Exit(1)

    config = _load_dataset_config(config_path)
    records = _read_source_records(config, source)

    from anysite.llm.prompts import PromptBuilder

    builder = PromptBuilder(template=template)
    system_prompt = "You are a helpful assistant. Generate the requested content."

    if dry_run:
        _show_dry_run(builder.build(records[0]), system_prompt)
        return

    structured = _make_structured_schema(
        "generate_output",
        {"text": {"type": "string"}},
        ["text"],
    )

    defaults = _get_llm_config_defaults()
    default_temp = 0.7  # Generation defaults to higher temperature
    prov, cache = _get_provider_and_cache(provider, model, no_cache)

    from anysite.llm.processor import LLMProcessor

    processor = LLMProcessor(
        prov,
        cache=cache,
        rate_limit=rate_limit or defaults[2],
        parallel=parallel,
        on_error="skip",
    )

    async def _run() -> Any:
        try:
            return await processor.process_records(
                records,
                builder,
                system_prompt=system_prompt,
                structured=structured,
                batch_size=1,
                temperature=temperature if temperature is not None else default_temp,
                max_tokens=max_tokens or defaults[1],
                no_cache=no_cache,
                fields=[f.strip() for f in fields.split(",")] if fields else None,
            )
        finally:
            await prov.close()

    try:
        result = asyncio.run(_run())
    except LLMError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from None

    # Rename text field if needed
    for r in result.results:
        if output_column != "text" and "text" in r:
            r[output_column] = r.pop("text")

    _show_stats(result, quiet)
    _output_results(result.results, format, output)


@app.command("cache-stats")
def cache_stats(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as machine-readable JSON"),
    ] = False,
) -> None:
    """Show LLM cache statistics.

    \b
    Examples:
      anysite llm cache-stats
      anysite llm cache-stats --json
    """
    from anysite.cli.json_output import resolve_json_output

    json_output = resolve_json_output(json_output)

    from anysite.llm.cache import LLMCache

    cache = LLMCache()
    stats = cache.stats()
    cache.close()

    hints = [
        ("Clear cache", "anysite llm cache-clear"),
        ("Reconfigure LLM", "anysite llm setup"),
    ]

    if json_output:
        from anysite.cli.json_output import json_response

        json_response(stats, hints=hints, command="anysite llm cache-stats")
        return

    console = Console()
    console.print("[bold]LLM Cache Statistics[/bold]")
    console.print(f"  Entries:        {stats['entries']}")
    console.print(f"  Input tokens:   {stats['total_input_tokens']:,}")
    console.print(f"  Output tokens:  {stats['total_output_tokens']:,}")

    from anysite.cli.json_output import print_hints

    print_hints(hints)


@app.command("cache-clear")
def cache_clear(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as machine-readable JSON"),
    ] = False,
) -> None:
    """Clear all LLM cache entries.

    \b
    Examples:
      anysite llm cache-clear
      anysite llm cache-clear --json
    """
    from anysite.cli.json_output import resolve_json_output

    json_output = resolve_json_output(json_output)

    from anysite.llm.cache import LLMCache

    cache = LLMCache()
    count = cache.clear()
    cache.close()

    hints = [
        ("View cache stats", "anysite llm cache-stats"),
        ("Run analysis", "anysite llm summarize <dataset.yaml> --source <source>"),
    ]

    if json_output:
        from anysite.cli.json_output import json_response

        json_response({"cleared": count}, hints=hints, command="anysite llm cache-clear")
        return

    Console().print(f"[green]Cleared[/green] {count} cache entries")

    from anysite.cli.json_output import print_hints

    print_hints(hints)


# ── Internal helpers ─────────────────────────────────────────────────────────


def _make_structured_schema(
    name: str,
    properties: dict[str, Any],
    required: list[str],
) -> StructuredSchema:
    """Create a StructuredSchema for structured output."""
    from anysite.llm.models import StructuredSchema as SS

    return SS(
        name=name,
        schema={
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    )


def _parse_add_specs(specs: list[str]) -> dict[str, str]:
    """Parse --add field specs like 'sentiment:positive/negative/neutral'."""
    result: dict[str, str] = {}
    for spec in specs:
        if ":" not in spec:
            typer.echo(
                f"Error: invalid --add spec '{spec}', expected 'name:type_or_values'",
                err=True,
            )
            raise typer.Exit(1)
        name, _, type_spec = spec.partition(":")
        result[name.strip()] = type_spec.strip()
    return result


# Re-import for type annotations used in the module
from anysite.llm.models import StructuredSchema  # noqa: E402
