"""Filesystem helpers for trial artifacts."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def timestamp_slug() -> str:
    return datetime.now(UTC).strftime("%Y%m%d_%H%M%S")


def create_run_root(output_root: Path, timestamp: str | None = None) -> Path:
    base = output_root / (timestamp or timestamp_slug())
    root = base
    counter = 2
    while root.exists():
        root = base.with_name(f"{base.name}-{counter}")
        counter += 1
    root.mkdir(parents=True, exist_ok=False)
    (root / "cells").mkdir()
    (root / "blind_packs").mkdir()
    return root


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        for block in iter(lambda: fp.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def relative_to_root(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path)
