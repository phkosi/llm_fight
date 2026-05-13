"""Endpoint resolution for local and OpenAI-compatible LLM servers."""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from urllib.parse import SplitResult, urlsplit, urlunsplit

from . import config as config_mod
from .engine import constants as C


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
    """Return the configured Ollama chat endpoint."""
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
