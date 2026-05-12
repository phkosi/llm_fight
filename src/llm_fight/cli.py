"""Typer-powered CLI front-end."""

import asyncio
import configparser
from pathlib import Path
from typing import Optional

import aiohttp
import typer

from .engine import render
from .engine import constants as C
from .agents import ping_ollama
from click import ClickException

app = typer.Typer()


def _load_config(config_path: Optional[Path]) -> None:
    if config_path is None:
        return
    if not config_path.exists():
        raise ClickException(f"Config file not found: {config_path}")

    from . import config as config_mod

    try:
        config_mod.CONFIG = config_mod.Config(config_path)
    except configparser.Error as exc:
        raise ClickException(f"Could not read config file {config_path}: {exc}") from exc


def _apply_simulation_overrides(runs: Optional[int] = None, max_turns: Optional[int] = None) -> None:
    if runs is None and max_turns is None:
        return

    from . import config as config_mod

    if runs is not None:
        if runs < 0:
            raise ClickException("--runs must be 0 or greater")
        config_mod.CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_RUNS, runs)
    if max_turns is not None:
        if max_turns < 1:
            raise ClickException("--max-turns must be 1 or greater")
        config_mod.CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, max_turns)


def _run_async(coro):
    try:
        return asyncio.run(coro)
    except ValueError as exc:
        raise ClickException(str(exc)) from exc
    except ConnectionError as exc:
        raise ClickException(str(exc)) from exc
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        raise ClickException(
            f"Ollama request failed: {exc}. Make sure Ollama is running, the model is pulled, "
            "and ollama_api_url or API_URL points to the correct endpoint."
        ) from exc
    except RuntimeError as exc:
        if "Validation/JSON parsing failed" in str(exc):
            raise ClickException(
                f"LLM output could not be parsed after retries: {exc}. "
                "Try a stronger model, increasing max_tokens_judge, or increasing max_retries."
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


@app.command()
def simulate(
    output_csv: Path = typer.Option(
        Path("sim_results.csv"),
        "--output-csv",
        "-o",
        help="Path for the simulation CSV output",
    ),
    config: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to configuration file",
    ),
    fighter_a: Optional[str] = typer.Option(
        None,
        "--fighter-a",
        "-A",
        help="INI section to use for fighter A",
    ),
    fighter_b: Optional[str] = typer.Option(
        None,
        "--fighter-b",
        "-B",
        help="INI section to use for fighter B",
    ),
    runs: Optional[int] = typer.Option(
        None,
        "--runs",
        help="Override [SIMULATION] runs for this invocation",
    ),
    max_turns: Optional[int] = typer.Option(
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
    from .engine.logger import update_logger_level, logger

    if not render.RICH_AVAILABLE:
        raise ClickException("The 'rich' library is required for this command")

    _load_config(config)
    _apply_simulation_overrides(runs=runs, max_turns=max_turns)
    batch_runs, _ = _validate_batch_config()
    update_logger_level()
    log_turns = config_mod.CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_LOG_COMBAT_TURNS, bool, fallback=False)
    if not verbose and not log_turns:
        logger.setLevel(CRITICAL)

    _run_async(ping_ollama())

    from .simulation import run_batch, summarize_batch_csv

    progress_cb = None
    if verbose:
        from rich.progress import Progress, BarColumn, TextColumn, TaskProgressColumn

        console = render.Console()
        progress = Progress(
            TextColumn("Simulating"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        )

        def update(done: int, total: int) -> None:
            if not progress.tasks:
                progress.add_task("runs", total=total)
            progress.update(0, completed=done)

        progress_cb = update
        with progress:
            path = _run_async(
                run_batch(
                    output_csv,
                    fighter_a_section=fighter_a,
                    fighter_b_section=fighter_b,
                    progress=progress_cb,
                )
            )
    else:
        path = _run_async(
            run_batch(
                output_csv,
                fighter_a_section=fighter_a,
                fighter_b_section=fighter_b,
            )
        )

    summary = summarize_batch_csv(path, total_runs=batch_runs)

    if verbose:
        import csv

        with open(path, newline="") as fp:
            rows = list(csv.DictReader(fp))
        table = render.make_summary_table(rows, total_runs=summary.total_runs)
        console.print(table)

    typer.echo(f"Simulation saved to {path}")
    if summary.has_errors:
        typer.echo(_batch_error_warning(summary))
        if not continue_on_error:
            raise typer.Exit(1)


@app.command()
def play(
    config: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to configuration file",
    ),
    fighter_a: Optional[str] = typer.Option(
        None,
        "--fighter-a",
        "-A",
        help="INI section to use for fighter A",
    ),
    fighter_b: Optional[str] = typer.Option(
        None,
        "--fighter-b",
        "-B",
        help="INI section to use for fighter B",
    ),
    max_turns: Optional[int] = typer.Option(
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
    from .engine.logger import update_logger_level, logger

    if not render.RICH_AVAILABLE and not simple_output:
        raise ClickException("The 'rich' library is required for this command")

    _load_config(config)
    _apply_simulation_overrides(max_turns=max_turns)
    update_logger_level()
    if not verbose:
        logger.setLevel(CRITICAL)

    _run_async(ping_ollama())

    console = render.Console()
    rendered_turns: set[int] = set()
    token_metadata: list[dict] = []

    def handle_event(event) -> None:
        if event.name == C.FIGHT_EVENT_TOKEN_METADATA:
            metadata = event.data.get("metadata", {})
            if metadata:
                token_metadata.append(metadata)
            return
        if event.name == C.FIGHT_EVENT_FIGHTERS_READY:
            console.print(render.make_fighter_design_view(event.data.get("fighters", {}), simple=simple_output))
            return
        if event.name == C.FIGHT_EVENT_TURN_COMPLETE:
            turn = event.data.get("turn")
            if turn is not None:
                rendered_turns.add(turn.turn)
                console.print(render.make_turn_table(turn, simple=simple_output))
            return
        if event.name == C.FIGHT_EVENT_FIGHT_COMPLETE:
            return
        if simple_output:
            console.print(render.format_fight_event_status(event))

    from .simulation import _single_fight

    if simple_output:
        result, log = _run_async(
            _single_fight(
                fighter_a_section=fighter_a,
                fighter_b_section=fighter_b,
                return_log=True,
                on_event=handle_event,
            )
        )
    else:
        with console.status("Starting fight...", spinner="dots") as status:

            def rich_event_handler(event) -> None:
                if event.name in {
                    C.FIGHT_EVENT_TOKEN_METADATA,
                    C.FIGHT_EVENT_FIGHTERS_READY,
                    C.FIGHT_EVENT_TURN_COMPLETE,
                    C.FIGHT_EVENT_FIGHT_COMPLETE,
                }:
                    handle_event(event)
                    if event.name == C.FIGHT_EVENT_FIGHT_COMPLETE:
                        status.update("Fight complete")
                    return
                status.update(render.format_fight_event_status(event))

            result, log = _run_async(
                _single_fight(
                    fighter_a_section=fighter_a,
                    fighter_b_section=fighter_b,
                    return_log=True,
                    on_event=rich_event_handler,
                )
            )

    for turn in log.turns:
        if turn.turn not in rendered_turns:
            console.print(render.make_turn_table(turn, simple=simple_output))

    if token_metadata:
        console.print(render.format_token_summary(token_metadata))

    typer.echo(f"Winner: {result.get(C.WINNER, C.DRAW)}")
