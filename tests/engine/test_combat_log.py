from src.engine.combat_log import CombatLog, CombatTurn
from src.engine import constants as C


def test_combat_log_basic_usage():
    log = CombatLog()
    log.append(CombatTurn(turn=1, judge_p2={C.NARRATION: "A swings"}))
    log.append(CombatTurn(turn=2, judge_p2={C.NARRATION: "B dodges"}))

    assert len(log) == 2
    assert log.to_summary() == "Turn 1: A swings\nTurn 2: B dodges"

    last = log.get_last_n(1)
    assert len(last) == 1
    assert last[0].turn == 2
    assert last[0].narration == "B dodges"

    assert log.to_summary(last_n=1) == "Turn 2: B dodges"
