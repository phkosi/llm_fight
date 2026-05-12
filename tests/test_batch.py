import asyncio
import csv
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import llm_fight.simulation as sim_module
from llm_fight.config import Config
from llm_fight.engine import constants as C
from llm_fight.judge import JudgePhase2FailureError
from llm_fight.state import FighterState
from llm_fight.utils.token_counter import PromptBudgetError


def _display_columns(a="", b="", winner=""):
    return {
        C.LOG_FIGHTER_A_DISPLAY_NAME: a,
        C.LOG_FIGHTER_B_DISPLAY_NAME: b,
        C.LOG_WINNER_DISPLAY_NAME: winner,
    }


def _patch_batch_config(runs: int, concurrency: int, seed_value: int = 42):
    orig_get = sim_module.config_mod.CONFIG.get

    def fake_get(section, key, cast=str, fallback=None):
        if section == C.CONFIG_SIMULATION and key == C.CONFIG_RUNS:
            return runs
        if section == C.CONFIG_SIMULATION and key == C.CONFIG_CONCURRENT_RUNS:
            return concurrency
        if section == C.CONFIG_SIMULATION and key == C.CONFIG_SEED:
            return seed_value
        return orig_get(section, key, cast, fallback)

    return patch.object(sim_module.config_mod.CONFIG, "get", side_effect=fake_get)


@pytest.mark.asyncio
async def test_run_batch_creates_unique_trace_per_concurrent_fight(tmp_path):
    transcript_dir = tmp_path / "traces"
    config_path = tmp_path / "game.ini"
    config_path.write_text(
        "\n".join(
            [
                "[General]",
                "save_transcripts = true",
                f"transcript_dir = {transcript_dir}",
                "",
                "[SIMULATION]",
                "runs = 2",
                "concurrent_runs = 2",
                "max_turns = 1",
            ]
        ),
        encoding="utf-8",
    )

    async def fake_get_attempt(*args, **kwargs):
        return "attack"

    async def fake_judge_p1(*args, **kwargs):
        return {
            f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "0.0",
            f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.0",
            "judgement_text": "No one lands.",
            "explanation": "",
        }

    async def fake_judge_p2(*args, **kwargs):
        return {C.NARRATION: "They reset.", C.DELTA: {}, C.FIGHT_END: False, C.WINNER: None}

    old_config = sim_module.config_mod.CONFIG
    sim_module.config_mod.CONFIG = Config(config_path)
    try:
        with (
            patch.object(sim_module, "get_fighter_attempt", new=AsyncMock(side_effect=fake_get_attempt)),
            patch.object(sim_module, "judge_phase1", new=AsyncMock(side_effect=fake_judge_p1)),
            patch.object(sim_module, "judge_phase2", new=AsyncMock(side_effect=fake_judge_p2)),
        ):
            await sim_module.run_batch(tmp_path / "results.csv")
    finally:
        sim_module.config_mod.CONFIG = old_config

    files = sorted(transcript_dir.glob("*.jsonl"))
    assert len(files) == 2
    assert list(transcript_dir.glob("*.json")) == []
    events_by_file = [[json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] for path in files]
    assert {events[0]["run_index"] for events in events_by_file} == {0, 1}
    assert all(events[-1]["event"] == C.FIGHT_EVENT_FIGHT_COMPLETE for events in events_by_file)


@pytest.mark.asyncio
async def test_run_batch_concurrency(tmp_path):

    running = 0
    max_running = 0
    lock = asyncio.Lock()

    async def fake_fight(*args, **kwargs):
        nonlocal running, max_running
        async with lock:
            running += 1
            if running > max_running:
                max_running = running
        await asyncio.sleep(0.01)
        async with lock:
            running -= 1
        return {C.WINNER: "A", C.LOG_TURN: "1"}

    with patch.object(sim_module, "_single_fight", side_effect=fake_fight):
        orig_get = sim_module.config_mod.CONFIG.get

        def fake_get(section, key, cast=str, fallback=None):
            if section == C.CONFIG_SIMULATION and key == C.CONFIG_RUNS:
                return 4
            if section == C.CONFIG_SIMULATION and key == C.CONFIG_CONCURRENT_RUNS:
                return 2
            return orig_get(section, key, cast, fallback)

        with patch.object(sim_module.config_mod.CONFIG, "get", side_effect=fake_get):
            out_file = tmp_path / "result.csv"
            ret = await sim_module.run_batch(out_file)

    assert max_running == 2
    assert ret == out_file
    assert out_file.exists()


@pytest.mark.asyncio
async def test_run_batch_exact_runs(tmp_path):
    calls = 0

    async def fake_fight(*args, **kwargs):
        nonlocal calls
        calls += 1
        return {C.WINNER: "A", C.LOG_TURN: "1"}

    with patch.object(sim_module, "_single_fight", side_effect=fake_fight):
        orig_get = sim_module.config_mod.CONFIG.get

        def fake_get(section, key, cast=str, fallback=None):
            if section == C.CONFIG_SIMULATION and key == C.CONFIG_RUNS:
                return 3
            if section == C.CONFIG_SIMULATION and key == C.CONFIG_CONCURRENT_RUNS:
                return 1
            return orig_get(section, key, cast, fallback)

        with patch.object(sim_module.config_mod.CONFIG, "get", side_effect=fake_get):
            await sim_module.run_batch(tmp_path / "result.csv")

    assert calls == 3


@pytest.mark.asyncio
async def test_run_batch_progress_callback(tmp_path):
    async def fake_fight(*args, **kwargs):
        await asyncio.sleep(0)
        return {C.WINNER: "A", C.LOG_TURN: "1"}

    progress_calls = []

    with patch.object(sim_module, "_single_fight", side_effect=fake_fight):
        orig_get = sim_module.config_mod.CONFIG.get

        def fake_get(section, key, cast=str, fallback=None):
            if section == C.CONFIG_SIMULATION and key == C.CONFIG_RUNS:
                return 2
            if section == C.CONFIG_SIMULATION and key == C.CONFIG_CONCURRENT_RUNS:
                return 1
            return orig_get(section, key, cast, fallback)

        with patch.object(sim_module.config_mod.CONFIG, "get", side_effect=fake_get):
            out_file = tmp_path / "prog.csv"

            def cb(done, total):
                progress_calls.append((done, total))

            await sim_module.run_batch(out_file, progress=cb)

    assert progress_calls == [(1, 2), (2, 2)]


@pytest.mark.asyncio
async def test_run_batch_flushes_each_completed_result(tmp_path):
    calls = 0
    first_progress_rows = []

    async def fake_fight(*args, **kwargs):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return {C.WINNER: "A" if calls == 1 else "B", C.LOG_TURN: str(calls)}

    out_file = tmp_path / "incremental.csv"

    def progress(done, total):
        if done == 1:
            with open(out_file, newline="") as fp:
                first_progress_rows.extend(csv.DictReader(fp))

    with patch.object(sim_module, "_single_fight", side_effect=fake_fight):
        orig_get = sim_module.config_mod.CONFIG.get

        def fake_get(section, key, cast=str, fallback=None):
            if section == C.CONFIG_SIMULATION and key == C.CONFIG_RUNS:
                return 2
            if section == C.CONFIG_SIMULATION and key == C.CONFIG_CONCURRENT_RUNS:
                return 1
            return orig_get(section, key, cast, fallback)

        with patch.object(sim_module.config_mod.CONFIG, "get", side_effect=fake_get):
            path = await sim_module.run_batch(out_file, progress=progress)

    assert path == out_file
    assert first_progress_rows == [
        {
            C.WINNER: "A",
            C.LOG_TURN: "1",
            C.LOG_P2_FALLBACK_TURNS: "0",
            C.LOG_P2_FALLBACK_USED: "false",
            **_display_columns(),
        }
    ]

    with open(out_file, newline="") as fp:
        final_rows = list(csv.DictReader(fp))
    assert final_rows == [
        {
            C.WINNER: "A",
            C.LOG_TURN: "1",
            C.LOG_P2_FALLBACK_TURNS: "0",
            C.LOG_P2_FALLBACK_USED: "false",
            **_display_columns(),
        },
        {
            C.WINNER: "B",
            C.LOG_TURN: "2",
            C.LOG_P2_FALLBACK_TURNS: "0",
            C.LOG_P2_FALLBACK_USED: "false",
            **_display_columns(),
        },
    ]


@pytest.mark.asyncio
async def test_run_batch_writes_rows_in_run_index_order_with_out_of_order_completion(tmp_path):
    call_index = 0
    delays = [0.03, 0, 0.01]
    progress_calls = []
    first_progress_rows = []
    out_file = tmp_path / "ordered.csv"

    async def fake_fight(*args, fight_rng=None, **kwargs):
        nonlocal call_index
        run_index = call_index
        call_index += 1
        await asyncio.sleep(delays[run_index])
        return {C.WINNER: str(run_index), C.LOG_TURN: str(run_index + 1)}

    def progress(done, total):
        progress_calls.append((done, total))
        if done == 1:
            with open(out_file, newline="") as fp:
                first_progress_rows.extend(csv.DictReader(fp))

    with (
        patch.object(sim_module, "_single_fight", side_effect=fake_fight),
        _patch_batch_config(runs=3, concurrency=3, seed_value=99),
    ):
        path = await sim_module.run_batch(out_file, progress=progress)

    assert path == out_file
    assert first_progress_rows == []
    assert progress_calls == [(1, 3), (2, 3), (3, 3)]
    with open(out_file, newline="") as fp:
        rows = list(csv.DictReader(fp))
    assert rows == [
        {
            C.WINNER: "0",
            C.LOG_TURN: "1",
            C.LOG_P2_FALLBACK_TURNS: "0",
            C.LOG_P2_FALLBACK_USED: "false",
            **_display_columns(),
        },
        {
            C.WINNER: "1",
            C.LOG_TURN: "2",
            C.LOG_P2_FALLBACK_TURNS: "0",
            C.LOG_P2_FALLBACK_USED: "false",
            **_display_columns(),
        },
        {
            C.WINNER: "2",
            C.LOG_TURN: "3",
            C.LOG_P2_FALLBACK_TURNS: "0",
            C.LOG_P2_FALLBACK_USED: "false",
            **_display_columns(),
        },
    ]


async def _run_seeded_fake_batch(tmp_path, seed_value, delays, filename):
    call_index = 0

    async def fake_fight(*args, fight_rng=None, **kwargs):
        nonlocal call_index
        run_index = call_index
        call_index += 1
        first = fight_rng.random()
        second = fight_rng.random()
        await asyncio.sleep(delays[run_index])
        return {
            C.WINNER: C.FIGHTER_A if first < 0.5 else C.FIGHTER_B,
            C.LOG_TURN: str(int(second * 1000)),
        }

    out_file = tmp_path / filename
    with (
        patch.object(sim_module, "_single_fight", side_effect=fake_fight),
        _patch_batch_config(runs=len(delays), concurrency=len(delays), seed_value=seed_value),
    ):
        await sim_module.run_batch(out_file)

    with open(out_file, newline="") as fp:
        return list(csv.DictReader(fp))


@pytest.mark.asyncio
async def test_run_batch_is_deterministic_across_varied_completion_order(tmp_path):
    delays_a = [0.03, 0, 0.01, 0.02]
    delays_b = [0, 0.03, 0.02, 0.01]

    rows_a = await _run_seeded_fake_batch(tmp_path, 1234, delays_a, "seeded_a.csv")
    rows_b = await _run_seeded_fake_batch(tmp_path, 1234, delays_b, "seeded_b.csv")

    assert rows_a == rows_b


@pytest.mark.asyncio
async def test_run_batch_base_seed_changes_per_fight_rng_streams(tmp_path):
    delays = [0, 0, 0, 0]

    rows_a = await _run_seeded_fake_batch(tmp_path, 1234, delays, "seeded_a.csv")
    rows_b = await _run_seeded_fake_batch(tmp_path, 4321, delays, "seeded_b.csv")

    assert rows_a != rows_b


@pytest.mark.asyncio
async def test_run_batch_handles_errors(tmp_path):
    async def failing_fight(*args, **kwargs):
        raise RuntimeError("boom")

    with patch.object(sim_module, "_single_fight", side_effect=failing_fight):
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
            out_file = tmp_path / "err.csv"
            path = await sim_module.run_batch(out_file)

    assert path == out_file
    with open(out_file, newline="") as fp:
        rows = list(csv.DictReader(fp))

    assert len(rows) == 2
    assert all(row[C.WINNER] == "error" for row in rows)
    assert mock_exc.call_count == 2


@pytest.mark.asyncio
async def test_run_batch_zero_runs(tmp_path):
    out_file = tmp_path / "empty.csv"

    with patch.object(sim_module, "_single_fight", side_effect=RuntimeError("should not run")) as mock_fight:
        orig_get = sim_module.config_mod.CONFIG.get

        def fake_get(section, key, cast=str, fallback=None):
            if section == C.CONFIG_SIMULATION and key == C.CONFIG_RUNS:
                return 0
            if section == C.CONFIG_SIMULATION and key == C.CONFIG_CONCURRENT_RUNS:
                return 1
            return orig_get(section, key, cast, fallback)

        with patch.object(sim_module.config_mod.CONFIG, "get", side_effect=fake_get):
            path = await sim_module.run_batch(out_file)

    assert path == out_file
    assert out_file.exists()
    with open(out_file, newline="") as fp:
        reader = csv.DictReader(fp)
        rows = list(reader)

    assert reader.fieldnames == [
        C.WINNER,
        C.LOG_TURN,
        C.LOG_P2_FALLBACK_TURNS,
        C.LOG_P2_FALLBACK_USED,
        C.LOG_FIGHTER_A_DISPLAY_NAME,
        C.LOG_FIGHTER_B_DISPLAY_NAME,
        C.LOG_WINNER_DISPLAY_NAME,
    ]
    assert rows == []
    mock_fight.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrency", [0, -1])
async def test_run_batch_invalid_concurrency_raises_without_starting_fight(tmp_path, concurrency):
    out_file = tmp_path / "invalid_concurrency.csv"
    mock_fight = AsyncMock(return_value={C.WINNER: "A", C.LOG_TURN: "1"})
    orig_get = sim_module.config_mod.CONFIG.get

    def fake_get(section, key, cast=str, fallback=None):
        if section == C.CONFIG_SIMULATION and key == C.CONFIG_RUNS:
            return 1
        if section == C.CONFIG_SIMULATION and key == C.CONFIG_CONCURRENT_RUNS:
            return concurrency
        return orig_get(section, key, cast, fallback)

    with (
        patch.object(sim_module, "_single_fight", new=mock_fight),
        patch.object(sim_module.config_mod.CONFIG, "get", side_effect=fake_get),
    ):
        with pytest.raises(ValueError, match="concurrent_runs"):
            await asyncio.wait_for(sim_module.run_batch(out_file), timeout=0.1)

    assert not out_file.exists()
    mock_fight.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_batch_negative_runs_raises_without_starting_fight(tmp_path):
    out_file = tmp_path / "negative_runs.csv"
    mock_fight = AsyncMock(return_value={C.WINNER: "A", C.LOG_TURN: "1"})
    orig_get = sim_module.config_mod.CONFIG.get

    def fake_get(section, key, cast=str, fallback=None):
        if section == C.CONFIG_SIMULATION and key == C.CONFIG_RUNS:
            return -1
        if section == C.CONFIG_SIMULATION and key == C.CONFIG_CONCURRENT_RUNS:
            return 1
        return orig_get(section, key, cast, fallback)

    with (
        patch.object(sim_module, "_single_fight", new=mock_fight),
        patch.object(sim_module.config_mod.CONFIG, "get", side_effect=fake_get),
    ):
        with pytest.raises(ValueError, match="runs"):
            await asyncio.wait_for(sim_module.run_batch(out_file), timeout=0.1)

    assert not out_file.exists()
    mock_fight.assert_not_awaited()


def test_summarize_batch_csv_counts_error_rows(tmp_path):
    out_file = tmp_path / "summary.csv"
    with out_file.open("w", newline="") as fp:
        writer = csv.DictWriter(
            fp,
            fieldnames=[
                C.WINNER,
                C.LOG_TURN,
                C.LOG_P2_FALLBACK_TURNS,
                C.LOG_P2_FALLBACK_USED,
            ],
        )
        writer.writeheader()
        writer.writerows(
            [
                {
                    C.WINNER: "A",
                    C.LOG_TURN: "1",
                    C.LOG_P2_FALLBACK_TURNS: "2",
                    C.LOG_P2_FALLBACK_USED: "true",
                },
                {
                    C.WINNER: C.BATCH_ERROR_WINNER,
                    C.LOG_TURN: "0",
                    C.LOG_P2_FALLBACK_TURNS: "0",
                    C.LOG_P2_FALLBACK_USED: "false",
                },
            ]
        )

    summary = sim_module.summarize_batch_csv(out_file, total_runs=3)

    assert summary.path == out_file
    assert summary.total_runs == 3
    assert summary.total_rows == 2
    assert summary.completed_rows == 1
    assert summary.error_rows == 1
    assert summary.fallback_rows == 1
    assert summary.fallback_turns == 2
    assert summary.has_errors


@pytest.mark.asyncio
async def test_run_batch_writes_fallback_columns_and_summary_counts(tmp_path):
    async def fake_fight(*args, **kwargs):
        return {
            C.WINNER: C.DRAW,
            C.LOG_TURN: "3",
            C.LOG_P2_FALLBACK_TURNS: "1",
            C.LOG_P2_FALLBACK_USED: "true",
        }

    out_file = tmp_path / "fallback.csv"
    with (
        patch.object(sim_module, "_single_fight", side_effect=fake_fight),
        _patch_batch_config(runs=1, concurrency=1),
    ):
        path = await sim_module.run_batch(out_file)

    with open(path, newline="") as fp:
        rows = list(csv.DictReader(fp))

    assert rows == [
        {
            C.WINNER: C.DRAW,
            C.LOG_TURN: "3",
            C.LOG_P2_FALLBACK_TURNS: "1",
            C.LOG_P2_FALLBACK_USED: "true",
            **_display_columns(),
        }
    ]
    summary = sim_module.summarize_batch_csv(path)
    assert summary.error_rows == 0
    assert summary.fallback_rows == 1
    assert summary.fallback_turns == 1


@pytest.mark.asyncio
async def test_run_batch_fail_closed_p2_exception_writes_error_row(tmp_path):
    async def failing_fight(*args, **kwargs):
        raise JudgePhase2FailureError("Judge Phase 2 failed after retries under fail_closed policy")

    out_file = tmp_path / "fail_closed.csv"
    with (
        patch.object(sim_module, "_single_fight", side_effect=failing_fight),
        _patch_batch_config(runs=1, concurrency=1),
        patch.object(sim_module.logger, "exception"),
    ):
        path = await sim_module.run_batch(out_file)

    with open(path, newline="") as fp:
        rows = list(csv.DictReader(fp))

    assert rows == [
        {
            C.WINNER: C.BATCH_ERROR_WINNER,
            C.LOG_TURN: "0",
            C.LOG_P2_FALLBACK_TURNS: "0",
            C.LOG_P2_FALLBACK_USED: "false",
            **_display_columns(),
        }
    ]


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
