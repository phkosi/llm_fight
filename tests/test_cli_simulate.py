import csv
from pathlib import Path
from unittest.mock import AsyncMock, patch

from click import unstyle
from typer.testing import CliRunner

from llm_fight.cli import app
from llm_fight.engine import constants as C
from llm_fight.utils.token_counter import PromptBudgetError


def _write_batch_csv(path, rows):
    with path.open("w", newline="") as fp:
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
        writer.writerows(rows)


def _plain_cli_output(result):
    return " ".join(unstyle(result.output).split())


def test_cli_simulate(tmp_path):
    runner = CliRunner()
    dummy = tmp_path / "dummy.csv"
    _write_batch_csv(dummy, [{C.WINNER: "A", C.LOG_TURN: "1"}])
    with (
        patch("llm_fight.simulation.run_batch", new=AsyncMock(return_value=dummy)) as mock_run_batch,
        patch("llm_fight.cli.ping_ollama", new=AsyncMock()),
    ):
        result = runner.invoke(app, ["simulate", "--output-csv", "out.csv"])
    assert result.exit_code == 0
    mock_run_batch.assert_called_once_with(Path("out.csv"), fighter_a_section=None, fighter_b_section=None)
    assert "Simulation saved to" in result.output


def test_cli_simulate_verbose(tmp_path):
    runner = CliRunner()
    dummy = tmp_path / "dummy.csv"
    _write_batch_csv(
        dummy,
        [
            {
                C.WINNER: "A",
                C.LOG_TURN: "1",
                C.LOG_P2_FALLBACK_TURNS: "1",
                C.LOG_P2_FALLBACK_USED: "true",
            }
        ],
    )
    with (
        patch(
            "llm_fight.simulation.run_batch",
            new=AsyncMock(return_value=dummy),
        ) as mock_run_batch,
        patch("llm_fight.cli.render") as mock_render,
        patch("llm_fight.cli.ping_ollama", new=AsyncMock()),
    ):
        mock_render.RICH_AVAILABLE = True
        mock_render.make_summary_table.return_value = "table"
        result = runner.invoke(app, ["simulate", "--verbose"])
    assert result.exit_code == 0
    assert mock_run_batch.call_args.kwargs["progress"] is not None
    mock_render.make_summary_table.assert_called_once()
    rows_arg = mock_render.make_summary_table.call_args.args[0]
    assert rows_arg[0][C.LOG_P2_FALLBACK_USED] == "true"


def test_cli_simulate_with_config(tmp_path):
    runner = CliRunner()
    cfg = tmp_path / "alt.ini"
    cfg.write_text("[SIMULATION]\nseed = 77\n")

    async def fake_run_batch(output_csv, fighter_a_section=None, fighter_b_section=None):
        from llm_fight.config import CONFIG

        assert CONFIG.path == cfg
        assert CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_SEED, int) == 77
        dummy = tmp_path / "dummy.csv"
        _write_batch_csv(dummy, [{C.WINNER: "A", C.LOG_TURN: "1"}])
        return dummy

    from llm_fight import config as config_mod

    original = config_mod.CONFIG
    with (
        patch("llm_fight.engine.logger.update_logger_level") as mock_update,
        patch(
            "llm_fight.simulation.run_batch",
            new=AsyncMock(side_effect=fake_run_batch),
        ) as mock_run_batch,
        patch("llm_fight.cli.ping_ollama", new=AsyncMock()),
    ):
        result = runner.invoke(app, ["simulate", "--config", str(cfg)])
    assert result.exit_code == 0
    mock_run_batch.assert_called_once_with(Path("sim_results.csv"), fighter_a_section=None, fighter_b_section=None)
    mock_update.assert_called_once()
    config_mod.CONFIG = original


def test_cli_simulate_scopes_configs_across_sequential_invocations(tmp_path):
    runner = CliRunner()
    cfg_one = tmp_path / "one.ini"
    cfg_two = tmp_path / "two.ini"
    cfg_one.write_text("[SIMULATION]\nseed = 11\n", encoding="utf-8")
    cfg_two.write_text("[SIMULATION]\nseed = 22\n", encoding="utf-8")
    seen = []

    async def fake_run_batch(output_csv, fighter_a_section=None, fighter_b_section=None):
        from llm_fight import config as config_mod

        seen.append((config_mod.CONFIG.path, config_mod.CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_SEED, int)))
        dummy = tmp_path / f"dummy_{len(seen)}.csv"
        _write_batch_csv(dummy, [{C.WINNER: "A", C.LOG_TURN: "1"}])
        return dummy

    from llm_fight import config as config_mod

    original = config_mod.CONFIG
    with (
        patch("llm_fight.simulation.run_batch", new=AsyncMock(side_effect=fake_run_batch)),
        patch("llm_fight.cli.ping_ollama", new=AsyncMock()),
    ):
        first = runner.invoke(app, ["simulate", "--config", str(cfg_one)])
        assert config_mod.CONFIG is original
        second = runner.invoke(app, ["simulate", "--config", str(cfg_two)])
        assert config_mod.CONFIG is original

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert seen == [(cfg_one, 11), (cfg_two, 22)]


def test_cli_simulate_overrides_do_not_leak_without_config(tmp_path):
    runner = CliRunner()

    async def fake_run_batch(output_csv, fighter_a_section=None, fighter_b_section=None):
        from llm_fight import config as config_mod

        assert config_mod.CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_RUNS, int) == 3
        assert config_mod.CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, int) == 4
        dummy = tmp_path / "dummy.csv"
        _write_batch_csv(dummy, [{C.WINNER: "A", C.LOG_TURN: "1"}])
        return dummy

    from llm_fight import config as config_mod

    original = config_mod.CONFIG
    original_runs = original.get(C.CONFIG_SIMULATION, C.CONFIG_RUNS, int)
    original_max_turns = original.get(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, int)
    with (
        patch("llm_fight.simulation.run_batch", new=AsyncMock(side_effect=fake_run_batch)),
        patch("llm_fight.cli.ping_ollama", new=AsyncMock()),
    ):
        result = runner.invoke(app, ["simulate", "--runs", "3", "--max-turns", "4"])

    assert result.exit_code == 0
    assert config_mod.CONFIG is original
    assert original.get(C.CONFIG_SIMULATION, C.CONFIG_RUNS, int) == original_runs
    assert original.get(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, int) == original_max_turns


def test_cli_simulate_fighter_options(tmp_path):
    runner = CliRunner()
    dummy = tmp_path / "dummy.csv"
    _write_batch_csv(dummy, [{C.WINNER: "A", C.LOG_TURN: "1"}])
    with (
        patch(
            "llm_fight.simulation.run_batch",
            new=AsyncMock(return_value=dummy),
        ) as mock_run_batch,
        patch("llm_fight.cli.ping_ollama", new=AsyncMock()),
    ):
        result = runner.invoke(app, ["simulate", "--fighter-a", "X", "--fighter-b", "Y"])
    assert result.exit_code == 0
    mock_run_batch.assert_called_once_with(Path("sim_results.csv"), fighter_a_section="X", fighter_b_section="Y")


def test_cli_simulate_smoke_overrides(tmp_path):
    runner = CliRunner()
    dummy = tmp_path / "dummy.csv"
    _write_batch_csv(dummy, [{C.WINNER: "A", C.LOG_TURN: "1"}])

    async def fake_run_batch(output_csv, fighter_a_section=None, fighter_b_section=None):
        from llm_fight.config import CONFIG

        assert CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_RUNS, int) == 3
        assert CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, int) == 4
        return dummy

    from llm_fight import config as config_mod

    original = config_mod.CONFIG
    with (
        patch("llm_fight.simulation.run_batch", new=AsyncMock(side_effect=fake_run_batch)),
        patch("llm_fight.cli.ping_ollama", new=AsyncMock()),
    ):
        result = runner.invoke(app, ["simulate", "--runs", "3", "--max-turns", "4"])

    assert result.exit_code == 0
    config_mod.CONFIG = original


def test_cli_simulate_exits_nonzero_for_all_error_rows(tmp_path):
    runner = CliRunner()
    dummy = tmp_path / "errors.csv"
    _write_batch_csv(
        dummy,
        [
            {C.WINNER: C.BATCH_ERROR_WINNER, C.LOG_TURN: "0"},
            {C.WINNER: C.BATCH_ERROR_WINNER, C.LOG_TURN: "0"},
        ],
    )

    with (
        patch("llm_fight.simulation.run_batch", new=AsyncMock(return_value=dummy)),
        patch("llm_fight.cli.ping_ollama", new=AsyncMock()),
    ):
        result = runner.invoke(app, ["simulate", "--runs", "2"])

    assert result.exit_code == 1
    assert "Simulation saved to" in result.output
    assert "2 error row(s)" in result.output


def test_cli_simulate_exits_nonzero_for_mixed_error_rows(tmp_path):
    runner = CliRunner()
    dummy = tmp_path / "mixed.csv"
    _write_batch_csv(
        dummy,
        [
            {C.WINNER: "A", C.LOG_TURN: "1"},
            {C.WINNER: C.BATCH_ERROR_WINNER, C.LOG_TURN: "0"},
        ],
    )

    with (
        patch("llm_fight.simulation.run_batch", new=AsyncMock(return_value=dummy)),
        patch("llm_fight.cli.ping_ollama", new=AsyncMock()),
    ):
        result = runner.invoke(app, ["simulate", "--runs", "2"])

    assert result.exit_code == 1
    assert "1 error row(s)" in result.output
    assert "1 completed successfully" in result.output


def test_cli_simulate_continue_on_error_exits_zero_with_warning(tmp_path):
    runner = CliRunner()
    dummy = tmp_path / "mixed.csv"
    _write_batch_csv(
        dummy,
        [
            {C.WINNER: "A", C.LOG_TURN: "1"},
            {C.WINNER: C.BATCH_ERROR_WINNER, C.LOG_TURN: "0"},
        ],
    )

    with (
        patch("llm_fight.simulation.run_batch", new=AsyncMock(return_value=dummy)),
        patch("llm_fight.cli.ping_ollama", new=AsyncMock()),
    ):
        result = runner.invoke(app, ["simulate", "--runs", "2", "--continue-on-error"])

    assert result.exit_code == 0
    assert "1 error row(s)" in result.output


def test_cli_simulate_prompt_budget_error_is_actionable():
    runner = CliRunner()
    error = PromptBudgetError(
        phase=C.PROMPT_PHASE_FIGHTER_ACTION,
        prompt_tokens=700,
        context_limit=600,
        requested_max_tokens=64,
        reserved_completion=64,
        log_window_setting=C.CONFIG_FIGHTER_LOG_WINDOW,
    )

    with (
        patch("llm_fight.simulation.run_batch", new=AsyncMock(side_effect=error)),
        patch("llm_fight.cli.ping_ollama", new=AsyncMock()),
    ):
        result = runner.invoke(app, ["simulate"])

    assert result.exit_code != 0
    assert "Prompt budget exceeded for fighter action" in result.output
    assert C.CONFIG_FIGHTER_LOG_WINDOW in result.output


def test_cli_simulate_invalid_config_fails_before_ping(tmp_path):
    runner = CliRunner()
    cfg = tmp_path / "bad_batch.ini"
    cfg.write_text("[SIMULATION]\nconcurrent_runs = 0\n")

    from llm_fight import config as config_mod

    original = config_mod.CONFIG
    ping = AsyncMock()
    run_batch = AsyncMock()
    try:
        with (
            patch("llm_fight.cli.ping_ollama", new=ping),
            patch("llm_fight.simulation.run_batch", new=run_batch),
        ):
            result = runner.invoke(app, ["simulate", "--config", str(cfg)])
    finally:
        config_mod.CONFIG = original

    assert result.exit_code != 0
    assert "concurrent_runs" in result.output
    ping.assert_not_awaited()
    run_batch.assert_not_awaited()


def test_cli_simulate_negative_runs_override_fails_before_ping():
    runner = CliRunner()
    ping = AsyncMock()

    with patch("llm_fight.cli.ping_ollama", new=ping):
        result = runner.invoke(app, ["simulate", "--runs", "-1"])

    assert result.exit_code != 0
    assert "--runs must be 0 or greater" in _plain_cli_output(result)
    ping.assert_not_awaited()
