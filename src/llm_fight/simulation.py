"""Batch self-play simulation harness."""

import asyncio
import csv
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import random
from typing import Any, Dict, Callable

from .state import FighterState
from .rng import rand
from .judge import judge_phase1, judge_phase2
from . import config as config_mod
from .engine.fighter import get_fighter_attempt
from .engine import constants as C
from .engine.logger import logger
from .engine.combat_log import CombatLog, CombatTurn
from .profile_generation import (
    ProfileGenerationError,
    choose_fighter_creation_nudge,
    generate_fighter_profile,
    profile_generation_metadata,
)
from .utils.token_counter import PromptBudgetError


@dataclass(frozen=True)
class BatchSummary:
    """Summary of rows written by a batch simulation CSV."""

    path: Path
    total_runs: int
    total_rows: int
    completed_rows: int
    error_rows: int

    @property
    def has_errors(self) -> bool:
        return self.error_rows > 0


@dataclass(frozen=True)
class FightEvent:
    """A play-mode progress event emitted by a running fight."""

    name: str
    turn: int | None = None
    fighter_id: str | None = None
    data: Dict[str, Any] = field(default_factory=dict)


FightEventCallback = Callable[[FightEvent], None]


def _emit_event(on_event: FightEventCallback | None, event: FightEvent) -> None:
    if on_event is not None:
        on_event(event)


def _emit_token_metadata(
    on_event: FightEventCallback | None,
    *,
    phase: str,
    metadata: dict[str, Any],
    turn: int | None = None,
    fighter_id: str | None = None,
) -> None:
    if not metadata:
        return
    _emit_event(
        on_event,
        FightEvent(
            C.FIGHT_EVENT_TOKEN_METADATA,
            turn=turn,
            fighter_id=fighter_id,
            data={"phase": phase, "metadata": metadata},
        ),
    )


def validate_batch_settings() -> tuple[int, int]:
    """Return validated ``(runs, concurrency)`` from the current config."""
    runs = config_mod.CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_RUNS, int)
    concurrency = config_mod.CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_CONCURRENT_RUNS, int, fallback=1)

    if runs < 0:
        raise ValueError("[SIMULATION] runs must be 0 or greater")
    if concurrency < 1:
        raise ValueError("[SIMULATION] concurrent_runs must be 1 or greater")
    return runs, concurrency


def summarize_batch_csv(output_csv: str | Path, total_runs: int | None = None) -> BatchSummary:
    """Read a batch CSV and summarize successful and failed rows."""
    csv_path = Path(output_csv)
    with csv_path.open(newline="") as fp:
        rows = list(csv.DictReader(fp))

    total_rows = len(rows)
    error_rows = sum(1 for row in rows if row.get(C.WINNER) == C.BATCH_ERROR_WINNER)
    completed_rows = total_rows - error_rows
    if total_runs is None:
        total_runs = total_rows

    return BatchSummary(
        path=csv_path,
        total_runs=total_runs,
        total_rows=total_rows,
        completed_rows=completed_rows,
        error_rows=error_rows,
    )


def _derive_fight_seed(batch_seed: int, run_index: int) -> int:
    """Derive a stable per-run seed without using process-randomized hashes."""
    digest = hashlib.sha256(f"{int(batch_seed)}:{int(run_index)}".encode("ascii")).digest()
    return int.from_bytes(digest[:8], "big")


def _status_outcome(A: FighterState, B: FighterState) -> str | None:
    a_out = A.status in {C.FighterStatus.DEAD, C.FighterStatus.UNCONSCIOUS}
    b_out = B.status in {C.FighterStatus.DEAD, C.FighterStatus.UNCONSCIOUS}
    if a_out and b_out:
        return C.DRAW
    if a_out:
        return B.id
    if b_out:
        return A.id
    return None


def _judge_outcome(p2: Dict[str, Any]) -> str | None:
    if not p2.get(C.FIGHT_END, False):
        if p2.get(C.WINNER) is not None:
            logger.warning("Judge supplied winner without fight_end=true; ignoring winner.")
        return None

    winner_id = p2.get(C.WINNER)
    if winner_id == C.FIGHTER_A:
        return C.FIGHTER_A
    if winner_id == C.FIGHTER_B:
        return C.FIGHTER_B
    if winner_id is None:
        return C.DRAW
    return "ended_no_clear_winner"


def _attempts_both_invalid_and_failed(p1: Dict[str, Any], rolls: Dict[str, bool]) -> bool:
    return (
        not rolls.get(C.FIGHTER_A, False)
        and not rolls.get(C.FIGHTER_B, False)
        and not p1.get(f"{C.ATTEMPT}_{C.FIGHTER_A}_valid", False)
        and not p1.get(f"{C.ATTEMPT}_{C.FIGHTER_B}_valid", False)
    )


def _authorized_phase2_sources(p1: Dict[str, Any], rolls: Dict[str, bool]) -> set[str]:
    return {
        fighter_id
        for fighter_id in (C.FIGHTER_A, C.FIGHTER_B)
        if rolls.get(fighter_id, False) and p1.get(f"{C.ATTEMPT}_{fighter_id}_valid", False)
    }


def _is_authorized_consequence(entry: Any, authorized_sources: set[str], field_name: str) -> bool:
    if not isinstance(entry, dict):
        logger.warning("Dropping Judge Phase 2 %s consequence without source object.", field_name)
        return False
    source = entry.get(C.SOURCE)
    if source not in authorized_sources:
        logger.warning(
            "Dropping Judge Phase 2 %s consequence from unauthorized source %r.",
            field_name,
            source,
        )
        return False
    return True


def _copy_without_source(entry: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = dict(entry)
    sanitized.pop(C.SOURCE, None)
    return sanitized


def _phase2_validation_warning(
    *,
    code: str,
    fighter_id: str,
    field: str,
    source: Any,
    action: str,
    reason: str | None = None,
    canonical_part: str | None = None,
) -> Dict[str, Any]:
    warning = {
        "code": code,
        "phase": "judge_phase2",
        "fighter_id": fighter_id,
        "field": field,
        "action": action,
    }
    if source in {C.FIGHTER_A, C.FIGHTER_B}:
        warning[C.SOURCE] = source
    if reason:
        warning["reason"] = reason
    if canonical_part:
        warning["canonical_part"] = canonical_part
    return warning


def _sanitize_phase2_narration(sanitized: Dict[str, Any], warnings: list[Dict[str, Any]]) -> None:
    if any(warning.get("code") == C.WARNING_CODE_INVALID_P2_WOUND_TARGET for warning in warnings):
        sanitized[C.NARRATION] = (
            "The judge referenced an invalid body-part target; only validated consequences are recorded."
        )


def _phase2_known_fields(p2: Dict[str, Any]) -> Dict[str, Any]:
    return {
        C.NARRATION: p2.get(C.NARRATION, ""),
        C.DELTA: p2.get(C.DELTA, {}),
        C.FIGHT_END: p2.get(C.FIGHT_END, False),
        C.WINNER: p2.get(C.WINNER),
    }


def _resolve_phase2_wound_target(
    wound: Dict[str, Any],
    target_fighter: FighterState,
    fighter_id: str,
    index: int,
) -> tuple[str | None, Dict[str, Any] | None]:
    field = f"delta.{fighter_id}.{C.WOUNDS}[{index}].{C.TARGETED_PART}"
    source = wound.get(C.SOURCE)
    canonical_part = target_fighter.normalize_part_name(wound.get(C.TARGETED_PART))
    if canonical_part is None:
        logger.warning(
            "Dropping Judge Phase 2 wound with invalid target for fighter %s.",
            fighter_id,
        )
        return None, _phase2_validation_warning(
            code=C.WARNING_CODE_INVALID_P2_WOUND_TARGET,
            fighter_id=fighter_id,
            field=field,
            source=source,
            action="dropped",
            reason="unknown_target_part",
        )
    return canonical_part, None


def _invalid_phase2_wound_target_warnings(
    raw_delta: Any,
    fighters: dict[str, FighterState],
) -> list[Dict[str, Any]]:
    if not isinstance(raw_delta, dict):
        return []

    warnings: list[Dict[str, Any]] = []
    for fighter_id in (C.FIGHTER_A, C.FIGHTER_B):
        delta = raw_delta.get(fighter_id, {})
        if not isinstance(delta, dict):
            continue
        for index, wound in enumerate(delta.get(C.WOUNDS, [])):
            if not isinstance(wound, dict):
                continue
            _, warning = _resolve_phase2_wound_target(wound, fighters[fighter_id], fighter_id, index)
            if warning is not None:
                warnings.append(warning)
    return warnings


def _warning_key(warning: Dict[str, Any]) -> tuple[Any, Any]:
    return warning.get("code"), warning.get("field")


def _merge_phase2_warnings(*warning_groups: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    merged: list[Dict[str, Any]] = []
    seen = set()
    for warnings in warning_groups:
        for warning in warnings:
            key = _warning_key(warning)
            if key in seen:
                continue
            seen.add(key)
            merged.append(warning)
    return merged


def _authorized_scalar_value(entry: Any, authorized_sources: set[str], field_name: str) -> Any:
    if not _is_authorized_consequence(entry, authorized_sources, field_name):
        return None
    return entry.get(C.VALUE)


def _authorize_fighter_delta(
    delta: Any,
    authorized_sources: set[str],
    target_fighter: FighterState,
    fighter_id: str,
) -> tuple[Dict[str, Any], list[Dict[str, Any]]]:
    if not isinstance(delta, dict):
        return {}, []

    authorized_delta: Dict[str, Any] = {}
    warnings: list[Dict[str, Any]] = []
    for field_name in (C.PAIN_INCREASE, C.EXHAUSTION_INCREASE, C.HEAT_INCREASE, C.STATUS_CHANGE):
        if field_name not in delta:
            continue
        value = _authorized_scalar_value(delta[field_name], authorized_sources, field_name)
        if value is not None:
            authorized_delta[field_name] = value

    wounds = []
    for index, wound in enumerate(delta.get(C.WOUNDS, [])):
        if _is_authorized_consequence(wound, authorized_sources, C.WOUNDS):
            source = wound.get(C.SOURCE)
            canonical_part, warning = _resolve_phase2_wound_target(wound, target_fighter, fighter_id, index)
            if warning is not None:
                warnings.append(warning)
                continue

            sanitized_wound = _copy_without_source(wound)
            if sanitized_wound.get(C.TARGETED_PART) != canonical_part:
                warnings.append(
                    _phase2_validation_warning(
                        code=C.WARNING_CODE_CANONICALIZED_P2_WOUND_TARGET,
                        fighter_id=fighter_id,
                        field=f"delta.{fighter_id}.{C.WOUNDS}[{index}].{C.TARGETED_PART}",
                        source=source,
                        action="canonicalized",
                        canonical_part=canonical_part,
                    )
                )
            sanitized_wound[C.TARGETED_PART] = canonical_part
            wounds.append(sanitized_wound)
    if wounds:
        authorized_delta[C.WOUNDS] = wounds

    effects_added = []
    for effect in delta.get(C.EFFECTS_ADDED, []):
        if _is_authorized_consequence(effect, authorized_sources, C.EFFECTS_ADDED):
            effects_added.append(_copy_without_source(effect))
    if effects_added:
        authorized_delta[C.EFFECTS_ADDED] = effects_added

    effects_removed = []
    for effect_removal in delta.get(C.EFFECTS_REMOVED, []):
        if _is_authorized_consequence(effect_removal, authorized_sources, C.EFFECTS_REMOVED):
            name = effect_removal.get(C.NAME)
            if name:
                effects_removed.append(name)
    if effects_removed:
        authorized_delta[C.EFFECTS_REMOVED] = effects_removed

    return authorized_delta, warnings


def _authorize_phase2_result(
    p2: Dict[str, Any],
    p1: Dict[str, Any],
    rolls: Dict[str, bool],
    fighters: dict[str, FighterState],
) -> Dict[str, Any]:
    authorized_sources = _authorized_phase2_sources(p1, rolls)
    sanitized = _phase2_known_fields(p2)
    raw_delta = p2.get(C.DELTA, {})
    invalid_target_warnings = _invalid_phase2_wound_target_warnings(raw_delta, fighters)

    if not authorized_sources:
        if p2.get(C.DELTA) or p2.get(C.FIGHT_END) or p2.get(C.WINNER) is not None:
            logger.warning("Ignoring Judge Phase 2 damage/end result because no valid attempt succeeded.")
            if _attempts_both_invalid_and_failed(p1, rolls):
                logger.warning("both attempts were invalid and failed.")
        if invalid_target_warnings:
            sanitized[C.VALIDATION_WARNINGS] = invalid_target_warnings
            _sanitize_phase2_narration(sanitized, invalid_target_warnings)
        sanitized[C.DELTA] = {}
        sanitized[C.FIGHT_END] = False
        sanitized[C.WINNER] = None
        return sanitized

    if not isinstance(raw_delta, dict):
        sanitized[C.DELTA] = {}
        return sanitized

    sanitized_delta: Dict[str, Any] = {}
    warnings: list[Dict[str, Any]] = []
    for fighter_id in (C.FIGHTER_A, C.FIGHTER_B):
        authorized_delta, delta_warnings = _authorize_fighter_delta(
            raw_delta.get(fighter_id, {}),
            authorized_sources,
            fighters[fighter_id],
            fighter_id,
        )
        warnings.extend(delta_warnings)
        if authorized_delta:
            sanitized_delta[fighter_id] = authorized_delta

    sanitized[C.DELTA] = sanitized_delta
    warnings = _merge_phase2_warnings(warnings, invalid_target_warnings)
    if warnings:
        sanitized[C.VALIDATION_WARNINGS] = warnings
        _sanitize_phase2_narration(sanitized, warnings)
    if not sanitized_delta and any(
        warning.get("code") == C.WARNING_CODE_INVALID_P2_WOUND_TARGET for warning in warnings
    ):
        sanitized[C.FIGHT_END] = False
        sanitized[C.WINNER] = None
    return sanitized


def _active_effects(fighter: FighterState):
    buffs = getattr(fighter, C.BUFFS, [])
    debuffs = getattr(fighter, C.DEBUFFS, [])
    if not isinstance(buffs, list):
        buffs = []
    if not isinstance(debuffs, list):
        debuffs = []
    return buffs + debuffs


def _active_roll_modifier_mechanics(fighter: FighterState):
    mechanics = []
    for effect in _active_effects(fighter):
        if effect.fresh_turns > 0:
            continue
        for mechanic in effect.mechanics:
            if mechanic.get(C.EFFECT_MECHANIC_KIND) in {
                C.EFFECT_MECHANIC_TARGETING_MODIFIER,
                C.EFFECT_MECHANIC_ACTION_MODIFIER,
            }:
                mechanics.append((effect, mechanic))
    return mechanics


def _apply_effect_roll_modifiers(p1: Dict[str, Any], fighters: dict[str, FighterState]) -> Dict[str, Any]:
    """Apply deterministic active-effect modifiers to P1 validity/probabilities."""
    modified = dict(p1)
    notes: list[str] = []

    for fighter_id, fighter in fighters.items():
        valid_key = f"{C.ATTEMPT}_{fighter_id}_valid"
        prob_key = f"{C.ATTEMPT}_{fighter_id}_prob"
        if not modified.get(valid_key, False):
            continue
        active_modifiers = _active_roll_modifier_mechanics(fighter)
        if not active_modifiers:
            continue

        try:
            prob = float(modified.get(prob_key, "0.0") or "0.0")
        except ValueError:
            continue

        for effect, mechanic in active_modifiers:
            kind = mechanic.get(C.EFFECT_MECHANIC_KIND)
            modifier = mechanic.get(C.EFFECT_MECHANIC_MODIFIER)
            if kind == C.EFFECT_MECHANIC_TARGETING_MODIFIER:
                penalty = int(mechanic.get(C.VALUE, 0)) / 100
                prob = max(0.0, prob - penalty)
                notes.append(f"{fighter_id}:{effect.name}:{modifier} -{penalty:.2f}")
            elif kind == C.EFFECT_MECHANIC_ACTION_MODIFIER:
                modified[valid_key] = False
                prob = 0.0
                notes.append(f"{fighter_id}:{effect.name}:{modifier} blocked")

        modified[prob_key] = f"{prob:.3f}".rstrip("0").rstrip(".") if prob not in (0.0, 1.0) else f"{prob:.1f}"

    if notes:
        modified[C.EFFECT_MODIFIERS_APPLIED] = notes
    return modified


async def _build_match_fighter(
    fighter_id: str,
    section: str,
    opponent_section: str,
    fight_rng: random.Random | None,
    on_event: FightEventCallback | None = None,
) -> FighterState:
    """Create one fighter from config or the opt-in generated-profile flow."""
    mode = config_mod.CONFIG.get_fighter_creation_mode()
    if mode == C.FIGHTER_CREATION_MODE_CONFIGURED:
        return FighterState.from_config(fighter_id, config_section=section)

    nudge = choose_fighter_creation_nudge(fight_rng)
    _emit_event(
        on_event,
        FightEvent(
            C.FIGHT_EVENT_PROFILE_GENERATION_START,
            fighter_id=fighter_id,
            data={"section": section, "nudge": nudge},
        ),
    )
    try:
        generation_kwargs: dict[str, Any] = {"config": config_mod.CONFIG}
        if on_event is not None:
            generation_kwargs["on_metadata"] = lambda metadata: _emit_token_metadata(
                on_event,
                phase="profile_generation",
                metadata=metadata,
                fighter_id=fighter_id,
            )
        profile = await generate_fighter_profile(
            fighter_id,
            section,
            opponent_section,
            nudge,
            **generation_kwargs,
        )
        metadata = profile_generation_metadata(nudge, mode=C.FIGHTER_CREATION_MODE_GENERATED)
        fighter = FighterState.from_profile(
            fighter_id,
            profile,
            config_section=section,
            config=config_mod.CONFIG,
            allow_config_overrides=False,
            profile_generation=metadata,
        )
        _emit_event(
            on_event,
            FightEvent(
                C.FIGHT_EVENT_PROFILE_GENERATION_END,
                fighter_id=fighter_id,
                data={"section": section, "nudge": nudge, "metadata": metadata},
            ),
        )
        return fighter
    except ProfileGenerationError as exc:
        metadata = profile_generation_metadata(
            nudge,
            mode="fallback",
            error=exc.code,
        )
        logger.warning(
            "Fighter %s profile generation failed with %s; falling back to configured profile.",
            fighter_id,
            exc.code,
        )
        fighter = FighterState.from_config(fighter_id, config_section=section)
        fighter.profile_generation = metadata
        _emit_event(
            on_event,
            FightEvent(
                C.FIGHT_EVENT_PROFILE_GENERATION_END,
                fighter_id=fighter_id,
                data={"section": section, "nudge": nudge, "metadata": metadata},
            ),
        )
        return fighter


async def _build_match_fighters(
    fighter_a_section: str,
    fighter_b_section: str,
    combat_log: CombatLog,
    fight_rng: random.Random | None,
    on_event: FightEventCallback | None = None,
) -> tuple[FighterState, FighterState]:
    """Create both match fighters before turn 1."""
    A = await _build_match_fighter(C.FIGHTER_A, fighter_a_section, fighter_b_section, fight_rng, on_event=on_event)
    B = await _build_match_fighter(C.FIGHTER_B, fighter_b_section, fighter_a_section, fight_rng, on_event=on_event)
    if A.profile_generation or B.profile_generation:
        combat_log.profile_generation = {
            C.FIGHTER_A: A.profile_generation,
            C.FIGHTER_B: B.profile_generation,
        }
    _emit_event(
        on_event,
        FightEvent(
            C.FIGHT_EVENT_FIGHTERS_READY,
            data={
                "fighters": {
                    C.FIGHTER_A: A.to_json(),
                    C.FIGHTER_B: B.to_json(),
                },
                C.PROFILE_GENERATION: combat_log.profile_generation,
            },
        ),
    )
    return A, B


async def _single_fight(
    fighter_a_section: str | None = None,
    fighter_b_section: str | None = None,
    return_log: bool = False,
    fight_rng: random.Random | None = None,
    on_event: FightEventCallback | None = None,
) -> Dict[str, str] | tuple[Dict[str, str], CombatLog]:
    """
    Simulates a single fight between two AI fighters (A and B).

    The fight proceeds in turns, with fighters proposing actions, a judge (Phase 1)
    determining action validity and success probabilities, dice rolls determining outcomes,
    and another judge (Phase 2) narrating events and calculating state deltas.
    The fight ends when a fighter is dead/unconscious, the judge declares an end,
    or a maximum turn limit is reached.

    Returns
    -------
    dict or tuple
        When ``return_log`` is ``False`` (default) returns a dict containing
        the winner and turn count. If ``True``, returns a tuple of that dict and
        the :class:`CombatLog` for the fight.
    """
    if fighter_a_section is None:
        fighter_a_section = config_mod.CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_FIGHTER_A_SECTION, str, fallback="A")
    if fighter_b_section is None:
        fighter_b_section = config_mod.CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_FIGHTER_B_SECTION, str, fallback="B")

    turn = 0
    outcome = None
    combat_log = CombatLog()
    A, B = await _build_match_fighters(fighter_a_section, fighter_b_section, combat_log, fight_rng, on_event=on_event)
    fighter_log_window = config_mod.CONFIG.get(C.CONFIG_CONTEXT, C.CONFIG_FIGHTER_LOG_WINDOW, int, fallback=5)
    judge_log_window = config_mod.CONFIG.get(C.CONFIG_CONTEXT, C.CONFIG_JUDGE_LOG_WINDOW, int, fallback=9999)

    while not outcome:
        turn += 1

        # Fighters propose actions concurrently, each receiving the combat log
        async def _fighter_attempt(fighter: FighterState, opponent: FighterState) -> str:
            _emit_event(
                on_event,
                FightEvent(C.FIGHT_EVENT_FIGHTER_ACTION_START, turn=turn, fighter_id=fighter.id),
            )
            try:
                attempt_kwargs: dict[str, Any] = {
                    "combat_log": combat_log,
                    "turn_window": fighter_log_window,
                }
                if on_event is not None:
                    attempt_kwargs["on_metadata"] = lambda metadata: _emit_token_metadata(
                        on_event,
                        phase="fighter_action",
                        metadata=metadata,
                        turn=turn,
                        fighter_id=fighter.id,
                    )
                return await get_fighter_attempt(fighter, opponent, **attempt_kwargs)
            finally:
                _emit_event(
                    on_event,
                    FightEvent(C.FIGHT_EVENT_FIGHTER_ACTION_END, turn=turn, fighter_id=fighter.id),
                )

        attemptA, attemptB = await asyncio.gather(
            _fighter_attempt(A, B),
            _fighter_attempt(B, A),
        )
        # Provide recent combat log context to judge_phase1
        p1_recent_log = combat_log.to_summary(last_n=fighter_log_window)
        _emit_event(on_event, FightEvent(C.FIGHT_EVENT_JUDGE_PHASE1_START, turn=turn))
        p1_kwargs: dict[str, Any] = {"recent_log": p1_recent_log}
        if on_event is not None:
            p1_kwargs["on_metadata"] = lambda metadata: _emit_token_metadata(
                on_event,
                phase="judge_phase1",
                metadata=metadata,
                turn=turn,
            )
        p1 = await judge_phase1({"A": A.to_json(), "B": B.to_json()}, attemptA, attemptB, **p1_kwargs)
        p1 = _apply_effect_roll_modifiers(p1, {C.FIGHTER_A: A, C.FIGHTER_B: B})
        _emit_event(on_event, FightEvent(C.FIGHT_EVENT_JUDGE_PHASE1_END, turn=turn, data={"p1": p1}))

        # Determine success of attempts based on probabilities from Judge P1
        _emit_event(on_event, FightEvent(C.FIGHT_EVENT_ROLLS_START, turn=turn))
        rolls = {"A": False, "B": False}
        try:
            prob_a_str = p1.get(f"{C.ATTEMPT}_{C.FIGHTER_A}_prob", "0.0")
            prob_a = float(prob_a_str) if prob_a_str else 0.0
            if p1.get(f"{C.ATTEMPT}_{C.FIGHTER_A}_valid", False):
                rolls["A"] = (fight_rng.random() if fight_rng is not None else rand()) < prob_a
        except ValueError:
            logger.warning(
                f"Could not parse probability string for Fighter A: '{prob_a_str}'. Defaulting to 0.0 probability."
            )
            # rolls['A'] remains False

        try:
            prob_b_str = p1.get(f"{C.ATTEMPT}_{C.FIGHTER_B}_prob", "0.0")
            prob_b = float(prob_b_str) if prob_b_str else 0.0
            if p1.get(f"{C.ATTEMPT}_{C.FIGHTER_B}_valid", False):
                rolls["B"] = (fight_rng.random() if fight_rng is not None else rand()) < prob_b
        except ValueError:
            logger.warning(
                f"Could not parse probability string for Fighter B: '{prob_b_str}'. Defaulting to 0.0 probability."
            )
            # rolls['B'] remains False
        _emit_event(on_event, FightEvent(C.FIGHT_EVENT_ROLLS_END, turn=turn, data={"rolls": dict(rolls)}))

        # Pass the judgement text to P2 for narration context, full states, and combat log
        judge_recent_log = combat_log.to_summary(last_n=judge_log_window)

        p2_input_state = {
            "fighter_A": A.to_json(),
            "fighter_B": B.to_json(),
            C.LOG_ATTEMPT_A: attemptA,
            C.LOG_ATTEMPT_B: attemptB,
            "p1_result": p1,
            "p1_judgement": p1.get("judgement_text", ""),
            "p1_explanation": p1.get("explanation", ""),
            "valid_target_parts": {
                C.FIGHTER_A: sorted(A.parts.keys()),
                C.FIGHTER_B: sorted(B.parts.keys()),
            },
            "combat_log_turns": len(combat_log),
            "recent_combat_log": judge_recent_log,
        }
        _emit_event(on_event, FightEvent(C.FIGHT_EVENT_JUDGE_PHASE2_START, turn=turn))
        p2_kwargs: dict[str, Any] = {}
        if on_event is not None:
            p2_kwargs["on_metadata"] = lambda metadata: _emit_token_metadata(
                on_event,
                phase="judge_phase2",
                metadata=metadata,
                turn=turn,
            )
        p2 = await judge_phase2(p2_input_state, rolls, **p2_kwargs)
        p2 = _authorize_phase2_result(p2, p1, rolls, {C.FIGHTER_A: A, C.FIGHTER_B: B})
        _emit_event(on_event, FightEvent(C.FIGHT_EVENT_JUDGE_PHASE2_END, turn=turn, data={"p2": p2}))

        turn_entry = CombatTurn(
            turn=turn,
            attempt_A=attemptA,
            attempt_B=attemptB,
            judge_p1=p1,
            judge_p2=p2,
            state_A_before=p2_input_state["fighter_A"],
            state_B_before=p2_input_state["fighter_B"],
        )

        # Apply deltas to fighter states
        _emit_event(on_event, FightEvent(C.FIGHT_EVENT_DELTAS_START, turn=turn))
        if "delta" in p2 and isinstance(p2["delta"], dict):
            A.apply_delta(p2["delta"].get("A", {}))
            B.apply_delta(p2["delta"].get("B", {}))
        _emit_event(on_event, FightEvent(C.FIGHT_EVENT_DELTAS_END, turn=turn))

        # Tick effects for both fighters AFTER deltas are applied for the turn
        _emit_event(on_event, FightEvent(C.FIGHT_EVENT_EFFECTS_START, turn=turn))
        A.apply_effects(rng=fight_rng)
        B.apply_effects(rng=fight_rng)
        _emit_event(on_event, FightEvent(C.FIGHT_EVENT_EFFECTS_END, turn=turn))

        turn_entry.state_A_after = A.to_json()
        turn_entry.state_B_after = B.to_json()

        combat_log.append(turn_entry)
        _emit_event(on_event, FightEvent(C.FIGHT_EVENT_TURN_COMPLETE, turn=turn, data={"turn": turn_entry}))
        if config_mod.CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_LOG_COMBAT_TURNS, bool, fallback=False):
            logger.info(turn_entry.to_simple_text())

        # Check for fight end conditions
        status_outcome = _status_outcome(A, B)
        judge_outcome = _judge_outcome(p2)
        if status_outcome:
            if judge_outcome and judge_outcome != status_outcome:
                logger.warning(
                    "Judge outcome %s contradicted post-delta state outcome %s; using state outcome.",
                    judge_outcome,
                    status_outcome,
                )
            outcome = status_outcome
        elif judge_outcome:
            logger.warning(
                "Ignoring judge-only outcome %s because post-delta state outcome is not terminal.",
                judge_outcome,
            )
        if not outcome and turn >= config_mod.CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, int, fallback=100):
            outcome = C.DRAW
        # else: outcome remains None, loop continues

    logger.info(f"Fight ended. Outcome: {outcome}, Turns: {turn}")
    logger.info(f"Fighter A ({A.id}) status: {A.status}, Fighter B ({B.id}) status: {B.status}")
    result = {C.WINNER: outcome, C.LOG_TURN: str(turn)}
    _emit_event(on_event, FightEvent(C.FIGHT_EVENT_FIGHT_COMPLETE, turn=turn, data={"result": result}))
    if return_log:
        return result, combat_log
    return result


async def run_batch(
    output_csv: str | Path = "sim_results.csv",
    fighter_a_section: str | None = None,
    fighter_b_section: str | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> Path:
    """Run a batch of simulations and write the results to ``output_csv``.

    The number of runs and allowed concurrency are read from the current
    configuration each time this function is called.  The resulting CSV contains
    one row per fight with columns matching the return value of
    :func:`_single_fight`.

    Parameters
    ----------
    output_csv:
        File path for the CSV output. Defaults to ``"sim_results.csv"`` in the
        current working directory.
    fighter_a_section:
        INI section providing fighter A's settings. Defaults to the value of
        ``fighter_A`` in the ``[General]`` section.
    fighter_b_section:
        INI section providing fighter B's settings. Defaults to the value of
        ``fighter_B`` in the ``[General]`` section.
    progress:
        Optional callback receiving ``(completed, total)`` as the batch runs.

    Returns
    -------
    Path
        Path object for the created CSV file.
    """
    runs, concurrency = validate_batch_settings()
    batch_seed = config_mod.CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_SEED, int)

    sem = asyncio.Semaphore(concurrency)

    async def sem_fight(run_index: int):
        async with sem:
            try:
                result = await _single_fight(
                    fighter_a_section=fighter_a_section,
                    fighter_b_section=fighter_b_section,
                    fight_rng=random.Random(_derive_fight_seed(batch_seed, run_index)),
                )
                return run_index, result
            except PromptBudgetError:
                raise
            except Exception:
                logger.exception("_single_fight failed")
                return run_index, {C.WINNER: C.BATCH_ERROR_WINNER, C.LOG_TURN: "0"}

    csv_path = Path(output_csv)
    with csv_path.open("w", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=[C.WINNER, C.LOG_TURN])
        writer.writeheader()
        fp.flush()

        tasks = [asyncio.create_task(sem_fight(run_index)) for run_index in range(runs)]
        buffered_results: dict[int, dict[str, str]] = {}
        next_to_write = 0
        try:
            for idx, coro in enumerate(asyncio.as_completed(tasks), start=1):
                run_index, result = await coro
                buffered_results[run_index] = result
                while next_to_write in buffered_results:
                    writer.writerow(buffered_results.pop(next_to_write))
                    fp.flush()
                    next_to_write += 1
                if progress:
                    progress(idx, runs)
        except PromptBudgetError:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

    return csv_path
