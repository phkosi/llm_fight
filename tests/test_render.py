from unittest.mock import patch

from src.engine.combat_log import CombatTurn
from src.engine import constants as C
from src.engine import render


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


def test_make_summary_table():
    rows = [{C.WINNER: "A", C.LOG_TURN: "2"}, {C.WINNER: "B", C.LOG_TURN: "3"}, {C.WINNER: "A", C.LOG_TURN: "1"}]
    table = render.make_summary_table(rows)
    if render.RICH_AVAILABLE:
        from rich.table import Table

        assert isinstance(table, Table)
    else:
        assert "Average" in table
