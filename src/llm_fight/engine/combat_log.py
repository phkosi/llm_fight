from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import constants as C


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

    def p2_fallback_text(self) -> str:
        return C.P2_FALLBACK_MARKER_TEXT if self.p2_fallback_used else ""

    def roll_lines(self) -> list[str]:
        """Return display lines for per-fighter roll outcomes."""
        lines = []
        for fighter in (C.FIGHTER_A, C.FIGHTER_B):
            metadata = self.rolls.get(fighter, {})
            if not metadata:
                continue
            label = self._fighter_label(fighter)
            reason = metadata.get("reason")
            probability_text = metadata.get("probability_text")
            roll = metadata.get("roll")
            success = metadata.get("success")

            if reason == "invalid_attempt":
                suffix = f" (p={probability_text})" if probability_text not in (None, "") else ""
                lines.append(f"{label}: invalid / not rolled{suffix}")
            elif reason == "invalid_probability":
                lines.append(f"{label}: invalid probability {probability_text!r} / not rolled")
            elif reason in {"success", "failed"} and isinstance(roll, (int, float)):
                comparison = "<" if success else ">="
                outcome = "success" if success else "failed"
                lines.append(f"{label}: {outcome} (roll {roll:.3f} {comparison} p={probability_text})")
            else:
                lines.append(f"{label}: {reason or 'unknown'}")
        return lines

    def rolls_text(self, separator: str = "\n") -> str:
        return separator.join(self.roll_lines())

    def judge_ruling_lines(self) -> list[str]:
        """Return Judge Phase 1 output as clear, display-ready lines."""
        lines = []
        judgement = self.judge_p1.get("judgement_text")
        if judgement:
            lines.append(str(judgement))

        for fighter in (C.FIGHTER_A, C.FIGHTER_B):
            detail = self._judge_attempt_ruling(fighter)
            if detail:
                lines.append(f"{self._fighter_label(fighter)}: {detail}")

        explanation = self.judge_p1.get("explanation")
        if explanation:
            lines.append(f"Reasoning: {explanation}")

        return lines

    def judge_ruling_text(self, separator: str = "\n") -> str:
        return separator.join(self.judge_ruling_lines())

    def status_changes_text(self) -> str:
        return " ".join(self._status_change_lines())

    def mechanical_change_lines(self) -> list[str]:
        """Return concise before/after mechanical changes for the full turn."""
        lines = []
        for fighter in (C.FIGHTER_A, C.FIGHTER_B):
            before, after = self._fighter_states(fighter)
            lines.extend(self._stat_change_lines(fighter, before, after))
            lines.extend(self._wound_lines(fighter))
            lines.extend(self._body_part_change_lines(fighter, before, after))
            lines.extend(self._effect_change_lines(fighter, before, after))
        lines.extend(self._status_change_lines())
        if not lines and self._has_state_snapshots():
            return ["No mechanical state changes."]
        return lines

    def mechanical_changes_text(self, separator: str = "\n") -> str:
        return separator.join(self.mechanical_change_lines())

    def to_text(self) -> str:
        """Return a concise, human-readable summary of the turn."""
        parts = [f"Turn {self.turn}"]
        if self.attempt_A:
            parts.append(f"{self._fighter_label(C.FIGHTER_A)} attempt: {self.attempt_A}")
        if self.attempt_B:
            parts.append(f"{self._fighter_label(C.FIGHTER_B)} attempt: {self.attempt_B}")
        judge = self.judge_ruling_text(separator="; ")
        if judge:
            parts.append(f"Judge ruling: {judge}")
        rolls = self.rolls_text(separator="; ")
        if rolls:
            parts.append(f"Rolls: {rolls}")
        narr = self.narration
        if narr:
            parts.append(f"Outcome: {narr}")
        fallback = self.p2_fallback_text()
        if fallback:
            parts.append(fallback)
        changes = self.mechanical_changes_text(separator="; ")
        if changes:
            parts.append(f"Mechanical changes: {changes}")
        return " | ".join(parts)

    def to_simple_text(self) -> str:
        """Return a multi-line debug representation of the turn."""
        lines = [f"Turn {self.turn}:"]
        if self.attempt_A:
            lines.append(f"{self._fighter_label(C.FIGHTER_A)} attempt: {self.attempt_A}")
        if self.attempt_B:
            lines.append(f"{self._fighter_label(C.FIGHTER_B)} attempt: {self.attempt_B}")
        judge_lines = self.judge_ruling_lines()
        if judge_lines:
            lines.append("Judge ruling:")
            lines.extend(f"  {line}" for line in judge_lines)
        roll_lines = self.roll_lines()
        if roll_lines:
            lines.append("Rolls:")
            lines.extend(f"  {line}" for line in roll_lines)
        narr = self.narration
        if narr:
            lines.append(f"Outcome: {narr}")
        fallback = self.p2_fallback_text()
        if fallback:
            lines.append(fallback)

        change_lines = self.mechanical_change_lines()
        if change_lines:
            lines.append("Mechanical changes:")
            lines.extend(f"  {line}" for line in change_lines)

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

    def _fighter_states(self, fighter: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if fighter == C.FIGHTER_A:
            return self.state_A_before, self.state_A_after
        return self.state_B_before, self.state_B_after

    def _fighter_display_name(self, fighter: str) -> str:
        before, after = self._fighter_states(fighter)
        for state in (after, before):
            if isinstance(state, dict):
                display_name = " ".join(str(state.get(C.DISPLAY_NAME, "")).strip().split())
                if display_name:
                    return display_name
        return fighter

    def _fighter_label(self, fighter: str) -> str:
        display_name = self._fighter_display_name(fighter)
        if display_name and display_name != fighter:
            return f"Fighter {fighter} ({display_name})"
        return f"Fighter {fighter}"

    def _has_state_snapshots(self) -> bool:
        return any((self.state_A_before, self.state_A_after, self.state_B_before, self.state_B_after))

    def _stat_change_lines(self, fighter: str, before: dict[str, Any], after: dict[str, Any]) -> list[str]:
        lines = []
        for stat in (C.PAIN, C.EXHAUSTION, C.HEAT):
            before_value = before.get(stat)
            after_value = after.get(stat)
            if (
                isinstance(before_value, (int, float))
                and isinstance(after_value, (int, float))
                and before_value != after_value
            ):
                delta = after_value - before_value
                sign = "+" if delta > 0 else ""
                lines.append(
                    f"{self._fighter_display_name_suffix(fighter)} {stat} "
                    f"{sign}{delta:g} ({before_value:g} -> {after_value:g})"
                )
        return lines

    def _fighter_display_name_suffix(self, fighter: str) -> str:
        display_name = self._fighter_display_name(fighter)
        if display_name and display_name != fighter:
            return f"{fighter} ({display_name})"
        return fighter

    def _wound_lines(self, fighter: str) -> list[str]:
        delta = self.judge_p2.get(C.DELTA, {})
        if not isinstance(delta, dict):
            return []
        fighter_delta = delta.get(fighter, {})
        if not isinstance(fighter_delta, dict):
            return []
        wounds = fighter_delta.get(C.WOUNDS, [])
        if not isinstance(wounds, list):
            return []
        lines = []
        for wound in wounds:
            if not isinstance(wound, dict):
                continue
            part = wound.get(C.TARGETED_PART, "unknown")
            damage_type = wound.get(C.TYPE, C.DamageType.GENERIC)
            damage_type = damage_type.value if hasattr(damage_type, "value") else damage_type
            value = wound.get(C.VALUE, "?")
            source = wound.get(C.SOURCE)
            source_text = f" from {source}" if source else ""
            lines.append(
                f"{self._fighter_display_name_suffix(fighter)} wound: {part} {damage_type} {value}{source_text}"
            )
        return lines

    def _body_part_change_lines(self, fighter: str, before: dict[str, Any], after: dict[str, Any]) -> list[str]:
        before_parts = before.get("parts", {}) if isinstance(before, dict) else {}
        after_parts = after.get("parts", {}) if isinstance(after, dict) else {}
        if not isinstance(before_parts, dict) or not isinstance(after_parts, dict):
            return []

        lines = []
        for part_name in sorted(set(before_parts) | set(after_parts)):
            before_part = before_parts.get(part_name)
            after_part = after_parts.get(part_name)
            if before_part is None:
                lines.append(f"{self._fighter_display_name_suffix(fighter)} {part_name}: part added")
                continue
            if after_part is None:
                lines.append(f"{self._fighter_display_name_suffix(fighter)} {part_name}: part removed")
                continue

            changes = []
            before_status = self._status_value(before_part.get(C.STATUS))
            after_status = self._status_value(after_part.get(C.STATUS))
            if before_status != after_status:
                changes.append(f"status {before_status} -> {after_status}")
            before_severed = bool(before_part.get("severed", False))
            after_severed = bool(after_part.get("severed", False))
            if before_severed != after_severed:
                changes.append(f"severed {before_severed} -> {after_severed}")
            changes.extend(self._layer_hp_change_lines(before_part, after_part))
            if changes:
                lines.append(f"{self._fighter_display_name_suffix(fighter)} {part_name}: " + "; ".join(changes))
        return lines

    def _layer_hp_change_lines(self, before_part: dict[str, Any], after_part: dict[str, Any]) -> list[str]:
        before_layers = before_part.get("layers", []) if isinstance(before_part, dict) else []
        after_layers = after_part.get("layers", []) if isinstance(after_part, dict) else []
        if not isinstance(before_layers, list) or not isinstance(after_layers, list):
            return []

        changes = []
        for index, (before_layer, after_layer) in enumerate(zip(before_layers, after_layers, strict=False), start=1):
            before_hp = self._layer_current_hp(before_layer)
            after_hp = self._layer_current_hp(after_layer)
            if before_hp != after_hp:
                layer_name = after_layer.get(C.NAME) or before_layer.get(C.NAME) or f"layer {index}"
                changes.append(f"{layer_name} hp {before_hp} -> {after_hp}")
        return changes

    def _effect_change_lines(self, fighter: str, before: dict[str, Any], after: dict[str, Any]) -> list[str]:
        before_effects = self._effect_map(before)
        after_effects = self._effect_map(after)
        lines = []
        fighter_label = self._fighter_display_name_suffix(fighter)
        for identity in sorted(set(after_effects) - set(before_effects)):
            details = self._effect_details(after_effects[identity])
            lines.append(f"{fighter_label} {self._format_effect_identity(identity)} added {details}".rstrip())
        for identity in sorted(set(before_effects) - set(after_effects)):
            lines.append(f"{fighter_label} {self._format_effect_identity(identity)} removed/expired")
        for identity in sorted(set(before_effects) & set(after_effects)):
            changes = []
            before_eff = before_effects[identity]
            after_eff = after_effects[identity]
            for field_name in (C.EFFECT_TTL, "magnitude"):
                before_value = before_eff.get(field_name)
                after_value = after_eff.get(field_name)
                if before_value != after_value:
                    changes.append(f"{field_name} {before_value} -> {after_value}")
            if changes:
                lines.append(f"{fighter_label} {self._format_effect_identity(identity)} updated: " + ", ".join(changes))
        return lines

    def _effect_map(self, state: dict[str, Any]) -> dict[tuple[str, str, str], dict[str, Any]]:
        effects = {}
        if not isinstance(state, dict):
            return effects
        for list_name in (C.BUFFS, C.DEBUFFS):
            for effect in state.get(list_name, []) or []:
                if not isinstance(effect, dict) or not effect.get(C.NAME):
                    continue
                metadata = effect.get(C.METADATA, {})
                target = metadata.get(C.TARGETED_PART, "") if isinstance(metadata, dict) else ""
                effects[(list_name, str(effect[C.NAME]), str(target or ""))] = effect
        return effects

    def _status_change_lines(self) -> list[str]:
        changes = []
        for fighter in (C.FIGHTER_A, C.FIGHTER_B):
            before, after = self._fighter_states(fighter)
            before_status = self._status_value(before.get(C.STATUS))
            after_status = self._status_value(after.get(C.STATUS))
            if before_status and after_status and before_status != after_status:
                changes.append(f"{self._fighter_display_name_suffix(fighter)} status {before_status} -> {after_status}")
        return changes

    @staticmethod
    def _status_value(value: Any) -> Any:
        return value.value if hasattr(value, "value") else value

    @staticmethod
    def _layer_current_hp(layer: dict[str, Any]) -> Any:
        current_hp = layer.get(C.CURRENT_HP, layer.get(C.MAX_HP))
        return layer.get(C.MAX_HP) if current_hp is None else current_hp

    @staticmethod
    def _format_effect_identity(identity: tuple[str, str, str]) -> str:
        list_name, name, target = identity
        effect_type = "buff" if list_name == C.BUFFS else "debuff"
        target_text = f" on {target}" if target else ""
        return f"{effect_type} {name}{target_text}"

    @staticmethod
    def _effect_details(effect: dict[str, Any]) -> str:
        details = []
        if C.EFFECT_TTL in effect:
            details.append(f"ttl={effect[C.EFFECT_TTL]}")
        if "magnitude" in effect:
            details.append(f"magnitude={effect['magnitude']}")
        return f"({', '.join(details)})" if details else ""

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
            if t.p2_fallback_used:
                lines.append(f"Turn {t.turn}: {C.P2_FALLBACK_MARKER_TEXT}")
            elif t.narration:
                lines.append(f"Turn {t.turn}: {t.narration}")
        return "\n".join(lines)
