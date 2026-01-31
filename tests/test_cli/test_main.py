"""Tests for main CLI commands."""

import pytest
from typer.testing import CliRunner

from anysite import __version__
from anysite.main import app


@pytest.fixture
def runner():
    return CliRunner()


def test_version(runner):
    """Test --version flag."""
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_help(runner):
    """Test --help flag."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Anysite CLI" in result.stdout
    assert "api" in result.stdout
    assert "describe" in result.stdout
    assert "schema" in result.stdout
    assert "config" in result.stdout


def test_config_help(runner):
    """Test config --help."""
    result = runner.invoke(app, ["config", "--help"])
    assert result.exit_code == 0
    assert "configuration" in result.stdout.lower()


def test_api_help(runner):
    """Test api --help."""
    result = runner.invoke(app, ["api", "--help"])
    assert result.exit_code == 0
    assert "endpoint" in result.stdout.lower()
    assert "key=value" in result.stdout


def test_describe_help(runner):
    """Test describe --help."""
    result = runner.invoke(app, ["describe", "--help"])
    assert result.exit_code == 0
    assert "endpoint" in result.stdout.lower()


def test_schema_help(runner):
    """Test schema --help."""
    result = runner.invoke(app, ["schema", "--help"])
    assert result.exit_code == 0
    assert "update" in result.stdout.lower()


def test_api_requires_slash(runner):
    """Test that api command rejects endpoints without leading slash."""
    result = runner.invoke(app, ["api", "linkedin/user"])
    assert result.exit_code == 1
    assert "must start with '/'" in result.output


def test_api_rejects_bad_params(runner):
    """Test that api command rejects params without = sign."""
    result = runner.invoke(app, ["api", "/api/test", "badparam"])
    assert result.exit_code == 1
    assert "key=value" in result.output
