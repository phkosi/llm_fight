"""Async wrappers for calling Ollama chat completions."""

import asyncio
import ipaddress
import os
import uuid
from dataclasses import dataclass, field
from typing import Any, cast
from urllib.parse import SplitResult, urlsplit, urlunsplit

import aiohttp

from . import config as config_mod
from .engine import constants as C
from .engine.logger import logger
from .transcripts import log_exchange


def _configured_api_url() -> str:
    return os.environ.get(
        "API_URL",
        config_mod.CONFIG.get(
            C.CONFIG_GENERAL,
            C.CONFIG_LLAMA_API_URL,
            str,
            fallback="http://localhost:11434/api/chat",
        ),
    )


def _split_without_query(url: str) -> SplitResult:
    split = urlsplit(url)
    return SplitResult(split.scheme, split.netloc, split.path.rstrip("/"), "", "")


def _normalize_chat_url(url: str) -> str:
    split = _split_without_query(url.strip())
    path = split.path or ""
    if path.endswith("/api/chat") or path.endswith("/v1/chat/completions"):
        return urlunsplit(split)
    if path.endswith("/v1"):
        split = split._replace(path=f"{path}/chat/completions")
        return urlunsplit(split)
    split = split._replace(path=f"{path}/api/chat")
    return urlunsplit(split)


def get_ollama_url() -> str:
    """Return the configured Ollama chat endpoint.

    ``API_URL`` may point at either Ollama's native ``/api/chat`` endpoint or
    the OpenAI-compatible ``/v1/chat/completions`` endpoint. Bare base URLs
    default to the native endpoint because it supports ``format`` and
    ``options.num_ctx`` directly.
    """
    return _normalize_chat_url(_configured_api_url())


def _uses_openai_compat(url: str) -> bool:
    return urlsplit(url).path.rstrip("/").endswith("/v1/chat/completions")


def _endpoint_mode(url: str) -> str:
    return "openai_compat" if _uses_openai_compat(url) else "native"


def _chat_base_url(url: str) -> str:
    split = _split_without_query(url)
    path = split.path
    if path.endswith("/v1/chat/completions"):
        path = path[: -len("/v1/chat/completions")]
    elif path.endswith("/api/chat"):
        path = path[: -len("/api/chat")]
    split = split._replace(path=path)
    return urlunsplit(split).rstrip("/")


def _redact_url(url: str) -> str:
    split = _split_without_query(url)
    host = split.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = host
    if split.port is not None:
        netloc = f"{netloc}:{split.port}"
    return urlunsplit(split._replace(netloc=netloc))


def _is_loopback_url(url: str) -> bool:
    host = (urlsplit(url).hostname or "").strip().lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _proxy_mode() -> str:
    mode = config_mod.CONFIG.get(
        C.CONFIG_GENERAL,
        C.CONFIG_OLLAMA_PROXY_MODE,
        str,
        fallback=C.OLLAMA_PROXY_AUTO,
    )
    mode = str(mode).strip().lower()
    valid_modes = {C.OLLAMA_PROXY_AUTO, C.OLLAMA_PROXY_DISABLED, C.OLLAMA_PROXY_ENABLED}
    if mode not in valid_modes:
        raise ValueError(
            f"[{C.CONFIG_GENERAL}] {C.CONFIG_OLLAMA_PROXY_MODE} must be one of: {', '.join(sorted(valid_modes))}."
        )
    return mode


def _resolve_trust_env(url: str) -> bool:
    mode = _proxy_mode()
    if mode == C.OLLAMA_PROXY_ENABLED:
        return True
    if mode == C.OLLAMA_PROXY_DISABLED:
        return False
    return not _is_loopback_url(url)


@dataclass(frozen=True)
class ResolvedEndpoint:
    chat_url: str
    health_url: str
    mode: str
    trust_env: bool
    is_loopback: bool

    @property
    def redacted_chat_url(self) -> str:
        return _redact_url(self.chat_url)

    @property
    def redacted_health_url(self) -> str:
        return _redact_url(self.health_url)


def resolve_endpoint() -> ResolvedEndpoint:
    chat_url = get_ollama_url()
    mode = _endpoint_mode(chat_url)
    base = _chat_base_url(chat_url)
    health_path = "/v1/models" if mode == "openai_compat" else "/api/tags"
    health_url = f"{base}{health_path}"
    return ResolvedEndpoint(
        chat_url=chat_url,
        health_url=health_url,
        mode=mode,
        trust_env=_resolve_trust_env(chat_url),
        is_loopback=_is_loopback_url(chat_url),
    )


HEADERS = {C.CONTENT_TYPE: C.APPLICATION_JSON}


@dataclass(frozen=True)
class ChatResult:
    """Text response plus provider metadata when the transport supplies it."""

    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


def _response_format(schema: dict[str, Any]) -> dict[str, Any]:
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

    result: dict[str, Any] = {}
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


def _metadata_from_response(data: dict[str, Any], *, use_openai: bool) -> dict[str, Any]:
    """Extract real provider metadata without inventing missing token counts."""
    metadata: dict[str, Any] = {}
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


def _request_log_context(endpoint: ResolvedEndpoint, payload: dict[str, Any], request_id: str) -> str:
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


# -------------- helper ---------------------------------------------
async def _post_json_result(
    session: aiohttp.ClientSession,
    payload: dict[str, Any],
    retries: int = 0,
    endpoint: ResolvedEndpoint | None = None,
) -> ChatResult:
    attempt = 0
    endpoint = endpoint or resolve_endpoint()
    use_openai = endpoint.mode == "openai_compat"
    request_id = uuid.uuid4().hex[:12]
    log_context = _request_log_context(endpoint, payload, request_id)
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
                    metadata=_metadata_from_response(data, use_openai=use_openai),
                )

        except aiohttp.ClientResponseError as e:
            if e.status >= 500 and attempt < retries:
                delay = 2**attempt
                logger.warning(
                    "Ollama API server error %s (attempt %s/%s). Retrying in %ss. %s",
                    e.status,
                    attempt + 1,
                    retries + 1,
                    delay,
                    log_context,
                )
                attempt += 1
                await asyncio.sleep(delay)
                continue
            logger.error("Ollama API request failed with status %s. %s", e.status, log_context)
            raise
        except (TimeoutError, aiohttp.ClientError) as e:
            if attempt < retries:
                delay = 2**attempt
                logger.warning(
                    "Ollama API call failed with %s (attempt %s/%s). Retrying in %ss. %s",
                    type(e).__name__,
                    attempt + 1,
                    retries + 1,
                    delay,
                    log_context,
                )
                attempt += 1
                await asyncio.sleep(delay)
                continue
            logger.error(
                "Ollama API call failed after %s attempts with %s. %s",
                attempt + 1,
                type(e).__name__,
                log_context,
            )
            raise
        except Exception as e:
            logger.error("Unexpected error during Ollama API call: %s. %s", type(e).__name__, log_context)
            raise


async def _post_json(
    session: aiohttp.ClientSession,
    payload: dict[str, Any],
    retries: int = 0,
    endpoint: ResolvedEndpoint | None = None,
) -> str:
    """Return only response text for callers that do not need metadata."""
    return (await _post_json_result(session, payload, retries=retries, endpoint=endpoint)).content


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
    """Raise an error if the Ollama server cannot be reached."""
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
