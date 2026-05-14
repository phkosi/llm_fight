"""Runner for local trial collection."""

from __future__ import annotations

import contextlib
import io
import random
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any, cast

from llm_fight import config as config_mod
from llm_fight import rng
from llm_fight.config import Config
from llm_fight.engine import constants as C

from .artifacts import create_run_root, relative_to_root, sha256_file, write_json
from .blind_packs import build_blind_packs, forbidden_terms, scan_forbidden_terms
from .specs import (
    DEFAULT_MAX_TURNS,
    DEFAULT_OLLAMA_NUM_CTX,
    TrialCellSpec,
    iter_trial_matrix,
    normalize_matrix,
    normalize_mode,
)
from .summaries import build_summary, render_summary_markdown, sanitized_error

FightRunner = Callable[..., Awaitable[Any]]


async def collect_trials(
    *,
    config_path: Path | None = None,
    output_root: Path = Path("transcripts/trials"),
    mode: str = C.FIGHTER_CREATION_MODE_CONFIGURED,
    smoke: bool = False,
    matrix: str = "full",
    seeds: Sequence[int] | None = None,
    models: Sequence[str] | None = None,
    timestamp: str | None = None,
    fight_runner: FightRunner | None = None,
) -> Path:
    """Collect a configured or generated trial matrix and write ignored artifacts."""
    trial_mode = normalize_mode(mode)
    trial_matrix = normalize_matrix(matrix)
    run_root = create_run_root(output_root, timestamp)
    cells = []
    specs = iter_trial_matrix(trial_mode, smoke=smoke, matrix=trial_matrix, seeds=seeds, models=models)
    for spec in specs:
        cells.append(await _collect_cell(run_root, config_path=config_path, spec=spec, fight_runner=fight_runner))

    pairs = build_blind_packs(run_root, cells)
    _scan_blind_pack_outputs(run_root, cells, pairs)
    manifest = {
        "schema_version": 1,
        "mode": trial_mode,
        "matrix": trial_matrix,
        "smoke": smoke,
        "seeds": sorted({cell["seed"] for cell in cells}),
        "models": sorted({cell["model"] for cell in cells}),
        "artifact_root": str(run_root),
        "cells": [_manifest_cell(cell) for cell in cells],
        "pairs": pairs,
    }
    write_json(run_root / "manifest.json", manifest)
    return run_root


async def _collect_cell(
    run_root: Path,
    *,
    config_path: Path | None,
    spec: TrialCellSpec,
    fight_runner: FightRunner | None,
) -> dict[str, Any]:
    cell_dir = run_root / "cells" / spec.cell_id
    transcript_dir = cell_dir / "transcripts"
    cell_dir.mkdir(parents=True, exist_ok=True)
    cell_config = materialize_cell_config(config_path, spec, cell_dir, transcript_dir)
    attempts: list[dict[str, Any]] = []
    stdout_chunks = []
    final_result: dict[str, Any] | None = None

    for attempt_number in (1, 2):
        fight_id = f"{spec.cell_id}-attempt-{attempt_number}"
        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()
        with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
            attempt = await _run_attempt(
                cell_config,
                spec,
                attempt_number=attempt_number,
                fight_id=fight_id,
                fight_runner=fight_runner,
            )
        stdout_chunks.append(_format_attempt_output(attempt_number, stdout_buffer.getvalue(), stderr_buffer.getvalue()))
        attempts.append(attempt)
        if attempt["status"] == "completed":
            final_result = cast(dict[str, Any], attempt.get("result", {}))
            break

    stdout_path = cell_dir / "stdout.txt"
    stdout_path.write_text("\n".join(stdout_chunks), encoding="utf-8")
    final_attempt = attempts[-1]
    status = str(final_attempt["status"])
    summary = build_summary(
        status=status,
        result=final_result,
        trace_path=Path(str(final_attempt["trace_path"])) if final_attempt.get("trace_path") else None,
        attempts=attempts,
    )
    result_payload = {
        "cell_id": spec.cell_id,
        "status": status,
        "result": final_result,
        "attempts": attempts,
    }
    result_path = cell_dir / "result.json"
    summary_json_path = cell_dir / "summary.json"
    summary_md_path = cell_dir / "summary.md"
    config_path_written = cell_dir / "config.ini"
    write_json(result_path, result_payload)
    write_json(summary_json_path, summary)
    summary_md_path.write_text(render_summary_markdown(summary), encoding="utf-8")

    return {
        **spec.to_manifest(),
        "status": status,
        "config_path": relative_to_root(config_path_written, run_root),
        "stdout_path": relative_to_root(stdout_path, run_root),
        "result_path": relative_to_root(result_path, run_root),
        "summary_path": relative_to_root(summary_md_path, run_root),
        "summary_json_path": relative_to_root(summary_json_path, run_root),
        "summary": summary,
        "attempts": [_relative_attempt_paths(attempt, run_root) for attempt in attempts],
        "hashes": {
            "config": sha256_file(config_path_written),
            "stdout": sha256_file(stdout_path),
            "result": sha256_file(result_path),
            "summary": sha256_file(summary_md_path),
        },
    }


def materialize_cell_config(
    config_path: Path | None,
    spec: TrialCellSpec,
    cell_dir: Path,
    transcript_dir: Path,
) -> Config:
    base_path = config_path or Path("llmfight.ini")
    cfg = Config(base_path)
    cell_dir.mkdir(parents=True, exist_ok=True)
    transcript_dir.mkdir(parents=True, exist_ok=True)
    _make_profile_references_absolute(cfg)
    cfg.path = cell_dir / "config.ini"
    cfg.set(C.CONFIG_GENERAL, C.CONFIG_LLAMA_DEFAULT_MODEL, spec.model)
    cfg.set(C.CONFIG_GENERAL, C.CONFIG_LLAMA_TEMPERATURE, spec.temperature)
    cfg.set(C.CONFIG_GENERAL, C.CONFIG_OLLAMA_NUM_CTX, DEFAULT_OLLAMA_NUM_CTX)
    cfg.set(C.CONFIG_GENERAL, C.CONFIG_MAX_TOKENS_FIGHTER, spec.token_preset.fighter_tokens)
    cfg.set(C.CONFIG_GENERAL, C.CONFIG_MAX_TOKENS_JUDGE, spec.token_preset.judge_tokens)
    cfg.set(C.CONFIG_GENERAL, C.CONFIG_FIGHTER_CREATION_MODE, spec.mode)
    cfg.set(C.CONFIG_GENERAL, C.CONFIG_SAVE_TRANSCRIPTS, "true")
    cfg.set(C.CONFIG_GENERAL, C.CONFIG_TRANSCRIPT_DETAIL, C.TRANSCRIPT_DETAIL_COMPACT)
    cfg.set(C.CONFIG_GENERAL, C.CONFIG_TRANSCRIPT_DIR, transcript_dir)
    cfg.set(C.CONFIG_SIMULATION, C.CONFIG_RUNS, "1")
    cfg.set(C.CONFIG_SIMULATION, C.CONFIG_CONCURRENT_RUNS, "1")
    cfg.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, DEFAULT_MAX_TURNS)
    cfg.set(C.CONFIG_SIMULATION, C.CONFIG_SEED, spec.seed)
    cfg.save()
    return cfg


def _make_profile_references_absolute(cfg: Config) -> None:
    from llm_fight.profiles import resolve_profile_path

    for section in _fighter_sections(cfg):
        reference = cfg.get_fighter_profile_reference(section)
        if not reference:
            continue
        raw_path = Path(reference).expanduser()
        if raw_path.is_absolute() or str(reference).strip().lower() == "humanoid":
            continue
        resolved = resolve_profile_path(reference, config=cfg)
        if resolved is None:
            continue
        resolved_text = str(resolved.resolve())
        for key in (C.CONFIG_FIGHTER_ANATOMY_PROFILE, C.CONFIG_FIGHTER_PROFILE):
            if cfg._explicit_section_value(section, key) is not None:
                cfg.set(section, key, resolved_text)


def _fighter_sections(cfg: Config) -> list[str]:
    sections = []
    for key, fallback in (
        (C.CONFIG_FIGHTER_A_SECTION, C.FIGHTER_A),
        (C.CONFIG_FIGHTER_B_SECTION, C.FIGHTER_B),
    ):
        section = cfg.get(C.CONFIG_GENERAL, key, str, fallback=fallback)
        if section not in sections:
            sections.append(section)
    return sections


async def _run_attempt(
    cell_config: Config,
    spec: TrialCellSpec,
    *,
    attempt_number: int,
    fight_id: str,
    fight_runner: FightRunner | None,
) -> dict[str, Any]:
    from llm_fight.simulation import _single_fight

    runner = fight_runner or _single_fight
    previous_rng_state = rng.get_state()
    try:
        with config_mod.use_config(cell_config):
            rng.seed_from_config(cell_config)
            response = await runner(
                return_log=True,
                fight_rng=random.Random(spec.seed),
                fight_id=fight_id,
                run_index=spec.index,
            )
    except Exception as exc:
        return {
            "attempt": attempt_number,
            "status": "error",
            "fight_id": fight_id,
            "trace_path": _find_trace_path(cell_config, fight_id),
            "error": sanitized_error(exc),
        }
    finally:
        rng.set_state(previous_rng_state)

    result = response[0] if isinstance(response, tuple) else response
    return {
        "attempt": attempt_number,
        "status": "completed",
        "fight_id": fight_id,
        "trace_path": _find_trace_path(cell_config, fight_id),
        "result": result,
    }


def _find_trace_path(cfg: Config, fight_id: str) -> str | None:
    transcript_dir = Path(cfg.get(C.CONFIG_GENERAL, C.CONFIG_TRANSCRIPT_DIR, str))
    matches = sorted(transcript_dir.glob(f"*_{fight_id}.jsonl"))
    if matches:
        return str(matches[-1])
    return None


def _format_attempt_output(attempt_number: int, stdout: str, stderr: str) -> str:
    parts = [f"attempt {attempt_number}"]
    if stdout.strip():
        parts.append("stdout:\n" + stdout.rstrip())
    if stderr.strip():
        parts.append("stderr:\n" + stderr.rstrip())
    return "\n".join(parts)


def _relative_attempt_paths(attempt: dict[str, Any], run_root: Path) -> dict[str, Any]:
    normalized = dict(attempt)
    trace_path = normalized.get("trace_path")
    if trace_path:
        normalized["trace_path"] = relative_to_root(Path(str(trace_path)), run_root)
    return normalized


def _manifest_cell(cell: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in cell.items() if key != "summary"}


def _scan_blind_pack_outputs(run_root: Path, cells: list[dict[str, Any]], pairs: list[dict[str, Any]]) -> None:
    terms = forbidden_terms(cells)
    leaks = []
    for pair in pairs:
        packs = pair.get("packs", {})
        for path_value in packs.values():
            path = run_root / str(path_value)
            leaks.extend(scan_forbidden_terms(path.read_text(encoding="utf-8"), terms))
    if leaks:
        raise RuntimeError(f"Blind pack leak scanner found forbidden terms: {sorted(set(leaks))}")
