"""Single-fight orchestration helpers."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from . import config as config_mod
from .engine import constants as C
from .engine.combat_log import CombatLog, CombatTurn
from .engine.logger import logger
from .state import FighterState
from .transcripts import active_trace, create_fight_trace, llm_trace_context


@dataclass(frozen=True)
class FightModelServices:
    build_match_fighters: Callable[..., Awaitable[tuple[FighterState, FighterState]]]
    get_fighter_attempt: Callable[..., Awaitable[str]]
    judge_phase1: Callable[..., Awaitable[dict[str, Any]]]
    judge_phase2: Callable[..., Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class FightRuleServices:
    apply_effect_roll_modifiers: Callable[[dict[str, Any], dict[str, FighterState]], dict[str, Any]]
    authorize_phase2_result: Callable[..., dict[str, Any]]
    resolve_turn_rolls: Callable[..., tuple[dict[str, bool], dict[str, Any]]]
    status_outcome: Callable[[FighterState, FighterState], str | None]
    judge_outcome: Callable[[dict[str, Any]], str | None]
    winner_display_name: Callable[[str, dict[str, FighterState]], str]


@dataclass(frozen=True)
class FightEventServices:
    emit_event: Callable[[Callable[[Any], None] | None, Any], None]
    emit_token_metadata: Callable[..., None]
    fight_event_type: type


@dataclass(frozen=True)
class SingleFightHooks:
    """Runtime services used by the generic single-fight loop."""

    model: FightModelServices
    rules: FightRuleServices
    events: FightEventServices

    @property
    def build_match_fighters(self):
        return self.model.build_match_fighters

    @property
    def get_fighter_attempt(self):
        return self.model.get_fighter_attempt

    @property
    def judge_phase1(self):
        return self.model.judge_phase1

    @property
    def judge_phase2(self):
        return self.model.judge_phase2

    @property
    def apply_effect_roll_modifiers(self):
        return self.rules.apply_effect_roll_modifiers

    @property
    def authorize_phase2_result(self):
        return self.rules.authorize_phase2_result

    @property
    def resolve_turn_rolls(self):
        return self.rules.resolve_turn_rolls

    @property
    def status_outcome(self):
        return self.rules.status_outcome

    @property
    def judge_outcome(self):
        return self.rules.judge_outcome

    @property
    def winner_display_name(self):
        return self.rules.winner_display_name

    @property
    def emit_event(self):
        return self.events.emit_event

    @property
    def emit_token_metadata(self):
        return self.events.emit_token_metadata

    @property
    def fight_event_type(self):
        return self.events.fight_event_type


def _resolved_fighter_sections(
    fighter_a_section: str | None,
    fighter_b_section: str | None,
) -> tuple[str, str]:
    if fighter_a_section is None:
        fighter_a_section = config_mod.CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_FIGHTER_A_SECTION, str, fallback="A")
    if fighter_b_section is None:
        fighter_b_section = config_mod.CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_FIGHTER_B_SECTION, str, fallback="B")
    return fighter_a_section, fighter_b_section


def _trace_event_callback(trace_writer, external_on_event, hooks: SingleFightHooks):
    def trace_and_forward(event) -> None:
        trace_writer.write_fight_event(event)
        hooks.emit_event(external_on_event, event)

    if getattr(trace_writer, "enabled", False) or external_on_event is not None:
        return trace_and_forward
    return None


async def _fighter_attempt(
    fighter: FighterState,
    opponent: FighterState,
    *,
    turn: int,
    combat_log: CombatLog,
    fighter_log_window: int,
    wants_event_metadata: bool,
    on_event,
    trace_writer,
    hooks: SingleFightHooks,
) -> str:
    hooks.emit_event(
        on_event, hooks.fight_event_type(C.FIGHT_EVENT_FIGHTER_ACTION_START, turn=turn, fighter_id=fighter.id)
    )
    try:
        attempt_kwargs: dict[str, Any] = {
            "combat_log": combat_log,
            "turn_window": fighter_log_window,
        }
        if wants_event_metadata:
            attempt_kwargs["on_metadata"] = lambda metadata: hooks.emit_token_metadata(
                on_event,
                phase="fighter_action",
                metadata=metadata,
                turn=turn,
                fighter_id=fighter.id,
            )
        with (
            active_trace(trace_writer),
            llm_trace_context(phase="fighter_action", turn=turn, fighter_id=fighter.id),
        ):
            return await hooks.get_fighter_attempt(fighter, opponent, **attempt_kwargs)
    finally:
        hooks.emit_event(
            on_event, hooks.fight_event_type(C.FIGHT_EVENT_FIGHTER_ACTION_END, turn=turn, fighter_id=fighter.id)
        )


async def _collect_fighter_attempts(
    A: FighterState,
    B: FighterState,
    *,
    turn: int,
    combat_log: CombatLog,
    fighter_log_window: int,
    wants_event_metadata: bool,
    on_event,
    trace_writer,
    hooks: SingleFightHooks,
) -> tuple[str, str]:
    tasks = [
        asyncio.create_task(
            _fighter_attempt(
                A,
                B,
                turn=turn,
                combat_log=combat_log,
                fighter_log_window=fighter_log_window,
                wants_event_metadata=wants_event_metadata,
                on_event=on_event,
                trace_writer=trace_writer,
                hooks=hooks,
            )
        ),
        asyncio.create_task(
            _fighter_attempt(
                B,
                A,
                turn=turn,
                combat_log=combat_log,
                fighter_log_window=fighter_log_window,
                wants_event_metadata=wants_event_metadata,
                on_event=on_event,
                trace_writer=trace_writer,
                hooks=hooks,
            )
        ),
    ]
    try:
        attempts = await asyncio.gather(*tasks)
        return attempts[0], attempts[1]
    except BaseException:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


async def _judge_phase1_result(
    A: FighterState,
    B: FighterState,
    attemptA: str,
    attemptB: str,
    *,
    turn: int,
    combat_log: CombatLog,
    fighter_log_window: int,
    wants_event_metadata: bool,
    on_event,
    trace_writer,
    hooks: SingleFightHooks,
) -> dict[str, Any]:
    recent_log = combat_log.to_summary(last_n=fighter_log_window)
    hooks.emit_event(on_event, hooks.fight_event_type(C.FIGHT_EVENT_JUDGE_PHASE1_START, turn=turn))
    p1_kwargs: dict[str, Any] = {"recent_log": recent_log}
    if wants_event_metadata:
        p1_kwargs["on_metadata"] = lambda metadata: hooks.emit_token_metadata(
            on_event,
            phase="judge_phase1",
            metadata=metadata,
            turn=turn,
        )
    with active_trace(trace_writer), llm_trace_context(phase="judge_phase1", turn=turn):
        p1 = await hooks.judge_phase1({"A": A.to_json(), "B": B.to_json()}, attemptA, attemptB, **p1_kwargs)
    p1 = hooks.apply_effect_roll_modifiers(p1, {C.FIGHTER_A: A, C.FIGHTER_B: B})
    hooks.emit_event(on_event, hooks.fight_event_type(C.FIGHT_EVENT_JUDGE_PHASE1_END, turn=turn, data={"p1": p1}))
    return p1


def _p2_input_state(
    A: FighterState,
    B: FighterState,
    attemptA: str,
    attemptB: str,
    p1: dict[str, Any],
    combat_log: CombatLog,
    judge_log_window: int,
) -> dict[str, Any]:
    return {
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
        "recent_combat_log": combat_log.to_summary(last_n=judge_log_window),
    }


async def _judge_phase2_result(
    p2_input_state: dict[str, Any],
    p1: dict[str, Any],
    rolls: dict[str, bool],
    fighters: dict[str, FighterState],
    attempts: dict[str, str],
    *,
    turn: int,
    wants_event_metadata: bool,
    on_event,
    trace_writer,
    hooks: SingleFightHooks,
) -> dict[str, Any]:
    hooks.emit_event(on_event, hooks.fight_event_type(C.FIGHT_EVENT_JUDGE_PHASE2_START, turn=turn))
    p2_kwargs: dict[str, Any] = {}
    if wants_event_metadata:
        p2_kwargs["on_metadata"] = lambda metadata: hooks.emit_token_metadata(
            on_event,
            phase="judge_phase2",
            metadata=metadata,
            turn=turn,
        )
    with active_trace(trace_writer), llm_trace_context(phase="judge_phase2", turn=turn):
        p2 = await hooks.judge_phase2(p2_input_state, rolls, **p2_kwargs)
    p2 = hooks.authorize_phase2_result(p2, p1, rolls, fighters, attempts=attempts)
    hooks.emit_event(on_event, hooks.fight_event_type(C.FIGHT_EVENT_JUDGE_PHASE2_END, turn=turn, data={"p2": p2}))
    return p2


def _apply_turn_state(
    A: FighterState,
    B: FighterState,
    p2: dict[str, Any],
    *,
    turn: int,
    fight_rng: random.Random | None,
    on_event,
    hooks: SingleFightHooks,
) -> None:
    hooks.emit_event(on_event, hooks.fight_event_type(C.FIGHT_EVENT_DELTAS_START, turn=turn))
    if "delta" in p2 and isinstance(p2["delta"], dict):
        A.apply_delta(p2["delta"].get("A", {}))
        B.apply_delta(p2["delta"].get("B", {}))
    hooks.emit_event(on_event, hooks.fight_event_type(C.FIGHT_EVENT_DELTAS_END, turn=turn))

    hooks.emit_event(on_event, hooks.fight_event_type(C.FIGHT_EVENT_EFFECTS_START, turn=turn))
    A.apply_effects(rng=fight_rng)
    B.apply_effects(rng=fight_rng)
    hooks.emit_event(on_event, hooks.fight_event_type(C.FIGHT_EVENT_EFFECTS_END, turn=turn))


async def _run_turn(
    A: FighterState,
    B: FighterState,
    *,
    turn: int,
    combat_log: CombatLog,
    fighter_log_window: int,
    judge_log_window: int,
    fight_rng: random.Random | None,
    wants_event_metadata: bool,
    on_event,
    trace_writer,
    hooks: SingleFightHooks,
) -> tuple[CombatTurn, dict[str, Any]]:
    attemptA, attemptB = await _collect_fighter_attempts(
        A,
        B,
        turn=turn,
        combat_log=combat_log,
        fighter_log_window=fighter_log_window,
        wants_event_metadata=wants_event_metadata,
        on_event=on_event,
        trace_writer=trace_writer,
        hooks=hooks,
    )
    p1 = await _judge_phase1_result(
        A,
        B,
        attemptA,
        attemptB,
        turn=turn,
        combat_log=combat_log,
        fighter_log_window=fighter_log_window,
        wants_event_metadata=wants_event_metadata,
        on_event=on_event,
        trace_writer=trace_writer,
        hooks=hooks,
    )
    hooks.emit_event(on_event, hooks.fight_event_type(C.FIGHT_EVENT_ROLLS_START, turn=turn))
    rolls, roll_metadata = hooks.resolve_turn_rolls(p1, fight_rng=fight_rng)
    hooks.emit_event(
        on_event,
        hooks.fight_event_type(
            C.FIGHT_EVENT_ROLLS_END,
            turn=turn,
            data={"rolls": dict(rolls), C.ROLL_METADATA: roll_metadata},
        ),
    )

    p2_input = _p2_input_state(A, B, attemptA, attemptB, p1, combat_log, judge_log_window)
    attempts = {
        C.FIGHTER_A: attemptA,
        C.FIGHTER_B: attemptB,
    }
    p2 = await _judge_phase2_result(
        p2_input,
        p1,
        rolls,
        {C.FIGHTER_A: A, C.FIGHTER_B: B},
        attempts,
        turn=turn,
        wants_event_metadata=wants_event_metadata,
        on_event=on_event,
        trace_writer=trace_writer,
        hooks=hooks,
    )
    turn_entry = CombatTurn(
        turn=turn,
        attempt_A=attemptA,
        attempt_B=attemptB,
        judge_p1=p1,
        judge_p2=p2,
        state_A_before=p2_input["fighter_A"],
        state_B_before=p2_input["fighter_B"],
        rolls=roll_metadata,
    )
    _apply_turn_state(A, B, p2, turn=turn, fight_rng=fight_rng, on_event=on_event, hooks=hooks)
    turn_entry.state_A_after = A.to_json()
    turn_entry.state_B_after = B.to_json()
    return turn_entry, p2


def _resolve_outcome(
    A: FighterState,
    B: FighterState,
    p2: dict[str, Any],
    turn: int,
    hooks: SingleFightHooks,
) -> str | None:
    status_outcome = hooks.status_outcome(A, B)
    judge_outcome = hooks.judge_outcome(p2)
    if status_outcome:
        if judge_outcome and judge_outcome != status_outcome:
            logger.warning(
                "Judge outcome %s contradicted post-delta state outcome %s; using state outcome.",
                judge_outcome,
                status_outcome,
            )
        return status_outcome
    if judge_outcome:
        logger.warning(
            "Ignoring judge-only outcome %s because post-delta state outcome is not terminal.",
            judge_outcome,
        )
    if turn >= config_mod.CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, int, fallback=100):
        return C.DRAW
    return None


def _fight_result(
    A: FighterState,
    B: FighterState,
    *,
    outcome: str,
    turn: int,
    p2_fallback_turns: int,
    hooks: SingleFightHooks,
) -> dict[str, str]:
    return {
        C.WINNER: outcome,
        C.LOG_TURN: str(turn),
        C.LOG_P2_FALLBACK_TURNS: str(p2_fallback_turns),
        C.LOG_P2_FALLBACK_USED: str(p2_fallback_turns > 0).lower(),
        C.LOG_FIGHTER_A_DISPLAY_NAME: A.display_name,
        C.LOG_FIGHTER_B_DISPLAY_NAME: B.display_name,
        C.LOG_WINNER_DISPLAY_NAME: hooks.winner_display_name(outcome, {C.FIGHTER_A: A, C.FIGHTER_B: B}),
    }


async def run_single_fight(
    fighter_a_section: str | None = None,
    fighter_b_section: str | None = None,
    return_log: bool = False,
    fight_rng: random.Random | None = None,
    on_event: Callable[[Any], None] | None = None,
    run_index: int | None = None,
    fight_id: str | None = None,
    *,
    hooks: SingleFightHooks,
) -> dict[str, str] | tuple[dict[str, str], CombatLog]:
    fighter_a_section, fighter_b_section = _resolved_fighter_sections(fighter_a_section, fighter_b_section)
    trace_writer = create_fight_trace(run_index=run_index, fight_id=fight_id)
    on_event = _trace_event_callback(trace_writer, on_event, hooks)
    wants_event_metadata = on_event is not None
    turn = 0
    trace_writer.write_event(
        event="fight_start",
        phase="fight",
        data={"fighter_a_section": fighter_a_section, "fighter_b_section": fighter_b_section},
    )
    try:
        outcome = None
        p2_fallback_turns = 0
        combat_log = CombatLog()
        A, B = await hooks.build_match_fighters(fighter_a_section, fighter_b_section, combat_log, fight_rng, on_event)
        fighter_log_window = config_mod.CONFIG.get(C.CONFIG_CONTEXT, C.CONFIG_FIGHTER_LOG_WINDOW, int, fallback=5)
        judge_log_window = config_mod.CONFIG.get(C.CONFIG_CONTEXT, C.CONFIG_JUDGE_LOG_WINDOW, int, fallback=9999)

        while not outcome:
            turn += 1
            turn_entry, p2 = await _run_turn(
                A,
                B,
                turn=turn,
                combat_log=combat_log,
                fighter_log_window=fighter_log_window,
                judge_log_window=judge_log_window,
                fight_rng=fight_rng,
                wants_event_metadata=wants_event_metadata,
                on_event=on_event,
                trace_writer=trace_writer,
                hooks=hooks,
            )
            p2_metadata = p2.get(C.METADATA, {})
            if isinstance(p2_metadata, dict) and p2_metadata.get(C.P2_FALLBACK_USED) is True:
                p2_fallback_turns += 1
            combat_log.append(turn_entry)
            hooks.emit_event(
                on_event, hooks.fight_event_type(C.FIGHT_EVENT_TURN_COMPLETE, turn=turn, data={"turn": turn_entry})
            )
            if config_mod.CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_LOG_COMBAT_TURNS, bool, fallback=False):
                logger.info(turn_entry.to_simple_text())
            outcome = _resolve_outcome(A, B, p2, turn, hooks)

        logger.info(f"Fight ended. Outcome: {outcome}, Turns: {turn}")
        logger.info(f"Fighter A ({A.id}) status: {A.status}, Fighter B ({B.id}) status: {B.status}")
        result = _fight_result(A, B, outcome=outcome, turn=turn, p2_fallback_turns=p2_fallback_turns, hooks=hooks)
        hooks.emit_event(
            on_event, hooks.fight_event_type(C.FIGHT_EVENT_FIGHT_COMPLETE, turn=turn, data={"result": result})
        )
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
