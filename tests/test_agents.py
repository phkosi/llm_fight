import pytest
import asyncio
import aiohttp
import os
from unittest.mock import AsyncMock, MagicMock, patch, call

from src.agents import chat
from src.engine import constants as C
from src.config import CONFIG # To access config values for assertions

BASE_OLLAMA_URL = CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_LLAMA_API_URL, str, fallback='http://localhost:11434/v1/chat/completions')
DEFAULT_MODEL = CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_LLAMA_DEFAULT_MODEL, str)
DEFAULT_TEMP = CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_LLAMA_TEMPERATURE, float)

@pytest.mark.asyncio
async def test_chat_single_call_success():
    messages = [{C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: "Hello"}]
    max_tokens = 50
    mock_response_content = "Hi there!"
    
    # 1. The actual response mock from (await session.post(...)).__aenter__()
    mock_actual_response = AsyncMock()
    mock_actual_response.json = AsyncMock(return_value={C.OLLAMA_CHOICES: [{C.OLLAMA_MESSAGE: {C.AGENT_CONTENT: mock_response_content}}]})
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
    with patch('aiohttp.ClientSession', return_value=mock_session_instance) as mock_ClientSession_constructor, \
         patch.dict(os.environ, {"API_URL": BASE_OLLAMA_URL}):
        responses = await chat(messages=messages, max_tokens=max_tokens, best_of=1)
    
    assert responses == [mock_response_content]
    
    mock_ClientSession_constructor.assert_called_once()
    
    # Check that session.post was called (it is now an AsyncMock itself)
    mock_session_instance.post.assert_called_once_with(
        BASE_OLLAMA_URL,
        json={
            C.AGENT_MODEL: DEFAULT_MODEL,
            C.TEMPERATURE: DEFAULT_TEMP,
            C.AGENT_MAX_TOKENS: max_tokens,
            C.AGENT_MESSAGES: messages,
        },
        headers={C.CONTENT_TYPE: C.APPLICATION_JSON},
        timeout=300
    )
    # Check that the context manager returned by `await session.post(...)` was entered
    mock_post_context_manager.__aenter__.assert_called_once()

@pytest.mark.asyncio
async def test_chat_best_of_n_calls_success():
    messages = [{C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: "Tell me a joke"}]
    max_tokens = 100
    best_of_n = 3
    mock_responses_content = [f"Joke {i+1}" for i in range(best_of_n)]
    
    mock_actual_responses = []
    mock_post_context_managers = []

    for i in range(best_of_n):
        # 1. Actual response mock
        actual_resp = AsyncMock()
        actual_resp.json = AsyncMock(return_value={C.OLLAMA_CHOICES: [{C.OLLAMA_MESSAGE: {C.AGENT_CONTENT: mock_responses_content[i]}}]})
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

    with patch('aiohttp.ClientSession', return_value=mock_session_instance) as mock_ClientSession_constructor, \
         patch.dict(os.environ, {"API_URL": BASE_OLLAMA_URL}):
        responses = await chat(messages=messages, max_tokens=max_tokens, best_of=best_of_n)
    
    assert responses == mock_responses_content
    assert mock_ClientSession_constructor.call_count == 1
    assert mock_session_instance.post.call_count == best_of_n
    
    expected_payload = {
        C.AGENT_MODEL: DEFAULT_MODEL,
        C.TEMPERATURE: DEFAULT_TEMP,
        C.AGENT_MAX_TOKENS: max_tokens,
        C.AGENT_MESSAGES: messages,
    }
    expected_calls = [
        call(BASE_OLLAMA_URL, json=expected_payload, headers={C.CONTENT_TYPE: C.APPLICATION_JSON}, timeout=300)
    ] * best_of_n
    mock_session_instance.post.assert_has_calls(expected_calls, any_order=False)
    for ctx_mgr in mock_post_context_managers:
        ctx_mgr.__aenter__.assert_called_once()

@pytest.mark.asyncio
async def test_chat_http_error_raises_exception():
    messages = [{C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: "Test"}]
    max_tokens = 10

    # 1. Actual response mock
    mock_actual_response = AsyncMock()
    mock_actual_response.status = 500 # Status indicating error
    # raise_for_status is synchronous but configured to raise the error
    mock_actual_response.raise_for_status = MagicMock(side_effect=aiohttp.ClientResponseError(
        request_info=AsyncMock(), 
        history=(), 
        status=500, 
        message="Internal Server Error", 
        headers=None
    ))
    # mock_actual_response.json will not be called if raise_for_status fails

    # 2. Context manager for session.post() result
    mock_post_context_manager = AsyncMock()
    mock_post_context_manager.__aenter__.return_value = mock_actual_response

    # 3. Session instance mock
    mock_session_instance = MagicMock()
    mock_session_instance.closed = False
    mock_session_instance.close = AsyncMock()
    mock_session_instance.post = MagicMock(return_value=mock_post_context_manager)

    with patch('aiohttp.ClientSession', return_value=mock_session_instance):
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

    with patch('aiohttp.ClientSession', return_value=mock_session_instance):
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

    with patch('aiohttp.ClientSession', return_value=mock_session_instance):
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

    with patch('aiohttp.ClientSession', return_value=mock_session_instance):
        with pytest.raises(ValueError):
            await chat(messages=messages, max_tokens=max_tokens, best_of=1) 
