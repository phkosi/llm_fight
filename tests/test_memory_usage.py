import os
import re
import shutil
import subprocess

import pytest

from src.agents import chat
from src.utils.token_counter import compute_max_tokens
from src.engine import constants as C


def _ps_memory_mb() -> float | None:
    """Return memory usage reported by ``ollama ps`` in megabytes."""
    if shutil.which("ollama") is None:
        return None
    try:
        out = subprocess.check_output(["ollama", "ps"], text=True, errors="ignore")
    except Exception:
        return None
    match = re.search(r"([0-9]+(?:\\.[0-9]+)?)\s*(GB|MB)", out)
    if not match:
        return None
    value = float(match.group(1))
    if match.group(2) == "GB":
        value *= 1024
    return value


@pytest.mark.asyncio
async def test_memory_footprint_large_context():
    api_url = os.environ.get("API_URL")
    if not api_url:
        pytest.skip("API_URL env var not set")
    if shutil.which("ollama") is None:
        pytest.skip("ollama command not found")

    messages = [{C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: "ping"}]

    max_24k = compute_max_tokens(messages, 24000)
    before_24k = _ps_memory_mb()
    resp_24k = await chat(
        messages=messages,
        max_tokens=max_24k,
        num_ctx=24000,
        best_of=1,
    )
    after_24k = _ps_memory_mb()

    max_48k = compute_max_tokens(messages, 48000)
    before_48k = _ps_memory_mb()
    resp_48k = await chat(
        messages=messages,
        max_tokens=max_48k,
        num_ctx=48000,
        best_of=1,
    )
    after_48k = _ps_memory_mb()

    assert isinstance(resp_24k, list) and len(resp_24k) == 1
    assert isinstance(resp_48k, list) and len(resp_48k) == 1

    if None not in (before_24k, after_24k):
        print(f"ps diff 24k: {after_24k - before_24k:.2f} MB")
    if None not in (before_48k, after_48k):
        print(f"ps diff 48k: {after_48k - before_48k:.2f} MB")
