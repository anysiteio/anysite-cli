"""Tests for JSON output helpers."""

import json
from unittest.mock import patch

import pytest
from click.exceptions import Exit

from anysite import __version__
from anysite.api.errors import AuthenticationError, RateLimitError
from anysite.cli.exit_codes import EXIT_AUTH, EXIT_ERROR, EXIT_NETWORK
from anysite.cli.json_output import (
    is_non_interactive,
    json_error,
    json_error_from_exception,
    json_response,
    print_hints,
)


def test_json_response_with_hints(capsys):
    """Test json_response outputs valid JSON with hints."""
    data = {"foo": "bar", "count": 42}
    hints = [("Next action", "anysite db list"), ("Another action", "anysite db test mydb")]
    command = "anysite db add"

    json_response(data, hints=hints, command=command)

    captured = capsys.readouterr()
    output = json.loads(captured.out)

    assert output["ok"] is True
    assert output["result"] == {"foo": "bar", "count": 42}
    assert len(output["hints"]) == 2
    assert output["hints"][0] == {"action": "Next action", "command": "anysite db list"}
    assert output["hints"][1] == {"action": "Another action", "command": "anysite db test mydb"}
    assert output["meta"]["version"] == __version__
    assert output["meta"]["command"] == "anysite db add"


def test_json_response_without_hints(capsys):
    """Test json_response without hints does not include hints key."""
    data = {"status": "success"}
    command = "anysite db info"

    json_response(data, command=command)

    captured = capsys.readouterr()
    output = json.loads(captured.out)

    assert output["ok"] is True
    assert output["result"] == {"status": "success"}
    assert "hints" not in output
    assert output["meta"]["version"] == __version__
    assert output["meta"]["command"] == "anysite db info"


def test_json_response_with_empty_hints(capsys):
    """Test json_response with empty hints list does not include hints."""
    data = {"value": 123}

    json_response(data, hints=[])

    captured = capsys.readouterr()
    output = json.loads(captured.out)

    assert output["ok"] is True
    assert output["result"] == {"value": 123}
    assert "hints" not in output


def test_json_response_without_command(capsys):
    """Test json_response without command omits command from meta."""
    data = ["item1", "item2"]

    json_response(data)

    captured = capsys.readouterr()
    output = json.loads(captured.out)

    assert output["ok"] is True
    assert output["result"] == ["item1", "item2"]
    assert output["meta"]["version"] == __version__
    assert "command" not in output["meta"]


def test_json_error(capsys):
    """Test json_error outputs valid JSON error and raises Exit."""
    with pytest.raises(Exit) as exc_info:
        json_error(
            "CONNECTION_NOT_FOUND",
            "Database connection 'mydb' not found",
            suggestions=["Run: anysite db add mydb", "Check: anysite db list"],
            retryable=False,
            exit_code=EXIT_ERROR,
        )

    assert exc_info.value.exit_code == EXIT_ERROR

    captured = capsys.readouterr()
    output = json.loads(captured.out)

    assert output["ok"] is False
    assert output["error"]["code"] == "CONNECTION_NOT_FOUND"
    assert output["error"]["message"] == "Database connection 'mydb' not found"
    assert output["error"]["retryable"] is False
    assert output["error"]["suggestions"] == [
        "Run: anysite db add mydb",
        "Check: anysite db list",
    ]
    assert output["meta"]["version"] == __version__


def test_json_error_without_suggestions(capsys):
    """Test json_error without suggestions omits suggestions key."""
    with pytest.raises(Exit) as exc_info:
        json_error("INVALID_INPUT", "Invalid parameter", retryable=True, exit_code=EXIT_ERROR)

    assert exc_info.value.exit_code == EXIT_ERROR

    captured = capsys.readouterr()
    output = json.loads(captured.out)

    assert output["ok"] is False
    assert output["error"]["code"] == "INVALID_INPUT"
    assert output["error"]["message"] == "Invalid parameter"
    assert output["error"]["retryable"] is True
    assert "suggestions" not in output["error"]


def test_json_error_retryable(capsys):
    """Test json_error with retryable flag."""
    with pytest.raises(Exit) as exc_info:
        json_error(
            "NETWORK_ERROR",
            "Connection timeout",
            retryable=True,
            exit_code=EXIT_NETWORK,
        )

    assert exc_info.value.exit_code == EXIT_NETWORK

    captured = capsys.readouterr()
    output = json.loads(captured.out)

    assert output["error"]["retryable"] is True


def test_json_error_from_exception_anysite_error(capsys):
    """Test json_error_from_exception converts AnysiteError subclass."""
    exc = AuthenticationError("API key invalid")

    with pytest.raises(Exit) as exc_info:
        json_error_from_exception(exc)

    assert exc_info.value.exit_code == EXIT_AUTH

    captured = capsys.readouterr()
    output = json.loads(captured.out)

    assert output["ok"] is False
    assert output["error"]["code"] == "AUTH_FAILED"
    assert "API key invalid" in output["error"]["message"]
    assert output["error"]["retryable"] is False
    assert len(output["error"]["suggestions"]) > 0


def test_json_error_from_exception_rate_limit(capsys):
    """Test json_error_from_exception with retryable error."""
    exc = RateLimitError("Too many requests", retry_after=60)

    with pytest.raises(Exit) as exc_info:
        json_error_from_exception(exc)

    assert exc_info.value.exit_code == EXIT_NETWORK

    captured = capsys.readouterr()
    output = json.loads(captured.out)

    assert output["ok"] is False
    assert output["error"]["code"] == "RATE_LIMIT"
    assert output["error"]["retryable"] is True
    assert len(output["error"]["suggestions"]) > 0


def test_json_error_from_exception_unknown(capsys):
    """Test json_error_from_exception with non-AnysiteError exception."""
    exc = ValueError("Something went wrong")

    with pytest.raises(Exit) as exc_info:
        json_error_from_exception(exc)

    assert exc_info.value.exit_code == EXIT_ERROR

    captured = capsys.readouterr()
    output = json.loads(captured.out)

    assert output["ok"] is False
    assert output["error"]["code"] == "UNKNOWN_ERROR"
    assert output["error"]["message"] == "Something went wrong"
    assert output["error"]["retryable"] is False


def test_print_hints_to_stderr(capsys):
    """Test print_hints outputs to stderr, not stdout."""
    hints = [("View schema", "anysite db schema mydb"), ("Run query", "anysite db query mydb")]

    print_hints(hints, quiet=False)

    captured = capsys.readouterr()
    assert captured.out == ""  # Nothing to stdout
    assert "Next steps:" in captured.err
    assert "View schema" in captured.err
    assert "anysite db schema mydb" in captured.err
    assert "Run query" in captured.err
    assert "anysite db query mydb" in captured.err


def test_print_hints_quiet_mode(capsys):
    """Test print_hints with quiet=True produces no output."""
    hints = [("Do something", "anysite command")]

    print_hints(hints, quiet=True)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_print_hints_empty_list(capsys):
    """Test print_hints with empty list produces no output."""
    print_hints([], quiet=False)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_is_non_interactive_with_state():
    """Test is_non_interactive returns True when state is set."""
    with patch("anysite.main.state", {"non_interactive": True}):
        assert is_non_interactive() is True


def test_is_non_interactive_without_state():
    """Test is_non_interactive returns False when state is not set."""
    with patch("anysite.main.state", {}):
        with patch("sys.stdin.isatty", return_value=True):
            assert is_non_interactive() is False


def test_is_non_interactive_not_tty():
    """Test is_non_interactive returns True when stdin is not a tty."""
    with patch("anysite.main.state", {}):
        with patch("sys.stdin.isatty", return_value=False):
            assert is_non_interactive() is True
