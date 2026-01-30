"""Twitter/X CLI commands."""

from typing import Annotated

import typer

from anysite.api.endpoints import (
    TWITTER_SEARCH_POSTS,
    TWITTER_SEARCH_USERS,
    TWITTER_USER,
    TWITTER_USER_POSTS,
)
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
    help="Twitter/X data extraction",
    no_args_is_help=True,
)


@app.command("user")
def user(
    username: Annotated[str, typer.Argument(help="Twitter username (without @)")] = "",
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
    """Get Twitter user profile.

    \b
    Examples:
      anysite twitter user elonmusk
      anysite twitter user openai --format table
      anysite twitter user elonmusk --fields "name,followers_count,description"
      anysite twitter user --from-file usernames.txt --parallel 5
    """
    payload = {"user": username} if username else {}

    run_single_command(
        endpoint=TWITTER_USER.path,
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
        input_key="user",
    )


@app.command("user-posts")
def user_posts(
    username: Annotated[str, typer.Argument(help="Twitter username")],
    count: Annotated[
        int,
        typer.Option("--count", "-c", help="Number of posts to fetch (max 1000)"),
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
    """Get Twitter user posts (tweets).

    \b
    Examples:
      anysite twitter user-posts elonmusk --count 20
      anysite twitter user-posts openai --format jsonl
      anysite twitter user-posts elonmusk --count 500 --stream -o tweets.jsonl
    """
    run_search_command(
        endpoint=TWITTER_USER_POSTS.path,
        payload={"user": username, "count": count},
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


@app.command("search-posts")
def search_posts(
    query: Annotated[
        str,
        typer.Option("--query", "-q", help="Search query"),
    ],
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
    """Search Twitter posts.

    \b
    Examples:
      anysite twitter search-posts --query "AI agents" --count 50
      anysite twitter search-posts --query "#startup" --format table
      anysite twitter search-posts --query "AI" --count 500 --stream -o posts.jsonl
    """
    run_search_command(
        endpoint=TWITTER_SEARCH_POSTS.path,
        payload={"query": query, "count": count},
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


@app.command("search-users")
def search_users(
    query: Annotated[
        str,
        typer.Option("--query", "-q", help="Search query"),
    ],
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
    """Search Twitter users.

    \b
    Examples:
      anysite twitter search-users --query "AI researcher" --count 20
      anysite twitter search-users --query "startup founder" --format table
      anysite twitter search-users --query "ML" --count 500 --stream -o users.jsonl
    """
    run_search_command(
        endpoint=TWITTER_SEARCH_USERS.path,
        payload={"query": query, "count": count},
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
