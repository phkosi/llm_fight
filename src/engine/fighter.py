"""Fighter agent logic: builds context and queries LLM for actions."""
from typing import Union, Optional

from ..state import FighterState  # Relative import from parent package
from ..agents import chat
from ..config import CONFIG
from .prompts import FIGHTER_SYSTEM_PROMPT  # Import the detailed prompt
from . import constants as C  # Added import
from .combat_log import CombatLog

def describe_pain(pain_level: int) -> str:
    if pain_level <= 0: return "no pain"
    if pain_level < 10: return "minor aches"
    if pain_level < 30: return "noticeable pain"
    if pain_level < 50: return "moderate pain, distracting"
    if pain_level < 70: return "severe pain, hard to focus"
    if pain_level < 90: return "crippling pain"
    return "unbearable agony"

def describe_exhaustion(exhaustion_level: int) -> str:
    if exhaustion_level <= 0: return "fully rested"
    if exhaustion_level < 10: return "slightly winded"
    if exhaustion_level < 30: return "feeling tired"
    if exhaustion_level < 50: return "heavily fatigued"
    if exhaustion_level < 70: return "exhausted, movement is a struggle"
    if exhaustion_level < 90: return "utterly spent"
    return "on the verge of collapse"

def describe_heat(heat_level: int) -> str:
    if heat_level <= 0: return "normal body temperature"
    if heat_level < 10: return "slightly warm"
    if heat_level < 30: return "feeling hot"
    if heat_level < 50: return "sweating profusely, very hot"
    if heat_level < 70: return "overheating, dizziness sets in"
    if heat_level < 90: return "dangerously overheated, nearing heatstroke"
    return "critical heat levels, system failure imminent"

async def get_fighter_attempt(
    fighter: FighterState,
    opponent: FighterState,
    combat_log: Union[CombatLog, str, None] = None,
    turn_window: Optional[int] = None,
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
    effects_list = ", ".join([e.name for e in fighter.buffs + fighter.debuffs]) or "none"
    
    loadout = fighter.loadout
    
    # If turn_window is not explicitly passed, try to get it from config, else default.
    # This allows _single_fight to control it, or use a global default.
    if turn_window is None:
        turn_window = CONFIG.get(C.CONFIG_CONTEXT, C.CONFIG_FIGHTER_LOG_WINDOW, int, fallback=5)

    # Determine what snippet of combat history to include in the prompt
    if isinstance(combat_log, CombatLog):
        current_recent_log = "" if turn_window == 0 else combat_log.to_summary(last_n=turn_window)
    else:
        if turn_window == 0:
            current_recent_log = ""
        else:
            current_recent_log = str(combat_log) if combat_log else "The fight has just begun! Nothing to report yet."

    system_prompt_content = FIGHTER_SYSTEM_PROMPT.format(
        name=fighter.id,
        class_=fighter.class_,
        environment=fighter.environment,
        pain_desc=pain_desc,
        exhaustion_desc=exhaustion_desc,
        heat_desc=heat_desc,
        effects_list=effects_list,
        turn_window=turn_window,
        recent_log=current_recent_log,
        loadout=loadout
    )
        
    system = {C.AGENT_ROLE: C.AGENT_SYSTEM, C.AGENT_CONTENT: system_prompt_content}
    # The user message might be simplified or removed if all context is in the system prompt
    # For now, let's keep a minimal user prompt that could signal the start of their turn to formulate an action.
    user_prompt_content = f"It's your turn to act, {fighter.id}. Opponent {opponent.id} is visible. What do you do?"
    
    user = {C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: user_prompt_content}
    
    texts = await chat(
        [system, user],
        max_tokens=CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_MAX_TOKENS_FIGHTER, int, fallback=256),
        best_of=CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_BEST_OF_FIGHTER, int, fallback=1)
    )
    txt = texts[0]
    return txt.strip()
