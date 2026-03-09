"""Tests for API endpoint dependency graph."""

from unittest.mock import patch

import pytest

from anysite.api.graph import (
    _detect_input_id_type,
    _extract_keywords,
    _infer_produces,
    _learn_linkedin_entity_types,
    _resolve_urn_literal,
    _singularize,
    build_graph,
    get_endpoint_connections,
    load_graph_cache,
    save_graph_cache,
    search_graph,
)

# ── Minimal spec fixtures ────────────────────────────────────────────────────


def _make_spec(paths: dict, schemas: dict | None = None) -> dict:
    """Build a minimal OpenAPI-like spec."""
    return {
        "paths": paths,
        "components": {"schemas": schemas or {}},
    }


def _make_endpoint(
    schema_name: str,
    response_schema_name: str | None = None,
    description: str = "",
) -> dict:
    """Build a minimal POST endpoint dict."""
    ep: dict = {
        "description": description,
        "requestBody": {
            "content": {
                "application/json": {
                    "schema": {"$ref": f"#/components/schemas/{schema_name}"},
                },
            },
        },
        "responses": {},
    }
    if response_schema_name:
        ep["responses"]["200"] = {
            "content": {
                "application/json": {
                    "schema": {"$ref": f"#/components/schemas/{response_schema_name}"},
                },
            },
        }
    return ep


MINIMAL_SPEC = _make_spec(
    paths={
        "/api/linkedin/user/posts": {
            "post": _make_endpoint(
                "UserPostsInput",
                response_schema_name="LinkedinUserPost",
                description="Get user posts\n**Price:** 5 credits",
            ),
        },
        "/api/linkedin/post/comments": {
            "post": _make_endpoint(
                "PostCommentsInput",
                response_schema_name="LinkedinPostComment",
                description="Get post comments",
            ),
        },
        "/api/linkedin/user": {
            "post": _make_endpoint(
                "UserInput",
                response_schema_name="LinkedinUser",
                description="Get LinkedIn profile",
            ),
        },
    },
    schemas={
        "UserPostsInput": {
            "properties": {
                "urn": {"$ref": "#/components/schemas/LinkedinURN_Literal_fsd_profile__"},
            },
            "required": ["urn"],
        },
        "PostCommentsInput": {
            "properties": {
                "urn": {"$ref": "#/components/schemas/LinkedinURN_Literal_activity__"},
            },
            "required": ["urn"],
        },
        "UserInput": {
            "properties": {
                "user": {"type": "string", "description": "Username"},
            },
            "required": ["user"],
        },
        "LinkedinURN_Literal_fsd_profile__": {"type": "string"},
        "LinkedinURN_Literal_activity__": {"type": "string"},
        "LinkedinUserPost": {
            "properties": {
                "urn": {"anyOf": [{"$ref": "#/components/schemas/LinkedinURN_Literal_activity__"}]},
                "author": {"$ref": "#/components/schemas/LinkedinPostAuthor"},
            },
        },
        "LinkedinPostComment": {
            "properties": {
                "text": {"type": "string"},
                "author": {"$ref": "#/components/schemas/LinkedinCommentAuthor"},
            },
        },
        "LinkedinUser": {
            "properties": {
                "urn": {"$ref": "#/components/schemas/LinkedinURN"},
                "name": {"type": "string"},
            },
        },
        "LinkedinURN": {"type": "string"},
        "LinkedinPostAuthor": {
            "properties": {
                "urn": {"$ref": "#/components/schemas/LinkedinURN_Literal_fsd_profile__"},
            },
        },
        "LinkedinCommentAuthor": {
            "properties": {
                "urn": {"$ref": "#/components/schemas/LinkedinURN_Literal_fsd_profile__"},
            },
        },
    },
)


# ── Helper tests ─────────────────────────────────────────────────────────────


class TestSingularize:
    def test_companies(self):
        assert _singularize("companies") == "company"

    def test_users(self):
        assert _singularize("users") == "user"

    def test_already_singular(self):
        assert _singularize("post") == "post"

    def test_ses(self):
        assert _singularize("addresses") == "address"

    def test_double_s(self):
        assert _singularize("access") == "access"


class TestResolveUrnLiteral:
    def test_fsd_profile(self):
        assert _resolve_urn_literal('{"$ref": "#/.../LinkedinURN_Literal_fsd_profile__"}') == "fsd_profile"

    def test_activity(self):
        assert _resolve_urn_literal('{"$ref": "#/.../LinkedinURN_Literal_activity__"}') == "activity"

    def test_company(self):
        assert _resolve_urn_literal('{"$ref": "#/.../LinkedinURN_Literal_company__"}') == "company"

    def test_fsd_company_company(self):
        assert _resolve_urn_literal('{"$ref": "#/.../LinkedinURN_Literal_fsd_company_company__"}') == "company"

    def test_no_match(self):
        assert _resolve_urn_literal('{"type": "string"}') is None

    def test_geo(self):
        assert _resolve_urn_literal('{"$ref": "#/.../LinkedinURN_Literal_geo__"}') == "geo"


class TestExtractKeywords:
    def test_from_path(self):
        kws = _extract_keywords("/api/linkedin/user/posts", "")
        assert "linkedin" in kws
        assert "user" in kws
        assert "posts" in kws

    def test_from_description(self):
        kws = _extract_keywords("/api/test", "Get comments on a post")
        assert "comments" in kws
        assert "post" in kws

    def test_strips_markdown(self):
        kws = _extract_keywords("/api/test", "Get data **Price:** 5 credits")
        assert "data" in kws
        # Markdown bold content is stripped
        assert "price" not in kws


class TestLearnLinkedinEntityTypes:
    def test_learns_entities(self):
        entities = _learn_linkedin_entity_types(
            MINIMAL_SPEC, MINIMAL_SPEC["components"]["schemas"]
        )
        assert entities.get("user") == "fsd_profile"
        assert entities.get("post") == "activity"


class TestDetectInputIdType:
    def test_urn_literal(self):
        prop = {"$ref": "#/components/schemas/LinkedinURN_Literal_fsd_profile__"}
        result = _detect_input_id_type(prop, "urn", "", "/api/linkedin/user", {})
        assert result == "li:fsd_profile"

    def test_platform_prefix(self):
        prop = {"type": "string"}
        result = _detect_input_id_type(prop, "user", "username", "/api/instagram/user", {})
        assert result == "ig:user"

    def test_no_match(self):
        prop = {"type": "string"}
        result = _detect_input_id_type(prop, "count", "number of results", "/api/linkedin/search", {})
        assert result is None


class TestInferProduces:
    def test_typed_urn(self):
        schemas = MINIMAL_SPEC["components"]["schemas"]
        entities = {"user": "fsd_profile", "post": "activity"}
        produces = _infer_produces("LinkedinUserPost", "/api/linkedin/user/posts", schemas, entities)
        assert "li:activity" in produces
        assert "li:fsd_profile" in produces  # from nested author

    def test_schema_name_analysis(self):
        """Generic URN -> entity type from schema name."""
        schemas = {
            "LinkedinUser": {
                "properties": {
                    "urn": {"$ref": "#/components/schemas/LinkedinURN"},
                },
            },
            "LinkedinURN": {"type": "string"},
        }
        entities = {"user": "fsd_profile"}
        produces = _infer_produces("LinkedinUser", "/api/linkedin/user", schemas, entities)
        assert "li:fsd_profile" in produces

    def test_no_response_schema(self):
        entities = {"user": "fsd_profile"}
        produces = _infer_produces(None, "/api/linkedin/user", {}, entities)
        assert "li:fsd_profile" in produces


# ── Build graph tests ────────────────────────────────────────────────────────


class TestBuildGraph:
    def test_creates_nodes_and_edges(self):
        graph = build_graph(MINIMAL_SPEC)
        assert "/api/linkedin/user/posts" in graph["nodes"]
        assert "/api/linkedin/post/comments" in graph["nodes"]
        assert "/api/linkedin/user" in graph["nodes"]
        assert len(graph["edges"]) > 0

    def test_nodes_have_expected_fields(self):
        graph = build_graph(MINIMAL_SPEC)
        node = graph["nodes"]["/api/linkedin/user/posts"]
        assert node["platform"] == "linkedin"
        assert node["method"] == "POST"
        assert node["cost"] == "5 credits"
        assert len(node["inputs"]) > 0
        assert isinstance(node["keywords"], list)

    def test_edges_connect_producers_to_consumers(self):
        graph = build_graph(MINIMAL_SPEC)
        edges = graph["edges"]
        # user/posts produces li:activity, post/comments needs li:activity
        activity_edges = [e for e in edges if e["id_type"] == "li:activity"]
        assert any(
            e["from"] == "/api/linkedin/user/posts" and e["to"] == "/api/linkedin/post/comments"
            for e in activity_edges
        )


# ── Search tests ─────────────────────────────────────────────────────────────


class TestSearchGraph:
    @pytest.fixture()
    def graph(self):
        return build_graph(MINIMAL_SPEC)

    def test_matches_by_keyword(self, graph):
        result = search_graph("comments", graph)
        paths = [m["path"] for m in result["matches"]]
        assert "/api/linkedin/post/comments" in paths

    def test_and_logic(self, graph):
        result = search_graph("user posts", graph)
        paths = [m["path"] for m in result["matches"]]
        assert "/api/linkedin/user/posts" in paths
        # "post/comments" should NOT match because it doesn't have "user"
        assert "/api/linkedin/post/comments" not in paths

    def test_scoring_entity_boost(self, graph):
        result = search_graph("post", graph)
        # Both endpoints match "post" but post/comments has it in entity
        paths = [m["path"] for m in result["matches"]]
        assert len(paths) >= 1

    def test_upstream_found(self, graph):
        result = search_graph("comments", graph)
        upstream_paths = [u["path"] for u in result["upstream"]]
        # user/posts produces li:activity which comments needs
        assert "/api/linkedin/user/posts" in upstream_paths

    def test_downstream_found(self, graph):
        result = search_graph("user posts", graph)
        downstream_paths = [d["path"] for d in result["downstream"]]
        # user/posts produces li:activity, post/comments consumes it
        assert "/api/linkedin/post/comments" in downstream_paths

    def test_no_results(self, graph):
        result = search_graph("nonexistent_xyz", graph)
        assert result["matches"] == []
        assert result["upstream"] == []
        assert result["downstream"] == []

    def test_search_has_usage(self, graph):
        result = search_graph("comments", graph)
        assert "usage" in result
        assert "matches" in result["usage"]
        assert "chaining" in result["usage"]

    def test_auto_loads_cache(self):
        graph_data = build_graph(MINIMAL_SPEC)
        with patch("anysite.api.graph.load_graph_cache", return_value=graph_data):
            result = search_graph("comments")
            assert len(result["matches"]) > 0


# ── Cache I/O tests ──────────────────────────────────────────────────────────


class TestCacheIO:
    def test_save_load_roundtrip(self, tmp_path):
        graph_data = {"nodes": {"a": {"id": "a"}}, "edges": []}
        cache_file = tmp_path / "graph.json"
        with (
            patch("anysite.config.paths.get_graph_cache_path", return_value=cache_file),
            patch("anysite.config.paths.get_config_dir", return_value=tmp_path),
        ):
            save_graph_cache(graph_data)
            loaded = load_graph_cache()
        assert loaded == graph_data

    def test_load_missing_returns_none(self, tmp_path):
        cache_file = tmp_path / "missing.json"
        with patch("anysite.config.paths.get_graph_cache_path", return_value=cache_file):
            assert load_graph_cache() is None


# ── Endpoint connections tests ───────────────────────────────────────────────


class TestGetEndpointConnections:
    def test_returns_connections(self):
        graph = build_graph(MINIMAL_SPEC)
        conns = get_endpoint_connections("/api/linkedin/post/comments", graph)
        assert conns is not None
        assert len(conns["upstream"]) > 0

    def test_returns_none_without_graph(self):
        with patch("anysite.api.graph.load_graph_cache", return_value=None):
            assert get_endpoint_connections("/api/test") is None

    def test_returns_none_for_unknown_endpoint(self):
        graph = build_graph(MINIMAL_SPEC)
        assert get_endpoint_connections("/api/nonexistent", graph) is None


# ── Fallback search tests ───────────────────────────────────────────────────


class TestFallbackSearch:
    def test_fallback_when_no_graph(self):
        mock_cache = {
            "endpoints": {
                "/api/linkedin/user": {"description": "Get profile", "tags": ["linkedin"]},
                "/api/linkedin/post": {"description": "Get post", "tags": ["linkedin"]},
            }
        }
        with (
            patch("anysite.api.graph.load_graph_cache", return_value=None),
            patch("anysite.api.schemas.load_cache", return_value=mock_cache),
        ):
            result = search_graph("user")
            assert len(result["matches"]) == 1
            assert result["matches"][0]["path"] == "/api/linkedin/user"
            assert result["upstream"] == []
            assert result["downstream"] == []

    def test_fallback_has_usage(self):
        mock_cache = {
            "endpoints": {
                "/api/linkedin/user": {"description": "Get profile", "tags": ["linkedin"]},
            }
        }
        with (
            patch("anysite.api.graph.load_graph_cache", return_value=None),
            patch("anysite.api.schemas.load_cache", return_value=mock_cache),
        ):
            result = search_graph("user")
            assert "usage" in result
            assert "next_step" in result["usage"]

    def test_fallback_no_cache(self):
        with (
            patch("anysite.api.graph.load_graph_cache", return_value=None),
            patch("anysite.api.schemas.load_cache", return_value=None),
        ):
            result = search_graph("user")
            assert result["matches"] == []
