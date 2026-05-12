"""Judge orchestration (Phase-1 probability, RNG, Phase-2 narration)."""

import json
from typing import Dict, Any

from jsonschema import ValidationError, validate

from .utils.json_parser import parse_json_from_text

from .agents import chat
from .utils.token_counter import compute_completion_tokens
from .validation import JudgeP1Schema, JudgeP2Schema, guarded_call
from . import config as config_mod
from .engine.prompts import JUDGE_P1_SYSTEM_PROMPT, JUDGE_P2_SYSTEM_PROMPT
from .engine import constants as C
from .engine.logger import logger

# -------------------------------------------------------------------


def _status_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def _effect_summary(effect: dict[str, Any]) -> dict[str, Any]:
    summary = {
        C.NAME: effect.get(C.NAME),
        "ttl": effect.get(C.EFFECT_TTL),
        "magnitude": effect.get("magnitude"),
    }
    metadata = effect.get(C.METADATA, {})
    target = metadata.get(C.TARGETED_PART) if isinstance(metadata, dict) else None
    if target:
        summary[C.TARGETED_PART] = target
    if effect.get(C.EFFECT_MECHANICS):
        summary[C.EFFECT_MECHANICS] = effect.get(C.EFFECT_MECHANICS)
    if effect.get(C.EFFECT_TAGS):
        summary[C.EFFECT_TAGS] = effect.get(C.EFFECT_TAGS)
    return {key: value for key, value in summary.items() if value not in (None, "", [])}


def _effect_summaries(effects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_effect_summary(effect) for effect in effects if effect.get(C.NAME)]


def _effect_names_text(effects: list[Any]) -> str:
    names = []
    for effect in effects:
        if isinstance(effect, dict):
            name = effect.get(C.NAME, "")
        else:
            name = str(effect)
        if name:
            names.append(name)
    return ", ".join(names) if names else "none"


def _current_state_reminder(fighter_a: dict[str, Any], fighter_b: dict[str, Any]) -> str:
    temp_terms = "smoke, haze, shadows, poison, bleeding, burning, stun, or obscurity"
    return (
        "Current active effects: "
        f"Fighter A buffs={_effect_names_text(fighter_a.get(C.BUFFS, []))}, "
        f"debuffs={_effect_names_text(fighter_a.get(C.DEBUFFS, []))}; "
        f"Fighter B buffs={_effect_names_text(fighter_b.get(C.BUFFS, []))}, "
        f"debuffs={_effect_names_text(fighter_b.get(C.DEBUFFS, []))}. "
        "Temporary effects not listed here are inactive, even if recent_combat_log mentions them. "
        f"Do not cite old {temp_terms} as current conditions unless they are listed here or created by the current action."
    )


def _damaged_parts(parts: dict[str, Any]) -> dict[str, Any]:
    damaged = {}
    for name, part in parts.items():
        status = part.get(C.STATUS, "intact")
        layers = part.get("layers", [])
        damaged_layers = [
            {"name": layer.get(C.NAME), "hp": layer.get(C.MAX_HP)} for layer in layers if layer.get(C.MAX_HP, 0) <= 0
        ]
        if status != "intact" or part.get("severed") or damaged_layers:
            damaged[name] = {
                C.STATUS: status,
                "severed": part.get("severed", False),
                "damaged_layers": damaged_layers,
            }
    return damaged


def _fighter_summary(state: dict[str, Any]) -> dict[str, Any]:
    parts = state.get("parts", {})
    return {
        "id": state.get("id"),
        "class": state.get("class_"),
        C.LOADOUT: state.get(C.LOADOUT),
        "environment": state.get("environment"),
        C.STATUS: _status_value(state.get(C.STATUS)),
        C.PAIN: state.get(C.PAIN),
        C.EXHAUSTION: state.get(C.EXHAUSTION),
        C.HEAT: state.get(C.HEAT),
        C.BUFFS: _effect_summaries(state.get(C.BUFFS, [])),
        C.DEBUFFS: _effect_summaries(state.get(C.DEBUFFS, [])),
        "valid_target_parts": sorted(parts.keys()),
        "damaged_parts": _damaged_parts(parts),
    }


def _judge_settings() -> tuple[int, int, int]:
    cfg = config_mod.CONFIG
    return (
        cfg.get(C.CONFIG_GENERAL, C.CONFIG_MAX_TOKENS_JUDGE, int),
        cfg.get(C.CONFIG_GENERAL, C.CONFIG_BEST_OF_JUDGE, int),
        cfg.get(C.CONFIG_GENERAL, C.CONFIG_MAX_RETRIES, int),
    )


def _ollama_num_ctx(fallback: int) -> int:
    return config_mod.CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_OLLAMA_NUM_CTX, int, fallback=fallback)


def _parse_first_json_response(response_texts: list[str]) -> dict[str, Any]:
    last_error: json.JSONDecodeError | None = None
    for txt in response_texts:
        if not (txt or "").strip():
            last_error = json.JSONDecodeError("LLM response was empty.", "", 0)
            continue
        try:
            return parse_json_from_text(txt)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
    if last_error:
        raise last_error
    raise json.JSONDecodeError("None of the LLM responses were valid JSON.", "", 0)


def _phase2_noop_result() -> dict[str, Any]:
    return {
        C.NARRATION: "The exchange is inconclusive; both fighters keep their guard and reset distance.",
        C.DELTA: {},
        C.FIGHT_END: False,
        C.WINNER: None,
    }


async def judge_phase1(state: Dict[str, Any], attemptA: str, attemptB: str, *, recent_log: str = "") -> Dict[str, Any]:
    """
    Judge Phase 1: Evaluates two fighter attempts for validity and success probability.

    Args:
        state: Dictionary containing summaries of fighter A and B's states.
        attemptA: String describing fighter A's attempted action.
        attemptB: String describing fighter B's attempted action.
        recent_log: Text summary of the most recent turns from the combat log.

    Returns:
        A dictionary conforming to JudgeP1Schema, including judgement text,
        validity flags, and success probabilities for each attempt.
    """
    system_prompt_content = JUDGE_P1_SYSTEM_PROMPT
    system = {C.AGENT_ROLE: C.AGENT_SYSTEM, C.AGENT_CONTENT: system_prompt_content}
    fighter_a_summary = _fighter_summary(state.get(C.FIGHTER_A, {}))
    fighter_b_summary = _fighter_summary(state.get(C.FIGHTER_B, {}))
    user_content = {
        f"fighter_{C.FIGHTER_A}_state_summary": fighter_a_summary,
        f"fighter_{C.FIGHTER_B}_state_summary": fighter_b_summary,
        f"{C.ATTEMPT}_{C.FIGHTER_A}": attemptA,
        f"{C.ATTEMPT}_{C.FIGHTER_B}": attemptB,
        "recent_combat_log": recent_log,
        "current_state_reminder": _current_state_reminder(fighter_a_summary, fighter_b_summary),
    }
    user = {C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: json.dumps(user_content)}

    messages = [system, user]
    max_tok_j, best_j, max_retries = _judge_settings()
    context_limit = _ollama_num_ctx(max_tok_j)
    max_tok = compute_completion_tokens(messages, max_tok_j, context_limit)

    async def _call():
        response_texts = await chat(
            messages,
            max_tokens=max_tok,
            num_ctx=context_limit,
            best_of=best_j,
            schema=JudgeP1Schema,
            retries=max_retries,
        )
        return _parse_first_json_response(response_texts)

    result = await guarded_call(_call, JudgeP1Schema, max_retries=max_retries)
    return result


async def judge_phase2(p2_input_state: Dict[str, Any], rolls: Dict[str, bool]) -> Dict[str, Any]:
    """
    Judge Phase 2: Narrates combat outcomes and calculates state changes (deltas).

    Args:
        p2_input_state: Dictionary containing current states of fighter A and B,
                        the judgement from Phase 1, and any combat log context.
        rolls: Dictionary indicating whether each fighter's attempt was successful.

    Returns:
        A dictionary conforming to JudgeP2Schema, including narration, state deltas
        for each fighter, a flag indicating if the fight ended, and the winner if applicable.
    """
    system_prompt_content = JUDGE_P2_SYSTEM_PROMPT
    system = {C.AGENT_ROLE: C.AGENT_SYSTEM, C.AGENT_CONTENT: system_prompt_content}
    # user_content already prepared and passed as p2_input_state, merge with rolls
    user_payload = {**p2_input_state, C.SUCCESSFUL_ROLLS: rolls}
    user_payload["current_state_reminder"] = _current_state_reminder(
        p2_input_state.get("fighter_A", {}),
        p2_input_state.get("fighter_B", {}),
    )
    user = {C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: json.dumps(user_payload)}

    messages = [system, user]
    max_tok_j, best_j, max_retries = _judge_settings()
    parse_retries = min(max_retries, 2)
    context_limit = _ollama_num_ctx(max_tok_j)
    max_tok = compute_completion_tokens(messages, max_tok_j, context_limit)

    async def _call_with_schema() -> dict[str, Any]:
        response_texts = await chat(
            messages,
            max_tokens=max_tok,
            num_ctx=context_limit,
            best_of=best_j,
            schema=JudgeP2Schema,
            retries=max_retries,
        )
        return _parse_first_json_response(response_texts)

    async def _call_without_schema() -> dict[str, Any]:
        repair_payload = {
            **user_payload,
            "strict_output_reminder": (
                "Return one compact JSON object only with keys narration, delta, fight_end, and winner. "
                "Use no markdown, no prose outside JSON, and no reasoning text."
            ),
        }
        repair_messages = [
            system,
            {C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: json.dumps(repair_payload)},
        ]
        response_texts = await chat(
            repair_messages,
            max_tokens=max_tok,
            num_ctx=context_limit,
            best_of=max(1, best_j),
            retries=max_retries,
        )
        return _parse_first_json_response(response_texts)

    async def _call() -> dict[str, Any]:
        try:
            data = await _call_with_schema()
            validate(data, JudgeP2Schema)
            return data
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.warning("Judge Phase 2 structured response failed; retrying as plain JSON: %s", exc)
            return await _call_without_schema()

    try:
        result = await guarded_call(_call, JudgeP2Schema, max_retries=parse_retries)
    except RuntimeError as exc:
        logger.warning("Judge Phase 2 failed after retries; using no-op turn result: %s", exc)
        result = _phase2_noop_result()
    return result
