"""Batch self-play simulation harness."""

import asyncio
from dataclasses import dataclass, field
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
from .transcripts import active_trace, create_fight_trace, llm_trace_context
from .phase2_authorization import authorize_phase2_result as _authorize_phase2_result
from .profile_generation import (
    ProfileGenerationError,
    choose_fighter_creation_nudge,
    generate_fighter_profile,
    profile_generation_metadata,
)
from . import batch as batch_mod

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


def _resolve_attempt_roll(
    p1: Dict[str, Any],
    fighter_id: str,
    fight_rng: random.Random | None = None,
) -> dict[str, Any]:
    """Resolve one attempt roll and return display metadata."""
    valid = p1.get(f"{C.ATTEMPT}_{fighter_id}_valid", False) is True
    raw_probability = p1.get(f"{C.ATTEMPT}_{fighter_id}_prob", "0.0")
    probability_text = str(raw_probability) if raw_probability is not None else ""
    metadata = {
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
    p1: Dict[str, Any],
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
    run_index: int | None = None,
    fight_id: str | None = None,
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

    trace_writer = create_fight_trace(run_index=run_index, fight_id=fight_id)
    external_on_event = on_event

    def trace_and_forward(event: FightEvent) -> None:
        trace_writer.write_fight_event(event)
        _emit_event(external_on_event, event)

    on_event = trace_and_forward if getattr(trace_writer, "enabled", False) or external_on_event is not None else None
    wants_event_metadata = on_event is not None
    turn = 0
    trace_writer.write_event(
        event="fight_start",
        phase="fight",
        data={
            "fighter_a_section": fighter_a_section,
            "fighter_b_section": fighter_b_section,
        },
    )
    try:
        outcome = None
        p2_fallback_turns = 0
        combat_log = CombatLog()
        A, B = await _build_match_fighters(
            fighter_a_section,
            fighter_b_section,
            combat_log,
            fight_rng,
            on_event=on_event,
        )
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
                    if wants_event_metadata:
                        attempt_kwargs["on_metadata"] = lambda metadata: _emit_token_metadata(
                            on_event,
                            phase="fighter_action",
                            metadata=metadata,
                            turn=turn,
                            fighter_id=fighter.id,
                        )
                    with (
                        active_trace(trace_writer),
                        llm_trace_context(
                            phase="fighter_action",
                            turn=turn,
                            fighter_id=fighter.id,
                        ),
                    ):
                        return await get_fighter_attempt(fighter, opponent, **attempt_kwargs)
                finally:
                    _emit_event(
                        on_event,
                        FightEvent(C.FIGHT_EVENT_FIGHTER_ACTION_END, turn=turn, fighter_id=fighter.id),
                    )

            fighter_attempt_tasks = [
                asyncio.create_task(_fighter_attempt(A, B)),
                asyncio.create_task(_fighter_attempt(B, A)),
            ]
            try:
                attemptA, attemptB = await asyncio.gather(*fighter_attempt_tasks)
            except BaseException:
                for task in fighter_attempt_tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*fighter_attempt_tasks, return_exceptions=True)
                raise
            # Provide recent combat log context to judge_phase1
            p1_recent_log = combat_log.to_summary(last_n=fighter_log_window)
            _emit_event(on_event, FightEvent(C.FIGHT_EVENT_JUDGE_PHASE1_START, turn=turn))
            p1_kwargs: dict[str, Any] = {"recent_log": p1_recent_log}
            if wants_event_metadata:
                p1_kwargs["on_metadata"] = lambda metadata: _emit_token_metadata(
                    on_event,
                    phase="judge_phase1",
                    metadata=metadata,
                    turn=turn,
                )
            with active_trace(trace_writer), llm_trace_context(phase="judge_phase1", turn=turn):
                p1 = await judge_phase1({"A": A.to_json(), "B": B.to_json()}, attemptA, attemptB, **p1_kwargs)
            p1 = _apply_effect_roll_modifiers(p1, {C.FIGHTER_A: A, C.FIGHTER_B: B})
            _emit_event(on_event, FightEvent(C.FIGHT_EVENT_JUDGE_PHASE1_END, turn=turn, data={"p1": p1}))

            # Determine success of attempts based on probabilities from Judge P1
            _emit_event(on_event, FightEvent(C.FIGHT_EVENT_ROLLS_START, turn=turn))
            rolls, roll_metadata = _resolve_turn_rolls(p1, fight_rng=fight_rng)
            _emit_event(
                on_event,
                FightEvent(
                    C.FIGHT_EVENT_ROLLS_END,
                    turn=turn,
                    data={"rolls": dict(rolls), C.ROLL_METADATA: roll_metadata},
                ),
            )

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
            if wants_event_metadata:
                p2_kwargs["on_metadata"] = lambda metadata: _emit_token_metadata(
                    on_event,
                    phase="judge_phase2",
                    metadata=metadata,
                    turn=turn,
                )
            with active_trace(trace_writer), llm_trace_context(phase="judge_phase2", turn=turn):
                p2 = await judge_phase2(p2_input_state, rolls, **p2_kwargs)
            p2 = _authorize_phase2_result(p2, p1, rolls, {C.FIGHTER_A: A, C.FIGHTER_B: B})
            p2_metadata = p2.get(C.METADATA, {})
            if isinstance(p2_metadata, dict) and p2_metadata.get(C.P2_FALLBACK_USED) is True:
                p2_fallback_turns += 1
            _emit_event(on_event, FightEvent(C.FIGHT_EVENT_JUDGE_PHASE2_END, turn=turn, data={"p2": p2}))

            turn_entry = CombatTurn(
                turn=turn,
                attempt_A=attemptA,
                attempt_B=attemptB,
                judge_p1=p1,
                judge_p2=p2,
                state_A_before=p2_input_state["fighter_A"],
                state_B_before=p2_input_state["fighter_B"],
                rolls=roll_metadata,
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
            if not outcome and turn >= config_mod.CONFIG.get(
                C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, int, fallback=100
            ):
                outcome = C.DRAW
            # else: outcome remains None, loop continues

        logger.info(f"Fight ended. Outcome: {outcome}, Turns: {turn}")
        logger.info(f"Fighter A ({A.id}) status: {A.status}, Fighter B ({B.id}) status: {B.status}")
        result = {
            C.WINNER: outcome,
            C.LOG_TURN: str(turn),
            C.LOG_P2_FALLBACK_TURNS: str(p2_fallback_turns),
            C.LOG_P2_FALLBACK_USED: str(p2_fallback_turns > 0).lower(),
            C.LOG_FIGHTER_A_DISPLAY_NAME: A.display_name,
            C.LOG_FIGHTER_B_DISPLAY_NAME: B.display_name,
            C.LOG_WINNER_DISPLAY_NAME: _winner_display_name(outcome, {C.FIGHTER_A: A, C.FIGHTER_B: B}),
        }
        _emit_event(on_event, FightEvent(C.FIGHT_EVENT_FIGHT_COMPLETE, turn=turn, data={"result": result}))
        if return_log:
            return result, combat_log
        return result
    except asyncio.CancelledError:
        trace_writer.write_event(
            event="fight_interrupted",
            phase="fight",
            turn=turn or None,
            data={"error_type": "CancelledError"},
        )
        raise
    except Exception as exc:
        trace_writer.write_event(
            event="fight_error",
            phase="fight",
            turn=turn or None,
            data={
                "error_type": type(exc).__name__,
                "message": f"Fight aborted due to {type(exc).__name__}. See application logs for details.",
            },
        )
        raise


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
        fight_runner=_single_fight,
    )
