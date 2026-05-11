from llm_fight.engine.prompts import FIGHTER_SYSTEM_PROMPT, JUDGE_P2_SYSTEM_PROMPT
from llm_fight.engine import constants as C


def test_judge_p2_prompt_contains_damage_types():
    for dt in C.DamageType:
        assert dt.value in JUDGE_P2_SYSTEM_PROMPT


def test_judge_p2_prompt_describes_wounds_as_positive():
    assert '"value": positive integer' in JUDGE_P2_SYSTEM_PROMPT


def test_fighter_prompt_does_not_add_article_before_environment():
    rendered = FIGHTER_SYSTEM_PROMPT.format(
        name="A",
        class_="Knight",
        environment="an open arena",
        pain_desc="no pain",
        exhaustion_desc="fully rested",
        heat_desc="normal body temperature",
        effects_list="none",
        turn_window=0,
        recent_log="",
        loadout="sword",
        sentence_limit=1,
        word_limit=30,
    )

    assert "inside an open arena" in rendered
    assert "inside a an open arena" not in rendered


def test_fighter_prompt_forbids_inventing_environment_features():
    rendered = FIGHTER_SYSTEM_PROMPT.format(
        name="A",
        class_="Knight",
        environment="an open arena",
        pain_desc="no pain",
        exhaustion_desc="fully rested",
        heat_desc="normal body temperature",
        effects_list="none",
        turn_window=0,
        recent_log="",
        loadout="sword",
        sentence_limit=1,
        word_limit=30,
    )

    assert "Use only environment features" in rendered
    assert "Do not invent walls, pillars, corridors, shadows, cover, terrain, or objects." in rendered
