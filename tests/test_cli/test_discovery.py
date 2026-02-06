"""Tests for agent discovery payload and auto-JSON detection."""

from __future__ import annotations

import json
from unittest.mock import patch

import typer
from typer.testing import CliRunner

from anysite.main import app

runner = CliRunner()


class TestDiscoveryPayload:
    """Test the discovery JSON returned when no subcommand is given."""

    def test_no_args_returns_help_in_terminal(self):
        """In CliRunner (simulated terminal), no args → help text."""
        result = runner.invoke(app, [])
        assert result.exit_code == 0
        assert "Usage:" in result.output
        assert "Commands" in result.output

    def test_no_args_human_flag_returns_help(self):
        """--human flag forces help text output."""
        result = runner.invoke(app, ["--human"])
        assert result.exit_code == 0
        assert "Usage:" in result.output


class TestDiscoveryPayloadStructure:
    """Test the structure of the discovery payload via build_discovery_payload."""

    def test_payload_structure(self):
        """Discovery payload has all required top-level keys."""
        # Create a minimal Click context to test the builder
        click_app = typer.main.get_command(app)
        ctx = click_app.make_context("anysite", [])

        from anysite.cli.discovery import build_discovery_payload

        payload = build_discovery_payload(ctx)

        assert payload["ok"] is True
        result = payload["result"]
        assert "tool" in result
        assert result["tool"] == "anysite-cli"
        assert "version" in result
        assert "agent_protocol" in result
        assert "output_schema" in result
        assert "exit_codes" in result
        assert "commands" in result
        assert "installed_extras" in result
        assert "meta" in payload

    def test_agent_protocol_keys(self):
        """Agent protocol section has all expected keys."""
        click_app = typer.main.get_command(app)
        ctx = click_app.make_context("anysite", [])

        from anysite.cli.discovery import build_discovery_payload

        protocol = build_discovery_payload(ctx)["result"]["agent_protocol"]
        assert "auto_json" in protocol
        assert "force_json" in protocol
        assert "force_human" in protocol
        assert "non_interactive" in protocol

    def test_exit_codes(self):
        """Exit codes are correctly documented."""
        click_app = typer.main.get_command(app)
        ctx = click_app.make_context("anysite", [])

        from anysite.cli.discovery import build_discovery_payload

        codes = build_discovery_payload(ctx)["result"]["exit_codes"]
        assert codes["0"] == "success"
        assert codes["3"] == "auth"
        assert codes["5"] == "network"

    def test_commands_discovered(self):
        """Commands are introspected from the Typer app."""
        click_app = typer.main.get_command(app)
        ctx = click_app.make_context("anysite", [])

        from anysite.cli.discovery import build_discovery_payload

        commands = build_discovery_payload(ctx)["result"]["commands"]
        # Core commands should always be present
        assert "describe" in commands
        assert "api" in commands
        assert "config" in commands
        assert "schema" in commands

    def test_command_groups_have_subcommands(self):
        """Command groups list their subcommands."""
        click_app = typer.main.get_command(app)
        ctx = click_app.make_context("anysite", [])

        from anysite.cli.discovery import build_discovery_payload

        commands = build_discovery_payload(ctx)["result"]["commands"]
        config_cmd = commands["config"]
        assert "subcommands" in config_cmd
        sub_names = [s["name"] for s in config_cmd["subcommands"]]
        assert "set" in sub_names
        assert "get" in sub_names
        assert "list" in sub_names

    def test_output_schema_documented(self):
        """Output schema shows both success and error envelopes."""
        click_app = typer.main.get_command(app)
        ctx = click_app.make_context("anysite", [])

        from anysite.cli.discovery import build_discovery_payload

        schema = build_discovery_payload(ctx)["result"]["output_schema"]
        assert schema["success"]["ok"] is True
        assert schema["error"]["ok"] is False
        assert "code" in schema["error"]["error"]
        assert "retryable" in schema["error"]["error"]

    def test_installed_extras_detected(self):
        """Installed extras are boolean flags."""
        click_app = typer.main.get_command(app)
        ctx = click_app.make_context("anysite", [])

        from anysite.cli.discovery import build_discovery_payload

        extras = build_discovery_payload(ctx)["result"]["installed_extras"]
        assert isinstance(extras.get("data"), bool)
        assert isinstance(extras.get("llm"), bool)
        assert isinstance(extras.get("postgres"), bool)

    def test_payload_is_valid_json(self):
        """The payload can round-trip through JSON serialization."""
        click_app = typer.main.get_command(app)
        ctx = click_app.make_context("anysite", [])

        from anysite.cli.discovery import build_discovery_payload

        payload = build_discovery_payload(ctx)
        serialized = json.dumps(payload, indent=2)
        parsed = json.loads(serialized)
        assert parsed["ok"] is True


class TestResolveJsonOutput:
    """Test the resolve_json_output() auto-detection logic."""

    def test_explicit_true_always_returns_true(self):
        """Passing --json explicitly → always JSON."""
        from anysite.cli.json_output import resolve_json_output

        assert resolve_json_output(explicit=True) is True

    def test_explicit_false_in_cli_runner(self):
        """In CliRunner (no real fd), explicit=False → human mode."""
        from anysite.cli.json_output import resolve_json_output

        assert resolve_json_output(explicit=False) is False

    def test_human_flag_overrides(self):
        """--human flag forces human output."""
        from anysite.cli.json_output import resolve_json_output

        with patch("anysite.main.state", {"human": True}):
            assert resolve_json_output(explicit=False) is False

    def test_human_flag_overrides_even_explicit(self):
        """--json still wins over --human (explicit=True takes priority)."""
        from anysite.cli.json_output import resolve_json_output

        with patch("anysite.main.state", {"human": True}):
            assert resolve_json_output(explicit=True) is True


class TestHumanFlagCLI:
    """Test the --human global flag works in CLI commands."""

    def test_human_flag_stored_in_state(self):
        """--human flag is stored in global state."""
        from anysite.main import state

        result = runner.invoke(app, ["--human", "config", "list"])
        assert result.exit_code == 0
        assert state.get("human") is True

    def test_default_no_human(self):
        """Without --human, state is False."""
        from anysite.main import state

        result = runner.invoke(app, ["config", "list"])
        assert result.exit_code == 0
        assert state.get("human") is False
