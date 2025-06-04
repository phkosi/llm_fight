"""Typer‑powered CLI front‑end."""
import asyncio
import typer

app = typer.Typer()

from pathlib import Path
from .simulation import run_batch

@app.command()
def simulate():
    """Run self‑play batch using config.ini parameters."""
    path = asyncio.run(run_batch())
    typer.echo(f"Simulation saved to {path}")

# Removed if __name__ == "__main__": app() and unconditional app()