from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .config import CONFIG
from .engine import constants as C
from .engine.logger import logger


def log_exchange(messages: list[dict], responses: list[str]) -> None:
    """Append a prompt/response pair to a timestamped transcript file."""
    if not CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_SAVE_TRANSCRIPTS, bool, fallback=False):
        return

    directory = Path(CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_TRANSCRIPT_DIR, str, fallback="transcripts"))
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.error(f"Failed to create transcript directory '{directory}': {exc}")
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = directory / f"{timestamp}.json"

    entry = {"prompt": messages, "responses": responses}
    try:
        with path.open("a", encoding="utf-8") as f:
            json.dump(entry, f)
            f.write("\n")
    except OSError as exc:
        logger.error(f"Failed to write transcript '{path}': {exc}")
