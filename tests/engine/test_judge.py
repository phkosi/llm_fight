import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
import json

from src.judge import judge_phase1, judge_phase2
from src.validation import JudgeP1Schema, JudgeP2Schema # Assuming these are Pydantic models or similar
from src.engine import constants as C

# Mock states and attempts for testing
MOCK_FIGHTER_A_STATE = {C.STATUS: "conscious", C.PAIN: 10}
MOCK_FIGHTER_B_STATE = {C.STATUS: "conscious", C.PAIN: 5}
MOCK_STATE_SUMMARY = {C.FIGHTER_A: MOCK_FIGHTER_A_STATE, C.FIGHTER_B: MOCK_FIGHTER_B_STATE}
MOCK_ATTEMPT_A = "Fighter A throws a punch."
MOCK_ATTEMPT_B = "Fighter B dodges."

@pytest.mark.asyncio
@patch('src.judge.guarded_call') # Patch guarded_call first
@patch('src.judge.chat', new_callable=AsyncMock) # Then patch chat
async def test_judge_phase1_calls_chat_and_guarded_call(mock_chat, mock_guarded_call):
    mock_chat.return_value = [json.dumps({
        "judgement_text": "A assesses the situation.",
        "attempt_A_valid": True,
        "attempt_A_prob": "0.8",
        "attempt_B_valid": True,
        "attempt_B_prob": "0.6",
        "explanation": "Both attempts are plausible."
    })]
    # Mock guarded_call to return the first (and only) parsed chat response
    async def mock_gc_logic(call_func, schema):
        return await call_func()
    mock_guarded_call.side_effect = mock_gc_logic

    await judge_phase1(MOCK_STATE_SUMMARY, MOCK_ATTEMPT_A, MOCK_ATTEMPT_B, recent_log="Turn 1")

    mock_chat.assert_called_once()
    chat_call_args = mock_chat.call_args[0][0]
    assert len(chat_call_args) == 2
    assert chat_call_args[0][C.AGENT_ROLE] == C.AGENT_SYSTEM
    # We can add more specific checks for prompt content if needed

    user_payload = json.loads(chat_call_args[1][C.AGENT_CONTENT])
    assert user_payload[f'fighter_{C.FIGHTER_A}_state_summary'] == MOCK_FIGHTER_A_STATE
    assert user_payload[f'fighter_{C.FIGHTER_B}_state_summary'] == MOCK_FIGHTER_B_STATE
    assert user_payload[f'{C.ATTEMPT}_{C.FIGHTER_A}'] == MOCK_ATTEMPT_A
    assert user_payload[f'{C.ATTEMPT}_{C.FIGHTER_B}'] == MOCK_ATTEMPT_B
    assert user_payload['recent_combat_log'] == "Turn 1"
    
    mock_guarded_call.assert_called_once()
    assert mock_guarded_call.call_args[0][1] == JudgeP1Schema


MOCK_P2_INPUT_STATE = {
    "fighter_A": MOCK_FIGHTER_A_STATE,
    "fighter_B": MOCK_FIGHTER_B_STATE,
    "p1_judgement": {"judgement_text": "A assesses the situation.", "attempt_A_valid": True, "attempt_A_prob": "0.8", "attempt_B_valid": True, "attempt_B_prob": "0.6", "explanation": "Both attempts are plausible."},
    "recent_combat_log": "Turn 1: A and B exchange blows.",
    "combat_log_turns": 1
}
MOCK_ROLLS = {C.FIGHTER_A: True, C.FIGHTER_B: False}

@pytest.mark.asyncio
@patch('src.judge.guarded_call')
@patch('src.judge.chat', new_callable=AsyncMock)
async def test_judge_phase2_calls_chat_and_guarded_call(mock_chat, mock_guarded_call):
    mock_chat.return_value = [json.dumps({
        "narration": "Fighter A lands a solid punch!",
        "delta": {
            "A": {},
            "B": {"pain_increase": 10}
        },
        "fight_end": False,
        "winner": None
    })]
    async def mock_gc_logic(call_func, schema):
        return await call_func()
    mock_guarded_call.side_effect = mock_gc_logic

    await judge_phase2(MOCK_P2_INPUT_STATE, MOCK_ROLLS)

    mock_chat.assert_called_once()
    chat_call_args = mock_chat.call_args[0][0]
    assert len(chat_call_args) == 2
    assert chat_call_args[0][C.AGENT_ROLE] == C.AGENT_SYSTEM

    user_payload = json.loads(chat_call_args[1][C.AGENT_CONTENT])
    assert user_payload[C.PREDICTION] == MOCK_ROLLS
    # Check if other parts of MOCK_P2_INPUT_STATE are present (they are merged)
    assert user_payload["fighter_A"] == MOCK_FIGHTER_A_STATE 

    mock_guarded_call.assert_called_once()
    assert mock_guarded_call.call_args[0][1] == JudgeP2Schema 
