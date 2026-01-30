"""Y Combinator CLI commands."""

from typing import Annotated

import typer

from anysite.api.endpoints import YC_COMPANY, YC_SEARCH_COMPANIES, YC_SEARCH_FOUNDERS
from anysite.cli.executor import run_search_command, run_single_command
from anysite.cli.options import (
    AppendOption,
    CompactOption,
    DelayOption,
    ErrorHandling,
    ExcludeOption,
    FieldsOption,
    FieldsPresetOption,
    FilenameTemplateOption,
    FormatOption,
    FromFileOption,
    OnErrorOption,
    OutputDirOption,
    OutputOption,
    ParallelOption,
    ProgressOption,
    QuietOption,
    RateLimitOption,
    StatsOption,
    StdinOption,
    StreamOption,
    VerboseOption,
)
from anysite.output.formatters import OutputFormat

app = typer.Typer(
    help="Y Combinator data extraction",
    no_args_is_help=True,
)


@app.command("company")
def company(
    company_name: Annotated[str, typer.Argument(help="YC company name or URL")] = "",
    format: FormatOption = OutputFormat.JSON,
    fields: FieldsOption = None,
    output: OutputOption = None,
    quiet: QuietOption = False,
    # Phase 2: Enhanced fields
    exclude: ExcludeOption = None,
    compact: CompactOption = False,
    fields_preset: FieldsPresetOption = None,
    # Phase 2: Batch input
    from_file: FromFileOption = None,
    stdin: StdinOption = False,
    parallel: ParallelOption = 1,
    delay: DelayOption = 0.0,
    on_error: OnErrorOption = ErrorHandling.STOP,
    # Phase 2: Rate limiting
    rate_limit: RateLimitOption = None,
    # Phase 2: Progress & feedback
    progress: ProgressOption = None,
    stats: StatsOption = False,
    verbose: VerboseOption = False,
    # Phase 2: Output
    append: AppendOption = False,
    output_dir: OutputDirOption = None,
    filename_template: FilenameTemplateOption = "{id}",
) -> None:
    """Get Y Combinator company information.

    \b
    Examples:
      anysite yc company anthropic
      anysite yc company stripe --format table
      anysite yc company openai --fields "name,batch,one_liner,team_size"
      anysite yc company --from-file companies.txt --parallel 3
    """
    payload = {"company": company_name} if company_name else {}

    run_single_command(
        endpoint=YC_COMPANY.path,
        payload=payload,
        format=format,
        fields=fields,
        output=output,
        quiet=quiet,
        exclude=exclude,
        compact=compact,
        fields_preset=fields_preset,
        from_file=from_file,
        stdin=stdin,
        parallel=parallel,
        delay=delay,
        on_error=on_error,
        rate_limit=rate_limit,
        progress=progress,
        stats=stats,
        verbose=verbose,
        append=append,
        output_dir=output_dir,
        filename_template=filename_template,
        input_key="company",
    )


@app.command("search-companies")
def search_companies(
    query: Annotated[
        str | None,
        typer.Option("--query", help="Search query"),
    ] = None,
    batch: Annotated[
        str | None,
        typer.Option("--batch", "-b", help="YC batch (e.g., W24, S23)"),
    ] = None,
    industry: Annotated[
        str | None,
        typer.Option("--industry", help="Industry filter"),
    ] = None,
    count: Annotated[
        int,
        typer.Option("--count", "-c", help="Number of results (max 1000)"),
    ] = 10,
    format: FormatOption = OutputFormat.JSON,
    fields: FieldsOption = None,
    output: OutputOption = None,
    quiet: QuietOption = False,
    # Phase 2
    exclude: ExcludeOption = None,
    compact: CompactOption = False,
    fields_preset: FieldsPresetOption = None,
    stream: StreamOption = False,
    progress: ProgressOption = None,
    stats: StatsOption = False,
    verbose: VerboseOption = False,
    append: AppendOption = False,
) -> None:
    """Search Y Combinator companies.

    \b
    Examples:
      anysite yc search-companies --query "AI" --count 20
      anysite yc search-companies --batch W24 --industry "B2B"
      anysite yc search-companies --batch S23 --format table
      anysite yc search-companies --query "AI" --count 500 --stream -o companies.jsonl
    """
    payload: dict[str, str | int] = {"count": count}
    if query:
        payload["query"] = query
    if batch:
        payload["batch"] = batch
    if industry:
        payload["industry"] = industry

    run_search_command(
        endpoint=YC_SEARCH_COMPANIES.path,
        payload=payload,
        format=format,
        fields=fields,
        output=output,
        quiet=quiet,
        exclude=exclude,
        compact=compact,
        fields_preset=fields_preset,
        stream=stream,
        progress=progress,
        stats=stats,
        verbose=verbose,
        append=append,
    )


@app.command("search-founders")
def search_founders(
    query: Annotated[
        str | None,
        typer.Option("--query", help="Search query"),
    ] = None,
    batch: Annotated[
        str | None,
        typer.Option("--batch", "-b", help="YC batch (e.g., W24, S23)"),
    ] = None,
    count: Annotated[
        int,
        typer.Option("--count", "-c", help="Number of results (max 1000)"),
    ] = 10,
    format: FormatOption = OutputFormat.JSON,
    fields: FieldsOption = None,
    output: OutputOption = None,
    quiet: QuietOption = False,
    # Phase 2
    exclude: ExcludeOption = None,
    compact: CompactOption = False,
    fields_preset: FieldsPresetOption = None,
    stream: StreamOption = False,
    progress: ProgressOption = None,
    stats: StatsOption = False,
    verbose: VerboseOption = False,
    append: AppendOption = False,
) -> None:
    """Search Y Combinator founders.

    \b
    Examples:
      anysite yc search-founders --query "ML" --count 20
      anysite yc search-founders --batch W24 --format table
      anysite yc search-founders --query "AI" --count 500 --stream -o founders.jsonl
    """
    payload: dict[str, str | int] = {"count": count}
    if query:
        payload["query"] = query
    if batch:
        payload["batch"] = batch

    run_search_command(
        endpoint=YC_SEARCH_FOUNDERS.path,
        payload=payload,
        format=format,
        fields=fields,
        output=output,
        quiet=quiet,
        exclude=exclude,
        compact=compact,
        fields_preset=fields_preset,
        stream=stream,
        progress=progress,
        stats=stats,
        verbose=verbose,
        append=append,
    )
