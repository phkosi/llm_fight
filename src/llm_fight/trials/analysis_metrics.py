"""Metric and recommendation helpers for trial analysis."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from llm_fight.engine import constants as C

from .blind_packs import settle_review_votes

OUTCOMES = ("baseline", "candidate", "inconclusive")
HUMANOID_PARTS = {
    "head",
    "heart",
    "left_arm",
    "left_eye",
    "left_leg",
    "right_arm",
    "right_eye",
    "right_leg",
    "torso",
}
COMMON_EFFECT_NAMES = {
    "bleeding",
    "blinded",
    "burning",
    "flanked",
    "guarded",
    "obscured",
    "poisoned",
    "stunned",
}

_EFFECT_ADDED_RE = re.compile(
    r"\b(?:buff|debuff)\s+([A-Za-z][A-Za-z0-9_]*)(?:\s+on\s+[A-Za-z][A-Za-z0-9_]*)?\s+added\b"
)


def pair_issues(
    pair: dict[str, Any],
    review: dict[str, Any],
    baseline: dict[str, Any] | None,
    candidate: dict[str, Any] | None,
    mode: object,
) -> list[str]:
    issues = []
    if baseline is None:
        issues.append("missing_baseline_cell")
    if candidate is None:
        issues.append("missing_candidate_cell")
    if review.get("baseline_cell_id") not in {None, pair.get("baseline_cell_id")}:
        issues.append("review_baseline_mismatch")
    if review.get("candidate_cell_id") not in {None, pair.get("candidate_cell_id")}:
        issues.append("review_candidate_mismatch")

    settled = str(review.get("settled", "inconclusive"))
    if settled not in OUTCOMES:
        issues.append("invalid_settled_outcome")
    normalized_votes = [str(review.get("ab_normalized", "")), str(review.get("ba_normalized", ""))]
    if all(vote in OUTCOMES for vote in normalized_votes):
        recomputed = settle_review_votes(normalized_votes)
        if recomputed != settled:
            issues.append("settled_vote_mismatch")
    if _note_polarity_mismatch(settled, str(review.get("note", ""))):
        issues.append("note_polarity_mismatch")
    if review_disagrees(review):
        issues.append("review_disagreement")
    if baseline and str(baseline.get("status")) != "completed":
        issues.append("baseline_not_completed")
    if candidate and str(candidate.get("status")) != "completed":
        issues.append("candidate_not_completed")
    if baseline and int(baseline["metrics"]["p2_fallback_turns"]) > 0:
        issues.append("baseline_p2_fallback")
    if candidate and int(candidate["metrics"]["p2_fallback_turns"]) > 0:
        issues.append("candidate_p2_fallback")
    if baseline and baseline.get("summary_missing"):
        issues.append("baseline_summary_missing")
    if candidate and candidate.get("summary_missing"):
        issues.append("candidate_summary_missing")
    if mode == C.FIGHTER_CREATION_MODE_GENERATED and (
        _profile_fallbacks(baseline) > 0 or _profile_fallbacks(candidate) > 0
    ):
        issues.append("generated_profile_fallback")
    return issues


def recommendation(
    settled: str,
    mode: object,
    baseline: dict[str, Any] | None,
    candidate: dict[str, Any] | None,
    issues: list[str],
) -> str:
    blocking_issues = {
        "missing_baseline_cell",
        "missing_candidate_cell",
        "review_baseline_mismatch",
        "review_candidate_mismatch",
        "settled_vote_mismatch",
        "note_polarity_mismatch",
        "invalid_settled_outcome",
        "baseline_not_completed",
        "candidate_not_completed",
        "baseline_summary_missing",
        "candidate_summary_missing",
    }
    if blocking_issues.intersection(issues):
        return "blocked"
    if mode == C.FIGHTER_CREATION_MODE_GENERATED and (
        _profile_fallbacks(baseline) > 0 or _profile_fallbacks(candidate) > 0
    ):
        return "blocked"
    if settled == "candidate":
        if issues or _seed_count(baseline, candidate) <= 1:
            return "retest"
        return "promote"
    if settled == "inconclusive":
        return "retest"
    if settled == "baseline":
        return "reject"
    return "blocked"


def cell_metrics(cell: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    result = summary.get("result", {}) if isinstance(summary.get("result"), dict) else {}
    turns = summary.get("turns", []) if isinstance(summary.get("turns"), list) else []
    effects = _effect_names(summary)
    profile_counts = _profile_counts(summary)
    anatomy = _anatomy_metrics(summary)
    return {
        "turn_count": _as_int(result.get(C.LOG_TURN), len(turns)),
        "p2_fallback_turns": _as_int(result.get(C.LOG_P2_FALLBACK_TURNS), _fallback_turns(turns)),
        "p2_fallback_used": _as_bool(result.get(C.LOG_P2_FALLBACK_USED)) or _fallback_turns(turns) > 0,
        "mechanical_change_count": sum(
            len(_list_value(turn.get("mechanical_changes"))) for turn in turns if isinstance(turn, dict)
        ),
        "profile_total_count": profile_counts["total"],
        "profile_generated_count": profile_counts["generated"],
        "profile_fallback_count": profile_counts["fallback"],
        "custom_target_part_count": len(anatomy["custom_target_parts"]),
        "custom_target_parts": sorted(anatomy["custom_target_parts"]),
        "missing_humanoid_part_count": len(anatomy["missing_humanoid_parts"]),
        "missing_humanoid_parts": sorted(anatomy["missing_humanoid_parts"]),
        "altered_body_plan_count": anatomy["altered_body_plan_count"],
        "effect_add_count": len(effects),
        "distinct_effect_names": sorted(set(effects)),
        "custom_effect_names": sorted({name for name in effects if name not in COMMON_EFFECT_NAMES}),
        "status": cell.get("status", ""),
    }


def review_totals(results: list[Any]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for result in results:
        if isinstance(result, dict):
            settled = str(result.get("settled", "inconclusive"))
            counts[settled if settled in OUTCOMES else "inconclusive"] += 1
    return {"pairs": sum(counts.values()), **{outcome: counts[outcome] for outcome in OUTCOMES}}


def run_profile_generation(cells: dict[str, dict[str, Any]]) -> dict[str, int]:
    totals: Counter[str] = Counter()
    for cell in cells.values():
        metrics = cell["metrics"]
        totals["total_fighters"] += int(metrics["profile_total_count"])
        totals["generated"] += int(metrics["profile_generated_count"])
        totals["fallback"] += int(metrics["profile_fallback_count"])
    return dict(totals)


def run_metrics(cells: dict[str, dict[str, Any]]) -> dict[str, int]:
    totals: Counter[str] = Counter()
    for cell in cells.values():
        metrics = cell["metrics"]
        totals["cells"] += 1
        totals["completed_cells"] += 1 if metrics["status"] == "completed" else 0
        totals["p2_fallback_turns"] += int(metrics["p2_fallback_turns"])
        totals["mechanical_change_count"] += int(metrics["mechanical_change_count"])
        totals["custom_target_part_count"] += int(metrics["custom_target_part_count"])
        totals["effect_add_count"] += int(metrics["effect_add_count"])
    return dict(totals)


def aggregate_settings(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for pair in (pair for report in reports for pair in report["pairs"]):
        key = (
            str(pair["mode"]),
            str(pair["model"]),
            str(pair["temperature"]),
            str(pair["token_preset"]),
        )
        group = groups.setdefault(
            key,
            {
                "mode": pair["mode"],
                "model": pair["model"],
                "temperature": pair["temperature"],
                "token_preset": pair["token_preset"],
                "pairs": 0,
                "baseline": 0,
                "candidate": 0,
                "inconclusive": 0,
                "recommendations": Counter(),
                "issues": set(),
                "roots": set(),
                "seeds": set(),
                "review_disagreements": 0,
                "candidate_turn_total": 0,
                "candidate_p2_fallback_turns": 0,
                "candidate_p2_fallback_pairs": 0,
                "candidate_mechanical_change_count": 0,
                "candidate_profile_total_count": 0,
                "candidate_profile_fallback_count": 0,
                "candidate_custom_target_part_count": 0,
                "candidate_altered_body_plan_count": 0,
                "candidate_effect_add_count": 0,
            },
        )
        candidate_metrics = pair.get("candidate_metrics", {})
        settled = str(pair["settled"])
        outcome = settled if settled in OUTCOMES else "inconclusive"
        group["pairs"] += 1
        group[outcome] += 1
        group["recommendations"][pair["recommendation"]] += 1
        group["issues"].update(pair["issues"])
        group["roots"].add(pair["run_root"])
        group["seeds"].add(str(pair["seed"]))
        group["review_disagreements"] += 1 if pair.get("review_disagreement") else 0
        group["candidate_turn_total"] += int(candidate_metrics.get("turn_count", 0))
        p2_fallback_turns = int(candidate_metrics.get("p2_fallback_turns", 0))
        group["candidate_p2_fallback_turns"] += p2_fallback_turns
        group["candidate_p2_fallback_pairs"] += 1 if p2_fallback_turns > 0 else 0
        group["candidate_mechanical_change_count"] += int(candidate_metrics.get("mechanical_change_count", 0))
        group["candidate_profile_total_count"] += int(candidate_metrics.get("profile_total_count", 0))
        group["candidate_profile_fallback_count"] += int(candidate_metrics.get("profile_fallback_count", 0))
        group["candidate_custom_target_part_count"] += int(candidate_metrics.get("custom_target_part_count", 0))
        group["candidate_altered_body_plan_count"] += int(candidate_metrics.get("altered_body_plan_count", 0))
        group["candidate_effect_add_count"] += int(candidate_metrics.get("effect_add_count", 0))

    rows = []
    for group in groups.values():
        recommendations = group["recommendations"]
        rows.append(
            {
                "mode": group["mode"],
                "model": group["model"],
                "temperature": group["temperature"],
                "token_preset": group["token_preset"],
                "pairs": group["pairs"],
                "baseline": group["baseline"],
                "candidate": group["candidate"],
                "inconclusive": group["inconclusive"],
                "recommendation": _aggregate_recommendation(group),
                "recommendation_counts": dict(sorted(recommendations.items())),
                "issues": sorted(group["issues"]),
                "roots": sorted(group["roots"]),
                "seeds": sorted(group["seeds"]),
                "review_disagreement_count": group["review_disagreements"],
                "candidate_avg_turn_count": _rate(group["candidate_turn_total"], group["pairs"]),
                "candidate_p2_fallback_turns": group["candidate_p2_fallback_turns"],
                "candidate_p2_fallback_pair_rate": _rate(group["candidate_p2_fallback_pairs"], group["pairs"]),
                "candidate_avg_mechanical_changes": _rate(group["candidate_mechanical_change_count"], group["pairs"]),
                "candidate_profile_fallback_rate": _rate(
                    group["candidate_profile_fallback_count"], group["candidate_profile_total_count"]
                ),
                "candidate_custom_target_part_count": group["candidate_custom_target_part_count"],
                "candidate_altered_body_plan_count": group["candidate_altered_body_plan_count"],
                "candidate_effect_add_count": group["candidate_effect_add_count"],
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            str(row["mode"]),
            str(row["model"]),
            _sort_temperature(row["temperature"]),
            str(row["token_preset"]),
        ),
    )


def aggregate_totals(reports: list[dict[str, Any]]) -> dict[str, int]:
    totals: Counter[str] = Counter()
    for report in reports:
        computed = report["computed_totals"]
        totals["runs"] += 1
        for key in ("pairs", *OUTCOMES):
            totals[key] += int(computed.get(key, 0))
        totals["issues"] += len(report["issues"]) + sum(len(pair["issues"]) for pair in report["pairs"])
    return dict(totals)


def review_disagrees(review: dict[str, Any]) -> bool:
    ab = str(review.get("ab_normalized", ""))
    ba = str(review.get("ba_normalized", ""))
    return bool(ab and ba and ab != ba)


def _aggregate_recommendation(group: dict[str, Any]) -> str:
    if group["recommendations"].get("blocked", 0):
        return "blocked"
    if group["inconclusive"]:
        return "retest"
    if group["candidate"] > group["baseline"]:
        return "retest" if len(group["seeds"]) <= 1 or group["issues"] else "promote"
    if group["baseline"] >= group["candidate"]:
        return "reject"
    return "retest"


def _profile_counts(summary: dict[str, Any]) -> Counter[str]:
    counts: Counter[str] = Counter()
    fighters = summary.get("fighters", {})
    if not isinstance(fighters, dict):
        return counts
    for fighter in fighters.values():
        if not isinstance(fighter, dict):
            continue
        profile_generation = fighter.get(C.PROFILE_GENERATION)
        if not isinstance(profile_generation, dict):
            continue
        counts["total"] += 1
        mode = str(profile_generation.get("mode", ""))
        if mode:
            counts[mode] += 1
    return counts


def _anatomy_metrics(summary: dict[str, Any]) -> dict[str, Any]:
    custom_parts: set[str] = set()
    missing_parts: set[str] = set()
    altered_body_plans = 0
    fighters = summary.get("fighters", {})
    if not isinstance(fighters, dict):
        return {
            "custom_target_parts": custom_parts,
            "missing_humanoid_parts": missing_parts,
            "altered_body_plan_count": altered_body_plans,
        }
    for fighter in fighters.values():
        if not isinstance(fighter, dict):
            continue
        target_parts = {str(part) for part in _list_value(fighter.get("valid_target_parts")) if str(part)}
        custom_parts.update(part for part in target_parts if part not in HUMANOID_PARTS)
        missing_parts.update(HUMANOID_PARTS - target_parts)
        if target_parts and target_parts != HUMANOID_PARTS:
            altered_body_plans += 1
    return {
        "custom_target_parts": custom_parts,
        "missing_humanoid_parts": missing_parts,
        "altered_body_plan_count": altered_body_plans,
    }


def _effect_names(summary: dict[str, Any]) -> list[str]:
    names = []
    fighters = summary.get("fighters", {})
    if isinstance(fighters, dict):
        for fighter in fighters.values():
            if isinstance(fighter, dict):
                for effect in _list_value(fighter.get(C.ACTIVE_EFFECTS)):
                    if isinstance(effect, dict) and effect.get(C.NAME):
                        names.append(str(effect[C.NAME]))
    turns = summary.get("turns", [])
    if isinstance(turns, list):
        for turn in turns:
            if not isinstance(turn, dict):
                continue
            for change in _list_value(turn.get("mechanical_changes")):
                match = _EFFECT_ADDED_RE.search(str(change))
                if match:
                    names.append(match.group(1))
    return names


def _fallback_turns(turns: list[Any]) -> int:
    return sum(1 for turn in turns if isinstance(turn, dict) and turn.get(C.P2_FALLBACK_USED) is True)


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _rate(numerator: Any, denominator: Any) -> float:
    bottom = _as_int(denominator)
    if bottom <= 0:
        return 0.0
    return round(_as_int(numerator) / bottom, 4)


def _sort_temperature(value: Any) -> float:
    try:
        return float(value)
    except TypeError, ValueError:
        return float("inf")


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value))
    except TypeError, ValueError:
        return default


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}


def _note_polarity_mismatch(settled: str, note: str) -> bool:
    lowered = note.lower()
    baseline_preferred = "baseline preferred" in lowered or "preferred baseline" in lowered
    candidate_preferred = "candidate preferred" in lowered or "preferred candidate" in lowered
    return (settled == "candidate" and baseline_preferred) or (settled == "baseline" and candidate_preferred)


def _profile_fallbacks(cell: dict[str, Any] | None) -> int:
    if not cell:
        return 0
    return int(cell.get("metrics", {}).get("profile_fallback_count", 0))


def _seed_count(*cells: dict[str, Any] | None) -> int:
    return len({str(cell.get("seed")) for cell in cells if cell and cell.get("seed") is not None})
