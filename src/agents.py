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
async def _post_json(session: aiohttp.ClientSession, payload: Dict[str, Any], retries: int = 0) -> str:
    attempt = 0
    while True:
        try:
            # Allow aiohttp to respect proxy-related environment variables
            # like HTTPS_PROXY so network-restricted environments can
            # successfully connect to remote APIs.
            async with session.post(get_ollama_url(), json=payload, headers=HEADERS, timeout=300) as resp:
                if resp.status >= 500:
                    raise aiohttp.ClientResponseError(
                        request_info=resp.request_info,
                        history=resp.history,
                        status=resp.status,
                        message=f"Server error {resp.status}",
                        headers=resp.headers,
                    )
                resp.raise_for_status()
                data = await resp.json()
                return data[C.OLLAMA_CHOICES][0][C.OLLAMA_MESSAGE][C.AGENT_CONTENT]

        except aiohttp.ClientResponseError as e:
            if e.status >= 500 and attempt < retries:
                delay = 2**attempt
                logger.warning(
                    f"Ollama API server error {e.status} (attempt {attempt + 1}/{retries + 1}). "
                    f"Retrying in {delay}s. Payload: {payload}"
                )
                attempt += 1
                await asyncio.sleep(delay)
                continue
            logger.error(f"Ollama API request failed with status {e.status}: {e.message}. Payload: {payload}")
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            if attempt < retries:
                delay = 2**attempt
                logger.warning(
                    f"Ollama API call failed (attempt {attempt + 1}/{retries + 1}): {e}. "
                    f"Retrying in {delay}s. Payload: {payload}"
                )
                attempt += 1
                await asyncio.sleep(delay)
                continue
            logger.error(f"Ollama API call failed after {attempt + 1} attempts: {e}. Payload: {payload}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during Ollama API call: {e}. Payload: {payload}")
            raise


async def chat(
    messages: List[Dict[str, str]],
    max_tokens: int,
    num_ctx: int | None = None,
    best_of: int = 1,
    schema: Optional[Dict[str, Any]] = None,
    session: aiohttp.ClientSession | None = None,
    retries: int = 0,
) -> List[str]:
    """Return ``best_of`` completions from Ollama.

    ``max_tokens`` limits how many tokens the model may generate. ``num_ctx``
    sets the context window for the request via Ollama's ``options``.
    ``retries`` specifies how many additional attempts should be made if the
    request fails due to network issues or 5xx responses.
    """
    tasks = []
    model = CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_LLAMA_DEFAULT_MODEL, str)
    temp = CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_LLAMA_TEMPERATURE, float)

    async def _collect(sess: aiohttp.ClientSession) -> List[str]:
        for _ in range(best_of):
            payload = {
                C.AGENT_MODEL: model,
                C.TEMPERATURE: temp,
                C.AGENT_MAX_TOKENS: max_tokens,
                C.AGENT_MESSAGES: messages,
            }
            if num_ctx is not None:
                payload[C.AGENT_OPTIONS] = {C.NUM_CTX: num_ctx}
            if schema is not None:
                payload[C.AGENT_FORMAT] = schema
            tasks.append(_post_json(sess, payload, retries=retries))
        return await asyncio.gather(*tasks)

    if session is None:
        async with SessionManager() as sess:
            responses = await _collect(sess)
    else:
        responses = await _collect(session)

    log_exchange(messages, responses)
    return responses
