"""Typer-powered CLI front-end."""

import asyncio
import configparser
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import aiohttp
import typer
from click import ClickException

from .agents import ping_ollama
from .engine import constants as C
from .engine import render
from .judge import JudgePhase2FailureError
from .utils.token_counter import PromptBudgetError

app = typer.Typer()


@contextmanager
def _command_runtime(
    config_path: Path | None,
    *,
    runs: int | None = None,
    max_turns: int | None = None,
    require_model: bool = False,
):
    from . import config as config_mod
    from . import rng

    runtime_config = _load_config(config_path)
    previous_rng_state = rng.get_state()
    try:
        with config_mod.use_config(runtime_config):
            _apply_simulation_overrides(runtime_config, runs=runs, max_turns=max_turns)
            if require_model:
                try:
                    runtime_config.get_ollama_model()
                except ValueError as exc:
                    raise ClickException(str(exc)) from exc
            rng.seed_from_config(runtime_config)
            yield runtime_config
    finally:
        rng.set_state(previous_rng_state)


def _load_config(config_path: Path | None):
    from . import config as config_mod

    if config_path is None:
        config_path = Path("llmfight.ini")
    elif not config_path.exists():
        raise ClickException(f"Config file not found: {config_path}")

    try:
        return config_mod.Config(config_path)
    except configparser.Error as exc:
        raise ClickException(f"Could not read config file {config_path}: {exc}") from exc


def _apply_simulation_overrides(runtime_config, runs: int | None = None, max_turns: int | None = None) -> None:
    if runs is None and max_turns is None:
        return

    if runs is not None:
        if runs < 0:
            raise ClickException("--runs must be 0 or greater")
        runtime_config.set(C.CONFIG_SIMULATION, C.CONFIG_RUNS, runs)
    if max_turns is not None:
        if max_turns < 1:
            raise ClickException("--max-turns must be 1 or greater")
        runtime_config.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, max_turns)


def _run_async(coro):
    try:
        return asyncio.run(coro)
    except JudgePhase2FailureError as exc:
        raise ClickException(str(exc)) from exc
    except PromptBudgetError as exc:
        raise ClickException(str(exc)) from exc
    except ValueError as exc:
        raise ClickException(str(exc)) from exc
    except ConnectionError as exc:
        raise ClickException(str(exc)) from exc
    except (TimeoutError, aiohttp.ClientError) as exc:
        raise ClickException(
            f"Ollama request failed: {exc}. Make sure Ollama is running, the model is pulled, "
            "and ollama_api_url or API_URL points to the correct endpoint."
        ) from exc
    except RuntimeError as exc:
        if "Validation/JSON parsing failed" in str(exc):
            raise ClickException(
                f"LLM output could not be parsed after retries: {exc}. "
                "Try a stronger model, increasing max_tokens_judge, or increasing invalid_output_retries."
            ) from exc
        raise


def _validate_batch_config() -> tuple[int, int]:
    from .simulation import validate_batch_settings

    try:
        return validate_batch_settings()
    except ValueError as exc:
        raise ClickException(str(exc)) from exc


def _batch_error_warning(summary) -> str:
    return (
        f"Batch produced {summary.error_rows} error row(s) out of {summary.total_rows} written row(s); "
        f"{summary.completed_rows} completed successfully. Use --continue-on-error to keep exit code 0 "
        "while preserving the CSV."
    )


def _format_winner_label(result: dict, fighter_display_names: dict[str, str] | None = None) -> str:
    winner = result.get(C.WINNER, C.DRAW)
    display_name = result.get(C.LOG_WINNER_DISPLAY_NAME, "")
    if not display_name and fighter_display_names:
        display_name = fighter_display_names.get(winner, "")
    display_name = " ".join(str(display_name or "").strip().split())
    if winner in {C.FIGHTER_A, C.FIGHTER_B} and display_name and display_name != winner:
        return f"{winner} ({display_name})"
    return str(winner)


@dataclass
class _PlayRenderState:
    console: Any
    simple_output: bool
    rendered_turns: set[int] = field(default_factory=set)
    token_metadata: list[dict[str, Any]] = field(default_factory=list)
    fighter_display_names: dict[str, str] = field(default_factory=dict)


def _capture_fighter_display_names(state: _PlayRenderState, fighters: dict[str, Any]) -> None:
    for fighter_id, fighter_state in fighters.items():
        if isinstance(fighter_state, dict):
            display_name = str(fighter_state.get(C.DISPLAY_NAME, "")).strip()
            if display_name:
                state.fighter_display_names[fighter_id] = display_name


def _handle_play_event(state: _PlayRenderState, event) -> None:
    if event.name == C.FIGHT_EVENT_TOKEN_METADATA:
        metadata = event.data.get("metadata", {})
        if metadata:
            state.token_metadata.append(metadata)
        return
    if event.name == C.FIGHT_EVENT_FIGHTERS_READY:
        fighters = event.data.get("fighters", {})
        _capture_fighter_display_names(state, fighters)
        state.console.print(render.make_fighter_design_view(fighters, simple=state.simple_output))
        return
    if event.name == C.FIGHT_EVENT_TURN_COMPLETE:
        turn = event.data.get("turn")
        if turn is not None:
            state.rendered_turns.add(turn.turn)
            state.console.print(render.make_turn_table(turn, simple=state.simple_output))
        return
    if event.name == C.FIGHT_EVENT_FIGHT_COMPLETE:
        return
    if event.name == C.FIGHT_EVENT_LLM_OUTPUT_RETRY:
        state.console.print(render.format_fight_event_status(event))
        return
    if state.simple_output:
        state.console.print(render.format_fight_event_status(event))


def _handle_rich_play_event(state: _PlayRenderState, status, event) -> None:
    if event.name in {
        C.FIGHT_EVENT_TOKEN_METADATA,
        C.FIGHT_EVENT_FIGHTERS_READY,
        C.FIGHT_EVENT_TURN_COMPLETE,
        C.FIGHT_EVENT_FIGHT_COMPLETE,
    }:
        _handle_play_event(state, event)
        if event.name == C.FIGHT_EVENT_FIGHT_COMPLETE:
            status.update("Fight complete")
        return
    if event.name == C.FIGHT_EVENT_LLM_OUTPUT_RETRY:
        _handle_play_event(state, event)
        status.update(render.format_fight_event_status(event))
        return
    status.update(render.format_fight_event_status(event))


def _run_play_fight(fighter_a: str | None, fighter_b: str | None, state: _PlayRenderState):
    from .simulation import _single_fight

    if state.simple_output:
        return _run_async(
            _single_fight(
                fighter_a_section=fighter_a,
                fighter_b_section=fighter_b,
                return_log=True,
                on_event=lambda event: _handle_play_event(state, event),
            )
        )

    with state.console.status("Starting fight...", spinner="dots") as status:
        return _run_async(
            _single_fight(
                fighter_a_section=fighter_a,
                fighter_b_section=fighter_b,
                return_log=True,
                on_event=lambda event: _handle_rich_play_event(state, status, event),
            )
        )


def _flush_unrendered_play_turns(state: _PlayRenderState, log) -> None:
    for turn in log.turns:
        if turn.turn not in state.rendered_turns:
            state.console.print(render.make_turn_table(turn, simple=state.simple_output))


def _print_play_summary(state: _PlayRenderState, result: dict) -> None:
    if state.token_metadata:
        state.console.print(render.format_token_summary(state.token_metadata))
    typer.echo(f"Winner: {_format_winner_label(result, state.fighter_display_names)}")


def _make_simulation_progress(console):
    from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn

    progress = Progress(
        TextColumn("Simulating"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    )

    def update(done: int, total: int) -> None:
        if not progress.tasks:
            progress.add_task("runs", total=total)
        progress.update(cast(Any, 0), completed=done)

    return progress, update


def _run_simulation_batch(
    output_csv: Path,
    *,
    fighter_a: str | None,
    fighter_b: str | None,
    verbose: bool,
):
    from .simulation import run_batch

    if not verbose:
        return (
            _run_async(
                run_batch(
                    output_csv,
                    fighter_a_section=fighter_a,
                    fighter_b_section=fighter_b,
                )
            ),
            None,
        )

    console = render.Console()
    progress, progress_cb = _make_simulation_progress(console)
    with progress:
        path = _run_async(
            run_batch(
                output_csv,
                fighter_a_section=fighter_a,
                fighter_b_section=fighter_b,
                progress=progress_cb,
            )
        )
    return path, console


def _summarize_simulation(path: Path, *, total_runs: int, console) -> Any:
    import csv

    from .simulation import summarize_batch_csv

    summary = summarize_batch_csv(path, total_runs=total_runs)
    if console is not None:
        with open(path, newline="") as fp:
            rows = list(csv.DictReader(fp))
        table = render.make_summary_table(rows, total_runs=summary.total_runs)
        console.print(table)
    return summary


def _finish_simulation(path: Path, summary, *, continue_on_error: bool) -> None:
    typer.echo(f"Simulation saved to {path}")
    if summary.has_errors:
        typer.echo(_batch_error_warning(summary))
        if not continue_on_error:
            raise typer.Exit(1)


@app.command()
def simulate(
    output_csv: Path = typer.Option(
        Path("sim_results.csv"),
        "--output-csv",
        "-o",
        help="Path for the simulation CSV output",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to configuration file",
    ),
    fighter_a: str | None = typer.Option(
        None,
        "--fighter-a",
        "-A",
        help="INI section to use for fighter A",
    ),
    fighter_b: str | None = typer.Option(
        None,
        "--fighter-b",
        "-B",
        help="INI section to use for fighter B",
    ),
    runs: int | None = typer.Option(
        None,
        "--runs",
        help="Override [SIMULATION] runs for this invocation",
    ),
    max_turns: int | None = typer.Option(
        None,
        "--max-turns",
        help="Override [SIMULATION] max_turns for this invocation",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show progress bar and summary table",
    ),
    continue_on_error: bool = typer.Option(
        False,
        "--continue-on-error",
        help="Exit 0 even when batch simulations write winner=error rows",
    ),
):
    """Run self-play batch using llmfight.ini parameters."""
    from logging import CRITICAL

    from . import config as config_mod
    from .engine.logger import cli_logging, logger, update_logger_level

    if not render.RICH_AVAILABLE:
        raise ClickException("The 'rich' library is required for this command")

    with _command_runtime(config, runs=runs, max_turns=max_turns, require_model=True), cli_logging(update_level=False):
        batch_runs, _ = _validate_batch_config()
        update_logger_level()
        log_turns = config_mod.CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_LOG_COMBAT_TURNS, bool, fallback=False)
        if not verbose and not log_turns:
            logger.setLevel(CRITICAL)

        _run_async(ping_ollama())

        path, console = _run_simulation_batch(
            output_csv,
            fighter_a=fighter_a,
            fighter_b=fighter_b,
            verbose=verbose,
        )
        summary = _summarize_simulation(path, total_runs=batch_runs, console=console)
        _finish_simulation(path, summary, continue_on_error=continue_on_error)


@app.command("collect-trials")
def collect_trials(
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to configuration file",
    ),
    output_root: Path = typer.Option(
        Path("transcripts/trials"),
        "--output-root",
        help="Directory where timestamped trial artifacts are written",
    ),
    mode: str = typer.Option(
        C.FIGHTER_CREATION_MODE_CONFIGURED,
        "--mode",
        help="Trial mode: configured or generated",
    ),
    smoke: bool = typer.Option(
        False,
        "--smoke",
        help="Run only the first matrix cell for a quick harness smoke check",
    ),
    matrix: str = typer.Option(
        "full",
        "--matrix",
        help="Trial matrix: full, finalist, or default-finalization",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        help="Restrict trials to one tested model; required for --matrix default-finalization.",
    ),
    seeds: str | None = typer.Option(
        None,
        "--seeds",
        help="Comma-separated integer seeds. Defaults to 42 for full; 42,43,44 for finalist and default-finalization.",
    ),
):
    """Collect local parameter-trial artifacts and blind A/B packs."""
    from .engine.logger import cli_logging, update_logger_level
    from .trials import collect_trials as collect_trial_artifacts
    from .trials.specs import iter_trial_matrix, normalize_matrix, normalize_mode, parse_seed_list

    try:
        mode = normalize_mode(mode)
        matrix = normalize_matrix(matrix)
        parsed_seeds = parse_seed_list(seeds, matrix=matrix)
        parsed_models = (model,) if model else None
        iter_trial_matrix(mode, smoke=smoke, matrix=matrix, seeds=parsed_seeds, models=parsed_models)
    except ValueError as exc:
        raise ClickException(str(exc)) from exc

    with _command_runtime(config), cli_logging(update_level=False):
        update_logger_level()
        _run_async(ping_ollama())
        run_root = _run_async(
            collect_trial_artifacts(
                config_path=config,
                output_root=output_root,
                mode=mode,
                smoke=smoke,
                matrix=matrix,
                seeds=parsed_seeds,
                models=parsed_models,
            )
        )
    typer.echo(f"Trial artifacts saved to {run_root}")


@app.command("collect-profile-trials")
def collect_profile_trials(
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to configuration file",
    ),
    output_root: Path = typer.Option(
        Path("transcripts/profile_trials"),
        "--output-root",
        help="Directory where timestamped profile-evaluation artifacts are written",
    ),
    smoke: bool = typer.Option(
        False,
        "--smoke",
        help="Run only the first model/nudge profile sample",
    ),
):
    """Sample generated fighter profiles without running fights."""
    from .engine.logger import cli_logging, update_logger_level
    from .trials import collect_profile_trials as collect_profile_trial_artifacts

    with _command_runtime(config), cli_logging(update_level=False):
        update_logger_level()
        _run_async(ping_ollama())
        run_root = _run_async(
            collect_profile_trial_artifacts(
                config_path=config,
                output_root=output_root,
                smoke=smoke,
            )
        )
    typer.echo(f"Profile trial artifacts saved to {run_root}")


@app.command("analyze-trials")
def analyze_trials(
    run_roots: list[Path] = typer.Argument(
        ...,
        help="One or more trial run roots containing manifest.json and review_results.json",
    ),
    output_dir: Path | None = typer.Option(
        None,
        "--output-dir",
        help="Directory where analysis.json, analysis.md, settings.csv, and pairs.csv are written",
    ),
):
    """Analyze preserved trial artifacts without contacting Ollama."""
    from .trials import analyze_trials as analyze_trial_artifacts
    from .trials.analysis import TrialAnalysisError

    try:
        analysis_dir = analyze_trial_artifacts(run_roots, output_dir=output_dir)
    except TrialAnalysisError as exc:
        raise ClickException(str(exc)) from exc
    typer.echo(f"Trial analysis saved to {analysis_dir}")


@app.command()
def play(
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to configuration file",
    ),
    fighter_a: str | None = typer.Option(
        None,
        "--fighter-a",
        "-A",
        help="INI section to use for fighter A",
    ),
    fighter_b: str | None = typer.Option(
        None,
        "--fighter-b",
        "-B",
        help="INI section to use for fighter B",
    ),
    max_turns: int | None = typer.Option(
        None,
        "--max-turns",
        help="Override [SIMULATION] max_turns for this invocation",
    ),
    simple_output: bool = typer.Option(
        False,
        "--simple-output",
        "-so",
        help="Disable rich formatting and print plain text",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Print extra debug information",
    ),
):
    """Run a single fight and print the winner."""
    from logging import CRITICAL

    from .engine.logger import cli_logging, logger, update_logger_level

    if not render.RICH_AVAILABLE and not simple_output:
        raise ClickException("The 'rich' library is required for this command")

    with _command_runtime(config, max_turns=max_turns, require_model=True), cli_logging(update_level=False):
        update_logger_level()
        if not verbose:
            logger.setLevel(CRITICAL)

        _run_async(ping_ollama())

        console = render.Console()
        render_state = _PlayRenderState(console=console, simple_output=simple_output)
        result, log = _run_play_fight(fighter_a, fighter_b, render_state)
        _flush_unrendered_play_turns(render_state, log)
        _print_play_summary(render_state, result)
