"""Batch self‑play simulation harness."""
import asyncio
import csv
from pathlib import Path
from typing import Dict, List

from .state import FighterState
from .rng import seed
from .judge import judge_phase1, judge_phase2
from .agents import chat
from .config import CONFIG
from .engine.fighter import get_fighter_attempt
from .engine import constants as C
from .engine.logger import logger

RUNS = CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_RUNS, int)

async def _single_fight() -> Dict[str, str]:
    """
    Simulates a single fight between two AI fighters (A and B).

    The fight proceeds in turns, with fighters proposing actions, a judge (Phase 1)
    determining action validity and success probabilities, dice rolls determining outcomes,
    and another judge (Phase 2) narrating events and calculating state deltas.
    The fight ends when a fighter is dead/unconscious, the judge declares an end,
    or a maximum turn limit is reached.

    Returns:
        A dictionary containing the 'winner' (fighter ID or 'draw') and 'turns' taken.
    """
    A = FighterState.from_preset('A', 'humanoid')
    B = FighterState.from_preset('B', 'humanoid')
    turn = 0
    outcome = None
    combat_log: List[str] = [] # Initialize combat log
    fighter_log_window = CONFIG.get(C.CONFIG_CONTEXT, C.CONFIG_FIGHTER_LOG_WINDOW, int, fallback=5)
    judge_log_window = CONFIG.get(C.CONFIG_CONTEXT, C.CONFIG_JUDGE_LOG_WINDOW, int, fallback=9999) # For Judge P2

    while not outcome:
        turn += 1

        # Prepare recent log for fighters
        start_index = max(0, len(combat_log) - fighter_log_window)
        recent_log_snippet = "\n".join(combat_log[start_index:])

        # Fighters propose actions concurrently
        attemptA, attemptB = await asyncio.gather(
            get_fighter_attempt(A, B, recent_log=recent_log_snippet, turn_window=fighter_log_window),
            get_fighter_attempt(B, A, recent_log=recent_log_snippet, turn_window=fighter_log_window),
        )
        # TODO: Provide more context to judge_phase1, like recent log entries
        p1 = await judge_phase1({'A': A.to_json(), 'B': B.to_json()}, attemptA, attemptB)
        
        # Determine success of attempts based on probabilities from Judge P1
        rolls = {'A': False, 'B': False}
        try:
            prob_a_str = p1.get(f"{C.ATTEMPT}_{C.FIGHTER_A}_prob", "0.0")
            prob_a = float(prob_a_str) if prob_a_str else 0.0
            if p1.get(f"{C.ATTEMPT}_{C.FIGHTER_A}_valid", False):
                rolls['A'] = rand() < prob_a
        except ValueError:
            logger.warning(f"Could not parse probability string for Fighter A: '{prob_a_str}'. Defaulting to 0.0 probability.")
            # rolls['A'] remains False
        
        try:
            prob_b_str = p1.get(f"{C.ATTEMPT}_{C.FIGHTER_B}_prob", "0.0")
            prob_b = float(prob_b_str) if prob_b_str else 0.0
            if p1.get(f"{C.ATTEMPT}_{C.FIGHTER_B}_valid", False):
                rolls['B'] = rand() < prob_b
        except ValueError:
            logger.warning(f"Could not parse probability string for Fighter B: '{prob_b_str}'. Defaulting to 0.0 probability.")
            # rolls['B'] remains False
        
        # Pass the judgement text to P2 for narration context, full states, and combat log
        log_for_judge_start_index = max(0, len(combat_log) - judge_log_window)
        judge_recent_log = "\n".join(combat_log[log_for_judge_start_index:])

        p2_input_state = {
            'fighter_A': A.to_json(), 
            'fighter_B': B.to_json(), 
            'p1_judgement': p1.get('judgement_text', ''),
            'p1_explanation': p1.get('explanation', ''),
            'combat_log_turns': len(combat_log),
            'recent_combat_log': judge_recent_log
        }
        p2 = await judge_phase2(p2_input_state, rolls)

        # Add narration to combat log
        if 'narration' in p2 and p2['narration']:
            combat_log.append(f"Turn {turn}: {p2['narration']}")

        # Apply deltas to fighter states
        if 'delta' in p2 and isinstance(p2['delta'], dict):
            A.apply_delta(p2['delta'].get('A', {}))
            B.apply_delta(p2['delta'].get('B', {}))
        
        # Tick effects for both fighters AFTER deltas are applied for the turn
        A.apply_effects()
        B.apply_effects()

        # Check for fight end conditions
        if p2.get('fight_end', False):
            winner_id = p2.get('winner')
            if winner_id == 'A':
                outcome = A.id
            elif winner_id == 'B':
                outcome = B.id
            elif winner_id is None: # Could be a draw declared by judge
                outcome = 'draw' 
            else: # Unspecified winner but fight_end is true, could be a mutual kill or environmental factor
                outcome = 'ended_no_clear_winner' 
        elif A.status == C.STATUS_DEAD or A.status == C.STATUS_UNCONSCIOUS:
            outcome = B.id # B wins if A is out
        elif B.status == C.STATUS_DEAD or B.status == C.STATUS_UNCONSCIOUS:
            outcome = A.id # A wins if B is out
        elif turn >= CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, int, fallback=100): # Max turn limit, used constant
            outcome = C.DRAW
        # else: outcome remains None, loop continues

    logger.info(f"Fight ended. Outcome: {outcome}, Turns: {turn}")
    logger.info(f"Fighter A ({A.id}) status: {A.status}, Fighter B ({B.id}) status: {B.status}")
    return {C.WINNER: outcome, C.LOG_TURN: str(turn)}

async def run_batch():
    """
    Runs a batch of simulations as defined by 'RUNS' in the configuration.

    Results of each fight (winner, turns) are collected and written to a CSV file
    named 'sim_results.csv' in the current working directory.

    Returns:
        The Path object for the created CSV file.
    """
    res = []
    for _ in range(RUNS):
        res.append(await _single_fight())
    # write CSV
    path = Path('sim_results.csv')
    with path.open('w', newline='') as fp:
        w = csv.DictWriter(fp, fieldnames=res[0].keys())
        w.writeheader()
        w.writerows(res)
    return path