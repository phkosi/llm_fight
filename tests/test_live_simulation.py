import asyncio
import csv
import os

import pytest

from llm_fight import config as config_mod
from llm_fight.engine import constants as C
from llm_fight.engine.combat_log import CombatLog
from llm_fight.engine.fighter import get_fighter_attempt
from llm_fight.simulation import run_batch
from llm_fight.state import FighterState

pytestmark = pytest.mark.live


def _skip_without_live_api():
    if not os.environ.get("API_URL"):
        pytest.skip("API_URL env var not set")


def _set_for_live_smoke():
    cfg = config_mod.CONFIG
    old_values = {
        (C.CONFIG_GENERAL, C.CONFIG_LLAMA_DEFAULT_MODEL): cfg.get(C.CONFIG_GENERAL, C.CONFIG_LLAMA_DEFAULT_MODEL, str),
        (C.CONFIG_GENERAL, C.CONFIG_LLAMA_TEMPERATURE): cfg.get(C.CONFIG_GENERAL, C.CONFIG_LLAMA_TEMPERATURE, str),
        (C.CONFIG_GENERAL, C.CONFIG_MAX_RETRIES): cfg.get(C.CONFIG_GENERAL, C.CONFIG_MAX_RETRIES, str),
        (C.CONFIG_GENERAL, C.CONFIG_OLLAMA_NUM_CTX): cfg.get(C.CONFIG_GENERAL, C.CONFIG_OLLAMA_NUM_CTX, str),
        (C.CONFIG_GENERAL, C.CONFIG_MAX_TOKENS_FIGHTER): cfg.get(C.CONFIG_GENERAL, C.CONFIG_MAX_TOKENS_FIGHTER, str),
        (C.CONFIG_GENERAL, C.CONFIG_MAX_TOKENS_JUDGE): cfg.get(C.CONFIG_GENERAL, C.CONFIG_MAX_TOKENS_JUDGE, str),
        (C.CONFIG_SIMULATION, C.CONFIG_RUNS): cfg.get(C.CONFIG_SIMULATION, C.CONFIG_RUNS, str),
        (C.CONFIG_SIMULATION, C.CONFIG_CONCURRENT_RUNS): cfg.get(C.CONFIG_SIMULATION, C.CONFIG_CONCURRENT_RUNS, str),
        (C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS): cfg.get(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, str),
    }
    live_model = os.environ.get("LLMFIGHT_LIVE_MODEL") or os.environ.get("OLLAMA_MODEL")
    if live_model:
        cfg.set(C.CONFIG_GENERAL, C.CONFIG_LLAMA_DEFAULT_MODEL, live_model)
    cfg.set(C.CONFIG_GENERAL, C.CONFIG_LLAMA_TEMPERATURE, "0.2")
    cfg.set(C.CONFIG_GENERAL, C.CONFIG_MAX_RETRIES, "2")
    cfg.set(C.CONFIG_GENERAL, C.CONFIG_OLLAMA_NUM_CTX, "32768")
    cfg.set(C.CONFIG_GENERAL, C.CONFIG_MAX_TOKENS_FIGHTER, "512")
    cfg.set(C.CONFIG_GENERAL, C.CONFIG_MAX_TOKENS_JUDGE, "4096")
    cfg.set(C.CONFIG_SIMULATION, C.CONFIG_RUNS, "2")
    cfg.set(C.CONFIG_SIMULATION, C.CONFIG_CONCURRENT_RUNS, "1")
    cfg.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, "2")
    return old_values


def _restore_config(old_values):
    for (section, key), value in old_values.items():
        config_mod.CONFIG.set(section, key, value)


@pytest.mark.asyncio
async def test_live_fighter_attempt_is_non_empty():
    _skip_without_live_api()
    old_values = _set_for_live_smoke()
    try:
        fighter = FighterState.from_preset("A", "humanoid")
        opponent = FighterState.from_preset("B", "humanoid")
        attempt = await asyncio.wait_for(
            get_fighter_attempt(fighter, opponent, combat_log=CombatLog(), turn_window=0),
            timeout=90,
        )
    finally:
        _restore_config(old_values)

    assert attempt.strip()


@pytest.mark.asyncio
async def test_live_short_batch_completes_without_error_rows(tmp_path):
    _skip_without_live_api()
    old_values = _set_for_live_smoke()
    try:
        output_csv = tmp_path / "live_sim_results.csv"
        path = await asyncio.wait_for(run_batch(output_csv), timeout=300)
    finally:
        _restore_config(old_values)

    with path.open(newline="") as fp:
        rows = list(csv.DictReader(fp))

    assert len(rows) == 2
    assert all(row[C.WINNER] != "error" for row in rows)
