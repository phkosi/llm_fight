"""Fighter agent logic: builds context and queries LLM for actions."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .. import config as config_mod
from ..agents import chat, chat_with_metadata
from ..state import FighterState  # Relative import from parent package
from ..utils.token_counter import budget_messages_with_trimmed_log
from . import constants as C  # Added import
from .combat_log import CombatLog
from .logger import logger
from .prompts import FIGHTER_SYSTEM_PROMPT, TEMPORARY_EFFECT_HISTORY_GUARDRAIL, TEMPORARY_EFFECT_TERMS
from .state_summary import (
    compact_fighter_state_summary,
    environment_scope_guardrail,
    render_fighter_state_summary,
)

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)
_EMPTY_ACTION_FALLBACK = "I keep my guard up and look for an opening."


@dataclass(frozen=True)
class _FighterPromptSettings:
    turn_window: int
    sentence_limit: int
    word_limit: int
    generation_limit: int
    context_limit: int
    best_of: int
    max_retries: int
    empty_action_retries: int


@dataclass(frozen=True)
class _FighterPromptContext:
    fighter: FighterState
    opponent: FighterState
    pain_desc: str
    exhaustion_desc: str
    heat_desc: str
    effects_list: str
    self_state_summary: dict[str, Any]
    opponent_state_summary: dict[str, Any]
    recent_log: str
    settings: _FighterPromptSettings


def _clean_fighter_action(text: str) -> str:
    """Strip whitespace and common reasoning-only wrappers from model output."""
    cleaned = _THINK_BLOCK_RE.sub("", text or "").strip()
    if cleaned.lower().startswith("<think>"):
        return ""
    return cleaned


def _temporary_effect_instruction(effects_list: str) -> str:
    if effects_list == "none":
        return (
            f"No temporary effects are active right now. Do not describe {TEMPORARY_EFFECT_TERMS} "
            "as current conditions unless your new action creates them."
        )
    return (
        f"Only these temporary effects are active right now: {effects_list}. "
        f"Do not describe other old {TEMPORARY_EFFECT_TERMS} as current conditions."
    )


def _valid_target_parts_text(fighter: FighterState) -> str:
    return ", ".join(sorted(fighter.parts.keys())) or "none"


def _effects_list_text(fighter: FighterState) -> str:
    effects = compact_fighter_state_summary(fighter)[C.ACTIVE_EFFECTS]
    if not effects:
        return "none"
    return render_fighter_state_summary(effects)


def describe_pain(pain_level: int) -> str:
    if pain_level <= 0:
        return "no pain"
    if pain_level < 10:
        return "minor aches"
    if pain_level < 30:
        return "noticeable pain"
    if pain_level < 50:
        return "moderate pain, distracting"
    if pain_level < 70:
        return "severe pain, hard to focus"
    if pain_level < 90:
        return "crippling pain"
    return "unbearable agony"


def describe_exhaustion(exhaustion_level: int) -> str:
    if exhaustion_level <= 0:
        return "fully rested"
    if exhaustion_level < 10:
        return "slightly winded"
    if exhaustion_level < 30:
        return "feeling tired"
    if exhaustion_level < 50:
        return "heavily fatigued"
    if exhaustion_level < 70:
        return "exhausted, movement is a struggle"
    if exhaustion_level < 90:
        return "utterly spent"
    return "on the verge of collapse"


def describe_heat(heat_level: int) -> str:
    if heat_level <= 0:
        return "normal body temperature"
    if heat_level < 10:
        return "slightly warm"
    if heat_level < 30:
        return "feeling hot"
    if heat_level < 50:
        return "sweating profusely, very hot"
    if heat_level < 70:
        return "overheating, dizziness sets in"
    if heat_level < 90:
        return "dangerously overheated, nearing heatstroke"
    return "critical heat levels, system failure imminent"


def _resolve_turn_window(turn_window: int | None) -> int:
    if turn_window is not None:
        return turn_window
    return config_mod.CONFIG.get(C.CONFIG_CONTEXT, C.CONFIG_FIGHTER_LOG_WINDOW, int, fallback=5)


def _recent_fighter_log(combat_log: CombatLog | str | None, turn_window: int) -> str:
    if isinstance(combat_log, CombatLog):
        return "" if turn_window == 0 else combat_log.to_summary(last_n=turn_window)
    if turn_window == 0:
        return ""
    return str(combat_log) if combat_log else "The fight has just begun! Nothing to report yet."


def _fighter_prompt_settings(turn_window: int) -> _FighterPromptSettings:
    sentence_limit = config_mod.CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_FIGHTER_SENTENCE_LIMIT, int, fallback=1)
    word_limit = config_mod.CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_FIGHTER_WORD_LIMIT, int, fallback=30)
    generation_limit = config_mod.CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_MAX_TOKENS_FIGHTER, int, fallback=256)
    context_limit = config_mod.CONFIG.get(
        C.CONFIG_GENERAL,
        C.CONFIG_OLLAMA_NUM_CTX,
        int,
        fallback=generation_limit,
    )
    best_of = config_mod.CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_BEST_OF_FIGHTER, int, fallback=1)
    max_retries = config_mod.CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_MAX_RETRIES, int, fallback=0)
    invalid_output_retries = config_mod.CONFIG.get_invalid_output_retries()
    return _FighterPromptSettings(
        turn_window=turn_window,
        sentence_limit=sentence_limit,
        word_limit=word_limit,
        generation_limit=generation_limit,
        context_limit=context_limit,
        best_of=best_of,
        max_retries=max_retries,
        empty_action_retries=invalid_output_retries,
    )


def _fighter_prompt_context(
    fighter: FighterState,
    opponent: FighterState,
    combat_log: CombatLog | str | None,
    turn_window: int | None,
) -> _FighterPromptContext:
    resolved_window = _resolve_turn_window(turn_window)
    return _FighterPromptContext(
        fighter=fighter,
        opponent=opponent,
        pain_desc=describe_pain(fighter.pain),
        exhaustion_desc=describe_exhaustion(fighter.exhaustion),
        heat_desc=describe_heat(fighter.heat),
        effects_list=_effects_list_text(fighter),
        self_state_summary=compact_fighter_state_summary(fighter),
        opponent_state_summary=compact_fighter_state_summary(opponent),
        recent_log=_recent_fighter_log(combat_log, resolved_window),
        settings=_fighter_prompt_settings(resolved_window),
    )


def _build_fighter_messages(
    context: _FighterPromptContext,
    recent_log: str,
    *,
    retry: bool = False,
) -> list[dict[str, str]]:
    fighter = context.fighter
    opponent = context.opponent
    settings = context.settings
    system_prompt_content = FIGHTER_SYSTEM_PROMPT.format(
        fighter_id=fighter.id,
        display_name=fighter.display_name,
        opponent_id=opponent.id,
        opponent_display_name=opponent.display_name,
        class_=fighter.class_,
        environment=fighter.environment,
        pain_desc=context.pain_desc,
        exhaustion_desc=context.exhaustion_desc,
        heat_desc=context.heat_desc,
        effects_list=context.effects_list,
        own_target_parts=_valid_target_parts_text(fighter),
        opponent_target_parts=_valid_target_parts_text(opponent),
        self_state_summary=render_fighter_state_summary(context.self_state_summary),
        opponent_state_summary=render_fighter_state_summary(context.opponent_state_summary),
        environment_scope_guardrail=environment_scope_guardrail(),
        temporary_effect_history_guardrail=TEMPORARY_EFFECT_HISTORY_GUARDRAIL,
        temporary_effect_instruction=_temporary_effect_instruction(context.effects_list),
        turn_window=settings.turn_window,
        recent_log=recent_log,
        loadout=fighter.loadout,
        sentence_limit=settings.sentence_limit,
        word_limit=settings.word_limit,
    )

    messages = [
        {C.AGENT_ROLE: C.AGENT_SYSTEM, C.AGENT_CONTENT: system_prompt_content},
        {
            C.AGENT_ROLE: C.AGENT_USER,
            C.AGENT_CONTENT: (
                f"It's your turn to act, Fighter {fighter.id} ({fighter.display_name}). "
                f"Opponent Fighter {opponent.id} ({opponent.display_name}) is visible. What do you do?"
            ),
        },
    ]
    if retry:
        messages.append(
            {
                C.AGENT_ROLE: C.AGENT_USER,
                C.AGENT_CONTENT: (
                    f"Your previous response was empty. Give one concrete physical action for Fighter {fighter.id} "
                    f"({fighter.display_name}) now. Raw action text only."
                ),
            }
        )
    return messages


def _budget_fighter_messages(
    context: _FighterPromptContext,
    *,
    retry: bool,
) -> tuple[list[dict[str, str]], int]:
    def build_for_log(recent_log: str) -> list[dict[str, str]]:
        return _build_fighter_messages(context, recent_log, retry=retry)

    active_messages, active_max_tokens, _ = budget_messages_with_trimmed_log(
        build_for_log,
        context.recent_log,
        requested_max_tokens=context.settings.generation_limit,
        context_limit=context.settings.context_limit,
        min_completion_tokens=C.PROMPT_MIN_COMPLETION_FIGHTER,
        phase=C.PROMPT_PHASE_FIGHTER_ACTION,
        log_window_setting=C.CONFIG_FIGHTER_LOG_WINDOW,
    )
    return active_messages, active_max_tokens


async def _request_fighter_texts(
    messages: list[dict[str, str]],
    max_tokens: int,
    settings: _FighterPromptSettings,
    on_metadata: Callable[[dict[str, Any]], None] | None,
) -> list[str]:
    if on_metadata is None:
        return await chat(
            messages,
            max_tokens=max_tokens,
            num_ctx=settings.context_limit,
            best_of=settings.best_of,
            retries=settings.max_retries,
        )

    results = await chat_with_metadata(
        messages,
        max_tokens=max_tokens,
        num_ctx=settings.context_limit,
        best_of=settings.best_of,
        retries=settings.max_retries,
    )
    texts = [result.content for result in results]
    for result in results:
        if result.metadata:
            on_metadata(result.metadata)
    return texts


def _first_clean_fighter_action(texts: list[str]) -> str | None:
    for text in texts:
        cleaned = _clean_fighter_action(text)
        if cleaned:
            return cleaned
    return None


async def get_fighter_attempt(
    fighter: FighterState,
    opponent: FighterState,
    combat_log: CombatLog | str | None = None,
    turn_window: int | None = None,
    on_metadata: Callable[[dict[str, Any]], None] | None = None,
    on_retry: Callable[[dict[str, Any]], None] | None = None,
) -> str:
    """Generates a fighter's attempted action for the current turn.

    Args:
        fighter: Acting fighter state.
        opponent: Opposing fighter state.
        combat_log: Either a ``CombatLog`` instance or a pre-formatted string
            summarising recent turns.
        turn_window: Number of recent turns to include in the prompt.
    """

    context = _fighter_prompt_context(fighter, opponent, combat_log, turn_window)

    for attempt in range(context.settings.empty_action_retries + 1):
        active_messages, active_max_tokens = _budget_fighter_messages(context, retry=bool(attempt))
        texts = await _request_fighter_texts(active_messages, active_max_tokens, context.settings, on_metadata)
        action = _first_clean_fighter_action(texts)
        if action:
            return action
        logger.warning(
            "Fighter %s returned only empty action text on attempt %s/%s.",
            fighter.id,
            attempt + 1,
            context.settings.empty_action_retries + 1,
        )
        if attempt < context.settings.empty_action_retries and on_retry is not None:
            on_retry(
                {
                    "attempt": attempt + 1,
                    "next_attempt": attempt + 2,
                    "max_attempts": context.settings.empty_action_retries + 1,
                    "reason": "empty_fighter_action",
                    "error_type": "EmptyAction",
                }
            )

    logger.warning("Fighter %s produced no usable action; using fallback guard action.", fighter.id)
    return _EMPTY_ACTION_FALLBACK
