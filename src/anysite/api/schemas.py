"""Dynamic OpenAPI schema cache for endpoint discovery.

Fetches the OpenAPI spec from the API, resolves $ref references,
and caches a compact representation of all endpoints with their
input parameters and output fields.

Used by `anysite describe` and `anysite schema update` commands.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

OPENAPI_URL = "https://api.anysite.io/openapi.json"
CACHE_VERSION = "0.0.1"


def get_cache_path() -> Path:
    """Get the schema cache file path."""
    from anysite.config.paths import get_schema_cache_path

    return get_schema_cache_path()


def resolve_ref(spec: dict[str, Any], ref_path: str) -> dict[str, Any]:
    """Resolve a $ref path within the OpenAPI spec.

    Args:
        spec: Full OpenAPI spec dict.
        ref_path: Reference string like '#/components/schemas/UserProfile'.

    Returns:
        The resolved schema dict.
    """
    parts = ref_path.lstrip("#/").split("/")
    node: Any = spec
    for part in parts:
        node = node[part]
    return node  # type: ignore[no-any-return]


def _resolve_schema(spec: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """Recursively resolve all $ref in a schema."""
    if "$ref" in schema:
        resolved = resolve_ref(spec, schema["$ref"])
        return _resolve_schema(spec, resolved)

    if "allOf" in schema:
        merged: dict[str, Any] = {}
        for sub in schema["allOf"]:
            resolved_sub = _resolve_schema(spec, sub)
            merged.update(resolved_sub.get("properties", {}))
        return {"type": "object", "properties": merged}

    if "anyOf" in schema or "oneOf" in schema:
        variants = schema.get("anyOf") or schema.get("oneOf", [])
        # Pick first non-null variant
        for variant in variants:
            resolved_v = _resolve_schema(spec, variant)
            if resolved_v.get("type") != "null":
                return resolved_v
        return variants[0] if variants else schema

    return schema


def _simplify_type(schema: dict[str, Any]) -> str:
    """Convert a resolved schema to a simple type string."""
    if "anyOf" in schema or "oneOf" in schema:
        variants = schema.get("anyOf") or schema.get("oneOf", [])
        types = []
        for v in variants:
            t = v.get("type", "object")
            if t != "null":
                types.append(t)
        return types[0] if types else "object"

    return schema.get("type", "object")


def _extract_properties(spec: dict[str, Any], schema: dict[str, Any]) -> dict[str, str]:
    """Extract flat field -> type mapping from a resolved schema."""
    schema = _resolve_schema(spec, schema)

    # Handle array of objects (most API responses)
    if schema.get("type") == "array" and "items" in schema:
        schema = _resolve_schema(spec, schema["items"])

    properties = schema.get("properties", {})
    result: dict[str, str] = {}
    for field_name, field_schema in properties.items():
        resolved_field = _resolve_schema(spec, field_schema)
        result[field_name] = _simplify_type(resolved_field)
    return result


def _extract_input(spec: dict[str, Any], method_data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Extract input parameters from request body schema."""
    request_body = method_data.get("requestBody", {})
    content = request_body.get("content", {})
    json_content = content.get("application/json", {})
    body_schema = json_content.get("schema", {})

    if not body_schema:
        return {}

    resolved = _resolve_schema(spec, body_schema)
    properties = resolved.get("properties", {})
    required_fields = set(resolved.get("required", []))

    result: dict[str, dict[str, Any]] = {}
    for field_name, field_schema in properties.items():
        resolved_field = _resolve_schema(spec, field_schema)
        result[field_name] = {
            "type": _simplify_type(resolved_field),
            "required": field_name in required_fields,
            "description": resolved_field.get("description", ""),
        }
    return result


def extract_endpoint_info(
    spec: dict[str, Any], method_data: dict[str, Any]
) -> dict[str, Any]:
    """Extract input/output info for a single endpoint.

    Args:
        spec: Full OpenAPI spec.
        method_data: The method dict (e.g. spec['paths'][path]['post']).

    Returns:
        Dict with description, tags, input, output.
    """
    description = method_data.get("description", "") or method_data.get("summary", "")
    tags = method_data.get("tags", [])

    # Extract input params
    input_params = _extract_input(spec, method_data)

    # Extract output fields from 200 response
    responses = method_data.get("responses", {})
    success_resp = responses.get("200", responses.get("201", {}))
    resp_content = success_resp.get("content", {})
    resp_json = resp_content.get("application/json", {})
    resp_schema = resp_json.get("schema", {})

    output_fields = _extract_properties(spec, resp_schema) if resp_schema else {}

    return {
        "description": description,
        "tags": tags,
        "input": input_params,
        "output": output_fields,
    }


def fetch_and_parse_openapi(url: str | None = None) -> dict[str, Any]:
    """Fetch the OpenAPI spec and parse all endpoints into a compact cache format.

    Args:
        url: OpenAPI spec URL. Defaults to OPENAPI_URL.

    Returns:
        Cache dict with version, updated_at, and endpoints.
    """
    spec_url = url or OPENAPI_URL
    response = httpx.get(spec_url, timeout=30, follow_redirects=True)
    response.raise_for_status()
    spec = response.json()

    endpoints: dict[str, Any] = {}

    for path, path_data in spec.get("paths", {}).items():
        # Only process POST endpoints (API pattern)
        for method in ("post", "get"):
            if method not in path_data:
                continue
            method_data = path_data[method]
            try:
                info = extract_endpoint_info(spec, method_data)
                endpoints[path] = info
            except (KeyError, TypeError):
                # Skip endpoints that can't be parsed
                continue

    return {
        "version": CACHE_VERSION,
        "updated_at": datetime.now(UTC).isoformat(),
        "endpoints": endpoints,
    }


def save_cache(data: dict[str, Any]) -> Path:
    """Save schema cache to disk.

    Returns:
        Path where the cache was saved.
    """
    from anysite.config.paths import ensure_config_dir

    ensure_config_dir()
    cache_path = get_cache_path()
    cache_path.write_text(json.dumps(data, indent=2))
    return cache_path


def load_cache() -> dict[str, Any] | None:
    """Load schema cache from disk.

    Returns:
        Cached data dict, or None if cache doesn't exist.
    """
    cache_path = get_cache_path()
    if not cache_path.exists():
        return None
    try:
        return json.loads(cache_path.read_text())  # type: ignore[no-any-return]
    except (json.JSONDecodeError, OSError):
        return None


def _normalize_command(command: str) -> str:
    """Convert shorthand command to API path.

    Examples:
        'linkedin.user' -> '/api/linkedin/user'
        '/api/linkedin/user' -> '/api/linkedin/user'
        'linkedin.search-users' -> '/api/linkedin/search/users'
        'linkedin.company-employees' -> '/api/linkedin/company/employees'
    """
    if command.startswith("/"):
        return command
    # linkedin.search-users -> /api/linkedin/search/users
    parts = command.replace(".", "/").replace("-", "/")
    return f"/api/{parts}"


def get_schema(command: str) -> dict[str, Any] | None:
    """Get schema info for an endpoint.

    Args:
        command: Command identifier like 'linkedin.user' or '/api/linkedin/user'.

    Returns:
        Dict with description, tags, input, output — or None if not found.
    """
    cache = load_cache()
    if cache is None:
        return None

    endpoints = cache.get("endpoints", {})
    path = _normalize_command(command)

    if path in endpoints:
        return endpoints[path]  # type: ignore[no-any-return]

    # Try fuzzy match: look for path ending
    for ep_path, ep_data in endpoints.items():
        if ep_path.endswith(path.lstrip("/")):
            return ep_data  # type: ignore[no-any-return]

    return None


def search_endpoints(query: str) -> list[dict[str, Any]]:
    """Search endpoints by keyword in path, description, or tags.

    Args:
        query: Search string.

    Returns:
        List of dicts with path, description, tags.
    """
    cache = load_cache()
    if cache is None:
        return []

    query_lower = query.lower()
    results = []

    for path, info in cache.get("endpoints", {}).items():
        description = info.get("description", "")
        tags = " ".join(info.get("tags", []))
        searchable = f"{path} {description} {tags}".lower()

        if query_lower in searchable:
            results.append({
                "path": path,
                "description": description,
                "tags": info.get("tags", []),
            })

    return results


def list_endpoints() -> list[dict[str, Any]]:
    """List all cached endpoints.

    Returns:
        List of dicts with path and description.
    """
    cache = load_cache()
    if cache is None:
        return []

    return [
        {"path": path, "description": info.get("description", "")}
        for path, info in cache.get("endpoints", {}).items()
    ]


def convert_value(value: str, type_hint: str) -> str | int | bool | float:
    """Convert a string value to the type specified in the schema.

    Args:
        value: Raw string value from CLI key=value arg.
        type_hint: Type from schema ('integer', 'boolean', 'number', 'string', etc.)

    Returns:
        Converted value.
    """
    if type_hint == "integer":
        return int(value)
    if type_hint == "boolean":
        return value.lower() in ("true", "1", "yes")
    if type_hint == "number":
        return float(value)
    return value
