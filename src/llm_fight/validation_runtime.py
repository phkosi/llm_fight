"""Runtime validation and retry helpers."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from jsonschema import ValidationError, validate

from . import config as config_mod
from .engine.logger import logger

SleepFunc = Callable[[float], Awaitable[Any]]
RetryCallback = Callable[[dict[str, Any]], None]


async def guarded_call(
    func: Callable[[], Any],
    schema: dict[str, Any],
    max_retries: int | None = None,
    *,
    sleep: SleepFunc = asyncio.sleep,
    on_retry: RetryCallback | None = None,
) -> Any:
    """Call ``func`` until ``schema`` validates or retries are exhausted."""

    backoff_base = 1
    last_error = None
    if max_retries is None:
        max_retries = config_mod.CONFIG.get_invalid_output_retries()

    for attempt in range(max_retries + 1):
        try:
            data = await func()
            validate(data, schema)
            return data
        except (ValidationError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt >= max_retries:
                raise RuntimeError(
                    f"Validation/JSON parsing failed after {max_retries + 1} attempts: {last_error}"
                ) from last_error

            logger.warning("guarded_call attempt %s/%s failed: %s", attempt + 1, max_retries + 1, exc)
            if on_retry is not None:
                on_retry(
                    {
                        "attempt": attempt + 1,
                        "next_attempt": attempt + 2,
                        "max_attempts": max_retries + 1,
                        "reason": "invalid_output",
                        "error_type": type(exc).__name__,
                    }
                )
            delay = backoff_base * 2**attempt
            logger.debug("Sleeping %.1fs before retry", delay)
            await sleep(delay)
    if last_error:
        raise RuntimeError(f"Validation/JSON parsing failed: {last_error}")
    raise RuntimeError("Guarded call failed without specific error after retries.")
