"""Dataset configuration validator.

Fast validation (<0.1s, no API calls) for dataset YAML configs.
Checks dependency graph, filter expressions, LLM add specs, and schema-aware checks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from anysite.dataset.models import ApiSource, DatasetConfig, EnrichFieldSpec, SqlSource


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


def validate_dataset_config(
    config: DatasetConfig,
    *,
    schema_cache: dict[str, Any] | None = None,
) -> ValidationResult:
    """Validate a dataset config deeply.

    Checks:
    1. Dependency graph (topological sort)
    2. All filter expressions (source.filter, transform.filter, db_load.filter)
    3. LLM add specs
    4. Common issues (warnings)
    5. Schema-aware checks (if schema cache available)

    Args:
        config: Dataset configuration to validate.
        schema_cache: Pre-loaded schema cache dict. If not provided, loaded from disk.
            If None (not found), schema-aware checks are silently skipped.
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

        # 4. Param checks (ApiSource only)
        if isinstance(source, ApiSource):
            # input_key duplicated in params — static value will override dynamic
            if source.input_key and source.input_key in source.params:
                result.errors.append(
                    ValidationError(
                        location=f"sources[{i}].params.{source.input_key}",
                        message=(
                            f"param '{source.input_key}' conflicts with input_key — "
                            f"remove it from params, the value from "
                            f"dependency.field or from_file is passed via input_key "
                            f"automatically"
                        ),
                    )
                )

            # Jinja-like {{ }} templates in params — not supported
            for param_name, param_val in source.params.items():
                if isinstance(param_val, str) and "{{" in param_val and "}}" in param_val:
                    result.errors.append(
                        ValidationError(
                            location=f"sources[{i}].params.{param_name}",
                            message=(
                                f"Jinja-style template '{param_val}' is not supported. "
                                f"Use dependency.field + input_key for dynamic values"
                            ),
                        )
                    )

            # Warnings
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

        # SQL source checks
        if isinstance(source, SqlSource) and source.query_file:
            qf = Path(source.query_file)
            if not qf.is_absolute() and not qf.exists():
                result.warnings.append(
                    f"sources[{i}]: query_file '{source.query_file}' "
                    f"not found (may be relative to config dir)"
                )

    # 5. Schema-aware checks
    if schema_cache is None:
        from anysite.api.schemas import load_cache

        schema_cache = load_cache()

    if schema_cache is not None and schema_cache.get("endpoints"):
        _validate_schema_aware(config, result, schema_cache)

    return result


def _validate_schema_aware(
    config: DatasetConfig,
    result: ValidationResult,
    schema_cache: dict[str, Any],
) -> None:
    """Run schema-aware validation using the cached OpenAPI spec.

    Checks endpoints, required params, input_key, and dependency.field paths.
    Only applies to ApiSource — LlmSource/UnionSource are skipped.
    """
    endpoints = schema_cache.get("endpoints", {})
    source_map = {s.id: s for s in config.sources}

    for i, source in enumerate(config.sources):
        if not isinstance(source, ApiSource):
            continue

        # --- Check 1: endpoint exists ---
        endpoint_info = endpoints.get(source.endpoint)
        if endpoint_info is None:
            similar = _find_similar(source.endpoint, list(endpoints.keys()))
            msg = f"Endpoint '{source.endpoint}' not found in schema cache"
            if similar:
                msg += f". Similar: {', '.join(similar)}"
            else:
                msg += ". Run 'anysite schema update' to refresh"
            result.errors.append(
                ValidationError(location=f"sources[{i}].endpoint", message=msg)
            )
            continue  # Can't check params/fields without endpoint info

        input_params = endpoint_info.get("input", {})

        # --- Check 2: required params provided ---
        covered_params = set(source.params.keys())
        if source.input_key:
            covered_params.add(source.input_key)
        if source.input_template:
            covered_params.update(source.input_template.keys())

        for param_name, param_info in input_params.items():
            if not param_info.get("required"):
                continue
            if param_name in covered_params:
                continue
            if param_info.get("default") is not None:
                continue
            desc = param_info.get("description", "")
            examples = param_info.get("examples", [])
            example_str = f", example: '{examples[0]}'" if examples else ""
            result.errors.append(
                ValidationError(
                    location=f"sources[{i}].params",
                    message=(
                        f"Missing required param '{param_name}' for "
                        f"{source.endpoint} ({desc}{example_str})"
                    ),
                )
            )

        # --- Check 3: input_key valid ---
        if source.input_key and source.input_key not in input_params:
            available = list(input_params)
            result.errors.append(
                ValidationError(
                    location=f"sources[{i}].input_key",
                    message=(
                        f"input_key '{source.input_key}' is not a valid param for "
                        f"{source.endpoint}. Available: {', '.join(available)}"
                    ),
                )
            )

        # --- Check 4: dependency.field exists in parent output ---
        if source.dependency and source.dependency.field:
            parent_id = source.dependency.from_source
            parent = source_map.get(parent_id)
            if parent and isinstance(parent, ApiSource):
                parent_info = endpoints.get(parent.endpoint)
                if parent_info:
                    parent_output = parent_info.get("output", {})
                    dep_field = source.dependency.field
                    normalized = re.sub(r"\[\d+\]", "[]", dep_field)
                    # Also try bare form (strip []) for implicit array paths
                    bare = normalized.replace("[]", "")
                    bare_output = {
                        k.replace("[]", ""): v for k, v in parent_output.items()
                    }
                    if (
                        normalized not in parent_output
                        and bare not in bare_output
                    ):
                        if _has_object_prefix(normalized, parent_output):
                            result.warnings.append(
                                f"sources[{i}].dependency.field: '{dep_field}' extends "
                                f"beyond schema depth — will be resolved at runtime"
                            )
                        else:
                            similar = _find_similar(
                                dep_field, list(parent_output.keys())
                            )
                            msg = (
                                f"dependency.field '{dep_field}' not found in "
                                f"{parent.endpoint} output"
                            )
                            if similar:
                                msg += f". Similar: {', '.join(similar)}"
                            result.errors.append(
                                ValidationError(
                                    location=f"sources[{i}].dependency.field",
                                    message=msg,
                                )
                            )


def _has_object_prefix(field: str, output: dict[str, str]) -> bool:
    """Check if a prefix of field exists in output as an unexpanded object type.

    Only returns True when the prefix key has no children in the schema —
    meaning the schema truncated expansion at that depth.  If children exist,
    the schema *did* expand the object, so a miss is a genuine mismatch.

    Comparisons strip ``[]`` markers so that bare dot-notation paths
    (e.g. ``companies.name``) match schema keys with array markers
    (e.g. ``companies[].name``).
    """
    field_bare = field.replace("[]", "")
    for key, type_str in output.items():
        if "object" not in type_str:
            continue
        key_bare = key.replace("[]", "")
        if not field_bare.startswith(key_bare + "."):
            continue
        # Check whether this key was expanded (has children in the schema)
        has_children = any(
            k != key and k.replace("[]", "").startswith(key_bare + ".")
            for k in output
        )
        if not has_children:
            return True
    return False


def _find_similar(target: str, candidates: list[str], max_results: int = 3) -> list[str]:
    """Find similar strings by prefix length, substring, or shared segments."""
    target_lower = target.lower()
    scored: list[tuple[float, str]] = []
    for c in candidates:
        c_lower = c.lower()
        if c_lower.startswith(target_lower) or target_lower.startswith(c_lower):
            scored.append((0, c))  # exact prefix
        elif target_lower in c_lower or c_lower in target_lower:
            scored.append((1, c))  # substring
        else:
            # Common prefix ratio — catches typos like "usr" vs "user"
            common = 0
            for a, b in zip(target_lower, c_lower, strict=False):
                if a != b:
                    break
                common += 1
            ratio = common / max(len(target_lower), len(c_lower))
            if ratio >= 0.7:
                scored.append((1.5 - ratio, c))  # higher ratio → lower score
            else:
                # Shared path segments
                target_parts = set(target_lower.strip("/").split("/"))
                c_parts = set(c_lower.strip("/").split("/"))
                if len(target_parts & c_parts) >= 2:
                    scored.append((2, c))
    scored.sort(key=lambda x: x[0])
    return [s[1] for s in scored[:max_results]]


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
