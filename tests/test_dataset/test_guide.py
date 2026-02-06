"""Tests for dataset guide command."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from anysite.dataset.guide import EXAMPLE_CONFIGS, GUIDE_SECTIONS, SECTION_ORDER
from anysite.main import app


@pytest.fixture
def runner():
    """Create CLI runner for testing."""
    return CliRunner()


class TestGuideSectionsData:
    """Test GUIDE_SECTIONS data integrity."""

    def test_all_sections_in_order(self) -> None:
        """GUIDE_SECTIONS has all keys from SECTION_ORDER."""
        for key in SECTION_ORDER:
            assert key in GUIDE_SECTIONS, f"Section '{key}' missing from GUIDE_SECTIONS"

    def test_section_has_required_fields(self) -> None:
        """Each section has title, description, and content."""
        for key, section in GUIDE_SECTIONS.items():
            assert section.title, f"Section '{key}' missing title"
            assert section.description, f"Section '{key}' missing description"
            assert section.content, f"Section '{key}' missing content"
            assert isinstance(section.title, str)
            assert isinstance(section.description, str)
            assert isinstance(section.content, str)

    def test_section_examples_is_list(self) -> None:
        """Section examples field is a list."""
        for key, section in GUIDE_SECTIONS.items():
            assert isinstance(section.examples, list), f"Section '{key}' examples not a list"

    def test_section_to_dict(self) -> None:
        """GuideSection.to_dict() returns correct structure."""
        section = GUIDE_SECTIONS["sources"]
        d = section.to_dict()
        assert "title" in d
        assert "description" in d
        assert "content" in d
        assert "examples" in d
        assert d["title"] == section.title
        assert d["description"] == section.description
        assert d["content"] == section.content
        assert d["examples"] == section.examples


class TestExampleConfigs:
    """Test EXAMPLE_CONFIGS data integrity."""

    def test_example_configs_exist(self) -> None:
        """EXAMPLE_CONFIGS has at least the expected examples."""
        expected = ["basic", "advanced", "from_file", "llm_enrichment"]
        for key in expected:
            assert key in EXAMPLE_CONFIGS, f"Example '{key}' missing from EXAMPLE_CONFIGS"

    def test_example_configs_are_strings(self) -> None:
        """All example configs are non-empty strings."""
        for key, config in EXAMPLE_CONFIGS.items():
            assert isinstance(config, str), f"Example '{key}' is not a string"
            assert config.strip(), f"Example '{key}' is empty"

    def test_basic_example_structure(self) -> None:
        """Basic example contains expected keys."""
        basic = EXAMPLE_CONFIGS["basic"]
        assert "name:" in basic
        assert "sources:" in basic
        assert "storage:" in basic


class TestGuideCommandCLI:
    """Test guide command via CLI."""

    def test_guide_list(self, runner: CliRunner) -> None:
        """CLI: guide --list shows section names."""
        result = runner.invoke(app, ["dataset", "guide", "--list"])
        assert result.exit_code == 0
        # Check for some expected section names
        assert "sources" in result.output
        assert "llm" in result.output
        assert "dependencies" in result.output
        assert "Available sections:" in result.output
        assert "Available examples:" in result.output

    def test_guide_section_sources(self, runner: CliRunner) -> None:
        """CLI: guide --section sources shows Source Types content."""
        result = runner.invoke(app, ["dataset", "guide", "--section", "sources"])
        assert result.exit_code == 0
        assert "Source Types" in result.output
        assert "INDEPENDENT" in result.output or "independent" in result.output.lower()

    def test_guide_section_llm(self, runner: CliRunner) -> None:
        """CLI: guide --section llm shows LLM enrichment content."""
        result = runner.invoke(app, ["dataset", "guide", "--section", "llm"])
        assert result.exit_code == 0
        assert "LLM Enrichment" in result.output

    def test_guide_section_invalid(self, runner: CliRunner) -> None:
        """CLI: guide --section invalid exits with error."""
        result = runner.invoke(app, ["dataset", "guide", "--section", "invalid"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_guide_example_basic(self, runner: CliRunner) -> None:
        """CLI: guide --example basic shows example config."""
        result = runner.invoke(app, ["dataset", "guide", "--example", "basic"])
        assert result.exit_code == 0
        assert "linkedin-search" in result.output or "name:" in result.output

    def test_guide_example_advanced(self, runner: CliRunner) -> None:
        """CLI: guide --example advanced shows advanced config."""
        result = runner.invoke(app, ["dataset", "guide", "--example", "advanced"])
        assert result.exit_code == 0
        assert "recruiting-pipeline" in result.output or "union" in result.output.lower()

    def test_guide_example_invalid(self, runner: CliRunner) -> None:
        """CLI: guide --example invalid exits with error."""
        result = runner.invoke(app, ["dataset", "guide", "--example", "invalid"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_guide_no_args(self, runner: CliRunner) -> None:
        """CLI: guide (no args) shows full guide without errors."""
        result = runner.invoke(app, ["dataset", "guide"])
        assert result.exit_code == 0
        # Check for some expected content from different sections
        assert "Source Types" in result.output
        assert "Complete Example Configs" in result.output


class TestGuideCommandJSON:
    """Test guide command JSON output."""

    def test_guide_json(self, runner: CliRunner) -> None:
        """CLI: guide --json outputs valid JSON with sections and examples."""
        result = runner.invoke(app, ["dataset", "guide", "--json"])
        assert result.exit_code == 0

        data = json.loads(result.output)
        assert data["ok"] is True
        assert "sections" in data["result"]
        assert "examples" in data["result"]
        assert "available_sections" in data["result"]
        assert "available_examples" in data["result"]

        # Check sections structure
        sections = data["result"]["sections"]
        assert isinstance(sections, dict)
        for key in SECTION_ORDER:
            assert key in sections
            assert "title" in sections[key]
            assert "description" in sections[key]
            assert "content" in sections[key]

        # Check examples structure
        examples = data["result"]["examples"]
        assert isinstance(examples, dict)
        assert "basic" in examples
        assert "advanced" in examples

    def test_guide_list_json(self, runner: CliRunner) -> None:
        """CLI: guide --list --json outputs sections and examples arrays."""
        result = runner.invoke(app, ["dataset", "guide", "--list", "--json"])
        assert result.exit_code == 0

        data = json.loads(result.output)
        assert data["ok"] is True
        assert "sections" in data["result"]
        assert "examples" in data["result"]

        sections = data["result"]["sections"]
        assert isinstance(sections, list)
        assert len(sections) > 0
        assert all("key" in s and "title" in s for s in sections)

        examples = data["result"]["examples"]
        assert isinstance(examples, list)
        assert "basic" in examples
        assert "advanced" in examples

    def test_guide_section_json(self, runner: CliRunner) -> None:
        """CLI: guide --section sources --json outputs section data."""
        result = runner.invoke(app, ["dataset", "guide", "--section", "sources", "--json"])
        assert result.exit_code == 0

        data = json.loads(result.output)
        assert data["ok"] is True
        assert "title" in data["result"]
        assert "description" in data["result"]
        assert "content" in data["result"]
        assert "examples" in data["result"]
        assert data["result"]["title"] == "Source Types"

    def test_guide_section_invalid_json(self, runner: CliRunner) -> None:
        """CLI: guide --section invalid --json returns error JSON."""
        result = runner.invoke(app, ["dataset", "guide", "--section", "invalid", "--json"])
        assert result.exit_code == 1

        data = json.loads(result.output)
        assert data["ok"] is False
        assert data["error"]["code"] == "SECTION_NOT_FOUND"
        assert "suggestions" in data["error"]

    def test_guide_example_json(self, runner: CliRunner) -> None:
        """CLI: guide --example basic --json outputs example config."""
        result = runner.invoke(app, ["dataset", "guide", "--example", "basic", "--json"])
        assert result.exit_code == 0

        data = json.loads(result.output)
        assert data["ok"] is True
        assert "example" in data["result"]
        assert "config" in data["result"]
        assert data["result"]["example"] == "basic"
        assert isinstance(data["result"]["config"], str)
        assert "linkedin-search" in data["result"]["config"]

    def test_guide_example_invalid_json(self, runner: CliRunner) -> None:
        """CLI: guide --example invalid --json returns error JSON."""
        result = runner.invoke(app, ["dataset", "guide", "--example", "invalid", "--json"])
        assert result.exit_code == 1

        data = json.loads(result.output)
        assert data["ok"] is False
        assert data["error"]["code"] == "EXAMPLE_NOT_FOUND"


class TestGuideSectionCoverage:
    """Test that all expected sections are present."""

    def test_all_expected_sections_exist(self) -> None:
        """All expected section keys exist in GUIDE_SECTIONS."""
        expected = [
            "sources",
            "params",
            "dependencies",
            "llm",
            "transform",
            "export",
            "db_load",
            "storage",
            "schedule",
            "notifications",
            "incremental",
        ]
        for key in expected:
            assert key in GUIDE_SECTIONS, f"Expected section '{key}' not found"
            assert key in SECTION_ORDER, f"Expected section '{key}' not in SECTION_ORDER"
