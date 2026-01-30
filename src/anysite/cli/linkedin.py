"""LinkedIn CLI commands."""

from typing import Annotated

import typer

from anysite.api.endpoints import (
    LINKEDIN_COMPANY,
    LINKEDIN_COMPANY_EMPLOYEES,
    LINKEDIN_COMPANY_POSTS,
    LINKEDIN_SEARCH_POSTS,
    LINKEDIN_SEARCH_USERS,
    LINKEDIN_USER,
    LINKEDIN_USER_POSTS,
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
    help="LinkedIn data extraction",
    no_args_is_help=True,
)


@app.command("user")
def user(
    username: Annotated[str, typer.Argument(help="LinkedIn username or profile URL")] = "",
    format: FormatOption = OutputFormat.JSON,
    fields: FieldsOption = None,
    output: OutputOption = None,
    quiet: QuietOption = False,
    with_experience: Annotated[
        bool,
        typer.Option("--with-experience/--no-experience", help="Include experience info"),
    ] = True,
    with_education: Annotated[
        bool,
        typer.Option("--with-education/--no-education", help="Include education info"),
    ] = True,
    with_skills: Annotated[
        bool,
        typer.Option("--with-skills/--no-skills", help="Include skills info"),
    ] = True,
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
    """Get LinkedIn user profile.

    \b
    Examples:
      anysite linkedin user satyanadella
      anysite linkedin user satyanadella --format table
      anysite linkedin user satyanadella --fields "name,headline,follower_count"
      anysite linkedin user "https://linkedin.com/in/satyanadella"
      anysite linkedin user --from-file usernames.txt --parallel 5
    """
    extra = {
        "with_experience": with_experience,
        "with_education": with_education,
        "with_skills": with_skills,
    }
    payload = {"user": username, **extra} if username else extra

    run_single_command(
        endpoint=LINKEDIN_USER.path,
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


@app.command("users")
def users_search(
    keywords: Annotated[
        str | None,
        typer.Option("--keywords", "-k", help="Search keywords"),
    ] = None,
    first_name: Annotated[
        str | None,
        typer.Option("--first-name", help="Filter by first name"),
    ] = None,
    last_name: Annotated[
        str | None,
        typer.Option("--last-name", help="Filter by last name"),
    ] = None,
    title: Annotated[
        str | None,
        typer.Option("--title", help="Filter by job title"),
    ] = None,
    company: Annotated[
        str | None,
        typer.Option("--company", help="Filter by current company"),
    ] = None,
    location: Annotated[
        str | None,
        typer.Option("--location", help="Filter by location"),
    ] = None,
    industry: Annotated[
        str | None,
        typer.Option("--industry", help="Filter by industry"),
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
    """Search LinkedIn users.

    \b
    Examples:
      anysite linkedin users --keywords "CTO fintech" --count 20
      anysite linkedin users --title "Director" --company "Google" --count 50
      anysite linkedin users --keywords "AI" --count 500 --stream -o results.jsonl
    """
    from anysite.output.console import print_error as _print_error

    if count < 1 or count > 1000:
        _print_error("Count must be between 1 and 1000")
        raise typer.Exit(1)

    payload: dict[str, str | int] = {"count": count}
    if keywords:
        payload["keywords"] = keywords
    if first_name:
        payload["first_name"] = first_name
    if last_name:
        payload["last_name"] = last_name
    if title:
        payload["title"] = title
    if company:
        payload["current_company"] = company
    if location:
        payload["location"] = location
    if industry:
        payload["industry"] = industry

    run_search_command(
        endpoint=LINKEDIN_SEARCH_USERS.path,
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


@app.command("company")
def company(
    company_name: Annotated[str, typer.Argument(help="Company name or URL")] = "",
    format: FormatOption = OutputFormat.JSON,
    fields: FieldsOption = None,
    output: OutputOption = None,
    quiet: QuietOption = False,
    # Phase 2
    exclude: ExcludeOption = None,
    compact: CompactOption = False,
    fields_preset: FieldsPresetOption = None,
    from_file: FromFileOption = None,
    stdin: StdinOption = False,
    parallel: ParallelOption = 1,
    delay: DelayOption = 0.0,
    on_error: OnErrorOption = ErrorHandling.STOP,
    rate_limit: RateLimitOption = None,
    progress: ProgressOption = None,
    stats: StatsOption = False,
    verbose: VerboseOption = False,
    append: AppendOption = False,
    output_dir: OutputDirOption = None,
    filename_template: FilenameTemplateOption = "{id}",
) -> None:
    """Get LinkedIn company information.

    \b
    Examples:
      anysite linkedin company anthropic
      anysite linkedin company "https://linkedin.com/company/anthropic"
      anysite linkedin company --from-file companies.txt --parallel 3
    """
    payload = {"company": company_name} if company_name else {}

    run_single_command(
        endpoint=LINKEDIN_COMPANY.path,
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


@app.command("company-employees")
def company_employees(
    company_name: Annotated[str, typer.Argument(help="Company name or URL")],
    count: Annotated[
        int,
        typer.Option("--count", "-c", help="Number of results"),
    ] = 10,
    keywords: Annotated[
        str | None,
        typer.Option("--keywords", "-k", help="Search keywords"),
    ] = None,
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
    """Get LinkedIn company employees.

    \b
    Examples:
      anysite linkedin company-employees anthropic --count 50
      anysite linkedin company-employees anthropic --keywords "engineer" --stream
    """
    payload: dict[str, str | int] = {"company": company_name, "count": count}
    if keywords:
        payload["keywords"] = keywords

    run_search_command(
        endpoint=LINKEDIN_COMPANY_EMPLOYEES.path,
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


@app.command("company-posts")
def company_posts(
    company_name: Annotated[str, typer.Argument(help="Company name or URL")],
    count: Annotated[
        int,
        typer.Option("--count", "-c", help="Number of results"),
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
    """Get LinkedIn company posts.

    \b
    Examples:
      anysite linkedin company-posts anthropic --count 20
      anysite linkedin company-posts anthropic --count 100 --stream
    """
    run_search_command(
        endpoint=LINKEDIN_COMPANY_POSTS.path,
        payload={"company": company_name, "count": count},
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


@app.command("posts")
def posts_search(
    keywords: Annotated[
        str,
        typer.Option("--keywords", "-k", help="Search keywords"),
    ],
    count: Annotated[
        int,
        typer.Option("--count", "-c", help="Number of results"),
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
    """Search LinkedIn posts.

    \b
    Examples:
      anysite linkedin posts --keywords "AI agents" --count 50
      anysite linkedin posts --keywords "startup" --stream -o posts.jsonl
    """
    run_search_command(
        endpoint=LINKEDIN_SEARCH_POSTS.path,
        payload={"keywords": keywords, "count": count},
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


@app.command("user-posts")
def user_posts(
    username: Annotated[str, typer.Argument(help="LinkedIn username")],
    count: Annotated[
        int,
        typer.Option("--count", "-c", help="Number of results"),
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
    """Get LinkedIn user posts.

    \b
    Examples:
      anysite linkedin user-posts satyanadella --count 20
      anysite linkedin user-posts satyanadella --count 100 --stream
    """
    run_search_command(
        endpoint=LINKEDIN_USER_POSTS.path,
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
