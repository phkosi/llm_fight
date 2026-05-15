import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llm_fight import agents as agents_module
from llm_fight.agents import chat, get_ollama_url
from llm_fight.config import CONFIG
from llm_fight.engine import constants as C

BASE_OLLAMA_URL = CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_LLAMA_API_URL, str, fallback="http://localhost:11434/api/chat")


@pytest.fixture(autouse=True)
def configured_model():
    with patch("llm_fight.config.Config.get_ollama_model", return_value="qwen3.6:35b"):
        yield


def test_get_ollama_url_no_env(monkeypatch):
    """When API_URL is unset, default config fallback is used."""
    monkeypatch.delenv("API_URL", raising=False)
    from llm_fight.agents import get_ollama_url

    assert get_ollama_url() == BASE_OLLAMA_URL


def test_get_ollama_url_missing_suffix(monkeypatch):
    """API_URL without a chat suffix should default to native Ollama."""
    custom_base = "http://example.com"
    monkeypatch.setenv("API_URL", custom_base)
    from llm_fight.agents import get_ollama_url

    assert get_ollama_url() == custom_base + "/api/chat"


def test_get_ollama_url_complete(monkeypatch):
    """If API_URL already ends with the suffix it should remain unchanged."""
    complete = "http://host:1234/v1/chat/completions"
    monkeypatch.setenv("API_URL", complete)
    from llm_fight.agents import get_ollama_url

    assert get_ollama_url() == complete


def test_get_ollama_url_normalizes_v1_base(monkeypatch):
    monkeypatch.setenv("API_URL", "http://host:1234/v1")

    assert get_ollama_url() == "http://host:1234/v1/chat/completions"


def test_get_ollama_url_from_env():
    custom_base = "https://example.com"
    with patch.dict(os.environ, {"API_URL": custom_base}):
        assert get_ollama_url() == custom_base + "/api/chat"


def test_get_ollama_url_from_config():
    old = CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_LLAMA_API_URL, str)
    try:
        new_url = "http://config-example.com/api/chat"
        CONFIG.set(C.CONFIG_GENERAL, C.CONFIG_LLAMA_API_URL, new_url)
        with patch.dict(os.environ, {}, clear=True):
            assert get_ollama_url() == new_url
    finally:
        CONFIG.set(C.CONFIG_GENERAL, C.CONFIG_LLAMA_API_URL, old)


def test_resolve_endpoint_proxy_auto_loopback_and_remote(monkeypatch):
    old_proxy_mode = CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_OLLAMA_PROXY_MODE, str)
    try:
        CONFIG.set(C.CONFIG_GENERAL, C.CONFIG_OLLAMA_PROXY_MODE, C.OLLAMA_PROXY_AUTO)
        monkeypatch.setenv("API_URL", "http://LOCALHOST:11434/api/chat")
        endpoint = agents_module.resolve_endpoint()
        assert endpoint.is_loopback is True
        assert endpoint.trust_env is False

        monkeypatch.setenv("API_URL", "http://127.42.0.1:11434/api/chat")
        assert agents_module.resolve_endpoint().trust_env is False

        monkeypatch.setenv("API_URL", "http://[::1]:11434/api/chat")
        assert agents_module.resolve_endpoint().trust_env is False

        monkeypatch.setenv("API_URL", "https://example.com/api/chat")
        assert agents_module.resolve_endpoint().trust_env is True
    finally:
        CONFIG.set(C.CONFIG_GENERAL, C.CONFIG_OLLAMA_PROXY_MODE, old_proxy_mode)


def test_resolve_endpoint_proxy_enabled_and_disabled(monkeypatch):
    old_proxy_mode = CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_OLLAMA_PROXY_MODE, str)
    try:
        monkeypatch.setenv("API_URL", "http://localhost:11434/api/chat")
        CONFIG.set(C.CONFIG_GENERAL, C.CONFIG_OLLAMA_PROXY_MODE, C.OLLAMA_PROXY_ENABLED)
        assert agents_module.resolve_endpoint().trust_env is True

        monkeypatch.setenv("API_URL", "https://example.com/api/chat")
        CONFIG.set(C.CONFIG_GENERAL, C.CONFIG_OLLAMA_PROXY_MODE, C.OLLAMA_PROXY_DISABLED)
        assert agents_module.resolve_endpoint().trust_env is False
    finally:
        CONFIG.set(C.CONFIG_GENERAL, C.CONFIG_OLLAMA_PROXY_MODE, old_proxy_mode)


def test_resolve_endpoint_rejects_invalid_proxy_mode(monkeypatch):
    old_proxy_mode = CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_OLLAMA_PROXY_MODE, str)
    try:
        monkeypatch.setenv("API_URL", "http://localhost:11434/api/chat")
        CONFIG.set(C.CONFIG_GENERAL, C.CONFIG_OLLAMA_PROXY_MODE, "surprise")
        with pytest.raises(ValueError, match=C.CONFIG_OLLAMA_PROXY_MODE):
            agents_module.resolve_endpoint()
    finally:
        CONFIG.set(C.CONFIG_GENERAL, C.CONFIG_OLLAMA_PROXY_MODE, old_proxy_mode)


@pytest.mark.asyncio
async def test_chat_uses_provided_session():
    messages = [{C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: "Hello"}]
    max_tokens = 5

    mock_resp = AsyncMock()
    mock_resp.json = AsyncMock(return_value={C.OLLAMA_MESSAGE: {C.AGENT_CONTENT: "Hi"}})
    mock_resp.status = 200
    mock_resp.raise_for_status = MagicMock()

    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_resp

    session = MagicMock()
    session.closed = False
    session.post = MagicMock(return_value=mock_cm)
    session.close = AsyncMock()

    with patch("aiohttp.ClientSession") as mock_ctor:
        responses = await chat(messages=messages, max_tokens=max_tokens, session=session)
        mock_ctor.assert_not_called()

    assert responses == ["Hi"]
    session.post.assert_called_once()


@pytest.mark.asyncio
async def test_chat_internal_session_uses_loopback_proxy_default(monkeypatch):
    messages = [{C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: "Hello"}]
    old_proxy_mode = CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_OLLAMA_PROXY_MODE, str)

    mock_resp = AsyncMock()
    mock_resp.json = AsyncMock(return_value={C.OLLAMA_MESSAGE: {C.AGENT_CONTENT: "Hi"}})
    mock_resp.status = 200
    mock_resp.raise_for_status = MagicMock()

    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_resp

    session = MagicMock()
    session.closed = False
    session.close = AsyncMock()
    session.post = MagicMock(return_value=mock_cm)

    try:
        CONFIG.set(C.CONFIG_GENERAL, C.CONFIG_OLLAMA_PROXY_MODE, C.OLLAMA_PROXY_AUTO)
        monkeypatch.setenv("API_URL", "http://localhost:11434/api/chat")
        with patch("aiohttp.ClientSession", return_value=session) as mock_ctor:
            await chat(messages=messages, max_tokens=5)
    finally:
        CONFIG.set(C.CONFIG_GENERAL, C.CONFIG_OLLAMA_PROXY_MODE, old_proxy_mode)

    mock_ctor.assert_called_once_with(trust_env=False)


@pytest.mark.asyncio
async def test_chat_internal_session_proxy_enabled_overrides_loopback(monkeypatch):
    messages = [{C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: "Hello"}]
    old_proxy_mode = CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_OLLAMA_PROXY_MODE, str)

    mock_resp = AsyncMock()
    mock_resp.json = AsyncMock(return_value={C.OLLAMA_MESSAGE: {C.AGENT_CONTENT: "Hi"}})
    mock_resp.status = 200
    mock_resp.raise_for_status = MagicMock()

    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_resp

    session = MagicMock()
    session.closed = False
    session.close = AsyncMock()
    session.post = MagicMock(return_value=mock_cm)

    try:
        CONFIG.set(C.CONFIG_GENERAL, C.CONFIG_OLLAMA_PROXY_MODE, C.OLLAMA_PROXY_ENABLED)
        monkeypatch.setenv("API_URL", "http://localhost:11434/api/chat")
        with patch("aiohttp.ClientSession", return_value=session) as mock_ctor:
            await chat(messages=messages, max_tokens=5)
    finally:
        CONFIG.set(C.CONFIG_GENERAL, C.CONFIG_OLLAMA_PROXY_MODE, old_proxy_mode)

    mock_ctor.assert_called_once_with(trust_env=True)


@pytest.mark.asyncio
async def test_ping_openai_compat_uses_models_health_and_shared_proxy(monkeypatch):
    old_proxy_mode = CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_OLLAMA_PROXY_MODE, str)

    mock_resp = AsyncMock()
    mock_resp.raise_for_status = MagicMock()

    get_cm = AsyncMock()
    get_cm.__aenter__.return_value = mock_resp

    session = MagicMock()
    session.get = MagicMock(return_value=get_cm)

    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = session

    try:
        CONFIG.set(C.CONFIG_GENERAL, C.CONFIG_OLLAMA_PROXY_MODE, C.OLLAMA_PROXY_AUTO)
        monkeypatch.setenv("API_URL", "http://localhost:11434/v1/chat/completions")
        with patch("aiohttp.ClientSession", return_value=session_cm) as mock_ctor:
            await agents_module.ping_ollama(timeout=7)
    finally:
        CONFIG.set(C.CONFIG_GENERAL, C.CONFIG_OLLAMA_PROXY_MODE, old_proxy_mode)

    mock_ctor.assert_called_once_with(trust_env=False)
    session.get.assert_called_once_with("http://localhost:11434/v1/models", timeout=7)
    assert "/api/tags" not in session.get.call_args.args[0]
