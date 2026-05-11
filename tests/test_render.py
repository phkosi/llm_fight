from unittest.mock import patch

from llm_fight.engine.combat_log import CombatTurn
from llm_fight.engine import constants as C
from llm_fight.engine import render


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


def test_make_turn_table_fallback_uses_explicit_turn_phases():
    turn = _turn_with_all_sections()
    with patch.object(render, "RICH_AVAILABLE", False):
        result = render.make_turn_table(turn)

    assert "Fighter A attempt: raise shield" in result
    assert "Fighter B attempt: throw smoke" in result
    assert "Judge ruling: Both attempts are plausible but defensive." in result
    assert "Outcome: The shield comes up before the smoke spreads." in result


def test_make_summary_table():
    rows = [{C.WINNER: "A", C.LOG_TURN: "2"}, {C.WINNER: "B", C.LOG_TURN: "3"}, {C.WINNER: "A", C.LOG_TURN: "1"}]
    table = render.make_summary_table(rows)
    if render.RICH_AVAILABLE:
        from rich.table import Table

        assert isinstance(table, Table)
    else:
        assert "Average" in table


def test_make_summary_table_fallback():
    rows = [{C.WINNER: "A", C.LOG_TURN: "1"}]
    with patch.object(render, "RICH_AVAILABLE", False):
        result = render.make_summary_table(rows)
    assert "Average Turns" in result
