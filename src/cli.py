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

# Removed if __name__ == "__main__": app() and unconditional app()
