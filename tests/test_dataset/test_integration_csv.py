"""Integration tests using real CSV data for diff and refresh: always features."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from anysite.dataset.differ import (
    DatasetDiffer,
    format_diff_records,
    format_diff_table,
)
from anysite.dataset.models import DatasetConfig, DatasetSource
from anysite.dataset.storage import MetadataStore, write_parquet

CSV_PATH = Path(__file__).resolve().parent.parent.parent / "test_data" / "enriched_partners_sample_10.csv"


def _load_csv_records() -> list[dict[str, object]]:
    """Load all 10 records from the sample CSV."""
    with open(CSV_PATH, newline="") as f:
        reader = csv.DictReader(f)
        records = []
        for row in reader:
            # Convert employee_count to int where possible
            try:
                row["employee_count"] = int(row["employee_count"])
            except (ValueError, TypeError):
                pass
            records.append(row)
    return records


def _records_by_alias(records: list[dict]) -> dict[str, dict]:
    return {r["linkedin_alias"]: r for r in records}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DAY1 = date(2026, 1, 23)
DAY2 = date(2026, 1, 24)


@pytest.fixture()
def csv_records():
    return _load_csv_records()


@pytest.fixture()
def day1_day2_parquet(tmp_path, csv_records):
    """Write day1 and day2 Parquet snapshots with planned mutations."""
    by_alias = _records_by_alias(csv_records)

    # Day 1: 8 of 10 — exclude solpak20 and 澳星电气有限公司
    day1_records = [
        r for alias, r in by_alias.items()
        if alias not in {"solpak20", "澳星电气有限公司"}
    ]

    # Day 2: all 10, but mutate 2 and remove ireadysystems
    day2_records = []
    for alias, r in by_alias.items():
        if alias == "ireadysystems":
            continue  # removed
        rec = dict(r)
        if alias == "polytron":
            rec["employee_count"] = 130  # was 115
        if alias == "dennis-group-brasil":
            rec["description"] = "Updated description for Dennis Group Brasil"
        day2_records.append(rec)

    source_dir = tmp_path / "raw" / "companies"
    source_dir.mkdir(parents=True)
    write_parquet(day1_records, source_dir / f"{DAY1.isoformat()}.parquet")
    write_parquet(day2_records, source_dir / f"{DAY2.isoformat()}.parquet")
    return tmp_path


# ---------------------------------------------------------------------------
# Test 1: diff with real CSV data
# ---------------------------------------------------------------------------


class TestDiffWithRealCsvData:
    def test_diff_counts(self, day1_day2_parquet):
        """Diff detects correct added/removed/changed counts."""
        differ = DatasetDiffer(day1_day2_parquet)
        result = differ.diff(
            "companies", "linkedin_alias",
            from_date=DAY1, to_date=DAY2,
        )

        assert len(result.added) == 2
        assert len(result.removed) == 1
        assert len(result.changed) == 2

        added_aliases = {r["linkedin_alias"] for r in result.added}
        assert added_aliases == {"solpak20", "澳星电气有限公司"}

        removed_aliases = {r["linkedin_alias"] for r in result.removed}
        assert removed_aliases == {"ireadysystems"}

    def test_changed_fields_populated(self, day1_day2_parquet):
        """Changed records have _changed_fields metadata."""
        differ = DatasetDiffer(day1_day2_parquet)
        result = differ.diff(
            "companies", "linkedin_alias",
            from_date=DAY1, to_date=DAY2,
        )

        for rec in result.changed:
            assert "_changed_fields" in rec
            assert len(rec["_changed_fields"]) > 0

    def test_employee_count_change_detected(self, day1_day2_parquet):
        """Polytron's employee_count change from 115 to 130 is detected."""
        differ = DatasetDiffer(day1_day2_parquet)
        result = differ.diff(
            "companies", "linkedin_alias",
            from_date=DAY1, to_date=DAY2,
        )

        polytron = [r for r in result.changed if r["linkedin_alias"] == "polytron"]
        assert len(polytron) == 1
        assert "employee_count" in polytron[0]["_changed_fields"]

    def test_unchanged_count(self, day1_day2_parquet):
        """5 records present in both snapshots and unchanged."""
        differ = DatasetDiffer(day1_day2_parquet)
        result = differ.diff(
            "companies", "linkedin_alias",
            from_date=DAY1, to_date=DAY2,
        )

        # day1 has 8, day2 has 9
        # matched by key: 7 (the 8 in day1 minus ireadysystems removed = 7 in both)
        # of those 7, 2 changed → 5 unchanged
        assert result.unchanged_count == 5


# ---------------------------------------------------------------------------
# Test 2: diff with field filter
# ---------------------------------------------------------------------------


class TestDiffFieldFilterWithCsv:
    def test_only_employee_count_changes(self, day1_day2_parquet):
        """With fields=[employee_count], only that change is detected."""
        differ = DatasetDiffer(day1_day2_parquet)
        result = differ.diff(
            "companies", "linkedin_alias",
            from_date=DAY1, to_date=DAY2,
            fields=["employee_count"],
        )

        # Only polytron changed employee_count; description change for dennis-group is ignored
        assert len(result.changed) == 1
        assert result.changed[0]["linkedin_alias"] == "polytron"
        assert "employee_count" in result.changed[0]["_changed_fields"]

    def test_only_description_changes(self, day1_day2_parquet):
        """With fields=[description], only dennis-group change is detected."""
        differ = DatasetDiffer(day1_day2_parquet)
        result = differ.diff(
            "companies", "linkedin_alias",
            from_date=DAY1, to_date=DAY2,
            fields=["description"],
        )

        assert len(result.changed) == 1
        assert result.changed[0]["linkedin_alias"] == "dennis-group-brasil"


# ---------------------------------------------------------------------------
# Test 3: diff output formats
# ---------------------------------------------------------------------------


class TestDiffOutputFormatsWithCsv:
    def test_format_diff_table_has_arrows(self, day1_day2_parquet):
        """format_diff_table produces → arrows for changed fields."""
        differ = DatasetDiffer(day1_day2_parquet)
        result = differ.diff(
            "companies", "linkedin_alias",
            from_date=DAY1, to_date=DAY2,
        )

        rows = format_diff_table(result)
        changed_rows = [r for r in rows if r["_diff"] == "changed"]
        assert len(changed_rows) == 2

        for row in changed_rows:
            # At least one field should have the arrow
            arrow_found = any("→" in str(v) for v in row.values())
            assert arrow_found, f"No → found in changed row: {row['linkedin_alias']}"

    def test_format_diff_records_has_old_columns(self, day1_day2_parquet):
        """format_diff_records includes __old columns for changed fields."""
        differ = DatasetDiffer(day1_day2_parquet)
        result = differ.diff(
            "companies", "linkedin_alias",
            from_date=DAY1, to_date=DAY2,
        )

        rows = format_diff_records(result)
        changed_rows = [r for r in rows if r["_diff"] == "changed"]
        assert len(changed_rows) == 2

        for row in changed_rows:
            old_cols = [k for k in row if k.endswith("__old")]
            assert len(old_cols) > 0, f"No __old columns in: {row['linkedin_alias']}"

    def test_all_diff_types_in_output(self, day1_day2_parquet):
        """All three diff types (added/removed/changed) appear in output."""
        differ = DatasetDiffer(day1_day2_parquet)
        result = differ.diff(
            "companies", "linkedin_alias",
            from_date=DAY1, to_date=DAY2,
        )

        table_rows = format_diff_table(result)
        diff_types = {r["_diff"] for r in table_rows}
        assert diff_types == {"added", "removed", "changed"}

        record_rows = format_diff_records(result)
        diff_types = {r["_diff"] for r in record_rows}
        assert diff_types == {"added", "removed", "changed"}


# ---------------------------------------------------------------------------
# Test 4: refresh: always with CSV from_file
# ---------------------------------------------------------------------------


class TestRefreshAlwaysWithCsvFromFile:
    @pytest.mark.asyncio
    async def test_refresh_always_skips_nothing(self, tmp_path):
        """With refresh: always, incremental mode still collects all inputs."""
        from anysite.dataset.collector import collect_dataset

        config = DatasetConfig(
            name="test-refresh",
            sources=[
                DatasetSource(
                    id="companies",
                    endpoint="/api/linkedin/company",
                    from_file=str(CSV_PATH),
                    file_field="linkedin_alias",
                    input_key="alias",
                    refresh="always",
                ),
            ],
            storage={"format": "parquet", "path": str(tmp_path / "data")},
        )

        # Pre-populate metadata with all 10 aliases as already collected
        metadata = MetadataStore(tmp_path / "data")
        all_aliases = [r["linkedin_alias"] for r in _load_csv_records()]
        metadata.update_collected_inputs("companies", all_aliases)

        # Verify they're stored
        assert len(metadata.get_collected_inputs("companies")) == 10

        call_count = 0

        with patch("anysite.dataset.collector.create_client") as mock_create:
            mock_client = AsyncMock()

            async def mock_post(endpoint, data=None):
                nonlocal call_count
                call_count += 1
                return {"id": call_count, "alias": data.get("alias", "")}

            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_create.return_value = mock_client

            results = await collect_dataset(
                config, config_dir=CSV_PATH.parent.parent, incremental=True, quiet=True,
            )

        # All 10 should be collected despite metadata saying they were done
        assert results["companies"] == 10
        assert call_count == 10
