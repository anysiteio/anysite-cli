"""Enhanced field selection with nested paths, wildcards, and presets."""

import re
from dataclasses import dataclass
from typing import Any, Literal


@dataclass
class FieldPath:
    """A single segment of a parsed field path."""

    type: Literal["key", "index", "wildcard"]
    value: str | int | None = None


def parse_field_path(path: str) -> list[FieldPath]:
    """Parse a field path string into segments.

    Supports:
        - Simple keys: "name"
        - Dot notation: "experience.company"
        - Array indexing: "experience[0].company"
        - Wildcards: "experience[*].company"

    Args:
        path: Field path string

    Returns:
        List of FieldPath segments
    """
    segments: list[FieldPath] = []
    # Split on dots, but handle brackets
    parts = re.split(r"\.(?![^\[]*\])", path)

    for part in parts:
        # Check for array index or wildcard: field[0] or field[*]
        match = re.match(r"^(\w+)\[(\*|\d+)\]$", part)
        if match:
            key, index = match.groups()
            segments.append(FieldPath(type="key", value=key))
            if index == "*":
                segments.append(FieldPath(type="wildcard"))
            else:
                segments.append(FieldPath(type="index", value=int(index)))
        else:
            segments.append(FieldPath(type="key", value=part))

    return segments


def extract_field(data: Any, segments: list[FieldPath]) -> Any:
    """Extract a value from data following field path segments.

    Args:
        data: Source data (dict, list, or scalar)
        segments: Parsed field path segments

    Returns:
        Extracted value, or None if path doesn't exist
    """
    current = data

    for i, segment in enumerate(segments):
        if current is None:
            return None

        if segment.type == "key":
            if isinstance(current, dict):
                current = current.get(segment.value)  # type: ignore[arg-type]
            else:
                return None

        elif segment.type == "index":
            if isinstance(current, list) and isinstance(segment.value, int):
                if segment.value < len(current):
                    current = current[segment.value]
                else:
                    return None
            else:
                return None

        elif segment.type == "wildcard":
            if isinstance(current, list):
                remaining = segments[i + 1:]
                if remaining:
                    return [extract_field(item, remaining) for item in current]
                return current
            else:
                return None

    return current


def filter_fields(data: dict[str, Any], field_paths: list[str]) -> dict[str, Any]:
    """Filter a dictionary to include only specified fields.

    Supports nested field paths with dot notation, array indexing,
    and wildcards.

    Args:
        data: Source dictionary
        field_paths: List of field path strings

    Returns:
        Filtered dictionary
    """
    if not field_paths:
        return data

    result: dict[str, Any] = {}

    for path in field_paths:
        segments = parse_field_path(path)

        if len(segments) == 1 and segments[0].type == "key":
            # Simple key access
            key = segments[0].value
            if isinstance(key, str) and key in data:
                result[key] = data[key]
        else:
            # Complex path - extract value
            value = extract_field(data, segments)
            if value is not None:
                # Store using the top-level key or flattened path
                top_key = segments[0].value
                if isinstance(top_key, str):
                    if len(segments) == 1:
                        result[top_key] = value
                    else:
                        # For nested paths, reconstruct nested structure
                        _set_nested(result, segments, value)

    return result


def _set_nested(target: dict[str, Any], segments: list[FieldPath], value: Any) -> None:
    """Set a value in a nested dict structure following field path segments."""
    current = target

    for i, segment in enumerate(segments[:-1]):
        if segment.type == "key":
            key = segment.value
            if isinstance(key, str):
                if key not in current:
                    # Look ahead to determine container type
                    next_seg = segments[i + 1]
                    if next_seg.type == "index" or next_seg.type == "wildcard":
                        current[key] = []
                    else:
                        current[key] = {}
                current = current[key]
        elif segment.type in ("index", "wildcard"):
            # For index/wildcard at intermediate level, just store value at parent
            break

    last = segments[-1]
    if last.type == "key" and isinstance(last.value, str):
        if isinstance(current, dict):
            current[last.value] = value
    elif isinstance(current, dict):
        # Store with the dotted path as key for complex paths
        path_str = ".".join(
            str(s.value) if s.type != "wildcard" else "*"
            for s in segments
        )
        current[path_str] = value


def exclude_fields(data: dict[str, Any], field_names: list[str]) -> dict[str, Any]:
    """Remove specified fields from a dictionary.

    Supports top-level and nested dot-notation keys.

    Args:
        data: Source dictionary
        field_names: List of field names to remove

    Returns:
        Dictionary with specified fields removed
    """
    import copy

    result = copy.deepcopy(data)

    for field_name in field_names:
        if "." in field_name:
            # Nested field removal
            parts = field_name.split(".")
            current = result
            for part in parts[:-1]:
                if isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    break
            else:
                if isinstance(current, dict) and parts[-1] in current:
                    del current[parts[-1]]
        else:
            result.pop(field_name, None)

    return result


# Built-in field presets
BUILT_IN_PRESETS: dict[str, list[str]] = {
    "minimal": ["name", "full_name", "headline", "url", "linkedin_url"],
    "contact": ["name", "full_name", "email", "phone", "linkedin_url", "twitter_url"],
    "recruiting": [
        "name", "full_name", "headline", "company", "current_company",
        "experience", "skills", "location", "linkedin_url",
    ],
}


def resolve_fields_preset(preset_name: str) -> list[str] | None:
    """Resolve a field preset name to a list of fields.

    Checks built-in presets first, then user config.

    Args:
        preset_name: Name of the preset

    Returns:
        List of field names, or None if preset not found
    """
    # Check built-in presets
    if preset_name in BUILT_IN_PRESETS:
        return BUILT_IN_PRESETS[preset_name]

    # Check user config
    try:
        from anysite.config.settings import get_config_value

        custom = get_config_value(f"presets.{preset_name}")
        if isinstance(custom, str):
            return [f.strip() for f in custom.split(",")]
        if isinstance(custom, list):
            return custom
    except Exception:
        pass

    return None
