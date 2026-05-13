"""Judge orchestration (Phase-1 probability, RNG, Phase-2 narration)."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from jsonschema import ValidationError, validate

from . import config as config_mod
from .agents import chat, chat_with_metadata
from .engine import constants as C
from .engine.logger import logger
from .engine.prompts import JUDGE_P1_SYSTEM_PROMPT, JUDGE_P2_SYSTEM_PROMPT
from .engine.state_summary import compact_fighter_state_summary
from .utils.json_parser import parse_json_from_text
from .utils.token_counter import budget_messages_with_trimmed_log
from .validation import JudgeP1Schema, JudgeP2Schema, guarded_call

# -------------------------------------------------------------------


class JudgePhase2FailureError(RuntimeError):
    """Raised when Judge Phase 2 exhausts retries under fail-closed policy."""


@dataclass(frozen=True)
class _JudgePhase2Settings:
    max_tokens: int
    best_of: int
    max_retries: int
    parse_retries: int
    context_limit: int


@dataclass(frozen=True)
class _JudgePhase2Context:
    p2_input_state: dict[str, Any]
    rolls: dict[str, bool]
    original_recent_log: str
    settings: _JudgePhase2Settings


def _effect_names_text(effects: list[Any]) -> str:
    names = []
    for effect in effects:
        name = effect.get(C.NAME, "") if isinstance(effect, dict) else str(effect)
        if name:
            names.append(name)
    return ", ".join(names) if names else "none"


def _active_effect_names_text(fighter: dict[str, Any], effect_type: str) -> str:
    active_effects = fighter.get(C.ACTIVE_EFFECTS)
    if isinstance(active_effects, list):
        names = [
            effect.get(C.NAME, "")
            for effect in active_effects
            if isinstance(effect, dict) and effect.get(C.TYPE) == effect_type and effect.get(C.NAME)
        ]
        return ", ".join(names) if names else "none"
    return _effect_names_text(fighter.get(effect_type, []))


def _current_state_reminder(fighter_a: dict[str, Any], fighter_b: dict[str, Any]) -> str:
    temp_terms = "smoke, haze, shadows, poison, bleeding, burning, stun, or obscurity"
    return (
        "Current active effects: "
        f"Fighter A buffs={_active_effect_names_text(fighter_a, C.BUFFS)}, "
        f"debuffs={_active_effect_names_text(fighter_a, C.DEBUFFS)}; "
        f"Fighter B buffs={_active_effect_names_text(fighter_b, C.BUFFS)}, "
        f"debuffs={_active_effect_names_text(fighter_b, C.DEBUFFS)}. "
        "Temporary effects not listed here are inactive, even if recent_combat_log mentions them. "
        f"Do not cite old {temp_terms} as current conditions unless they are listed here or "
        "created by the current action."
    )


def _fighter_summary(state: dict[str, Any]) -> dict[str, Any]:
    return compact_fighter_state_summary(state)


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


def _sanitize_error_text(exc: Exception, max_length: int = 180) -> str:
    text = f"{type(exc).__name__}: {exc}"
    text = " ".join(str(text).split())
    if len(text) > max_length:
        text = text[: max_length - 3].rstrip() + "..."
    return text


def _strip_untrusted_phase2_metadata(result: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(result)
    sanitized.pop(C.METADATA, None)
    sanitized.pop(C.P2_ENGINE_FALLBACK_MARKER, None)
    return sanitized


def _phase2_failure_policy() -> str:
    return config_mod.CONFIG.get_judge_phase2_failure_policy()


def _phase2_noop_result(exc: Exception | None = None, *, policy: str = C.P2_FAILURE_POLICY_FAIL_OPEN) -> dict[str, Any]:
    metadata = {
        C.P2_FALLBACK_USED: True,
        C.P2_FALLBACK_REASON: C.P2_FALLBACK_REASON_PARSE_FAILED,
        C.P2_FALLBACK_POLICY: policy,
    }
    if exc is not None:
        metadata[C.P2_LLM_ERROR] = _sanitize_error_text(exc)
    return {
        C.NARRATION: "The exchange is inconclusive; both fighters keep their guard and reset distance.",
        C.DELTA: {},
        C.FIGHT_END: False,
        C.WINNER: None,
        C.METADATA: metadata,
        C.P2_ENGINE_FALLBACK_MARKER: True,
    }


def _judge_phase2_settings() -> _JudgePhase2Settings:
    max_tokens, best_of, max_retries = _judge_settings()
    parse_retries = min(max_retries, 2)
    context_limit = _ollama_num_ctx(max_tokens)
    return _JudgePhase2Settings(
        max_tokens=max_tokens,
        best_of=best_of,
        max_retries=max_retries,
        parse_retries=parse_retries,
        context_limit=context_limit,
    )


def _judge_phase2_context(p2_input_state: dict[str, Any], rolls: dict[str, bool]) -> _JudgePhase2Context:
    return _JudgePhase2Context(
        p2_input_state=p2_input_state,
        rolls=rolls,
        original_recent_log=str(p2_input_state.get("recent_combat_log", "")),
        settings=_judge_phase2_settings(),
    )


def _judge_phase2_user_payload(context: _JudgePhase2Context, recent_log: str, *, repair: bool) -> dict[str, Any]:
    user_payload = {
        **context.p2_input_state,
        "recent_combat_log": recent_log,
        C.SUCCESSFUL_ROLLS: context.rolls,
    }
    user_payload["current_state_reminder"] = _current_state_reminder(
        context.p2_input_state.get("fighter_A", {}),
        context.p2_input_state.get("fighter_B", {}),
    )
    if repair:
        user_payload["strict_output_reminder"] = (
            "Return one compact JSON object only with keys narration, delta, fight_end, and winner. "
            "Use no markdown, no prose outside JSON, and no reasoning text."
        )
    return user_payload


def _judge_phase2_messages(
    context: _JudgePhase2Context,
    recent_log: str,
    *,
    repair: bool = False,
) -> list[dict[str, str]]:
    system = {C.AGENT_ROLE: C.AGENT_SYSTEM, C.AGENT_CONTENT: JUDGE_P2_SYSTEM_PROMPT}
    user = {
        C.AGENT_ROLE: C.AGENT_USER,
        C.AGENT_CONTENT: json.dumps(_judge_phase2_user_payload(context, recent_log, repair=repair)),
    }
    return [system, user]


def _budget_judge_phase2_messages(
    context: _JudgePhase2Context,
    *,
    repair: bool = False,
) -> tuple[list[dict[str, str]], int]:
    settings = context.settings
    min_completion_tokens = C.PROMPT_MIN_COMPLETION_JUDGE_P2_REPAIR if repair else C.PROMPT_MIN_COMPLETION_JUDGE_P2
    phase = C.PROMPT_PHASE_JUDGE_P2_REPAIR if repair else C.PROMPT_PHASE_JUDGE_P2

    def build_for_log(candidate_recent_log: str) -> list[dict[str, str]]:
        return _judge_phase2_messages(context, candidate_recent_log, repair=repair)

    messages, max_tokens, _ = budget_messages_with_trimmed_log(
        build_for_log,
        context.original_recent_log,
        requested_max_tokens=settings.max_tokens,
        context_limit=settings.context_limit,
        min_completion_tokens=min_completion_tokens,
        phase=phase,
        log_window_setting=C.CONFIG_JUDGE_LOG_WINDOW,
    )
    return messages, max_tokens


async def _request_judge_phase2_texts(
    messages: list[dict[str, str]],
    max_tokens: int,
    settings: _JudgePhase2Settings,
    on_metadata: Callable[[dict[str, Any]], None] | None,
    *,
    schema: dict[str, Any] | None,
) -> list[str]:
    best_of = settings.best_of if schema is not None else max(1, settings.best_of)
    if on_metadata is None:
        kwargs: dict[str, Any] = {}
        if schema is not None:
            kwargs["schema"] = schema
        return await chat(
            messages,
            max_tokens=max_tokens,
            num_ctx=settings.context_limit,
            best_of=best_of,
            retries=settings.max_retries,
            **kwargs,
        )

    kwargs = {}
    if schema is not None:
        kwargs["schema"] = schema
    results = await chat_with_metadata(
        messages,
        max_tokens=max_tokens,
        num_ctx=settings.context_limit,
        best_of=best_of,
        retries=settings.max_retries,
        **kwargs,
    )
    response_texts = [result.content for result in results]
    for result in results:
        if result.metadata:
            on_metadata(result.metadata)
    return response_texts


async def _call_judge_phase2_with_schema(
    context: _JudgePhase2Context,
    on_metadata: Callable[[dict[str, Any]], None] | None,
) -> dict[str, Any]:
    messages, max_tokens = _budget_judge_phase2_messages(context)
    response_texts = await _request_judge_phase2_texts(
        messages,
        max_tokens,
        context.settings,
        on_metadata,
        schema=JudgeP2Schema,
    )
    return _parse_first_json_response(response_texts)


async def _call_judge_phase2_repair(
    context: _JudgePhase2Context,
    on_metadata: Callable[[dict[str, Any]], None] | None,
) -> dict[str, Any]:
    messages, max_tokens = _budget_judge_phase2_messages(context, repair=True)
    response_texts = await _request_judge_phase2_texts(
        messages,
        max_tokens,
        context.settings,
        on_metadata,
        schema=None,
    )
    return _parse_first_json_response(response_texts)


async def _call_judge_phase2_with_repair(
    context: _JudgePhase2Context,
    on_metadata: Callable[[dict[str, Any]], None] | None,
) -> dict[str, Any]:
    try:
        data = await _call_judge_phase2_with_schema(context, on_metadata)
        validate(data, JudgeP2Schema)
        return data
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.warning("Judge Phase 2 structured response failed; retrying as plain JSON: %s", exc)
        return await _call_judge_phase2_repair(context, on_metadata)


def _handle_phase2_guarded_failure(exc: RuntimeError) -> dict[str, Any]:
    policy = _phase2_failure_policy()
    if policy == C.P2_FAILURE_POLICY_FAIL_CLOSED:
        raise JudgePhase2FailureError(
            f"Judge Phase 2 failed after retries under fail_closed policy: {_sanitize_error_text(exc)}"
        ) from exc
    logger.warning("Judge Phase 2 failed after retries; using no-op turn result: %s", exc)
    return _phase2_noop_result(exc, policy=policy)


async def judge_phase1(
    state: dict[str, Any],
    attemptA: str,
    attemptB: str,
    *,
    recent_log: str = "",
    on_metadata: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
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
    max_tok_j, best_j, max_retries = _judge_settings()
    context_limit = _ollama_num_ctx(max_tok_j)

    def build_messages(candidate_recent_log: str) -> list[dict[str, str]]:
        user_content = {
            f"fighter_{C.FIGHTER_A}_state_summary": fighter_a_summary,
            f"fighter_{C.FIGHTER_B}_state_summary": fighter_b_summary,
            f"{C.ATTEMPT}_{C.FIGHTER_A}": attemptA,
            f"{C.ATTEMPT}_{C.FIGHTER_B}": attemptB,
            "recent_combat_log": candidate_recent_log,
            "current_state_reminder": _current_state_reminder(fighter_a_summary, fighter_b_summary),
        }
        user = {C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: json.dumps(user_content)}
        return [system, user]

    messages, max_tok, _ = budget_messages_with_trimmed_log(
        build_messages,
        recent_log,
        requested_max_tokens=max_tok_j,
        context_limit=context_limit,
        min_completion_tokens=C.PROMPT_MIN_COMPLETION_JUDGE_P1,
        phase=C.PROMPT_PHASE_JUDGE_P1,
        log_window_setting=C.CONFIG_FIGHTER_LOG_WINDOW,
    )

    async def _call():
        if on_metadata is None:
            response_texts = await chat(
                messages,
                max_tokens=max_tok,
                num_ctx=context_limit,
                best_of=best_j,
                schema=JudgeP1Schema,
                retries=max_retries,
            )
        else:
            results = await chat_with_metadata(
                messages,
                max_tokens=max_tok,
                num_ctx=context_limit,
                best_of=best_j,
                schema=JudgeP1Schema,
                retries=max_retries,
            )
            response_texts = [result.content for result in results]
            for result in results:
                if result.metadata:
                    on_metadata(result.metadata)
        return _parse_first_json_response(response_texts)

    result = await guarded_call(_call, JudgeP1Schema, max_retries=max_retries)
    return result


async def judge_phase2(
    p2_input_state: dict[str, Any],
    rolls: dict[str, bool],
    *,
    on_metadata: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
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
    context = _judge_phase2_context(p2_input_state, rolls)

    try:
        result = await guarded_call(
            lambda: _call_judge_phase2_with_repair(context, on_metadata),
            JudgeP2Schema,
            max_retries=context.settings.parse_retries,
        )
    except RuntimeError as exc:
        return _handle_phase2_guarded_failure(exc)
    return _strip_untrusted_phase2_metadata(result)
