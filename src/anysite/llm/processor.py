"""LLM processing orchestrator — reads data, batches, calls LLM, outputs."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import orjson

from anysite.llm.cache import LLMCache
from anysite.llm.errors import LLMError
from anysite.llm.models import (
    LLMMessage,
    ProcessorResult,
    StructuredSchema,
)
from anysite.llm.prompts import PromptBuilder, filter_record_fields
from anysite.llm.providers import LLMProvider

logger = logging.getLogger(__name__)


class LLMProcessor:
    """Orchestrates LLM calls over a set of records."""

    def __init__(
        self,
        provider: LLMProvider,
        cache: LLMCache | None = None,
        rate_limit: str | None = None,
        parallel: int = 5,
        on_error: str = "skip",
    ) -> None:
        self._provider = provider
        self._cache = cache
        self._rate_limit = rate_limit
        self._parallel = parallel
        self._on_error = on_error

    async def process_records(
        self,
        records: list[dict[str, Any]],
        prompt_builder: PromptBuilder,
        *,
        system_prompt: str = "",
        structured: StructuredSchema | None = None,
        batch_size: int = 1,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        no_cache: bool = False,
        fields: list[str] | None = None,
        variables: dict[str, Any] | None = None,
    ) -> ProcessorResult:
        """Process records through the LLM.

        Args:
            records: Input records to process
            prompt_builder: Builds prompts from records
            system_prompt: System message for the LLM
            structured: JSON schema for structured output
            batch_size: Records per LLM call
            temperature: LLM temperature
            max_tokens: Max response tokens
            no_cache: Skip cache lookup
            fields: Record fields to include in prompt
            variables: Extra template variables
        """
        result = ProcessorResult()
        semaphore = asyncio.Semaphore(self._parallel)

        # Set up rate limiter if configured
        rate_limiter = None
        if self._rate_limit:
            from anysite.batch.rate_limiter import RateLimiter

            rate_limiter = RateLimiter(self._rate_limit)

        # Build batches
        batches: list[list[dict[str, Any]]] = []
        for i in range(0, len(records), batch_size):
            batch = records[i : i + batch_size]
            if fields:
                batch = [filter_record_fields(r, fields) for r in batch]
            batches.append(batch)

        tasks = [
            self._process_batch(
                batch,
                batch_idx,
                prompt_builder,
                system_prompt=system_prompt,
                structured=structured,
                temperature=temperature,
                max_tokens=max_tokens,
                no_cache=no_cache,
                variables=variables,
                semaphore=semaphore,
                rate_limiter=rate_limiter,
            )
            for batch_idx, batch in enumerate(batches)
        ]

        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, br in enumerate(batch_results):
            if isinstance(br, Exception):
                error_info = {"batch": i, "error": str(br)}
                result.errors.append(error_info)
                if self._on_error == "stop":
                    break
            elif isinstance(br, dict):
                result.results.extend(br.get("results", []))
                result.total_input_tokens += br.get("input_tokens", 0)
                result.total_output_tokens += br.get("output_tokens", 0)
                result.cache_hits += br.get("cache_hit", 0)
                result.llm_calls += br.get("llm_call", 0)

        return result

    async def _process_batch(
        self,
        batch: list[dict[str, Any]],
        batch_idx: int,
        prompt_builder: PromptBuilder,
        *,
        system_prompt: str,
        structured: StructuredSchema | None,
        temperature: float,
        max_tokens: int,
        no_cache: bool,
        variables: dict[str, Any] | None,
        semaphore: asyncio.Semaphore,
        rate_limiter: Any,
    ) -> dict[str, Any]:
        async with semaphore:
            if rate_limiter:
                await rate_limiter.acquire()

            # Build prompt
            if len(batch) == 1:
                user_prompt = prompt_builder.build(batch[0], variables)
            else:
                user_prompt = prompt_builder.build_for_batch(batch, variables)

            # Check cache
            if self._cache and not no_cache:
                cache_key = LLMCache.make_key(
                    self._provider.__class__.__name__,
                    system_prompt + user_prompt,
                    orjson.dumps(batch).decode(),
                )
                cached = self._cache.get(cache_key)
                if cached is not None:
                    return {
                        "results": _parse_response(cached["content"], batch),
                        "input_tokens": cached["input_tokens"],
                        "output_tokens": cached["output_tokens"],
                        "cache_hit": 1,
                        "llm_call": 0,
                    }
            else:
                cache_key = None

            # Call LLM
            messages: list[LLMMessage] = []
            if system_prompt:
                messages.append(LLMMessage(role="system", content=system_prompt))
            messages.append(LLMMessage(role="user", content=user_prompt))

            try:
                response = await self._provider.complete(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    structured=structured,
                )
            except LLMError:
                raise
            except Exception as e:
                raise LLMError(f"LLM call failed for batch {batch_idx}: {e}") from e

            # Cache the response
            if self._cache and cache_key:
                self._cache.put(
                    cache_key,
                    response.model,
                    response.content,
                    response.input_tokens,
                    response.output_tokens,
                )

            return {
                "results": _parse_response(response.content, batch),
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "cache_hit": 0,
                "llm_call": 1,
            }


def _strip_markdown_json(text: str) -> str:
    """Strip markdown code fences from LLM responses."""
    stripped = text.strip()
    if stripped.startswith("```"):
        # Remove opening fence (```json or ```)
        first_newline = stripped.find("\n")
        if first_newline != -1:
            stripped = stripped[first_newline + 1 :]
        # Remove closing fence
        if stripped.rstrip().endswith("```"):
            stripped = stripped.rstrip()[:-3].rstrip()
    return stripped


def _parse_response(content: str, batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parse LLM response into structured results.

    Tries JSON parsing first, strips markdown fences if needed, falls back to raw text.
    """
    try:
        parsed = orjson.loads(content)
        if isinstance(parsed, dict):
            # Single result — merge with the first record
            if len(batch) == 1:
                return [{**batch[0], **parsed}]
            # Might have a "results" key for batch
            if "results" in parsed and isinstance(parsed["results"], list):
                results = []
                for item in parsed["results"]:
                    idx = item.get("index", len(results))
                    if idx < len(batch):
                        results.append({**batch[idx], **item})
                    else:
                        results.append(item)
                return results
            # Might have "matches" key
            if "matches" in parsed and isinstance(parsed["matches"], list):
                return parsed["matches"]
            # Might have "duplicates" key
            if "duplicates" in parsed and isinstance(parsed["duplicates"], list):
                return parsed["duplicates"]
            return [parsed]
        if isinstance(parsed, list):
            return parsed
    except (orjson.JSONDecodeError, ValueError):
        # Try stripping markdown code fences (common with Anthropic)
        cleaned = _strip_markdown_json(content)
        if cleaned != content:
            try:
                parsed = orjson.loads(cleaned)
                if isinstance(parsed, dict):
                    if len(batch) == 1:
                        return [{**batch[0], **parsed}]
                    if "results" in parsed and isinstance(parsed["results"], list):
                        results = []
                        for item in parsed["results"]:
                            idx = item.get("index", len(results))
                            if idx < len(batch):
                                results.append({**batch[idx], **item})
                            else:
                                results.append(item)
                        return results
                    return [parsed]
                if isinstance(parsed, list):
                    return parsed
            except (orjson.JSONDecodeError, ValueError):
                pass

    # Fallback: return raw text as result
    if len(batch) == 1:
        return [{**batch[0], "_llm_response": content}]
    return [{"_llm_response": content}]
