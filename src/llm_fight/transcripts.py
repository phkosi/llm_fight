from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from . import config as config_mod
from .engine import constants as C
from .engine.logger import logger

TRACE_SCHEMA_VERSION = 1

_ACTIVE_TRACE: ContextVar[TraceWriter | None] = ContextVar("llm_fight_active_trace", default=None)
_TRACE_PHASE: ContextVar[str | None] = ContextVar("llm_fight_trace_phase", default=None)
_TRACE_TURN: ContextVar[int | None] = ContextVar("llm_fight_trace_turn", default=None)
_TRACE_FIGHTER_ID: ContextVar[str | None] = ContextVar("llm_fight_trace_fighter_id", default=None)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _timestamp_for_filename() -> str:
    return datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(cast(Any, value)))
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _trace_enabled() -> bool:
    return config_mod.CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_SAVE_TRANSCRIPTS, bool, fallback=False)


def _trace_directory() -> Path:
    return Path(config_mod.CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_TRANSCRIPT_DIR, str, fallback="transcripts"))


class NullTraceWriter:
    """No-op writer used when transcripts are disabled."""

    enabled = False
    fight_id: str | None = None
    run_index: int | None = None
    path: Path | None = None

    def write_event(
        self,
        *,
        event: str,
        phase: str,
        data: dict[str, Any] | None = None,
        turn: int | None = None,
        fighter_id: str | None = None,
    ) -> None:
        return

    def write_fight_event(self, event: Any) -> None:
        return


class TraceWriter:
    """Append-only JSONL trace writer for one fight."""

    enabled = True

    def __init__(self, path: Path, *, fight_id: str, run_index: int | None = None) -> None:
        self.path = path
        self.fight_id = fight_id
        self.run_index = run_index
        self._event_index = 0

    def write_event(
        self,
        *,
        event: str,
        phase: str,
        data: dict[str, Any] | None = None,
        turn: int | None = None,
        fighter_id: str | None = None,
    ) -> None:
        entry = {
            "schema_version": TRACE_SCHEMA_VERSION,
            "event_index": self._event_index,
            "timestamp": _utc_now(),
            "fight_id": self.fight_id,
            "run_index": self.run_index,
            "turn": turn,
            "phase": phase,
            "event": event,
            "fighter_id": fighter_id,
            "data": _jsonable(data or {}),
        }
        self._event_index += 1
        try:
            with self.path.open("a", encoding="utf-8") as fp:
                json.dump(entry, fp, sort_keys=True, separators=(",", ":"))
                fp.write("\n")
                fp.flush()
        except OSError as exc:
            logger.error("Failed to write trace '%s': %s", self.path, exc)

    def write_fight_event(self, event: Any) -> None:
        name = str(getattr(event, "name", "event"))
        data = getattr(event, "data", {}) or {}
        self.write_event(
            event=name,
            phase=_phase_for_event(name, data),
            turn=getattr(event, "turn", None),
            fighter_id=getattr(event, "fighter_id", None),
            data=_event_data_for_trace(name, data),
        )


def _phase_for_event(event_name: str, data: dict[str, Any]) -> str:
    if event_name == C.FIGHT_EVENT_TOKEN_METADATA:
        return str(data.get("phase") or "llm")
    if event_name.startswith("profile_generation"):
        return "profile_generation"
    if event_name == C.FIGHT_EVENT_FIGHTERS_READY:
        return "setup"
    if event_name.startswith("fighter_action"):
        return "fighter_action"
    if event_name.startswith("judge_phase1"):
        return "judge_phase1"
    if event_name.startswith("rolls"):
        return "rolls"
    if event_name.startswith("judge_phase2"):
        return "judge_phase2"
    if event_name.startswith("deltas"):
        return "deltas"
    if event_name.startswith("effects"):
        return "effects"
    if event_name == C.FIGHT_EVENT_TURN_COMPLETE:
        return "turn"
    if event_name == C.FIGHT_EVENT_FIGHT_COMPLETE:
        return "fight"
    return "fight"


def _event_data_for_trace(event_name: str, data: dict[str, Any]) -> dict[str, Any]:
    if event_name == C.FIGHT_EVENT_TURN_COMPLETE and "turn" in data:
        return {"turn": data["turn"]}
    return data


def create_fight_trace(run_index: int | None = None, fight_id: str | None = None) -> TraceWriter | NullTraceWriter:
    """Create a fight-scoped trace writer or a no-op writer if disabled."""
    if not _trace_enabled():
        return NullTraceWriter()

    directory = _trace_directory()
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.error("Failed to create transcript directory '%s': %s", directory, exc)
        return NullTraceWriter()

    resolved_fight_id = fight_id or uuid.uuid4().hex[:12]
    run_part = f"_run{run_index:04d}" if run_index is not None else ""
    path = directory / f"{_timestamp_for_filename()}{run_part}_{resolved_fight_id}.jsonl"
    return TraceWriter(path, fight_id=resolved_fight_id, run_index=run_index)


@contextmanager
def active_trace(writer: TraceWriter | NullTraceWriter) -> Iterator[None]:
    token = _ACTIVE_TRACE.set(cast(TraceWriter | None, writer if getattr(writer, "enabled", False) else None))
    try:
        yield
    finally:
        _ACTIVE_TRACE.reset(token)


@contextmanager
def llm_trace_context(
    *,
    phase: str,
    turn: int | None = None,
    fighter_id: str | None = None,
) -> Iterator[None]:
    phase_token = _TRACE_PHASE.set(phase)
    turn_token = _TRACE_TURN.set(turn)
    fighter_token = _TRACE_FIGHTER_ID.set(fighter_id)
    try:
        yield
    finally:
        _TRACE_FIGHTER_ID.reset(fighter_token)
        _TRACE_TURN.reset(turn_token)
        _TRACE_PHASE.reset(phase_token)


def _current_trace() -> TraceWriter | None:
    writer = _ACTIVE_TRACE.get()
    return writer if getattr(writer, "enabled", False) else None


def log_exchange(
    messages: list[dict],
    responses: list[str],
    metadata_items: list[dict[str, Any]] | None = None,
) -> None:
    """Record a prompt/response exchange.

    During an active fight trace this appends an ``llm_exchange`` event to the
    fight JSONL trace. Outside a fight, it preserves the legacy per-exchange
    JSON fragment behavior for compatibility.
    """
    writer = _current_trace()
    if writer is not None:
        data = {
            "messages": messages,
            "responses": responses,
        }
        if metadata_items:
            data["metadata"] = metadata_items
        writer.write_event(
            event="llm_exchange",
            phase=_TRACE_PHASE.get() or "llm",
            turn=_TRACE_TURN.get(),
            fighter_id=_TRACE_FIGHTER_ID.get(),
            data=data,
        )
        return

    if not _trace_enabled():
        return

    directory = _trace_directory()
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.error(f"Failed to create transcript directory '{directory}': {exc}")
        return

    path = directory / f"{_timestamp_for_filename()}.json"

    entry = {"prompt": messages, "responses": responses}
    if metadata_items:
        entry["metadata"] = metadata_items
    try:
        with path.open("a", encoding="utf-8") as fp:
            json.dump(entry, fp)
            fp.write("\n")
    except OSError as exc:
        logger.error(f"Failed to write transcript '{path}': {exc}")
