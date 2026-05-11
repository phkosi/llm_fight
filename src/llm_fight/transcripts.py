from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from . import config as config_mod
from .engine import constants as C
from .engine.logger import logger


def log_exchange(messages: list[dict], responses: list[str]) -> None:
    """Append a prompt/response pair to a transcript file.

    Each exchange is written as a JSON line with a filename that includes
    microseconds to avoid collisions when multiple exchanges happen in quick
    succession.
    """
    if not config_mod.CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_SAVE_TRANSCRIPTS, bool, fallback=False):
        return

    directory = Path(config_mod.CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_TRANSCRIPT_DIR, str, fallback="transcripts"))
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.error(f"Failed to create transcript directory '{directory}': {exc}")
        return

    # Include microseconds to avoid collisions when multiple exchanges occur
    # within the same second.
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = directory / f"{timestamp}.json"

    entry = {"prompt": messages, "responses": responses}
    try:
        with path.open("a", encoding="utf-8") as f:
            json.dump(entry, f)
            f.write("\n")
    except OSError as exc:
        logger.error(f"Failed to write transcript '{path}': {exc}")
