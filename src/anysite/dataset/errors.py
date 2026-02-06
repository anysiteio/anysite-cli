"""Dataset-specific error classes."""

from anysite.api.errors import AnysiteError


class DatasetError(AnysiteError):
    """Base error for dataset operations."""

    error_code = "DATASET_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)


class CircularDependencyError(DatasetError):
    """Raised when source dependencies form a cycle."""

    error_code = "CIRCULAR_DEPENDENCY"

    def __init__(self, sources: list[str]) -> None:
        self.sources = sources
        cycle = " -> ".join(sources)
        super().__init__(f"Circular dependency detected: {cycle}")


class SourceNotFoundError(DatasetError):
    """Raised when a dependency references a non-existent source."""

    error_code = "SOURCE_NOT_FOUND"

    def __init__(self, source_id: str, referenced_by: str) -> None:
        self.source_id = source_id
        self.referenced_by = referenced_by
        super().__init__(f"Source '{source_id}' referenced by '{referenced_by}' does not exist")
