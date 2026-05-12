import pytest
import asyncio
import aiohttp
import os
from unittest.mock import AsyncMock, MagicMock, patch, call

from llm_fight.agents import chat, get_ollama_url
from llm_fight.engine import constants as C
from llm_fight.config import CONFIG  # To access config values for assertions
from llm_fight.config import Config
from llm_fight import config as config_mod

BASE_OLLAMA_URL = CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_LLAMA_API_URL, str, fallback="http://localhost:11434/api/chat")
DEFAULT_MODEL = CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_LLAMA_DEFAULT_MODEL, str)
DEFAULT_TEMP = CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_LLAMA_TEMPERATURE, float)


@pytest.mark.asyncio
async def test_chat_single_call_success():
    messages = [{C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: "Hello"}]
    max_tokens = 50
    schema = {"type": "object"}
    mock_response_content = "Hi there!"

    # 1. The actual response mock from (await session.post(...)).__aenter__()
    mock_actual_response = AsyncMock()
    mock_actual_response.json = AsyncMock(return_value={C.OLLAMA_MESSAGE: {C.AGENT_CONTENT: mock_response_content}})
    mock_actual_response.status = 200
    mock_actual_response.raise_for_status = MagicMock()

    # 2. The context manager object that `await session.post(...)` resolves to.
    # This object has __aenter__ and __aexit__.
    mock_post_context_manager = AsyncMock()
    mock_post_context_manager.__aenter__.return_value = mock_actual_response

    # 3. The session instance returned by ClientSession()
    # Its `post` method should return the context manager defined above.
    mock_session_instance = MagicMock()
    mock_session_instance.closed = False
    mock_session_instance.close = AsyncMock()

    # Configure the .post method on the session instance
    # `aiohttp.ClientSession.post` returns a context manager directly,
    # so use a regular MagicMock rather than AsyncMock.
    mock_session_instance.post = MagicMock(return_value=mock_post_context_manager)

    # Patch aiohttp.ClientSession so our module-level session uses the mock.
    with (
        patch("aiohttp.ClientSession", return_value=mock_session_instance) as mock_ClientSession_constructor,
        patch.dict(os.environ, {"API_URL": BASE_OLLAMA_URL}),
    ):
        responses = await chat(
            messages=messages,
            max_tokens=max_tokens,
            best_of=1,
            schema=schema,
        )

    assert responses == [mock_response_content]

    mock_ClientSession_constructor.assert_called_once()

    # Check that session.post was called (it is now an AsyncMock itself)
    mock_session_instance.post.assert_called_once_with(
        BASE_OLLAMA_URL,
        json={
            C.AGENT_MODEL: DEFAULT_MODEL,
            C.AGENT_MESSAGES: messages,
            C.AGENT_STREAM: False,
            C.AGENT_THINK: False,
            C.AGENT_KEEP_ALIVE: "10m",
            C.AGENT_OPTIONS: {
                C.TEMPERATURE: DEFAULT_TEMP,
                C.AGENT_NUM_PREDICT: max_tokens,
            },
            C.AGENT_FORMAT: schema,
        },
        headers={C.CONTENT_TYPE: C.APPLICATION_JSON},
        timeout=300,
    )
    # Check that the context manager returned by `await session.post(...)` was entered
    mock_post_context_manager.__aenter__.assert_called_once()


@pytest.mark.asyncio
async def test_chat_best_of_n_calls_success():
    messages = [{C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: "Tell me a joke"}]
    max_tokens = 100
    best_of_n = 3
    schema = {"type": "object"}
    mock_responses_content = [f"Joke {i+1}" for i in range(best_of_n)]

    mock_actual_responses = []
    mock_post_context_managers = []

    for i in range(best_of_n):
        # 1. Actual response mock
        actual_resp = AsyncMock()
        actual_resp.json = AsyncMock(return_value={C.OLLAMA_MESSAGE: {C.AGENT_CONTENT: mock_responses_content[i]}})
        actual_resp.status = 200
        actual_resp.raise_for_status = MagicMock()
        mock_actual_responses.append(actual_resp)

        # 2. Context manager for session.post() result
        ctx_mgr = AsyncMock()
        ctx_mgr.__aenter__.return_value = actual_resp
        mock_post_context_managers.append(ctx_mgr)

    # 3. Session instance mock reused for all calls
    mock_session_instance = MagicMock()
    mock_session_instance.closed = False
    mock_session_instance.close = AsyncMock()
    # session.post will be called N times and should return the context manager
    # directly each time
    mock_session_instance.post = MagicMock(side_effect=mock_post_context_managers)

    with (
        patch("aiohttp.ClientSession", return_value=mock_session_instance) as mock_ClientSession_constructor,
        patch.dict(os.environ, {"API_URL": BASE_OLLAMA_URL}),
    ):
        responses = await chat(
            messages=messages,
            max_tokens=max_tokens,
            best_of=best_of_n,
            schema=schema,
        )

    assert responses == mock_responses_content
    assert mock_ClientSession_constructor.call_count == 1
    assert mock_session_instance.post.call_count == best_of_n

    expected_payload = {
        C.AGENT_MODEL: DEFAULT_MODEL,
        C.AGENT_MESSAGES: messages,
        C.AGENT_STREAM: False,
        C.AGENT_THINK: False,
        C.AGENT_KEEP_ALIVE: "10m",
        C.AGENT_OPTIONS: {
            C.TEMPERATURE: DEFAULT_TEMP,
            C.AGENT_NUM_PREDICT: max_tokens,
        },
        C.AGENT_FORMAT: schema,
    }
    expected_calls = [
        call(BASE_OLLAMA_URL, json=expected_payload, headers={C.CONTENT_TYPE: C.APPLICATION_JSON}, timeout=300)
    ] * best_of_n
    mock_session_instance.post.assert_has_calls(expected_calls, any_order=False)
    for ctx_mgr in mock_post_context_managers:
        ctx_mgr.__aenter__.assert_called_once()


@pytest.mark.asyncio
async def test_chat_openai_compat_payload_and_response_format():
    messages = [{C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: "Hello"}]
    schema = {"type": "object"}
    openai_url = "http://localhost:11434/v1/chat/completions"

    mock_actual_response = AsyncMock()
    mock_actual_response.json = AsyncMock(
        return_value={C.OLLAMA_CHOICES: [{C.OLLAMA_MESSAGE: {C.AGENT_CONTENT: "compat ok"}}]}
    )
    mock_actual_response.status = 200
    mock_actual_response.raise_for_status = MagicMock()

    mock_post_context_manager = AsyncMock()
    mock_post_context_manager.__aenter__.return_value = mock_actual_response

    mock_session_instance = MagicMock()
    mock_session_instance.closed = False
    mock_session_instance.close = AsyncMock()
    mock_session_instance.post = MagicMock(return_value=mock_post_context_manager)

    with (
        patch("aiohttp.ClientSession", return_value=mock_session_instance),
        patch.dict(os.environ, {"API_URL": openai_url}),
    ):
        responses = await chat(messages=messages, max_tokens=12, best_of=1, schema=schema)

    assert responses == ["compat ok"]
    mock_session_instance.post.assert_called_once_with(
        openai_url,
        json={
            C.AGENT_MODEL: DEFAULT_MODEL,
            C.TEMPERATURE: DEFAULT_TEMP,
            C.AGENT_MAX_TOKENS: 12,
            C.AGENT_MESSAGES: messages,
            C.AGENT_RESPONSE_FORMAT: {
                C.SCHEMA_TYPE: "json_schema",
                "json_schema": {
                    C.NAME: "llm_fight_response",
                    "schema": schema,
                },
            },
        },
        headers={C.CONTENT_TYPE: C.APPLICATION_JSON},
        timeout=300,
    )


@pytest.mark.asyncio
async def test_chat_native_payload_sanitizes_schema_for_ollama():
    messages = [{C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: "Hello"}]
    schema = {
        C.SCHEMA_TYPE: C.SCHEMA_OBJECT,
        C.SCHEMA_PROPERTIES: {
            "prob": {
                C.SCHEMA_TYPE: C.SCHEMA_STRING,
                C.SCHEMA_PATTERN: r"^(0(\.\d+)?|1(\.0+)?)$",
            }
        },
        C.SCHEMA_PATTERN_PROPERTIES: {
            f"^[{C.FIGHTER_A}{C.FIGHTER_B}]$": {
                C.SCHEMA_TYPE: C.SCHEMA_OBJECT,
                C.SCHEMA_PROPERTIES: {"pain": {C.SCHEMA_TYPE: C.SCHEMA_INTEGER, C.SCHEMA_MINIMUM: 0}},
            }
        },
        "allOf": [{"if": {C.SCHEMA_PROPERTIES: {"done": {"const": False}}}}],
    }

    mock_resp = AsyncMock()
    mock_resp.json = AsyncMock(return_value={C.OLLAMA_MESSAGE: {C.AGENT_CONTENT: "ok"}})
    mock_resp.status = 200
    mock_resp.raise_for_status = MagicMock()

    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_resp

    session = MagicMock()
    session.closed = False
    session.close = AsyncMock()
    session.post = MagicMock(return_value=mock_cm)

    with patch.dict(os.environ, {"API_URL": BASE_OLLAMA_URL}):
        await chat(messages=messages, max_tokens=12, session=session, schema=schema)

    sent_schema = session.post.call_args.kwargs["json"][C.AGENT_FORMAT]
    assert "allOf" not in sent_schema
    assert C.SCHEMA_PATTERN not in sent_schema[C.SCHEMA_PROPERTIES]["prob"]
    assert C.SCHEMA_PATTERN_PROPERTIES not in sent_schema
    assert C.FIGHTER_A in sent_schema[C.SCHEMA_PROPERTIES]
    assert C.FIGHTER_B in sent_schema[C.SCHEMA_PROPERTIES]
    assert C.SCHEMA_MINIMUM not in sent_schema[C.SCHEMA_PROPERTIES][C.FIGHTER_A][C.SCHEMA_PROPERTIES]["pain"]


@pytest.mark.asyncio
async def test_chat_native_payload_keeps_num_ctx_separate_from_generation_limit():
    messages = [{C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: "Hello"}]

    mock_resp = AsyncMock()
    mock_resp.json = AsyncMock(return_value={C.OLLAMA_MESSAGE: {C.AGENT_CONTENT: "ok"}})
    mock_resp.status = 200
    mock_resp.raise_for_status = MagicMock()

    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_resp

    session = MagicMock()
    session.closed = False
    session.close = AsyncMock()
    session.post = MagicMock(return_value=mock_cm)

    with patch.dict(os.environ, {"API_URL": BASE_OLLAMA_URL}):
        await chat(messages=messages, max_tokens=64, num_ctx=32768, session=session)

    payload = session.post.call_args.kwargs["json"]
    assert payload[C.AGENT_OPTIONS][C.NUM_CTX] == 32768
    assert payload[C.AGENT_OPTIONS][C.AGENT_NUM_PREDICT] == 64
    assert payload[C.AGENT_KEEP_ALIVE] == "10m"


@pytest.mark.asyncio
async def test_chat_can_suppress_transcript_logging():
    messages = [{C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: "Hello"}]

    mock_resp = AsyncMock()
    mock_resp.json = AsyncMock(return_value={C.OLLAMA_MESSAGE: {C.AGENT_CONTENT: "unsafe raw text"}})
    mock_resp.status = 200
    mock_resp.raise_for_status = MagicMock()

    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_resp

    session = MagicMock()
    session.closed = False
    session.close = AsyncMock()
    session.post = MagicMock(return_value=mock_cm)

    with (
        patch.dict(os.environ, {"API_URL": BASE_OLLAMA_URL}),
        patch("llm_fight.agents.log_exchange") as mock_log_exchange,
    ):
        responses = await chat(messages=messages, max_tokens=12, session=session, log_transcript=False)

    assert responses == ["unsafe raw text"]
    mock_log_exchange.assert_not_called()


@pytest.mark.asyncio
async def test_chat_reads_model_api_and_retry_config_at_call_time(tmp_path, monkeypatch):
    cfg_path = tmp_path / "llmfight.ini"
    cfg_path.write_text(
        "[General]\n"
        "ollama_default_model = config-model\n"
        "ollama_api_url = http://configured-host:11434/api/chat\n"
        "ollama_temperature = 0.25\n"
        "ollama_keep_alive = 30m\n"
        "max_retries = 7\n"
    )
    old_config = config_mod.CONFIG
    config_mod.CONFIG = Config(cfg_path)
    monkeypatch.delenv("API_URL", raising=False)

    mock_resp = AsyncMock()
    mock_resp.json = AsyncMock(return_value={C.OLLAMA_MESSAGE: {C.AGENT_CONTENT: "configured"}})
    mock_resp.status = 200
    mock_resp.raise_for_status = MagicMock()

    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_resp

    session = MagicMock()
    session.closed = False
    session.close = AsyncMock()
    session.post = MagicMock(return_value=mock_cm)

    try:
        responses = await chat(
            messages=[{C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: "Hi"}], max_tokens=8, session=session
        )
    finally:
        config_mod.CONFIG = old_config

    assert responses == ["configured"]
    assert session.post.call_args.args[0] == "http://configured-host:11434/api/chat"
    payload = session.post.call_args.kwargs["json"]
    assert payload[C.AGENT_MODEL] == "config-model"
    assert payload[C.AGENT_THINK] is False
    assert payload[C.AGENT_KEEP_ALIVE] == "30m"
    assert payload[C.AGENT_OPTIONS][C.TEMPERATURE] == 0.25


@pytest.mark.asyncio
async def test_chat_http_error_raises_exception():
    messages = [{C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: "Test"}]
    max_tokens = 10

    # 1. Actual response mock
    mock_actual_response = AsyncMock()
    mock_actual_response.status = 500  # Status indicating error
    # raise_for_status is synchronous but configured to raise the error
    mock_actual_response.raise_for_status = MagicMock(
        side_effect=aiohttp.ClientResponseError(
            request_info=AsyncMock(), history=(), status=500, message="Internal Server Error", headers=None
        )
    )
    # mock_actual_response.json will not be called if raise_for_status fails

    # 2. Context manager for session.post() result
    mock_post_context_manager = AsyncMock()
    mock_post_context_manager.__aenter__.return_value = mock_actual_response

    # 3. Session instance mock
    mock_session_instance = MagicMock()
    mock_session_instance.closed = False
    mock_session_instance.close = AsyncMock()
    mock_session_instance.post = MagicMock(return_value=mock_post_context_manager)

    with patch("aiohttp.ClientSession", return_value=mock_session_instance):
        with pytest.raises(aiohttp.ClientResponseError):
            await chat(messages=messages, max_tokens=max_tokens, best_of=1)


@pytest.mark.asyncio
async def test_chat_connection_error_raises_exception():
    messages = [{C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: "Test"}]
    max_tokens = 10

    # Session instance mock
    mock_session_instance = MagicMock()
    mock_session_instance.closed = False
    mock_session_instance.close = AsyncMock()
    # The post method itself raises the error
    mock_session_instance.post = MagicMock(side_effect=aiohttp.ClientConnectionError("Cannot connect"))

    with patch("aiohttp.ClientSession", return_value=mock_session_instance):
        with pytest.raises(aiohttp.ClientConnectionError):
            await chat(messages=messages, max_tokens=max_tokens, best_of=1)


@pytest.mark.asyncio
async def test_chat_timeout_error_raises_exception():
    messages = [{C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: "Test"}]
    max_tokens = 10

    # Session instance mock
    mock_session_instance = MagicMock()
    mock_session_instance.closed = False
    mock_session_instance.close = AsyncMock()
    # The post method itself raises the error
    mock_session_instance.post = MagicMock(side_effect=asyncio.TimeoutError())

    with patch("aiohttp.ClientSession", return_value=mock_session_instance):
        with pytest.raises(asyncio.TimeoutError):
            await chat(messages=messages, max_tokens=max_tokens, best_of=1)


@pytest.mark.asyncio
async def test_chat_unexpected_error_raises_exception():
    messages = [{C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: "Test"}]
    max_tokens = 10

    # Session instance mock
    mock_session_instance = MagicMock()
    mock_session_instance.closed = False
    mock_session_instance.close = AsyncMock()
    # The post method itself raises the error
    mock_session_instance.post = MagicMock(side_effect=ValueError("Unexpected issue"))

    with patch("aiohttp.ClientSession", return_value=mock_session_instance):
        with pytest.raises(ValueError):
            await chat(messages=messages, max_tokens=max_tokens, best_of=1)


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
async def test_chat_retries_on_failure(monkeypatch):
    messages = [{C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: "Retry"}]
    max_tokens = 5
    mock_resp = AsyncMock()
    mock_resp.json = AsyncMock(return_value={C.OLLAMA_MESSAGE: {C.AGENT_CONTENT: "ok"}})
    mock_resp.status = 200
    mock_resp.raise_for_status = MagicMock()

    mock_cm_success = AsyncMock()
    mock_cm_success.__aenter__.return_value = mock_resp

    session = MagicMock()
    session.closed = False
    session.close = AsyncMock()
    session.post = MagicMock(side_effect=[aiohttp.ClientConnectionError("boom"), mock_cm_success])

    with (
        patch("aiohttp.ClientSession", return_value=session),
        patch("llm_fight.agents.asyncio.sleep", new=AsyncMock()) as mock_sleep,
    ):
        responses = await chat(messages=messages, max_tokens=max_tokens, retries=1)

    assert responses == ["ok"]
    assert session.post.call_count == 2
    mock_sleep.assert_awaited_once_with(1)
