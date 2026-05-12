from llm_fight.engine.combat_log import CombatLog, CombatTurn
from llm_fight.engine import constants as C


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


def test_to_summary_zero_last_n():
    log = CombatLog()
    log.append(CombatTurn(turn=1, judge_p2={C.NARRATION: "A swings"}))
    log.append(CombatTurn(turn=2, judge_p2={C.NARRATION: "B dodges"}))

    assert log.to_summary(last_n=0) == ""


def test_to_summary_marks_phase2_fallback_instead_of_confident_narration():
    log = CombatLog()
    log.append(
        CombatTurn(
            turn=1,
            judge_p2={
                C.NARRATION: "The model claimed a clean hit.",
                C.METADATA: {C.P2_FALLBACK_USED: True},
            },
        )
    )

    assert log.to_summary() == f"Turn 1: {C.P2_FALLBACK_MARKER_TEXT}"


def test_combat_turn_to_text():
    turn = CombatTurn(
        turn=3,
        attempt_A="strike",
        attempt_B="parry",
        judge_p1={
            "judgement_text": "A hits",
            "attempt_A_valid": True,
            "attempt_A_prob": "0.8",
            "attempt_B_valid": False,
            "attempt_B_prob": "0.1",
            "explanation": "The parry starts too late.",
        },
        judge_p2={C.NARRATION: "A wounds B"},
    )

    text = turn.to_text()
    assert "Turn 3" in text
    assert "Fighter A attempt: strike" in text
    assert "Fighter B attempt: parry" in text
    assert "Judge ruling: A hits" in text
    assert "Fighter A: valid, success p=0.8" in text
    assert "Fighter B: invalid, success p=0.1" in text
    assert "Reasoning: The parry starts too late." in text
    assert "Outcome: A wounds B" in text


def test_combat_turn_to_text_marks_phase2_fallback():
    turn = CombatTurn(
        turn=3,
        judge_p2={
            C.NARRATION: "The exchange is inconclusive.",
            C.METADATA: {C.P2_FALLBACK_USED: True},
        },
    )

    text = turn.to_text()

    assert C.P2_FALLBACK_MARKER_TEXT in text


def test_combat_turn_to_simple_text():
    turn = CombatTurn(
        turn=4,
        attempt_A="swing",
        attempt_B="block",
        judge_p1={"judgement_text": "A misses"},
        judge_p2={C.NARRATION: "B blocks"},
        state_A_before={"status": C.FighterStatus.FIGHTING},
        state_B_before={"status": C.FighterStatus.FIGHTING},
        state_A_after={"status": C.FighterStatus.FIGHTING},
        state_B_after={"status": C.FighterStatus.UNCONSCIOUS},
    )

    text = turn.to_simple_text()
    lines = text.splitlines()
    assert lines[0].startswith("Turn 4")
    assert "Fighter A attempt: swing" in lines[1]
    assert "Fighter B attempt: block" in lines[2]
    assert any("Judge ruling:" in l for l in lines)
    assert any("A misses" in l for l in lines)
    assert any("Outcome: B blocks" in l for l in lines)
    assert any("Status changes:" in l and "B unconscious" in l for l in lines)
