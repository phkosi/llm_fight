from src.engine.prompts import JUDGE_P2_SYSTEM_PROMPT
from src.engine import constants as C


def test_judge_p2_prompt_contains_damage_types():
    for dt in C.DamageType:
        assert dt.value in JUDGE_P2_SYSTEM_PROMPT
