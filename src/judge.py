"""Judge orchestration (Phase‑1 probability, RNG, Phase‑2 narration)."""

import json
from typing import Dict, Any

from .utils.json_parser import parse_json_from_text

from .agents import chat
from .validation import JudgeP1Model, JudgeP2Model, guarded_call
from .config import CONFIG
from .engine.prompts import JUDGE_P1_SYSTEM_PROMPT, JUDGE_P2_SYSTEM_PROMPT
from .engine import constants as C

MAX_TOK_J = CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_MAX_TOKENS_JUDGE, int)
BEST_J = CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_BEST_OF_JUDGE, int)

# -------------------------------------------------------------------


async def judge_phase1(state: Dict[str, Any], attemptA: str, attemptB: str, *, recent_log: str = "") -> JudgeP1Model:
    """
    Judge Phase 1: Evaluates two fighter attempts for validity and success probability.

    Args:
        state: Dictionary containing summaries of fighter A and B's states.
        attemptA: String describing fighter A's attempted action.
        attemptB: String describing fighter B's attempted action.
        recent_log: Text summary of the most recent turns from the combat log.

    Returns:
        A ``JudgeP1Model`` including judgement text,
        validity flags, and success probabilities for each attempt.
    """
    system_prompt_content = JUDGE_P1_SYSTEM_PROMPT
    system = {C.AGENT_ROLE: C.AGENT_SYSTEM, C.AGENT_CONTENT: system_prompt_content}
    user_content = {
        f"fighter_{C.FIGHTER_A}_state_summary": {
            C.STATUS: state.get(C.FIGHTER_A, {}).get(C.STATUS),
            C.PAIN: state.get(C.FIGHTER_A, {}).get(C.PAIN),
        },
        f"fighter_{C.FIGHTER_B}_state_summary": {
            C.STATUS: state.get(C.FIGHTER_B, {}).get(C.STATUS),
            C.PAIN: state.get(C.FIGHTER_B, {}).get(C.PAIN),
        },
        f"{C.ATTEMPT}_{C.FIGHTER_A}": attemptA,
        f"{C.ATTEMPT}_{C.FIGHTER_B}": attemptB,
        "recent_combat_log": recent_log,
    }
    user = {C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: json.dumps(user_content)}

    async def _call():
        response_texts = await chat(
            [system, user],
            max_tokens=MAX_TOK_J,
            best_of=BEST_J,
            format=JudgeP1Model.model_json_schema(),
        )
        for txt in response_texts:
            try:
                return json.dumps(parse_json_from_text(txt))
            except json.JSONDecodeError:
                continue  # Try next response
        raise json.JSONDecodeError("None of the LLM responses were valid JSON.", "", 0)  # All failed

    result = await guarded_call(_call, JudgeP1Model)
    return result


async def judge_phase2(p2_input_state: Dict[str, Any], rolls: Dict[str, bool]) -> JudgeP2Model:
    """
    Judge Phase 2: Narrates combat outcomes and calculates state changes (deltas).

    Args:
        p2_input_state: Dictionary containing current states of fighter A and B,
                        the judgement from Phase 1, and any combat log context.
        rolls: Dictionary indicating whether each fighter's attempt was successful.

    Returns:
        A ``JudgeP2Model`` including narration, state deltas
        for each fighter, a flag indicating if the fight ended, and the winner if applicable.
    """
    system_prompt_content = JUDGE_P2_SYSTEM_PROMPT
    system = {C.AGENT_ROLE: C.AGENT_SYSTEM, C.AGENT_CONTENT: system_prompt_content}
    # user_content already prepared and passed as p2_input_state, merge with rolls
    user_payload = {**p2_input_state, C.PREDICTION: rolls}
    user = {C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: json.dumps(user_payload)}

    async def _call():
        response_texts = await chat(
            [system, user],
            max_tokens=MAX_TOK_J,
            best_of=BEST_J,
            format=JudgeP2Model.model_json_schema(),
        )
        for txt in response_texts:
            try:
                return json.dumps(parse_json_from_text(txt))
            except json.JSONDecodeError:
                continue  # Try next response
        raise json.JSONDecodeError("None of the LLM responses were valid JSON.", "", 0)  # All failed

    result = await guarded_call(_call, JudgeP2Model)
    return result
