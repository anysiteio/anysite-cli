"""Instagram CLI commands."""

from typing import Annotated

import typer

from anysite.api.endpoints import (
    INSTAGRAM_POST,
    INSTAGRAM_SEARCH_POSTS,
    INSTAGRAM_USER,
    INSTAGRAM_USER_POSTS,
    INSTAGRAM_USER_REELS,
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
    help="Instagram data extraction",
    no_args_is_help=True,
)


@app.command("user")
def user(
    username: Annotated[str, typer.Argument(help="Instagram username")] = "",
    format: FormatOption = OutputFormat.JSON,
    fields: FieldsOption = None,
    output: OutputOption = None,
    quiet: QuietOption = False,
    with_creation_date: Annotated[
        bool,
        typer.Option("--with-creation-date", help="Include account creation date"),
    ] = False,
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
    """Get Instagram user profile.

    \b
    Examples:
      anysite instagram user cristiano
      anysite instagram user nike --format table
      anysite instagram user cristiano --fields "username,follower_count,following_count"
      anysite instagram user --from-file usernames.txt --parallel 5
    """
    extra = {"with_creation_date": with_creation_date}
    payload = {"user": username, **extra} if username else extra

    run_single_command(
        endpoint=INSTAGRAM_USER.path,
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
        extra_payload=extra,
    )


@app.command("user-posts")
def user_posts(
    username: Annotated[str, typer.Argument(help="Instagram username")],
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
    """Get Instagram user posts.

    \b
    Examples:
      anysite instagram user-posts nike --count 20
      anysite instagram user-posts cristiano --format jsonl
      anysite instagram user-posts nike --count 100 --stream -o posts.jsonl
    """
    run_search_command(
        endpoint=INSTAGRAM_USER_POSTS.path,
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


@app.command("user-reels")
def user_reels(
    username: Annotated[str, typer.Argument(help="Instagram username")],
    count: Annotated[
        int,
        typer.Option("--count", "-c", help="Number of reels to fetch (max 1000)"),
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
    """Get Instagram user reels.

    \b
    Examples:
      anysite instagram user-reels nike --count 20
      anysite instagram user-reels nike --count 100 --stream
    """
    run_search_command(
        endpoint=INSTAGRAM_USER_REELS.path,
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


@app.command("post")
def post(
    post_id: Annotated[str, typer.Argument(help="Instagram post ID or URL")] = "",
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
    """Get Instagram post details.

    \b
    Examples:
      anysite instagram post CxYz123abc
      anysite instagram post "https://instagram.com/p/CxYz123abc"
      anysite instagram post --from-file post_ids.txt --parallel 5
    """
    payload = {"post": post_id} if post_id else {}

    run_single_command(
        endpoint=INSTAGRAM_POST.path,
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
        input_key="post",
    )


@app.command("search-posts")
def search_posts(
    query: Annotated[
        str,
        typer.Option("--query", "-q", help="Search query (hashtag or keyword)"),
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
    """Search Instagram posts by hashtag.

    \b
    Examples:
      anysite instagram search-posts --query "ai" --count 20
      anysite instagram search-posts --query "startup" --format table
      anysite instagram search-posts --query "ai" --count 500 --stream -o posts.jsonl
    """
    run_search_command(
        endpoint=INSTAGRAM_SEARCH_POSTS.path,
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
