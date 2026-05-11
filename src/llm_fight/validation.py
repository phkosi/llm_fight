"""Schema validation and retry helpers using jsonschema."""

import json
import asyncio
from typing import Any, Callable, Dict
from jsonschema import validate, ValidationError

from . import config as config_mod
from .engine import constants as C
from .engine.logger import logger

ActionSchema = {
    C.SCHEMA_TYPE: C.SCHEMA_OBJECT,
    C.SCHEMA_PROPERTIES: {
        C.VALIDATION_PROB: {
            C.SCHEMA_TYPE: C.SCHEMA_NUMBER,
            C.SCHEMA_MINIMUM: 0,
            C.SCHEMA_MAXIMUM: 1,
        },
        C.VALIDATION_PREDICTED: {C.SCHEMA_TYPE: C.SCHEMA_STRING},
    },
    C.SCHEMA_REQUIRED: [C.VALIDATION_PROB, C.VALIDATION_PREDICTED],
}

# Schema for the output of Phase 1 Judge
# This is a simple schema that expects a dictionary with two keys:
# "judgement": a string describing the judgement
# "valid_attempt_A": a boolean indicating if fighter A's attempt is valid
# "valid_attempt_B": a boolean indicating if fighter B's attempt is valid
JudgeP1Schema: Dict[str, Any] = {
    C.SCHEMA_TYPE: C.SCHEMA_OBJECT,
    C.SCHEMA_PROPERTIES: {
        "judgement_text": {C.SCHEMA_TYPE: C.SCHEMA_STRING},
        f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": {C.SCHEMA_TYPE: C.SCHEMA_BOOLEAN},
        f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": {
            C.SCHEMA_TYPE: C.SCHEMA_STRING,
            C.SCHEMA_PATTERN: r"^(0(\.\d+)?|1(\.0+)?)$",
        },
        f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": {C.SCHEMA_TYPE: C.SCHEMA_BOOLEAN},
        f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": {
            C.SCHEMA_TYPE: C.SCHEMA_STRING,
            C.SCHEMA_PATTERN: r"^(0(\.\d+)?|1(\.0+)?)$",
        },
        "explanation": {C.SCHEMA_TYPE: C.SCHEMA_STRING},
    },
    C.SCHEMA_REQUIRED: [
        "judgement_text",
        f"{C.ATTEMPT}_{C.FIGHTER_A}_valid",
        f"{C.ATTEMPT}_{C.FIGHTER_A}_prob",
        f"{C.ATTEMPT}_{C.FIGHTER_B}_valid",
        f"{C.ATTEMPT}_{C.FIGHTER_B}_prob",
    ],
    C.SCHEMA_ADDITIONAL_PROPERTIES: True,
}

EffectMagnitudeSchema = {
    C.SCHEMA_TYPE: C.SCHEMA_NUMBER,
    C.SCHEMA_MINIMUM: 0.001,
    C.SCHEMA_MAXIMUM: C.EFFECT_MAX_MAGNITUDE,
}

EffectTextSchema = {
    C.SCHEMA_TYPE: C.SCHEMA_STRING,
    C.SCHEMA_MIN_LENGTH: 1,
    C.SCHEMA_MAX_LENGTH: C.EFFECT_TEXT_MAX_LENGTH,
    C.SCHEMA_PATTERN: C.EFFECT_SAFE_TEXT_PATTERN,
}

EffectSchema = {
    C.SCHEMA_TYPE: C.SCHEMA_OBJECT,
    C.SCHEMA_PROPERTIES: {
        C.NAME: {
            C.SCHEMA_TYPE: C.SCHEMA_STRING,
            C.SCHEMA_MIN_LENGTH: 1,
            C.SCHEMA_MAX_LENGTH: C.EFFECT_NAME_MAX_LENGTH,
            C.SCHEMA_PATTERN: C.EFFECT_SAFE_NAME_PATTERN,
        },
        C.VALUE: EffectMagnitudeSchema,
        "magnitude": EffectMagnitudeSchema,
        C.EFFECT_TTL: {
            C.SCHEMA_ONE_OF: [
                {
                    C.SCHEMA_TYPE: C.SCHEMA_INTEGER,
                    C.SCHEMA_MINIMUM: 1,
                    C.SCHEMA_MAXIMUM: C.EFFECT_MAX_TTL,
                },
                {C.SCHEMA_CONST: -1},
            ]
        },
        C.TYPE: {C.SCHEMA_TYPE: C.SCHEMA_STRING, C.SCHEMA_ENUM: [C.BUFFS, C.DEBUFFS]},
        C.EFFECT_ON_APPLY: EffectTextSchema,
        C.EFFECT_ON_TICK: EffectTextSchema,
        C.METADATA: {
            C.SCHEMA_TYPE: C.SCHEMA_OBJECT,
            C.SCHEMA_PROPERTIES: {
                C.TARGETED_PART: {
                    C.SCHEMA_TYPE: C.SCHEMA_STRING,
                    C.SCHEMA_MIN_LENGTH: 1,
                    C.SCHEMA_MAX_LENGTH: C.EFFECT_METADATA_VALUE_MAX_LENGTH,
                    C.SCHEMA_PATTERN: C.EFFECT_SAFE_NAME_PATTERN,
                }
            },
            C.SCHEMA_ADDITIONAL_PROPERTIES: False,
        },
    },
    C.SCHEMA_REQUIRED: [C.NAME, C.EFFECT_TTL],
    C.SCHEMA_ONE_OF: [
        {C.SCHEMA_REQUIRED: [C.VALUE], C.SCHEMA_NOT: {C.SCHEMA_REQUIRED: ["magnitude"]}},
        {C.SCHEMA_REQUIRED: ["magnitude"], C.SCHEMA_NOT: {C.SCHEMA_REQUIRED: [C.VALUE]}},
    ],
    C.SCHEMA_ADDITIONAL_PROPERTIES: False,
}

DeltaSchema = {
    C.SCHEMA_TYPE: C.SCHEMA_OBJECT,
    C.SCHEMA_PROPERTIES: {
        C.PAIN_INCREASE: {C.SCHEMA_TYPE: C.SCHEMA_INTEGER, C.SCHEMA_MINIMUM: 0},
        C.EXHAUSTION_INCREASE: {C.SCHEMA_TYPE: C.SCHEMA_INTEGER, C.SCHEMA_MINIMUM: 0},
        C.HEAT_INCREASE: {C.SCHEMA_TYPE: C.SCHEMA_INTEGER, C.SCHEMA_MINIMUM: 0},
        C.WOUNDS: {
            C.SCHEMA_TYPE: C.SCHEMA_ARRAY,
            C.SCHEMA_ITEMS: {
                C.SCHEMA_TYPE: C.SCHEMA_OBJECT,
                C.SCHEMA_PROPERTIES: {
                    C.TARGETED_PART: {C.SCHEMA_TYPE: C.SCHEMA_STRING},
                    C.VALUE: {C.SCHEMA_TYPE: C.SCHEMA_INTEGER, C.SCHEMA_MINIMUM: 1},
                    C.TYPE: {
                        C.SCHEMA_TYPE: C.SCHEMA_STRING,
                        C.SCHEMA_ENUM: [dt.value for dt in C.DamageType] + ["burning"],
                    },
                },
                C.SCHEMA_REQUIRED: [C.TARGETED_PART, C.VALUE],
                C.SCHEMA_ADDITIONAL_PROPERTIES: False,
            },
        },
        C.EFFECTS_ADDED: {C.SCHEMA_TYPE: C.SCHEMA_ARRAY, C.SCHEMA_ITEMS: EffectSchema},
        C.EFFECTS_REMOVED: {C.SCHEMA_TYPE: C.SCHEMA_ARRAY, C.SCHEMA_ITEMS: {C.SCHEMA_TYPE: C.SCHEMA_STRING}},
        C.STATUS_CHANGE: {
            C.SCHEMA_TYPE: C.SCHEMA_STRING,
            C.SCHEMA_ENUM: [status.value for status in C.FighterStatus],
        },
    },
    C.SCHEMA_ADDITIONAL_PROPERTIES: False,
}

JudgeP2Schema = {
    C.SCHEMA_TYPE: C.SCHEMA_OBJECT,
    C.SCHEMA_PROPERTIES: {
        C.NARRATION: {C.SCHEMA_TYPE: C.SCHEMA_STRING},
        C.DELTA: {
            C.SCHEMA_TYPE: C.SCHEMA_OBJECT,
            C.SCHEMA_PATTERN_PROPERTIES: {f"^[{C.FIGHTER_A}{C.FIGHTER_B}]$": DeltaSchema},
            C.SCHEMA_MIN_PROPERTIES: 0,
            C.SCHEMA_MAX_PROPERTIES: 2,
            C.SCHEMA_ADDITIONAL_PROPERTIES: False,
        },
        C.FIGHT_END: {C.SCHEMA_TYPE: C.SCHEMA_BOOLEAN},
        C.WINNER: {C.SCHEMA_TYPE: [C.SCHEMA_STRING, C.SCHEMA_NULL], C.SCHEMA_ENUM: [C.FIGHTER_A, C.FIGHTER_B, None]},
    },
    C.SCHEMA_REQUIRED: [C.NARRATION, C.DELTA, C.FIGHT_END, C.WINNER],
    "allOf": [
        {
            "if": {C.SCHEMA_PROPERTIES: {C.FIGHT_END: {"const": False}}},
            "then": {C.SCHEMA_PROPERTIES: {C.WINNER: {"const": None}}},
        }
    ],
}

# generic validate wrapper ------------------------------------------------


async def guarded_call(func: Callable[[], Any], schema: dict, max_retries: int | None = None) -> Any:
    """Call ``func`` until ``schema`` validates or retries are exhausted."""

    BACKOFF_BASE = 1  # seconds
    last_error = None
    if max_retries is None:
        max_retries = config_mod.CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_MAX_RETRIES, int)

    for attempt in range(max_retries + 1):
        try:
            data = await func()
            validate(data, schema)
            return data
        except (ValidationError, json.JSONDecodeError) as e:
            last_error = e
            if attempt >= max_retries:
                raise RuntimeError(
                    f"Validation/JSON parsing failed after {max_retries + 1} attempts: {last_error}"
                ) from last_error

            logger.warning("guarded_call attempt %s/%s failed: %s", attempt + 1, max_retries + 1, e)
            delay = BACKOFF_BASE * 2**attempt
            logger.debug("Sleeping %.1fs before retry", delay)
            await asyncio.sleep(delay)
    # This part should not be reached if max_retries >= 0, due to the raise in the loop.
    # However, to satisfy linters/type checkers if max_retries could be -1 (though it shouldn't):
    if last_error:
        raise RuntimeError(f"Validation/JSON parsing failed: {last_error}")
    # Fallback if loop somehow finishes without success or error (should not happen with current logic)
    raise RuntimeError("Guarded call failed without specific error after retries.")
