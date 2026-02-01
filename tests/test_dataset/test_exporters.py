"""Tests for dataset exporters — file and webhook."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from anysite.dataset.exporters import _expand_template, run_exports
from anysite.dataset.models import ExportDestination


@pytest.fixture
def sample_records() -> list[dict]:
    return [
        {"name": "Alice", "score": 10},
        {"name": "Bob", "score": 20},
    ]


class TestFileExporter:
    @pytest.mark.asyncio
    async def test_jsonl_export(self, tmp_path: Path, sample_records: list[dict]) -> None:
        export = ExportDestination(type="file", path=str(tmp_path / "out.jsonl"), format="jsonl")
        await run_exports(sample_records, [export], "test_source", "test_ds")

        lines = (tmp_path / "out.jsonl").read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["name"] == "Alice"

    @pytest.mark.asyncio
    async def test_json_export(self, tmp_path: Path, sample_records: list[dict]) -> None:
        export = ExportDestination(type="file", path=str(tmp_path / "out.json"), format="json")
        await run_exports(sample_records, [export], "test_source", "test_ds")

        data = json.loads((tmp_path / "out.json").read_text())
        assert len(data) == 2

    @pytest.mark.asyncio
    async def test_csv_export(self, tmp_path: Path, sample_records: list[dict]) -> None:
        export = ExportDestination(type="file", path=str(tmp_path / "out.csv"), format="csv")
        await run_exports(sample_records, [export], "test_source", "test_ds")

        with open(tmp_path / "out.csv") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 2
        assert rows[0]["name"] == "Alice"

    @pytest.mark.asyncio
    async def test_creates_parent_dirs(self, tmp_path: Path, sample_records: list[dict]) -> None:
        export = ExportDestination(
            type="file",
            path=str(tmp_path / "sub" / "dir" / "out.jsonl"),
            format="jsonl",
        )
        await run_exports(sample_records, [export], "src", "ds")
        assert (tmp_path / "sub" / "dir" / "out.jsonl").exists()

    @pytest.mark.asyncio
    async def test_empty_records_skipped(self, tmp_path: Path) -> None:
        export = ExportDestination(type="file", path=str(tmp_path / "out.jsonl"), format="jsonl")
        await run_exports([], [export], "src", "ds")
        assert not (tmp_path / "out.jsonl").exists()


class TestWebhookExporter:
    @pytest.mark.asyncio
    async def test_webhook_post(self, sample_records: list[dict]) -> None:
        export = ExportDestination(type="webhook", url="https://example.com/hook")

        mock_resp = AsyncMock()
        mock_resp.raise_for_status = lambda: None

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await run_exports(sample_records, [export], "src", "ds")

            mock_client.post.assert_called_once()
            call_kwargs = mock_client.post.call_args
            assert call_kwargs[1]["json"]["count"] == 2
            assert call_kwargs[1]["json"]["source"] == "src"


class TestTemplateExpansion:
    def test_date_template(self) -> None:
        result = _expand_template("./out/{{date}}.csv", "src", "ds")
        # Should contain a date-like string
        assert "202" in result
        assert "{{date}}" not in result

    def test_source_template(self) -> None:
        result = _expand_template("./out/{{source}}.csv", "my_src", "ds")
        assert "my_src" in result

    def test_dataset_template(self) -> None:
        result = _expand_template("./out/{{dataset}}.csv", "src", "my_ds")
        assert "my_ds" in result


class TestExportValidation:
    def test_file_requires_path(self) -> None:
        with pytest.raises(Exception):
            ExportDestination(type="file")

    def test_webhook_requires_url(self) -> None:
        with pytest.raises(Exception):
            ExportDestination(type="webhook")
