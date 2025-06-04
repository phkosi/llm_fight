"""Typer‑powered CLI front‑end."""
import typer

app = typer.Typer()

from pathlib import Path

@app.command()
def simulate():
    """Run self‑play batch using config.ini parameters."""
    import asyncio
    from .simulation import run_batch

    path = asyncio.run(run_batch())
    typer.echo(f"Simulation saved to {path}")

@app.command()
def play():
    """Run a single fight and print the winner."""
    import asyncio
    from .simulation import _single_fight
    from .engine import constants as C

    result = asyncio.run(_single_fight())
    typer.echo(f"Winner: {result.get(C.WINNER, C.DRAW)}")

# Removed if __name__ == "__main__": app() and unconditional app()
