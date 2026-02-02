"""Tests for LLM cache."""

import pytest

from anysite.llm.cache import LLMCache


@pytest.fixture
def cache(tmp_path):
    """Create a cache with a temporary database."""
    db_path = tmp_path / "test_cache.db"
    c = LLMCache(db_path=db_path)
    yield c
    c.close()


def test_make_key():
    key1 = LLMCache.make_key("model", "prompt", "input")
    key2 = LLMCache.make_key("model", "prompt", "input")
    key3 = LLMCache.make_key("model", "prompt", "different")
    assert key1 == key2
    assert key1 != key3
    assert len(key1) == 64  # SHA256 hex digest


def test_put_and_get(cache):
    cache.put("key1", "gpt-4", "hello world", input_tokens=10, output_tokens=5)
    result = cache.get("key1")
    assert result is not None
    assert result["content"] == "hello world"
    assert result["model"] == "gpt-4"
    assert result["input_tokens"] == 10
    assert result["output_tokens"] == 5


def test_get_miss(cache):
    result = cache.get("nonexistent")
    assert result is None


def test_put_overwrites(cache):
    cache.put("key1", "gpt-4", "first", input_tokens=10, output_tokens=5)
    cache.put("key1", "gpt-4", "second", input_tokens=20, output_tokens=10)
    result = cache.get("key1")
    assert result["content"] == "second"
    assert result["input_tokens"] == 20


def test_stats_empty(cache):
    stats = cache.stats()
    assert stats["entries"] == 0
    assert stats["total_input_tokens"] == 0
    assert stats["total_output_tokens"] == 0


def test_stats_with_entries(cache):
    cache.put("key1", "gpt-4", "a", input_tokens=10, output_tokens=5)
    cache.put("key2", "gpt-4", "b", input_tokens=20, output_tokens=10)
    stats = cache.stats()
    assert stats["entries"] == 2
    assert stats["total_input_tokens"] == 30
    assert stats["total_output_tokens"] == 15


def test_clear(cache):
    cache.put("key1", "gpt-4", "a", input_tokens=10, output_tokens=5)
    cache.put("key2", "gpt-4", "b", input_tokens=20, output_tokens=10)
    count = cache.clear()
    assert count == 2
    assert cache.stats()["entries"] == 0


def test_clear_empty(cache):
    count = cache.clear()
    assert count == 0


def test_wal_mode(cache):
    # Force connection
    conn = cache._connect()
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"
