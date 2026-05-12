"""Schema validation and retry helpers using jsonschema."""

import asyncio
import json
from collections.abc import Callable
from copy import deepcopy
from typing import Any, cast

from jsonschema import ValidationError, validate

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
JudgeP1Schema: dict[str, Any] = {
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

EffectTagSchema = {
    C.SCHEMA_TYPE: C.SCHEMA_STRING,
    C.SCHEMA_MIN_LENGTH: 1,
    C.SCHEMA_MAX_LENGTH: C.EFFECT_TAG_MAX_LENGTH,
    C.SCHEMA_PATTERN: C.EFFECT_SAFE_NAME_PATTERN,
}

EffectMechanicValueSchema = {
    C.SCHEMA_TYPE: C.SCHEMA_INTEGER,
    C.SCHEMA_MINIMUM: 1,
    C.SCHEMA_MAXIMUM: C.EFFECT_MECHANIC_MAX_VALUE,
}

EffectMechanicSchema = {
    C.SCHEMA_ONE_OF: [
        {
            C.SCHEMA_TYPE: C.SCHEMA_OBJECT,
            C.SCHEMA_PROPERTIES: {
                C.EFFECT_MECHANIC_KIND: {C.SCHEMA_CONST: C.EFFECT_MECHANIC_STAT_TICK},
                C.EFFECT_MECHANIC_STAT: {
                    C.SCHEMA_TYPE: C.SCHEMA_STRING,
                    C.SCHEMA_ENUM: [C.PAIN, C.EXHAUSTION, C.HEAT],
                },
                C.VALUE: EffectMechanicValueSchema,
            },
            C.SCHEMA_REQUIRED: [C.EFFECT_MECHANIC_KIND, C.EFFECT_MECHANIC_STAT, C.VALUE],
            C.SCHEMA_ADDITIONAL_PROPERTIES: False,
        },
        {
            C.SCHEMA_TYPE: C.SCHEMA_OBJECT,
            C.SCHEMA_PROPERTIES: {
                C.EFFECT_MECHANIC_KIND: {C.SCHEMA_CONST: C.EFFECT_MECHANIC_DAMAGE_TICK},
                C.TARGETED_PART: {
                    C.SCHEMA_TYPE: C.SCHEMA_STRING,
                    C.SCHEMA_MIN_LENGTH: 1,
                    C.SCHEMA_MAX_LENGTH: C.EFFECT_METADATA_VALUE_MAX_LENGTH,
                    C.SCHEMA_PATTERN: C.EFFECT_SAFE_NAME_PATTERN,
                },
                C.VALUE: EffectMechanicValueSchema,
                C.TYPE: {
                    C.SCHEMA_TYPE: C.SCHEMA_STRING,
                    C.SCHEMA_ENUM: [dt.value for dt in C.DamageType],
                },
            },
            C.SCHEMA_REQUIRED: [C.EFFECT_MECHANIC_KIND, C.TARGETED_PART, C.VALUE],
            C.SCHEMA_ADDITIONAL_PROPERTIES: False,
        },
        {
            C.SCHEMA_TYPE: C.SCHEMA_OBJECT,
            C.SCHEMA_PROPERTIES: {
                C.EFFECT_MECHANIC_KIND: {C.SCHEMA_CONST: C.EFFECT_MECHANIC_TARGETING_MODIFIER},
                C.EFFECT_MECHANIC_MODIFIER: {
                    C.SCHEMA_TYPE: C.SCHEMA_STRING,
                    C.SCHEMA_ENUM: [C.EFFECT_MECHANIC_OUTGOING_ACCURACY_PENALTY],
                },
                C.VALUE: EffectMechanicValueSchema,
            },
            C.SCHEMA_REQUIRED: [C.EFFECT_MECHANIC_KIND, C.EFFECT_MECHANIC_MODIFIER, C.VALUE],
            C.SCHEMA_ADDITIONAL_PROPERTIES: False,
        },
        {
            C.SCHEMA_TYPE: C.SCHEMA_OBJECT,
            C.SCHEMA_PROPERTIES: {
                C.EFFECT_MECHANIC_KIND: {C.SCHEMA_CONST: C.EFFECT_MECHANIC_ACTION_MODIFIER},
                C.EFFECT_MECHANIC_MODIFIER: {
                    C.SCHEMA_TYPE: C.SCHEMA_STRING,
                    C.SCHEMA_ENUM: [C.EFFECT_MECHANIC_ACTION_BLOCK],
                },
                C.VALUE: EffectMechanicValueSchema,
            },
            C.SCHEMA_REQUIRED: [C.EFFECT_MECHANIC_KIND, C.EFFECT_MECHANIC_MODIFIER],
            C.SCHEMA_ADDITIONAL_PROPERTIES: False,
        },
    ]
}

ProfileIdentifierSchema = {
    C.SCHEMA_TYPE: C.SCHEMA_STRING,
    C.SCHEMA_MIN_LENGTH: 1,
    C.SCHEMA_MAX_LENGTH: C.EFFECT_METADATA_VALUE_MAX_LENGTH,
    C.SCHEMA_PATTERN: C.EFFECT_SAFE_NAME_PATTERN,
}

TissueLayerSchema = {
    C.SCHEMA_TYPE: C.SCHEMA_OBJECT,
    C.SCHEMA_PROPERTIES: {
        C.NAME: ProfileIdentifierSchema,
        C.MAX_HP: {
            C.SCHEMA_TYPE: C.SCHEMA_INTEGER,
            C.SCHEMA_MINIMUM: 1,
            C.SCHEMA_MAXIMUM: 500,
        },
    },
    C.SCHEMA_REQUIRED: [C.NAME, C.MAX_HP],
    C.SCHEMA_ADDITIONAL_PROPERTIES: False,
}

BodyPartSchema = {
    C.SCHEMA_TYPE: C.SCHEMA_OBJECT,
    C.SCHEMA_PROPERTIES: {
        "id": ProfileIdentifierSchema,
        C.NAME: ProfileIdentifierSchema,
        "layers": {
            C.SCHEMA_TYPE: C.SCHEMA_ARRAY,
            C.SCHEMA_ITEMS: TissueLayerSchema,
            C.SCHEMA_MIN_ITEMS: 1,
            C.SCHEMA_MAX_ITEMS: 8,
        },
        "is_vital": {C.SCHEMA_TYPE: C.SCHEMA_BOOLEAN},
        "can_be_severed": {C.SCHEMA_TYPE: C.SCHEMA_BOOLEAN},
        C.BLEED_RATE: {
            C.SCHEMA_TYPE: C.SCHEMA_INTEGER,
            C.SCHEMA_MINIMUM: 0,
            C.SCHEMA_MAXIMUM: 50,
        },
        C.BURN_RATE: {
            C.SCHEMA_TYPE: C.SCHEMA_INTEGER,
            C.SCHEMA_MINIMUM: 0,
            C.SCHEMA_MAXIMUM: 50,
        },
        C.CONSEQUENCE_TAGS: {
            C.SCHEMA_TYPE: C.SCHEMA_ARRAY,
            C.SCHEMA_ITEMS: {
                C.SCHEMA_TYPE: C.SCHEMA_STRING,
                C.SCHEMA_ENUM: list(C.CONSEQUENCE_ALLOWED_TAGS),
            },
            C.SCHEMA_UNIQUE_ITEMS: True,
            C.SCHEMA_MAX_ITEMS: len(C.CONSEQUENCE_ALLOWED_TAGS),
        },
        C.CONSEQUENCE_GROUP: ProfileIdentifierSchema,
    },
    C.SCHEMA_REQUIRED: ["id", "layers"],
    C.SCHEMA_ADDITIONAL_PROPERTIES: False,
}

FighterProfileSchema = {
    C.SCHEMA_TYPE: C.SCHEMA_OBJECT,
    C.SCHEMA_PROPERTIES: {
        C.CONFIG_FIGHTER_CLASS: EffectTextSchema,
        C.THEME: ProfileIdentifierSchema,
        C.LOADOUT: EffectTextSchema,
        "environment": EffectTextSchema,
        C.BODY_PARTS: {
            C.SCHEMA_TYPE: C.SCHEMA_ARRAY,
            C.SCHEMA_ITEMS: BodyPartSchema,
            C.SCHEMA_MIN_ITEMS: 1,
            C.SCHEMA_MAX_ITEMS: 32,
        },
        C.ANATOMY: {
            C.SCHEMA_TYPE: C.SCHEMA_ARRAY,
            C.SCHEMA_ITEMS: BodyPartSchema,
            C.SCHEMA_MIN_ITEMS: 1,
            C.SCHEMA_MAX_ITEMS: 32,
        },
    },
    C.SCHEMA_ONE_OF: [
        {C.SCHEMA_REQUIRED: [C.BODY_PARTS], C.SCHEMA_NOT: {C.SCHEMA_REQUIRED: [C.ANATOMY]}},
        {C.SCHEMA_REQUIRED: [C.ANATOMY], C.SCHEMA_NOT: {C.SCHEMA_REQUIRED: [C.BODY_PARTS]}},
    ],
    C.SCHEMA_ADDITIONAL_PROPERTIES: False,
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
        C.EFFECT_MECHANICS: {
            C.SCHEMA_TYPE: C.SCHEMA_ARRAY,
            C.SCHEMA_ITEMS: EffectMechanicSchema,
            C.SCHEMA_MAX_ITEMS: 8,
        },
        C.EFFECT_TAGS: {
            C.SCHEMA_TYPE: C.SCHEMA_ARRAY,
            C.SCHEMA_ITEMS: EffectTagSchema,
            C.SCHEMA_MAX_ITEMS: 8,
        },
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

SourceSchema = {C.SCHEMA_TYPE: C.SCHEMA_STRING, C.SCHEMA_ENUM: [C.FIGHTER_A, C.FIGHTER_B]}

SourceIntChangeSchema = {
    C.SCHEMA_TYPE: C.SCHEMA_OBJECT,
    C.SCHEMA_PROPERTIES: {
        C.SOURCE: SourceSchema,
        C.VALUE: {C.SCHEMA_TYPE: C.SCHEMA_INTEGER, C.SCHEMA_MINIMUM: 0},
    },
    C.SCHEMA_REQUIRED: [C.SOURCE, C.VALUE],
    C.SCHEMA_ADDITIONAL_PROPERTIES: False,
}

SourceStatusChangeSchema = {
    C.SCHEMA_TYPE: C.SCHEMA_OBJECT,
    C.SCHEMA_PROPERTIES: {
        C.SOURCE: SourceSchema,
        C.VALUE: {
            C.SCHEMA_TYPE: C.SCHEMA_STRING,
            C.SCHEMA_ENUM: [status.value for status in C.FighterStatus],
        },
    },
    C.SCHEMA_REQUIRED: [C.SOURCE, C.VALUE],
    C.SCHEMA_ADDITIONAL_PROPERTIES: False,
}

SourceWoundSchema = {
    C.SCHEMA_TYPE: C.SCHEMA_OBJECT,
    C.SCHEMA_PROPERTIES: {
        C.SOURCE: SourceSchema,
        C.TARGETED_PART: {C.SCHEMA_TYPE: C.SCHEMA_STRING},
        C.VALUE: {C.SCHEMA_TYPE: C.SCHEMA_INTEGER, C.SCHEMA_MINIMUM: 1},
        C.TYPE: {
            C.SCHEMA_TYPE: C.SCHEMA_STRING,
            C.SCHEMA_ENUM: [dt.value for dt in C.DamageType] + ["burning"],
        },
    },
    C.SCHEMA_REQUIRED: [C.SOURCE, C.TARGETED_PART, C.VALUE],
    C.SCHEMA_ADDITIONAL_PROPERTIES: False,
}

SourceEffectSchema = deepcopy(EffectSchema)
_source_effect_properties = cast(dict[str, Any], SourceEffectSchema[C.SCHEMA_PROPERTIES])
_source_effect_required = cast(list[str], SourceEffectSchema[C.SCHEMA_REQUIRED])
SourceEffectSchema[C.SCHEMA_PROPERTIES] = {
    C.SOURCE: SourceSchema,
    **_source_effect_properties,
}
SourceEffectSchema[C.SCHEMA_REQUIRED] = [C.SOURCE, *_source_effect_required]

SourceEffectRemovalSchema = {
    C.SCHEMA_TYPE: C.SCHEMA_OBJECT,
    C.SCHEMA_PROPERTIES: {
        C.SOURCE: SourceSchema,
        C.NAME: {
            C.SCHEMA_TYPE: C.SCHEMA_STRING,
            C.SCHEMA_MIN_LENGTH: 1,
            C.SCHEMA_MAX_LENGTH: C.EFFECT_NAME_MAX_LENGTH,
            C.SCHEMA_PATTERN: C.EFFECT_SAFE_NAME_PATTERN,
        },
        C.TYPE: {C.SCHEMA_TYPE: C.SCHEMA_STRING, C.SCHEMA_ENUM: [C.BUFFS, C.DEBUFFS]},
        C.TARGETED_PART: {
            C.SCHEMA_TYPE: C.SCHEMA_STRING,
            C.SCHEMA_MIN_LENGTH: 1,
            C.SCHEMA_MAX_LENGTH: C.EFFECT_METADATA_VALUE_MAX_LENGTH,
            C.SCHEMA_PATTERN: C.EFFECT_SAFE_NAME_PATTERN,
        },
    },
    C.SCHEMA_REQUIRED: [C.SOURCE, C.NAME],
    C.SCHEMA_ADDITIONAL_PROPERTIES: False,
}

DeltaSchema = {
    C.SCHEMA_TYPE: C.SCHEMA_OBJECT,
    C.SCHEMA_PROPERTIES: {
        C.PAIN_INCREASE: SourceIntChangeSchema,
        C.EXHAUSTION_INCREASE: SourceIntChangeSchema,
        C.HEAT_INCREASE: SourceIntChangeSchema,
        C.WOUNDS: {C.SCHEMA_TYPE: C.SCHEMA_ARRAY, C.SCHEMA_ITEMS: SourceWoundSchema},
        C.EFFECTS_ADDED: {C.SCHEMA_TYPE: C.SCHEMA_ARRAY, C.SCHEMA_ITEMS: SourceEffectSchema},
        C.EFFECTS_REMOVED: {C.SCHEMA_TYPE: C.SCHEMA_ARRAY, C.SCHEMA_ITEMS: SourceEffectRemovalSchema},
        C.STATUS_CHANGE: SourceStatusChangeSchema,
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
