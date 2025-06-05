"""Schema validation and retry helpers using jsonschema."""

import json
import asyncio
from typing import Any, Callable, Dict, Type
from jsonschema import validate, ValidationError as JSONSchemaValidationError
from pydantic import BaseModel, ConfigDict, ValidationError as PydanticValidationError, Field, field_validator

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


class JudgeP1Model(BaseModel):
    """Pydantic model for Judge phase‑1 output."""

    judgement_text: str
    attempt_A_valid: bool | None = Field(default=None, strict=True)
    attempt_A_prob: str | None = None
    attempt_B_valid: bool | None = Field(default=None, strict=True)
    attempt_B_prob: str | None = None
    explanation: str | None = None

    model_config = ConfigDict(extra="allow")


class WoundModel(BaseModel):
    targeted_part: str
    value: int = Field(ge=0)
    type: C.DamageType | None = None

    model_config = ConfigDict(extra="ignore")


class DeltaModel(BaseModel):
    pain_increase: int | None = Field(default=None, ge=0)
    exhaustion_increase: int | None = Field(default=None, ge=0)
    heat_increase: int | None = Field(default=None, ge=0)
    wounds: list[WoundModel] | None = None
    effects_added: list[dict] | None = None
    effects_removed: list[str] | None = None
    status_change: C.FighterStatus | None = None

    model_config = ConfigDict(extra="forbid")


class JudgeP2Model(BaseModel):
    narration: str
    delta: Dict[str, DeltaModel]
    fight_end: bool
    winner: str | None = Field(default=None)

    @field_validator("delta")
    @classmethod
    def _check_delta_keys(cls, v: Dict[str, DeltaModel]) -> Dict[str, DeltaModel]:
        for key in v:
            if key not in {C.FIGHTER_A, C.FIGHTER_B}:
                raise ValueError("delta keys must be 'A' or 'B'")
        return v

    @field_validator("winner")
    @classmethod
    def _check_winner(cls, v: str | None) -> str | None:
        if v is not None and v not in {C.FIGHTER_A, C.FIGHTER_B}:
            raise ValueError("winner must be 'A', 'B', or null")
        return v

    model_config = ConfigDict(extra="forbid")


# generic validate wrapper ------------------------------------------------


async def guarded_call(func: Callable[[], Any], schema: dict | Type[BaseModel]) -> Any:
    """Call ``func`` until ``schema``/``model`` validates or retries are exhausted."""

    BACKOFF_BASE = 1  # seconds
    last_error = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            data = await func()
            if isinstance(schema, dict):
                validate(data, schema)
                return data
            else:
                json_str = data if isinstance(data, str) else json.dumps(data)
                return schema.model_validate_json(json_str)
        except (JSONSchemaValidationError, PydanticValidationError, json.JSONDecodeError) as e:
            last_error = e
            if attempt >= MAX_RETRIES:
                raise RuntimeError(
                    f"Validation/JSON parsing failed after {MAX_RETRIES + 1} attempts: {last_error}"
                ) from last_error

            logger.warning("guarded_call attempt %s/%s failed: %s", attempt + 1, MAX_RETRIES + 1, e)
            delay = BACKOFF_BASE * 2**attempt
            logger.debug("Sleeping %.1fs before retry", delay)
            await asyncio.sleep(delay)
    # This part should not be reached if MAX_RETRIES >= 0, due to the raise in the loop.
    # However, to satisfy linters/type checkers if MAX_RETRIES could be -1 (though it shouldn't):
    if last_error:
        raise RuntimeError(f"Validation/JSON parsing failed: {last_error}")
    # Fallback if loop somehow finishes without success or error (should not happen with current logic)
    raise RuntimeError("Guarded call failed without specific error after retries.")
