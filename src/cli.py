"""Typer‑powered CLI front‑end."""

from pathlib import Path
from typing import Optional

import typer

from .engine import render
from .engine import constants as C
from .agents import ping_ollama
import asyncio
from click import ClickException


app = typer.Typer()


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
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show progress bar and summary table",
    ),
):
    """Run self‑play batch using config.ini parameters."""
    from logging import CRITICAL
    from . import config as config_mod
    from .engine.logger import update_logger_level, logger

    if not render.RICH_AVAILABLE:
        raise ClickException("The 'rich' library is required for this command")

    if config is not None:
        config_mod.CONFIG = config_mod.Config(config)
    update_logger_level()
    log_turns = config_mod.CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_LOG_COMBAT_TURNS, bool, fallback=False)
    if not verbose and not log_turns:
        logger.setLevel(CRITICAL)

    asyncio.run(ping_ollama())

    from .simulation import run_batch

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
            path = asyncio.run(
                run_batch(
                    output_csv,
                    fighter_a_section=fighter_a,
                    fighter_b_section=fighter_b,
                    progress=progress_cb,
                )
            )
    else:
        path = asyncio.run(
            run_batch(
                output_csv,
                fighter_a_section=fighter_a,
                fighter_b_section=fighter_b,
            )
        )

    if verbose:
        import csv

        with open(path, newline="") as fp:
            rows = list(csv.DictReader(fp))
        table = render.make_summary_table(rows)
        console.print(table)

    typer.echo(f"Simulation saved to {path}")


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
    from . import config as config_mod
    from .engine.logger import update_logger_level, logger

    if not render.RICH_AVAILABLE and not simple_output:
        raise ClickException("The 'rich' library is required for this command")

    if config is not None:
        config_mod.CONFIG = config_mod.Config(config)
    update_logger_level()
    log_turns = config_mod.CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_LOG_COMBAT_TURNS, bool, fallback=False)
    if not verbose and not log_turns:
        logger.setLevel(CRITICAL)

    asyncio.run(ping_ollama())

    from .simulation import _single_fight

    result, log = asyncio.run(
        _single_fight(
            fighter_a_section=fighter_a,
            fighter_b_section=fighter_b,
            return_log=True,
        )
    )
    console = render.Console()
    for turn in log.turns:
        table = render.make_turn_table(turn, simple=simple_output)
        console.print(table)

    typer.echo(f"Winner: {result.get(C.WINNER, C.DRAW)}")
