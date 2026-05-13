"""Async wrappers for calling Ollama chat completions."""

from __future__ import annotations

import asyncio
from typing import Any, cast

import aiohttp

from . import config as config_mod
from .agents_endpoint import (
    ResolvedEndpoint,
    _chat_base_url,
    _configured_api_url,
    _endpoint_mode,
    _is_loopback_url,
    _normalize_chat_url,
    _proxy_mode,
    _redact_url,
    _resolve_trust_env,
    _split_without_query,
    _uses_openai_compat,
    get_ollama_url,
    resolve_endpoint,
)
from .agents_metadata import ChatResult
from .agents_metadata import metadata_from_response as _metadata_from_response
from .agents_schema import response_format as _response_format
from .agents_schema import schema_for_ollama as _schema_for_ollama
from .agents_transport import HEADERS, SessionManager, post_json, post_json_result
from .agents_transport import request_log_context as _request_log_context
from .engine import constants as C
from .engine.logger import logger
from .transcripts import log_exchange

__all__ = [
    "HEADERS",
    "_OPENAI_COMPAT_WARNING_ENDPOINTS",
    "ChatResult",
    "ResolvedEndpoint",
    "SessionManager",
    "_chat_base_url",
    "_configured_api_url",
    "_endpoint_mode",
    "_is_loopback_url",
    "_metadata_from_response",
    "_normalize_chat_url",
    "_post_json",
    "_post_json_result",
    "_proxy_mode",
    "_redact_url",
    "_request_log_context",
    "_resolve_trust_env",
    "_response_format",
    "_schema_for_ollama",
    "_split_without_query",
    "_uses_openai_compat",
    "chat",
    "chat_with_metadata",
    "get_ollama_url",
    "ping_ollama",
    "resolve_endpoint",
]


_OPENAI_COMPAT_WARNING_ENDPOINTS: set[str] = set()


def _warn_openai_compat_native_options(endpoint: ResolvedEndpoint) -> None:
    if endpoint.mode != "openai_compat":
        return
    key = endpoint.redacted_chat_url
    if key in _OPENAI_COMPAT_WARNING_ENDPOINTS:
        return
    _OPENAI_COMPAT_WARNING_ENDPOINTS.add(key)
    logger.warning(
        "OpenAI-compatible endpoint mode ignores native Ollama settings %s, %s, %s, and schema grammar format for %s.",
        C.CONFIG_OLLAMA_NUM_CTX,
        C.CONFIG_OLLAMA_KEEP_ALIVE,
        C.AGENT_THINK,
        endpoint.redacted_chat_url,
    )


async def _post_json_result(
    session: aiohttp.ClientSession,
    payload: dict[str, Any],
    retries: int = 0,
    endpoint: ResolvedEndpoint | None = None,
) -> ChatResult:
    return await post_json_result(session, payload, retries=retries, endpoint=endpoint, sleep=asyncio.sleep)


async def _post_json(
    session: aiohttp.ClientSession,
    payload: dict[str, Any],
    retries: int = 0,
    endpoint: ResolvedEndpoint | None = None,
) -> str:
    """Return only response text for callers that do not need metadata."""
    return await post_json(session, payload, retries=retries, endpoint=endpoint, sleep=asyncio.sleep)


async def chat(
    messages: list[dict[str, str]],
    max_tokens: int,
    num_ctx: int | None = None,
    best_of: int = 1,
    schema: dict[str, Any] | None = None,
    session: aiohttp.ClientSession | None = None,
    retries: int = 0,
    log_transcript: bool = True,
) -> list[str]:
    """Return ``best_of`` completions from the configured chat endpoint."""
    results = await chat_with_metadata(
        messages=messages,
        max_tokens=max_tokens,
        num_ctx=num_ctx,
        best_of=best_of,
        schema=schema,
        session=session,
        retries=retries,
        log_transcript=log_transcript,
    )
    return [result.content for result in results]


async def chat_with_metadata(
    messages: list[dict[str, str]],
    max_tokens: int,
    num_ctx: int | None = None,
    best_of: int = 1,
    schema: dict[str, Any] | None = None,
    session: aiohttp.ClientSession | None = None,
    retries: int = 0,
    log_transcript: bool = True,
) -> list[ChatResult]:
    """Return completions with real provider metadata when available."""
    tasks = []
    cfg = config_mod.CONFIG
    model = cfg.get(C.CONFIG_GENERAL, C.CONFIG_LLAMA_DEFAULT_MODEL, str)
    temp = cfg.get(C.CONFIG_GENERAL, C.CONFIG_LLAMA_TEMPERATURE, float)
    keep_alive = cfg.get(C.CONFIG_GENERAL, C.CONFIG_OLLAMA_KEEP_ALIVE, str, fallback="10m")
    endpoint = resolve_endpoint()
    use_openai = endpoint.mode == "openai_compat"
    if use_openai:
        _warn_openai_compat_native_options(endpoint)

    async def _collect(sess: aiohttp.ClientSession) -> list[ChatResult]:
        for _ in range(best_of):
            if use_openai:
                payload = {
                    C.AGENT_MODEL: model,
                    C.TEMPERATURE: temp,
                    C.AGENT_MAX_TOKENS: max_tokens,
                    C.AGENT_MESSAGES: messages,
                }
                if schema is not None:
                    payload[C.AGENT_RESPONSE_FORMAT] = _response_format(schema)
            else:
                options = {
                    C.TEMPERATURE: temp,
                    C.AGENT_NUM_PREDICT: max_tokens,
                }
                if num_ctx is not None:
                    options[C.NUM_CTX] = num_ctx
                payload = {
                    C.AGENT_MODEL: model,
                    C.AGENT_MESSAGES: messages,
                    C.AGENT_STREAM: False,
                    C.AGENT_THINK: False,
                    C.AGENT_KEEP_ALIVE: keep_alive,
                    C.AGENT_OPTIONS: options,
                }
                if schema is not None:
                    payload[C.AGENT_FORMAT] = _schema_for_ollama(schema)
            tasks.append(_post_json_result(sess, payload, retries=retries, endpoint=endpoint))
        return await asyncio.gather(*tasks)

    if session is None:
        async with SessionManager(endpoint.trust_env) as sess:
            responses = await _collect(sess)
    else:
        responses = await _collect(session)

    if log_transcript:
        log_exchange(
            messages,
            [response.content for response in responses],
            [response.metadata for response in responses if response.metadata],
        )
    return responses


async def ping_ollama(timeout: int = 5) -> None:
    """Raise an error if the configured server cannot be reached."""
    endpoint = resolve_endpoint()
    try:
        async with (
            aiohttp.ClientSession(trust_env=endpoint.trust_env) as session,
            session.get(endpoint.health_url, timeout=cast(Any, timeout)) as resp,
        ):
            resp.raise_for_status()
    except Exception as exc:
        raise ConnectionError(
            f"Cannot reach Ollama server at {endpoint.redacted_health_url}: {type(exc).__name__}"
        ) from exc
