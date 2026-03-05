"""Tests for dataset models and YAML parsing."""

from pathlib import Path

import pytest
import yaml

from anysite.dataset.errors import CircularDependencyError, SourceNotFoundError
from anysite.dataset.models import (
    ApiSource,
    DatasetConfig,
    EnrichFieldSpec,
    LLMStepConfig,
    LlmSource,
    SourceDependency,
    SqlSource,
    StorageConfig,
    UnionSource,
)


class TestSourceDependency:
    def test_basic(self):
        dep = SourceDependency(from_source="parent", field="urn")
        assert dep.from_source == "parent"
        assert dep.field == "urn"
        assert dep.dedupe is False

    def test_with_match_by(self):
        dep = SourceDependency(from_source="parent", match_by="name")
        assert dep.match_by == "name"
        assert dep.field is None


class TestDatasetSource:
    def test_basic(self):
        src = ApiSource(id="test", endpoint="/api/linkedin/user")
        assert src.id == "test"
        assert src.endpoint == "/api/linkedin/user"
        assert src.params == {}
        assert src.parallel == 1

    def test_invalid_endpoint(self):
        with pytest.raises(ValueError, match="must start with '/'"):
            ApiSource(id="test", endpoint="api/linkedin/user")

    def test_with_dependency(self):
        src = ApiSource(
            id="posts",
            endpoint="/api/linkedin/user/posts",
            dependency=SourceDependency(from_source="profiles", field="urn"),
            input_key="user_urn",
            parallel=5,
            rate_limit="10/s",
        )
        assert src.dependency is not None
        assert src.dependency.from_source == "profiles"
        assert src.input_key == "user_urn"


class TestLLMSourceType:
    """Tests for LlmSource type."""

    def test_llm_source_valid(self):
        """LLM source with dependency and llm steps is valid."""
        src = LlmSource(
            id="enriched",
            type="llm",
            dependency=SourceDependency(from_source="profiles", field="urn"),
            llm=[LLMStepConfig(type="enrich", add=["sentiment:positive/negative"])],
        )
        assert src.type == "llm"
        assert src.dependency is not None
        assert len(src.llm) == 1

    def test_llm_source_requires_dependency(self):
        """LLM source without dependency raises error."""
        with pytest.raises(ValueError, match="must have a dependency"):
            LlmSource(
                id="enriched",
                type="llm",
                llm=[LLMStepConfig(type="enrich", add=["sentiment:positive/negative"])],
            )

    def test_llm_source_requires_llm_steps(self):
        """LLM source without llm steps raises error."""
        with pytest.raises(ValueError, match="must have at least one LLM step"):
            LlmSource(
                id="enriched",
                type="llm",
                dependency=SourceDependency(from_source="profiles", field="urn"),
            )

    def test_api_source_requires_endpoint(self):
        """API source without endpoint raises error."""
        with pytest.raises(ValueError, match="Field required"):
            ApiSource(id="test")

    def test_default_type_is_api(self):
        """Default source type is 'api'."""
        src = ApiSource(id="test", endpoint="/api/test")
        assert src.type == "api"


class TestDatasetConfig:
    def test_from_dict(self):
        config = DatasetConfig(
            name="test-ds",
            sources=[
                ApiSource(id="src1", endpoint="/api/test"),
            ],
        )
        assert config.name == "test-ds"
        assert len(config.sources) == 1

    def test_duplicate_source_ids(self):
        with pytest.raises(ValueError, match="Duplicate source IDs"):
            DatasetConfig(
                name="test",
                sources=[
                    ApiSource(id="same", endpoint="/api/a"),
                    ApiSource(id="same", endpoint="/api/b"),
                ],
            )

    def test_from_yaml(self, tmp_path):
        yaml_content = {
            "name": "test-dataset",
            "description": "A test",
            "sources": [
                {"id": "profiles", "endpoint": "/api/linkedin/search/users", "params": {"count": 10}},
                {
                    "id": "posts",
                    "endpoint": "/api/linkedin/user/posts",
                    "dependency": {"from_source": "profiles", "field": "urn", "dedupe": True},
                    "input_key": "user_urn",
                    "parallel": 5,
                },
            ],
            "storage": {"format": "parquet", "path": "./data/test/"},
        }

        yaml_path = tmp_path / "dataset.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(yaml_content, f)

        config = DatasetConfig.from_yaml(yaml_path)
        assert config.name == "test-dataset"
        assert len(config.sources) == 2
        assert config.sources[1].dependency is not None
        assert config.sources[1].dependency.from_source == "profiles"

    def test_get_source(self):
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(id="a", endpoint="/api/a"),
                ApiSource(id="b", endpoint="/api/b"),
            ],
        )
        assert config.get_source("a") is not None
        assert config.get_source("a").id == "a"
        assert config.get_source("missing") is None

    def test_storage_path(self):
        config = DatasetConfig(
            name="test",
            sources=[ApiSource(id="a", endpoint="/api/a")],
            storage=StorageConfig(path="./data/my-ds/"),
        )
        assert config.storage_path() == Path("./data/my-ds/")


class TestTopologicalSort:
    def test_independent_sources(self):
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(id="a", endpoint="/api/a"),
                ApiSource(id="b", endpoint="/api/b"),
            ],
        )
        ordered = config.topological_sort()
        ids = [s.id for s in ordered]
        assert set(ids) == {"a", "b"}

    def test_linear_dependency(self):
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(id="a", endpoint="/api/a"),
                ApiSource(
                    id="b",
                    endpoint="/api/b",
                    dependency=SourceDependency(from_source="a", field="id"),
                    input_key="parent_id",
                ),
                ApiSource(
                    id="c",
                    endpoint="/api/c",
                    dependency=SourceDependency(from_source="b", field="id"),
                    input_key="parent_id",
                ),
            ],
        )
        ordered = config.topological_sort()
        ids = [s.id for s in ordered]
        assert ids.index("a") < ids.index("b")
        assert ids.index("b") < ids.index("c")

    def test_diamond_dependency(self):
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(id="root", endpoint="/api/root"),
                ApiSource(
                    id="left",
                    endpoint="/api/left",
                    dependency=SourceDependency(from_source="root", field="id"),
                    input_key="id",
                ),
                ApiSource(
                    id="right",
                    endpoint="/api/right",
                    dependency=SourceDependency(from_source="root", field="id"),
                    input_key="id",
                ),
            ],
        )
        ordered = config.topological_sort()
        ids = [s.id for s in ordered]
        assert ids[0] == "root"

    def test_circular_dependency(self):
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(
                    id="a",
                    endpoint="/api/a",
                    dependency=SourceDependency(from_source="b", field="id"),
                    input_key="id",
                ),
                ApiSource(
                    id="b",
                    endpoint="/api/b",
                    dependency=SourceDependency(from_source="a", field="id"),
                    input_key="id",
                ),
            ],
        )
        with pytest.raises(CircularDependencyError):
            config.topological_sort()

    def test_missing_dependency(self):
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(
                    id="a",
                    endpoint="/api/a",
                    dependency=SourceDependency(from_source="nonexistent", field="id"),
                    input_key="id",
                ),
            ],
        )
        with pytest.raises(SourceNotFoundError):
            config.topological_sort()

    def test_union_dependency_order(self):
        """Union source comes after all its parent sources."""
        config = DatasetConfig(
            name="test",
            sources=[
                UnionSource(
                    id="combined",
                    type="union",
                    sources=["search_a", "search_b"],
                ),
                ApiSource(id="search_a", endpoint="/api/search"),
                ApiSource(id="search_b", endpoint="/api/search"),
            ],
        )
        ordered = config.topological_sort()
        ids = [s.id for s in ordered]
        assert ids.index("search_a") < ids.index("combined")
        assert ids.index("search_b") < ids.index("combined")

    def test_union_missing_source_raises(self):
        """Union referencing non-existent source raises error at config creation."""
        with pytest.raises(SourceNotFoundError):
            DatasetConfig(
                name="test",
                sources=[
                    ApiSource(id="a", endpoint="/api/a"),
                    UnionSource(
                        id="combined",
                        type="union",
                        sources=["a", "nonexistent"],
                    ),
                ],
            )

    def test_union_with_downstream_dependent(self):
        """Dependent source can reference union as parent."""
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(id="search_a", endpoint="/api/search"),
                ApiSource(id="search_b", endpoint="/api/search"),
                UnionSource(
                    id="combined",
                    type="union",
                    sources=["search_a", "search_b"],
                ),
                ApiSource(
                    id="profiles",
                    endpoint="/api/profiles",
                    dependency=SourceDependency(from_source="combined", field="urn"),
                    input_key="user",
                ),
            ],
        )
        ordered = config.topological_sort()
        ids = [s.id for s in ordered]
        assert ids.index("combined") < ids.index("profiles")

    def test_union_different_endpoints_raises(self):
        """Union sources must reference sources with same endpoint."""
        with pytest.raises(ValueError, match="different endpoints"):
            DatasetConfig(
                name="test",
                sources=[
                    ApiSource(id="users", endpoint="/api/users"),
                    ApiSource(id="companies", endpoint="/api/companies"),
                    UnionSource(
                        id="combined",
                        type="union",
                        sources=["users", "companies"],
                    ),
                ],
            )

    def test_union_same_endpoint_valid(self):
        """Union sources with same endpoint are valid."""
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(id="search_a", endpoint="/api/search"),
                ApiSource(id="search_b", endpoint="/api/search"),
                UnionSource(
                    id="combined",
                    type="union",
                    sources=["search_a", "search_b"],
                ),
            ],
        )
        assert config is not None
        ordered = config.topological_sort()
        assert len(ordered) == 3


class TestUnionSourceType:
    """Tests for UnionSource type."""

    def test_union_source_valid(self):
        """Union source with sources list is valid."""
        src = UnionSource(
            id="combined",
            type="union",
            sources=["search_a", "search_b"],
        )
        assert src.type == "union"
        assert src.sources == ["search_a", "search_b"]

    def test_union_source_requires_sources(self):
        """Union source without sources raises error."""
        with pytest.raises(ValueError, match="Field required"):
            UnionSource(id="combined", type="union")

    def test_union_with_dedupe_by(self):
        """Union source with dedupe_by is valid."""
        src = UnionSource(
            id="combined",
            type="union",
            sources=["a", "b"],
            dedupe_by="urn.value",
        )
        assert src.dedupe_by == "urn.value"


class TestStoragePath:
    def test_relative_to_yaml(self, tmp_path):
        """Relative storage path should resolve against YAML file location."""
        yaml_dir = tmp_path / "project"
        yaml_dir.mkdir()
        yaml_file = yaml_dir / "dataset.yaml"
        yaml_file.write_text(yaml.dump({
            "name": "test",
            "sources": [{"id": "s1", "endpoint": "/api/s1"}],
            "storage": {"path": "./data/"},
        }))

        config = DatasetConfig.from_yaml(yaml_file)
        assert config.storage_path() == yaml_dir / "data"

    def test_absolute_unchanged(self, tmp_path):
        """Absolute storage path should stay as-is."""
        yaml_file = tmp_path / "dataset.yaml"
        yaml_file.write_text(yaml.dump({
            "name": "test",
            "sources": [{"id": "s1", "endpoint": "/api/s1"}],
            "storage": {"path": "/absolute/data/"},
        }))

        config = DatasetConfig.from_yaml(yaml_file)
        assert config.storage_path() == Path("/absolute/data/")

    def test_no_config_dir_fallback(self):
        """Programmatic config (no from_yaml) falls back to relative path."""
        config = DatasetConfig(
            name="test",
            sources=[ApiSource(id="s1", endpoint="/api/s1")],
            storage=StorageConfig(path="./my_data/"),
        )
        assert config.storage_path() == Path("./my_data/")


class TestLLMStepConfig:
    def test_enrich_valid(self):
        step = LLMStepConfig(type="enrich", add=["mood:happy/sad"])
        assert step.type == "enrich"
        assert step.add == ["mood:happy/sad"]

    def test_enrich_without_add_raises(self):
        with pytest.raises(ValueError, match="enrich step requires 'add'"):
            LLMStepConfig(type="enrich")

    def test_classify_valid(self):
        step = LLMStepConfig(type="classify", categories="a,b,c")
        assert step.categories == "a,b,c"

    def test_classify_without_categories_is_auto(self):
        step = LLMStepConfig(type="classify")
        assert step.categories is None

    def test_summarize_defaults(self):
        step = LLMStepConfig(type="summarize")
        assert step.max_length == 100
        assert step.output_column is None

    def test_generate_valid(self):
        step = LLMStepConfig(type="generate", prompt="Hello {name}")
        assert step.prompt == "Hello {name}"

    def test_generate_without_prompt_raises(self):
        with pytest.raises(ValueError, match="generate step requires 'prompt'"):
            LLMStepConfig(type="generate")

    def test_common_defaults(self):
        step = LLMStepConfig(type="summarize")
        assert step.fields == []
        assert step.temperature is None
        assert step.max_tokens is None
        assert step.provider is None
        assert step.model is None
        assert step.output_column is None

    def test_common_overrides(self):
        step = LLMStepConfig(
            type="classify",
            categories="a,b",
            provider="anthropic",
            model="claude-sonnet-4-5-20250514",
            temperature=0.5,
            max_tokens=2048,
            output_column="role",
            fields=["headline"],
        )
        assert step.provider == "anthropic"
        assert step.model == "claude-sonnet-4-5-20250514"
        assert step.temperature == 0.5
        assert step.output_column == "role"

    def test_source_with_llm_steps(self):
        src = ApiSource(
            id="test",
            endpoint="/api/test",
            llm=[
                LLMStepConfig(type="enrich", add=["mood:happy/sad"]),
                LLMStepConfig(type="summarize"),
            ],
        )
        assert len(src.llm) == 2
        assert src.llm[0].type == "enrich"
        assert src.llm[1].type == "summarize"

    def test_source_without_llm_defaults_empty(self):
        src = ApiSource(id="test", endpoint="/api/test")
        assert src.llm == []


class TestEnrichFieldSpec:
    def test_string_type(self):
        spec = EnrichFieldSpec(name="summary")
        assert spec.type == "string"  # defaults to string

    def test_enum_values(self):
        spec = EnrichFieldSpec(name="sentiment", values=["positive", "negative", "neutral"])
        assert spec.values == ["positive", "negative", "neutral"]

    def test_integer_range(self):
        spec = EnrichFieldSpec(name="score", type="integer", min=1, max=10)
        assert spec.type == "integer"
        assert spec.min == 1
        assert spec.max == 10

    def test_type_and_values_conflict(self):
        with pytest.raises(ValueError, match="Cannot set both"):
            EnrichFieldSpec(name="x", type="string", values=["a", "b"])

    def test_structured_in_llm_step(self):
        step = LLMStepConfig(
            type="enrich",
            add=[
                EnrichFieldSpec(name="score", type="integer", min=1, max=10),
                "sentiment:positive/negative",
            ],
        )
        assert len(step.add) == 2


class TestInputAlias:
    """Tests for 'input' as an alias for 'params'."""

    def test_input_accepted(self):
        src = ApiSource.model_validate(
            {"id": "s", "endpoint": "/api/test", "input": {"keywords": "hello"}}
        )
        assert src.params == {"keywords": "hello"}

    def test_input_in_yaml(self, tmp_path):
        yaml_path = tmp_path / "dataset.yaml"
        yaml_path.write_text(
            yaml.dump(
                {
                    "name": "test",
                    "sources": [
                        {
                            "id": "search",
                            "endpoint": "/api/search",
                            "input": {"keywords": "engineer", "count": 50},
                        }
                    ],
                }
            )
        )
        config = DatasetConfig.from_yaml(yaml_path)
        assert config.sources[0].params == {"keywords": "engineer", "count": 50}

    def test_input_and_params_conflict(self):
        with pytest.raises(ValueError, match="Cannot use both"):
            ApiSource.model_validate(
                {
                    "id": "s",
                    "endpoint": "/api/s",
                    "input": {"a": 1},
                    "params": {"b": 2},
                }
            )

    def test_params_still_works(self):
        src = ApiSource(id="test", endpoint="/api/test", params={"count": 10})
        assert src.params == {"count": 10}

    def test_empty_input(self):
        src = ApiSource.model_validate(
            {"id": "s", "endpoint": "/api/test", "input": {}}
        )
        assert src.params == {}


class TestRefreshNever:
    """Tests for refresh: never."""

    def test_accepted(self):
        src = ApiSource(id="test", endpoint="/api/test", refresh="never")
        assert src.refresh == "never"

    def test_in_yaml(self, tmp_path):
        yaml_path = tmp_path / "dataset.yaml"
        yaml_path.write_text(
            yaml.dump(
                {
                    "name": "test",
                    "sources": [
                        {"id": "s", "endpoint": "/api/test", "refresh": "never"}
                    ],
                }
            )
        )
        config = DatasetConfig.from_yaml(yaml_path)
        assert config.sources[0].refresh == "never"


class TestDepRefShorthand:
    """Tests for ${source.field} dependency shorthand."""

    def test_basic_expansion(self):
        config = DatasetConfig.model_validate(
            {
                "name": "test",
                "sources": [
                    {"id": "search", "endpoint": "/api/search"},
                    {
                        "id": "profiles",
                        "endpoint": "/api/user",
                        "input": {"user": "${search.urn.value}", "count": 20},
                    },
                ],
            }
        )
        src = config.sources[1]
        assert src.dependency is not None
        assert src.dependency.from_source == "search"
        assert src.dependency.field == "urn.value"
        assert src.input_key == "user"
        assert src.params == {"count": 20}

    def test_with_params_key(self):
        src = ApiSource.model_validate(
            {
                "id": "profiles",
                "endpoint": "/api/user",
                "params": {"user": "${search.urn.value}"},
            }
        )
        assert src.dependency.from_source == "search"
        assert src.input_key == "user"
        assert src.params == {}

    def test_multiple_refs_error(self):
        with pytest.raises(ValueError, match="Only one"):
            ApiSource.model_validate(
                {
                    "id": "x",
                    "endpoint": "/api/x",
                    "input": {"user": "${a.f1}", "company": "${b.f2}"},
                }
            )

    def test_conflict_with_explicit_dependency(self):
        with pytest.raises(ValueError, match="Cannot use"):
            ApiSource.model_validate(
                {
                    "id": "x",
                    "endpoint": "/api/x",
                    "input": {"user": "${search.urn.value}"},
                    "dependency": {"from_source": "search", "field": "urn.value"},
                }
            )

    def test_conflict_with_explicit_input_key(self):
        with pytest.raises(ValueError, match="Cannot use"):
            ApiSource.model_validate(
                {
                    "id": "x",
                    "endpoint": "/api/x",
                    "input": {"user": "${search.urn.value}"},
                    "input_key": "user",
                }
            )

    def test_non_matching_passes_through(self):
        """Values without a dot don't match the pattern."""
        src = ApiSource.model_validate(
            {"id": "t", "endpoint": "/api/t", "params": {"q": "${not_a_ref}"}}
        )
        assert src.params == {"q": "${not_a_ref}"}
        assert src.dependency is None

    def test_hyphenated_source_id(self):
        src = ApiSource.model_validate(
            {
                "id": "profiles",
                "endpoint": "/api/user",
                "params": {"user": "${search-results.urn.value}"},
            }
        )
        assert src.dependency.from_source == "search-results"

    def test_deep_field_path(self):
        src = ApiSource.model_validate(
            {
                "id": "p",
                "endpoint": "/api/p",
                "input": {"user": "${profiles.author.urn.value}"},
            }
        )
        assert src.dependency.field == "author.urn.value"


class TestSqlSource:
    """Tests for SqlSource type."""

    def test_sql_source_valid_with_query(self):
        src = SqlSource(
            id="billing",
            type="sql",
            connection="billing_db",
            query="SELECT name, email FROM subscriptions WHERE status = 'inactive'",
        )
        assert src.type == "sql"
        assert src.connection == "billing_db"
        assert src.query is not None
        assert src.query_file is None

    def test_sql_source_valid_with_query_file(self):
        src = SqlSource(
            id="billing",
            type="sql",
            connection="billing_db",
            query_file="queries/inactive.sql",
        )
        assert src.query is None
        assert src.query_file == "queries/inactive.sql"

    def test_sql_source_requires_query_or_file(self):
        with pytest.raises(ValueError, match="requires either 'query' or 'query_file'"):
            SqlSource(
                id="billing",
                type="sql",
                connection="billing_db",
            )

    def test_sql_source_rejects_both(self):
        with pytest.raises(ValueError, match="cannot have both"):
            SqlSource(
                id="billing",
                type="sql",
                connection="billing_db",
                query="SELECT 1",
                query_file="query.sql",
            )

    def test_sql_source_inherits_base_fields(self):
        src = SqlSource(
            id="billing",
            type="sql",
            connection="billing_db",
            query="SELECT 1",
            filter=".email != null",
            refresh="always",
        )
        assert src.filter == ".email != null"
        assert src.refresh == "always"

    def test_sql_source_topo_sort_as_root(self):
        """SQL source as root, API source depends on it."""
        config = DatasetConfig(
            name="test",
            sources=[
                SqlSource(
                    id="billing",
                    type="sql",
                    connection="db",
                    query="SELECT name FROM users",
                ),
                ApiSource(
                    id="profiles",
                    endpoint="/api/linkedin/search/users",
                    dependency=SourceDependency(from_source="billing", field="name"),
                    input_key="keywords",
                ),
            ],
        )
        ordered = config.topological_sort()
        ids = [s.id for s in ordered]
        assert ids.index("billing") < ids.index("profiles")

    def test_sql_source_yaml_roundtrip(self, tmp_path):
        yaml_content = {
            "name": "sql-test",
            "sources": [
                {
                    "id": "billing",
                    "type": "sql",
                    "connection": "billing_db",
                    "query": "SELECT name FROM users",
                },
            ],
        }
        yaml_path = tmp_path / "dataset.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(yaml_content, f)

        config = DatasetConfig.from_yaml(yaml_path)
        assert len(config.sources) == 1
        src = config.sources[0]
        assert isinstance(src, SqlSource)
        assert src.connection == "billing_db"
        assert src.query == "SELECT name FROM users"
