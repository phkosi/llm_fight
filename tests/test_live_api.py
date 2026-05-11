import os
import asyncio
import pytest

from llm_fight.agents import chat
from llm_fight.engine import constants as C

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_chat_live_api():
    api_url = os.environ.get("API_URL")
    if not api_url:
        pytest.skip("API_URL env var not set")
    messages = [{C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: "Hello"}]
    responses = await asyncio.wait_for(chat(messages=messages, max_tokens=10, best_of=1), timeout=20)
    assert isinstance(responses, list)
    assert len(responses) == 1
    assert isinstance(responses[0], str)
