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

    @property
    def p2_metadata(self) -> Dict[str, Any]:
        metadata = self.judge_p2.get(C.METADATA, {})
        return metadata if isinstance(metadata, dict) else {}

    @property
    def p2_fallback_used(self) -> bool:
        return self.p2_metadata.get(C.P2_FALLBACK_USED) is True

    def p2_fallback_text(self) -> str:
        return C.P2_FALLBACK_MARKER_TEXT if self.p2_fallback_used else ""

    def judge_ruling_lines(self) -> list[str]:
        """Return Judge Phase 1 output as clear, display-ready lines."""
        lines = []
        judgement = self.judge_p1.get("judgement_text")
        if judgement:
            lines.append(str(judgement))

        for fighter in (C.FIGHTER_A, C.FIGHTER_B):
            detail = self._judge_attempt_ruling(fighter)
            if detail:
                lines.append(f"Fighter {fighter}: {detail}")

        explanation = self.judge_p1.get("explanation")
        if explanation:
            lines.append(f"Reasoning: {explanation}")

        return lines

    def judge_ruling_text(self, separator: str = "\n") -> str:
        return separator.join(self.judge_ruling_lines())

    def status_changes_text(self) -> str:
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
        return " ".join(changes)

    def to_text(self) -> str:
        """Return a concise, human-readable summary of the turn."""
        parts = [f"Turn {self.turn}"]
        if self.attempt_A:
            parts.append(f"Fighter A attempt: {self.attempt_A}")
        if self.attempt_B:
            parts.append(f"Fighter B attempt: {self.attempt_B}")
        judge = self.judge_ruling_text(separator="; ")
        if judge:
            parts.append(f"Judge ruling: {judge}")
        narr = self.narration
        if narr:
            parts.append(f"Outcome: {narr}")
        fallback = self.p2_fallback_text()
        if fallback:
            parts.append(fallback)
        changes = self.status_changes_text()
        if changes:
            parts.append(f"Status changes: {changes}")
        return " | ".join(parts)

    def to_simple_text(self) -> str:
        """Return a multi-line debug representation of the turn."""
        lines = [f"Turn {self.turn}:"]
        if self.attempt_A:
            lines.append(f"Fighter A attempt: {self.attempt_A}")
        if self.attempt_B:
            lines.append(f"Fighter B attempt: {self.attempt_B}")
        judge_lines = self.judge_ruling_lines()
        if judge_lines:
            lines.append("Judge ruling:")
            lines.extend(f"  {line}" for line in judge_lines)
        narr = self.narration
        if narr:
            lines.append(f"Outcome: {narr}")
        fallback = self.p2_fallback_text()
        if fallback:
            lines.append(fallback)

        changes = self.status_changes_text()
        if changes:
            lines.append(f"Status changes: {changes}")

        return "\n".join(lines)

    def _judge_attempt_ruling(self, fighter: str) -> str:
        key_prefix = f"{C.ATTEMPT}_{fighter}"
        valid = self.judge_p1.get(f"{key_prefix}_valid")
        prob = self.judge_p1.get(f"{key_prefix}_prob")

        parts = []
        if isinstance(valid, bool):
            parts.append("valid" if valid else "invalid")
        elif valid is not None:
            parts.append(f"validity={valid}")
        if prob not in (None, ""):
            parts.append(f"success p={prob}")

        return ", ".join(parts)

    def __str__(self) -> str:  # pragma: no cover - thin wrapper
        return self.to_text()


class CombatLog:
    """Container for `CombatTurn` objects with helper query methods."""

    def __init__(self) -> None:
        self.turns: List[CombatTurn] = []
        self.profile_generation: Dict[str, Any] = {}

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

        lines = []
        for t in turns:
            if t.p2_fallback_used:
                lines.append(f"Turn {t.turn}: {C.P2_FALLBACK_MARKER_TEXT}")
            elif t.narration:
                lines.append(f"Turn {t.turn}: {t.narration}")
        return "\n".join(lines)
