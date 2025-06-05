"""Async wrappers for calling Ollama chat completions."""

import aiohttp
import asyncio
import os
from typing import List, Dict, Any, Optional

from .config import CONFIG
from .engine import constants as C
from .engine.logger import logger
from .transcripts import log_exchange


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


HEADERS = {C.CONTENT_TYPE: C.APPLICATION_JSON}


class SessionManager:
    """Async context manager that provides an ``aiohttp.ClientSession``."""

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> aiohttp.ClientSession:
        self._session = aiohttp.ClientSession(trust_env=True)
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None


# -------------- helper ---------------------------------------------
async def _post_json(session: aiohttp.ClientSession, payload: Dict[str, Any]) -> str:
    try:
        # Allow aiohttp to respect proxy-related environment variables
        # like HTTPS_PROXY so network-restricted environments can
        # successfully connect to remote APIs.
        async with session.post(get_ollama_url(), json=payload, headers=HEADERS, timeout=300) as resp:
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


async def chat(
    messages: List[Dict[str, str]],
    max_tokens: int,
    best_of: int = 1,
    schema: Optional[Dict[str, Any]] = None,
) -> List[str]:
    tasks = []
    model = CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_LLAMA_DEFAULT_MODEL, str)
    temp = CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_LLAMA_TEMPERATURE, float)
    async with SessionManager() as session:
        for _ in range(best_of):
            payload = {
                C.AGENT_MODEL: model,
                C.TEMPERATURE: temp,
                C.AGENT_MAX_TOKENS: max_tokens,
                C.AGENT_MESSAGES: messages,
            }
            if schema is not None:
                payload[C.AGENT_FORMAT] = schema
            tasks.append(_post_json(session, payload))
        responses = await asyncio.gather(*tasks)
    log_exchange(messages, responses)
    return responses
