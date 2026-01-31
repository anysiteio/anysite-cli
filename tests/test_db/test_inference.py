"""Tests for type inference."""


from anysite.db.schema.inference import (
    _infer_string_subtype,
    _merge_types,
    infer_sql_type,
    infer_table_schema,
)
from anysite.db.schema.types import get_sql_type


class TestInferSqlType:
    def test_none(self):
        assert infer_sql_type(None) == "text"

    def test_bool(self):
        assert infer_sql_type(True) == "boolean"
        assert infer_sql_type(False) == "boolean"

    def test_int(self):
        assert infer_sql_type(42) == "integer"
        assert infer_sql_type(0) == "integer"
        assert infer_sql_type(-1) == "integer"

    def test_float(self):
        assert infer_sql_type(3.14) == "float"
        assert infer_sql_type(0.0) == "float"

    def test_dict(self):
        assert infer_sql_type({"key": "value"}) == "json"

    def test_list(self):
        assert infer_sql_type([1, 2, 3]) == "json"

    def test_short_string(self):
        assert infer_sql_type("hello") == "varchar"

    def test_long_string(self):
        assert infer_sql_type("x" * 300) == "text"

    def test_empty_string(self):
        assert infer_sql_type("") == "text"


class TestInferStringSubtype:
    def test_date(self):
        assert _infer_string_subtype("2024-01-15") == "date"

    def test_datetime_iso(self):
        assert _infer_string_subtype("2024-01-15T10:30:00Z") == "datetime"
        assert _infer_string_subtype("2024-01-15T10:30:00+05:30") == "datetime"
        assert _infer_string_subtype("2024-01-15 10:30:00") == "datetime"

    def test_url(self):
        assert _infer_string_subtype("https://example.com") == "url"
        assert _infer_string_subtype("http://example.com/path") == "url"

    def test_email(self):
        assert _infer_string_subtype("user@example.com") == "email"

    def test_plain_string(self):
        assert _infer_string_subtype("hello world") == "varchar"


class TestMergeTypes:
    def test_same_types(self):
        assert _merge_types("integer", "integer") == "integer"

    def test_int_float(self):
        assert _merge_types("integer", "float") == "float"
        assert _merge_types("float", "integer") == "float"

    def test_text_absorbs(self):
        assert _merge_types("text", "integer") == "text"
        assert _merge_types("varchar", "text") == "text"

    def test_string_subtypes_merge(self):
        assert _merge_types("url", "email") == "varchar"
        assert _merge_types("date", "datetime") == "varchar"

    def test_json_stays(self):
        assert _merge_types("json", "varchar") == "json"


class TestInferTableSchema:
    def test_empty_rows(self):
        schema = infer_table_schema("test", [])
        assert schema.table_name == "test"
        assert schema.columns == []

    def test_single_row(self):
        schema = infer_table_schema("test", [{"id": 1, "name": "alice", "active": True}])
        assert len(schema.columns) == 3

        names = {c.name: c.inferred_type for c in schema.columns}
        assert names["id"] == "integer"
        assert names["name"] == "varchar"
        assert names["active"] == "boolean"

    def test_multiple_rows_type_promotion(self):
        rows = [
            {"value": 1},
            {"value": 2.5},
        ]
        schema = infer_table_schema("test", rows)
        value_col = next(c for c in schema.columns if c.name == "value")
        assert value_col.inferred_type == "float"

    def test_nullable_detection(self):
        rows = [
            {"name": "alice", "email": "a@b.com"},
            {"name": "bob"},
        ]
        schema = infer_table_schema("test", rows)
        email_col = next(c for c in schema.columns if c.name == "email")
        assert email_col.nullable is True

        name_col = next(c for c in schema.columns if c.name == "name")
        assert name_col.nullable is False

    def test_null_values(self):
        rows = [
            {"name": None},
            {"name": "alice"},
        ]
        schema = infer_table_schema("test", rows)
        name_col = schema.columns[0]
        assert name_col.nullable is True
        assert name_col.inferred_type == "varchar"

    def test_nested_objects(self):
        rows = [{"data": {"nested": True}, "tags": [1, 2]}]
        schema = infer_table_schema("test", rows)
        names = {c.name: c.inferred_type for c in schema.columns}
        assert names["data"] == "json"
        assert names["tags"] == "json"

    def test_column_order_preserved(self):
        rows = [{"c": 1, "a": 2, "b": 3}]
        schema = infer_table_schema("test", rows)
        names = [c.name for c in schema.columns]
        assert names == ["c", "a", "b"]

    def test_to_sql_types_sqlite(self):
        schema = infer_table_schema("test", [{"id": 1, "name": "alice", "score": 9.5}])
        sql = schema.to_sql_types("sqlite")
        assert sql["id"] == "INTEGER"
        assert sql["name"] == "TEXT"  # varchar maps to TEXT in sqlite
        assert sql["score"] == "REAL"

    def test_to_sql_types_postgres(self):
        schema = infer_table_schema("test", [{"id": 1, "name": "alice", "data": {"a": 1}}])
        sql = schema.to_sql_types("postgres")
        assert sql["id"] == "BIGINT"
        assert sql["name"] == "VARCHAR(255)"
        assert sql["data"] == "JSONB"


class TestGetSqlType:
    def test_known_type(self):
        assert get_sql_type("integer", "sqlite") == "INTEGER"
        assert get_sql_type("integer", "postgres") == "BIGINT"

    def test_unknown_type_defaults_to_text(self):
        assert get_sql_type("unknown", "sqlite") == "TEXT"

    def test_unknown_dialect_falls_back(self):
        assert get_sql_type("integer", "unknown_db") == "INTEGER"
