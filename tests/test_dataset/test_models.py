"""Tests for dataset models and YAML parsing."""

from pathlib import Path

import pytest
import yaml

from anysite.dataset.errors import CircularDependencyError, SourceNotFoundError
from anysite.dataset.models import DatasetConfig, DatasetSource, LLMStepConfig, SourceDependency, StorageConfig


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
        src = DatasetSource(id="test", endpoint="/api/linkedin/user")
        assert src.id == "test"
        assert src.endpoint == "/api/linkedin/user"
        assert src.params == {}
        assert src.parallel == 1

    def test_invalid_endpoint(self):
        with pytest.raises(ValueError, match="must start with '/'"):
            DatasetSource(id="test", endpoint="api/linkedin/user")

    def test_with_dependency(self):
        src = DatasetSource(
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
    """Tests for type='llm' sources."""

    def test_llm_source_valid(self):
        """LLM source with dependency and llm steps is valid."""
        src = DatasetSource(
            id="enriched",
            type="llm",
            dependency=SourceDependency(from_source="profiles", field="urn"),
            llm=[LLMStepConfig(type="enrich", add=["sentiment:positive/negative"])],
        )
        assert src.type == "llm"
        assert src.endpoint is None
        assert src.dependency is not None
        assert len(src.llm) == 1

    def test_llm_source_requires_dependency(self):
        """LLM source without dependency raises error."""
        with pytest.raises(ValueError, match="must have a dependency"):
            DatasetSource(
                id="enriched",
                type="llm",
                llm=[LLMStepConfig(type="enrich", add=["sentiment:positive/negative"])],
            )

    def test_llm_source_requires_llm_steps(self):
        """LLM source without llm steps raises error."""
        with pytest.raises(ValueError, match="must have at least one LLM step"):
            DatasetSource(
                id="enriched",
                type="llm",
                dependency=SourceDependency(from_source="profiles", field="urn"),
            )

    def test_llm_source_cannot_have_endpoint(self):
        """LLM source with endpoint raises error."""
        with pytest.raises(ValueError, match="cannot have endpoint"):
            DatasetSource(
                id="enriched",
                type="llm",
                endpoint="/api/something",
                dependency=SourceDependency(from_source="profiles", field="urn"),
                llm=[LLMStepConfig(type="enrich", add=["sentiment:positive/negative"])],
            )

    def test_llm_source_cannot_have_from_file(self):
        """LLM source with from_file raises error."""
        with pytest.raises(ValueError, match="cannot have from_file"):
            DatasetSource(
                id="enriched",
                type="llm",
                from_file="./data.txt",
                dependency=SourceDependency(from_source="profiles", field="urn"),
                llm=[LLMStepConfig(type="enrich", add=["sentiment:positive/negative"])],
            )

    def test_llm_source_cannot_have_input_key(self):
        """LLM source with input_key raises error."""
        with pytest.raises(ValueError, match="cannot have input_key"):
            DatasetSource(
                id="enriched",
                type="llm",
                input_key="user",
                dependency=SourceDependency(from_source="profiles", field="urn"),
                llm=[LLMStepConfig(type="enrich", add=["sentiment:positive/negative"])],
            )

    def test_api_source_requires_endpoint(self):
        """API source (default type) without endpoint raises error."""
        with pytest.raises(ValueError, match="requires endpoint"):
            DatasetSource(id="test", type="api")

    def test_default_type_is_api(self):
        """Default source type is 'api'."""
        src = DatasetSource(id="test", endpoint="/api/test")
        assert src.type == "api"


class TestDatasetConfig:
    def test_from_dict(self):
        config = DatasetConfig(
            name="test-ds",
            sources=[
                DatasetSource(id="src1", endpoint="/api/test"),
            ],
        )
        assert config.name == "test-ds"
        assert len(config.sources) == 1

    def test_duplicate_source_ids(self):
        with pytest.raises(ValueError, match="Duplicate source IDs"):
            DatasetConfig(
                name="test",
                sources=[
                    DatasetSource(id="same", endpoint="/api/a"),
                    DatasetSource(id="same", endpoint="/api/b"),
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
                DatasetSource(id="a", endpoint="/api/a"),
                DatasetSource(id="b", endpoint="/api/b"),
            ],
        )
        assert config.get_source("a") is not None
        assert config.get_source("a").id == "a"
        assert config.get_source("missing") is None

    def test_storage_path(self):
        config = DatasetConfig(
            name="test",
            sources=[DatasetSource(id="a", endpoint="/api/a")],
            storage=StorageConfig(path="./data/my-ds/"),
        )
        assert config.storage_path() == Path("./data/my-ds/")


class TestTopologicalSort:
    def test_independent_sources(self):
        config = DatasetConfig(
            name="test",
            sources=[
                DatasetSource(id="a", endpoint="/api/a"),
                DatasetSource(id="b", endpoint="/api/b"),
            ],
        )
        ordered = config.topological_sort()
        ids = [s.id for s in ordered]
        assert set(ids) == {"a", "b"}

    def test_linear_dependency(self):
        config = DatasetConfig(
            name="test",
            sources=[
                DatasetSource(id="a", endpoint="/api/a"),
                DatasetSource(
                    id="b",
                    endpoint="/api/b",
                    dependency=SourceDependency(from_source="a", field="id"),
                    input_key="parent_id",
                ),
                DatasetSource(
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
                DatasetSource(id="root", endpoint="/api/root"),
                DatasetSource(
                    id="left",
                    endpoint="/api/left",
                    dependency=SourceDependency(from_source="root", field="id"),
                    input_key="id",
                ),
                DatasetSource(
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
                DatasetSource(
                    id="a",
                    endpoint="/api/a",
                    dependency=SourceDependency(from_source="b", field="id"),
                    input_key="id",
                ),
                DatasetSource(
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
                DatasetSource(
                    id="a",
                    endpoint="/api/a",
                    dependency=SourceDependency(from_source="nonexistent", field="id"),
                    input_key="id",
                ),
            ],
        )
        with pytest.raises(SourceNotFoundError):
            config.topological_sort()


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
            sources=[DatasetSource(id="s1", endpoint="/api/s1")],
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
        src = DatasetSource(
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
        src = DatasetSource(id="test", endpoint="/api/test")
        assert src.llm == []
