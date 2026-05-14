"""Sanitized trial summaries used by private artifacts and blind packs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from llm_fight.engine import constants as C

from .artifacts import read_jsonl


def sanitized_error(exc: BaseException) -> dict[str, str]:
    return {
        "error_type": type(exc).__name__,
        "message": f"Fight aborted due to {type(exc).__name__}. See application logs for details.",
    }


def build_summary(
    *,
    status: str,
    result: dict[str, Any] | None,
    trace_path: Path | None,
    attempts: list[dict[str, Any]],
) -> dict[str, Any]:
    if status != "completed":
        return _error_summary(attempts)

    events = read_jsonl(trace_path) if trace_path is not None and trace_path.exists() else []
    fighters_ready = _first_event(events, C.FIGHT_EVENT_FIGHTERS_READY)
    fight_complete = _first_event(events, C.FIGHT_EVENT_FIGHT_COMPLETE)
    turns = [_turn_summary(event) for event in events if event.get("event") == C.FIGHT_EVENT_TURN_COMPLETE]
    fighters = _fighter_summaries(fighters_ready)
    resolved_result = result or (fight_complete.get("data", {}).get("result", {}) if fight_complete else {})
    fallback_count = sum(1 for turn in turns if turn.get(C.P2_FALLBACK_USED) is True)

    return {
        "status": "completed",
        "quality_markers": _quality_markers(fighters),
        "fighters": fighters,
        "turns": turns,
        "result": {
            C.WINNER: resolved_result.get(C.WINNER, ""),
            C.LOG_TURN: resolved_result.get(C.LOG_TURN, ""),
            C.LOG_P2_FALLBACK_USED: resolved_result.get(C.LOG_P2_FALLBACK_USED, str(fallback_count > 0).lower()),
            C.LOG_P2_FALLBACK_TURNS: resolved_result.get(C.LOG_P2_FALLBACK_TURNS, str(fallback_count)),
        },
        "attempts": _attempt_summaries(attempts),
    }


def render_summary_markdown(summary: dict[str, Any], *, title: str = "Fight Sample") -> str:
    lines = [f"# {title}", ""]
    status = summary.get("status", "unknown")
    lines.append(f"Status: {status}")

    if status != "completed":
        error = summary.get("error", {})
        lines.extend(["", "## Reliability", str(error.get("message", "Fight failed before completion."))])
        return "\n".join(lines).rstrip() + "\n"

    markers = summary.get("quality_markers", [])
    if markers:
        lines.extend(["", "## Quality Markers"])
        lines.extend(f"- {marker}" for marker in markers)

    lines.extend(["", "## Fighter Cards"])
    for fighter_id, fighter in summary.get("fighters", {}).items():
        display = fighter.get(C.DISPLAY_NAME) or fighter_id
        lines.append(f"- Fighter {fighter_id}: {display}")
        for field_name in ("class_", C.THEME, C.LOADOUT, "environment"):
            value = fighter.get(field_name)
            if value:
                lines.append(f"  {field_name}: {value}")
        target_parts = fighter.get("valid_target_parts", [])
        if target_parts:
            lines.append(f"  valid_target_parts: {', '.join(target_parts)}")
        profile_generation = fighter.get(C.PROFILE_GENERATION)
        if profile_generation:
            lines.append(f"  profile_generation: {_profile_generation_text(profile_generation)}")

    lines.extend(["", "## Turns"])
    for turn in summary.get("turns", []):
        lines.append(f"Turn {turn.get(C.LOG_TURN)}")
        if turn.get(C.LOG_ATTEMPT_A):
            lines.append(f"- Fighter A attempt: {turn[C.LOG_ATTEMPT_A]}")
        if turn.get(C.LOG_ATTEMPT_B):
            lines.append(f"- Fighter B attempt: {turn[C.LOG_ATTEMPT_B]}")
        for ruling in turn.get("judge_ruling", []):
            lines.append(f"- Judge ruling: {ruling}")
        for roll in _roll_lines(turn.get("rolls", {})):
            lines.append(f"- Roll: {roll}")
        if turn.get(C.NARRATION):
            lines.append(f"- Outcome: {turn[C.NARRATION]}")
        if turn.get(C.P2_FALLBACK_USED):
            lines.append(f"- {C.P2_FALLBACK_MARKER_TEXT}")
        for change in turn.get("mechanical_changes", []):
            lines.append(f"- Mechanical change: {change}")

    result = summary.get("result", {})
    lines.extend(["", "## Result"])
    lines.append(f"Winner: {result.get(C.WINNER, '')}")
    lines.append(f"Turns: {result.get(C.LOG_TURN, '')}")
    lines.append(f"P2 fallback turns: {result.get(C.LOG_P2_FALLBACK_TURNS, '0')}")
    return "\n".join(lines).rstrip() + "\n"


def _error_summary(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    last_error: dict[str, Any] = next(
        (attempt.get("error", {}) for attempt in reversed(attempts) if attempt.get("status") == "error"),
        {},
    )
    return {
        "status": "error",
        "error": {
            "error_type": last_error.get("error_type", "UnknownError"),
            "message": last_error.get("message", "Fight failed before completion."),
        },
        "attempts": _attempt_summaries(attempts),
    }


def _first_event(events: list[dict[str, Any]], name: str) -> dict[str, Any]:
    return next((event for event in events if event.get("event") == name), {})


def _fighter_summaries(fighters_ready: dict[str, Any]) -> dict[str, Any]:
    fighters = fighters_ready.get("data", {}).get("fighters", {})
    if not isinstance(fighters, dict):
        return {}
    return {
        fighter_id: _fighter_summary(fighter) for fighter_id, fighter in fighters.items() if isinstance(fighter, dict)
    }


def _fighter_summary(fighter: dict[str, Any]) -> dict[str, Any]:
    parts = fighter.get("parts", {})
    valid_parts = sorted(str(part_id) for part_id in parts) if isinstance(parts, dict) else []
    active_effects = []
    for list_name in (C.BUFFS, C.DEBUFFS):
        for effect in fighter.get(list_name, []) or []:
            if isinstance(effect, dict):
                active_effects.append(
                    {
                        C.TYPE: list_name,
                        C.NAME: effect.get(C.NAME, ""),
                        C.EFFECT_MECHANICS: effect.get(C.EFFECT_MECHANICS, []),
                        C.METADATA: effect.get(C.METADATA, {}),
                    }
                )
    return {
        C.DISPLAY_NAME: fighter.get(C.DISPLAY_NAME, ""),
        "class_": fighter.get("class_", ""),
        C.THEME: fighter.get(C.THEME, ""),
        C.LOADOUT: fighter.get(C.LOADOUT, ""),
        "environment": fighter.get("environment", ""),
        "valid_target_parts": valid_parts,
        "active_effects": active_effects,
        C.PROFILE_GENERATION: fighter.get(C.PROFILE_GENERATION),
    }


def _turn_summary(event: dict[str, Any]) -> dict[str, Any]:
    turn = event.get("data", {}).get("turn", {})
    if not isinstance(turn, dict):
        return {}
    return {
        C.LOG_TURN: turn.get(C.LOG_TURN),
        C.LOG_ATTEMPT_A: turn.get(C.LOG_ATTEMPT_A, ""),
        C.LOG_ATTEMPT_B: turn.get(C.LOG_ATTEMPT_B, ""),
        "judge_ruling": turn.get("judge_ruling", []),
        "rolls": turn.get("rolls", {}),
        C.NARRATION: turn.get(C.NARRATION, ""),
        C.P2_FALLBACK_USED: bool(turn.get(C.P2_FALLBACK_USED)),
        "mechanical_changes": turn.get("mechanical_changes", []),
    }


def _quality_markers(fighters: dict[str, Any]) -> list[str]:
    markers = []
    for fighter_id, fighter in fighters.items():
        profile_generation = fighter.get(C.PROFILE_GENERATION)
        if isinstance(profile_generation, dict) and profile_generation.get("mode") == "fallback":
            markers.append(
                f"Fighter {fighter_id} profile generation fell back to the configured seed fighter; "
                "the generated profile was invalid or unusable."
            )
    return markers


def _attempt_summaries(attempts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "attempt": attempt.get("attempt"),
            "status": attempt.get("status"),
            "error": attempt.get("error"),
        }
        for attempt in attempts
    ]


def _profile_generation_text(profile_generation: dict[str, Any]) -> str:
    mode = profile_generation.get("mode")
    nudge = profile_generation.get("nudge")
    error = profile_generation.get("error")
    pieces = [f"mode={mode}", f"nudge={nudge}"]
    if error:
        pieces.append(f"error={error}")
    return ", ".join(pieces)


def _roll_lines(rolls: dict[str, Any]) -> list[str]:
    lines = []
    for fighter_id, metadata in rolls.items():
        if not isinstance(metadata, dict):
            continue
        outcome = "success" if metadata.get("success") else "failed"
        probability = metadata.get("probability_text", "")
        roll = metadata.get("roll")
        roll_text = f"{roll:.3f}" if isinstance(roll, (int, float)) else "not rolled"
        lines.append(f"Fighter {fighter_id}: {outcome} (roll {roll_text}, p={probability})")
    return lines
