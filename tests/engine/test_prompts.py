from llm_fight.engine.prompts import FIGHTER_SYSTEM_PROMPT, JUDGE_P1_SYSTEM_PROMPT, JUDGE_P2_SYSTEM_PROMPT
from llm_fight.engine import constants as C


def test_judge_p2_prompt_contains_damage_types():
    for dt in C.DamageType:
        assert dt.value in JUDGE_P2_SYSTEM_PROMPT


def test_judge_p2_prompt_describes_wounds_as_positive():
    assert '"value": positive integer' in JUDGE_P2_SYSTEM_PROMPT


def test_judge_p2_prompt_requires_source_attribution():
    assert '"source": "A"|"B"' in JUDGE_P2_SYSTEM_PROMPT
    assert "Every state-changing consequence must include the source fighter" in JUDGE_P2_SYSTEM_PROMPT
    assert "Do not infer source from the target fighter" in JUDGE_P2_SYSTEM_PROMPT
    assert "judge-only fight_end or winner values will be ignored" in JUDGE_P2_SYSTEM_PROMPT


def test_judge_p2_prompt_documents_structured_targeted_effect_removal():
    assert '"effects_removed": array of objects' in JUDGE_P2_SYSTEM_PROMPT
    assert '"type": "buffs"|"debuffs" optional' in JUDGE_P2_SYSTEM_PROMPT
    assert '"targeted_part": string optional' in JUDGE_P2_SYSTEM_PROMPT
    assert 'include "targeted_part" when treating or extinguishing one localized effect' in JUDGE_P2_SYSTEM_PROMPT
    assert "omit it only for intentional remove-all by name/type" in JUDGE_P2_SYSTEM_PROMPT


def test_fighter_prompt_does_not_add_article_before_environment():
    rendered = FIGHTER_SYSTEM_PROMPT.format(
        name="A",
        class_="Knight",
        environment="an open arena",
        pain_desc="no pain",
        exhaustion_desc="fully rested",
        heat_desc="normal body temperature",
        effects_list="none",
        own_target_parts="head, torso",
        opponent_target_parts="left_wing, tail",
        temporary_effect_instruction="No temporary effects are active right now.",
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
        own_target_parts="head, torso",
        opponent_target_parts="left_wing, tail",
        temporary_effect_instruction="No temporary effects are active right now.",
        turn_window=0,
        recent_log="",
        loadout="sword",
        sentence_limit=1,
        word_limit=30,
    )

    assert "Current state is authoritative" in rendered
    assert (
        "Do not rely on temporary effects from the recent log unless they are still listed in Active effects."
        in rendered
    )
    assert "Current state reminder: active effects right now are none." in rendered
    assert "Your valid target parts: head, torso" in rendered
    assert "Opponent valid target parts: left_wing, tail" in rendered
    assert (
        "Use only the current environment, active effects, equipment, and durable changes established above."
        in rendered
    )
    assert "Do not invent walls, pillars, corridors, shadows, cover, terrain, or objects." in rendered


def test_fighter_prompt_repeats_active_effects_after_recent_log():
    recent_log = "Turn 1: Smoke fills the arena."
    rendered = FIGHTER_SYSTEM_PROMPT.format(
        name="A",
        class_="Knight",
        environment="an open arena",
        pain_desc="no pain",
        exhaustion_desc="fully rested",
        heat_desc="normal body temperature",
        effects_list="none",
        own_target_parts="head, torso",
        opponent_target_parts="left_wing, tail",
        temporary_effect_instruction="No temporary effects are active right now.",
        turn_window=1,
        recent_log=recent_log,
        loadout="sword",
        sentence_limit=1,
        word_limit=30,
    )

    assert rendered.index(recent_log) < rendered.index("Current state reminder")
    assert "Older temporary effects not listed here have ended." in rendered
    assert "No temporary effects are active right now." in rendered


def test_judge_prompts_treat_current_state_as_authoritative():
    for prompt in (JUDGE_P1_SYSTEM_PROMPT, JUDGE_P2_SYSTEM_PROMPT):
        assert "Current" in prompt and "authoritative" in prompt
        assert "recent combat log as history, not active state" in prompt
        assert "Temporary conditions from older narration" in prompt
