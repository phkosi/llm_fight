import logging
import os
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from llm_fight import agents as agents_module
from llm_fight import config as config_mod
from llm_fight.agents import chat, chat_with_metadata
from llm_fight.config import (
    CONFIG,  # To access config values for assertions
    Config,
)
from llm_fight.engine import constants as C

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
    mock_responses_content = [f"Joke {i + 1}" for i in range(best_of_n)]

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
async def test_chat_openai_compat_payload_and_response_format(caplog):
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

    agents_module._OPENAI_COMPAT_WARNING_ENDPOINTS.clear()
    caplog.set_level(logging.WARNING, logger="llm_fight_engine")
    with patch.dict(os.environ, {"API_URL": openai_url}):
        responses = await chat(
            messages=messages, max_tokens=12, best_of=1, schema=schema, session=mock_session_instance
        )

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
    payload = mock_session_instance.post.call_args.kwargs["json"]
    assert C.AGENT_OPTIONS not in payload
    assert C.AGENT_KEEP_ALIVE not in payload
    assert C.AGENT_THINK not in payload
    assert C.AGENT_STREAM not in payload
    assert C.AGENT_FORMAT not in payload
    assert caplog.text.count("OpenAI-compatible endpoint mode ignores native Ollama settings") == 1

    mock_second_response = AsyncMock()
    mock_second_response.json = AsyncMock(
        return_value={C.OLLAMA_CHOICES: [{C.OLLAMA_MESSAGE: {C.AGENT_CONTENT: "compat ok 2"}}]}
    )
    mock_second_response.status = 200
    mock_second_response.raise_for_status = MagicMock()
    mock_second_context = AsyncMock()
    mock_second_context.__aenter__.return_value = mock_second_response
    mock_session_instance.post = MagicMock(return_value=mock_second_context)

    with patch.dict(os.environ, {"API_URL": openai_url}):
        await chat(messages=messages, max_tokens=12, best_of=1, schema=schema, session=mock_session_instance)

    assert caplog.text.count("OpenAI-compatible endpoint mode ignores native Ollama settings") == 1


@pytest.mark.asyncio
async def test_chat_with_metadata_extracts_openai_usage():
    messages = [{C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: "Hello"}]
    openai_url = "http://localhost:11434/v1/chat/completions"

    mock_actual_response = AsyncMock()
    mock_actual_response.json = AsyncMock(
        return_value={
            C.OLLAMA_CHOICES: [{C.OLLAMA_MESSAGE: {C.AGENT_CONTENT: "compat ok"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
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
        results = await chat_with_metadata(messages=messages, max_tokens=12, best_of=1)

    assert results[0].content == "compat ok"
    assert results[0].metadata == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}


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
async def test_chat_with_metadata_extracts_native_ollama_counts_and_durations():
    messages = [{C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: "Hello"}]

    mock_resp = AsyncMock()
    mock_resp.json = AsyncMock(
        return_value={
            C.OLLAMA_MESSAGE: {C.AGENT_CONTENT: "ok"},
            "prompt_eval_count": 7,
            "eval_count": 3,
            "total_duration": 100,
            "load_duration": 20,
            "prompt_eval_duration": 30,
            "eval_duration": 40,
            "done_reason": "stop",
        }
    )
    mock_resp.status = 200
    mock_resp.raise_for_status = MagicMock()

    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_resp

    session = MagicMock()
    session.closed = False
    session.close = AsyncMock()
    session.post = MagicMock(return_value=mock_cm)

    with patch.dict(os.environ, {"API_URL": BASE_OLLAMA_URL}):
        results = await chat_with_metadata(messages=messages, max_tokens=12, session=session)

    assert results[0].content == "ok"
    assert results[0].metadata["prompt_tokens"] == 7
    assert results[0].metadata["completion_tokens"] == 3
    assert results[0].metadata["total_tokens"] == 10
    assert results[0].metadata["prompt_eval_count"] == 7
    assert results[0].metadata["eval_count"] == 3
    assert results[0].metadata["done_reason"] == "stop"


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
