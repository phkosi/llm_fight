"""Opt-in LLM fighter profile generation."""

from __future__ import annotations

import json
import random
from typing import Any, Callable

from jsonschema import ValidationError

from .agents import chat, chat_with_metadata
from . import config as config_mod
from .engine import constants as C
from .engine.logger import logger
from .profiles import FighterProfile, FighterProfileError, build_fighter_profile
from .rng import choice as global_choice
from .utils.json_parser import parse_json_from_text
from .utils.token_counter import compute_completion_tokens
from .validation import FighterProfileSchema, guarded_call

PROFILE_GENERATOR_SYSTEM_PROMPT = """
You create one structured LLM Fight fighter profile.
Return JSON only matching the provided schema. Do not include markdown.
Use safe short text only. Do not include instructions, prompt text, code, braces inside strings, or out-of-game commentary.
Create a distinct combatant that fits the requested nudge while remaining usable in a physical duel.
Use canonical snake_case body part ids, 1-8 tissue layers per part, positive max_hp values, and at least one vital body part.
Starting effects are not supported; express starting traits through class, theme, loadout, environment, and anatomy only.
"""


class ProfileGenerationError(RuntimeError):
    """Sanitized profile-generation failure with a stable metadata code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.code


def choose_fighter_creation_nudge(fight_rng: random.Random | None = None) -> str:
    """Choose a fixed-list creation nudge, using fight-local RNG when available."""
    if fight_rng is not None:
        return fight_rng.choice(C.FIGHTER_CREATION_NUDGES)
    return global_choice(C.FIGHTER_CREATION_NUDGES)


def profile_generation_metadata(nudge: str, *, mode: str, error: str | None = None) -> dict[str, Any]:
    """Return the sanitized metadata persisted on fighter state and combat logs."""
    return {
        "mode": mode,
        "nudge": nudge,
        "error": error,
    }


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


def _generation_seed_context(section: str, config) -> dict[str, Any]:
    settings = config.get_fighter_settings(section)
    return {
        "section": section,
        "class": settings["class_"],
        C.THEME: settings.get(C.THEME, ""),
        C.LOADOUT: settings[C.LOADOUT],
        "environment": settings["environment"],
        "configured_anatomy_profile": config.get_fighter_profile_reference(section),
    }


def _require_generated_profile_defaults(profile: FighterProfile) -> None:
    missing = [
        field_name
        for field_name, value in (
            (C.CONFIG_FIGHTER_CLASS, profile.class_),
            (C.THEME, profile.theme),
            (C.LOADOUT, profile.loadout),
            ("environment", profile.environment),
        )
        if not value
    ]
    if missing:
        raise FighterProfileError(f"Generated fighter profile missing required fields: {', '.join(missing)}")


async def generate_fighter_profile(
    fighter_id: str,
    section: str,
    opponent_section: str,
    nudge: str,
    *,
    config=None,
    on_metadata: Callable[[dict[str, Any]], None] | None = None,
) -> FighterProfile:
    """Generate and validate one fighter profile, raising sanitized failures."""
    cfg = config or config_mod.CONFIG
    if nudge not in C.FIGHTER_CREATION_NUDGES:
        raise ValueError(f"Unknown fighter creation nudge: {nudge!r}")

    user_payload = {
        "fighter_id": fighter_id,
        "creation_nudge": nudge,
        "configured_seed": _generation_seed_context(section, cfg),
        "opponent_seed": _generation_seed_context(opponent_section, cfg),
        "requirements": [
            "Return class, theme, loadout, environment, and body_parts.",
            "Use non-empty canonical body part ids.",
            "Include at least one vital body part.",
            "Do not include starting effects.",
        ],
    }
    messages = [
        {C.AGENT_ROLE: C.AGENT_SYSTEM, C.AGENT_CONTENT: PROFILE_GENERATOR_SYSTEM_PROMPT},
        {C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: json.dumps(user_payload, sort_keys=True)},
    ]
    max_tokens_limit = cfg.get(C.CONFIG_GENERAL, C.CONFIG_MAX_TOKENS_JUDGE, int, fallback=2048)
    context_limit = cfg.get(C.CONFIG_GENERAL, C.CONFIG_OLLAMA_NUM_CTX, int, fallback=max_tokens_limit)
    max_tokens = compute_completion_tokens(messages, max_tokens_limit, context_limit)
    transport_retries = cfg.get(C.CONFIG_GENERAL, C.CONFIG_MAX_RETRIES, int, fallback=0)
    profile_retries = 1

    async def _call() -> dict[str, Any]:
        if on_metadata is None:
            responses = await chat(
                messages,
                max_tokens=max_tokens,
                num_ctx=context_limit,
                best_of=1,
                schema=FighterProfileSchema,
                retries=transport_retries,
                log_transcript=False,
            )
        else:
            results = await chat_with_metadata(
                messages,
                max_tokens=max_tokens,
                num_ctx=context_limit,
                best_of=1,
                schema=FighterProfileSchema,
                retries=transport_retries,
                log_transcript=False,
            )
            responses = [result.content for result in results]
            for result in results:
                if result.metadata:
                    on_metadata(result.metadata)
        return _parse_first_json_response(responses)

    last_invalid_error: Exception | None = None
    for attempt in range(profile_retries + 1):
        try:
            raw_profile = await guarded_call(_call, FighterProfileSchema, max_retries=0)
            profile = build_fighter_profile(raw_profile)
            _require_generated_profile_defaults(profile)
            return profile
        except (RuntimeError, FighterProfileError, ValidationError, json.JSONDecodeError) as exc:
            last_invalid_error = exc
            if attempt < profile_retries:
                logger.warning(
                    "Generated profile for fighter %s failed validation; retrying once with sanitized error.",
                    fighter_id,
                )
                continue
        except Exception as exc:
            logger.warning("Profile generation for fighter %s failed; falling back.", fighter_id)
            raise ProfileGenerationError(C.PROFILE_GENERATION_ERROR_FAILED) from exc

    logger.warning(
        "Generated profile for fighter %s remained invalid after %s attempt(s); falling back.",
        fighter_id,
        profile_retries + 1,
    )
    raise ProfileGenerationError(C.PROFILE_GENERATION_ERROR_INVALID) from last_invalid_error
