from unittest.mock import patch

from llm_fight.engine.combat_log import CombatTurn
from llm_fight.engine import constants as C
from llm_fight.engine import render
from llm_fight.simulation import FightEvent


def _turn_with_all_sections():
    return CombatTurn(
        turn=1,
        attempt_A="raise shield",
        attempt_B="throw smoke",
        judge_p1={
            "judgement_text": "Both attempts are plausible but defensive.",
            "attempt_A_valid": True,
            "attempt_A_prob": "0.7",
            "attempt_B_valid": True,
            "attempt_B_prob": "0.4",
            "explanation": "Smoke is possible, but the shield is already up.",
        },
        judge_p2={C.NARRATION: "The shield comes up before the smoke spreads."},
    )


def test_make_turn_table_rich():
    turn = CombatTurn(turn=1, attempt_A="hit", attempt_B="parry", judge_p2={C.NARRATION: "A hits"})
    if render.RICH_AVAILABLE:
        table = render.make_turn_table(turn)
        from rich.table import Table

        assert isinstance(table, Table)
    else:
        table = render.make_turn_table(turn)
        assert isinstance(table, str) and "Turn" in table


def test_make_turn_table_fallback():
    turn = CombatTurn(turn=1, attempt_A="hit", attempt_B="parry", judge_p2={C.NARRATION: "A hits"})
    with patch.object(render, "RICH_AVAILABLE", False):
        result = render.make_turn_table(turn)
        assert isinstance(result, str)
        assert "Turn 1" in result


def test_make_turn_table_simple():
    turn = CombatTurn(
        turn=1,
        attempt_A="hit",
        attempt_B="parry",
        judge_p2={C.NARRATION: "A hits"},
        state_A_before={"status": C.FighterStatus.FIGHTING},
        state_A_after={"status": C.FighterStatus.FIGHTING},
        state_B_before={"status": C.FighterStatus.FIGHTING},
        state_B_after={"status": C.FighterStatus.DEAD},
    )
    result = render.make_turn_table(turn, simple=True)
    assert isinstance(result, str)
    assert "Fighter A attempt: hit" in result
    assert "Fighter B attempt: parry" in result
    assert "Outcome: A hits" in result
    assert "Status changes:" in result


def test_make_turn_table_simple_marks_phase2_fallback():
    turn = CombatTurn(
        turn=1,
        judge_p2={
            C.NARRATION: "The exchange is inconclusive.",
            C.METADATA: {C.P2_FALLBACK_USED: True},
        },
    )

    result = render.make_turn_table(turn, simple=True)

    assert C.P2_FALLBACK_MARKER_TEXT in result


def test_make_turn_table_rich_uses_explicit_turn_phases():
    if not render.RICH_AVAILABLE:
        return

    turn = _turn_with_all_sections()
    table = render.make_turn_table(turn)

    console = render.Console(record=True, width=140, color_system=None)
    console.print(table)
    output = console.export_text()
    lines = output.splitlines()

    assert "Phase" in output
    assert "Details" in output
    assert "Fighter A attempt" in output
    assert "Fighter B attempt" in output
    assert "Judge ruling" in output
    assert "Outcome" in output

    fighter_a_line = next(line for line in lines if "Fighter A attempt" in line)
    fighter_b_line = next(line for line in lines if "Fighter B attempt" in line)
    judge_line = next(line for line in lines if "Judge ruling" in line)
    outcome_line = next(line for line in lines if "Outcome" in line)

    assert "raise shield" in fighter_a_line
    assert "throw smoke" in fighter_b_line
    assert "Both attempts are plausible" not in fighter_a_line
    assert "Both attempts are plausible" not in fighter_b_line
    assert "The shield comes up" not in fighter_a_line
    assert "The shield comes up" not in fighter_b_line
    assert "Both attempts are plausible" in judge_line
    assert "The shield comes up" in outcome_line


def test_make_turn_table_rich_marks_phase2_fallback():
    if not render.RICH_AVAILABLE:
        return

    turn = CombatTurn(
        turn=1,
        judge_p2={
            C.NARRATION: "The exchange is inconclusive.",
            C.METADATA: {C.P2_FALLBACK_USED: True},
        },
    )
    table = render.make_turn_table(turn)

    console = render.Console(record=True, width=120, color_system=None)
    console.print(table)
    output = console.export_text()

    assert "Warning" in output
    assert C.P2_FALLBACK_MARKER_TEXT in output


def test_make_turn_table_fallback_uses_explicit_turn_phases():
    turn = _turn_with_all_sections()
    with patch.object(render, "RICH_AVAILABLE", False):
        result = render.make_turn_table(turn)

    assert "Fighter A attempt: raise shield" in result
    assert "Fighter B attempt: throw smoke" in result
    assert "Judge ruling: Both attempts are plausible but defensive." in result
    assert "Outcome: The shield comes up before the smoke spreads." in result


def test_make_summary_table():
    rows = [
        {C.WINNER: "A", C.LOG_TURN: "2", C.LOG_P2_FALLBACK_TURNS: "1", C.LOG_P2_FALLBACK_USED: "true"},
        {C.WINNER: "B", C.LOG_TURN: "3", C.LOG_P2_FALLBACK_TURNS: "0", C.LOG_P2_FALLBACK_USED: "false"},
        {C.WINNER: "A", C.LOG_TURN: "1", C.LOG_P2_FALLBACK_TURNS: "0", C.LOG_P2_FALLBACK_USED: "false"},
    ]
    table = render.make_summary_table(rows)
    if render.RICH_AVAILABLE:
        from rich.table import Table

        assert isinstance(table, Table)
    else:
        assert "Average" in table


def test_make_summary_table_fallback():
    rows = [{C.WINNER: "A", C.LOG_TURN: "1", C.LOG_P2_FALLBACK_TURNS: "2", C.LOG_P2_FALLBACK_USED: "true"}]
    with patch.object(render, "RICH_AVAILABLE", False):
        result = render.make_summary_table(rows)
    assert "Average Turns" in result
    assert "P2 Fallback Rows: 1" in result
    assert "P2 Fallback Turns: 2" in result


def test_make_fighter_design_view_simple_includes_dynamic_design_details():
    fighters = {
        C.FIGHTER_A: {
            "class_": "Winged Duelist",
            C.THEME: "sky mutant",
            C.LOADOUT: "hook blades",
            "environment": "an open arena",
            "parts": {"left_wing": {}, "second_head": {}},
            C.BUFFS: [],
            C.DEBUFFS: [{C.NAME: "crystal_rot"}],
            C.PROFILE_GENERATION: {"mode": "generated", "nudge": "original", "error": None},
        },
        C.FIGHTER_B: {
            "class_": "Knight",
            C.LOADOUT: "sword",
            "environment": "an open arena",
            "parts": {"head": {}, "torso": {}},
            C.BUFFS: [],
            C.DEBUFFS: [],
        },
    }

    result = render.make_fighter_design_view(fighters, simple=True)

    assert "Fighter Designs" in result
    assert "Winged Duelist (sky mutant)" in result
    assert "left_wing, second_head" in result
    assert "crystal_rot" in result
    assert "Profile generation" in result


def test_format_fight_event_status_includes_phase_fighter_and_turn():
    event = FightEvent(C.FIGHT_EVENT_FIGHTER_ACTION_START, turn=3, fighter_id=C.FIGHTER_A)

    assert render.format_fight_event_status(event) == "Generating fighter action (Fighter A, turn 3)"


def test_format_token_summary_with_counts_and_missing_fallback():
    assert render.format_token_summary([]) == "Token usage: tokens unavailable"

    summary = render.format_token_summary(
        [
            {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            {"prompt_tokens": 4, "completion_tokens": 6, "total_tokens": 10},
        ]
    )

    assert summary == "Token usage: prompt 14, completion 11, total 25"
