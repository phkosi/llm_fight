"""Utilities for formatting combat logs using rich tables."""

from __future__ import annotations

from collections import Counter
from statistics import mean
from typing import Iterable

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
    changes = turn.status_changes_text()
    if changes:
        table.add_row("Status changes", changes)
    return table


def make_summary_table(results: Iterable[dict[str, str]]) -> "Table | str":
    """Create a summary table from simulation ``results``."""
    data = list(results)
    winners = Counter(r.get(C.WINNER, C.DRAW) for r in data)
    avg_turns = mean(int(r.get(C.LOG_TURN, "0")) for r in data) if data else 0.0

    if not RICH_AVAILABLE:
        lines = [f"{w}: {c}" for w, c in winners.items()]
        lines.append(f"Average Turns: {avg_turns:.1f}")
        return "\n".join(lines)

    table = Table(title="Simulation Summary")
    table.add_column("Winner")
    table.add_column("Count", justify="right")
    for w, c in winners.items():
        table.add_row(w, str(c))
    table.add_row("Average Turns", f"{avg_turns:.1f}")
    return table
