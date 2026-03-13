"""Structured changelog for AI agent discovery.

Each release entry includes a version, date, and categorized changes.
Agents use ``anysite changelog`` or the discovery payload ``whats_new``
key to learn about new capabilities after upgrades.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ChangeEntry:
    """A single changelog entry for a version."""

    version: str
    date: str
    changes: list[Change] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "date": self.date,
            "changes": [c.to_dict() for c in self.changes],
        }


@dataclass(frozen=True)
class Change:
    """One change within a release."""

    category: str  # "added", "changed", "fixed", "removed"
    summary: str
    detail: str | None = None
    example: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"category": self.category, "summary": self.summary}
        if self.detail:
            d["detail"] = self.detail
        if self.example:
            d["example"] = self.example
        return d


# ── Changelog entries (newest first) ─────────────────────────────────────────

CHANGELOG: list[ChangeEntry] = [
    ChangeEntry(
        version="0.3.23",
        date="2026-03-13",
        changes=[
            Change(
                category="fixed",
                summary="OpenAI provider uses max_completion_tokens for GPT-4.1+/GPT-5+/o-series models",
            ),
            Change(
                category="fixed",
                summary="Anthropic provider uses tool_use for reliable structured output",
                detail=(
                    "Anthropic models now use tool_use API instead of system prompt injection "
                    "for structured output. Fixes empty results with enrich/classify/summarize. "
                    "Also adds markdown code fence stripping as fallback for JSON parsing."
                ),
            ),
            Change(
                category="added",
                summary="SQL sources without connection query dataset Parquet files via DuckDB",
                detail=(
                    "When 'connection' is omitted from a type: sql source, the query runs "
                    "against DuckDB with all previously-collected sources registered as views "
                    "by their source id. Enables cross-source JOINs within the dataset pipeline."
                ),
                example=(
                    "- id: combined\n"
                    "  type: sql\n"
                    "  query: |\n"
                    "    SELECT u.*, c.description\n"
                    "    FROM user_profiles u\n"
                    "    LEFT JOIN company_profiles c ON ..."
                ),
            ),
        ],
    ),
    ChangeEntry(
        version="0.3.20",
        date="2026-03-10",
        changes=[
            Change(
                category="added",
                summary="Implicit array traversal in dependency.field extraction",
                detail=(
                    "Dot-notation paths like 'current_companies.company.urn.value' now "
                    "automatically traverse array elements. No need for [0] or [*] syntax — "
                    "all values from all elements are collected and flattened."
                ),
            ),
            Change(
                category="fixed",
                summary="Validator allows deep nested dependency.field paths beyond schema depth",
            ),
        ],
    ),
    ChangeEntry(
        version="0.3.19",
        date="2026-03-09",
        changes=[
            Change(
                category="fixed",
                summary="Search matches compound words (e.g. 'webpage' finds 'web' + 'page')",
            ),
            Change(
                category="added",
                summary="Usage instructions in describe --search results",
                detail=(
                    "Search results now include a `usage` key with concise instructions "
                    "explaining how to interpret matches, upstream, downstream, chaining, "
                    "and next steps. Makes search output self-documenting for agents."
                ),
            ),
            Change(
                category="added",
                summary="Graph-based endpoint dependency search in describe --search",
                detail=(
                    "Search now returns matched endpoints plus upstream providers "
                    "and downstream consumers. Shows which endpoints produce IDs that "
                    "other endpoints need, enabling automatic pipeline discovery."
                ),
                example='anysite describe --search "linkedin comments"',
            ),
            Change(
                category="added",
                summary="Endpoint connections in single endpoint describe",
                detail=(
                    "anysite describe <endpoint> now shows upstream and downstream "
                    "connections when graph cache is available."
                ),
            ),
            Change(
                category="changed",
                summary="schema update now builds dependency graph alongside schema cache",
                detail=(
                    "anysite schema update fetches the spec once, builds both schema.json "
                    "and graph.json. Graph enables dependency-aware search."
                ),
            ),
            Change(
                category="removed",
                summary="Removed synonym-based keyword search (replaced by graph search)",
            ),
        ],
    ),
    ChangeEntry(
        version="0.3.18",
        date="2026-03-06",
        changes=[
            Change(
                category="added",
                summary="anysite changelog command for agent feature discovery",
                detail=(
                    "Agents can run 'anysite changelog' or 'anysite changelog --since 0.3.17' "
                    "to discover new features after upgrades. Discovery payload now includes "
                    "'whats_new' with latest release highlights."
                ),
                example="anysite changelog --since 0.3.17 --json",
            ),
            Change(
                category="added",
                summary="whats_new key in discovery payload",
                detail=(
                    "The discovery payload (echo '' | anysite) now includes a 'whats_new' key "
                    "with the latest release version, date, and highlight summaries."
                ),
            ),
        ],
    ),
    ChangeEntry(
        version="0.3.17",
        date="2026-03-05",
        changes=[
            Change(
                category="added",
                summary="SQL source type for dataset pipelines (type: sql)",
                detail=(
                    "Run SQL queries against named database connections "
                    "(from 'anysite db add') and feed results into the pipeline. "
                    "Downstream sources can depend on SQL output for batch API enrichment."
                ),
                example=(
                    "sources:\n"
                    "  - id: billing_users\n"
                    "    type: sql\n"
                    "    connection: billing\n"
                    '    query: "SELECT name, email FROM subscriptions WHERE status = \'inactive\'"'
                ),
            ),
        ],
    ),
    ChangeEntry(
        version="0.3.16",
        date="2026-02-28",
        changes=[
            Change(
                category="added",
                summary="--format parquet for db query export",
            ),
            Change(
                category="added",
                summary="{{date}} output templates for db query --output",
            ),
            Change(
                category="added",
                summary="Array parameter auto-wrap in api command",
            ),
        ],
    ),
    ChangeEntry(
        version="0.3.15",
        date="2026-02-20",
        changes=[
            Change(
                category="changed",
                summary="Bumped typer minimum to >=0.12.0",
            ),
        ],
    ),
    ChangeEntry(
        version="0.3.14",
        date="2026-02-15",
        changes=[
            Change(
                category="fixed",
                summary="--no-truncate uses unconstrained console width",
            ),
            Change(
                category="fixed",
                summary="Decimal JSON serialization",
            ),
            Change(
                category="added",
                summary="--sql-file option for db query",
            ),
            Change(
                category="added",
                summary="Column quoting in SQL operations",
            ),
        ],
    ),
]


# ── Helpers ───────────────────────────────────────────────────────────────────


def get_changelog_since(since: str | None = None) -> list[ChangeEntry]:
    """Return changelog entries since a given version (exclusive).

    If *since* is ``None``, returns all entries.
    """
    if since is None:
        return CHANGELOG

    result: list[ChangeEntry] = []
    for entry in CHANGELOG:
        if entry.version == since:
            break
        result.append(entry)
    return result


def get_latest_entry() -> ChangeEntry | None:
    """Return the most recent changelog entry."""
    return CHANGELOG[0] if CHANGELOG else None


def whats_new_payload() -> dict[str, Any] | None:
    """Build a compact ``whats_new`` dict for the discovery payload."""
    latest = get_latest_entry()
    if latest is None:
        return None
    return {
        "version": latest.version,
        "date": latest.date,
        "highlights": [c.summary for c in latest.changes],
        "full_changelog": "anysite changelog --json",
    }
