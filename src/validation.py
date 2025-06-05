"""Schema validation and retry helpers using jsonschema."""
import json
from typing import Any, Callable, Dict
from jsonschema import validate, ValidationError

from .config import CONFIG
from .engine import constants as C
from .engine.logger import logger

MAX_RETRIES = CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_MAX_RETRIES, int)

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
        f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": {C.SCHEMA_TYPE: C.SCHEMA_STRING},
        f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": {C.SCHEMA_TYPE: C.SCHEMA_BOOLEAN},
        f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": {C.SCHEMA_TYPE: C.SCHEMA_STRING},
        "explanation": {C.SCHEMA_TYPE: C.SCHEMA_STRING}
    },
    C.SCHEMA_REQUIRED: ["judgement_text", f"{C.ATTEMPT}_{C.FIGHTER_A}_valid", f"{C.ATTEMPT}_{C.FIGHTER_B}_valid"],
    C.SCHEMA_ADDITIONAL_PROPERTIES: True
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
                    C.VALUE: {C.SCHEMA_TYPE: C.SCHEMA_INTEGER},
                    C.TYPE: {C.SCHEMA_TYPE: C.SCHEMA_STRING}
                },
                C.SCHEMA_REQUIRED: [C.TARGETED_PART, C.VALUE]
            }
        },
        C.EFFECTS_ADDED: {C.SCHEMA_TYPE: C.SCHEMA_ARRAY, C.SCHEMA_ITEMS: {C.SCHEMA_TYPE: C.SCHEMA_OBJECT}},
        C.EFFECTS_REMOVED: {C.SCHEMA_TYPE: C.SCHEMA_ARRAY, C.SCHEMA_ITEMS: {C.SCHEMA_TYPE: C.SCHEMA_STRING}},
        C.STATUS_CHANGE: {C.SCHEMA_TYPE: C.SCHEMA_STRING, C.SCHEMA_ENUM: [C.STATUS_FIGHTING, C.STATUS_UNCONSCIOUS, C.STATUS_DEAD]},
    },
    C.SCHEMA_ADDITIONAL_PROPERTIES: False
}

JudgeP2Schema = {
    C.SCHEMA_TYPE: C.SCHEMA_OBJECT,
    C.SCHEMA_PROPERTIES: {
        C.NARRATION: {C.SCHEMA_TYPE: C.SCHEMA_STRING},
        C.DELTA: {
            C.SCHEMA_TYPE: C.SCHEMA_OBJECT,
            C.SCHEMA_PATTERN_PROPERTIES: {
                f"^[{C.FIGHTER_A}{C.FIGHTER_B}]$": DeltaSchema
            },
            C.SCHEMA_MIN_PROPERTIES: 0,
            C.SCHEMA_MAX_PROPERTIES: 2,
            C.SCHEMA_ADDITIONAL_PROPERTIES: False
        },
        C.FIGHT_END: {C.SCHEMA_TYPE: C.SCHEMA_BOOLEAN},
        C.WINNER: {C.SCHEMA_TYPE: [C.SCHEMA_STRING, C.SCHEMA_NULL], C.SCHEMA_ENUM: [C.FIGHTER_A, C.FIGHTER_B, None]}
    },
    C.SCHEMA_REQUIRED: [C.NARRATION, C.DELTA, C.FIGHT_END]
}

# generic validate wrapper ------------------------------------------------

async def guarded_call(func: Callable[[], Any], schema: dict) -> Any:
    """Call func() async until schema validates or retries exhausted."""
    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            data = await func() # Await func() as it's an async callable (e.g. _call in judge.py)
            validate(data, schema)
            return data
        except (ValidationError, json.JSONDecodeError) as e: # Catch JSONDecodeError here too
            last_error = e
            if attempt >= MAX_RETRIES:
                # After all retries, raise the last encountered error
                raise RuntimeError(f"Validation/JSON parsing failed after {MAX_RETRIES + 1} attempts: {last_error}") from last_error
            # Optionally log the error for this attempt before retrying
            logger.debug(f"Attempt {attempt + 1} failed during guarded_call: {e}. Retrying...")
    # This part should not be reached if MAX_RETRIES >= 0, due to the raise in the loop.
    # However, to satisfy linters/type checkers if MAX_RETRIES could be -1 (though it shouldn't):
    if last_error:
        raise RuntimeError(f"Validation/JSON parsing failed: {last_error}")
    # Fallback if loop somehow finishes without success or error (should not happen with current logic)
    raise RuntimeError("Guarded call failed without specific error after retries.")
