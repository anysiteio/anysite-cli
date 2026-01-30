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
    assert "linkedin" in result.stdout
    assert "instagram" in result.stdout
    assert "twitter" in result.stdout
    assert "web" in result.stdout
    assert "yc" in result.stdout
    assert "config" in result.stdout


def test_linkedin_help(runner):
    """Test linkedin --help."""
    result = runner.invoke(app, ["linkedin", "--help"])
    assert result.exit_code == 0
    assert "LinkedIn" in result.stdout


def test_instagram_help(runner):
    """Test instagram --help."""
    result = runner.invoke(app, ["instagram", "--help"])
    assert result.exit_code == 0
    assert "Instagram" in result.stdout


def test_twitter_help(runner):
    """Test twitter --help."""
    result = runner.invoke(app, ["twitter", "--help"])
    assert result.exit_code == 0
    assert "Twitter" in result.stdout


def test_web_help(runner):
    """Test web --help."""
    result = runner.invoke(app, ["web", "--help"])
    assert result.exit_code == 0
    assert "Web" in result.stdout or "parse" in result.stdout


def test_yc_help(runner):
    """Test yc --help."""
    result = runner.invoke(app, ["yc", "--help"])
    assert result.exit_code == 0
    assert "Y Combinator" in result.stdout or "company" in result.stdout


def test_config_help(runner):
    """Test config --help."""
    result = runner.invoke(app, ["config", "--help"])
    assert result.exit_code == 0
    assert "configuration" in result.stdout.lower()
