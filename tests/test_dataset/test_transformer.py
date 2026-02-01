"""Tests for dataset transformer — filter, field selection, add_columns."""

from __future__ import annotations

import pytest

from anysite.dataset.models import TransformConfig
from anysite.dataset.transformer import FilterParseError, RecordTransformer


# ---------------------------------------------------------------------------
# Filter expressions
# ---------------------------------------------------------------------------


class TestFilter:
    def test_greater_than(self) -> None:
        config = TransformConfig(filter=".count > 10")
        t = RecordTransformer(config)
        records = [{"count": 5}, {"count": 15}, {"count": 10}]
        assert t.apply(records) == [{"count": 15}]

    def test_equal_string(self) -> None:
        config = TransformConfig(filter='.status == "active"')
        t = RecordTransformer(config)
        records = [{"status": "active"}, {"status": "inactive"}]
        assert t.apply(records) == [{"status": "active"}]

    def test_not_equal(self) -> None:
        config = TransformConfig(filter='.location != ""')
        t = RecordTransformer(config)
        records = [{"location": "NYC"}, {"location": ""}, {"location": "LA"}]
        assert t.apply(records) == [{"location": "NYC"}, {"location": "LA"}]

    def test_and_connector(self) -> None:
        config = TransformConfig(filter=".count > 5 and .count < 15")
        t = RecordTransformer(config)
        records = [{"count": 3}, {"count": 10}, {"count": 20}]
        assert t.apply(records) == [{"count": 10}]

    def test_or_connector(self) -> None:
        config = TransformConfig(filter='.status == "a" or .status == "b"')
        t = RecordTransformer(config)
        records = [{"status": "a"}, {"status": "b"}, {"status": "c"}]
        assert len(t.apply(records)) == 2

    def test_nested_field(self) -> None:
        config = TransformConfig(filter=".urn.value != null")
        t = RecordTransformer(config)
        records = [{"urn": {"value": "123"}}, {"urn": {"value": None}}, {"urn": {}}]
        assert t.apply(records) == [{"urn": {"value": "123"}}]

    def test_null_comparison(self) -> None:
        config = TransformConfig(filter=".name == null")
        t = RecordTransformer(config)
        records = [{"name": None}, {"name": "Alice"}]
        assert t.apply(records) == [{"name": None}]

    def test_float_comparison(self) -> None:
        config = TransformConfig(filter=".score >= 3.5")
        t = RecordTransformer(config)
        records = [{"score": 3.0}, {"score": 3.5}, {"score": 4.0}]
        assert len(t.apply(records)) == 2

    def test_empty_filter_is_noop(self) -> None:
        config = TransformConfig(filter="")
        t = RecordTransformer(config)
        records = [{"a": 1}, {"a": 2}]
        assert t.apply(records) == records

    def test_none_filter_is_noop(self) -> None:
        config = TransformConfig(filter=None)
        t = RecordTransformer(config)
        records = [{"a": 1}]
        assert t.apply(records) == records

    def test_invalid_filter_raises(self) -> None:
        with pytest.raises(FilterParseError):
            config = TransformConfig(filter="invalid expression")
            RecordTransformer(config)

    def test_missing_field_returns_false(self) -> None:
        config = TransformConfig(filter=".missing > 0")
        t = RecordTransformer(config)
        records = [{"other": 1}]
        assert t.apply(records) == []


# ---------------------------------------------------------------------------
# Field selection
# ---------------------------------------------------------------------------


class TestFieldSelection:
    def test_select_fields(self) -> None:
        config = TransformConfig(fields=["name", "url"])
        t = RecordTransformer(config)
        records = [{"name": "A", "url": "u", "extra": "x"}]
        result = t.apply(records)
        assert result == [{"name": "A", "url": "u"}]

    def test_dot_notation_alias(self) -> None:
        config = TransformConfig(fields=["urn.value AS urn_id"])
        t = RecordTransformer(config)
        records = [{"urn": {"value": "123"}, "name": "A"}]
        result = t.apply(records)
        assert result == [{"urn_id": "123"}]

    def test_auto_alias_for_dot_path(self) -> None:
        config = TransformConfig(fields=["urn.value"])
        t = RecordTransformer(config)
        records = [{"urn": {"value": "123"}}]
        result = t.apply(records)
        assert result == [{"urn_value": "123"}]


# ---------------------------------------------------------------------------
# Add columns
# ---------------------------------------------------------------------------


class TestAddColumns:
    def test_add_static_columns(self) -> None:
        config = TransformConfig(add_columns={"batch": "q1"})
        t = RecordTransformer(config)
        records = [{"name": "A"}, {"name": "B"}]
        result = t.apply(records)
        assert all(r["batch"] == "q1" for r in result)

    def test_combined_pipeline(self) -> None:
        config = TransformConfig(
            filter=".count > 0",
            fields=["name", "count"],
            add_columns={"source": "test"},
        )
        t = RecordTransformer(config)
        records = [
            {"name": "A", "count": 5, "extra": "x"},
            {"name": "B", "count": 0, "extra": "y"},
        ]
        result = t.apply(records)
        assert len(result) == 1
        assert result[0] == {"name": "A", "count": 5, "source": "test"}
