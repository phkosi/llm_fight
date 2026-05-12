"""Fighter agent logic: builds context and queries LLM for actions."""

import re
from typing import Union, Optional, Callable, Any

from ..state import FighterState  # Relative import from parent package
from ..agents import chat, chat_with_metadata
from ..utils.token_counter import budget_messages_with_trimmed_log
from .. import config as config_mod
from .prompts import FIGHTER_SYSTEM_PROMPT  # Import the detailed prompt
from . import constants as C  # Added import
from .combat_log import CombatLog
from .logger import logger
from .state_summary import (
    compact_fighter_state_summary,
    environment_scope_guardrail,
    render_fighter_state_summary,
)

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)
_EMPTY_ACTION_FALLBACK = "I keep my guard up and look for an opening."
_TEMPORARY_EFFECT_TERMS = "smoke, haze, shadows, poison, bleeding, burning, stun, or obscurity"


def _clean_fighter_action(text: str) -> str:
    """Strip whitespace and common reasoning-only wrappers from model output."""
    cleaned = _THINK_BLOCK_RE.sub("", text or "").strip()
    if cleaned.lower().startswith("<think>"):
        return ""
    return cleaned


def _temporary_effect_instruction(effects_list: str) -> str:
    if effects_list == "none":
        return (
            f"No temporary effects are active right now. Do not describe {_TEMPORARY_EFFECT_TERMS} "
            "as current conditions unless your new action creates them."
        )
    return (
        f"Only these temporary effects are active right now: {effects_list}. "
        f"Do not describe other old {_TEMPORARY_EFFECT_TERMS} as current conditions."
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


async def get_fighter_attempt(
    fighter: FighterState,
    opponent: FighterState,
    combat_log: Union[CombatLog, str, None] = None,
    turn_window: Optional[int] = None,
    on_metadata: Callable[[dict[str, Any]], None] | None = None,
) -> str:
    """Generates a fighter's attempted action for the current turn.

    Args:
        fighter: Acting fighter state.
        opponent: Opposing fighter state.
        combat_log: Either a ``CombatLog`` instance or a pre-formatted string
            summarising recent turns.
        turn_window: Number of recent turns to include in the prompt.
    """

    pain_desc = describe_pain(fighter.pain)
    exhaustion_desc = describe_exhaustion(fighter.exhaustion)
    heat_desc = describe_heat(fighter.heat)
    effects_list = _effects_list_text(fighter)
    self_state_summary = compact_fighter_state_summary(fighter)
    opponent_state_summary = compact_fighter_state_summary(opponent)

    loadout = fighter.loadout

    # If turn_window is not explicitly passed, try to get it from config, else default.
    # This allows _single_fight to control it, or use a global default.
    if turn_window is None:
        turn_window = config_mod.CONFIG.get(C.CONFIG_CONTEXT, C.CONFIG_FIGHTER_LOG_WINDOW, int, fallback=5)

    # Determine what snippet of combat history to include in the prompt
    if isinstance(combat_log, CombatLog):
        current_recent_log = "" if turn_window == 0 else combat_log.to_summary(last_n=turn_window)
    else:
        if turn_window == 0:
            current_recent_log = ""
        else:
            current_recent_log = str(combat_log) if combat_log else "The fight has just begun! Nothing to report yet."

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
    empty_action_retries = min(max_retries, 1)

    def build_messages(recent_log: str, retry: bool = False) -> list[dict[str, str]]:
        system_prompt_content = FIGHTER_SYSTEM_PROMPT.format(
            fighter_id=fighter.id,
            display_name=fighter.display_name,
            opponent_id=opponent.id,
            opponent_display_name=opponent.display_name,
            class_=fighter.class_,
            environment=fighter.environment,
            pain_desc=pain_desc,
            exhaustion_desc=exhaustion_desc,
            heat_desc=heat_desc,
            effects_list=effects_list,
            own_target_parts=_valid_target_parts_text(fighter),
            opponent_target_parts=_valid_target_parts_text(opponent),
            self_state_summary=render_fighter_state_summary(self_state_summary),
            opponent_state_summary=render_fighter_state_summary(opponent_state_summary),
            environment_scope_guardrail=environment_scope_guardrail(),
            temporary_effect_instruction=_temporary_effect_instruction(effects_list),
            turn_window=turn_window,
            recent_log=recent_log,
            loadout=loadout,
            sentence_limit=sentence_limit,
            word_limit=word_limit,
        )

        system = {C.AGENT_ROLE: C.AGENT_SYSTEM, C.AGENT_CONTENT: system_prompt_content}
        user_prompt_content = (
            f"It's your turn to act, Fighter {fighter.id} ({fighter.display_name}). "
            f"Opponent Fighter {opponent.id} ({opponent.display_name}) is visible. What do you do?"
        )
        user = {C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: user_prompt_content}
        messages = [system, user]
        if retry:
            retry_user = {
                C.AGENT_ROLE: C.AGENT_USER,
                C.AGENT_CONTENT: (
                    f"Your previous response was empty. Give one concrete physical action for Fighter {fighter.id} "
                    f"({fighter.display_name}) now. Raw action text only."
                ),
            }
            messages.append(retry_user)
        return messages

    for attempt in range(empty_action_retries + 1):
        active_messages, active_max_tokens, _ = budget_messages_with_trimmed_log(
            lambda recent_log, retry=bool(attempt): build_messages(recent_log, retry=retry),
            current_recent_log,
            requested_max_tokens=generation_limit,
            context_limit=context_limit,
            min_completion_tokens=C.PROMPT_MIN_COMPLETION_FIGHTER,
            phase=C.PROMPT_PHASE_FIGHTER_ACTION,
            log_window_setting=C.CONFIG_FIGHTER_LOG_WINDOW,
        )

        if on_metadata is None:
            texts = await chat(
                active_messages,
                max_tokens=active_max_tokens,
                num_ctx=context_limit,
                best_of=best_of,
                retries=max_retries,
            )
        else:
            results = await chat_with_metadata(
                active_messages,
                max_tokens=active_max_tokens,
                num_ctx=context_limit,
                best_of=best_of,
                retries=max_retries,
            )
            texts = [result.content for result in results]
            for result in results:
                if result.metadata:
                    on_metadata(result.metadata)
        for txt in texts:
            cleaned = _clean_fighter_action(txt)
            if cleaned:
                return cleaned
        logger.warning(
            "Fighter %s returned only empty action text on attempt %s/%s.",
            fighter.id,
            attempt + 1,
            empty_action_retries + 1,
        )

    logger.warning("Fighter %s produced no usable action; using fallback guard action.", fighter.id)
    return _EMPTY_ACTION_FALLBACK
