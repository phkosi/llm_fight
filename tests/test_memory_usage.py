import os
import pytest
from ollama import AsyncClient

from llm_fight.agents import chat
from llm_fight.utils.token_counter import compute_max_tokens
from llm_fight.engine import constants as C

pytestmark = [pytest.mark.live, pytest.mark.perf]


async def _ollama_mem_usage(client: AsyncClient) -> int:
    resp = await client.ps()
    return sum(m.size for m in resp.models)


@pytest.mark.asyncio
async def test_memory_footprint_large_context():
    api_url = os.environ.get("API_URL")
    if not api_url:
        pytest.skip("API_URL env var not set")

    base = api_url.split("/v1")[0]
    client = AsyncClient(host=base)
    try:
        messages = [{C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: "ping"}]

        max_24k = compute_max_tokens(messages, 24000)
        before_24k = await _ollama_mem_usage(client)
        resp_24k = await chat(
            messages=messages,
            max_tokens=max_24k,
            num_ctx=24000,
            best_of=1,
        )
        after_24k = await _ollama_mem_usage(client)

        max_48k = compute_max_tokens(messages, 48000)
        before_48k = await _ollama_mem_usage(client)
        resp_48k = await chat(
            messages=messages,
            max_tokens=max_48k,
            num_ctx=48000,
            best_of=1,
        )
        after_48k = await _ollama_mem_usage(client)

        assert isinstance(resp_24k, list) and len(resp_24k) == 1
        assert isinstance(resp_48k, list) and len(resp_48k) == 1
        print(f"Memory diff 24k: {after_24k - before_24k} KB")
        print(f"Memory diff 48k: {after_48k - before_48k} KB")
    finally:
        await client._client.aclose()
