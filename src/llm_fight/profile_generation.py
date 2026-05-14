"""Opt-in LLM fighter profile generation."""

from __future__ import annotations

import json
import random
from collections.abc import Callable
from typing import Any

from jsonschema import ValidationError

from . import config as config_mod
from .agents import chat, chat_with_metadata
from .engine import constants as C
from .engine.logger import logger
from .profiles import FighterProfile, FighterProfileError, build_fighter_profile
from .rng import choice as global_choice
from .utils.json_parser import parse_json_from_text
from .utils.token_counter import PromptBudgetError, compute_completion_tokens
from .validation import FighterProfileSchema, guarded_call

PROFILE_GENERATOR_SYSTEM_PROMPT = """
You create one structured LLM Fight fighter profile.
Return one JSON object only. Do not include markdown, explanations, comments, or extra text.
Use exactly these top-level keys: "class", "theme", "loadout", "environment", "body_parts".
Never use "class_", "anatomy", "description", "abilities", "effects", "buffs", "debuffs", "notes", or "current_hp".
Every body part must use only allowed body-part keys. Never use null; omit optional keys when they do not apply.
Use short safe strings with no braces, angle brackets, backticks, prompt text, or out-of-game commentary.
Use simple identifier-like names for body part ids, body part names, layer names, theme, and consequence_group.
Create a distinct combatant that fits the requested nudge while remaining usable in a physical duel.
Avoid a plain humanoid copy: include at least one targetable custom part such as tail, wing, horn, shell, core, crystal, tentacle, or focus.
Use canonical snake_case body part ids, 1-8 tissue layers per part, positive max_hp values, and at least one terminal part.
Most reliable terminal pattern: one body part such as "core" or "head" has is_vital true and consequence_tags ["fatal_if_destroyed"].
Only use allowed consequence_tags. If using mobility_member, set consequence_group to "legs"; if using vision_member, set it to "vision".
Starting effects are not supported; express starting traits through class, theme, loadout, environment, and anatomy only.
"""

PROFILE_GENERATOR_EXAMPLE: dict[str, Any] = {
    C.CONFIG_FIGHTER_CLASS: "Prism Duelist",
    C.THEME: "crystal martial art",
    C.LOADOUT: "mirror blade and prism shield",
    "environment": "open arena",
    C.BODY_PARTS: [
        {
            "id": "core",
            C.NAME: "core",
            "is_vital": True,
            C.CONSEQUENCE_TAGS: [C.CONSEQUENCE_FATAL_IF_DESTROYED],
            "layers": [{C.NAME: "crystal", C.MAX_HP: 24}],
        },
        {
            "id": "left_claw",
            C.NAME: "left_claw",
            "can_be_severed": True,
            C.BLEED_RATE: 1,
            "layers": [{C.NAME: "carapace", C.MAX_HP: 10}, {C.NAME: "muscle", C.MAX_HP: 12}],
        },
        {
            "id": "right_claw",
            C.NAME: "right_claw",
            "can_be_severed": True,
            C.BLEED_RATE: 1,
            "layers": [{C.NAME: "carapace", C.MAX_HP: 10}, {C.NAME: "muscle", C.MAX_HP: 12}],
        },
        {
            "id": "tail",
            C.NAME: "tail",
            "can_be_severed": True,
            C.CONSEQUENCE_TAGS: [C.CONSEQUENCE_MOBILITY_MEMBER],
            C.CONSEQUENCE_GROUP: C.CONSEQUENCE_GROUP_LEGS,
            "layers": [{C.NAME: "scale", C.MAX_HP: 12}, {C.NAME: "bone", C.MAX_HP: 14}],
        },
    ],
}

PROFILE_NUDGE_GUIDANCE = {
    "warrior": "Armored physical combatant with at least one custom target part such as shield_arm, helm, crest, or armor_core.",
    "mage": "Arcane combatant with a targetable focus, wand_hand, mana_core, crystal, familiar, or rune_array.",
    "monster": "Clearly non-humanoid beast with targetable claws, fangs, tail, horn, wing, shell, stinger, or core.",
    "trickster": "Agile deceptive combatant with targetable decoy_limb, mask, hidden_blade_arm, cloak, tail, or smoke_gland.",
    "hybrid": "Mixed body plan combining humanoid parts with a clear non-humanoid part such as wing, tail, tentacle, horn, or shell.",
    "original": "Invent a readable strange body plan with several custom target parts while keeping the mechanics physical.",
}

PROFILE_BODY_PART_KEYS = (
    "id",
    C.NAME,
    "layers",
    "is_vital",
    "can_be_severed",
    C.BLEED_RATE,
    C.BURN_RATE,
    C.CONSEQUENCE_TAGS,
    C.CONSEQUENCE_GROUP,
)


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


def _generation_seed_context(section: str, config, display_name_fallback: str) -> dict[str, Any]:
    settings = config.get_fighter_settings(section, display_name_fallback=display_name_fallback)
    return {
        "section": section,
        C.DISPLAY_NAME: settings[C.DISPLAY_NAME],
        "class": settings["class_"],
        C.THEME: settings.get(C.THEME, ""),
        C.LOADOUT: settings[C.LOADOUT],
        "environment": settings["environment"],
        "configured_anatomy_profile": config.get_fighter_profile_reference(section),
    }


def _profile_generation_payload(
    fighter_id: str, section: str, opponent_section: str, nudge: str, cfg
) -> dict[str, Any]:
    opponent_id = C.FIGHTER_B if fighter_id == C.FIGHTER_A else C.FIGHTER_A
    return {
        "fighter_id": fighter_id,
        "creation_nudge": nudge,
        "configured_seed": _generation_seed_context(section, cfg, fighter_id),
        "opponent_seed": _generation_seed_context(opponent_section, cfg, opponent_id),
        "output_contract": {
            "top_level_keys": [C.CONFIG_FIGHTER_CLASS, C.THEME, C.LOADOUT, "environment", C.BODY_PARTS],
            "body_parts_key_required": True,
            "forbidden_top_level_keys": [
                "class_",
                C.ANATOMY,
                "description",
                "abilities",
                C.BUFFS,
                C.DEBUFFS,
                "effects",
                "notes",
            ],
            "null_policy": "Never use null values. Omit optional keys instead.",
        },
        "body_part_contract": {
            "allowed_keys": list(PROFILE_BODY_PART_KEYS),
            "required_keys": ["id", "layers"],
            "layer_keys": [C.NAME, C.MAX_HP],
            "identifier_style": "Use simple snake_case or short words only; no punctuation beyond spaces, underscores, or hyphens.",
            "terminal_pattern": (
                "Include one part with is_vital true and consequence_tags ['fatal_if_destroyed']; "
                "this is the safest way to satisfy survival validation."
            ),
            "grouped_tags": {
                C.CONSEQUENCE_MOBILITY_MEMBER: C.CONSEQUENCE_GROUP_LEGS,
                C.CONSEQUENCE_VISION_MEMBER: C.CONSEQUENCE_GROUP_VISION,
            },
        },
        "allowed_consequence_tags": list(C.CONSEQUENCE_ALLOWED_TAGS),
        "nudge_guidance": PROFILE_NUDGE_GUIDANCE[nudge],
        "body_plan_goal": (
            "Do not return only the default humanoid target list. Include at least one targetable custom part "
            "that supports the nudge and can matter mechanically."
        ),
        "valid_example": PROFILE_GENERATOR_EXAMPLE,
        "requirements": [
            "Return class, theme, loadout, environment, and body_parts.",
            "Use body_parts, not anatomy.",
            "Use only the allowed keys; no extra fields.",
            "Use non-empty canonical body part ids.",
            "Omit optional body part keys instead of setting them to null.",
            "Include at least one vital body part or explicit terminal consequence tag.",
            "Do not include starting effects.",
        ],
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
    user_payload = _profile_generation_payload(fighter_id, section, opponent_section, nudge, cfg)
    messages = [
        {C.AGENT_ROLE: C.AGENT_SYSTEM, C.AGENT_CONTENT: PROFILE_GENERATOR_SYSTEM_PROMPT},
        {C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: json.dumps(user_payload, sort_keys=True)},
    ]
    max_tokens_limit = cfg.get(C.CONFIG_GENERAL, C.CONFIG_MAX_TOKENS_JUDGE, int, fallback=2048)
    context_limit = cfg.get(C.CONFIG_GENERAL, C.CONFIG_OLLAMA_NUM_CTX, int, fallback=max_tokens_limit)
    try:
        max_tokens = compute_completion_tokens(
            messages,
            max_tokens_limit,
            context_limit,
            min_completion_tokens=C.PROMPT_MIN_COMPLETION_PROFILE_GENERATION,
            phase=C.PROMPT_PHASE_PROFILE_GENERATION,
        )
    except PromptBudgetError as exc:
        logger.warning("Profile generation for fighter %s exceeded prompt budget: %s", fighter_id, exc)
        raise ProfileGenerationError(C.PROFILE_GENERATION_ERROR_FAILED) from exc
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
