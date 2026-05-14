import csv
import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from llm_fight.cli import app
from llm_fight.engine import constants as C
from llm_fight.trials.analysis import TrialAnalysisError, analyze_trials


def _write_json(path: Path, payload, *, bom: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8-sig" if bom else "utf-8")


def _summary(*, profile_modes=(), custom_part="", custom_effect="", p2_fallback_turns=0):
    fighters = {}
    for index, fighter_id in enumerate((C.FIGHTER_A, C.FIGHTER_B)):
        profile_mode = profile_modes[index] if index < len(profile_modes) else None
        profile_generation = None
        if profile_mode:
            profile_generation = {
                "mode": profile_mode,
                "nudge": "original",
                "error": C.PROFILE_GENERATION_ERROR_INVALID if profile_mode == "fallback" else None,
            }
        parts = ["head", "heart", "torso"]
        if custom_part and fighter_id == C.FIGHTER_A:
            parts.append(custom_part)
        fighter = {
            C.DISPLAY_NAME: fighter_id,
            "class_": "Duelist",
            C.LOADOUT: "blade",
            "environment": "arena",
            "valid_target_parts": parts,
            C.ACTIVE_EFFECTS: [],
        }
        if profile_generation:
            fighter[C.PROFILE_GENERATION] = profile_generation
        fighters[fighter_id] = fighter

    mechanical_changes = ["B pain +2 (0 -> 2)"]
    if custom_effect:
        mechanical_changes.append(f"B debuff {custom_effect} added (ttl=2, magnitude=1)")
    return {
        "status": "completed",
        "fighters": fighters,
        "result": {
            C.WINNER: C.DRAW,
            C.LOG_TURN: "2",
            C.LOG_P2_FALLBACK_USED: str(p2_fallback_turns > 0).lower(),
            C.LOG_P2_FALLBACK_TURNS: str(p2_fallback_turns),
        },
        "turns": [
            {
                "turn": 1,
                C.P2_FALLBACK_USED: p2_fallback_turns > 0,
                "mechanical_changes": mechanical_changes,
            },
            {"turn": 2, C.P2_FALLBACK_USED: False, "mechanical_changes": []},
        ],
    }


def _make_run(
    root: Path,
    *,
    mode: str = C.FIGHTER_CREATION_MODE_CONFIGURED,
    review_note: str = "Candidate preferred.",
    settled: str = "candidate",
    stored_totals=None,
    baseline_summary=None,
    candidate_summary=None,
) -> Path:
    baseline = {
        "cell_id": "cell-0005",
        "status": "completed",
        "mode": mode,
        "model": "qwen3.6:35b",
        "temperature": 0.4,
        "token_preset": "default",
        "max_tokens_fighter": 512,
        "max_tokens_judge": 4096,
        "seed": 42,
        "is_baseline": True,
        "summary_json_path": "cells/cell-0005/summary.json",
    }
    candidate = {
        "cell_id": "cell-0001",
        "status": "completed",
        "mode": mode,
        "model": "qwen3.6:35b",
        "temperature": 0.2,
        "token_preset": "focused",
        "max_tokens_fighter": 384,
        "max_tokens_judge": 3072,
        "seed": 42,
        "is_baseline": False,
        "summary_json_path": "cells/cell-0001/summary.json",
    }
    pair = {
        "pair_id": "pair-0001",
        "model": "qwen3.6:35b",
        "baseline_cell_id": "cell-0005",
        "candidate_cell_id": "cell-0001",
        "side_mapping": {
            "ab": {"A": "cell-0005", "B": "cell-0001"},
            "ba": {"A": "cell-0001", "B": "cell-0005"},
        },
    }
    review = {
        "pair_id": "pair-0001",
        "baseline_cell_id": "cell-0005",
        "candidate_cell_id": "cell-0001",
        "ab_normalized": settled,
        "ba_normalized": settled,
        "settled": settled,
        "note": review_note,
    }
    _write_json(
        root / "manifest.json",
        {
            "schema_version": 1,
            "mode": mode,
            "smoke": False,
            "artifact_root": str(root),
            "cells": [candidate, baseline],
            "pairs": [pair],
        },
    )
    _write_json(
        root / "review_results.json",
        {
            "schema_version": 1,
            "mode": mode,
            "totals": stored_totals or {"pairs": 1, "baseline": 0, "candidate": 1, "inconclusive": 0},
            "results": [review],
        },
        bom=True,
    )
    _write_json(root / "cells" / "cell-0005" / "summary.json", baseline_summary or _summary())
    _write_json(root / "cells" / "cell-0001" / "summary.json", candidate_summary or _summary())
    return root


def test_analyze_trials_recomputes_totals_and_flags_note_mismatch(tmp_path):
    root = _make_run(
        tmp_path / "run",
        review_note="Baseline preferred for cleaner mechanics.",
        stored_totals={"pairs": 1, "baseline": 1, "candidate": 0, "inconclusive": 0},
    )

    output_dir = analyze_trials([root], output_dir=tmp_path / "out")
    analysis = json.loads((output_dir / "analysis.json").read_text(encoding="utf-8"))

    assert analysis["runs"][0]["computed_totals"] == {
        "pairs": 1,
        "baseline": 0,
        "candidate": 1,
        "inconclusive": 0,
    }
    assert analysis["runs"][0]["issues"][0]["code"] == "stored_totals_mismatch"
    assert "note_polarity_mismatch" in analysis["runs"][0]["pairs"][0]["issues"]
    assert analysis["settings"][0]["recommendation"] == "blocked"
    assert "note_polarity_mismatch" in (output_dir / "analysis.md").read_text(encoding="utf-8")


def test_analyze_trials_blocks_generated_fallback_and_measures_creativity(tmp_path):
    root = _make_run(
        tmp_path / "generated",
        mode=C.FIGHTER_CREATION_MODE_GENERATED,
        candidate_summary=_summary(
            profile_modes=("fallback", "generated"),
            custom_part="crystal_core",
            custom_effect="crystal_rot",
        ),
        baseline_summary=_summary(profile_modes=("generated", "generated")),
    )

    output_dir = analyze_trials([root], output_dir=tmp_path / "out")
    analysis = json.loads((output_dir / "analysis.json").read_text(encoding="utf-8"))
    pair = analysis["runs"][0]["pairs"][0]

    assert analysis["runs"][0]["profile_generation"] == {"total_fighters": 4, "generated": 3, "fallback": 1}
    assert pair["recommendation"] == "blocked"
    assert "generated_profile_fallback" in pair["issues"]
    assert pair["candidate_metrics"]["custom_target_parts"] == ["crystal_core"]
    assert pair["candidate_metrics"]["custom_effect_names"] == ["crystal_rot"]
    assert pair["candidate_metrics"]["altered_body_plan_count"] == 2
    assert "left_eye" in pair["candidate_metrics"]["missing_humanoid_parts"]


def test_analyze_trials_writes_csv_reports(tmp_path):
    root = _make_run(tmp_path / "run")

    output_dir = analyze_trials([root], output_dir=tmp_path / "out")
    with (output_dir / "settings.csv").open(encoding="utf-8", newline="") as fp:
        settings = list(csv.DictReader(fp))
    with (output_dir / "pairs.csv").open(encoding="utf-8", newline="") as fp:
        pairs = list(csv.DictReader(fp))

    assert settings[0]["model"] == "qwen3.6:35b"
    assert settings[0]["recommendation"] == "retest"
    assert settings[0]["candidate_avg_turn_count"] == "2.0"
    assert settings[0]["candidate_p2_fallback_pair_rate"] == "0.0"
    assert pairs[0]["pair_id"] == "pair-0001"
    assert pairs[0]["candidate_mechanical_changes"] == "1"


def test_analyze_trials_treats_blank_summary_path_as_missing(tmp_path):
    root = _make_run(tmp_path / "run")
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["cells"][0]["summary_json_path"] = ""
    _write_json(manifest_path, manifest)

    output_dir = analyze_trials([root], output_dir=tmp_path / "out")
    analysis = json.loads((output_dir / "analysis.json").read_text(encoding="utf-8"))

    pair = analysis["runs"][0]["pairs"][0]
    assert "candidate_summary_missing" in pair["issues"]
    assert pair["recommendation"] == "blocked"


def test_analyze_trials_treats_malformed_summary_lists_as_empty(tmp_path):
    malformed_summary = _summary()
    malformed_summary["fighters"][C.FIGHTER_A][C.ACTIVE_EFFECTS] = "guarded"
    malformed_summary["turns"][0]["mechanical_changes"] = None
    malformed_summary["turns"][1]["mechanical_changes"] = "B buff guarded added"
    root = _make_run(tmp_path / "run", candidate_summary=malformed_summary)

    output_dir = analyze_trials([root], output_dir=tmp_path / "out")
    analysis = json.loads((output_dir / "analysis.json").read_text(encoding="utf-8"))
    metrics = analysis["runs"][0]["pairs"][0]["candidate_metrics"]

    assert metrics["mechanical_change_count"] == 0
    assert metrics["distinct_effect_names"] == []


def test_analyze_trials_handles_missing_candidate_cell_without_aggregation_crash(tmp_path):
    root = _make_run(tmp_path / "run")
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["pairs"][0]["candidate_cell_id"] = "cell-missing"
    _write_json(manifest_path, manifest)

    output_dir = analyze_trials([root], output_dir=tmp_path / "out")
    analysis = json.loads((output_dir / "analysis.json").read_text(encoding="utf-8"))
    pair = analysis["runs"][0]["pairs"][0]

    assert pair["recommendation"] == "blocked"
    assert "missing_candidate_cell" in pair["issues"]
    assert analysis["settings"][0]["temperature"] == ""


def test_analyze_trials_reads_review_artifact_as_object(tmp_path):
    root = _make_run(tmp_path / "run")
    _write_json(root / "review_results.json", [])

    try:
        analyze_trials([root], output_dir=tmp_path / "out")
    except TrialAnalysisError as exc:
        assert "must be a JSON object" in str(exc)
    else:  # pragma: no cover - assertion safety
        raise AssertionError("Expected TrialAnalysisError")


def test_analyze_trials_blocks_invalid_settled_without_aggregation_crash(tmp_path):
    root = _make_run(tmp_path / "run", settled="weird")

    output_dir = analyze_trials([root], output_dir=tmp_path / "out")
    analysis = json.loads((output_dir / "analysis.json").read_text(encoding="utf-8"))
    pair = analysis["runs"][0]["pairs"][0]

    assert pair["settled"] == "weird"
    assert pair["recommendation"] == "blocked"
    assert "invalid_settled_outcome" in pair["issues"]
    assert analysis["settings"][0]["inconclusive"] == 1


def test_analyze_trials_detects_target_qualified_custom_effects(tmp_path):
    summary = _summary(custom_part="crystal_core")
    summary["turns"][0]["mechanical_changes"] = ["B debuff crystal_rot on crystal_core added (ttl=2, magnitude=1)"]
    root = _make_run(tmp_path / "run", candidate_summary=summary)

    output_dir = analyze_trials([root], output_dir=tmp_path / "out")
    analysis = json.loads((output_dir / "analysis.json").read_text(encoding="utf-8"))
    metrics = analysis["runs"][0]["pairs"][0]["candidate_metrics"]

    assert metrics["custom_effect_names"] == ["crystal_rot"]


def test_analyze_trials_requires_review_results(tmp_path):
    root = tmp_path / "run"
    _write_json(root / "manifest.json", {"schema_version": 1, "mode": "configured", "cells": [], "pairs": []})

    try:
        analyze_trials([root], output_dir=tmp_path / "out")
    except TrialAnalysisError as exc:
        assert "review_results.json" in str(exc)
    else:  # pragma: no cover - assertion safety
        raise AssertionError("Expected TrialAnalysisError")


def test_cli_analyze_trials_wires_single_root_default_output(tmp_path):
    root = _make_run(tmp_path / "run")
    runner = CliRunner()

    result = runner.invoke(app, ["analyze-trials", str(root)])

    assert result.exit_code == 0
    assert "Trial analysis saved to" in result.output
    assert (root / "analysis" / "analysis.json").exists()


def test_cli_analyze_trials_wires_multiple_roots_and_output_dir(tmp_path):
    root_a = _make_run(tmp_path / "run-a")
    root_b = _make_run(tmp_path / "run-b")
    output_dir = tmp_path / "combined"
    runner = CliRunner()

    result = runner.invoke(app, ["analyze-trials", str(root_a), str(root_b), "--output-dir", str(output_dir)])

    assert result.exit_code == 0
    analysis = json.loads((output_dir / "analysis.json").read_text(encoding="utf-8"))
    assert analysis["run_count"] == 2


def test_cli_analyze_trials_reports_malformed_artifacts(tmp_path):
    root = tmp_path / "run"
    root.mkdir()
    (root / "manifest.json").write_text("{", encoding="utf-8")
    runner = CliRunner()

    with patch("llm_fight.cli.ping_ollama") as ping:
        result = runner.invoke(app, ["analyze-trials", str(root)])

    assert result.exit_code != 0
    assert "not valid JSON" in result.output
    ping.assert_not_called()
