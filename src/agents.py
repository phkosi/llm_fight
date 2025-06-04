"""Async wrappers for calling Ollama chat completions."""
import aiohttp
import asyncio
from typing import List, Dict, Any

from .config import CONFIG
from .engine import constants as C
from .engine.logger import logger

OLLAMA_URL = CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_LLAMA_API_URL, str, fallback='http://localhost:11434/v1/chat/completions')

HEADERS = {
    C.CONTENT_TYPE: C.APPLICATION_JSON
}

MODEL = CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_LLAMA_DEFAULT_MODEL, str)
TEMP = CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_LLAMA_TEMPERATURE, float)
BEST_OF_F = CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_BEST_OF_FIGHTER, int)
BEST_OF_J = CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_BEST_OF_JUDGE, int)

# -------------- helper ---------------------------------------------
async def _post_json(payload: Dict[str, Any]):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(OLLAMA_URL, json=payload, headers=HEADERS, timeout=300) as resp:
                resp.raise_for_status()
                data = await resp.json()
                return data[C.OLLAMA_CHOICES][0][C.OLLAMA_MESSAGE][C.AGENT_CONTENT]
    except aiohttp.ClientResponseError as e:
        logger.error(f"Ollama API request failed with status {e.status}: {e.message}. Payload: {payload}")
        raise
    except aiohttp.ClientConnectionError as e:
        logger.error(f"Ollama API connection error: {e}. Is Ollama running at {OLLAMA_URL}?")
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
    for _ in range(best_of):
        payload = {
            C.AGENT_MODEL: MODEL,
            C.TEMPERATURE: TEMP,
            C.AGENT_MAX_TOKENS: max_tokens,
            C.AGENT_MESSAGES: messages,
        }
        tasks.append(_post_json(payload))
    responses = await asyncio.gather(*tasks)
    # Caller will handle picking/parsing from the list.
    return responses
