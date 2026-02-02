"""Tests for dataset differ."""

import json
from datetime import date

import pytest

from anysite.dataset.differ import (
    DatasetDiffer,
    DiffResult,
    _values_differ,
    format_diff_records,
    format_diff_table,
)
from anysite.dataset.errors import DatasetError
from anysite.dataset.storage import write_parquet


class TestAvailableDates:
    def test_returns_sorted_dates(self, tmp_path):
        source_dir = tmp_path / "raw" / "profiles"
        source_dir.mkdir(parents=True)
        write_parquet([{"id": 1}], source_dir / "2026-01-15.parquet")
        write_parquet([{"id": 2}], source_dir / "2026-01-10.parquet")
        write_parquet([{"id": 3}], source_dir / "2026-01-20.parquet")

        differ = DatasetDiffer(tmp_path)
        dates = differ.available_dates("profiles")
        assert dates == [
            date(2026, 1, 10),
            date(2026, 1, 15),
            date(2026, 1, 20),
        ]

    def test_no_source_dir(self, tmp_path):
        differ = DatasetDiffer(tmp_path)
        assert differ.available_dates("nonexistent") == []

    def test_empty_source_dir(self, tmp_path):
        source_dir = tmp_path / "raw" / "profiles"
        source_dir.mkdir(parents=True)
        differ = DatasetDiffer(tmp_path)
        assert differ.available_dates("profiles") == []


class TestDiffAdded:
    def test_added_records(self, tmp_path):
        """Records in new snapshot but not in old are reported as added."""
        source_dir = tmp_path / "raw" / "items"
        source_dir.mkdir(parents=True)
        write_parquet(
            [{"urn": "a", "name": "Alice"}],
            source_dir / "2026-01-01.parquet",
        )
        write_parquet(
            [{"urn": "a", "name": "Alice"}, {"urn": "b", "name": "Bob"}],
            source_dir / "2026-01-02.parquet",
        )

        differ = DatasetDiffer(tmp_path)
        result = differ.diff("items", "urn")

        assert len(result.added) == 1
        assert result.added[0]["urn"] == "b"
        assert result.added[0]["name"] == "Bob"
        assert len(result.removed) == 0


class TestDiffRemoved:
    def test_removed_records(self, tmp_path):
        """Records in old snapshot but not in new are reported as removed."""
        source_dir = tmp_path / "raw" / "items"
        source_dir.mkdir(parents=True)
        write_parquet(
            [{"urn": "a", "name": "Alice"}, {"urn": "b", "name": "Bob"}],
            source_dir / "2026-01-01.parquet",
        )
        write_parquet(
            [{"urn": "a", "name": "Alice"}],
            source_dir / "2026-01-02.parquet",
        )

        differ = DatasetDiffer(tmp_path)
        result = differ.diff("items", "urn")

        assert len(result.removed) == 1
        assert result.removed[0]["urn"] == "b"
        assert len(result.added) == 0


class TestDiffChanged:
    def test_changed_records(self, tmp_path):
        """Records with same key but different values are reported as changed."""
        source_dir = tmp_path / "raw" / "items"
        source_dir.mkdir(parents=True)
        write_parquet(
            [{"urn": "a", "name": "Alice", "title": "Engineer"}],
            source_dir / "2026-01-01.parquet",
        )
        write_parquet(
            [{"urn": "a", "name": "Alice", "title": "Senior Engineer"}],
            source_dir / "2026-01-02.parquet",
        )

        differ = DatasetDiffer(tmp_path)
        result = differ.diff("items", "urn")

        assert len(result.changed) == 1
        assert result.changed[0]["urn"] == "a"
        assert result.changed[0]["title"] == "Senior Engineer"
        assert result.changed[0]["title__old"] == "Engineer"
        assert "title" in result.changed[0]["_changed_fields"]
        assert "name" not in result.changed[0]["_changed_fields"]

    def test_unchanged_not_in_output(self, tmp_path):
        """Records that haven't changed are counted but not included."""
        source_dir = tmp_path / "raw" / "items"
        source_dir.mkdir(parents=True)
        write_parquet(
            [
                {"urn": "a", "name": "Alice"},
                {"urn": "b", "name": "Bob"},
            ],
            source_dir / "2026-01-01.parquet",
        )
        write_parquet(
            [
                {"urn": "a", "name": "Alice"},
                {"urn": "b", "name": "Bob"},
            ],
            source_dir / "2026-01-02.parquet",
        )

        differ = DatasetDiffer(tmp_path)
        result = differ.diff("items", "urn")

        assert len(result.added) == 0
        assert len(result.removed) == 0
        assert len(result.changed) == 0
        assert result.unchanged_count == 2
        assert not result.has_changes


class TestDiffAutoDetectDates:
    def test_picks_two_most_recent(self, tmp_path):
        """Without --from/--to, uses the two most recent snapshots."""
        source_dir = tmp_path / "raw" / "items"
        source_dir.mkdir(parents=True)
        write_parquet([{"urn": "a"}], source_dir / "2026-01-01.parquet")
        write_parquet([{"urn": "a"}], source_dir / "2026-01-15.parquet")
        write_parquet(
            [{"urn": "a"}, {"urn": "b"}],
            source_dir / "2026-01-20.parquet",
        )

        differ = DatasetDiffer(tmp_path)
        result = differ.diff("items", "urn")

        assert result.from_date == date(2026, 1, 15)
        assert result.to_date == date(2026, 1, 20)
        assert len(result.added) == 1


class TestDiffSpecificDates:
    def test_uses_provided_dates(self, tmp_path):
        source_dir = tmp_path / "raw" / "items"
        source_dir.mkdir(parents=True)
        write_parquet([{"urn": "a"}], source_dir / "2026-01-01.parquet")
        write_parquet(
            [{"urn": "a"}, {"urn": "b"}],
            source_dir / "2026-01-15.parquet",
        )
        write_parquet(
            [{"urn": "a"}, {"urn": "b"}, {"urn": "c"}],
            source_dir / "2026-01-20.parquet",
        )

        differ = DatasetDiffer(tmp_path)
        result = differ.diff(
            "items", "urn",
            from_date=date(2026, 1, 1),
            to_date=date(2026, 1, 20),
        )

        assert result.from_date == date(2026, 1, 1)
        assert result.to_date == date(2026, 1, 20)
        assert len(result.added) == 2  # b and c


class TestDiffFieldFilter:
    def test_only_compares_specified_fields(self, tmp_path):
        """With --fields, only those fields are checked for changes."""
        source_dir = tmp_path / "raw" / "items"
        source_dir.mkdir(parents=True)
        write_parquet(
            [{"urn": "a", "name": "Alice", "score": 10}],
            source_dir / "2026-01-01.parquet",
        )
        write_parquet(
            [{"urn": "a", "name": "Alice", "score": 20}],
            source_dir / "2026-01-02.parquet",
        )

        differ = DatasetDiffer(tmp_path)

        # Only compare name — score change should be ignored
        result = differ.diff("items", "urn", fields=["name"])
        assert len(result.changed) == 0
        assert result.unchanged_count == 1

        # Compare score — should detect change
        result = differ.diff("items", "urn", fields=["score"])
        assert len(result.changed) == 1


class TestDiffErrors:
    def test_no_snapshots_error(self, tmp_path):
        source_dir = tmp_path / "raw" / "items"
        source_dir.mkdir(parents=True)
        write_parquet([{"urn": "a"}], source_dir / "2026-01-01.parquet")

        differ = DatasetDiffer(tmp_path)
        with pytest.raises(DatasetError, match="at least 2 snapshots"):
            differ.diff("items", "urn")

    def test_key_field_missing_error(self, tmp_path):
        source_dir = tmp_path / "raw" / "items"
        source_dir.mkdir(parents=True)
        write_parquet([{"name": "Alice"}], source_dir / "2026-01-01.parquet")
        write_parquet([{"name": "Bob"}], source_dir / "2026-01-02.parquet")

        differ = DatasetDiffer(tmp_path)
        with pytest.raises(DatasetError, match="Key field 'urn' not found"):
            differ.diff("items", "urn")

    def test_missing_date_error(self, tmp_path):
        source_dir = tmp_path / "raw" / "items"
        source_dir.mkdir(parents=True)
        write_parquet([{"urn": "a"}], source_dir / "2026-01-01.parquet")
        write_parquet([{"urn": "a"}], source_dir / "2026-01-02.parquet")

        differ = DatasetDiffer(tmp_path)
        with pytest.raises(DatasetError, match="No snapshot"):
            differ.diff(
                "items", "urn",
                from_date=date(2026, 3, 1),
                to_date=date(2026, 3, 2),
            )


class TestDiffMixed:
    def test_all_change_types(self, tmp_path):
        """Test a mix of added, removed, changed, and unchanged records."""
        source_dir = tmp_path / "raw" / "items"
        source_dir.mkdir(parents=True)
        write_parquet(
            [
                {"urn": "a", "name": "Alice", "score": 10},
                {"urn": "b", "name": "Bob", "score": 20},
                {"urn": "c", "name": "Carol", "score": 30},
            ],
            source_dir / "2026-01-01.parquet",
        )
        write_parquet(
            [
                {"urn": "a", "name": "Alice", "score": 10},  # unchanged
                {"urn": "b", "name": "Bob", "score": 25},    # changed
                {"urn": "d", "name": "Dave", "score": 40},   # added
            ],
            source_dir / "2026-01-02.parquet",
        )

        differ = DatasetDiffer(tmp_path)
        result = differ.diff("items", "urn")

        assert len(result.added) == 1
        assert result.added[0]["urn"] == "d"

        assert len(result.removed) == 1
        assert result.removed[0]["urn"] == "c"

        assert len(result.changed) == 1
        assert result.changed[0]["urn"] == "b"
        assert result.changed[0]["score"] == 25
        assert result.changed[0]["score__old"] == 20

        assert result.unchanged_count == 1


class TestFormatDiffTable:
    def test_formats_with_arrows(self):
        result = DiffResult(
            source_id="items",
            from_date=date(2026, 1, 1),
            to_date=date(2026, 1, 2),
            key="urn",
            added=[{"urn": "b", "name": "Bob"}],
            removed=[{"urn": "c", "name": "Carol"}],
            changed=[{
                "urn": "a",
                "name": "Alice Updated",
                "name__old": "Alice",
                "_changed_fields": ["name"],
            }],
            unchanged_count=5,
        )

        rows = format_diff_table(result)
        assert len(rows) == 3

        added_row = [r for r in rows if r["_diff"] == "added"][0]
        assert added_row["name"] == "Bob"

        removed_row = [r for r in rows if r["_diff"] == "removed"][0]
        assert removed_row["name"] == "Carol"

        changed_row = [r for r in rows if r["_diff"] == "changed"][0]
        assert "→" in changed_row["name"]


class TestFormatDiffRecords:
    def test_includes_old_columns(self):
        result = DiffResult(
            source_id="items",
            from_date=date(2026, 1, 1),
            to_date=date(2026, 1, 2),
            key="urn",
            changed=[{
                "urn": "a",
                "name": "Alice Updated",
                "name__old": "Alice",
                "_changed_fields": ["name"],
            }],
        )

        rows = format_diff_records(result)
        assert len(rows) == 1
        assert rows[0]["name"] == "Alice Updated"
        assert rows[0]["name__old"] == "Alice"
        assert "_changed_fields" in rows[0]
        assert rows[0]["_changed_fields"] == ["name"]


class TestDotNotationKey:
    def test_diff_with_json_key(self, tmp_path):
        """Dot-notation key extracts values from JSON string fields."""
        source_dir = tmp_path / "raw" / "items"
        source_dir.mkdir(parents=True)
        write_parquet(
            [
                {"urn": json.dumps({"type": "post", "value": "p1"}), "score": 10},
                {"urn": json.dumps({"type": "post", "value": "p2"}), "score": 20},
            ],
            source_dir / "2026-01-01.parquet",
        )
        write_parquet(
            [
                {"urn": json.dumps({"type": "post", "value": "p1"}), "score": 15},
                {"urn": json.dumps({"type": "post", "value": "p2"}), "score": 20},
                {"urn": json.dumps({"type": "post", "value": "p3"}), "score": 30},
            ],
            source_dir / "2026-01-02.parquet",
        )

        differ = DatasetDiffer(tmp_path)
        result = differ.diff("items", "urn.value")

        assert len(result.added) == 1
        assert result.added[0]["urn.value"] == "p3"

        assert len(result.changed) == 1
        assert result.changed[0]["urn.value"] == "p1"
        assert "score" in result.changed[0]["_changed_fields"]

        assert result.unchanged_count == 1

    def test_dot_key_removed(self, tmp_path):
        """Dot-notation key detects removed records."""
        source_dir = tmp_path / "raw" / "items"
        source_dir.mkdir(parents=True)
        write_parquet(
            [
                {"meta": json.dumps({"id": "a"}), "name": "Alice"},
                {"meta": json.dumps({"id": "b"}), "name": "Bob"},
            ],
            source_dir / "2026-01-01.parquet",
        )
        write_parquet(
            [{"meta": json.dumps({"id": "a"}), "name": "Alice"}],
            source_dir / "2026-01-02.parquet",
        )

        differ = DatasetDiffer(tmp_path)
        result = differ.diff("items", "meta.id")
        assert len(result.removed) == 1
        assert result.removed[0]["meta.id"] == "b"

    def test_dot_key_root_missing_error(self, tmp_path):
        """Dot-notation with missing root column raises DatasetError."""
        source_dir = tmp_path / "raw" / "items"
        source_dir.mkdir(parents=True)
        write_parquet([{"name": "Alice"}], source_dir / "2026-01-01.parquet")
        write_parquet([{"name": "Bob"}], source_dir / "2026-01-02.parquet")

        differ = DatasetDiffer(tmp_path)
        with pytest.raises(DatasetError, match="Root field 'urn'"):
            differ.diff("items", "urn.value")


class TestOutputFieldFiltering:
    def test_fields_filter_diff_output(self, tmp_path):
        """When fields is set, output only contains those fields + key."""
        source_dir = tmp_path / "raw" / "items"
        source_dir.mkdir(parents=True)
        write_parquet(
            [{"urn": "a", "name": "Alice", "score": 10, "city": "SF"}],
            source_dir / "2026-01-01.parquet",
        )
        write_parquet(
            [
                {"urn": "a", "name": "Alice", "score": 20, "city": "NY"},
                {"urn": "b", "name": "Bob", "score": 30, "city": "LA"},
            ],
            source_dir / "2026-01-02.parquet",
        )

        differ = DatasetDiffer(tmp_path)
        result = differ.diff("items", "urn", fields=["score"])

        # Added record should only have urn + score
        assert len(result.added) == 1
        assert set(result.added[0].keys()) == {"urn", "score"}

        # Changed record should have urn + score + score__old + _changed_fields
        assert len(result.changed) == 1
        assert "city" not in result.changed[0]
        assert "score" in result.changed[0]
        assert "score__old" in result.changed[0]

    def test_format_diff_table_with_output_fields(self):
        """format_diff_table filters to output_fields."""
        result = DiffResult(
            source_id="items",
            from_date=date(2026, 1, 1),
            to_date=date(2026, 1, 2),
            key="urn",
            added=[{"urn": "b", "name": "Bob", "score": 30}],
            changed=[{
                "urn": "a",
                "name": "Alice",
                "score": 20,
                "score__old": 10,
                "_changed_fields": ["score"],
            }],
        )

        rows = format_diff_table(result, output_fields=["score"])
        for row in rows:
            assert "name" not in row
            assert "urn" in row  # key always included

    def test_format_diff_records_with_output_fields(self):
        """format_diff_records filters to output_fields + __old."""
        result = DiffResult(
            source_id="items",
            from_date=date(2026, 1, 1),
            to_date=date(2026, 1, 2),
            key="urn",
            changed=[{
                "urn": "a",
                "name": "Alice Updated",
                "name__old": "Alice",
                "score": 20,
                "score__old": 10,
                "_changed_fields": ["name", "score"],
            }],
        )

        rows = format_diff_records(result, output_fields=["score"])
        assert len(rows) == 1
        assert "score" in rows[0]
        assert "score__old" in rows[0]
        assert "name" not in rows[0]
        assert "name__old" not in rows[0]
        assert "urn" in rows[0]  # key always included


class TestChangedFieldsDetail:
    """Verify _changed_fields and __old columns appear in output."""

    def test_changed_fields_in_json_output(self):
        """format_diff_records includes _changed_fields for changed records."""
        result = DiffResult(
            source_id="items",
            from_date=date(2026, 1, 1),
            to_date=date(2026, 1, 2),
            key="id",
            changed=[{
                "id": "1",
                "name": "Alice Updated",
                "name__old": "Alice",
                "score": 90,
                "score__old": 90,
                "_changed_fields": ["name"],
            }],
        )

        rows = format_diff_records(result)
        assert len(rows) == 1
        assert "_changed_fields" in rows[0]
        assert rows[0]["_changed_fields"] == ["name"]
        assert "name__old" in rows[0]
        assert rows[0]["name__old"] == "Alice"

    def test_changed_fields_not_in_table_output(self):
        """format_diff_table uses old→new arrows instead of _changed_fields."""
        result = DiffResult(
            source_id="items",
            from_date=date(2026, 1, 1),
            to_date=date(2026, 1, 2),
            key="id",
            changed=[{
                "id": "1",
                "name": "Bob",
                "name__old": "Alice",
                "score": 90,
                "score__old": 90,
                "_changed_fields": ["name"],
            }],
        )

        rows = format_diff_table(result)
        assert len(rows) == 1
        assert "_changed_fields" not in rows[0]
        assert "→" in rows[0]["name"]
        assert rows[0]["score"] == 90  # unchanged, no arrow

    def test_values_differ_with_dicts(self):
        """_values_differ handles dict comparison correctly."""
        assert not _values_differ({"a": 1}, {"a": 1})
        assert _values_differ({"a": 1}, {"a": 2})
        assert not _values_differ({"b": 2, "a": 1}, {"a": 1, "b": 2})  # key order

    def test_values_differ_with_lists(self):
        """_values_differ handles list comparison."""
        assert not _values_differ([1, 2], [1, 2])
        assert _values_differ([1, 2], [1, 3])

    def test_values_differ_dict_vs_string(self):
        """_values_differ handles dict vs JSON string comparison."""
        assert _values_differ({"a": 1}, '{"a": 1}')

    def test_fallback_all_compare_fields(self, tmp_path):
        """When Python can't identify changed fields, all compare fields are marked."""
        source_dir = tmp_path / "raw" / "items"
        source_dir.mkdir(parents=True)

        # Write old and new snapshots with a value DuckDB sees as different
        write_parquet(
            [{"id": "1", "data": json.dumps({"x": 1})}],
            source_dir / "2026-01-01.parquet",
        )
        write_parquet(
            [{"id": "1", "data": json.dumps({"x": 1, "y": 2})}],
            source_dir / "2026-01-02.parquet",
        )

        differ = DatasetDiffer(tmp_path)
        result = differ.diff("items", "id")

        assert len(result.changed) == 1
        record = result.changed[0]
        assert "_changed_fields" in record
        assert len(record["_changed_fields"]) > 0
