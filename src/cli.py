"""Typer‑powered CLI front‑end."""

from pathlib import Path
import typer
from typing import Optional

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
):
    """Run self‑play batch using config.ini parameters."""
    import asyncio
    from . import config as config_mod
    from .engine.logger import update_logger_level

    if config is not None:
        config_mod.CONFIG = config_mod.Config(config)
        update_logger_level()

    from .simulation import run_batch

    path = asyncio.run(
        run_batch(
            output_csv,
            fighter_a_section=fighter_a,
            fighter_b_section=fighter_b,
        )
    )
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
):
    """Run a single fight and print the winner."""
    import asyncio
    from . import config as config_mod
    from .engine.logger import update_logger_level

    if config is not None:
        config_mod.CONFIG = config_mod.Config(config)
        update_logger_level()

    from .simulation import _single_fight
    from .engine import constants as C

    result = asyncio.run(
        _single_fight(
            fighter_a_section=fighter_a,
            fighter_b_section=fighter_b,
        )
    )
    typer.echo(f"Winner: {result.get(C.WINNER, C.DRAW)}")
