"""HTTP transport for chat requests."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, cast

import aiohttp

from .agents_endpoint import ResolvedEndpoint, resolve_endpoint
from .agents_metadata import ChatResult, metadata_from_response
from .engine import constants as C
from .engine.logger import logger

HEADERS = {C.CONTENT_TYPE: C.APPLICATION_JSON}
SleepFunc = Callable[[float], Awaitable[Any]]


class SessionManager:
    """Async context manager that provides an ``aiohttp.ClientSession``."""

    def __init__(self, trust_env: bool | None = None) -> None:
        self._trust_env = resolve_endpoint().trust_env if trust_env is None else trust_env
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> aiohttp.ClientSession:
        self._session = aiohttp.ClientSession(trust_env=self._trust_env)
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None


def request_log_context(endpoint: ResolvedEndpoint, payload: dict[str, Any], request_id: str) -> str:
    messages = payload.get(C.AGENT_MESSAGES, [])
    message_count = len(messages) if isinstance(messages, list) else 0
    message_chars = 0
    if isinstance(messages, list):
        message_chars = sum(
            len(str(message.get(C.AGENT_CONTENT, ""))) for message in messages if isinstance(message, dict)
        )

    options = payload.get(C.AGENT_OPTIONS, {})
    requested_completion = payload.get(C.AGENT_MAX_TOKENS)
    if requested_completion is None and isinstance(options, dict):
        requested_completion = options.get(C.AGENT_NUM_PREDICT)

    parts = [
        f"request_id={request_id}",
        f"url={endpoint.redacted_chat_url}",
        f"mode={endpoint.mode}",
        f"model={payload.get(C.AGENT_MODEL, '<unknown>')}",
        f"message_count={message_count}",
        f"message_chars={message_chars}",
        f"max_tokens={requested_completion}",
        f"schema_present={C.AGENT_FORMAT in payload or C.AGENT_RESPONSE_FORMAT in payload}",
    ]
    if endpoint.mode == "native" and isinstance(options, dict) and options.get(C.NUM_CTX) is not None:
        parts.append(f"num_ctx={options[C.NUM_CTX]}")
    return " ".join(parts)


async def post_json_result(
    session: aiohttp.ClientSession,
    payload: dict[str, Any],
    retries: int = 0,
    endpoint: ResolvedEndpoint | None = None,
    *,
    sleep: SleepFunc = asyncio.sleep,
) -> ChatResult:
    attempt = 0
    endpoint = endpoint or resolve_endpoint()
    use_openai = endpoint.mode == "openai_compat"
    request_id = uuid.uuid4().hex[:12]
    log_context = request_log_context(endpoint, payload, request_id)
    while True:
        try:
            async with session.post(endpoint.chat_url, json=payload, headers=HEADERS, timeout=cast(Any, 300)) as resp:
                if resp.status >= 500:
                    raise aiohttp.ClientResponseError(
                        request_info=resp.request_info,
                        history=resp.history,
                        status=resp.status,
                        message=f"Server error {resp.status}",
                        headers=resp.headers,
                    )
                resp.raise_for_status()
                data = await resp.json()
                if use_openai:
                    content = data[C.OLLAMA_CHOICES][0][C.OLLAMA_MESSAGE][C.AGENT_CONTENT]
                else:
                    content = data[C.OLLAMA_MESSAGE][C.AGENT_CONTENT]
                return ChatResult(
                    content=content,
                    metadata=metadata_from_response(data, use_openai=use_openai),
                )

        except aiohttp.ClientResponseError as exc:
            if exc.status >= 500 and attempt < retries:
                delay = 2**attempt
                logger.warning(
                    "Ollama API server error %s (attempt %s/%s). Retrying in %ss. %s",
                    exc.status,
                    attempt + 1,
                    retries + 1,
                    delay,
                    log_context,
                )
                attempt += 1
                await sleep(delay)
                continue
            logger.error("Ollama API request failed with status %s. %s", exc.status, log_context)
            raise
        except (TimeoutError, aiohttp.ClientError) as exc:
            if attempt < retries:
                delay = 2**attempt
                logger.warning(
                    "Ollama API call failed with %s (attempt %s/%s). Retrying in %ss. %s",
                    type(exc).__name__,
                    attempt + 1,
                    retries + 1,
                    delay,
                    log_context,
                )
                attempt += 1
                await sleep(delay)
                continue
            logger.error(
                "Ollama API call failed after %s attempts with %s. %s",
                attempt + 1,
                type(exc).__name__,
                log_context,
            )
            raise
        except Exception as exc:
            logger.error("Unexpected error during Ollama API call: %s. %s", type(exc).__name__, log_context)
            raise


async def post_json(
    session: aiohttp.ClientSession,
    payload: dict[str, Any],
    retries: int = 0,
    endpoint: ResolvedEndpoint | None = None,
    *,
    sleep: SleepFunc = asyncio.sleep,
) -> str:
    """Return only response text for callers that do not need metadata."""
    return (await post_json_result(session, payload, retries=retries, endpoint=endpoint, sleep=sleep)).content
