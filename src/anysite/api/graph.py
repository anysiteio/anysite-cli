"""Dependency graph for API endpoint discovery.

Builds a graph from the OpenAPI spec where nodes are endpoints and edges
represent data flow: endpoint A produces IDs that endpoint B needs as input.
Search returns matched endpoints plus upstream providers and downstream
consumers in a single query.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# Platform → ID prefix mapping (naming convention, not domain knowledge)
PLATFORM_PREFIX: dict[str, str] = {
    "instagram": "ig",
    "twitter": "tw",
    "reddit": "reddit",
    "youtube": "yt",
    "yc": "yc",
    "sec": "sec",
    "crunchbase": "crunchbase",
}


# ── Internal helpers ─────────────────────────────────────────────────────────


def _singularize(word: str) -> str:
    """Naive English singularization: companies->company, users->user."""
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith("ses"):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _compound_matches(word: str, searchable: str) -> bool:
    """Try splitting word into two halves that both appear in searchable."""
    for i in range(2, len(word) - 1):
        if word[:i] in searchable and word[i:] in searchable:
            return True
    return False


def _word_matches(word: str, searchable: str) -> bool:
    """Check if word matches via exact substring or compound split."""
    return word in searchable or _compound_matches(word, searchable)


def _split_camel(name: str) -> list[str]:
    """Split CamelCase into lowercase words: LinkedinUserPost -> ['linkedin', 'user', 'post']."""
    parts = re.findall(r"[A-Z][a-z]*|[a-z]+", name)
    return [p.lower() for p in parts]


def _resolve_urn_literal(raw: str) -> str | None:
    """Extract URN literal type from a JSON string.

    LinkedinURN_Literal_fsd_profile__ -> fsd_profile
    LinkedinURN_Literal_activity__ -> activity
    """
    m = re.search(r"LinkedinURN_Literal_(\w+?)__", raw)
    if not m:
        return None
    literal = m.group(1)
    if literal == "fsd_profile":
        return "fsd_profile"
    if literal in ("fsd_company_company", "company"):
        return "company"
    if literal == "fsd_company":
        return "fsd_company"
    if literal in ("activity", "activity_comment"):
        return "activity"
    return literal


def _learn_linkedin_entity_types(
    spec: dict[str, Any], schemas: dict[str, Any]
) -> dict[str, str]:
    """Auto-learn entity->URN mapping from typed URN inputs in the spec.

    Example results: {"user": "fsd_profile", "post": "activity", ...}
    """
    entity_map: dict[str, str] = {}

    for path, methods in spec.get("paths", {}).items():
        if "/linkedin/" not in path:
            continue
        segments = path.replace("/api/linkedin/", "").split("/")

        for _method, op in methods.items():
            if not isinstance(op, dict):
                continue
            rb = op.get("requestBody", {}).get("content", {})
            for _ct, si in rb.items():
                ref = si.get("schema", {}).get("$ref", "")
                if not ref:
                    continue
                sname = ref.split("/")[-1]
                s = schemas.get(sname, {})
                for pname, pdef in s.get("properties", {}).items():
                    raw = json.dumps(pdef)
                    urn_type = _resolve_urn_literal(raw)
                    if not urn_type:
                        continue

                    # From path: /user/posts, urn: fsd_profile -> "user" = fsd_profile
                    if pname == "urn" and len(segments) >= 2:
                        entity = _singularize(segments[-2])
                        entity_map.setdefault(entity, urn_type)

                    # From field name: location: geo -> "location" = geo
                    if pname not in ("urn", "timeout", "count", "sort"):
                        base = pname.split("_")[-1]
                        key = _singularize(base)
                        entity_map.setdefault(key, urn_type)

    return entity_map


def _detect_input_id_type(
    prop_def: dict[str, Any],
    prop_name: str,
    description: str,
    path: str,
    linkedin_entities: dict[str, str],
) -> str | None:
    """Determine the ID type for an input parameter."""
    raw = json.dumps(prop_def)
    desc = description.lower()

    # LinkedIn: typed URN ref
    urn_type = _resolve_urn_literal(raw)
    if urn_type:
        return f"li:{urn_type}"

    # LinkedIn: URN type from description
    if "/linkedin/" in path:
        for keyword, li_type in linkedin_entities.items():
            if keyword in desc and "urn" in desc:
                return f"li:{li_type}"

    # Non-LinkedIn: derive from platform + field name
    parts = path.replace("/api/", "").split("/")
    platform = parts[0] if parts else ""
    prefix = PLATFORM_PREFIX.get(platform)

    if prefix:
        if prop_name in (
            "user", "post", "video", "channel", "username",
            "post_url", "document_url", "company",
        ):
            return f"{prefix}:{prop_name}"
        if prefix == "tw" and "account" in desc:
            return "tw:user"

    return None


def _iter_refs(pdef: dict[str, Any]) -> list[str]:
    """Collect all $ref strings from a property definition."""
    refs: list[str] = []
    ref = pdef.get("$ref", "")
    if ref:
        refs.append(ref)
    for item in pdef.get("anyOf", []):
        ref = item.get("$ref", "")
        if ref:
            refs.append(ref)
    return refs


def _get_nested_schemas(schema: dict[str, Any], field_name: str) -> list[str]:
    """Get schema names for a nested object field."""
    pdef = schema.get("properties", {}).get(field_name, {})
    names: list[str] = []
    ref = pdef.get("$ref", "")
    if ref:
        names.append(ref.split("/")[-1])
    for item in pdef.get("anyOf", []):
        ref = item.get("$ref", "")
        if ref:
            names.append(ref.split("/")[-1])
    return names


def _get_response_schema_name(op: dict[str, Any]) -> str | None:
    """Extract the response schema name from a 200 response."""
    resp = op.get("responses", {}).get("200", {}).get("content", {})
    for _ct, si in resp.items():
        schema = si.get("schema", {})
        ref = schema.get("$ref", "") or schema.get("items", {}).get("$ref", "")
        if ref:
            return ref.split("/")[-1]
    return None


def _infer_produces(
    response_schema: str | None,
    path: str,
    schemas: dict[str, Any],
    linkedin_entities: dict[str, str],
) -> set[str]:
    """Determine which ID types an endpoint produces in its output."""
    produces: set[str] = set()
    if not response_schema:
        # Fallback: infer from path for endpoints without response schema
        if "/linkedin/" in path:
            segments = path.replace("/api/linkedin/", "").split("/")
            for seg in segments:
                key = _singularize(seg)
                if key in linkedin_entities:
                    produces.add(f"li:{linkedin_entities[key]}")
                    break
        return produces

    s = schemas.get(response_schema, {})
    if not s:
        return produces

    parts = path.replace("/api/", "").split("/")
    platform = parts[0] if parts else ""
    prefix = PLATFORM_PREFIX.get(platform)

    # A. Typed URN refs in schema fields
    for _pname, pdef in s.get("properties", {}).items():
        for ref_src in _iter_refs(pdef):
            if "URN_Literal" in ref_src:
                urn_type = _resolve_urn_literal(ref_src)
                if urn_type:
                    produces.add(f"li:{urn_type}")

    # B. LinkedIn: generic LinkedinURN -> determine type by schema name
    if "/linkedin/" in path:
        has_generic_urn = any(
            "LinkedinURN" in json.dumps(pdef) and "Literal" not in json.dumps(pdef)
            for pname, pdef in s.get("properties", {}).items()
            if pname in ("urn", "internal_id")
        )
        if has_generic_urn:
            words = _split_camel(response_schema)
            skip = {"linkedin", "search", "management", "sales", "navigator"}
            meaningful = [w for w in words if w not in skip]
            if meaningful:
                primary = _singularize(meaningful[-1])
                if primary in linkedin_entities:
                    produces.add(f"li:{linkedin_entities[primary]}")

    # C. Nested author/user/creator -> find their ID types
    for pname in ("user", "author", "creator"):
        nested_schemas = _get_nested_schemas(s, pname)
        for ns_name in nested_schemas:
            ns = schemas.get(ns_name, {})
            ns_props = ns.get("properties", {})
            for _np, nd in ns_props.items():
                for ref_src in _iter_refs(nd):
                    if "URN_Literal" in ref_src:
                        urn_type = _resolve_urn_literal(ref_src)
                        if urn_type:
                            produces.add(f"li:{urn_type}")

            if "/linkedin/" in path:
                has_generic = any(
                    "LinkedinURN" in json.dumps(nd) and "Literal" not in json.dumps(nd)
                    for np, nd in ns_props.items()
                    if np in ("urn", "internal_id")
                )
                if has_generic and "user" in linkedin_entities:
                    produces.add(f"li:{linkedin_entities['user']}")
            elif prefix:
                for np, nd in ns_props.items():
                    if prefix == "reddit" and np == "name" and nd.get("type") == "string":
                        produces.add("reddit:username")
                    elif np in ("id", "alias") and nd.get("type") == "string":
                        if prefix == "yt":
                            produces.add(f"{prefix}:channel")
                        elif prefix != "reddit":
                            produces.add(f"{prefix}:user")

    # D. Non-LinkedIn: determine by schema fields
    if prefix:
        schema_words = _split_camel(response_schema)
        valid_entities: dict[str, set[str]] = {
            "ig": {"user", "post"},
            "tw": {"user"},
            "reddit": {"post_url", "username"},
            "yt": {"video", "channel"},
            "yc": {"company"},
            "sec": {"document_url"},
        }
        platform_entities = valid_entities.get(prefix, set())

        for pname, pdef in s.get("properties", {}).items():
            if pname == "id" and pdef.get("type") == "string":
                for w in reversed(schema_words):
                    entity = _singularize(w)
                    if entity in platform_entities:
                        produces.add(f"{prefix}:{entity}")
                        break

            if (
                pname == "alias"
                and pdef.get("type") == "string"
                and "user" in platform_entities
                and any(w in ("user",) for w in schema_words)
            ):
                produces.add(f"{prefix}:user")

            if (
                pname == "url"
                and pdef.get("type") == "string"
                and "post" in schema_words
                and prefix == "reddit"
            ):
                produces.add("reddit:post_url")

            if pname == "author" and prefix == "reddit":
                    if pdef.get("type") == "string":
                        produces.add("reddit:username")
                    for ns_name in _get_nested_schemas(s, pname):
                        ns = schemas.get(ns_name, {})
                        if any(
                            ns.get("properties", {}).get(f, {}).get("type") == "string"
                            for f in ("alias", "name")
                        ):
                            produces.add("reddit:username")

            if pname in ("slug", "company_slug") and prefix == "yc":
                produces.add("yc:company")

            if pname == "document_url" and prefix == "sec":
                produces.add("sec:document_url")

    return produces


def _extract_keywords(path: str, description: str) -> list[str]:
    """Extract search keywords from endpoint path and description."""
    words: set[str] = set()
    parts = path.replace("/api/", "").replace("_", " ").split("/")
    for p in parts:
        for w in p.split():
            if len(w) > 2:
                words.add(w.lower())
    desc_clean = re.sub(r"\*\*.*?\*\*", "", description)
    desc_clean = re.sub(r"[^a-zA-Z ]", " ", desc_clean)
    for w in desc_clean.split():
        if len(w) > 2:
            words.add(w.lower())
    return sorted(words)


# ── Public API ───────────────────────────────────────────────────────────────


def build_graph(spec: dict[str, Any]) -> dict[str, Any]:
    """Build dependency graph from raw OpenAPI spec.

    Nodes are API endpoints; edges connect endpoints where one produces
    IDs that another requires as input.

    Args:
        spec: Full OpenAPI spec dict (as returned by fetching openapi.json).

    Returns:
        Dict with ``nodes`` (dict of node_id -> node) and ``edges`` (list of edge dicts).
    """
    schemas = spec.get("components", {}).get("schemas", {})

    # Phase 1: learn LinkedIn entity->URN mapping
    linkedin_entities = _learn_linkedin_entity_types(spec, schemas)

    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    # Phase 2+3: build nodes
    for path, methods in spec.get("paths", {}).items():
        if not path.startswith("/api/"):
            continue

        for method, op in methods.items():
            if not isinstance(op, dict):
                continue
            node_id = path
            description = op.get("description", op.get("summary", ""))

            parts = path.replace("/api/", "").split("/")
            platform = parts[0] if parts else "unknown"
            entity = "/".join(parts[1:]) if len(parts) > 1 else parts[0]

            # Inputs
            inputs: list[dict[str, Any]] = []
            rb = op.get("requestBody", {}).get("content", {})
            for _ct, si in rb.items():
                ref = si.get("schema", {}).get("$ref", "")
                if ref:
                    schema_name = ref.split("/")[-1]
                    s = schemas.get(schema_name, {})
                    required = s.get("required", [])
                    for pname, pdef in s.get("properties", {}).items():
                        if pname == "timeout":
                            continue
                        desc = pdef.get("description", "")
                        id_type = _detect_input_id_type(
                            pdef, pname, desc, path, linkedin_entities
                        )
                        inputs.append({
                            "name": pname,
                            "description": desc[:200],
                            "required": pname in required,
                            "id_type": id_type,
                        })

            # Outputs
            response_schema = _get_response_schema_name(op)
            produces = _infer_produces(response_schema, path, schemas, linkedin_entities)

            cost = ""
            cost_match = re.search(r"\*\*Price:\*\*\s*(.+?)(?:\n|$)", description)
            if cost_match:
                cost = cost_match.group(1).strip()

            nodes[node_id] = {
                "id": node_id,
                "method": method.upper(),
                "platform": platform,
                "entity": entity,
                "description": description.split("\n")[0],
                "cost": cost,
                "inputs": inputs,
                "produces": sorted(produces),
                "keywords": _extract_keywords(path, description),
            }

    # Phase 4: edges
    for node_b_id, node_b in nodes.items():
        for inp in node_b["inputs"]:
            if not inp["id_type"]:
                continue
            id_type = inp["id_type"]
            for node_a_id, node_a in nodes.items():
                if node_a_id == node_b_id:
                    continue
                if id_type in node_a["produces"]:
                    edges.append({
                        "from": node_a_id,
                        "to": node_b_id,
                        "via_field": inp["name"],
                        "id_type": id_type,
                        "label": f'{id_type} → {inp["name"]}',
                    })

    return {"nodes": nodes, "edges": edges}


def save_graph_cache(data: dict[str, Any]) -> Path:
    """Save graph to ~/.anysite/graph.json.

    Returns:
        Path where the graph was saved.
    """
    from anysite.config.paths import ensure_config_dir, get_graph_cache_path

    ensure_config_dir()
    cache_path = get_graph_cache_path()
    cache_path.write_text(json.dumps(data, indent=2))
    return cache_path


def load_graph_cache() -> dict[str, Any] | None:
    """Load cached graph from disk.

    Returns:
        Graph data dict, or None if cache doesn't exist.
    """
    from anysite.config.paths import get_graph_cache_path

    cache_path = get_graph_cache_path()
    if not cache_path.exists():
        return None
    try:
        return json.loads(cache_path.read_text())  # type: ignore[no-any-return]
    except (json.JSONDecodeError, OSError):
        return None


def search_graph(
    query: str, graph: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Search graph by keywords with upstream/downstream context.

    All query words must match (AND logic). If no graph is provided,
    loads from cache. Falls back to keyword-only search over schema.json
    if graph.json is missing.

    Args:
        query: Space-separated search keywords.
        graph: Pre-loaded graph dict. Auto-loads cache if None.

    Returns:
        Dict with ``query``, ``matches``, ``upstream``, ``downstream``.
    """
    if graph is None:
        graph = load_graph_cache()

    # Fallback: no graph cache -> keyword-only search over schema.json
    if graph is None:
        return _fallback_search(query)

    query_words = query.lower().split()
    nodes = graph["nodes"]
    edges = graph["edges"]

    # Keyword matching (all words must match)
    matches: dict[str, dict[str, Any]] = {}
    for node_id, node in nodes.items():
        searchable = (
            node["id"].lower() + " "
            + node["entity"].lower() + " "
            + " ".join(node["keywords"]) + " "
            + node["description"].lower()
        )
        matched_words = 0
        score = 0
        for w in query_words:
            if w in searchable:
                matched_words += 1
                score += 1
                if w in node["entity"].lower():
                    score += 2
                if w in node["id"].lower():
                    score += 1
            elif _compound_matches(w, searchable):
                matched_words += 1
                score += 0.5
        if matched_words == len(query_words):
            matches[node_id] = {**node, "_score": score}

    # Upstream: who provides data for matched endpoints
    upstream: list[dict[str, Any]] = []
    seen_upstream: set[str] = set()
    for edge in edges:
        if edge["to"] in matches and edge["from"] not in matches:
            from_id = edge["from"]
            if from_id not in seen_upstream:
                seen_upstream.add(from_id)
                upstream.append({
                    "path": from_id,
                    "description": nodes[from_id]["description"],
                    "provides": [],
                })
            # Find the upstream entry and add provides info
            for up in upstream:
                if up["path"] == from_id:
                    up["provides"].append({
                        "id_type": edge["id_type"],
                        "for": edge["to"],
                        "via_field": edge["via_field"],
                    })
                    break

    # Downstream: what matched endpoints enable
    downstream: list[dict[str, Any]] = []
    seen_downstream: set[str] = set()
    for edge in edges:
        if edge["from"] in matches and edge["to"] not in matches:
            to_id = edge["to"]
            if to_id not in seen_downstream:
                seen_downstream.add(to_id)
                downstream.append({
                    "path": to_id,
                    "description": nodes[to_id]["description"],
                    "receives": [],
                })
            for down in downstream:
                if down["path"] == to_id:
                    down["receives"].append({
                        "id_type": edge["id_type"],
                        "from": edge["from"],
                        "via_field": edge["via_field"],
                    })
                    break

    # Sort matches by score descending
    sorted_matches = sorted(matches.values(), key=lambda x: -x["_score"])
    # Clean up internal fields for output
    result_matches: list[dict[str, Any]] = []
    for m in sorted_matches:
        result_matches.append({
            "path": m["id"],
            "description": m["description"],
            "platform": m["platform"],
            "cost": m["cost"],
            "inputs": [
                {k: v for k, v in inp.items() if k != "description"}
                for inp in m["inputs"]
                if inp.get("required")
            ],
            "produces": m["produces"],
        })

    return {
        "query": query,
        "usage": {
            "matches": "Endpoints matching your query. Call via `anysite api <path> key=value`.",
            "inputs": "Required parameters. `id_type` (e.g. `li:activity`) means the value is a URN — get it from an upstream endpoint's response.",
            "produces": "ID types in this endpoint's response. Pass them as inputs to downstream endpoints.",
            "upstream": "Endpoints that output IDs needed by matched endpoints. Call these first to obtain the required URNs.",
            "downstream": "Endpoints that accept IDs produced by matched endpoints. Call these after to continue the pipeline.",
            "chaining": "Pipeline order: upstream → matched → downstream. Each step passes an ID type from one endpoint's output to the next endpoint's input.",
            "next_step": "Run `anysite describe <path>` for full input/output schema of any endpoint.",
        },
        "matches": result_matches,
        "upstream": upstream,
        "downstream": downstream,
    }


def _fallback_search(query: str) -> dict[str, Any]:
    """Keyword-only search over schema.json when graph is unavailable."""
    from anysite.api.schemas import load_cache

    cache = load_cache()
    if cache is None:
        return {
            "query": query,
            "usage": {
                "matches": "Endpoints matching your query. Call via `anysite api <path> key=value`.",
                "next_step": "Run `anysite schema update` to enable dependency-aware search with upstream/downstream context.",
            },
            "matches": [],
            "upstream": [],
            "downstream": [],
        }

    query_words = query.lower().split()
    matches: list[dict[str, Any]] = []

    for path, info in cache.get("endpoints", {}).items():
        description = info.get("description", "")
        tags = " ".join(info.get("tags", []))
        searchable = f"{path} {description} {tags}".lower()
        if all(_word_matches(w, searchable) for w in query_words):
            matches.append({
                "path": path,
                "description": description.split("\n")[0],
                "platform": path.replace("/api/", "").split("/")[0] if path.startswith("/api/") else "",
                "cost": "",
                "inputs": [],
                "produces": [],
            })

    return {
        "query": query,
        "usage": {
            "matches": "Endpoints matching your query. Call via `anysite api <path> key=value`.",
            "next_step": "Run `anysite schema update` to enable dependency-aware search with upstream/downstream context.",
        },
        "matches": matches,
        "upstream": [],
        "downstream": [],
    }


def get_endpoint_connections(
    endpoint: str, graph: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """Get upstream/downstream connections for a single endpoint.

    Args:
        endpoint: API endpoint path (e.g. /api/linkedin/user).
        graph: Pre-loaded graph dict. Auto-loads cache if None.

    Returns:
        Dict with ``upstream`` and ``downstream`` lists, or None if
        graph is unavailable or endpoint not found.
    """
    if graph is None:
        graph = load_graph_cache()
    if graph is None:
        return None

    nodes = graph.get("nodes", {})
    edges = graph.get("edges", [])

    if endpoint not in nodes:
        return None

    upstream: list[dict[str, Any]] = []
    seen_up: set[str] = set()
    for edge in edges:
        if edge["to"] == endpoint:
            from_id = edge["from"]
            if from_id not in seen_up:
                seen_up.add(from_id)
                upstream.append({
                    "path": from_id,
                    "description": nodes[from_id]["description"],
                    "provides": [],
                })
            for up in upstream:
                if up["path"] == from_id:
                    up["provides"].append({
                        "id_type": edge["id_type"],
                        "via_field": edge["via_field"],
                    })
                    break

    downstream: list[dict[str, Any]] = []
    seen_down: set[str] = set()
    for edge in edges:
        if edge["from"] == endpoint:
            to_id = edge["to"]
            if to_id not in seen_down:
                seen_down.add(to_id)
                downstream.append({
                    "path": to_id,
                    "description": nodes[to_id]["description"],
                    "receives": [],
                })
            for down in downstream:
                if down["path"] == to_id:
                    down["receives"].append({
                        "id_type": edge["id_type"],
                        "via_field": edge["via_field"],
                    })
                    break

    return {"upstream": upstream, "downstream": downstream}
