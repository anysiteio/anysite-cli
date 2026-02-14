"""Dataset configuration validator.

Fast validation (<0.1s, no API calls) for dataset YAML configs.
Checks dependency graph, filter expressions, and LLM add specs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from anysite.dataset.models import ApiSource, DatasetConfig, EnrichFieldSpec


@dataclass
class ValidationError:
    """A single validation error."""

    location: str
    message: str


@dataclass
class ValidationResult:
    """Result of dataset config validation."""

    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return len(self.errors) == 0


def validate_dataset_config(config: DatasetConfig) -> ValidationResult:
    """Validate a dataset config deeply.

    Checks:
    1. Dependency graph (topological sort)
    2. All filter expressions (source.filter, transform.filter, db_load.filter)
    3. LLM add specs
    4. Common issues (warnings)
    """
    result = ValidationResult()

    # 1. Dependency graph
    try:
        config.topological_sort()
    except Exception as e:
        result.errors.append(
            ValidationError(location="sources", message=f"Dependency graph error: {e}")
        )

    # 2. Validate all filter expressions
    from anysite.dataset.transformer import validate_filter

    for i, source in enumerate(config.sources):
        # Source-level filter
        if source.filter:
            errors = validate_filter(source.filter)
            for err in errors:
                result.errors.append(
                    ValidationError(location=f"sources[{i}].filter", message=err)
                )

        # Transform filter
        if source.transform and source.transform.filter:
            errors = validate_filter(source.transform.filter)
            for err in errors:
                result.errors.append(
                    ValidationError(location=f"sources[{i}].transform.filter", message=err)
                )

        # DB load filter
        if source.db_load and source.db_load.filter:
            errors = validate_filter(source.db_load.filter)
            for err in errors:
                result.errors.append(
                    ValidationError(location=f"sources[{i}].db_load.filter", message=err)
                )

        # 3. LLM add specs
        if source.llm:
            for j, step in enumerate(source.llm):
                if step.type == "enrich" and step.add:
                    _validate_add_specs(
                        step.add,
                        f"sources[{i}].llm[{j}].add",
                        result,
                    )

        # 4. Warnings
        if isinstance(source, ApiSource):
            if source.parallel > 10:
                result.warnings.append(
                    f"sources[{i}]: parallel={source.parallel} is high, consider 3-5"
                )
            if source.from_file:
                from_path = Path(source.from_file)
                if not from_path.is_absolute() and not from_path.exists():
                    result.warnings.append(
                        f"sources[{i}]: from_file '{source.from_file}' "
                        f"not found (may be relative to config dir)"
                    )

    return result


def _validate_add_specs(
    specs: list[Any],
    location: str,
    result: ValidationResult,
) -> None:
    """Validate LLM enrich add specs."""
    for k, spec in enumerate(specs):
        if isinstance(spec, EnrichFieldSpec):
            continue  # Already validated by Pydantic
        if isinstance(spec, str):
            if ":" not in spec:
                result.errors.append(
                    ValidationError(
                        location=f"{location}[{k}]",
                        message=f"Invalid add spec '{spec}', expected 'name:type_or_values'",
                    )
                )
        else:
            result.errors.append(
                ValidationError(
                    location=f"{location}[{k}]",
                    message=f"Invalid add spec type: {type(spec).__name__}",
                )
            )
