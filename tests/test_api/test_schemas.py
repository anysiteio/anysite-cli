"""Tests for URN auto-normalization utilities in schemas module."""

from anysite.api.schemas import _extract_urn_example, get_urn_prefix, normalize_urn_value


class TestExtractUrnExample:
    def test_plain_string(self):
        examples = ["activity:7234173400267538433"]
        assert _extract_urn_example(examples) == "activity:7234173400267538433"

    def test_full_urn_string(self):
        examples = ["urn:li:fsd_profile:ACoAACmguogBIdbijM6YpcIganWLJ67yKyV5kd4"]
        assert _extract_urn_example(examples) == "urn:li:fsd_profile:ACoAACmguogBIdbijM6YpcIganWLJ67yKyV5kd4"

    def test_dict_with_urn_key(self):
        examples = [{"slug": "some-slug", "urn": "activity:7234173400267538433"}]
        assert _extract_urn_example(examples) == "activity:7234173400267538433"

    def test_no_urn_example(self):
        examples = ["satyanadella"]
        assert _extract_urn_example(examples) is None

    def test_empty_list(self):
        assert _extract_urn_example([]) is None

    def test_dict_without_urn_key(self):
        examples = [{"exact search": "macadamia ltd", "example": "microsoft"}]
        assert _extract_urn_example(examples) is None

    def test_mixed_picks_first_urn(self):
        examples = ["no-colon", {"urn": "activity:999"}]
        assert _extract_urn_example(examples) == "activity:999"


class TestGetUrnPrefix:
    MOCK_CACHE = {
        "endpoints": {
            "/api/linkedin/post": {
                "input": {
                    "urn": {
                        "type": "string",
                        "required": True,
                        "examples": [
                            {"slug": "some-slug", "urn": "activity:7234173400267538433"}
                        ],
                    },
                },
            },
            "/api/linkedin/user/posts": {
                "input": {
                    "urn": {
                        "type": "string",
                        "required": True,
                        "examples": [
                            "urn:li:fsd_profile:ACoAACmguogBIdbijM6YpcIganWLJ67yKyV5kd4"
                        ],
                    },
                    "count": {"type": "integer", "required": True},
                },
            },
            "/api/linkedin/user": {
                "input": {
                    "user": {
                        "type": "string",
                        "required": True,
                        "examples": ["satyanadella"],
                    },
                },
            },
        },
    }

    def test_short_urn_prefix(self):
        prefix = get_urn_prefix("/api/linkedin/post", "urn", schema_cache=self.MOCK_CACHE)
        assert prefix == "activity:"

    def test_full_urn_prefix(self):
        prefix = get_urn_prefix(
            "/api/linkedin/user/posts", "urn", schema_cache=self.MOCK_CACHE
        )
        assert prefix == "urn:li:fsd_profile:"

    def test_no_prefix_for_non_urn_param(self):
        prefix = get_urn_prefix("/api/linkedin/user", "user", schema_cache=self.MOCK_CACHE)
        assert prefix is None

    def test_unknown_endpoint(self):
        prefix = get_urn_prefix("/api/nonexistent", "urn", schema_cache=self.MOCK_CACHE)
        assert prefix is None

    def test_unknown_param(self):
        prefix = get_urn_prefix("/api/linkedin/post", "foo", schema_cache=self.MOCK_CACHE)
        assert prefix is None

    def test_empty_cache(self):
        prefix = get_urn_prefix("/api/linkedin/post", "urn", schema_cache={})
        assert prefix is None


class TestNormalizeUrnValue:
    def test_adds_short_prefix(self):
        assert normalize_urn_value("7234173400267538433", "activity:") == "activity:7234173400267538433"

    def test_adds_full_prefix(self):
        assert (
            normalize_urn_value("ACoAAA123", "urn:li:fsd_profile:")
            == "urn:li:fsd_profile:ACoAAA123"
        )

    def test_already_has_prefix(self):
        assert (
            normalize_urn_value("activity:7234173400267538433", "activity:")
            == "activity:7234173400267538433"
        )

    def test_already_has_full_urn(self):
        val = "urn:li:fsd_profile:ACoAAA123"
        assert normalize_urn_value(val, "urn:li:fsd_profile:") == val

    def test_different_prefix_unchanged(self):
        """Value with a different colon-prefix is left unchanged."""
        assert normalize_urn_value("activity:999", "urn:li:fsd_profile:") == "activity:999"

    def test_empty_value(self):
        assert normalize_urn_value("", "activity:") == "activity:"
