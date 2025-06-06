import pytest
import json
from jsonschema import ValidationError, validate
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

from src.judge import judge_phase1, judge_phase2

from src.validation import guarded_call, ActionSchema, JudgeP1Schema, JudgeP2Schema, DeltaSchema
from src.engine import constants as C


# --- Mocks for guarded_call tests ---
class MockAsyncCallable:
    def __init__(self, return_values: List[Any], errors: List[Exception | None] = None):
        self.call_count = 0
        self.return_values = return_values
        self.errors = errors if errors else [None] * len(return_values)

    async def __call__(self) -> Any:
        current_call = self.call_count
        self.call_count += 1

        if current_call < len(self.errors) and self.errors[current_call]:
            raise self.errors[current_call]

        if current_call < len(self.return_values):
            return self.return_values[current_call]
        raise RuntimeError("MockAsyncCallable called too many times")


# --- guarded_call tests ---
@pytest.mark.asyncio
async def test_guarded_call_success_first_try():
    schema = {
        C.SCHEMA_TYPE: C.SCHEMA_OBJECT,
        C.SCHEMA_PROPERTIES: {"key": {C.SCHEMA_TYPE: C.SCHEMA_STRING}},
        C.SCHEMA_REQUIRED: ["key"],
    }
    valid_data = {"key": "value"}
    mock_func = MockAsyncCallable(return_values=[valid_data])

    result = await guarded_call(mock_func, schema)
    assert result == valid_data
    assert mock_func.call_count == 1


@pytest.mark.asyncio
async def test_guarded_call_retry_on_validation_error_then_success():
    schema = {
        C.SCHEMA_TYPE: C.SCHEMA_OBJECT,
        C.SCHEMA_PROPERTIES: {"key": {C.SCHEMA_TYPE: C.SCHEMA_STRING}},
        C.SCHEMA_REQUIRED: ["key"],
    }
    invalid_data = {"wrong_key": "value"}
    valid_data = {"key": "value"}
    # First call raises ValidationError (implicitly, as data won't validate), second returns valid data.
    # We simulate this by having the mock function return data that won't validate against the schema.
    # The actual ValidationError is raised by jsonschema.validate inside guarded_call.
    mock_func = MockAsyncCallable(return_values=[invalid_data, valid_data])

    result = await guarded_call(mock_func, schema)
    assert result == valid_data
    assert mock_func.call_count == 2  # Retried once


@pytest.mark.asyncio
async def test_guarded_call_retry_on_json_decode_error_then_success():
    schema = {
        C.SCHEMA_TYPE: C.SCHEMA_OBJECT,
        C.SCHEMA_PROPERTIES: {"key": {C.SCHEMA_TYPE: C.SCHEMA_STRING}},
        C.SCHEMA_REQUIRED: ["key"],
    }
    valid_data = {"key": "value"}
    # First call will raise json.JSONDecodeError, second returns valid data.
    mock_func = MockAsyncCallable(
        return_values=[None, valid_data],  # Return value for error attempt doesn't matter
        errors=[json.JSONDecodeError("msg", "doc", 0), None],
    )

    result = await guarded_call(mock_func, schema)
    assert result == valid_data
    assert mock_func.call_count == 2


@pytest.mark.asyncio
async def test_guarded_call_exponential_backoff(monkeypatch):
    monkeypatch.setattr("src.validation.MAX_RETRIES", 2)
    sleep_calls: List[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr("src.validation.asyncio.sleep", fake_sleep)

    schema = {
        C.SCHEMA_TYPE: C.SCHEMA_OBJECT,
        C.SCHEMA_PROPERTIES: {"key": {C.SCHEMA_TYPE: C.SCHEMA_STRING}},
        C.SCHEMA_REQUIRED: ["key"],
    }
    invalid = {"wrong": 1}
    valid = {"key": "ok"}
    mock_func = MockAsyncCallable(return_values=[invalid, invalid, valid])

    result = await guarded_call(mock_func, schema)
    assert result == valid
    assert sleep_calls == [1, 2]


@pytest.mark.asyncio
async def test_guarded_call_fail_after_max_retries_validation_error(monkeypatch):
    # Reduce MAX_RETRIES for this test for speed
    monkeypatch.setattr("src.validation.MAX_RETRIES", 1)
    schema = {
        C.SCHEMA_TYPE: C.SCHEMA_OBJECT,
        C.SCHEMA_PROPERTIES: {"key": {C.SCHEMA_TYPE: C.SCHEMA_STRING}},
        C.SCHEMA_REQUIRED: ["key"],
    }
    invalid_data1 = {"wrong1": "value"}
    invalid_data2 = {"wrong2": "value"}  # Ensure it keeps failing
    mock_func = MockAsyncCallable(return_values=[invalid_data1, invalid_data2])

    with pytest.raises(RuntimeError, match="Validation/JSON parsing failed after 2 attempts"):
        await guarded_call(mock_func, schema)
    assert mock_func.call_count == 2  # Initial call + 1 retry


@pytest.mark.asyncio
async def test_guarded_call_fail_after_max_retries_json_decode_error(monkeypatch):
    monkeypatch.setattr("src.validation.MAX_RETRIES", 1)
    schema = {
        C.SCHEMA_TYPE: C.SCHEMA_OBJECT,
        C.SCHEMA_PROPERTIES: {"key": {C.SCHEMA_TYPE: C.SCHEMA_STRING}},
        C.SCHEMA_REQUIRED: ["key"],
    }
    mock_func = MockAsyncCallable(
        return_values=[None, None],
        errors=[json.JSONDecodeError("msg1", "doc", 0), json.JSONDecodeError("msg2", "doc", 0)],
    )

    with pytest.raises(RuntimeError, match="Validation/JSON parsing failed after 2 attempts"):
        await guarded_call(mock_func, schema)
    assert mock_func.call_count == 2


# --- Schema tests ---


# Helper function to test schema validation
def _validate_against_schema(data: Any, schema: Dict[str, Any], should_be_valid: bool):
    if should_be_valid:
        try:
            validate(instance=data, schema=schema)
        except ValidationError as e:
            pytest.fail(f"Data should be valid but failed validation: {e}\nData: {data}")
    else:
        with pytest.raises(ValidationError):
            validate(instance=data, schema=schema)


# --- ActionSchema Tests ---
def test_action_schema_valid():
    valid_data = {C.VALIDATION_PROB: 0.75, C.VALIDATION_PREDICTED: "Fighter attempts a feint."}
    _validate_against_schema(valid_data, ActionSchema, True)


def test_action_schema_invalid_missing_field():
    invalid_data = {C.VALIDATION_PREDICTED: "Action details"}  # Missing prob
    _validate_against_schema(invalid_data, ActionSchema, False)


def test_action_schema_invalid_type():
    invalid_data = {C.VALIDATION_PROB: "0.5", C.VALIDATION_PREDICTED: "Text"}  # prob should be number
    _validate_against_schema(invalid_data, ActionSchema, False)


# --- JudgeP1Schema Tests ---
def test_judge_p1_schema_valid():
    valid_data = {
        "judgement_text": "Both fighters engage!",
        f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
        f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "0.8",
        f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": False,
        f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.1",
        "explanation": "Fighter B slipped.",
    }
    _validate_against_schema(valid_data, JudgeP1Schema, True)


def test_judge_p1_schema_valid_no_explanation():  # Explanation is optional
    valid_data = {
        "judgement_text": "A engages, B hesitates.",
        f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
        f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "0.9",
        f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
        f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.3",
    }
    _validate_against_schema(valid_data, JudgeP1Schema, True)


def test_judge_p1_schema_valid_missing_attempt_fields():
    valid_data = {"judgement_text": "Just a summary."}
    _validate_against_schema(valid_data, JudgeP1Schema, True)


def test_judge_p1_schema_invalid_missing_required():
    invalid_data = {  # Missing judgement_text
        f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
        f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "0.8",
        f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": False,
        f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.1",
    }
    _validate_against_schema(invalid_data, JudgeP1Schema, False)


def test_judge_p1_schema_invalid_type():
    invalid_data = {
        "judgement_text": "Engage!",
        f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": "yes",  # Should be boolean
        f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "0.8",
        f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": False,
        f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.1",
    }
    _validate_against_schema(invalid_data, JudgeP1Schema, False)


# --- DeltaSchema Tests ---
def test_delta_schema_valid_full():
    valid_data = {
        C.PAIN_INCREASE: 10,
        C.EXHAUSTION_INCREASE: 5,
        C.HEAT_INCREASE: 3,
        C.WOUNDS: [
            {C.TARGETED_PART: "torso", C.VALUE: 15, C.TYPE: "piercing"},
            {C.TARGETED_PART: "left_arm", C.VALUE: 8, C.TYPE: "slashing"},
        ],
        C.EFFECTS_ADDED: [
            {
                C.NAME: "burning",
                C.VALUE: 1.0,
                C.EFFECT_TTL: 3,
                C.EFFECT_ON_APPLY: "Starts burning",
                C.EFFECT_ON_TICK: "Takes fire damage",
                C.TYPE: C.DEBUFFS,  # For determining which list in FighterState
            }
        ],
        C.EFFECTS_REMOVED: ["stunned"],
        C.STATUS_CHANGE: C.FighterStatus.UNCONSCIOUS,
    }
    _validate_against_schema(valid_data, DeltaSchema, True)


def test_delta_schema_valid_minimal():
    valid_data = {C.PAIN_INCREASE: 1}  # Only one field
    _validate_against_schema(valid_data, DeltaSchema, True)
    valid_data_empty = {}  # Empty delta is also valid
    _validate_against_schema(valid_data_empty, DeltaSchema, True)


def test_delta_schema_valid_blank_status_change():
    valid_data = {C.STATUS_CHANGE: ""}
    _validate_against_schema(valid_data, DeltaSchema, True)


def test_delta_schema_invalid_pain_type():
    invalid_data = {C.PAIN_INCREASE: "high"}  # Should be integer
    _validate_against_schema(invalid_data, DeltaSchema, False)


def test_delta_schema_invalid_pain_value():
    invalid_data = {C.PAIN_INCREASE: -5}  # Should be non-negative
    _validate_against_schema(invalid_data, DeltaSchema, False)


def test_delta_schema_invalid_wound_missing_field():
    invalid_data = {C.WOUNDS: [{C.TARGETED_PART: "head", C.TYPE: C.DamageType.PIERCING}]}  # Missing value
    _validate_against_schema(invalid_data, DeltaSchema, False)


def test_delta_schema_invalid_status_change_enum():
    invalid_data = {C.STATUS_CHANGE: "confused"}  # Not in enum
    _validate_against_schema(invalid_data, DeltaSchema, False)


def test_delta_schema_invalid_additional_property():
    # DeltaSchema has additionalProperties: False
    invalid_data = {"mood_change": "angry"}
    _validate_against_schema(invalid_data, DeltaSchema, False)


def test_delta_schema_damage_types_match_constants():
    enum_list = DeltaSchema[C.SCHEMA_PROPERTIES][C.WOUNDS][C.SCHEMA_ITEMS][C.SCHEMA_PROPERTIES][C.TYPE][C.SCHEMA_ENUM]
    assert set(enum_list) == {dt.value for dt in C.DamageType}


# --- JudgeP2Schema Tests ---
def test_judge_p2_schema_valid():
    valid_data = {
        C.NARRATION: "The fighters trade blows, A lands a solid hit!",
        C.DELTA: {
            C.FIGHTER_A: {C.PAIN_INCREASE: 5},
            C.FIGHTER_B: {C.WOUNDS: [{C.TARGETED_PART: "leg", C.VALUE: 10, C.TYPE: C.DamageType.SLASHING}]},
        },
        C.FIGHT_END: False,
        C.WINNER: None,
    }
    _validate_against_schema(valid_data, JudgeP2Schema, True)


def test_judge_p2_schema_valid_fight_ends():
    valid_data = {
        C.NARRATION: "B collapses, A is victorious!",
        C.DELTA: {C.FIGHTER_B: {C.STATUS_CHANGE: C.FighterStatus.UNCONSCIOUS}},
        C.FIGHT_END: True,
        C.WINNER: C.FIGHTER_A,
    }
    _validate_against_schema(valid_data, JudgeP2Schema, True)


def test_judge_p2_schema_valid_empty_delta():
    valid_data = {C.NARRATION: "They circle each other warily.", C.DELTA: {}, C.FIGHT_END: False, C.WINNER: None}
    _validate_against_schema(valid_data, JudgeP2Schema, True)


def test_judge_p2_schema_invalid_missing_narration():
    invalid_data = {C.DELTA: {}, C.FIGHT_END: False, C.WINNER: None}  # Missing narration
    _validate_against_schema(invalid_data, JudgeP2Schema, False)


def test_judge_p2_schema_invalid_winner_enum():
    invalid_data = {
        C.NARRATION: "The fight ends strangely.",
        C.DELTA: {},
        C.FIGHT_END: True,
        C.WINNER: "C",  # Not A, B, or None
    }
    _validate_against_schema(invalid_data, JudgeP2Schema, False)


def test_judge_p2_schema_invalid_delta_fighter_key():
    invalid_data = {
        C.NARRATION: "A attacks.",
        C.DELTA: {"FighterC": {C.PAIN_INCREASE: 1}},  # Invalid fighter key
        C.FIGHT_END: False,
        C.WINNER: None,
    }
    _validate_against_schema(invalid_data, JudgeP2Schema, False)


@pytest.mark.asyncio
async def test_guarded_call_negative_max_retries(monkeypatch):
    monkeypatch.setattr("src.validation.MAX_RETRIES", -1)

    async def dummy():
        return {"key": "val"}

    with pytest.raises(RuntimeError, match="Guarded call failed without specific error"):
        await guarded_call(dummy, {"type": "object"})


@pytest.mark.asyncio
@patch("src.judge.guarded_call")
@patch("src.judge.chat", new_callable=AsyncMock)
async def test_judge_phase1_passes_schema_to_chat(mock_chat, mock_guarded_call):
    mock_chat.return_value = [json.dumps({"judgement_text": "ok"})]

    async def passthrough(func, schema):
        return await func()

    mock_guarded_call.side_effect = passthrough
    state = {C.FIGHTER_A: {}, C.FIGHTER_B: {}}
    await judge_phase1(state, "a", "b")

    assert mock_chat.call_args.kwargs["schema"] == JudgeP1Schema


@pytest.mark.asyncio
@patch("src.judge.guarded_call")
@patch("src.judge.chat", new_callable=AsyncMock)
async def test_judge_phase2_passes_schema_to_chat(mock_chat, mock_guarded_call):
    mock_chat.return_value = [json.dumps({"narration": "", "delta": {}, "fight_end": False, "winner": None})]

    async def passthrough(func, schema):
        return await func()

    mock_guarded_call.side_effect = passthrough
    p2_input = {"recent_combat_log": "", "combat_log_turns": 0}
    rolls = {C.FIGHTER_A: True, C.FIGHTER_B: False}
    await judge_phase2(p2_input, rolls)

    assert mock_chat.call_args.kwargs["schema"] == JudgeP2Schema
