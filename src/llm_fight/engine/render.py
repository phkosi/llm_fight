"""Utilities for formatting combat logs using rich tables."""

from __future__ import annotations

from collections import Counter
from statistics import mean
from typing import Any, Iterable

from .combat_log import CombatTurn
from . import constants as C

try:
    from rich.table import Table
    from rich.console import Console as RichConsole
    from rich.text import Text

    RICH_AVAILABLE = True
    Console = RichConsole
except Exception:  # pragma: no cover - import error fallback
    RICH_AVAILABLE = False

    class Console:
        """Minimal console fallback printing to stdout."""

        def print(self, *objects: object, **kwargs: object) -> None:
            for obj in objects:
                print(obj)


def make_turn_table(turn: CombatTurn, simple: bool = False) -> "Table | str":
    """Return a rich ``Table`` or plain text representation of ``turn``."""
    if simple or not RICH_AVAILABLE:
        if simple:
            return turn.to_simple_text()
        return turn.to_text()

    table = Table(title=f"Turn {turn.turn}", show_lines=True)
    table.add_column("Phase", style="bold", no_wrap=True)
    table.add_column("Details")
    if turn.attempt_A:
        table.add_row("Fighter A attempt", Text(turn.attempt_A, style="cyan"))
    if turn.attempt_B:
        table.add_row("Fighter B attempt", Text(turn.attempt_B, style="magenta"))
    judge = turn.judge_ruling_text()
    if judge:
        table.add_row("Judge ruling", Text(judge, style="yellow"))
    if turn.narration:
        table.add_row("Outcome", Text(turn.narration, style="green"))
    fallback = turn.p2_fallback_text()
    if fallback:
        table.add_row("Warning", Text(fallback, style="bold red"))
    changes = turn.status_changes_text()
    if changes:
        table.add_row("Status changes", changes)
    return table


def _effect_names(state: dict[str, Any]) -> str:
    names = []
    for effect in state.get(C.BUFFS, []) + state.get(C.DEBUFFS, []):
        if isinstance(effect, dict) and effect.get(C.NAME):
            names.append(str(effect[C.NAME]))
    return ", ".join(names) if names else "none"


def _fighter_design_lines(fighter_id: str, state: dict[str, Any]) -> list[str]:
    title = f"Fighter {fighter_id}: {state.get('class_', 'Unknown Fighter')}"
    theme = state.get(C.THEME)
    if theme:
        title += f" ({theme})"
    lines = [
        title,
        f"  Loadout: {state.get(C.LOADOUT, 'unknown')}",
        f"  Environment: {state.get('environment', 'unknown')}",
        f"  Body parts: {', '.join(sorted(state.get('parts', {}).keys())) or 'none'}",
        f"  Active effects: {_effect_names(state)}",
    ]
    profile_generation = state.get(C.PROFILE_GENERATION)
    if profile_generation:
        lines.append(f"  Profile generation: {profile_generation}")
    return lines


def make_fighter_design_view(fighters: dict[str, dict[str, Any]], simple: bool = False) -> "Table | str":
    """Return a pre-fight fighter design view for rich or plain output."""
    if simple or not RICH_AVAILABLE:
        lines = ["Fighter Designs"]
        for fighter_id in (C.FIGHTER_A, C.FIGHTER_B):
            lines.extend(_fighter_design_lines(fighter_id, fighters.get(fighter_id, {})))
        return "\n".join(lines)

    table = Table(title="Fighter Designs", show_lines=True)
    table.add_column("Fighter", style="bold", no_wrap=True)
    table.add_column("Design")
    for fighter_id in (C.FIGHTER_A, C.FIGHTER_B):
        state = fighters.get(fighter_id, {})
        table.add_row(fighter_id, "\n".join(_fighter_design_lines(fighter_id, state)))
    return table


_EVENT_STATUS_LABELS = {
    C.FIGHT_EVENT_PROFILE_GENERATION_START: "Generating fighter profile",
    C.FIGHT_EVENT_PROFILE_GENERATION_END: "Finished fighter profile",
    C.FIGHT_EVENT_FIGHTERS_READY: "Fighters ready",
    C.FIGHT_EVENT_FIGHTER_ACTION_START: "Generating fighter action",
    C.FIGHT_EVENT_FIGHTER_ACTION_END: "Finished fighter action",
    C.FIGHT_EVENT_JUDGE_PHASE1_START: "Judge Phase 1",
    C.FIGHT_EVENT_JUDGE_PHASE1_END: "Judge Phase 1 complete",
    C.FIGHT_EVENT_ROLLS_START: "Rolling outcomes",
    C.FIGHT_EVENT_ROLLS_END: "Rolls complete",
    C.FIGHT_EVENT_JUDGE_PHASE2_START: "Judge Phase 2",
    C.FIGHT_EVENT_JUDGE_PHASE2_END: "Judge Phase 2 complete",
    C.FIGHT_EVENT_DELTAS_START: "Applying deltas",
    C.FIGHT_EVENT_DELTAS_END: "Deltas applied",
    C.FIGHT_EVENT_EFFECTS_START: "Ticking effects",
    C.FIGHT_EVENT_EFFECTS_END: "Effects ticked",
    C.FIGHT_EVENT_TURN_COMPLETE: "Turn complete",
    C.FIGHT_EVENT_FIGHT_COMPLETE: "Fight complete",
}


def format_fight_event_status(event: Any) -> str:
    """Return a short user-facing status line for a play event."""
    label = _EVENT_STATUS_LABELS.get(getattr(event, "name", ""), str(getattr(event, "name", "event")))
    fighter_id = getattr(event, "fighter_id", None)
    turn = getattr(event, "turn", None)
    event_name = getattr(event, "name", "")
    suffixes = []
    if fighter_id:
        suffixes.append(f"Fighter {fighter_id}")
    if turn is not None and event_name not in {
        C.FIGHT_EVENT_PROFILE_GENERATION_START,
        C.FIGHT_EVENT_PROFILE_GENERATION_END,
    }:
        suffixes.append(f"turn {turn}")
    if suffixes:
        return f"{label} ({', '.join(suffixes)})"
    return label


def format_token_summary(metadata_items: Iterable[dict[str, Any]]) -> str:
    """Summarize real provider token metadata, or report that it is unavailable."""
    items = [item for item in metadata_items if item]
    if not items:
        return "Token usage: tokens unavailable"

    prompt_tokens = sum(item.get("prompt_tokens", 0) for item in items if isinstance(item.get("prompt_tokens"), int))
    completion_tokens = sum(
        item.get("completion_tokens", 0) for item in items if isinstance(item.get("completion_tokens"), int)
    )
    total_tokens = sum(item.get("total_tokens", 0) for item in items if isinstance(item.get("total_tokens"), int))
    if not total_tokens and (prompt_tokens or completion_tokens):
        total_tokens = prompt_tokens + completion_tokens

    parts = []
    if prompt_tokens:
        parts.append(f"prompt {prompt_tokens}")
    if completion_tokens:
        parts.append(f"completion {completion_tokens}")
    if total_tokens:
        parts.append(f"total {total_tokens}")
    if not parts:
        return "Token usage: tokens unavailable"
    return "Token usage: " + ", ".join(parts)


def make_summary_table(results: Iterable[dict[str, str]], total_runs: int | None = None) -> "Table | str":
    """Create a summary table from simulation ``results``."""
    data = list(results)
    if total_runs is None:
        total_runs = len(data)
    error_rows = sum(1 for r in data if r.get(C.WINNER) == C.BATCH_ERROR_WINNER)
    completed_rows = len(data) - error_rows
    fallback_rows = sum(1 for r in data if str(r.get(C.LOG_P2_FALLBACK_USED, "")).lower() == "true")
    fallback_turns = sum(int(r.get(C.LOG_P2_FALLBACK_TURNS) or 0) for r in data)
    winners = Counter(r.get(C.WINNER, C.DRAW) for r in data)
    avg_turns = mean(int(r.get(C.LOG_TURN, "0")) for r in data) if data else 0.0

    if not RICH_AVAILABLE:
        lines = [
            f"Total Runs: {total_runs}",
            f"Completed Rows: {completed_rows}",
            f"Error Rows: {error_rows}",
            f"P2 Fallback Rows: {fallback_rows}",
            f"P2 Fallback Turns: {fallback_turns}",
        ]
        lines.extend(f"{w}: {c}" for w, c in winners.items())
        lines.append(f"Average Turns: {avg_turns:.1f}")
        return "\n".join(lines)

    table = Table(title="Simulation Summary")
    table.add_column("Metric")
    table.add_column("Count", justify="right")
    table.add_row("Total Runs", str(total_runs))
    table.add_row("Completed Rows", str(completed_rows))
    table.add_row("Error Rows", str(error_rows))
    table.add_row("P2 Fallback Rows", str(fallback_rows))
    table.add_row("P2 Fallback Turns", str(fallback_turns))
    for w, c in winners.items():
        table.add_row(w, str(c))
    table.add_row("Average Turns", f"{avg_turns:.1f}")
    return table
