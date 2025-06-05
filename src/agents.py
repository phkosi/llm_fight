"""Async wrappers for calling Ollama chat completions."""
import aiohttp
import asyncio
import os
from typing import List, Dict, Any

from .config import CONFIG
from .engine import constants as C
from .engine.logger import logger

def get_ollama_url() -> str:
    """Return the Ollama chat completions endpoint.

    If ``API_URL`` is provided via environment variable, ensure it points to the
    ``/v1/chat/completions`` endpoint. This makes it easier to override the
    base URL without needing to specify the full path.
    """

    url = os.environ.get(
        "API_URL",
        CONFIG.get(
            C.CONFIG_GENERAL,
            C.CONFIG_LLAMA_API_URL,
            str,
            fallback="http://localhost:11434/v1/chat/completions",
        ),
    )

    if not url.endswith("/v1/chat/completions"):
        url = url.rstrip("/") + "/v1/chat/completions"

    return url


# -------------- helper ---------------------------------------------
async def _post_json(payload: Dict[str, Any]):
    headers = {C.CONTENT_TYPE: C.APPLICATION_JSON}
    try:
        # Allow aiohttp to respect proxy-related environment variables
        # like HTTPS_PROXY so network-restricted environments can
        # successfully connect to remote APIs.
        async with aiohttp.ClientSession(trust_env=True) as session:
            async with session.post(get_ollama_url(), json=payload, headers=headers, timeout=300) as resp:
                resp.raise_for_status()
                data = await resp.json()
                return data[C.OLLAMA_CHOICES][0][C.OLLAMA_MESSAGE][C.AGENT_CONTENT]
    except aiohttp.ClientResponseError as e:
        logger.error(f"Ollama API request failed with status {e.status}: {e.message}. Payload: {payload}")
        raise
    except aiohttp.ClientConnectionError as e:
        logger.error(f"Ollama API connection error: {e}. Is Ollama running at {get_ollama_url()}?")
        raise
    except aiohttp.ContentTypeError as e:
        logger.error(f"Ollama API response content type error: {e}. Expected JSON. Payload: {payload}")
        raise
    except asyncio.TimeoutError:
        logger.error(f"Ollama API request timed out after 300s. Payload: {payload}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error during Ollama API call: {e}. Payload: {payload}")
        raise

async def chat(messages: List[Dict[str, str]], max_tokens: int, best_of: int = 1) -> List[str]:
    tasks = []
    model = CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_LLAMA_DEFAULT_MODEL, str)
    temp = CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_LLAMA_TEMPERATURE, float)
    for _ in range(best_of):
        payload = {
            C.AGENT_MODEL: model,
            C.TEMPERATURE: temp,
            C.AGENT_MAX_TOKENS: max_tokens,
            C.AGENT_MESSAGES: messages,
        }
        tasks.append(_post_json(payload))
    responses = await asyncio.gather(*tasks)
    # Caller will handle picking/parsing from the list.
    return responses
