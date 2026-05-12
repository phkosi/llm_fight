from llm_fight.engine import constants as C
from llm_fight.engine.combat_log import CombatLog, CombatTurn


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
    assert any("Judge ruling:" in line for line in lines)
    assert any("A misses" in line for line in lines)
    assert any("Outcome: B blocks" in line for line in lines)
    assert any("Mechanical changes:" in line for line in lines)
    assert any("B status fighting -> unconscious" in line for line in lines)


def test_combat_turn_rolls_and_mechanical_changes_text():
    before_b = {
        C.STATUS: C.FighterStatus.FIGHTING,
        C.PAIN: 0,
        C.EXHAUSTION: 1,
        C.HEAT: 0,
        "parts": {
            "left_arm": {
                C.STATUS: "intact",
                "severed": False,
                "layers": [{C.NAME: "skin", C.MAX_HP: 10, C.CURRENT_HP: 10}],
            }
        },
        C.BUFFS: [],
        C.DEBUFFS: [
            {
                C.NAME: "bleeding",
                "magnitude": 2,
                C.EFFECT_TTL: 3,
                C.METADATA: {C.TARGETED_PART: "left_arm"},
            }
        ],
    }
    after_b = {
        C.STATUS: C.FighterStatus.UNCONSCIOUS,
        C.PAIN: 5,
        C.EXHAUSTION: 1,
        C.HEAT: 0,
        "parts": {
            "left_arm": {
                C.STATUS: C.STATUS_SEVERED,
                "severed": True,
                "layers": [{C.NAME: "skin", C.MAX_HP: 10, C.CURRENT_HP: 3}],
            }
        },
        C.BUFFS: [],
        C.DEBUFFS: [
            {
                C.NAME: "poisoned",
                "magnitude": 1,
                C.EFFECT_TTL: 2,
                C.METADATA: {C.TARGETED_PART: "left_arm"},
            }
        ],
    }
    turn = CombatTurn(
        turn=1,
        judge_p2={
            C.DELTA: {
                C.FIGHTER_B: {
                    C.WOUNDS: [
                        {
                            C.SOURCE: C.FIGHTER_A,
                            C.TARGETED_PART: "left_arm",
                            C.TYPE: C.DamageType.SLASHING,
                            C.VALUE: 7,
                        }
                    ]
                }
            }
        },
        state_A_before={C.STATUS: C.FighterStatus.FIGHTING},
        state_A_after={C.STATUS: C.FighterStatus.FIGHTING},
        state_B_before=before_b,
        state_B_after=after_b,
        rolls={
            C.FIGHTER_A: {
                "valid": True,
                "probability": 0.8,
                "probability_text": "0.8",
                "roll": 0.2,
                "success": True,
                "reason": "success",
            },
            C.FIGHTER_B: {
                "valid": False,
                "probability": None,
                "probability_text": "0.4",
                "roll": None,
                "success": False,
                "reason": "invalid_attempt",
            },
        },
    )

    assert "Fighter A: success (roll 0.200 < p=0.8)" in turn.rolls_text()
    assert "Fighter B: invalid / not rolled (p=0.4)" in turn.rolls_text()

    changes = turn.mechanical_changes_text()
    assert "B pain +5 (0 -> 5)" in changes
    assert "B wound: left_arm slashing 7 from A" in changes
    assert "B left_arm: status intact -> severed; severed False -> True; skin hp 10 -> 3" in changes
    assert "B debuff bleeding on left_arm removed/expired" in changes
    assert "B debuff poisoned on left_arm added (ttl=2, magnitude=1)" in changes
    assert "B status fighting -> unconscious" in changes


def test_combat_turn_reports_no_mechanical_changes_when_snapshots_match():
    state = {
        C.STATUS: C.FighterStatus.FIGHTING,
        C.PAIN: 0,
        C.EXHAUSTION: 0,
        C.HEAT: 0,
        "parts": {},
        C.BUFFS: [],
        C.DEBUFFS: [],
    }
    turn = CombatTurn(
        turn=1,
        state_A_before=state,
        state_A_after=state,
        state_B_before=state,
        state_B_after=state,
    )

    assert turn.mechanical_change_lines() == ["No mechanical state changes."]
