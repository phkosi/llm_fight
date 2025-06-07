"""Batch self‑play simulation harness."""

import asyncio
import csv
from pathlib import Path
from typing import Dict, Callable

from .state import FighterState
from .rng import rand, seed
from .judge import judge_phase1, judge_phase2
from .config import CONFIG
from .engine.fighter import get_fighter_attempt
from .engine import constants as C
from .engine.logger import logger
from .engine.combat_log import CombatLog, CombatTurn


async def _single_fight(
    fighter_a_section: str | None = None,
    fighter_b_section: str | None = None,
    return_log: bool = False,
    on_turn: Callable[[CombatTurn], None] | None = None,
) -> Dict[str, str] | tuple[Dict[str, str], CombatLog]:
    """
    Simulates a single fight between two AI fighters (A and B).

    The fight proceeds in turns, with fighters proposing actions, a judge (Phase 1)
    determining action validity and success probabilities, dice rolls determining outcomes,
    and another judge (Phase 2) narrating events and calculating state deltas.
    The fight ends when a fighter is dead/unconscious, the judge declares an end,
    or a maximum turn limit is reached.

    Returns
    -------
    dict or tuple
        When ``return_log`` is ``False`` (default) returns a dict containing
        the winner and turn count. If ``True``, returns a tuple of that dict and
        the :class:`CombatLog` for the fight. The ``on_turn`` callback, when
        provided, is invoked with each :class:`CombatTurn` as it occurs.
    """
    if fighter_a_section is None:
        fighter_a_section = CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_FIGHTER_A_SECTION, str, fallback="A")
    if fighter_b_section is None:
        fighter_b_section = CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_FIGHTER_B_SECTION, str, fallback="B")

    A = FighterState.from_preset("A", "humanoid", config_section=fighter_a_section)
    B = FighterState.from_preset("B", "humanoid", config_section=fighter_b_section)
    turn = 0
    outcome = None
    combat_log = CombatLog()
    fighter_log_window = CONFIG.get(C.CONFIG_CONTEXT, C.CONFIG_FIGHTER_LOG_WINDOW, int, fallback=5)
    judge_log_window = CONFIG.get(C.CONFIG_CONTEXT, C.CONFIG_JUDGE_LOG_WINDOW, int, fallback=9999)  # For Judge P2

    while not outcome:
        turn += 1

        # Fighters propose actions concurrently, each receiving the combat log
        attemptA, attemptB = await asyncio.gather(
            get_fighter_attempt(A, B, combat_log=combat_log, turn_window=fighter_log_window),
            get_fighter_attempt(B, A, combat_log=combat_log, turn_window=fighter_log_window),
        )
        # Provide recent combat log context to judge_phase1
        p1_recent_log = combat_log.to_summary(last_n=fighter_log_window)
        p1 = await judge_phase1({"A": A.to_json(), "B": B.to_json()}, attemptA, attemptB, recent_log=p1_recent_log)

        # Determine success of attempts based on probabilities from Judge P1
        rolls = {"A": False, "B": False}
        try:
            prob_a_str = p1.get(f"{C.ATTEMPT}_{C.FIGHTER_A}_prob", "0.0")
            prob_a = float(prob_a_str) if prob_a_str else 0.0
            if p1.get(f"{C.ATTEMPT}_{C.FIGHTER_A}_valid", False):
                rolls["A"] = rand() < prob_a
        except ValueError:
            logger.warning(
                f"Could not parse probability string for Fighter A: '{prob_a_str}'. Defaulting to 0.0 probability."
            )
            # rolls['A'] remains False

        try:
            prob_b_str = p1.get(f"{C.ATTEMPT}_{C.FIGHTER_B}_prob", "0.0")
            prob_b = float(prob_b_str) if prob_b_str else 0.0
            if p1.get(f"{C.ATTEMPT}_{C.FIGHTER_B}_valid", False):
                rolls["B"] = rand() < prob_b
        except ValueError:
            logger.warning(
                f"Could not parse probability string for Fighter B: '{prob_b_str}'. Defaulting to 0.0 probability."
            )
            # rolls['B'] remains False

        # Pass the judgement text to P2 for narration context, full states, and combat log
        judge_recent_log = combat_log.to_summary(last_n=judge_log_window)

        p2_input_state = {
            "fighter_A": A.to_json(),
            "fighter_B": B.to_json(),
            "p1_judgement": p1.get("judgement_text", ""),
            "p1_explanation": p1.get("explanation", ""),
            "combat_log_turns": len(combat_log),
            "recent_combat_log": judge_recent_log,
        }
        p2 = await judge_phase2(p2_input_state, rolls)

        turn_entry = CombatTurn(
            turn=turn,
            attempt_A=attemptA,
            attempt_B=attemptB,
            judge_p1=p1,
            judge_p2=p2,
            state_A_before=p2_input_state["fighter_A"],
            state_B_before=p2_input_state["fighter_B"],
        )

        # Apply deltas to fighter states
        if "delta" in p2 and isinstance(p2["delta"], dict):
            A.apply_delta(p2["delta"].get("A", {}))
            B.apply_delta(p2["delta"].get("B", {}))

        # Tick effects for both fighters AFTER deltas are applied for the turn
        A.apply_effects()
        B.apply_effects()

        turn_entry.state_A_after = A.to_json()
        turn_entry.state_B_after = B.to_json()

        combat_log.append(turn_entry)
        if CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_LOG_COMBAT_TURNS, bool, fallback=False):
            logger.info(turn_entry.to_simple_text())
        if on_turn is not None:
            on_turn(turn_entry)

        # Check for fight end conditions
        if p2.get("fight_end", False):
            winner_id = p2.get("winner")
            if winner_id == "A":
                outcome = A.id
            elif winner_id == "B":
                outcome = B.id
            elif winner_id is None:  # Could be a draw declared by judge
                outcome = "draw"
            else:  # Unspecified winner but fight_end is true, could be a mutual kill or environmental factor
                outcome = "ended_no_clear_winner"
        elif A.status in {C.FighterStatus.DEAD, C.FighterStatus.UNCONSCIOUS}:
            outcome = B.id  # B wins if A is out
        elif B.status in {C.FighterStatus.DEAD, C.FighterStatus.UNCONSCIOUS}:
            outcome = A.id  # A wins if B is out
        elif turn >= CONFIG.get(
            C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, int, fallback=100
        ):  # Max turn limit, used constant
            outcome = C.DRAW
        # else: outcome remains None, loop continues

    logger.info(f"Fight ended. Outcome: {outcome}, Turns: {turn}")
    logger.info(f"Fighter A ({A.id}) status: {A.status}, Fighter B ({B.id}) status: {B.status}")
    result = {C.WINNER: outcome, C.LOG_TURN: str(turn)}
    if return_log:
        return result, combat_log
    return result


async def run_batch(
    output_csv: str | Path = "sim_results.csv",
    fighter_a_section: str | None = None,
    fighter_b_section: str | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> Path:
    """Run a batch of simulations and write the results to ``output_csv``.

    The number of runs and allowed concurrency are read from the current
    configuration each time this function is called.  The resulting CSV contains
    one row per fight with columns matching the return value of
    :func:`_single_fight`.

    Parameters
    ----------
    output_csv:
        File path for the CSV output. Defaults to ``"sim_results.csv"`` in the
        current working directory.
    fighter_a_section:
        INI section providing fighter A's settings. Defaults to the value of
        ``fighter_A`` in the ``[General]`` section.
    fighter_b_section:
        INI section providing fighter B's settings. Defaults to the value of
        ``fighter_B`` in the ``[General]`` section.
    progress:
        Optional callback receiving ``(completed, total)`` as the batch runs.

    Returns
    -------
    Path
        Path object for the created CSV file.
    """
    seed(CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_SEED, int))

    runs = CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_RUNS, int)
    concurrency = CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_CONCURRENT_RUNS, int, fallback=1)

    res = []
    sem = asyncio.Semaphore(concurrency)

    async def sem_fight():
        async with sem:
            try:
                return await _single_fight(
                    fighter_a_section=fighter_a_section,
                    fighter_b_section=fighter_b_section,
                )
            except Exception:
                logger.exception("_single_fight failed")
                return {C.WINNER: "error", C.LOG_TURN: "0"}

    tasks = [asyncio.create_task(sem_fight()) for _ in range(runs)]
    for idx, coro in enumerate(asyncio.as_completed(tasks), start=1):
        res.append(await coro)
        if progress:
            progress(idx, runs)

    csv_path = Path(output_csv)
    if not res:
        # When the number of runs is zero we still create the CSV but with only headers
        with csv_path.open("w", newline="") as fp:
            writer = csv.DictWriter(fp, fieldnames=[C.WINNER, C.LOG_TURN])
            writer.writeheader()
        return csv_path

    with csv_path.open("w", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=res[0].keys())
        writer.writeheader()
        writer.writerows(res)

    return csv_path
