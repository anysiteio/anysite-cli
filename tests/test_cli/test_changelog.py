"""Tests for the changelog command and discovery integration."""

from __future__ import annotations

import json

import typer
from typer.testing import CliRunner

from anysite.changelog import (
    CHANGELOG,
    Change,
    ChangeEntry,
    get_changelog_since,
    get_latest_entry,
    whats_new_payload,
)
from anysite.main import app

runner = CliRunner()


class TestChangelogData:
    """Test the changelog data structures."""

    def test_changelog_not_empty(self):
        assert len(CHANGELOG) > 0

    def test_entries_ordered_newest_first(self):
        versions = [e.version for e in CHANGELOG]
        # Each version should be greater than or equal to the next
        for i in range(len(versions) - 1):
            assert versions[i] >= versions[i + 1]

    def test_entry_to_dict(self):
        entry = ChangeEntry(
            version="1.0.0",
            date="2026-01-01",
            changes=[Change(category="added", summary="Test feature", detail="Details")],
        )
        d = entry.to_dict()
        assert d["version"] == "1.0.0"
        assert d["date"] == "2026-01-01"
        assert len(d["changes"]) == 1
        assert d["changes"][0]["category"] == "added"
        assert d["changes"][0]["summary"] == "Test feature"
        assert d["changes"][0]["detail"] == "Details"

    def test_change_to_dict_minimal(self):
        c = Change(category="fixed", summary="Bug fix")
        d = c.to_dict()
        assert d == {"category": "fixed", "summary": "Bug fix"}
        assert "detail" not in d
        assert "example" not in d

    def test_change_to_dict_with_example(self):
        c = Change(category="added", summary="New thing", example="anysite new-thing")
        d = c.to_dict()
        assert d["example"] == "anysite new-thing"

    def test_get_latest_entry(self):
        entry = get_latest_entry()
        assert entry is not None
        assert entry.version == CHANGELOG[0].version

    def test_get_changelog_since_none(self):
        entries = get_changelog_since(None)
        assert entries == CHANGELOG

    def test_get_changelog_since_version(self):
        if len(CHANGELOG) < 2:
            return
        second = CHANGELOG[1].version
        entries = get_changelog_since(second)
        assert len(entries) == 1
        assert entries[0].version == CHANGELOG[0].version

    def test_get_changelog_since_unknown_version(self):
        entries = get_changelog_since("0.0.1")
        assert entries == CHANGELOG

    def test_get_changelog_since_latest(self):
        entries = get_changelog_since(CHANGELOG[0].version)
        assert entries == []

    def test_whats_new_payload(self):
        payload = whats_new_payload()
        assert payload is not None
        assert "version" in payload
        assert "highlights" in payload
        assert "full_changelog" in payload
        assert isinstance(payload["highlights"], list)
        assert len(payload["highlights"]) > 0


class TestChangelogCommand:
    """Test the anysite changelog CLI command."""

    def test_changelog_human(self):
        result = runner.invoke(app, ["changelog"])
        assert result.exit_code == 0
        assert "0.3.17" in result.output
        assert "added" in result.output

    def test_changelog_json(self):
        result = runner.invoke(app, ["changelog", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["ok"] is True
        assert "releases" in data["result"]
        assert len(data["result"]["releases"]) > 0
        assert data["result"]["releases"][0]["version"] == CHANGELOG[0].version

    def test_changelog_since(self):
        if len(CHANGELOG) < 2:
            return
        second = CHANGELOG[1].version
        result = runner.invoke(app, ["changelog", "--since", second, "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        releases = data["result"]["releases"]
        assert len(releases) == 1
        assert releases[0]["version"] == CHANGELOG[0].version

    def test_changelog_last(self):
        result = runner.invoke(app, ["changelog", "--last", "1", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data["result"]["releases"]) == 1

    def test_changelog_since_latest_empty(self):
        result = runner.invoke(app, ["changelog", "--since", CHANGELOG[0].version])
        assert result.exit_code == 0
        assert "No changelog entries" in result.output

    def test_changelog_appears_in_help(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "changelog" in result.output


class TestDiscoveryWhatsNew:
    """Test whats_new in the discovery payload."""

    def test_discovery_payload_includes_whats_new(self):
        click_app = typer.main.get_command(app)
        ctx = click_app.make_context("anysite", [])

        from anysite.cli.discovery import build_discovery_payload

        payload = build_discovery_payload(ctx)
        result = payload["result"]
        assert "whats_new" in result
        assert result["whats_new"]["version"] == CHANGELOG[0].version
        assert isinstance(result["whats_new"]["highlights"], list)

    def test_discovery_commands_include_changelog(self):
        click_app = typer.main.get_command(app)
        ctx = click_app.make_context("anysite", [])

        from anysite.cli.discovery import build_discovery_payload

        payload = build_discovery_payload(ctx)
        commands = payload["result"]["commands"]
        assert "changelog" in commands
