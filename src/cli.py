"""Typer‑powered CLI front‑end."""

import typer

app = typer.Typer()

from pathlib import Path


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
        help="Path to configuration file (llmfight.ini by default)",
    ),
):
    """Run self‑play batch using config.ini parameters."""
    from . import config as config_module

    if config is not None:
        config_module.CONFIG = config_module.Config(config)

    import asyncio
    from .simulation import run_batch

    path = asyncio.run(run_batch(output_csv))
    typer.echo(f"Simulation saved to {path}")


@app.command()
def play(
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to configuration file (llmfight.ini by default)",
    ),
):
    """Run a single fight and print the winner."""
    from . import config as config_module

    if config is not None:
        config_module.CONFIG = config_module.Config(config)

    import asyncio
    from .simulation import _single_fight
    from .engine import constants as C

    result = asyncio.run(_single_fight())
    typer.echo(f"Winner: {result.get(C.WINNER, C.DRAW)}")


# Removed if __name__ == "__main__": app() and unconditional app()
