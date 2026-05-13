"""Shared display and mechanical-diff helpers for combat turns."""

from __future__ import annotations

from typing import Any

from . import constants as C


def roll_lines(turn: Any) -> list[str]:
    """Return display lines for per-fighter roll outcomes."""
    lines = []
    for fighter in (C.FIGHTER_A, C.FIGHTER_B):
        metadata = turn.rolls.get(fighter, {})
        if not metadata:
            continue
        label = _fighter_label(turn, fighter)
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


def rolls_text(turn: Any, separator: str = "\n") -> str:
    return separator.join(roll_lines(turn))


def judge_ruling_lines(turn: Any) -> list[str]:
    """Return Judge Phase 1 output as clear, display-ready lines."""
    lines = []
    judgement = turn.judge_p1.get("judgement_text")
    if judgement:
        lines.append(str(judgement))

    for fighter in (C.FIGHTER_A, C.FIGHTER_B):
        detail = _judge_attempt_ruling(turn, fighter)
        if detail:
            lines.append(f"{_fighter_label(turn, fighter)}: {detail}")

    explanation = turn.judge_p1.get("explanation")
    if explanation:
        lines.append(f"Reasoning: {explanation}")

    return lines


def judge_ruling_text(turn: Any, separator: str = "\n") -> str:
    return separator.join(judge_ruling_lines(turn))


def status_changes_text(turn: Any) -> str:
    return " ".join(_status_change_lines(turn))


def mechanical_change_lines(turn: Any) -> list[str]:
    """Return concise before/after mechanical changes for the full turn."""
    lines = []
    for fighter in (C.FIGHTER_A, C.FIGHTER_B):
        before, after = _fighter_states(turn, fighter)
        lines.extend(_stat_change_lines(turn, fighter, before, after))
        lines.extend(_wound_lines(turn, fighter))
        lines.extend(_body_part_change_lines(turn, fighter, before, after))
        lines.extend(_effect_change_lines(turn, fighter, before, after))
    lines.extend(_status_change_lines(turn))
    if not lines and _has_state_snapshots(turn):
        return ["No mechanical state changes."]
    return lines


def mechanical_changes_text(turn: Any, separator: str = "\n") -> str:
    return separator.join(mechanical_change_lines(turn))


def turn_to_text(turn: Any) -> str:
    """Return a concise, human-readable summary of the turn."""
    parts = [f"Turn {turn.turn}"]
    if turn.attempt_A:
        parts.append(f"{_fighter_label(turn, C.FIGHTER_A)} attempt: {turn.attempt_A}")
    if turn.attempt_B:
        parts.append(f"{_fighter_label(turn, C.FIGHTER_B)} attempt: {turn.attempt_B}")
    judge = judge_ruling_text(turn, separator="; ")
    if judge:
        parts.append(f"Judge ruling: {judge}")
    rolls = rolls_text(turn, separator="; ")
    if rolls:
        parts.append(f"Rolls: {rolls}")
    narr = turn.narration
    if narr:
        parts.append(f"Outcome: {narr}")
    fallback = turn.p2_fallback_text()
    if fallback:
        parts.append(fallback)
    changes = mechanical_changes_text(turn, separator="; ")
    if changes:
        parts.append(f"Mechanical changes: {changes}")
    return " | ".join(parts)


def turn_to_simple_text(turn: Any) -> str:
    """Return a multi-line plain text representation of the turn."""
    lines = [f"Turn {turn.turn}:"]
    if turn.attempt_A:
        lines.append(f"{_fighter_label(turn, C.FIGHTER_A)} attempt: {turn.attempt_A}")
    if turn.attempt_B:
        lines.append(f"{_fighter_label(turn, C.FIGHTER_B)} attempt: {turn.attempt_B}")
    judge_lines = judge_ruling_lines(turn)
    if judge_lines:
        lines.append("Judge ruling:")
        lines.extend(f"  {line}" for line in judge_lines)
    roll_lines_ = roll_lines(turn)
    if roll_lines_:
        lines.append("Rolls:")
        lines.extend(f"  {line}" for line in roll_lines_)
    narr = turn.narration
    if narr:
        lines.append(f"Outcome: {narr}")
    fallback = turn.p2_fallback_text()
    if fallback:
        lines.append(fallback)

    change_lines = mechanical_change_lines(turn)
    if change_lines:
        lines.append("Mechanical changes:")
        lines.extend(f"  {line}" for line in change_lines)

    return "\n".join(lines)


def _judge_attempt_ruling(turn: Any, fighter: str) -> str:
    key_prefix = f"{C.ATTEMPT}_{fighter}"
    valid = turn.judge_p1.get(f"{key_prefix}_valid")
    prob = turn.judge_p1.get(f"{key_prefix}_prob")

    parts = []
    if isinstance(valid, bool):
        parts.append("valid" if valid else "invalid")
    elif valid is not None:
        parts.append(f"validity={valid}")
    if prob not in (None, ""):
        parts.append(f"success p={prob}")

    return ", ".join(parts)


def _fighter_states(turn: Any, fighter: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if fighter == C.FIGHTER_A:
        return turn.state_A_before, turn.state_A_after
    return turn.state_B_before, turn.state_B_after


def _fighter_display_name(turn: Any, fighter: str) -> str:
    before, after = _fighter_states(turn, fighter)
    for state in (after, before):
        if isinstance(state, dict):
            display_name = " ".join(str(state.get(C.DISPLAY_NAME, "")).strip().split())
            if display_name:
                return display_name
    return fighter


def _fighter_label(turn: Any, fighter: str) -> str:
    display_name = _fighter_display_name(turn, fighter)
    if display_name and display_name != fighter:
        return f"Fighter {fighter} ({display_name})"
    return f"Fighter {fighter}"


def _has_state_snapshots(turn: Any) -> bool:
    return any((turn.state_A_before, turn.state_A_after, turn.state_B_before, turn.state_B_after))


def _stat_change_lines(turn: Any, fighter: str, before: dict[str, Any], after: dict[str, Any]) -> list[str]:
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
                f"{_fighter_display_name_suffix(turn, fighter)} {stat} "
                f"{sign}{delta:g} ({before_value:g} -> {after_value:g})"
            )
    return lines


def _fighter_display_name_suffix(turn: Any, fighter: str) -> str:
    display_name = _fighter_display_name(turn, fighter)
    if display_name and display_name != fighter:
        return f"{fighter} ({display_name})"
    return fighter


def _wound_lines(turn: Any, fighter: str) -> list[str]:
    delta = turn.judge_p2.get(C.DELTA, {})
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
        lines.append(f"{_fighter_display_name_suffix(turn, fighter)} wound: {part} {damage_type} {value}{source_text}")
    return lines


def _body_part_change_lines(
    turn: Any,
    fighter: str,
    before: dict[str, Any],
    after: dict[str, Any],
) -> list[str]:
    before_parts = before.get("parts", {}) if isinstance(before, dict) else {}
    after_parts = after.get("parts", {}) if isinstance(after, dict) else {}
    if not isinstance(before_parts, dict) or not isinstance(after_parts, dict):
        return []

    lines = []
    for part_name in sorted(set(before_parts) | set(after_parts)):
        before_part = before_parts.get(part_name)
        after_part = after_parts.get(part_name)
        if before_part is None:
            lines.append(f"{_fighter_display_name_suffix(turn, fighter)} {part_name}: part added")
            continue
        if after_part is None:
            lines.append(f"{_fighter_display_name_suffix(turn, fighter)} {part_name}: part removed")
            continue

        changes = []
        before_status = _status_value(before_part.get(C.STATUS))
        after_status = _status_value(after_part.get(C.STATUS))
        if before_status != after_status:
            changes.append(f"status {before_status} -> {after_status}")
        before_severed = bool(before_part.get("severed", False))
        after_severed = bool(after_part.get("severed", False))
        if before_severed != after_severed:
            changes.append(f"severed {before_severed} -> {after_severed}")
        changes.extend(_layer_hp_change_lines(before_part, after_part))
        if changes:
            lines.append(f"{_fighter_display_name_suffix(turn, fighter)} {part_name}: " + "; ".join(changes))
    return lines


def _layer_hp_change_lines(before_part: dict[str, Any], after_part: dict[str, Any]) -> list[str]:
    before_layers = before_part.get("layers", []) if isinstance(before_part, dict) else []
    after_layers = after_part.get("layers", []) if isinstance(after_part, dict) else []
    if not isinstance(before_layers, list) or not isinstance(after_layers, list):
        return []

    changes = []
    for index, (before_layer, after_layer) in enumerate(zip(before_layers, after_layers, strict=False), start=1):
        before_hp = _layer_current_hp(before_layer)
        after_hp = _layer_current_hp(after_layer)
        if before_hp != after_hp:
            layer_name = after_layer.get(C.NAME) or before_layer.get(C.NAME) or f"layer {index}"
            changes.append(f"{layer_name} hp {before_hp} -> {after_hp}")
    return changes


def _effect_change_lines(turn: Any, fighter: str, before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    before_effects = _effect_map(before)
    after_effects = _effect_map(after)
    lines = []
    fighter_label = _fighter_display_name_suffix(turn, fighter)
    for identity in sorted(set(after_effects) - set(before_effects)):
        details = _effect_details(after_effects[identity])
        lines.append(f"{fighter_label} {_format_effect_identity(identity)} added {details}".rstrip())
    for identity in sorted(set(before_effects) - set(after_effects)):
        lines.append(f"{fighter_label} {_format_effect_identity(identity)} removed/expired")
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
            lines.append(f"{fighter_label} {_format_effect_identity(identity)} updated: " + ", ".join(changes))
    return lines


def _effect_map(state: dict[str, Any]) -> dict[tuple[str, str, str], dict[str, Any]]:
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


def _status_change_lines(turn: Any) -> list[str]:
    changes = []
    for fighter in (C.FIGHTER_A, C.FIGHTER_B):
        before, after = _fighter_states(turn, fighter)
        before_status = _status_value(before.get(C.STATUS))
        after_status = _status_value(after.get(C.STATUS))
        if before_status and after_status and before_status != after_status:
            changes.append(f"{_fighter_display_name_suffix(turn, fighter)} status {before_status} -> {after_status}")
    return changes


def _status_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def _layer_current_hp(layer: dict[str, Any]) -> Any:
    current_hp = layer.get(C.CURRENT_HP, layer.get(C.MAX_HP))
    return layer.get(C.MAX_HP) if current_hp is None else current_hp


def _format_effect_identity(identity: tuple[str, str, str]) -> str:
    list_name, name, target = identity
    effect_type = "buff" if list_name == C.BUFFS else "debuff"
    target_text = f" on {target}" if target else ""
    return f"{effect_type} {name}{target_text}"


def _effect_details(effect: dict[str, Any]) -> str:
    details = []
    if C.EFFECT_TTL in effect:
        details.append(f"ttl={effect[C.EFFECT_TTL]}")
    if "magnitude" in effect:
        details.append(f"magnitude={effect['magnitude']}")
    return f"({', '.join(details)})" if details else ""
