"""Web parsing CLI commands."""

from typing import Annotated

import typer

from anysite.api.endpoints import WEB_PARSE, WEB_SITEMAP
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
    help="Web page parsing",
    no_args_is_help=True,
)


@app.command("parse")
def parse(
    url: Annotated[str, typer.Argument(help="URL to parse")] = "",
    format: FormatOption = OutputFormat.JSON,
    fields: FieldsOption = None,
    output: OutputOption = None,
    quiet: QuietOption = False,
    only_main_content: Annotated[
        bool,
        typer.Option("--only-main-content", help="Extract only main content (heuristic)"),
    ] = False,
    extract_contacts: Annotated[
        bool,
        typer.Option("--extract-contacts", help="Extract links, emails, and phone numbers"),
    ] = False,
    social_links_only: Annotated[
        bool,
        typer.Option("--social-links-only", help="Only extract social media links"),
    ] = False,
    strip_all_tags: Annotated[
        bool,
        typer.Option("--strip-tags", help="Remove all HTML tags, return plain text"),
    ] = False,
    include_tags: Annotated[
        str | None,
        typer.Option("--include-tags", help="CSS selectors to include (comma-separated)"),
    ] = None,
    exclude_tags: Annotated[
        str | None,
        typer.Option("--exclude-tags", help="CSS selectors to exclude (comma-separated)"),
    ] = None,
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
    """Parse and clean HTML from web page.

    \b
    Examples:
      anysite web parse https://example.com
      anysite web parse https://blog.example.com --only-main-content
      anysite web parse https://company.com --extract-contacts
      anysite web parse https://company.com --social-links-only
      anysite web parse https://example.com --strip-tags
      anysite web parse --from-file urls.txt --parallel 5
    """
    extra: dict[str, str | bool | list[str]] = {}
    if only_main_content:
        extra["only_main_content"] = True
    if extract_contacts:
        extra["extract_contacts"] = True
    if social_links_only:
        extra["social_links_only"] = True
    if strip_all_tags:
        extra["strip_all_tags"] = True
    if include_tags:
        extra["include_tags"] = [t.strip() for t in include_tags.split(",")]
    if exclude_tags:
        extra["exclude_tags"] = [t.strip() for t in exclude_tags.split(",")]

    payload: dict = {"url": url, **extra} if url else {**extra}

    run_single_command(
        endpoint=WEB_PARSE.path,
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
        input_key="url",
        extra_payload=extra if extra else None,
    )


@app.command("sitemap")
def sitemap(
    url: Annotated[str, typer.Argument(help="Website URL to get sitemap from")],
    count: Annotated[
        int,
        typer.Option("--count", "-c", help="Maximum number of URLs to return (max 1000)"),
    ] = 100,
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
    """Get sitemap URLs from a website.

    \b
    Examples:
      anysite web sitemap https://example.com
      anysite web sitemap https://example.com --count 500
      anysite web sitemap https://blog.example.com --format csv
      anysite web sitemap https://example.com --count 500 --stream -o urls.jsonl
    """
    run_search_command(
        endpoint=WEB_SITEMAP.path,
        payload={"url": url, "count": count},
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
