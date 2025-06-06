import os
import pytest
import httpx

from src.agents import chat, get_ollama_url
from src.utils.token_counter import compute_max_tokens
from src.engine import constants as C


def _ps_vram() -> int:
    """Return total VRAM usage across Ollama processes in MB."""
    base_url = get_ollama_url().split("/v1/chat/completions")[0]
    resp = httpx.get(f"{base_url}/api/ps", timeout=5)
    resp.raise_for_status()
    processes = resp.json()
    return sum(p.get("size_vram", 0) for p in processes)


@pytest.mark.skipif(os.environ.get("CI"), reason="Requires running Ollama server")
@pytest.mark.asyncio
async def test_memory_footprint_large_context():
    api_url = os.environ.get("API_URL")
    if not api_url:
        pytest.skip("API_URL env var not set")

    messages = [{C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: "ping"}]

    max_24k = compute_max_tokens(messages, 24000)
    before_24k = _ps_vram()
    resp_24k = await chat(
        messages=messages,
        max_tokens=max_24k,
        num_ctx=24000,
        best_of=1,
    )
    after_24k = _ps_vram()

    max_48k = compute_max_tokens(messages, 48000)
    before_48k = _ps_vram()
    resp_48k = await chat(
        messages=messages,
        max_tokens=max_48k,
        num_ctx=48000,
        best_of=1,
    )
    after_48k = _ps_vram()

    assert isinstance(resp_24k, list) and len(resp_24k) == 1
    assert isinstance(resp_48k, list) and len(resp_48k) == 1

    print(f"VRAM diff 24k: {after_24k - before_24k} MB")
    print(f"VRAM diff 48k: {after_48k - before_48k} MB")
