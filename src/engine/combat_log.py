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

    def to_text(self) -> str:
        """Return a concise, human-readable summary of the turn."""
        parts = [f"Turn {self.turn}"]
        if self.attempt_A:
            parts.append(f"A: {self.attempt_A}")
        if self.attempt_B:
            parts.append(f"B: {self.attempt_B}")
        jtext = self.judge_p1.get("judgement_text")
        if jtext:
            parts.append(f"Judge: {jtext}")
        narr = self.narration
        if narr:
            parts.append(f"Narration: {narr}")
        return " | ".join(parts)

    def to_simple_text(self) -> str:
        """Return a multi-line debug representation of the turn."""
        lines = [f"Turn {self.turn}:"]
        if self.attempt_A:
            lines.append(f"A: {self.attempt_A}")
        if self.attempt_B:
            lines.append(f"B: {self.attempt_B}")
        jtext = self.judge_p1.get("judgement_text")
        if jtext:
            lines.append(f"Judge: {jtext}")
        narr = self.narration
        if narr:
            lines.append(f"Narration: {narr}")

        changes = []
        before_a = self.state_A_before.get("status")
        after_a = self.state_A_after.get("status")
        if hasattr(after_a, "value"):
            after_a = after_a.value
        if hasattr(before_a, "value"):
            before_a = before_a.value
        if before_a and after_a and before_a != after_a:
            changes.append(f"A {after_a}")
        before_b = self.state_B_before.get("status")
        after_b = self.state_B_after.get("status")
        if hasattr(after_b, "value"):
            after_b = after_b.value
        if hasattr(before_b, "value"):
            before_b = before_b.value
        if before_b and after_b and before_b != after_b:
            changes.append(f"B {after_b}")
        if changes:
            lines.append("Status changes: " + " ".join(changes))

        return "\n".join(lines)

    def __str__(self) -> str:  # pragma: no cover - thin wrapper
        return self.to_text()


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
        if last_n is not None:
            if last_n <= 0:
                return ""
            turns = self.turns[-last_n:]
        else:
            turns = self.turns

        lines = [f"Turn {t.turn}: {t.narration}" for t in turns if t.narration]
        return "\n".join(lines)
