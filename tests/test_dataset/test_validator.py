"""Tests for dataset config validator."""

from __future__ import annotations

import pytest

from anysite.dataset.models import (
    ApiSource,
    DatasetConfig,
    DbLoadConfig,
    LLMStepConfig,
    LlmSource,
    SourceDependency,
    TransformConfig,
)
from anysite.dataset.validator import ValidationResult, validate_dataset_config


class TestValidateDatasetConfig:
    def test_valid_config(self):
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(id="profiles", endpoint="/api/linkedin/user"),
            ],
        )
        result = validate_dataset_config(config)
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
        result = validate_dataset_config(config)
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
        result = validate_dataset_config(config)
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
        result = validate_dataset_config(config)
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
        result = validate_dataset_config(config)
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
        result = validate_dataset_config(config)
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
        result = validate_dataset_config(config)
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
        result = validate_dataset_config(config)
        assert not result.valid
        assert len(result.errors) == 2


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
