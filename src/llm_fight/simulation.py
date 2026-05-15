"""Batch self-play simulation harness."""

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from . import batch as batch_mod
from . import config as config_mod
from .engine import constants as C
from .engine.combat_log import CombatLog
from .engine.fighter import get_fighter_attempt
from .engine.logger import logger
from .fight_loop import FightEventServices, FightModelServices, FightRuleServices, SingleFightHooks, run_single_fight
from .judge import judge_phase1, judge_phase2
from .phase2_authorization import authorize_phase2_result as _authorize_phase2_result
from .profile_generation import (
    ProfileGenerationError,
    choose_fighter_creation_nudge,
    generate_fighter_profile,
    profile_generation_metadata,
)
from .rng import rand
from .state import FighterState

BatchSummary = batch_mod.BatchSummary
_derive_fight_seed = batch_mod._derive_fight_seed
summarize_batch_csv = batch_mod.summarize_batch_csv
validate_batch_settings = batch_mod.validate_batch_settings


@dataclass(frozen=True)
class FightEvent:
    """A play-mode progress event emitted by a running fight."""

    name: str
    turn: int | None = None
    fighter_id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


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


def _emit_llm_output_retry(
    on_event: FightEventCallback | None,
    *,
    phase: str,
    retry: dict[str, Any],
    turn: int | None = None,
    fighter_id: str | None = None,
) -> None:
    data = {
        "phase": phase,
        "attempt": retry.get("attempt"),
        "next_attempt": retry.get("next_attempt"),
        "max_attempts": retry.get("max_attempts"),
        "reason": retry.get("reason", "invalid_output"),
        "error_type": retry.get("error_type", "InvalidOutput"),
    }
    _emit_event(
        on_event,
        FightEvent(
            C.FIGHT_EVENT_LLM_OUTPUT_RETRY,
            turn=turn,
            fighter_id=fighter_id,
            data=data,
        ),
    )


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


def _winner_display_name(winner: str | None, fighters: dict[str, FighterState]) -> str:
    fighter = fighters.get(str(winner))
    if fighter is None:
        return ""
    return fighter.display_name


def _judge_outcome(p2: dict[str, Any]) -> str | None:
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


def _resolve_attempt_roll(
    p1: dict[str, Any],
    fighter_id: str,
    fight_rng: random.Random | None = None,
) -> dict[str, Any]:
    """Resolve one attempt roll and return display metadata."""
    valid = p1.get(f"{C.ATTEMPT}_{fighter_id}_valid", False) is True
    raw_probability = p1.get(f"{C.ATTEMPT}_{fighter_id}_prob", "0.0")
    probability_text = str(raw_probability) if raw_probability is not None else ""
    metadata: dict[str, Any] = {
        "valid": valid,
        "probability": None,
        "probability_text": probability_text,
        "roll": None,
        "success": False,
        "reason": "invalid_attempt",
    }

    if not valid:
        return metadata

    try:
        probability = float(probability_text) if probability_text else 0.0
    except ValueError:
        logger.warning(
            f"Could not parse probability string for Fighter {fighter_id}: "
            f"{probability_text!r}. Defaulting to failed without rolling."
        )
        metadata["reason"] = "invalid_probability"
        return metadata

    if probability <= 0:
        metadata.update({"probability": probability, "reason": "zero_probability"})
        return metadata

    roll = fight_rng.random() if fight_rng is not None else rand()
    success = roll < probability
    metadata.update(
        {
            "probability": probability,
            "roll": roll,
            "success": success,
            "reason": "success" if success else "failed",
        }
    )
    return metadata


def _resolve_turn_rolls(
    p1: dict[str, Any],
    fight_rng: random.Random | None = None,
) -> tuple[dict[str, bool], dict[str, dict[str, Any]]]:
    roll_metadata = {
        fighter_id: _resolve_attempt_roll(p1, fighter_id, fight_rng=fight_rng)
        for fighter_id in (C.FIGHTER_A, C.FIGHTER_B)
    }
    successful_rolls = {fighter_id: bool(metadata.get("success")) for fighter_id, metadata in roll_metadata.items()}
    return successful_rolls, roll_metadata


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


def _apply_effect_roll_modifiers(p1: dict[str, Any], fighters: dict[str, FighterState]) -> dict[str, Any]:
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
            generation_kwargs["on_retry"] = lambda retry: _emit_llm_output_retry(
                on_event,
                phase="profile_generation",
                retry=retry,
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
    run_index: int | None = None,
    fight_id: str | None = None,
) -> dict[str, str] | tuple[dict[str, str], CombatLog]:
    """Simulate a single fight between two AI fighters."""
    hooks = SingleFightHooks(
        model=FightModelServices(
            build_match_fighters=_build_match_fighters,
            get_fighter_attempt=get_fighter_attempt,
            judge_phase1=judge_phase1,
            judge_phase2=judge_phase2,
        ),
        rules=FightRuleServices(
            apply_effect_roll_modifiers=_apply_effect_roll_modifiers,
            authorize_phase2_result=_authorize_phase2_result,
            resolve_turn_rolls=_resolve_turn_rolls,
            status_outcome=_status_outcome,
            judge_outcome=_judge_outcome,
            winner_display_name=_winner_display_name,
        ),
        events=FightEventServices(
            emit_event=_emit_event,
            emit_token_metadata=_emit_token_metadata,
            fight_event_type=FightEvent,
        ),
    )
    return await run_single_fight(
        fighter_a_section=fighter_a_section,
        fighter_b_section=fighter_b_section,
        return_log=return_log,
        fight_rng=fight_rng,
        on_event=on_event,
        run_index=run_index,
        fight_id=fight_id,
        hooks=hooks,
    )


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
    return await batch_mod.run_batch(
        output_csv=output_csv,
        fighter_a_section=fighter_a_section,
        fighter_b_section=fighter_b_section,
        progress=progress,
        fight_runner=cast(batch_mod.FightRunner, _single_fight),
    )
