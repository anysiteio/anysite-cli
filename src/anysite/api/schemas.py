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
CACHE_VERSION = "0.0.2"


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


def _extract_properties(
    spec: dict[str, Any],
    schema: dict[str, Any],
    *,
    prefix: str = "",
    max_depth: int = 3,
    _depth: int = 0,
) -> dict[str, str]:
    """Extract field -> type mapping, expanding nested objects with dot-notation.

    Nested object fields are expanded recursively up to ``max_depth`` levels.
    For example, ``urn`` (object with ``type`` and ``value``) becomes::

        {"urn": "object", "urn.type": "string", "urn.value": "string"}

    Array items with object type use ``field[].subfield`` notation.
    """
    schema = _resolve_schema(spec, schema)

    # Handle array of objects (most API responses)
    if schema.get("type") == "array" and "items" in schema:
        schema = _resolve_schema(spec, schema["items"])

    properties = schema.get("properties", {})
    result: dict[str, str] = {}
    for field_name, field_schema in properties.items():
        resolved = _resolve_schema(spec, field_schema)
        field_type = _simplify_type(resolved)
        full_name = f"{prefix}{field_name}"

        if field_type == "object" and "properties" in resolved and _depth < max_depth:
            result[full_name] = "object"
            result.update(
                _extract_properties(
                    spec,
                    resolved,
                    prefix=f"{full_name}.",
                    max_depth=max_depth,
                    _depth=_depth + 1,
                )
            )
        elif field_type == "array" and "items" in resolved and _depth < max_depth:
            items = _resolve_schema(spec, resolved["items"])
            if items.get("type") == "object" and "properties" in items:
                result[full_name] = "array[object]"
                result.update(
                    _extract_properties(
                        spec,
                        items,
                        prefix=f"{full_name}[].",
                        max_depth=max_depth,
                        _depth=_depth + 1,
                    )
                )
            else:
                result[full_name] = f"array[{_simplify_type(items)}]"
        else:
            result[full_name] = field_type
    return result


def _extract_input(spec: dict[str, Any], method_data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Extract input parameters from request body schema.

    Captures description, examples, and default from the **raw** field schema
    before resolving ``anyOf``/``oneOf`` (which strips parent-level metadata).
    For array params, resolves item types to show ``array[string]`` or
    ``array[object{type,value}]`` instead of bare ``array``.
    """
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
        # Capture metadata from RAW schema before anyOf/oneOf resolution
        raw_desc = field_schema.get("description", "")
        raw_examples = field_schema.get("examples")
        raw_default = field_schema.get("default")

        resolved_field = _resolve_schema(spec, field_schema)
        field_type = _simplify_type(resolved_field)

        # Prefer raw (parent-level) description, fall back to resolved
        description = raw_desc or resolved_field.get("description", "")

        # Enrich array types with item info
        if field_type == "array":
            field_type = _describe_array_type(spec, resolved_field)
        elif field_schema.get("type") == "array":
            # Raw schema is array but resolved (via anyOf) lost that info
            field_type = _describe_array_type(spec, field_schema)

        entry: dict[str, Any] = {
            "type": field_type,
            "required": field_name in required_fields,
            "description": description,
        }
        if raw_examples is not None:
            entry["examples"] = raw_examples
        if raw_default is not None:
            entry["default"] = raw_default

        result[field_name] = entry
    return result


def _describe_array_type(spec: dict[str, Any], schema: dict[str, Any]) -> str:
    """Return a descriptive type string for an array schema.

    Examples: ``array[string]``, ``array[object{type,value}]``.
    """
    items = schema.get("items")
    if not items:
        return "array"
    resolved_items = _resolve_schema(spec, items)
    item_type = _simplify_type(resolved_items)
    if item_type == "object" and "properties" in resolved_items:
        prop_names = list(resolved_items["properties"].keys())
        return f"array[object{{{','.join(prop_names)}}}]"
    return f"array[{item_type}]"


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


_SYNONYMS: dict[str, list[str]] = {
    "profile": ["user", "person", "people"],
    "user": ["profile", "person", "people"],
    "person": ["user", "profile", "people"],
    "people": ["user", "person", "profile", "search"],
    "company": ["organization", "business", "employer"],
    "organization": ["company", "business"],
    "job": ["career", "position", "vacancy", "hiring"],
    "career": ["job", "position"],
    "post": ["article", "content", "publication"],
    "article": ["post", "content"],
    "search": ["find", "lookup", "discover"],
    "find": ["search", "lookup"],
    "comment": ["reply", "response"],
    "follower": ["connection", "subscriber"],
    "connection": ["follower", "contact"],
}
"""Common synonyms for endpoint search — maps query words to alternatives."""


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

        if _matches_query(query_lower, searchable):
            results.append({
                "path": path,
                "description": description,
                "tags": info.get("tags", []),
            })

    return results


def _matches_query(query: str, searchable: str) -> bool:
    """Check if query matches searchable text.

    Supports exact substring match, prefix-word matching
    (e.g., "company" matches "companies"), and synonym expansion
    (e.g., "profile" also tries "user").
    """
    # Fast path: exact substring
    if query in searchable:
        return True

    # Split searchable into tokens (by / _ - and whitespace)
    import re

    tokens = re.split(r"[/\s_-]+", searchable)
    query_words = query.split()

    # Every query word (or one of its synonyms) must match a token
    return all(_word_or_synonym_matches(word, tokens) for word in query_words)


def _word_or_synonym_matches(word: str, tokens: list[str]) -> bool:
    """Check if a word or any of its synonyms matches a token."""
    if _word_matches_any(word, tokens):
        return True
    return any(_word_matches_any(syn, tokens) for syn in _SYNONYMS.get(word, []))


def _word_matches_any(word: str, tokens: list[str]) -> bool:
    """Check if a query word matches any token via shared prefix.

    Rules:
    - Exact prefix match in either direction (always matches)
    - Stem match: shared prefix must be >= 80% of the shorter word
      ("company"/"companies" share "compan" = 6/7 = 86% → match)
    """
    for token in tokens:
        if not token or len(token) < 3:
            continue
        if token.startswith(word) or word.startswith(token):
            return True
        # Shared prefix ratio — catches plural/verb forms
        common = 0
        for a, b in zip(word, token, strict=False):
            if a != b:
                break
            common += 1
        shorter = min(len(word), len(token))
        if shorter >= 4 and common / shorter >= 0.8:
            return True
    return False


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


def compact_output(output: dict[str, str]) -> dict[str, str]:
    """Collapse expanded dot-notation output to compact single-level representation.

    Converts the fully expanded output::

        {"urn": "object", "urn.type": "string", "urn.value": "string",
         "reactions": "array[object]", "reactions[].type": "string", ...}

    Into compact form::

        {"urn": "object{type,value}", "reactions": "array[object{type,count}]"}

    This preserves all field names while dramatically reducing token count
    for LLM/agent consumption.
    """
    # Collect immediate children for each top-level field
    children: dict[str, list[str]] = {}
    array_children: dict[str, list[str]] = {}

    for key in output:
        if "." not in key and "[]." not in key:
            continue
        # object children: "urn.type" -> parent="urn", child="type"
        if "[]." not in key and "." in key:
            parts = key.split(".", 1)
            parent = parts[0]
            child_rest = parts[1]
            # Only immediate children (no further dots)
            if "." not in child_rest and "[]." not in child_rest:
                children.setdefault(parent, []).append(child_rest)
        # array item children: "reactions[].type" -> parent="reactions", child="type"
        elif "[]." in key:
            parent, child_rest = key.split("[].", 1)
            if "." not in parent and "." not in child_rest and "[]." not in child_rest:
                array_children.setdefault(parent, []).append(child_rest)

    result: dict[str, str] = {}
    for key, type_str in output.items():
        # Skip nested keys
        if "." in key or "[]." in key:
            continue
        if type_str == "object" and key in children:
            result[key] = f"object{{{','.join(children[key])}}}"
        elif type_str == "array[object]" and key in array_children:
            result[key] = f"array[object{{{','.join(array_children[key])}}}]"
        else:
            result[key] = type_str
    return result


def convert_value(value: str, type_hint: str) -> str | int | bool | float | list | dict:
    """Convert a string value to the type specified in the schema.

    Args:
        value: Raw string value from CLI key=value arg.
        type_hint: Type from schema ('integer', 'boolean', 'number', 'string', 'array', etc.)

    Returns:
        Converted value.
    """
    if type_hint == "integer":
        return int(value)
    if type_hint == "boolean":
        return value.lower() in ("true", "1", "yes")
    if type_hint == "number":
        return float(value)
    if type_hint == "array" or type_hint.startswith("array["):
        # Parse JSON array
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass
        # Comma-separated → list, or single value → [value]
        if "," in value:
            return [v.strip() for v in value.split(",")]
        return [value]
    # Auto-detect JSON arrays/objects even without type hint
    if value.startswith("[") or value.startswith("{"):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            pass
    return value


def _extract_urn_example(examples: list[Any]) -> str | None:
    """Find the first URN-like string from parameter examples.

    Handles plain strings (``"activity:7234..."``) and dicts with a
    ``"urn"`` key (``{"slug": "...", "urn": "activity:7234..."}``).
    """
    for ex in examples:
        if isinstance(ex, dict):
            ex = ex.get("urn")
        if isinstance(ex, str) and ":" in ex:
            return ex
    return None


def get_urn_prefix(
    endpoint: str, param_name: str, *, schema_cache: dict[str, Any] | None = None
) -> str | None:
    """Extract the expected URN prefix for a parameter from schema examples.

    Returns a prefix like ``"activity:"`` or ``"urn:li:fsd_profile:"``
    that should be prepended to raw values.  Returns ``None`` when the
    parameter has no URN-like examples.
    """
    if schema_cache is None:
        schema_cache = load_cache() or {}
    endpoints = schema_cache.get("endpoints", {})
    ep_info = endpoints.get(endpoint)
    if not ep_info:
        return None
    param_info = ep_info.get("input", {}).get(param_name)
    if not param_info:
        return None
    examples = param_info.get("examples")
    if not examples or not isinstance(examples, list):
        return None
    urn_example = _extract_urn_example(examples)
    if not urn_example:
        return None
    last_colon = urn_example.rfind(":")
    if last_colon <= 0:
        return None
    return urn_example[: last_colon + 1]


def normalize_urn_value(value: str, prefix: str) -> str:
    """Prepend *prefix* to *value* unless it already contains one.

    Safe to call on values that are already fully-qualified — they are
    returned unchanged.
    """
    if value.startswith(prefix):
        return value
    if ":" in value:
        return value  # already has some prefix
    return prefix + value
