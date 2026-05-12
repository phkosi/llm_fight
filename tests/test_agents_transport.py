import asyncio
import logging
import os
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from llm_fight.agents import chat
from llm_fight.engine import constants as C


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

    with patch("aiohttp.ClientSession", return_value=mock_session_instance), pytest.raises(aiohttp.ClientResponseError):
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

    with (
        patch("aiohttp.ClientSession", return_value=mock_session_instance),
        pytest.raises(aiohttp.ClientConnectionError),
    ):
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
    mock_session_instance.post = MagicMock(side_effect=TimeoutError())

    with patch("aiohttp.ClientSession", return_value=mock_session_instance), pytest.raises(asyncio.TimeoutError):
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

    with patch("aiohttp.ClientSession", return_value=mock_session_instance), pytest.raises(ValueError):
        await chat(messages=messages, max_tokens=max_tokens, best_of=1)


def _session_with_post_failure(failure):
    session = MagicMock()
    session.closed = False
    session.close = AsyncMock()
    session.post = MagicMock(side_effect=failure)
    return session


def _session_with_status(status):
    mock_resp = AsyncMock()
    mock_resp.status = status
    mock_resp.request_info = MagicMock()
    mock_resp.history = ()
    mock_resp.headers = {}
    mock_resp.raise_for_status = MagicMock()

    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_resp

    session = MagicMock()
    session.closed = False
    session.close = AsyncMock()
    session.post = MagicMock(return_value=mock_cm)
    return session


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("session_factory", "expected_error"),
    [
        (lambda sentinel: _session_with_status(500), aiohttp.ClientResponseError),
        (
            lambda sentinel: _session_with_post_failure(aiohttp.ClientConnectionError(f"boom {sentinel}")),
            aiohttp.ClientConnectionError,
        ),
        (
            lambda sentinel: _session_with_post_failure(TimeoutError(f"timeout {sentinel}")),
            asyncio.TimeoutError,
        ),
        (lambda sentinel: _session_with_post_failure(ValueError(f"unexpected {sentinel}")), ValueError),
    ],
)
async def test_transport_failure_logs_redact_payload_and_prompt(caplog, session_factory, expected_error):
    sentinel = "SENTINEL_PROMPT_SECRET"
    api_url = "http://user:pass@localhost:11434/api/chat?token=secret_query"
    messages = [{C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: sentinel}]
    session = session_factory(sentinel)
    caplog.set_level(logging.WARNING, logger="llm_fight_engine")

    with patch.dict(os.environ, {"API_URL": api_url}), pytest.raises(expected_error):
        await chat(messages=messages, max_tokens=10, session=session, retries=0)

    log_text = caplog.text
    assert sentinel not in log_text
    assert "Payload:" not in log_text
    assert "messages" not in log_text
    assert "user:pass" not in log_text
    assert "secret_query" not in log_text
    assert "message_count=1" in log_text
    assert "message_chars=" in log_text


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
