import csv
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import llm_fight.simulation as sim_module
from llm_fight.engine import constants as C
from llm_fight.state import FighterState
from llm_fight.utils.token_counter import PromptBudgetError


@pytest.mark.asyncio
async def test_single_fight_raises_on_guarded_call(monkeypatch):
    async def fail_guarded(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("llm_fight.validation.guarded_call", fail_guarded)
    monkeypatch.setattr("llm_fight.judge.guarded_call", fail_guarded)

    fighter_a = MagicMock(spec=FighterState)
    fighter_a.id = "A"
    fighter_a.status = C.FighterStatus.FIGHTING
    fighter_a.to_json.return_value = {}
    fighter_a.apply_delta = MagicMock()
    fighter_a.apply_effects = MagicMock()

    fighter_b = MagicMock(spec=FighterState)
    fighter_b.id = "B"
    fighter_b.status = C.FighterStatus.FIGHTING
    fighter_b.to_json.return_value = {}
    fighter_b.apply_delta = MagicMock()
    fighter_b.apply_effects = MagicMock()

    monkeypatch.setattr(
        sim_module.FighterState,
        "from_preset",
        MagicMock(side_effect=[fighter_a, fighter_b]),
    )
    monkeypatch.setattr(sim_module, "get_fighter_attempt", AsyncMock(return_value="attack"))

    with pytest.raises(RuntimeError):
        await sim_module._single_fight()


@pytest.mark.asyncio
async def test_run_batch_partial_results_on_guarded_call_failure(monkeypatch, tmp_path):
    async def fail_guarded(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("llm_fight.validation.guarded_call", fail_guarded)
    monkeypatch.setattr("llm_fight.judge.guarded_call", fail_guarded)

    fighter_a = MagicMock(spec=FighterState)
    fighter_a.id = "A"
    fighter_a.status = C.FighterStatus.FIGHTING
    fighter_a.to_json.return_value = {}
    fighter_a.apply_delta = MagicMock()
    fighter_a.apply_effects = MagicMock()

    fighter_b = MagicMock(spec=FighterState)
    fighter_b.id = "B"
    fighter_b.status = C.FighterStatus.FIGHTING
    fighter_b.to_json.return_value = {}
    fighter_b.apply_delta = MagicMock()
    fighter_b.apply_effects = MagicMock()

    monkeypatch.setattr(
        sim_module.FighterState,
        "from_preset",
        MagicMock(side_effect=[fighter_a, fighter_b]),
    )
    monkeypatch.setattr(sim_module, "get_fighter_attempt", AsyncMock(return_value="attack"))

    out_file = tmp_path / "results.csv"
    orig_get = sim_module.config_mod.CONFIG.get

    def fake_get(section, key, cast=str, fallback=None):
        if section == C.CONFIG_SIMULATION and key == C.CONFIG_RUNS:
            return 2
        if section == C.CONFIG_SIMULATION and key == C.CONFIG_CONCURRENT_RUNS:
            return 1
        return orig_get(section, key, cast, fallback)

    with (
        patch.object(sim_module.config_mod.CONFIG, "get", side_effect=fake_get),
        patch.object(sim_module.logger, "exception") as mock_exc,
    ):
        path = await sim_module.run_batch(out_file)

    assert path == out_file
    with open(out_file, newline="") as fp:
        rows = list(csv.DictReader(fp))

    assert len(rows) == 2
    assert all(row[C.WINNER] == "error" for row in rows)
    assert mock_exc.call_count == 2


@pytest.mark.asyncio
async def test_run_batch_propagates_prompt_budget_error(tmp_path):
    error = PromptBudgetError(
        phase=C.PROMPT_PHASE_FIGHTER_ACTION,
        prompt_tokens=500,
        context_limit=400,
        requested_max_tokens=64,
        reserved_completion=64,
        log_window_setting=C.CONFIG_FIGHTER_LOG_WINDOW,
    )
    out_file = tmp_path / "budget.csv"

    orig_get = sim_module.config_mod.CONFIG.get

    def fake_get(section, key, cast=str, fallback=None):
        if section == C.CONFIG_SIMULATION and key == C.CONFIG_RUNS:
            return 1
        if section == C.CONFIG_SIMULATION and key == C.CONFIG_CONCURRENT_RUNS:
            return 1
        return orig_get(section, key, cast, fallback)

    with (
        patch.object(sim_module.config_mod.CONFIG, "get", side_effect=fake_get),
        patch.object(sim_module, "_single_fight", new=AsyncMock(side_effect=error)),
    ):
        with pytest.raises(PromptBudgetError):
            await sim_module.run_batch(out_file)


@pytest.mark.asyncio
async def test_run_batch_cancels_pending_tasks_on_prompt_budget_error(tmp_path):
    error = PromptBudgetError(
        phase=C.PROMPT_PHASE_FIGHTER_ACTION,
        prompt_tokens=500,
        context_limit=400,
        requested_max_tokens=64,
        reserved_completion=64,
        log_window_setting=C.CONFIG_FIGHTER_LOG_WINDOW,
    )
    out_file = tmp_path / "budget_concurrent.csv"
    pending_cancelled = False
    call_count = 0

    orig_get = sim_module.config_mod.CONFIG.get

    def fake_get(section, key, cast=str, fallback=None):
        if section == C.CONFIG_SIMULATION and key == C.CONFIG_RUNS:
            return 2
        if section == C.CONFIG_SIMULATION and key == C.CONFIG_CONCURRENT_RUNS:
            return 2
        return orig_get(section, key, cast, fallback)

    async def fake_single_fight(*args, **kwargs):
        nonlocal call_count, pending_cancelled
        call_count += 1
        if call_count == 1:
            await asyncio.sleep(0)
            raise error
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            pending_cancelled = True
            raise

    with (
        patch.object(sim_module.config_mod.CONFIG, "get", side_effect=fake_get),
        patch.object(sim_module, "_single_fight", new=AsyncMock(side_effect=fake_single_fight)),
    ):
        with pytest.raises(PromptBudgetError):
            await sim_module.run_batch(out_file)

    assert pending_cancelled is True
    with out_file.open(newline="") as fp:
        rows = list(csv.DictReader(fp))
    assert rows == []
