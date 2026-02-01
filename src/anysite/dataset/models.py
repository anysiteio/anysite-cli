"""Pydantic models for dataset YAML configuration."""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, PrivateAttr, field_validator, model_validator

from anysite.dataset.errors import CircularDependencyError, SourceNotFoundError

# ---------------------------------------------------------------------------
# New models for transform / export / schedule / notifications
# ---------------------------------------------------------------------------


class TransformConfig(BaseModel):
    """Per-source transform: filter → select fields → add columns."""

    filter: str | None = Field(default=None, description="Filter expression (e.g., '.employee_count > 10')")
    fields: list[str] = Field(default_factory=list, description="Fields to keep (empty = all)")
    add_columns: dict[str, Any] = Field(default_factory=dict, description="Static columns to add")


class ExportDestination(BaseModel):
    """Per-source export destination (file or webhook)."""

    type: Literal["file", "webhook"] = Field(description="Export type")
    path: str | None = Field(default=None, description="Output file path (file type)")
    format: str = Field(default="jsonl", description="File format: json, jsonl, csv")
    url: str | None = Field(default=None, description="Webhook URL (webhook type)")
    headers: dict[str, str] = Field(default_factory=dict, description="HTTP headers for webhook")

    @model_validator(mode="after")
    def validate_type_fields(self) -> ExportDestination:
        if self.type == "file" and not self.path:
            raise ValueError("File export requires 'path'")
        if self.type == "webhook" and not self.url:
            raise ValueError("Webhook export requires 'url'")
        return self


class ScheduleConfig(BaseModel):
    """Cron-based schedule for dataset collection."""

    cron: str = Field(description="Cron expression (e.g., '0 9 * * MON')")


class WebhookNotification(BaseModel):
    """A single webhook notification endpoint."""

    url: str = Field(description="Webhook URL")
    headers: dict[str, str] = Field(default_factory=dict, description="HTTP headers")


class NotificationsConfig(BaseModel):
    """Notification webhooks for collection events."""

    on_complete: list[WebhookNotification] = Field(default_factory=list)
    on_failure: list[WebhookNotification] = Field(default_factory=list)


class SourceDependency(BaseModel):
    """Dependency on another source's output."""

    from_source: str = Field(description="Source ID to depend on")
    field: str | None = Field(
        default=None,
        description="Field to extract from parent records (dot notation)",
    )
    match_by: str | None = Field(
        default=None,
        description="Field for fuzzy matching by name",
    )
    dedupe: bool = Field(default=False, description="Deduplicate extracted values")


class DbLoadConfig(BaseModel):
    """Configuration for loading a source into a relational database."""

    table: str | None = Field(default=None, description="Override table name (default: source id)")
    fields: list[str] = Field(default_factory=list, description="Fields to include (empty = all)")
    exclude: list[str] = Field(
        default_factory=lambda: ["_input_value", "_parent_source"],
        description="Fields to exclude (default: provenance metadata)",
    )


class DatasetSource(BaseModel):
    """A single data source within a dataset."""

    id: str = Field(description="Unique source identifier")
    endpoint: str = Field(description="API endpoint path (e.g., /api/linkedin/search/users)")
    params: dict[str, Any] = Field(default_factory=dict, description="Static API parameters")
    dependency: SourceDependency | None = Field(
        default=None,
        description="Dependency on another source",
    )
    input_key: str | None = Field(
        default=None,
        description="Parameter name for dependent input values",
    )
    input_template: dict[str, Any] | None = Field(
        default=None,
        description="Template for input value — use {value} placeholder (e.g., {type: company, value: '{value}'})",
    )
    from_file: str | None = Field(
        default=None,
        description="Path to input file (CSV/JSONL/text) with values to iterate over",
    )
    file_field: str | None = Field(
        default=None,
        description="Column name to extract from CSV input file",
    )
    parallel: int = Field(default=1, ge=1, description="Parallel requests for dependent collection")
    rate_limit: str | None = Field(default=None, description="Rate limit (e.g., '10/s')")
    on_error: str = Field(default="skip", description="Error handling: stop or skip")
    db_load: DbLoadConfig | None = Field(
        default=None,
        description="Database loading configuration (optional)",
    )
    transform: TransformConfig | None = Field(
        default=None,
        description="Post-collection transform (filter/fields/add_columns)",
    )
    export: list[ExportDestination] = Field(
        default_factory=list,
        description="Export destinations (file/webhook) applied after Parquet write",
    )

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, v: str) -> str:
        if not v.startswith("/"):
            raise ValueError(f"Endpoint must start with '/', got: {v}")
        return v


class StorageConfig(BaseModel):
    """Storage configuration for dataset output."""

    format: str = Field(default="parquet", description="Storage format")
    path: str = Field(default="./data/", description="Base directory for data files")
    partition_by: list[str] = Field(
        default_factory=lambda: ["source_id", "collected_date"],
        description="Partition dimensions",
    )


class DatasetConfig(BaseModel):
    """Top-level dataset configuration parsed from YAML."""

    name: str = Field(description="Dataset name")
    description: str = Field(default="", description="Dataset description")
    sources: list[DatasetSource] = Field(description="Data sources to collect")
    storage: StorageConfig = Field(default_factory=StorageConfig)
    schedule: ScheduleConfig | None = Field(default=None, description="Collection schedule")
    notifications: NotificationsConfig | None = Field(default=None, description="Webhook notifications")

    _config_dir: Path | None = PrivateAttr(default=None)

    @field_validator("sources")
    @classmethod
    def validate_unique_ids(cls, v: list[DatasetSource]) -> list[DatasetSource]:
        ids = [s.id for s in v]
        dupes = [sid for sid in ids if ids.count(sid) > 1]
        if dupes:
            raise ValueError(f"Duplicate source IDs: {set(dupes)}")
        return v

    @classmethod
    def from_yaml(cls, path: Path) -> DatasetConfig:
        """Load dataset configuration from a YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f)
        config = cls.model_validate(data)
        config._config_dir = path.resolve().parent
        return config

    def get_source(self, source_id: str) -> DatasetSource | None:
        """Get a source by ID."""
        for s in self.sources:
            if s.id == source_id:
                return s
        return None

    def topological_sort(self) -> list[DatasetSource]:
        """Sort sources by dependency order using Kahn's algorithm.

        Returns:
            List of sources in execution order (independent first).

        Raises:
            CircularDependencyError: If dependencies form a cycle.
            SourceNotFoundError: If a dependency references a non-existent source.
        """
        source_map = {s.id: s for s in self.sources}

        # Build adjacency: in_degree counts and adjacency list
        in_degree: dict[str, int] = {s.id: 0 for s in self.sources}
        dependents: dict[str, list[str]] = {s.id: [] for s in self.sources}

        for source in self.sources:
            if source.dependency:
                parent_id = source.dependency.from_source
                if parent_id not in source_map:
                    raise SourceNotFoundError(parent_id, source.id)
                in_degree[source.id] += 1
                dependents[parent_id].append(source.id)

        # Kahn's algorithm
        queue: deque[str] = deque()
        for sid, degree in in_degree.items():
            if degree == 0:
                queue.append(sid)

        result: list[DatasetSource] = []
        while queue:
            sid = queue.popleft()
            result.append(source_map[sid])
            for dep_id in dependents[sid]:
                in_degree[dep_id] -= 1
                if in_degree[dep_id] == 0:
                    queue.append(dep_id)

        if len(result) != len(self.sources):
            # Find the cycle
            remaining = [s.id for s in self.sources if s.id not in {r.id for r in result}]
            raise CircularDependencyError(remaining)

        return result

    def storage_path(self) -> Path:
        """Resolve the storage base path.

        Relative paths are resolved against the directory containing the
        YAML config file (set by ``from_yaml``).  Absolute paths and
        programmatic configs (no config dir) use the path as-is.
        """
        p = Path(self.storage.path)
        if not p.is_absolute() and self._config_dir is not None:
            return self._config_dir / p
        return p
