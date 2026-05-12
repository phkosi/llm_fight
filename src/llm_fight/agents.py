"""Async wrappers for calling Ollama chat completions."""

import aiohttp
import asyncio
import os
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from . import config as config_mod
from .engine import constants as C
from .engine.logger import logger
from .transcripts import log_exchange


def get_ollama_url() -> str:
    """Return the configured Ollama chat endpoint.

    ``API_URL`` may point at either Ollama's native ``/api/chat`` endpoint or
    the OpenAI-compatible ``/v1/chat/completions`` endpoint. Bare base URLs
    default to the native endpoint because it supports ``format`` and
    ``options.num_ctx`` directly.
    """

    url = os.environ.get(
        "API_URL",
        config_mod.CONFIG.get(
            C.CONFIG_GENERAL,
            C.CONFIG_LLAMA_API_URL,
            str,
            fallback="http://localhost:11434/api/chat",
        ),
    )

    if not (url.endswith("/api/chat") or url.endswith("/v1/chat/completions")):
        url = url.rstrip("/") + "/api/chat"

    return url


HEADERS = {C.CONTENT_TYPE: C.APPLICATION_JSON}


@dataclass(frozen=True)
class ChatResult:
    """Text response plus provider metadata when the transport supplies it."""

    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)


def _uses_openai_compat(url: str) -> bool:
    return url.rstrip("/").endswith("/v1/chat/completions")


def _response_format(schema: Dict[str, Any]) -> Dict[str, Any]:
    return {
        C.SCHEMA_TYPE: "json_schema",
        "json_schema": {
            C.NAME: "llm_fight_response",
            "schema": schema,
        },
    }


UNSUPPORTED_OLLAMA_SCHEMA_KEYS = {
    "allOf",
    "anyOf",
    "oneOf",
    "not",
    "if",
    "then",
    "else",
    "const",
    C.SCHEMA_PATTERN,
    C.SCHEMA_MINIMUM,
    C.SCHEMA_MAXIMUM,
    C.SCHEMA_MIN_PROPERTIES,
    C.SCHEMA_MAX_PROPERTIES,
}


def _schema_for_ollama(schema: Any) -> Any:
    """Return a JSON Schema subset that Ollama's grammar compiler accepts."""

    if isinstance(schema, list):
        return [_schema_for_ollama(item) for item in schema]
    if not isinstance(schema, dict):
        return schema

    result: Dict[str, Any] = {}
    for key, value in schema.items():
        if key in UNSUPPORTED_OLLAMA_SCHEMA_KEYS:
            continue
        if key == C.SCHEMA_PATTERN_PROPERTIES:
            properties = result.setdefault(C.SCHEMA_PROPERTIES, {})
            for pattern, subschema in value.items():
                if pattern == f"^[{C.FIGHTER_A}{C.FIGHTER_B}]$":
                    properties[C.FIGHTER_A] = _schema_for_ollama(subschema)
                    properties[C.FIGHTER_B] = _schema_for_ollama(subschema)
            continue
        result[key] = _schema_for_ollama(value)
    return result


def _chat_base_url(url: str) -> str:
    if url.endswith("/v1/chat/completions"):
        return url[: -len("/v1/chat/completions")]
    if url.endswith("/api/chat"):
        return url[: -len("/api/chat")]
    return url.rstrip("/")


def _metadata_from_response(data: Dict[str, Any], *, use_openai: bool) -> Dict[str, Any]:
    """Extract real provider metadata without inventing missing token counts."""
    metadata: Dict[str, Any] = {}
    if use_openai:
        usage = data.get("usage", {})
        if isinstance(usage, dict):
            mapping = {
                "prompt_tokens": "prompt_tokens",
                "completion_tokens": "completion_tokens",
                "total_tokens": "total_tokens",
            }
            for source, target in mapping.items():
                if usage.get(source) is not None:
                    metadata[target] = usage[source]
        return metadata

    native_mapping = {
        "prompt_eval_count": "prompt_tokens",
        "eval_count": "completion_tokens",
        "total_duration": "total_duration",
        "load_duration": "load_duration",
        "prompt_eval_duration": "prompt_eval_duration",
        "eval_duration": "eval_duration",
        "done_reason": "done_reason",
    }
    for source, target in native_mapping.items():
        if data.get(source) is not None:
            metadata[target] = data[source]
            if target != source:
                metadata[source] = data[source]
    prompt_tokens = metadata.get("prompt_tokens")
    completion_tokens = metadata.get("completion_tokens")
    if isinstance(prompt_tokens, int) and isinstance(completion_tokens, int):
        metadata["total_tokens"] = prompt_tokens + completion_tokens
    return metadata


class SessionManager:
    """Async context manager that provides an ``aiohttp.ClientSession``."""

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> aiohttp.ClientSession:
        self._session = aiohttp.ClientSession(trust_env=True)
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None


# -------------- helper ---------------------------------------------
async def _post_json_result(session: aiohttp.ClientSession, payload: Dict[str, Any], retries: int = 0) -> ChatResult:
    attempt = 0
    url = get_ollama_url()
    use_openai = _uses_openai_compat(url)
    while True:
        try:
            # Allow aiohttp to respect proxy-related environment variables
            # like HTTPS_PROXY so network-restricted environments can
            # successfully connect to remote APIs.
            async with session.post(url, json=payload, headers=HEADERS, timeout=300) as resp:
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
                    metadata=_metadata_from_response(data, use_openai=use_openai),
                )

        except aiohttp.ClientResponseError as e:
            if e.status >= 500 and attempt < retries:
                delay = 2**attempt
                logger.warning(
                    f"Ollama API server error {e.status} (attempt {attempt + 1}/{retries + 1}). "
                    f"Retrying in {delay}s. Payload: {payload}"
                )
                attempt += 1
                await asyncio.sleep(delay)
                continue
            logger.error(f"Ollama API request failed with status {e.status}: {e.message}. Payload: {payload}")
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            if attempt < retries:
                delay = 2**attempt
                logger.warning(
                    f"Ollama API call failed (attempt {attempt + 1}/{retries + 1}): {e}. "
                    f"Retrying in {delay}s. Payload: {payload}"
                )
                attempt += 1
                await asyncio.sleep(delay)
                continue
            logger.error(f"Ollama API call failed after {attempt + 1} attempts: {e}. Payload: {payload}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during Ollama API call: {e}. Payload: {payload}")
            raise


async def _post_json(session: aiohttp.ClientSession, payload: Dict[str, Any], retries: int = 0) -> str:
    """Return only response text for callers that do not need metadata."""
    return (await _post_json_result(session, payload, retries=retries)).content


async def chat(
    messages: List[Dict[str, str]],
    max_tokens: int,
    num_ctx: int | None = None,
    best_of: int = 1,
    schema: Optional[Dict[str, Any]] = None,
    session: aiohttp.ClientSession | None = None,
    retries: int = 0,
    log_transcript: bool = True,
) -> List[str]:
    """Return ``best_of`` completions from Ollama.

    ``max_tokens`` limits how many tokens the model may generate. ``num_ctx``
    sets the context window for the request via Ollama's ``options``.
    ``retries`` specifies how many additional attempts should be made if the
    request fails due to network issues or 5xx responses.
    """
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
    messages: List[Dict[str, str]],
    max_tokens: int,
    num_ctx: int | None = None,
    best_of: int = 1,
    schema: Optional[Dict[str, Any]] = None,
    session: aiohttp.ClientSession | None = None,
    retries: int = 0,
    log_transcript: bool = True,
) -> List[ChatResult]:
    """Return completions with real provider metadata when available."""
    tasks = []
    cfg = config_mod.CONFIG
    model = cfg.get(C.CONFIG_GENERAL, C.CONFIG_LLAMA_DEFAULT_MODEL, str)
    temp = cfg.get(C.CONFIG_GENERAL, C.CONFIG_LLAMA_TEMPERATURE, float)
    keep_alive = cfg.get(C.CONFIG_GENERAL, C.CONFIG_OLLAMA_KEEP_ALIVE, str, fallback="10m")
    url = get_ollama_url()
    use_openai = _uses_openai_compat(url)

    async def _collect(sess: aiohttp.ClientSession) -> List[ChatResult]:
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
            tasks.append(_post_json_result(sess, payload, retries=retries))
        return await asyncio.gather(*tasks)

    if session is None:
        async with SessionManager() as sess:
            responses = await _collect(sess)
    else:
        responses = await _collect(session)

    if log_transcript:
        log_exchange(messages, [response.content for response in responses])
    return responses


async def ping_ollama(timeout: int = 5) -> None:
    """Raise an error if the Ollama server cannot be reached."""
    url = _chat_base_url(get_ollama_url()).rstrip("/") + "/api/tags"
    try:
        async with aiohttp.ClientSession(trust_env=True) as session:
            async with session.get(url, timeout=timeout) as resp:
                resp.raise_for_status()
    except Exception as exc:
        raise ConnectionError(f"Cannot reach Ollama server at {url}: {exc}") from exc
