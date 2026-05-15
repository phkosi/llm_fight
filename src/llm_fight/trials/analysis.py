"""Analysis reports for collected trial artifacts."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .analysis_metrics import (
    aggregate_settings,
    aggregate_totals,
    cell_metrics,
    pair_issues,
    recommendation,
    review_disagrees,
    review_totals,
    run_metrics,
    run_profile_generation,
)
from .artifacts import timestamp_slug, write_json


class TrialAnalysisError(ValueError):
    """Raised when trial artifacts cannot be analyzed."""


def analyze_trials(run_roots: Iterable[Path], *, output_dir: Path | None = None) -> Path:
    """Analyze one or more trial roots and write JSON, Markdown, and CSV reports."""
    roots = [Path(root) for root in run_roots]
    if not roots:
        raise TrialAnalysisError("At least one trial run root is required.")

    reports = [_analyze_run_root(root) for root in roots]
    setting_rows = aggregate_settings(reports)
    pair_rows = [pair for report in reports for pair in report["pairs"]]
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "design_north_star": "tactical_emergence",
        "run_count": len(reports),
        "runs": reports,
        "settings": setting_rows,
        "totals": aggregate_totals(reports),
    }

    destination = _analysis_output_dir(roots, output_dir)
    write_json(destination / "analysis.json", payload)
    (destination / "analysis.md").write_text(_render_markdown(payload), encoding="utf-8")
    _write_csv(destination / "settings.csv", _settings_csv_rows(setting_rows), SETTINGS_FIELDS)
    _write_csv(destination / "pairs.csv", _pairs_csv_rows(pair_rows), PAIRS_FIELDS)
    return destination


def _analyze_run_root(root: Path) -> dict[str, Any]:
    if not root.exists():
        raise TrialAnalysisError(f"Trial run root not found: {root}")
    manifest = _read_json(root / "manifest.json")
    reviews = _read_json(root / "review_results.json")
    if not isinstance(manifest, dict):
        raise TrialAnalysisError(f"Manifest {root / 'manifest.json'} must be a JSON object.")
    if not isinstance(reviews, dict):
        raise TrialAnalysisError(f"Review artifact {root / 'review_results.json'} must be a JSON object.")
    cells = _load_cells(root, manifest)
    pairs = _load_pairs(manifest)
    review_results = reviews.get("results")
    if not isinstance(review_results, list):
        raise TrialAnalysisError(f"Review artifact {root / 'review_results.json'} must contain a results list.")

    run_issues: list[dict[str, str]] = []
    pair_rows = _analyze_pairs(root, manifest, reviews, cells, pairs, run_issues)
    computed_totals = review_totals(review_results)
    stored_totals = reviews.get("totals", {})
    if stored_totals != computed_totals:
        run_issues.append(
            {
                "code": "stored_totals_mismatch",
                "message": f"Stored totals {stored_totals!r} differ from recomputed totals {computed_totals!r}.",
            }
        )

    return {
        "run_root": str(root),
        "mode": manifest.get("mode"),
        "smoke": bool(manifest.get("smoke", False)),
        "artifact_root": manifest.get("artifact_root", str(root)),
        "stored_totals": stored_totals,
        "computed_totals": computed_totals,
        "profile_generation": run_profile_generation(cells),
        "metrics": run_metrics(cells),
        "issues": run_issues,
        "pairs": pair_rows,
    }


def _read_json(path: Path) -> Any:
    if not path.exists():
        raise TrialAnalysisError(f"Required trial artifact is missing: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise TrialAnalysisError(f"Trial artifact is not valid JSON: {path}: {exc}") from exc
    except OSError as exc:
        raise TrialAnalysisError(f"Trial artifact could not be read: {path}: {exc}") from exc


def _load_cells(root: Path, manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_cells = manifest.get("cells")
    if not isinstance(raw_cells, list):
        raise TrialAnalysisError(f"Manifest {root / 'manifest.json'} must contain a cells list.")
    cells = {}
    for raw_cell in raw_cells:
        if not isinstance(raw_cell, dict) or not raw_cell.get("cell_id"):
            raise TrialAnalysisError(f"Manifest {root / 'manifest.json'} contains a malformed cell.")
        cell = dict(raw_cell)
        summary_reference = str(cell.get("summary_json_path", "") or "")
        summary_path = root / summary_reference if summary_reference else None
        summary = _read_json(summary_path) if summary_path is not None and summary_path.is_file() else {}
        cell["summary"] = summary
        cell["summary_missing"] = not bool(summary)
        cell["metrics"] = cell_metrics(cell, summary)
        cells[str(cell["cell_id"])] = cell
    return cells


def _load_pairs(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_pairs = manifest.get("pairs")
    if not isinstance(raw_pairs, list):
        raise TrialAnalysisError("Manifest must contain a pairs list.")
    pairs = {}
    for raw_pair in raw_pairs:
        if isinstance(raw_pair, dict) and raw_pair.get("pair_id"):
            pairs[str(raw_pair["pair_id"])] = raw_pair
    return pairs


def _analyze_pairs(
    root: Path,
    manifest: dict[str, Any],
    reviews: dict[str, Any],
    cells: dict[str, dict[str, Any]],
    pairs: dict[str, dict[str, Any]],
    run_issues: list[dict[str, str]],
) -> list[dict[str, Any]]:
    rows = []
    review_by_pair = {str(review.get("pair_id")): review for review in reviews["results"] if isinstance(review, dict)}
    missing_reviews = sorted(set(pairs) - set(review_by_pair))
    extra_reviews = sorted(set(review_by_pair) - set(pairs))
    for pair_id in missing_reviews:
        run_issues.append({"code": "missing_review", "message": f"Manifest pair {pair_id} has no review result."})
    for pair_id in extra_reviews:
        run_issues.append({"code": "extra_review", "message": f"Review result {pair_id} is not present in manifest."})

    for pair_id in sorted(set(pairs) & set(review_by_pair)):
        pair = pairs[pair_id]
        review = review_by_pair[pair_id]
        baseline = cells.get(str(pair.get("baseline_cell_id")))
        candidate = cells.get(str(pair.get("candidate_cell_id")))
        issues = pair_issues(pair, review, baseline, candidate, manifest.get("mode"))
        settled = str(review.get("settled", "inconclusive"))
        pair_recommendation = recommendation(settled, manifest.get("mode"), baseline, candidate, issues)
        rows.append(
            {
                "run_root": str(root),
                "mode": manifest.get("mode", ""),
                "pair_id": pair_id,
                "model": pair.get("model", candidate.get("model", "") if candidate else ""),
                "baseline_cell_id": pair.get("baseline_cell_id", ""),
                "candidate_cell_id": pair.get("candidate_cell_id", ""),
                "temperature": candidate.get("temperature", "") if candidate else "",
                "token_preset": candidate.get("token_preset", "") if candidate else "",
                "seed": candidate.get("seed", "") if candidate else "",
                "settled": settled,
                "ab_normalized": review.get("ab_normalized", ""),
                "ba_normalized": review.get("ba_normalized", ""),
                "review_disagreement": review_disagrees(review),
                "note": review.get("note", ""),
                "issues": issues,
                "recommendation": pair_recommendation,
                "baseline_metrics": baseline.get("metrics", {}) if baseline else {},
                "candidate_metrics": candidate.get("metrics", {}) if candidate else {},
            }
        )
    return rows


def _analysis_output_dir(roots: list[Path], output_dir: Path | None) -> Path:
    if output_dir is not None:
        destination = output_dir
    elif len(roots) == 1:
        destination = roots[0] / "analysis"
    else:
        destination = Path("transcripts") / "trials" / "analysis" / timestamp_slug()
    destination.mkdir(parents=True, exist_ok=True)
    return destination


SETTINGS_FIELDS = [
    "mode",
    "model",
    "temperature",
    "token_preset",
    "pairs",
    "baseline",
    "candidate",
    "inconclusive",
    "recommendation",
    "recommendation_counts",
    "review_disagreement_count",
    "candidate_avg_turn_count",
    "candidate_p2_fallback_turns",
    "candidate_p2_fallback_pair_rate",
    "candidate_avg_mechanical_changes",
    "candidate_profile_fallback_rate",
    "candidate_custom_target_part_count",
    "candidate_altered_body_plan_count",
    "candidate_effect_add_count",
    "issues",
    "roots",
    "seeds",
]

PAIRS_FIELDS = [
    "run_root",
    "mode",
    "pair_id",
    "model",
    "temperature",
    "token_preset",
    "baseline_cell_id",
    "candidate_cell_id",
    "settled",
    "recommendation",
    "review_disagreement",
    "issues",
    "candidate_turns",
    "candidate_p2_fallback_turns",
    "candidate_mechanical_changes",
    "candidate_profile_fallbacks",
    "candidate_custom_target_parts",
    "candidate_missing_humanoid_parts",
    "candidate_altered_body_plans",
    "candidate_custom_effects",
    "note",
]


def _settings_csv_rows(settings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            **row,
            "recommendation_counts": ";".join(
                f"{name}:{count}" for name, count in row["recommendation_counts"].items()
            ),
            "issues": ";".join(row["issues"]),
            "roots": ";".join(row["roots"]),
            "seeds": ";".join(row["seeds"]),
        }
        for row in settings
    ]


def _pairs_csv_rows(pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for pair in pairs:
        metrics = pair["candidate_metrics"]
        rows.append(
            {
                "run_root": pair["run_root"],
                "mode": pair["mode"],
                "pair_id": pair["pair_id"],
                "model": pair["model"],
                "temperature": pair["temperature"],
                "token_preset": pair["token_preset"],
                "baseline_cell_id": pair["baseline_cell_id"],
                "candidate_cell_id": pair["candidate_cell_id"],
                "settled": pair["settled"],
                "recommendation": pair["recommendation"],
                "review_disagreement": pair["review_disagreement"],
                "issues": ";".join(pair["issues"]),
                "candidate_turns": metrics.get("turn_count", 0),
                "candidate_p2_fallback_turns": metrics.get("p2_fallback_turns", 0),
                "candidate_mechanical_changes": metrics.get("mechanical_change_count", 0),
                "candidate_profile_fallbacks": metrics.get("profile_fallback_count", 0),
                "candidate_custom_target_parts": ";".join(metrics.get("custom_target_parts", [])),
                "candidate_missing_humanoid_parts": ";".join(metrics.get("missing_humanoid_parts", [])),
                "candidate_altered_body_plans": metrics.get("altered_body_plan_count", 0),
                "candidate_custom_effects": ";".join(metrics.get("custom_effect_names", [])),
                "note": pair["note"],
            }
        )
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Trial Analysis",
        "",
        (
            "Design north star: tactical emergence through multi-turn adaptation, mechanical consequences, "
            "readable causality, and reliable state continuity."
        ),
        "",
        "## Totals",
        "",
        f"- Runs: {payload['totals'].get('runs', 0)}",
        f"- Pairs: {payload['totals'].get('pairs', 0)}",
        (
            f"- Outcomes: baseline {payload['totals'].get('baseline', 0)}, "
            f"candidate {payload['totals'].get('candidate', 0)}, "
            f"inconclusive {payload['totals'].get('inconclusive', 0)}"
        ),
        f"- Flagged issues: {payload['totals'].get('issues', 0)}",
        "",
        "## Settings",
        "",
        "| Mode | Model | Temp | Tokens | Outcomes | Recommendation | Issues |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in payload["settings"]:
        outcomes = f"B {row['baseline']} / C {row['candidate']} / I {row['inconclusive']}"
        issues = ", ".join(row["issues"]) if row["issues"] else "none"
        lines.append(
            f"| {row['mode']} | {row['model']} | {row['temperature']} | {row['token_preset']} | "
            f"{outcomes} | {row['recommendation']} | {issues} |"
        )
    lines.extend(["", "## Setting Metrics", ""])
    for row in payload["settings"]:
        lines.append(
            f"- {row['mode']} / {row['model']} / {row['temperature']} / {row['token_preset']}: "
            f"avg turns {row['candidate_avg_turn_count']}, "
            f"P2 fallback turns {row['candidate_p2_fallback_turns']}, "
            f"profile fallback rate {row['candidate_profile_fallback_rate']}, "
            f"review disagreements {row['review_disagreement_count']}."
        )
    lines.extend(["", "## Run Issues", ""])
    any_issue = False
    for run in payload["runs"]:
        for issue in run["issues"]:
            any_issue = True
            lines.append(f"- `{run['run_root']}`: {issue['code']} - {issue['message']}")
        for pair in run["pairs"]:
            if pair["issues"]:
                any_issue = True
                lines.append(f"- `{run['run_root']}` {pair['pair_id']}: {', '.join(pair['issues'])}")
    if not any_issue:
        lines.append("- None.")
    lines.extend(
        [
            "",
            "## Next Retest Matrix",
            "",
            "- qwen3.6:35b: default finalized at 0.4/expansive; no immediate retest unless regressions appear.",
            "- gemma4:26b: default finalized at 0.4/default; no candidate cleared the promotion rule.",
            (
                "- Generated-mode prompt work: profile fallback is unblocked; focus next on generated-anatomy "
                "target/consequence reliability before adding new mechanics."
            ),
        ]
    )
    return "\n".join(lines) + "\n"
