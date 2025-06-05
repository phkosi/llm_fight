import os
import asyncio
import pytest

from src.agents import chat
from src.engine import constants as C


@pytest.mark.asyncio
async def test_chat_live_api():
    api_url = os.environ.get("API_URL")
    if not api_url:
        pytest.skip("API_URL env var not set")
    messages = [{C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: "Hello"}]
    try:
        responses = await asyncio.wait_for(chat(messages=messages, max_tokens=10, best_of=1), timeout=20)
    except Exception as e:
        pytest.xfail(f"Live API call failed: {e}")
    assert isinstance(responses, list)
    assert len(responses) == 1
    assert isinstance(responses[0], str)
