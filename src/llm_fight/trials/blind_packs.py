"""Blind A/B pack generation for trial summaries."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from llm_fight.engine import constants as C

from .specs import BASELINE_TEMPERATURE, BASELINE_TOKEN_PRESET
from .summaries import render_summary_markdown

REVIEW_PROMPT = """Review the two LLM Fight samples below without guessing model or parameter identity.
Score interestingness, emergent tactics, readability, mechanical consequence, coherence, pacing, UX smoothness,
and reliability. Return one winner: A, B, tie, or inconclusive, plus short evidence.
"""


def build_blind_packs(run_root: Path, cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pairs = build_pair_specs(cells)
    packs_root = run_root / "blind_packs"
    for pair in pairs:
        pair_dir = packs_root / str(pair["pair_id"])
        pair_dir.mkdir(parents=True, exist_ok=True)
        baseline = pair["baseline"]
        candidate = pair["candidate"]
        (pair_dir / "ab.md").write_text(render_blind_pack("A", baseline, "B", candidate), encoding="utf-8")
        (pair_dir / "ba.md").write_text(render_blind_pack("A", candidate, "B", baseline), encoding="utf-8")
        pair["packs"] = {
            "ab": str((pair_dir / "ab.md").relative_to(run_root)).replace("\\", "/"),
            "ba": str((pair_dir / "ba.md").relative_to(run_root)).replace("\\", "/"),
        }
        pair["side_mapping"] = {
            "ab": {"A": baseline["cell_id"], "B": candidate["cell_id"]},
            "ba": {"A": candidate["cell_id"], "B": baseline["cell_id"]},
        }
        pair.pop("baseline")
        pair.pop("candidate")
    return pairs


def build_pair_specs(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    completed_or_failed = [cell for cell in cells if cell.get("status") in {"completed", "error"}]
    pairs = []
    next_index = 1
    for model in _ordered_models(completed_or_failed):
        model_cells = [cell for cell in completed_or_failed if cell.get("model") == model]
        for seed in _ordered_seeds(model_cells):
            seeded_cells = [cell for cell in model_cells if cell.get("seed") == seed]
            baseline = next(
                (
                    cell
                    for cell in seeded_cells
                    if cell.get("temperature") == BASELINE_TEMPERATURE
                    and cell.get("token_preset") == BASELINE_TOKEN_PRESET
                ),
                None,
            )
            if baseline is None:
                continue
            for candidate in seeded_cells:
                if candidate["cell_id"] == baseline["cell_id"]:
                    continue
                pairs.append(
                    {
                        "pair_id": f"pair-{next_index:04d}",
                        "model": model,
                        "seed": seed,
                        "baseline_cell_id": baseline["cell_id"],
                        "candidate_cell_id": candidate["cell_id"],
                        "baseline": baseline,
                        "candidate": candidate,
                    }
                )
                next_index += 1
    return pairs


def render_blind_pack(left_label: str, left: dict[str, Any], right_label: str, right: dict[str, Any]) -> str:
    return (
        REVIEW_PROMPT.strip()
        + "\n\n"
        + render_summary_markdown(left["summary"], title=f"Sample {left_label}")
        + "\n"
        + render_summary_markdown(right["summary"], title=f"Sample {right_label}")
    )


def forbidden_terms(cells: list[dict[str, Any]]) -> list[str]:
    terms = {
        C.CONFIG_LLAMA_TEMPERATURE,
        "temperature=",
        "token_preset",
        "max_tokens_fighter",
        "max_tokens_judge",
        "fight_id",
        "run_id",
        "run_index",
        "manifest.json",
        "config.ini",
        "stdout.txt",
        "result.json",
        "transcript",
        "transcripts",
    }
    for cell in cells:
        for key in ("model", "cell_id", "config_path", "result_path", "summary_path"):
            value = cell.get(key)
            if value:
                terms.add(str(value))
        for attempt in cell.get("attempts", []):
            if isinstance(attempt, dict):
                for key in ("fight_id", "trace_path"):
                    if attempt.get(key):
                        terms.add(str(attempt[key]))
    return sorted(term for term in terms if term and term != "None")


def scan_forbidden_terms(text: str, terms: list[str]) -> list[str]:
    leaks = []
    for term in terms:
        pattern = _term_pattern(term)
        if re.search(pattern, text, flags=re.IGNORECASE):
            leaks.append(term)
    return leaks


def normalize_review_vote(
    presentation: str,
    vote: str,
    side_mapping: dict[str, dict[str, str]],
    baseline_cell_id: str,
) -> str:
    normalized_vote = vote.strip().lower()
    if normalized_vote in {"tie", "inconclusive"}:
        return normalized_vote
    side = normalized_vote.upper()
    if side not in {"A", "B"}:
        return "inconclusive"
    voted_cell = side_mapping[presentation][side]
    return "baseline" if voted_cell == baseline_cell_id else "candidate"


def settle_review_votes(votes: list[str]) -> str:
    if not votes or any(vote == "inconclusive" for vote in votes):
        return "inconclusive"
    first = votes[0]
    if all(vote == first for vote in votes):
        return first
    return "inconclusive"


def _ordered_models(cells: list[dict[str, Any]]) -> list[str]:
    ordered = []
    for cell in cells:
        model = str(cell.get("model", ""))
        if model and model not in ordered:
            ordered.append(model)
    return ordered


def _ordered_seeds(cells: list[dict[str, Any]]) -> list[object]:
    ordered = []
    for cell in cells:
        seed = cell.get("seed")
        if seed not in ordered:
            ordered.append(seed)
    return ordered


def _term_pattern(term: str) -> str:
    escaped = re.escape(term)
    if re.fullmatch(r"\d+(\.\d+)?", term):
        return rf"(?<![\w.]){escaped}(?![\w.])"
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", term):
        return rf"(?<!\w){escaped}(?!\w)"
    return escaped
