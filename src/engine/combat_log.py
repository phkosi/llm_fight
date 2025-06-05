from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List

from . import constants as C


@dataclass
class CombatTurn:
    """Represents a single turn in the combat log."""

    turn: int
    attempt_A: str = ""
    attempt_B: str = ""
    judge_p1: Dict[str, Any] = field(default_factory=dict)
    judge_p2: Dict[str, Any] = field(default_factory=dict)
    state_A_before: Dict[str, Any] = field(default_factory=dict)
    state_B_before: Dict[str, Any] = field(default_factory=dict)
    state_A_after: Dict[str, Any] = field(default_factory=dict)
    state_B_after: Dict[str, Any] = field(default_factory=dict)

    @property
    def narration(self) -> str:
        return self.judge_p2.get(C.NARRATION, "")


class CombatLog:
    """Container for `CombatTurn` objects with helper query methods."""

    def __init__(self) -> None:
        self.turns: List[CombatTurn] = []

    def append(self, turn: CombatTurn) -> None:
        self.turns.append(turn)

    def __len__(self) -> int:
        return len(self.turns)

    def get_last_n(self, n: int) -> List[CombatTurn]:
        return self.turns[-n:]

    def to_summary(self, last_n: int | None = None) -> str:
        """Return narration summary for all or the last `n` turns."""
        turns = self.turns if last_n is None else self.turns[-last_n:]
        lines = [f"Turn {t.turn}: {t.narration}" for t in turns if t.narration]
        return "\n".join(lines)
