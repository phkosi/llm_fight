from llm_fight.engine import constants as C
from llm_fight.engine.prompts import FIGHTER_SYSTEM_PROMPT, JUDGE_P1_SYSTEM_PROMPT, JUDGE_P2_SYSTEM_PROMPT
from llm_fight.engine.state_summary import environment_scope_guardrail


def _render_fighter_prompt(environment="an open arena"):
    return FIGHTER_SYSTEM_PROMPT.format(
        fighter_id="A",
        display_name="Sir Galant",
        opponent_id="B",
        opponent_display_name="Shade",
        class_="Knight",
        environment=environment,
        pain_desc="no pain",
        exhaustion_desc="fully rested",
        heat_desc="normal body temperature",
        effects_list="none",
        own_target_parts="head, torso",
        opponent_target_parts="left_wing, tail",
        self_state_summary='{"id":"A"}',
        opponent_state_summary='{"id":"B"}',
        environment_scope_guardrail=environment_scope_guardrail(),
        temporary_effect_instruction="No temporary effects are active right now.",
        turn_window=0,
        recent_log="",
        loadout="sword",
        sentence_limit=1,
        word_limit=30,
    )


def test_judge_p2_prompt_contains_damage_types():
    for dt in C.DamageType:
        assert dt.value in JUDGE_P2_SYSTEM_PROMPT


def test_judge_p2_prompt_describes_wounds_as_positive():
    assert '"value": integer 1-200' in JUDGE_P2_SYSTEM_PROMPT


def test_judge_p2_prompt_requires_source_attribution():
    assert '"source": "A"|"B"' in JUDGE_P2_SYSTEM_PROMPT
    assert "Every state-changing consequence must include the source fighter" in JUDGE_P2_SYSTEM_PROMPT
    assert "Do not infer source from the target fighter" in JUDGE_P2_SYSTEM_PROMPT
    assert "judge-only fight_end or winner values will be ignored" in JUDGE_P2_SYSTEM_PROMPT


def test_judge_p2_prompt_distinguishes_target_delta_key_from_source():
    assert "Delta keys are the fighter receiving the consequence" in JUDGE_P2_SYSTEM_PROMPT
    assert "successful B hit on A -> delta.A with source B" in JUDGE_P2_SYSTEM_PROMPT
    assert "successful A hit on B -> delta.B with source A" in JUDGE_P2_SYSTEM_PROMPT
    assert "Do not put attack damage under the attacking fighter" in JUDGE_P2_SYSTEM_PROMPT


def test_judge_prompts_forbid_swapping_actions_and_called_shot_targets():
    for prompt in (JUDGE_P1_SYSTEM_PROMPT, JUDGE_P2_SYSTEM_PROMPT):
        assert "attempt_A is Fighter A's action only" in prompt
        assert "attempt_B is Fighter B's action only" in prompt
    assert "Never swap actions" in prompt
    assert "failed or invalid actions" in JUDGE_P2_SYSTEM_PROMPT
    assert "must not create wounds" in JUDGE_P2_SYSTEM_PROMPT
    assert "Do not move a called shot to a different part" in JUDGE_P2_SYSTEM_PROMPT
    assert "do not convert them into weapon wounds" in JUDGE_P2_SYSTEM_PROMPT


def test_judge_p2_prompt_documents_structured_targeted_effect_removal():
    assert '"effects_removed": array of objects' in JUDGE_P2_SYSTEM_PROMPT
    assert '"type": "buffs"|"debuffs" optional' in JUDGE_P2_SYSTEM_PROMPT
    assert '"targeted_part": string optional' in JUDGE_P2_SYSTEM_PROMPT
    assert 'include "targeted_part" when treating or extinguishing one localized effect' in JUDGE_P2_SYSTEM_PROMPT
    assert "omit it only for intentional remove-all by name/type" in JUDGE_P2_SYSTEM_PROMPT


def test_fighter_prompt_does_not_add_article_before_environment():
    rendered = _render_fighter_prompt()

    assert "You are Fighter A (display name: Sir Galant)" in rendered
    assert "Your opponent is Fighter B (display name: Shade)" in rendered
    assert "stable combat ids remain A and B" in rendered
    assert "inside an open arena" in rendered
    assert "inside a an open arena" not in rendered


def test_fighter_prompt_forbids_inventing_environment_features():
    rendered = _render_fighter_prompt()

    assert "Current state is authoritative" in rendered
    assert (
        "Do not rely on temporary effects from the recent log unless they are still listed in Active effects."
        in rendered
    )
    assert "Current state reminder: active effects right now are none." in rendered
    assert "Your valid target parts: head, torso" in rendered
    assert "Opponent valid target parts: left_wing, tail" in rendered
    assert "Self state summary: " in rendered
    assert "Opponent state summary: " in rendered
    assert "Use only features present in the current environment, equipment, active effects" in rendered
    assert "Do not claim new cover, walls, pillars, smoke, shadows, terrain, or objects already exist" in rendered


def test_fighter_prompt_allows_explicit_environment_features():
    rendered = _render_fighter_prompt(environment="a ruined hall with pillars, smoke, and broken cover")

    assert "inside a ruined hall with pillars, smoke, and broken cover" in rendered
    assert "unless listed there" in rendered


def test_fighter_prompt_repeats_active_effects_after_recent_log():
    recent_log = "Turn 1: Smoke fills the arena."
    rendered = FIGHTER_SYSTEM_PROMPT.format(
        fighter_id="A",
        display_name="Sir Galant",
        opponent_id="B",
        opponent_display_name="Shade",
        class_="Knight",
        environment="an open arena",
        pain_desc="no pain",
        exhaustion_desc="fully rested",
        heat_desc="normal body temperature",
        effects_list="none",
        own_target_parts="head, torso",
        opponent_target_parts="left_wing, tail",
        self_state_summary='{"id":"A"}',
        opponent_state_summary='{"id":"B"}',
        environment_scope_guardrail=environment_scope_guardrail(),
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


def test_judge_prompts_keep_display_names_label_only():
    assert "Display names in fighter summaries are labels only" in JUDGE_P1_SYSTEM_PROMPT
    assert "mechanical fighter ids remain A and B" in JUDGE_P1_SYSTEM_PROMPT
    assert "Display names in fighter states are labels only" in JUDGE_P2_SYSTEM_PROMPT
    assert "winner values must remain stable ids A or B" in JUDGE_P2_SYSTEM_PROMPT
