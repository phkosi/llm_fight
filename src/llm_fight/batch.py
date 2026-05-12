"""Batch simulation orchestration and CSV summary helpers."""

from __future__ import annotations

import asyncio
import csv
import hashlib
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import config as config_mod
from .engine import constants as C
from .engine.logger import logger
from .utils.token_counter import PromptBudgetError

FightRunner = Callable[..., Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class BatchSummary:
    """Summary of rows written by a batch simulation CSV."""

    path: Path
    total_runs: int
    total_rows: int
    completed_rows: int
    error_rows: int
    fallback_rows: int = 0
    fallback_turns: int = 0

    @property
    def has_errors(self) -> bool:
        return self.error_rows > 0


def validate_batch_settings() -> tuple[int, int]:
    """Return validated ``(runs, concurrency)`` from the current config."""
    runs = config_mod.CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_RUNS, int)
    concurrency = config_mod.CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_CONCURRENT_RUNS, int, fallback=1)

    if runs < 0:
        raise ValueError("[SIMULATION] runs must be 0 or greater")
    if concurrency < 1:
        raise ValueError("[SIMULATION] concurrent_runs must be 1 or greater")
    return runs, concurrency


def summarize_batch_csv(output_csv: str | Path, total_runs: int | None = None) -> BatchSummary:
    """Read a batch CSV and summarize successful and failed rows."""
    csv_path = Path(output_csv)
    with csv_path.open(newline="") as fp:
        rows = list(csv.DictReader(fp))

    total_rows = len(rows)
    error_rows = sum(1 for row in rows if row.get(C.WINNER) == C.BATCH_ERROR_WINNER)
    completed_rows = total_rows - error_rows
    fallback_turns = sum(int(row.get(C.LOG_P2_FALLBACK_TURNS) or 0) for row in rows)
    fallback_rows = sum(1 for row in rows if (row.get(C.LOG_P2_FALLBACK_USED) or "").strip().lower() == "true")
    if total_runs is None:
        total_runs = total_rows

    return BatchSummary(
        path=csv_path,
        total_runs=total_runs,
        total_rows=total_rows,
        completed_rows=completed_rows,
        error_rows=error_rows,
        fallback_rows=fallback_rows,
        fallback_turns=fallback_turns,
    )


def _derive_fight_seed(batch_seed: int, run_index: int) -> int:
    """Derive a stable per-run seed without using process-randomized hashes."""
    digest = hashlib.sha256(f"{int(batch_seed)}:{int(run_index)}".encode("ascii")).digest()
    return int.from_bytes(digest[:8], "big")


def _batch_error_row() -> dict[str, str]:
    return {
        C.WINNER: C.BATCH_ERROR_WINNER,
        C.LOG_TURN: "0",
        C.LOG_P2_FALLBACK_TURNS: "0",
        C.LOG_P2_FALLBACK_USED: "false",
        C.LOG_FIGHTER_A_DISPLAY_NAME: "",
        C.LOG_FIGHTER_B_DISPLAY_NAME: "",
        C.LOG_WINNER_DISPLAY_NAME: "",
    }


def _fill_batch_row_defaults(row: dict[str, Any]) -> dict[str, Any]:
    row.setdefault(C.LOG_TURN, "0")
    row.setdefault(C.LOG_P2_FALLBACK_TURNS, "0")
    row.setdefault(C.LOG_P2_FALLBACK_USED, "false")
    row.setdefault(C.LOG_FIGHTER_A_DISPLAY_NAME, "")
    row.setdefault(C.LOG_FIGHTER_B_DISPLAY_NAME, "")
    row.setdefault(C.LOG_WINNER_DISPLAY_NAME, "")
    return row


async def run_batch(
    output_csv: str | Path = "sim_results.csv",
    fighter_a_section: str | None = None,
    fighter_b_section: str | None = None,
    progress: Callable[[int, int], None] | None = None,
    *,
    fight_runner: FightRunner,
) -> Path:
    """Run a batch of simulations and write the results to ``output_csv``."""
    runs, concurrency = validate_batch_settings()
    batch_seed = config_mod.CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_SEED, int)

    sem = asyncio.Semaphore(concurrency)

    async def sem_fight(run_index: int):
        async with sem:
            try:
                result = await fight_runner(
                    fighter_a_section=fighter_a_section,
                    fighter_b_section=fighter_b_section,
                    fight_rng=random.Random(_derive_fight_seed(batch_seed, run_index)),
                    run_index=run_index,
                )
                return run_index, result
            except PromptBudgetError:
                raise
            except Exception:
                logger.exception("_single_fight failed")
                return run_index, _batch_error_row()

    csv_path = Path(output_csv)
    with csv_path.open("w", newline="") as fp:
        writer = csv.DictWriter(
            fp,
            fieldnames=[
                C.WINNER,
                C.LOG_TURN,
                C.LOG_P2_FALLBACK_TURNS,
                C.LOG_P2_FALLBACK_USED,
                C.LOG_FIGHTER_A_DISPLAY_NAME,
                C.LOG_FIGHTER_B_DISPLAY_NAME,
                C.LOG_WINNER_DISPLAY_NAME,
            ],
        )
        writer.writeheader()
        fp.flush()

        tasks = [asyncio.create_task(sem_fight(run_index)) for run_index in range(runs)]
        buffered_results: dict[int, dict[str, Any]] = {}
        next_to_write = 0
        try:
            for idx, coro in enumerate(asyncio.as_completed(tasks), start=1):
                run_index, result = await coro
                buffered_results[run_index] = result
                while next_to_write in buffered_results:
                    row = _fill_batch_row_defaults(buffered_results.pop(next_to_write))
                    writer.writerow(row)
                    fp.flush()
                    next_to_write += 1
                if progress:
                    progress(idx, runs)
        except PromptBudgetError:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

    return csv_path
