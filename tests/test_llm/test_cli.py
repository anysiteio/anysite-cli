"""Tests for LLM CLI commands."""

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from anysite.llm.cli import app

runner = CliRunner()


@pytest.fixture
def _mock_llm_deps():
    """Mock LLM dependency check."""
    with patch("anysite.llm.cli.check_llm_deps"):
        yield


@pytest.fixture
def mock_dataset(tmp_path):
    """Create a minimal dataset config and parquet data."""
    import yaml

    config = {
        "name": "test-dataset",
        "sources": [
            {
                "id": "profiles",
                "endpoint": "/api/test",
                "params": {"q": "test"},
            },
        ],
        "storage": {
            "format": "parquet",
            "path": str(tmp_path / "data"),
        },
    }
    config_path = tmp_path / "dataset.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config, f)

    return config_path


class TestSetup:
    def test_setup_help(self, _mock_llm_deps):
        result = runner.invoke(app, ["setup", "--help"])
        assert result.exit_code == 0
        assert "Configure" in result.output


class TestCacheStats:
    def test_cache_stats(self, _mock_llm_deps, tmp_path):
        from anysite.llm.cache import LLMCache

        cache = LLMCache(db_path=tmp_path / "test_cache.db")
        cache.put("k1", "model", "resp", 100, 50)
        cache.close()

        with patch("anysite.llm.cache._default_cache_path", return_value=tmp_path / "test_cache.db"):
            result = runner.invoke(app, ["cache-stats"])
            assert result.exit_code == 0
            assert "1" in result.output  # 1 entry


class TestCacheClear:
    def test_cache_clear(self, _mock_llm_deps):
        with patch("anysite.llm.cache.LLMCache") as MockCache:
            instance = MagicMock()
            instance.clear.return_value = 3
            MockCache.return_value = instance

            result = runner.invoke(app, ["cache-clear"])
            assert result.exit_code == 0


class TestSummarize:
    def test_summarize_help(self, _mock_llm_deps):
        result = runner.invoke(app, ["summarize", "--help"])
        assert result.exit_code == 0
        assert "source" in result.output.lower()
        assert "max-length" in result.output.lower()

    def test_summarize_dry_run(self, _mock_llm_deps, mock_dataset):
        with (
            patch("anysite.llm.cli._load_dataset_config") as mock_config,
            patch("anysite.llm.cli._read_source_records") as mock_read,
        ):
            mock_config.return_value = MagicMock()
            mock_read.return_value = [
                {"name": "Alice", "headline": "Engineer"},
                {"name": "Bob", "headline": "Designer"},
            ]

            result = runner.invoke(
                app,
                [
                    "summarize",
                    str(mock_dataset),
                    "--source",
                    "profiles",
                    "--dry-run",
                ],
            )
            assert result.exit_code == 0
            assert "prompt" in result.output.lower() or "Alice" in result.output


class TestClassify:
    def test_classify_help(self, _mock_llm_deps):
        result = runner.invoke(app, ["classify", "--help"])
        assert result.exit_code == 0
        assert "categories" in result.output.lower()
        assert "multi" in result.output.lower()

    def test_classify_dry_run(self, _mock_llm_deps, mock_dataset):
        with (
            patch("anysite.llm.cli._load_dataset_config") as mock_config,
            patch("anysite.llm.cli._read_source_records") as mock_read,
        ):
            mock_config.return_value = MagicMock()
            mock_read.return_value = [
                {"name": "Alice", "headline": "Engineer"},
            ]

            result = runner.invoke(
                app,
                [
                    "classify",
                    str(mock_dataset),
                    "--source",
                    "profiles",
                    "--categories",
                    "eng,mgr,exec",
                    "--dry-run",
                ],
            )
            assert result.exit_code == 0


class TestMatch:
    def test_match_help(self, _mock_llm_deps):
        result = runner.invoke(app, ["match", "--help"])
        assert result.exit_code == 0
        assert "source-a" in result.output.lower()
        assert "source-b" in result.output.lower()
        assert "top-k" in result.output.lower()


class TestDeduplicate:
    def test_deduplicate_help(self, _mock_llm_deps):
        result = runner.invoke(app, ["deduplicate", "--help"])
        assert result.exit_code == 0
        assert "key" in result.output.lower()
        assert "threshold" in result.output.lower()

    def test_deduplicate_dry_run_no_blocks(self, _mock_llm_deps, mock_dataset):
        with (
            patch("anysite.llm.cli._load_dataset_config") as mock_config,
            patch("anysite.llm.cli._read_source_records") as mock_read,
        ):
            mock_config.return_value = MagicMock()
            # All different first 3 chars → no blocking groups with >1 record
            mock_read.return_value = [
                {"name": "Alice"},
                {"name": "Bob"},
                {"name": "Charlie"},
            ]

            result = runner.invoke(
                app,
                [
                    "deduplicate",
                    str(mock_dataset),
                    "--source",
                    "profiles",
                    "--dry-run",
                ],
            )
            assert result.exit_code == 0


class TestEnrich:
    def test_enrich_help(self, _mock_llm_deps):
        result = runner.invoke(app, ["enrich", "--help"])
        assert result.exit_code == 0
        assert "add" in result.output.lower()

    def test_enrich_dry_run(self, _mock_llm_deps, mock_dataset):
        with (
            patch("anysite.llm.cli._load_dataset_config") as mock_config,
            patch("anysite.llm.cli._read_source_records") as mock_read,
        ):
            mock_config.return_value = MagicMock()
            mock_read.return_value = [
                {"name": "Alice", "headline": "Engineer"},
            ]

            result = runner.invoke(
                app,
                [
                    "enrich",
                    str(mock_dataset),
                    "--source",
                    "profiles",
                    "--add",
                    "sentiment:positive/negative/neutral",
                    "--dry-run",
                ],
            )
            assert result.exit_code == 0


class TestGenerate:
    def test_generate_help(self, _mock_llm_deps):
        result = runner.invoke(app, ["generate", "--help"])
        assert result.exit_code == 0
        assert "prompt" in result.output.lower()

    def test_generate_requires_prompt(self, _mock_llm_deps, mock_dataset):
        with (
            patch("anysite.llm.cli._load_dataset_config") as mock_config,
            patch("anysite.llm.cli._read_source_records") as mock_read,
        ):
            mock_config.return_value = MagicMock()
            mock_read.return_value = [{"name": "Alice"}]

            result = runner.invoke(
                app,
                [
                    "generate",
                    str(mock_dataset),
                    "--source",
                    "profiles",
                ],
            )
            assert result.exit_code == 1
            assert "required" in result.output.lower()

    def test_generate_dry_run(self, _mock_llm_deps, mock_dataset):
        with (
            patch("anysite.llm.cli._load_dataset_config") as mock_config,
            patch("anysite.llm.cli._read_source_records") as mock_read,
        ):
            mock_config.return_value = MagicMock()
            mock_read.return_value = [
                {"name": "Alice", "headline": "Engineer"},
            ]

            result = runner.invoke(
                app,
                [
                    "generate",
                    str(mock_dataset),
                    "--source",
                    "profiles",
                    "--prompt",
                    "Write about {name}",
                    "--dry-run",
                ],
            )
            assert result.exit_code == 0
            assert "Alice" in result.output
