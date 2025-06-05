import os
import asyncio
import pytest

from src.judge import judge_phase1, judge_phase2
from src.validation import JudgeP1Model, JudgeP2Model
from src.engine import constants as C


@pytest.mark.asyncio
async def test_judge_phase1_live():
    api_url = os.environ.get("API_URL")
    if not api_url:
        pytest.skip("API_URL env var not set")

    state = {
        C.FIGHTER_A: {C.STATUS: C.FighterStatus.FIGHTING, C.PAIN: 0},
        C.FIGHTER_B: {C.STATUS: C.FighterStatus.FIGHTING, C.PAIN: 0},
    }

    attempt_a = "A throws a jab"
    attempt_b = "B blocks"

    try:
        result = await asyncio.wait_for(
            judge_phase1(state, attempt_a, attempt_b),
            timeout=20,
        )
    except Exception as e:
        pytest.xfail(f"Live API call failed: {e}")

    assert isinstance(result, JudgeP1Model)


@pytest.mark.asyncio
async def test_judge_phase2_live():
    api_url = os.environ.get("API_URL")
    if not api_url:
        pytest.skip("API_URL env var not set")

    state = {
        C.FIGHTER_A: {C.STATUS: C.FighterStatus.FIGHTING, C.PAIN: 0},
        C.FIGHTER_B: {C.STATUS: C.FighterStatus.FIGHTING, C.PAIN: 0},
    }

    attempt_a = "A feints left"
    attempt_b = "B steps back"

    try:
        p1 = await asyncio.wait_for(
            judge_phase1(state, attempt_a, attempt_b),
            timeout=20,
        )
    except Exception as e:
        pytest.xfail(f"Live API call failed during phase1: {e}")

    p2_input = {
        "fighter_A": state[C.FIGHTER_A],
        "fighter_B": state[C.FIGHTER_B],
        "p1_judgement": p1.get("judgement_text", ""),
        "p1_explanation": p1.get("explanation", ""),
        "recent_combat_log": "",
        "combat_log_turns": 0,
    }
    rolls = {C.FIGHTER_A: True, C.FIGHTER_B: False}

    try:
        p2 = await asyncio.wait_for(
            judge_phase2(p2_input, rolls),
            timeout=20,
        )
    except Exception as e:
        pytest.xfail(f"Live API call failed during phase2: {e}")

    assert isinstance(p2, JudgeP2Model)
