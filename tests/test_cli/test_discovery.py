"""Tests for two-level agent discovery payload and auto-JSON detection."""

from __future__ import annotations

import json
from unittest.mock import patch

import typer
from typer.testing import CliRunner

from anysite.main import app

runner = CliRunner()


def _build_payload():
    """Helper to build the Level 1 discovery payload for tests."""
    click_app = typer.main.get_command(app)
    ctx = click_app.make_context("anysite", [])

    from anysite.cli.discovery import build_discovery_payload

    return build_discovery_payload(ctx)


def _build_group_detail(group_name: str):
    """Helper to build Level 2 detail for a command group."""
    click_app = typer.main.get_command(app)
    root_ctx = click_app.make_context("anysite", [])
    group_cmd = click_app.get_command(root_ctx, group_name)
    group_ctx = group_cmd.make_context(f"anysite {group_name}", [], parent=root_ctx)

    from anysite.cli.discovery import build_command_detail

    return build_command_detail(group_name, group_ctx)


def _build_single_detail(cmd_name: str):
    """Helper to build Level 2 detail for a single (non-group) command."""
    click_app = typer.main.get_command(app)
    root_ctx = click_app.make_context("anysite", [])
    click_cmd = click_app.get_command(root_ctx, cmd_name)

    from anysite.cli.discovery import build_single_command_detail

    return build_single_command_detail(cmd_name, click_cmd)


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
    """Test the structure of the Level 1 discovery payload."""

    def test_payload_structure(self):
        """Discovery payload has all required top-level keys."""
        payload = _build_payload()

        assert payload["ok"] is True
        result = payload["result"]
        assert result["tool"] == "anysite-cli"
        assert "version" in result
        assert "skill" in result
        assert "status" in result
        assert "agent_protocol" in result
        assert "output_schema" in result
        assert "exit_codes" in result
        assert "commands" in result
        assert "installed_extras" in result
        assert "meta" in payload

    def test_agent_protocol_keys(self):
        """Agent protocol section has all expected keys including discovery."""
        protocol = _build_payload()["result"]["agent_protocol"]
        assert "auto_json" in protocol
        assert "force_json" in protocol
        assert "force_human" in protocol
        assert "non_interactive" in protocol
        assert "discovery" in protocol

    def test_exit_codes(self):
        """Exit codes are correctly documented."""
        codes = _build_payload()["result"]["exit_codes"]
        assert codes["0"] == "success"
        assert codes["3"] == "auth"
        assert codes["5"] == "network"

    def test_commands_discovered(self):
        """Commands are introspected from the Typer app."""
        commands = _build_payload()["result"]["commands"]
        assert "describe" in commands
        assert "api" in commands
        assert "config" in commands
        assert "schema" in commands

    def test_command_groups_have_subcommands(self):
        """Command groups list their subcommands as name→description dict."""
        commands = _build_payload()["result"]["commands"]
        config_cmd = commands["config"]
        assert "subcommands" in config_cmd
        sub_names = list(config_cmd["subcommands"].keys())
        assert "set" in sub_names
        assert "get" in sub_names
        assert "list" in sub_names
        # Subcommand values are one-line description strings
        assert isinstance(config_cmd["subcommands"]["set"], str)

    def test_output_schema_documented(self):
        """Output schema shows both success and error envelopes."""
        schema = _build_payload()["result"]["output_schema"]
        assert schema["success"]["ok"] is True
        assert schema["error"]["ok"] is False
        assert "code" in schema["error"]["error"]
        assert "retryable" in schema["error"]["error"]

    def test_installed_extras_detected(self):
        """Installed extras are boolean flags."""
        extras = _build_payload()["result"]["installed_extras"]
        assert isinstance(extras.get("data"), bool)
        assert isinstance(extras.get("llm"), bool)
        assert isinstance(extras.get("postgres"), bool)
        assert isinstance(extras.get("clickhouse"), bool)
        assert isinstance(extras.get("mysql"), bool)

    def test_payload_is_valid_json(self):
        """The payload can round-trip through JSON serialization."""
        payload = _build_payload()
        serialized = json.dumps(payload, indent=2)
        parsed = json.loads(serialized)
        assert parsed["ok"] is True


class TestSkillReference:
    """Test the skill reference in the discovery payload."""

    def test_skill_reference_present(self):
        """Payload includes a skill reference."""
        result = _build_payload()["result"]
        assert result["skill"] == "anysite-skills:anysite-cli"


class TestStatusDiscovery:
    """Test the runtime status section of the discovery payload."""

    def test_status_has_auth(self):
        """Status includes auth information with method and status."""
        status = _build_payload()["result"]["status"]
        assert "auth" in status
        assert "method" in status["auth"]
        assert "status" in status["auth"]

    def test_status_has_llm(self):
        """Status includes LLM configuration info."""
        status = _build_payload()["result"]["status"]
        assert "llm" in status
        assert "configured" in status["llm"]

    def test_status_has_databases(self):
        """Status includes databases list."""
        status = _build_payload()["result"]["status"]
        assert "databases" in status
        assert isinstance(status["databases"], list)

    def test_status_has_schema(self):
        """Status includes schema cache info."""
        status = _build_payload()["result"]["status"]
        assert "schema" in status
        assert "cached" in status["schema"]

    def test_status_schema_not_cached(self):
        """Schema status shows action_required when no cache."""
        with patch("anysite.config.paths.get_schema_cache_path") as mock_path:
            mock_path.return_value.exists.return_value = False

            from anysite.cli.discovery import _collect_status

            status = _collect_status()
            assert status["schema"]["cached"] is False
            assert "action_required" in status["schema"]

    def test_status_auth_not_authenticated(self):
        """Auth status shows not_authenticated when no credentials."""
        with (
            patch("anysite.auth.token_store.TokenStore") as mock_store,
            patch.dict("os.environ", {}, clear=True),
            patch("anysite.config.get_settings") as mock_settings,
        ):
            mock_store.return_value.load.return_value = None
            mock_settings.return_value.api_key = None

            from anysite.cli.discovery import _collect_status

            status = _collect_status()
            assert status["auth"]["status"] == "not_authenticated"

    def test_status_llm_not_configured(self):
        """LLM status shows configured=False when no config."""
        with patch(
            "anysite.llm.load_llm_config",
            side_effect=Exception("no config"),
        ):
            from anysite.cli.discovery import _collect_status

            status = _collect_status()
            assert status["llm"]["configured"] is False


class TestLevel1Compact:
    """Test that Level 1 payload is compact — no full options for groups."""

    def test_groups_have_no_options(self):
        """Command groups have subcommands + detail_command, not options."""
        commands = _build_payload()["result"]["commands"]
        for group in ("db", "llm", "dataset", "config", "auth"):
            if group in commands:
                assert "options" not in commands[group], f"{group} should not have options in Level 1"
                assert "subcommands" in commands[group], f"{group} should have subcommands"
                assert "detail_command" in commands[group], f"{group} should have detail_command"

    def test_top_level_commands_are_compact(self):
        """Top-level commands (api, describe) are compact — no options, have detail_command."""
        commands = _build_payload()["result"]["commands"]
        api_cmd = commands["api"]
        assert "options" not in api_cmd
        assert "detail_command" in api_cmd

    def test_describe_is_compact(self):
        """Describe command is compact — no options, has detail_command."""
        commands = _build_payload()["result"]["commands"]
        desc = commands["describe"]
        assert "options" not in desc
        assert "detail_command" in desc

    def test_rich_descriptions(self):
        """Groups have multi-sentence descriptions (not one-liners)."""
        commands = _build_payload()["result"]["commands"]
        db_desc = commands["db"]["description"]
        # Rich descriptions are longer than one sentence
        assert len(db_desc) > 80

    def test_payload_size_reasonable(self):
        """Level 1 payload stays under 10KB."""
        payload = _build_payload()
        size = len(json.dumps(payload))
        assert size < 10000, f"Level 1 payload is {size} bytes, should be < 10KB"

    def test_detail_command_format(self):
        """detail_command tells agent how to get Level 2."""
        commands = _build_payload()["result"]["commands"]
        db_cmd = commands["db"]
        assert db_cmd["detail_command"] == "echo '' | anysite db"


class TestLevel2Detail:
    """Test Level 2 per-group detail payloads."""

    def test_db_detail_structure(self):
        """DB Level 2 has group, subcommands, common_options, tips."""
        detail = _build_group_detail("db")
        assert detail["ok"] is True
        result = detail["result"]
        assert result["group"] == "db"
        assert "common_options" in result
        assert "subcommands" in result
        assert "add" in result["subcommands"]
        assert "query" in result["subcommands"]
        assert "tips" in result

    def test_common_options_factored(self):
        """Common options (like --json) appear in common_options, not per-subcommand."""
        detail = _build_group_detail("db")
        common_names = {o["name"] for o in detail["result"]["common_options"]}
        assert "json" in common_names
        # --json should NOT appear in individual subcommand options
        for sub_name, sub in detail["result"]["subcommands"].items():
            if "options" in sub:
                sub_opt_names = [o["name"] for o in sub["options"]]
                assert "json" not in sub_opt_names, f"--json should not be in {sub_name} unique options"

    def test_unique_options_present(self):
        """Subcommands have their unique options."""
        detail = _build_group_detail("db")
        add_cmd = detail["result"]["subcommands"]["add"]
        assert "options" in add_cmd
        opt_names = [o["name"] for o in add_cmd["options"]]
        assert "type" in opt_names
        assert "host" in opt_names

    def test_examples_present(self):
        """Subcommands with curated examples have examples list."""
        detail = _build_group_detail("db")
        add_cmd = detail["result"]["subcommands"]["add"]
        assert "examples" in add_cmd
        assert len(add_cmd["examples"]) > 0
        assert any("sqlite" in ex for ex in add_cmd["examples"])

    def test_tips_present(self):
        """Group detail has tips list."""
        detail = _build_group_detail("db")
        tips = detail["result"]["tips"]
        assert len(tips) > 0

    def test_meta_has_command(self):
        """Meta section includes the group command."""
        detail = _build_group_detail("db")
        assert detail["meta"]["command"] == "anysite db"

    def test_all_groups_have_detail(self):
        """All command groups return valid Level 2 detail."""
        for group in ("db", "llm", "dataset", "config", "auth", "schema"):
            detail = _build_group_detail(group)
            assert detail["ok"] is True
            assert detail["result"]["group"] == group
            assert "subcommands" in detail["result"]


class TestLevel2SingleCommand:
    """Test Level 2 detail for single (non-group) commands like api and describe."""

    def test_api_detail_structure(self):
        """API Level 2 has command, options, examples, tips."""
        detail = _build_single_detail("api")
        assert detail["ok"] is True
        result = detail["result"]
        assert result["command"] == "api"
        assert "options" in result
        assert "examples" in result
        assert "tips" in result

    def test_api_has_all_options(self):
        """API Level 2 includes all options including batch and output."""
        detail = _build_single_detail("api")
        opt_names = [o["name"] for o in detail["result"]["options"]]
        assert "ENDPOINT" in opt_names
        assert "format" in opt_names
        assert "from-file" in opt_names
        assert "parallel" in opt_names
        assert "fields" in opt_names

    def test_describe_detail_structure(self):
        """Describe Level 2 has command, options, examples, tips."""
        detail = _build_single_detail("describe")
        assert detail["ok"] is True
        result = detail["result"]
        assert result["command"] == "describe"
        assert "options" in result
        assert "examples" in result
        assert "tips" in result

    def test_describe_has_options(self):
        """Describe Level 2 includes search and json options."""
        detail = _build_single_detail("describe")
        opt_names = [o["name"] for o in detail["result"]["options"]]
        assert "search" in opt_names
        assert "json" in opt_names

    def test_meta_has_command(self):
        """Meta section includes the command name."""
        detail = _build_single_detail("api")
        assert detail["meta"]["command"] == "anysite api"

    def test_both_commands_have_detail(self):
        """Both api and describe return valid Level 2 detail."""
        for cmd in ("api", "describe"):
            detail = _build_single_detail(cmd)
            assert detail["ok"] is True
            assert detail["result"]["command"] == cmd
            assert "options" in detail["result"]


class TestLevel2ParameterDiscovery:
    """Test parameter introspection in Level 2 detail payloads."""

    def _get_all_options(self, group: str, subcommand: str):
        """Get all options for a subcommand (common + unique)."""
        detail = _build_group_detail(group)
        result = detail["result"]
        common = result.get("common_options", [])
        sub = result["subcommands"][subcommand]
        unique = sub.get("options", [])
        return common + unique

    def test_choice_option_exposes_choices(self):
        """Choice options include their allowed values."""
        opts = self._get_all_options("db", "add")
        type_opt = next(o for o in opts if o["name"] == "type")
        assert type_opt["type"] == "choice"
        assert "choices" in type_opt
        assert "sqlite" in type_opt["choices"]
        assert "postgres" in type_opt["choices"]

    def test_flag_option(self):
        """Flag options have is_flag=True and type=boolean."""
        opts = self._get_all_options("llm", "setup")
        no_test = next(o for o in opts if o["name"] == "no-test")
        assert no_test["is_flag"] is True
        assert no_test["type"] == "boolean"

    def test_required_argument(self):
        """Positional arguments have param_type=argument and required=True."""
        opts = self._get_all_options("config", "set")
        key_arg = next(o for o in opts if o["name"] == "KEY")
        assert key_arg["param_type"] == "argument"
        assert key_arg["required"] is True

    def test_help_text_included(self):
        """Options with help text include the help field."""
        opts = self._get_all_options("llm", "setup")
        provider = next(o for o in opts if o["name"] == "provider")
        assert "help" in provider
        assert len(provider["help"]) > 0

    def test_integer_type_detected(self):
        """Integer options are detected as type=integer."""
        opts = self._get_all_options("auth", "login")
        timeout = next(o for o in opts if o["name"] == "timeout")
        assert timeout["type"] == "integer"

    def test_default_values_included(self):
        """Options with defaults include the default value."""
        opts = self._get_all_options("auth", "login")
        timeout = next(o for o in opts if o["name"] == "timeout")
        assert timeout["default"] == 120

    def test_option_short_flags(self):
        """Options with short flags include both in opts list."""
        opts = self._get_all_options("auth", "login")
        force = next(o for o in opts if o["name"] == "force")
        assert "--force" in force["opts"]
        assert "-f" in force["opts"]

    def test_option_structure(self):
        """Each option entry has at minimum name and type."""
        opts = self._get_all_options("llm", "setup")
        for opt in opts:
            assert "name" in opt
            assert "type" in opt


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


class TestGroupCallbackCLI:
    """Test that group callbacks show help in terminal (CliRunner)."""

    def test_config_no_args_shows_help(self):
        """anysite config (no subcommand) shows help."""
        result = runner.invoke(app, ["config"])
        assert result.exit_code == 0
        assert "Usage:" in result.output

    def test_db_no_args_shows_help(self):
        """anysite db (no subcommand) shows help."""
        result = runner.invoke(app, ["db"])
        assert result.exit_code == 0
        assert "Usage:" in result.output

    def test_auth_no_args_shows_help(self):
        """anysite auth (no subcommand) shows help."""
        result = runner.invoke(app, ["auth"])
        assert result.exit_code == 0
        assert "Usage:" in result.output

    def test_schema_no_args_shows_help(self):
        """anysite schema (no subcommand) shows help."""
        result = runner.invoke(app, ["schema"])
        assert result.exit_code == 0
        assert "Usage:" in result.output

    def test_api_no_args_shows_help(self):
        """anysite api (no endpoint) shows help in terminal."""
        result = runner.invoke(app, ["api"])
        assert result.exit_code == 0
        assert "Usage:" in result.output
