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

    RICH_AVAILABLE = True
    Console = RichConsole
except Exception:  # pragma: no cover - import error fallback
    RICH_AVAILABLE = False

    class Console:
        """Minimal console fallback printing to stdout."""

        def print(self, *objects: object, **kwargs: object) -> None:
            for obj in objects:
                print(obj)


def get_console(**kwargs: object) -> Console:
    """Return a :class:`rich.console.Console` if available."""

    if RICH_AVAILABLE:
        return RichConsole(**kwargs)
    return Console()


def make_turn_table(turn: CombatTurn, simple: bool = False) -> "Table | str":
    """Return a rich ``Table`` or plain text representation of ``turn``."""
    if simple or not RICH_AVAILABLE:
        if simple:
            return turn.to_simple_text()
        return turn.to_text()

    table = Table(title=f"Turn {turn.turn}")
    table.add_column("Fighter A", style="cyan")
    table.add_column("Fighter B", style="magenta")
    table.add_row(turn.attempt_A, turn.attempt_B)
    table.add_row(turn.judge_p1.get("judgement_text", ""), turn.narration)
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
