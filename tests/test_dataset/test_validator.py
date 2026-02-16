"""Tests for dataset config validator."""

from __future__ import annotations

from anysite.dataset.models import (
    ApiSource,
    DatasetConfig,
    DbLoadConfig,
    LlmSource,
    LLMStepConfig,
    SourceDependency,
    TransformConfig,
)
from anysite.dataset.validator import (
    ValidationResult,
    _find_similar,
    validate_dataset_config,
)

# Empty schema cache — disables schema-aware checks for non-schema tests
NO_SCHEMA: dict = {}


class TestValidateDatasetConfig:
    def test_valid_config(self):
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(id="profiles", endpoint="/api/linkedin/user"),
            ],
        )
        result = validate_dataset_config(config, schema_cache=NO_SCHEMA)
        assert result.valid
        assert result.errors == []

    def test_valid_filter(self):
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(
                    id="profiles",
                    endpoint="/api/linkedin/user",
                    filter=".count > 10",
                ),
            ],
        )
        result = validate_dataset_config(config, schema_cache=NO_SCHEMA)
        assert result.valid

    def test_invalid_source_filter(self):
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(
                    id="profiles",
                    endpoint="/api/linkedin/user",
                    filter=".count = 10",
                ),
            ],
        )
        result = validate_dataset_config(config, schema_cache=NO_SCHEMA)
        assert not result.valid
        assert len(result.errors) == 1
        assert "sources[0].filter" in result.errors[0].location
        assert "==" in result.errors[0].message

    def test_invalid_transform_filter(self):
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(
                    id="profiles",
                    endpoint="/api/linkedin/user",
                    transform=TransformConfig(filter=".score = 5"),
                ),
            ],
        )
        result = validate_dataset_config(config, schema_cache=NO_SCHEMA)
        assert not result.valid
        assert "sources[0].transform.filter" in result.errors[0].location

    def test_invalid_db_load_filter(self):
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(
                    id="profiles",
                    endpoint="/api/linkedin/user",
                    db_load=DbLoadConfig(filter=".active = true"),
                ),
            ],
        )
        result = validate_dataset_config(config, schema_cache=NO_SCHEMA)
        assert not result.valid
        assert "sources[0].db_load.filter" in result.errors[0].location

    def test_invalid_add_spec(self):
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(
                    id="profiles",
                    endpoint="/api/linkedin/user",
                    llm=[
                        LLMStepConfig(
                            type="enrich",
                            add=["valid:string", "invalid_no_colon"],
                        ),
                    ],
                ),
            ],
        )
        result = validate_dataset_config(config, schema_cache=NO_SCHEMA)
        assert not result.valid
        assert "sources[0].llm[0].add[1]" in result.errors[0].location
        assert "invalid_no_colon" in result.errors[0].message

    def test_high_parallel_warning(self):
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(
                    id="profiles",
                    endpoint="/api/linkedin/user",
                    parallel=20,
                ),
            ],
        )
        result = validate_dataset_config(config, schema_cache=NO_SCHEMA)
        assert result.valid
        assert len(result.warnings) == 1
        assert "parallel=20" in result.warnings[0]

    def test_multiple_errors(self):
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(
                    id="profiles",
                    endpoint="/api/linkedin/user",
                    filter=".count = 10",
                    transform=TransformConfig(filter=".score = 5"),
                ),
            ],
        )
        result = validate_dataset_config(config, schema_cache=NO_SCHEMA)
        assert not result.valid
        assert len(result.errors) == 2


# ---------------------------------------------------------------------------
# Schema-aware validation tests
# ---------------------------------------------------------------------------

MOCK_SCHEMA = {
    "endpoints": {
        "/api/linkedin/user": {
            "description": "Get user profile",
            "tags": ["linkedin"],
            "input": {
                "user": {
                    "type": "string",
                    "required": True,
                    "description": "User Alias or URL",
                    "examples": ["satyanadella"],
                },
                "with_experience": {
                    "type": "boolean",
                    "required": False,
                    "description": "Include experience",
                    "default": True,
                },
            },
            "output": {
                "name": "string",
                "urn": "object",
                "urn.type": "string",
                "urn.value": "string",
                "headline": "string",
            },
        },
        "/api/linkedin/user/posts": {
            "description": "Get user posts",
            "tags": ["linkedin"],
            "input": {
                "urn": {
                    "type": "string",
                    "required": True,
                    "description": "User URN",
                    "examples": ["urn:li:fsd_profile:ACoAA..."],
                },
                "count": {"type": "integer", "required": True, "description": "Max results"},
            },
            "output": {
                "text": "string",
                "likes": "integer",
            },
        },
        "/api/linkedin/search/users": {
            "description": "Search users",
            "tags": ["linkedin"],
            "input": {
                "keywords": {"type": "string", "required": True, "description": "Search query"},
                "count": {"type": "integer", "required": False, "default": 10},
            },
            "output": {
                "name": "string",
                "urn": "object",
                "urn.value": "string",
            },
        },
    },
}


class TestSchemaAwareValidation:
    def test_endpoint_not_found(self):
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(id="profiles", endpoint="/api/linkedin/usr"),
            ],
        )
        result = validate_dataset_config(config, schema_cache=MOCK_SCHEMA)
        assert not result.valid
        assert "sources[0].endpoint" in result.errors[0].location
        assert "not found" in result.errors[0].message
        assert "/api/linkedin/user" in result.errors[0].message  # suggestion

    def test_endpoint_valid(self):
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(
                    id="profiles",
                    endpoint="/api/linkedin/user",
                    params={"user": "test"},
                ),
            ],
        )
        result = validate_dataset_config(config, schema_cache=MOCK_SCHEMA)
        assert result.valid

    def test_missing_required_param(self):
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(id="profiles", endpoint="/api/linkedin/user"),
            ],
        )
        result = validate_dataset_config(config, schema_cache=MOCK_SCHEMA)
        assert not result.valid
        err = result.errors[0]
        assert "sources[0].params" in err.location
        assert "user" in err.message
        assert "example: 'satyanadella'" in err.message

    def test_required_param_covered_by_input_key(self):
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(
                    id="profiles",
                    endpoint="/api/linkedin/user",
                    input_key="user",
                    from_file="users.txt",
                ),
            ],
        )
        result = validate_dataset_config(config, schema_cache=MOCK_SCHEMA)
        assert result.valid

    def test_required_param_with_default_not_required(self):
        """Params with default values don't trigger missing-param error."""
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(
                    id="search",
                    endpoint="/api/linkedin/search/users",
                    params={"keywords": "python"},
                ),
            ],
        )
        result = validate_dataset_config(config, schema_cache=MOCK_SCHEMA)
        assert result.valid  # count has default=10, not missing

    def test_invalid_input_key(self):
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(
                    id="profiles",
                    endpoint="/api/linkedin/user",
                    input_key="username",
                    from_file="users.txt",
                ),
            ],
        )
        result = validate_dataset_config(config, schema_cache=MOCK_SCHEMA)
        assert not result.valid
        err = [e for e in result.errors if "input_key" in e.location][0]
        assert "username" in err.message
        assert "user" in err.message  # available param

    def test_valid_input_key(self):
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(
                    id="profiles",
                    endpoint="/api/linkedin/user",
                    input_key="user",
                    from_file="users.txt",
                ),
            ],
        )
        result = validate_dataset_config(config, schema_cache=MOCK_SCHEMA)
        assert result.valid

    def test_dependency_field_not_in_parent_output(self):
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(
                    id="profiles",
                    endpoint="/api/linkedin/user",
                    params={"user": "test"},
                ),
                ApiSource(
                    id="posts",
                    endpoint="/api/linkedin/user/posts",
                    input_key="urn",
                    params={"count": 10},
                    dependency=SourceDependency(
                        from_source="profiles",
                        field="urn.val",  # typo — should be urn.value
                    ),
                ),
            ],
        )
        result = validate_dataset_config(config, schema_cache=MOCK_SCHEMA)
        assert not result.valid
        err = [e for e in result.errors if "dependency.field" in e.location][0]
        assert "urn.val" in err.message
        assert "urn.value" in err.message  # suggestion

    def test_dependency_field_valid(self):
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(
                    id="profiles",
                    endpoint="/api/linkedin/user",
                    params={"user": "test"},
                ),
                ApiSource(
                    id="posts",
                    endpoint="/api/linkedin/user/posts",
                    input_key="urn",
                    params={"count": 10},
                    dependency=SourceDependency(
                        from_source="profiles",
                        field="urn.value",
                    ),
                ),
            ],
        )
        result = validate_dataset_config(config, schema_cache=MOCK_SCHEMA)
        assert result.valid

    def test_no_schema_cache_skips_checks(self):
        """When schema_cache is empty dict, no schema errors are added."""
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(id="profiles", endpoint="/api/nonexistent"),
            ],
        )
        result = validate_dataset_config(config, schema_cache=NO_SCHEMA)
        assert result.valid  # no endpoints in cache → no checks

    def test_required_param_covered_by_input_template(self):
        """Params provided via input_template should count as covered."""
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(
                    id="profiles",
                    endpoint="/api/linkedin/user",
                    params={"user": "test"},
                ),
                ApiSource(
                    id="posts",
                    endpoint="/api/linkedin/user/posts",
                    input_key="urn",
                    input_template={
                        "urn": "{value}",
                        "count": 10,
                    },
                    dependency=SourceDependency(
                        from_source="profiles",
                        field="urn.value",
                    ),
                ),
            ],
        )
        result = validate_dataset_config(config, schema_cache=MOCK_SCHEMA)
        assert result.valid

    def test_non_api_sources_skipped(self):
        """LlmSource should not trigger endpoint checks."""
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(
                    id="profiles",
                    endpoint="/api/linkedin/user",
                    params={"user": "test"},
                ),
                LlmSource(
                    type="llm",
                    id="enriched",
                    dependency=SourceDependency(from_source="profiles"),
                    llm=[LLMStepConfig(type="summarize")],
                ),
            ],
        )
        result = validate_dataset_config(config, schema_cache=MOCK_SCHEMA)
        assert result.valid


class TestParamChecks:
    def test_input_key_conflicts_with_params(self):
        """input_key duplicated in params — static value will override dynamic."""
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(
                    id="profiles",
                    endpoint="/api/linkedin/user",
                    input_key="user",
                    params={"user": "static_value"},
                    from_file="users.txt",
                ),
            ],
        )
        result = validate_dataset_config(config, schema_cache=NO_SCHEMA)
        assert not result.valid
        err = result.errors[0]
        assert "sources[0].params.user" in err.location
        assert "conflicts with input_key" in err.message

    def test_input_key_not_in_params_is_valid(self):
        """input_key NOT in params — no conflict."""
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(
                    id="profiles",
                    endpoint="/api/linkedin/user",
                    input_key="user",
                    from_file="users.txt",
                ),
            ],
        )
        result = validate_dataset_config(config, schema_cache=NO_SCHEMA)
        assert result.valid

    def test_jinja_template_in_params(self):
        """Jinja-style {{ }} templates in params are not supported."""
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(
                    id="posts",
                    endpoint="/api/linkedin/user/posts",
                    params={"urn": "{{ profiles.output.urn.value }}", "count": 10},
                ),
            ],
        )
        result = validate_dataset_config(config, schema_cache=NO_SCHEMA)
        assert not result.valid
        err = [e for e in result.errors if "Jinja" in e.message][0]
        assert "sources[0].params.urn" in err.location
        assert "not supported" in err.message
        assert "dependency.field + input_key" in err.message

    def test_non_jinja_params_are_valid(self):
        """Normal string params without {{ }} should pass."""
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(
                    id="search",
                    endpoint="/api/linkedin/search/posts",
                    params={"keywords": "generative AI education", "count": 5},
                ),
            ],
        )
        result = validate_dataset_config(config, schema_cache=NO_SCHEMA)
        assert result.valid

    def test_both_input_key_conflict_and_jinja(self):
        """Config with both input_key in params AND Jinja template — two errors."""
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(
                    id="profiles",
                    endpoint="/api/linkedin/user",
                    params={"user": "test"},
                ),
                ApiSource(
                    id="posts",
                    endpoint="/api/linkedin/user/posts",
                    input_key="urn",
                    params={"urn": "{{ profiles.output.urn.value }}", "count": 3},
                    dependency=SourceDependency(
                        from_source="profiles",
                        field="urn.value",
                    ),
                ),
            ],
        )
        result = validate_dataset_config(config, schema_cache=NO_SCHEMA)
        assert not result.valid
        assert len(result.errors) == 2
        locations = [e.location for e in result.errors]
        assert "sources[1].params.urn" in locations[0]
        assert "sources[1].params.urn" in locations[1]
        messages = [e.message for e in result.errors]
        assert any("conflicts with input_key" in m for m in messages)
        assert any("Jinja" in m for m in messages)


class TestFindSimilar:
    def test_prefix_match(self):
        result = _find_similar("/api/linkedin/usr", ["/api/linkedin/user", "/api/instagram/user"])
        assert "/api/linkedin/user" in result

    def test_substring_match(self):
        result = _find_similar("urn.val", ["urn.type", "urn.value", "name"])
        assert "urn.value" in result

    def test_no_match(self):
        result = _find_similar("xyz", ["abc", "def"])
        assert result == []

    def test_max_results(self):
        candidates = ["/api/a/b", "/api/a/c", "/api/a/d", "/api/a/e"]
        result = _find_similar("/api/a", candidates, max_results=2)
        assert len(result) <= 2

    def test_shared_segments(self):
        result = _find_similar(
            "/api/linkedin/usr",
            ["/api/linkedin/user", "/api/twitter/user"],
        )
        # /api/linkedin/user shares "api" and "linkedin" segments (>=2)
        assert "/api/linkedin/user" in result


class TestValidationResult:
    def test_empty_is_valid(self):
        result = ValidationResult()
        assert result.valid

    def test_with_errors_is_invalid(self):
        from anysite.dataset.validator import ValidationError

        result = ValidationResult(
            errors=[ValidationError(location="test", message="bad")]
        )
        assert not result.valid

    def test_warnings_dont_invalidate(self):
        result = ValidationResult(warnings=["some warning"])
        assert result.valid
