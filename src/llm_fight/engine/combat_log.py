from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import constants as C
from . import turn_display


@dataclass
class CombatTurn:
    """Represents a single turn in the combat log."""

    turn: int
    attempt_A: str = ""
    attempt_B: str = ""
    judge_p1: dict[str, Any] = field(default_factory=dict)
    judge_p2: dict[str, Any] = field(default_factory=dict)
    state_A_before: dict[str, Any] = field(default_factory=dict)
    state_B_before: dict[str, Any] = field(default_factory=dict)
    state_A_after: dict[str, Any] = field(default_factory=dict)
    state_B_after: dict[str, Any] = field(default_factory=dict)
    rolls: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def narration(self) -> str:
        return self.judge_p2.get(C.NARRATION, "")

    @property
    def p2_metadata(self) -> dict[str, Any]:
        metadata = self.judge_p2.get(C.METADATA, {})
        return metadata if isinstance(metadata, dict) else {}

    @property
    def p2_fallback_used(self) -> bool:
        return self.p2_metadata.get(C.P2_FALLBACK_USED) is True

    @property
    def p2_engine_repair_used(self) -> bool:
        return self.p2_metadata.get(C.P2_ENGINE_REPAIR_USED) is True

    def p2_fallback_text(self) -> str:
        if self.p2_engine_repair_used:
            return ""
        return C.P2_FALLBACK_MARKER_TEXT if self.p2_fallback_used else ""

    def roll_lines(self) -> list[str]:
        return turn_display.roll_lines(self)

    def rolls_text(self, separator: str = "\n") -> str:
        return turn_display.rolls_text(self, separator)

    def judge_ruling_lines(self) -> list[str]:
        return turn_display.judge_ruling_lines(self)

    def judge_ruling_text(self, separator: str = "\n") -> str:
        return turn_display.judge_ruling_text(self, separator)

    def status_changes_text(self) -> str:
        return turn_display.status_changes_text(self)

    def mechanical_change_lines(self) -> list[str]:
        return turn_display.mechanical_change_lines(self)

    def mechanical_changes_text(self, separator: str = "\n") -> str:
        return turn_display.mechanical_changes_text(self, separator)

    def to_text(self) -> str:
        return turn_display.turn_to_text(self)

    def to_simple_text(self) -> str:
        return turn_display.turn_to_simple_text(self)

    def __str__(self) -> str:  # pragma: no cover - thin wrapper
        return self.to_text()


class CombatLog:
    """Container for `CombatTurn` objects with helper query methods."""

    def __init__(self) -> None:
        self.turns: list[CombatTurn] = []
        self.profile_generation: dict[str, Any] = {}

    def append(self, turn: CombatTurn) -> None:
        self.turns.append(turn)

    def __len__(self) -> int:
        return len(self.turns)

    def get_last_n(self, n: int) -> list[CombatTurn]:
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
            if t.p2_fallback_used and not t.p2_engine_repair_used:
                lines.append(f"Turn {t.turn}: {t.p2_fallback_text()}")
            elif t.narration:
                lines.append(f"Turn {t.turn}: {t.narration}")
        return "\n".join(lines)
