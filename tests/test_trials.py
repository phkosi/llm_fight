import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from llm_fight import config as config_mod
from llm_fight.cli import app
from llm_fight.engine import constants as C
from llm_fight.profiles import resolve_fighter_profile
from llm_fight.trials.blind_packs import (
    build_blind_packs,
    build_pair_specs,
    forbidden_terms,
    normalize_review_vote,
    scan_forbidden_terms,
    settle_review_votes,
)
from llm_fight.trials.runner import collect_trials, materialize_cell_config
from llm_fight.trials.specs import (
    DEFAULT_FINALIST_SEEDS,
    TOKEN_PRESETS,
    TrialCellSpec,
    iter_trial_matrix,
    parse_seed_list,
)
from llm_fight.trials.summaries import build_summary, render_summary_markdown


def _custom_profile(part_id="left_wing"):
    return {
        C.CONFIG_FIGHTER_CLASS: "Winged Duelist",
        C.LOADOUT: "hook blades",
        "environment": "windy arena",
        C.BODY_PARTS: [
            {
                "id": "second_head",
                C.NAME: "second head",
                "is_vital": True,
                "layers": [{C.NAME: "bone", C.MAX_HP: 10}],
            },
            {
                "id": part_id,
                C.NAME: part_id.replace("_", " "),
                "can_be_severed": True,
                "layers": [{C.NAME: "muscle", C.MAX_HP: 12}],
            },
        ],
    }


def test_trial_matrix_order_and_baseline():
    cells = iter_trial_matrix(C.FIGHTER_CREATION_MODE_CONFIGURED)

    assert len(cells) == 18
    assert [cell.model for cell in cells[:9]] == ["qwen3.6:35b"] * 9
    assert [cell.model for cell in cells[9:]] == ["gemma4:26b"] * 9
    assert [(cell.temperature, cell.token_preset.label) for cell in cells[:3]] == [
        (0.2, "focused"),
        (0.2, "default"),
        (0.2, "expansive"),
    ]
    assert [cell.cell_id for cell in cells[:2]] == ["cell-0001", "cell-0002"]
    assert [cell.cell_id for cell in cells if cell.is_baseline] == ["cell-0005", "cell-0014"]
    assert {cell.seed for cell in cells} == {42}


def test_finalist_matrix_expands_expected_settings_and_seeds():
    cells = iter_trial_matrix(C.FIGHTER_CREATION_MODE_CONFIGURED, matrix="finalist")

    assert len(cells) == 15
    assert {cell.seed for cell in cells} == set(DEFAULT_FINALIST_SEEDS)
    assert [cell.cell_id for cell in cells[:5]] == [
        "cell-0001",
        "cell-0002",
        "cell-0003",
        "cell-0004",
        "cell-0005",
    ]
    assert [(cell.model, cell.seed, cell.temperature, cell.token_preset.label) for cell in cells[:5]] == [
        ("qwen3.6:35b", 42, 0.4, "default"),
        ("qwen3.6:35b", 42, 0.2, "expansive"),
        ("gemma4:26b", 42, 0.4, "default"),
        ("gemma4:26b", 42, 0.2, "expansive"),
        ("gemma4:26b", 42, 0.7, "focused"),
    ]
    qwen_candidates = [
        cell
        for cell in cells
        if cell.model == "qwen3.6:35b" and (cell.temperature, cell.token_preset.label) == (0.2, "expansive")
    ]
    gemma_candidates = [
        cell
        for cell in cells
        if cell.model == "gemma4:26b" and (cell.temperature, cell.token_preset.label) != (0.4, "default")
    ]
    assert len(qwen_candidates) == 3
    assert len(gemma_candidates) == 6


def test_trial_matrix_custom_seeds_and_smoke_are_opt_in():
    default_cells = iter_trial_matrix(C.FIGHTER_CREATION_MODE_CONFIGURED)
    multi_seed_cells = iter_trial_matrix(C.FIGHTER_CREATION_MODE_CONFIGURED, seeds=(7, 8))
    finalist_smoke = iter_trial_matrix(C.FIGHTER_CREATION_MODE_CONFIGURED, matrix="finalist", smoke=True)

    assert len(default_cells) == 18
    assert len(multi_seed_cells) == 36
    assert {cell.seed for cell in multi_seed_cells} == {7, 8}
    assert len(finalist_smoke) == 1
    assert finalist_smoke[0].is_baseline is True
    assert finalist_smoke[0].seed == 42


def test_parse_seed_list_defaults_and_validation():
    assert parse_seed_list(None, matrix="full") == (42,)
    assert parse_seed_list(None, matrix="finalist") == DEFAULT_FINALIST_SEEDS
    assert parse_seed_list(" 101, 102,101 ") == (101, 102)
    with pytest.raises(ValueError, match="Invalid seed"):
        parse_seed_list("101,nope")
    with pytest.raises(ValueError, match="matrix"):
        parse_seed_list(None, matrix="wide")


def test_materialize_cell_config_does_not_mutate_base_config(tmp_path):
    base_config = tmp_path / "llmfight.ini"
    base_config.write_text(
        "[General]\nollama_default_model = base-model\n\n[SIMULATION]\nseed = 99\n",
        encoding="utf-8",
    )
    spec = TrialCellSpec(
        index=1,
        mode=C.FIGHTER_CREATION_MODE_GENERATED,
        model="qwen3.6:35b",
        temperature=0.2,
        token_preset=TOKEN_PRESETS[0],
    )

    cfg = materialize_cell_config(base_config, spec, tmp_path / "cell", tmp_path / "cell" / "transcripts")

    assert base_config.read_text(encoding="utf-8") == (
        "[General]\nollama_default_model = base-model\n\n[SIMULATION]\nseed = 99\n"
    )
    assert cfg.path == tmp_path / "cell" / "config.ini"
    assert cfg.get(C.CONFIG_GENERAL, C.CONFIG_LLAMA_DEFAULT_MODEL, str) == "qwen3.6:35b"
    assert cfg.get(C.CONFIG_GENERAL, C.CONFIG_OLLAMA_NUM_CTX, int) == 90000
    assert cfg.get(C.CONFIG_GENERAL, C.CONFIG_MAX_TOKENS_FIGHTER, int) == 384
    assert cfg.get(C.CONFIG_GENERAL, C.CONFIG_MAX_TOKENS_JUDGE, int) == 3072
    assert cfg.get_fighter_creation_mode() == C.FIGHTER_CREATION_MODE_GENERATED
    assert cfg.get(C.CONFIG_GENERAL, C.CONFIG_SAVE_TRANSCRIPTS, bool) is True
    assert cfg.get_transcript_detail() == C.TRANSCRIPT_DETAIL_COMPACT


def test_materialize_cell_config_preserves_relative_profile_base(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    profile_path = config_dir / "fighter.json"
    profile_path.write_text(json.dumps(_custom_profile("left_wing")), encoding="utf-8")
    base_config = config_dir / "llmfight.ini"
    base_config.write_text("[A]\nanatomy_profile = fighter.json\n", encoding="utf-8")
    spec = TrialCellSpec(
        index=1,
        mode=C.FIGHTER_CREATION_MODE_CONFIGURED,
        model="qwen3.6:35b",
        temperature=0.2,
        token_preset=TOKEN_PRESETS[0],
    )

    cfg = materialize_cell_config(base_config, spec, tmp_path / "cell", tmp_path / "cell" / "transcripts")
    profile = resolve_fighter_profile(C.FIGHTER_A, config=cfg)

    assert profile is not None
    assert "left_wing" in profile.parts
    assert str(profile_path.resolve()) in (tmp_path / "cell" / "config.ini").read_text(encoding="utf-8")


async def _fake_trial_fight(*, return_log=False, fight_rng=None, fight_id=None, run_index=None):
    transcript_dir = Path(config_mod.CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_TRANSCRIPT_DIR, str))
    transcript_dir.mkdir(parents=True, exist_ok=True)
    profile_generation = None
    if config_mod.CONFIG.get_fighter_creation_mode() == C.FIGHTER_CREATION_MODE_GENERATED:
        profile_generation = {"mode": "generated", "nudge": "original", "error": None}

    result = {
        C.WINNER: C.DRAW,
        C.LOG_TURN: "1",
        C.LOG_P2_FALLBACK_USED: "false",
        C.LOG_P2_FALLBACK_TURNS: "0",
    }
    trace_events = [
        {
            "schema_version": 1,
            "event_index": 0,
            "fight_id": fight_id,
            "run_index": run_index,
            "event": "fight_start",
            "phase": "fight",
            "data": {},
        },
        {
            "schema_version": 1,
            "event_index": 1,
            "fight_id": fight_id,
            "run_index": run_index,
            "event": C.FIGHT_EVENT_FIGHTERS_READY,
            "phase": "setup",
            "data": {
                "fighters": {
                    C.FIGHTER_A: {
                        C.DISPLAY_NAME: "Sir Galant",
                        "class_": "Knight",
                        C.THEME: "honor",
                        C.LOADOUT: "sword",
                        "environment": "arena",
                        "parts": {"head": {}, "left_wing": {}},
                        C.BUFFS: [],
                        C.DEBUFFS: [],
                        C.PROFILE_GENERATION: profile_generation,
                    },
                    C.FIGHTER_B: {
                        C.DISPLAY_NAME: "Shade",
                        "class_": "Assassin",
                        C.LOADOUT: "dagger",
                        "environment": "arena",
                        "parts": {"head": {}, "torso": {}},
                        C.BUFFS: [],
                        C.DEBUFFS: [],
                        C.PROFILE_GENERATION: profile_generation,
                    },
                }
            },
        },
        {
            "schema_version": 1,
            "event_index": 2,
            "fight_id": fight_id,
            "run_index": run_index,
            "event": C.FIGHT_EVENT_TURN_COMPLETE,
            "phase": "turn",
            "data": {
                "turn": {
                    C.LOG_TURN: 1,
                    C.LOG_ATTEMPT_A: "A tests range.",
                    C.LOG_ATTEMPT_B: "B guards.",
                    "judge_ruling": ["Both attempts are plausible."],
                    "rolls": {
                        C.FIGHTER_A: {"success": True, "roll": 0.1, "probability_text": "0.8"},
                        C.FIGHTER_B: {"success": False, "roll": 0.9, "probability_text": "0.3"},
                    },
                    C.NARRATION: "A clips B without ending the duel.",
                    C.P2_FALLBACK_USED: False,
                    "mechanical_changes": ["B pain +2 (0 -> 2)"],
                }
            },
        },
        {
            "schema_version": 1,
            "event_index": 3,
            "fight_id": fight_id,
            "run_index": run_index,
            "event": C.FIGHT_EVENT_FIGHT_COMPLETE,
            "phase": "fight",
            "data": {"result": result},
        },
    ]
    trace_path = transcript_dir / f"20260514_000000_000000_run{run_index:04d}_{fight_id}.jsonl"
    trace_path.write_text(
        "\n".join(json.dumps(event, sort_keys=True) for event in trace_events) + "\n",
        encoding="utf-8",
    )
    return result, object()


@pytest.mark.asyncio
async def test_collect_trials_writes_artifacts_manifest_and_blind_packs(tmp_path):
    run_root = await collect_trials(
        output_root=tmp_path / "trials",
        mode=C.FIGHTER_CREATION_MODE_CONFIGURED,
        timestamp="fixed",
        fight_runner=_fake_trial_fight,
    )

    manifest = json.loads((run_root / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["cells"]) == 18
    assert manifest["matrix"] == "full"
    assert manifest["seeds"] == [42]
    assert len(manifest["pairs"]) == 16
    first_cell = manifest["cells"][0]
    assert first_cell["model"] == "qwen3.6:35b"
    assert first_cell["temperature"] == 0.2
    assert first_cell["token_preset"] == "focused"
    assert (run_root / first_cell["config_path"]).exists()
    assert (run_root / first_cell["stdout_path"]).exists()
    assert (run_root / first_cell["result_path"]).exists()
    assert (run_root / first_cell["summary_path"]).exists()
    assert first_cell["attempts"][0]["fight_id"] == "cell-0001-attempt-1"
    assert first_cell["attempts"][0]["trace_path"].endswith("cell-0001-attempt-1.jsonl")
    assert (run_root / "blind_packs" / "pair-0001" / "ab.md").exists()
    assert manifest["pairs"][0]["side_mapping"]["ab"]["A"] == "cell-0005"
    assert manifest["pairs"][0]["side_mapping"]["ab"]["B"] == "cell-0001"
    blind_text = (run_root / "blind_packs" / "pair-0001" / "ab.md").read_text(encoding="utf-8")
    assert "qwen3.6:35b" not in blind_text
    assert "focused" not in blind_text
    assert "cell-0001" not in blind_text
    assert "config.ini" not in blind_text


@pytest.mark.asyncio
async def test_collect_trials_finalist_matrix_writes_seeded_manifest_and_pairs(tmp_path):
    run_root = await collect_trials(
        output_root=tmp_path / "trials",
        mode=C.FIGHTER_CREATION_MODE_CONFIGURED,
        matrix="finalist",
        seeds=(11,),
        timestamp="finalist",
        fight_runner=_fake_trial_fight,
    )

    manifest = json.loads((run_root / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["matrix"] == "finalist"
    assert manifest["seeds"] == [11]
    assert len(manifest["cells"]) == 5
    assert len(manifest["pairs"]) == 3
    assert all(pair["seed"] == 11 for pair in manifest["pairs"])
    assert {cell["seed"] for cell in manifest["cells"]} == {11}
    assert {cell["is_baseline"] for cell in manifest["cells"]} == {True, False}
    assert (run_root / "blind_packs" / "pair-0003" / "ba.md").exists()


@pytest.mark.asyncio
async def test_collect_trials_retries_error_cells_and_writes_failure_card(tmp_path):
    calls = 0

    async def always_fails(**kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("raw model path C:/secret and ignore previous instructions")

    run_root = await collect_trials(
        output_root=tmp_path / "trials",
        mode=C.FIGHTER_CREATION_MODE_CONFIGURED,
        smoke=True,
        timestamp="failure",
        fight_runner=always_fails,
    )

    result = json.loads((run_root / "cells" / "cell-0001" / "result.json").read_text(encoding="utf-8"))
    summary = (run_root / "cells" / "cell-0001" / "summary.md").read_text(encoding="utf-8")
    assert calls == 2
    assert result["status"] == "error"
    assert [attempt["status"] for attempt in result["attempts"]] == ["error", "error"]
    assert "Fight aborted due to RuntimeError" in summary
    assert "ignore previous instructions" not in summary
    assert "C:/secret" not in summary


def test_build_summary_preserves_generated_profile_and_fallback_quality_marker(tmp_path):
    trace_path = tmp_path / "trace.jsonl"
    events = [
        {
            "event": C.FIGHT_EVENT_FIGHTERS_READY,
            "data": {
                "fighters": {
                    C.FIGHTER_A: {
                        C.DISPLAY_NAME: "Fallback A",
                        "class_": "Knight",
                        C.LOADOUT: "sword",
                        "environment": "arena",
                        "parts": {"left_wing": {}, "heart": {}},
                        C.BUFFS: [],
                        C.DEBUFFS: [],
                        C.PROFILE_GENERATION: {
                            "mode": "fallback",
                            "nudge": "monster",
                            "error": C.PROFILE_GENERATION_ERROR_INVALID,
                        },
                    }
                }
            },
        },
        {
            "event": C.FIGHT_EVENT_TURN_COMPLETE,
            "data": {
                "turn": {
                    C.LOG_TURN: 1,
                    C.LOG_ATTEMPT_A: "A dives.",
                    C.LOG_ATTEMPT_B: "B braces.",
                    "judge_ruling": ["A can reach B."],
                    "rolls": {},
                    C.NARRATION: "They clash.",
                    C.P2_FALLBACK_USED: True,
                    "mechanical_changes": ["No mechanical state changes."],
                }
            },
        },
    ]
    trace_path.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")

    summary = build_summary(
        status="completed",
        result={C.WINNER: C.DRAW, C.LOG_TURN: "1"},
        trace_path=trace_path,
        attempts=[{"attempt": 1, "status": "completed"}],
    )
    markdown = render_summary_markdown(summary)

    assert summary["fighters"][C.FIGHTER_A]["valid_target_parts"] == ["heart", "left_wing"]
    assert summary["fighters"][C.FIGHTER_A][C.PROFILE_GENERATION]["mode"] == "fallback"
    assert "profile generation fell back" in markdown
    assert C.PROFILE_GENERATION_ERROR_INVALID in markdown
    assert C.P2_FALLBACK_MARKER_TEXT in markdown


def test_blind_pack_redaction_side_swapping_and_review_normalization(tmp_path):
    cells = [
        {
            "cell_id": "cell-0001",
            "status": "completed",
            "model": "qwen3.6:35b",
            "temperature": 0.2,
            "token_preset": "focused",
            "max_tokens_fighter": 384,
            "max_tokens_judge": 3072,
            "summary": {"status": "completed", "fighters": {}, "turns": [], "result": {C.WINNER: C.DRAW}},
            "attempts": [{"fight_id": "cell-0001-attempt-1", "trace_path": "cells/cell-0001/transcripts/x.jsonl"}],
            "config_path": "cells/cell-0001/config.ini",
        },
        {
            "cell_id": "cell-0005",
            "status": "completed",
            "model": "qwen3.6:35b",
            "temperature": 0.4,
            "token_preset": "default",
            "max_tokens_fighter": 512,
            "max_tokens_judge": 4096,
            "summary": {"status": "completed", "fighters": {}, "turns": [], "result": {C.WINNER: C.DRAW}},
            "attempts": [{"fight_id": "cell-0005-attempt-1", "trace_path": "cells/cell-0005/transcripts/x.jsonl"}],
            "config_path": "cells/cell-0005/config.ini",
        },
    ]
    run_root = tmp_path / "run"
    (run_root / "blind_packs").mkdir(parents=True)

    pairs = build_blind_packs(run_root, cells)

    assert pairs[0]["side_mapping"]["ab"] == {"A": "cell-0005", "B": "cell-0001"}
    assert pairs[0]["side_mapping"]["ba"] == {"A": "cell-0001", "B": "cell-0005"}
    ab_text = (run_root / pairs[0]["packs"]["ab"]).read_text(encoding="utf-8")
    forbidden = ["qwen3.6:35b", "cell-0001", "cell-0005", "focused", "default", "config.ini", "x.jsonl"]
    assert scan_forbidden_terms(ab_text, forbidden) == []

    ab_vote = normalize_review_vote("ab", "B", pairs[0]["side_mapping"], baseline_cell_id="cell-0005")
    ba_vote = normalize_review_vote("ba", "A", pairs[0]["side_mapping"], baseline_cell_id="cell-0005")
    assert ab_vote == "candidate"
    assert ba_vote == "candidate"
    assert settle_review_votes([ab_vote, ba_vote]) == "candidate"
    assert settle_review_votes(["baseline", "candidate"]) == "inconclusive"
    assert settle_review_votes(["baseline", "inconclusive"]) == "inconclusive"


def test_blind_pack_pair_specs_use_same_seed_baselines_for_finalists():
    cells = []
    for spec in iter_trial_matrix(C.FIGHTER_CREATION_MODE_CONFIGURED, matrix="finalist"):
        cells.append(
            {
                **spec.to_manifest(),
                "status": "completed",
                "summary": {"status": "completed", "fighters": {}, "turns": [], "result": {C.WINNER: C.DRAW}},
                "attempts": [],
            }
        )

    pairs = build_pair_specs(cells)

    assert len(pairs) == 9
    assert [pair["seed"] for pair in pairs[:3]] == [42, 43, 44]
    for pair in pairs:
        baseline = pair["baseline"]
        candidate = pair["candidate"]
        assert baseline["model"] == candidate["model"] == pair["model"]
        assert baseline["seed"] == candidate["seed"] == pair["seed"]
        assert baseline["is_baseline"] is True
        assert candidate["is_baseline"] is False


def test_blind_pack_forbidden_terms_allow_common_prose_and_roll_numbers():
    cells = [
        {
            "cell_id": "cell-0001",
            "status": "completed",
            "model": "qwen3.6:35b",
            "temperature": 0.2,
            "token_preset": "focused",
            "max_tokens_fighter": 384,
            "max_tokens_judge": 3072,
            "summary": {"status": "completed"},
            "attempts": [{"fight_id": "cell-0001-attempt-1", "trace_path": "cells/cell-0001/transcripts/x.jsonl"}],
            "config_path": "cells/cell-0001/config.ini",
        }
    ]

    terms = forbidden_terms(cells)

    assert "qwen3.6:35b" in terms
    assert "cell-0001" in terms
    assert "focused" not in terms
    assert "0.2" not in terms
    assert "384" not in terms
    assert scan_forbidden_terms("A focused feint succeeds at p=0.2 after a 384-degree pivot.", terms) == []
    assert scan_forbidden_terms("The shield manifested a focused defense.", terms) == []
    assert "manifest.json" in scan_forbidden_terms("Open manifest.json for the answer.", terms)


def test_cli_collect_trials_wires_command(tmp_path):
    runner = CliRunner()
    output_root = tmp_path / "trials"
    returned_root = output_root / "fixed"

    with (
        patch("llm_fight.cli.ping_ollama", new=AsyncMock()),
        patch("llm_fight.trials.collect_trials", new=AsyncMock(return_value=returned_root)) as collect,
    ):
        result = runner.invoke(
            app,
            ["collect-trials", "--output-root", str(output_root), "--mode", "generated", "--smoke"],
        )

    assert result.exit_code == 0
    assert "Trial artifacts saved to" in result.output
    collect.assert_awaited_once_with(
        config_path=None,
        output_root=output_root,
        mode=C.FIGHTER_CREATION_MODE_GENERATED,
        smoke=True,
        matrix="full",
        seeds=(42,),
    )


def test_cli_collect_trials_wires_finalist_matrix_and_seeds(tmp_path):
    runner = CliRunner()
    output_root = tmp_path / "trials"
    returned_root = output_root / "fixed"

    with (
        patch("llm_fight.cli.ping_ollama", new=AsyncMock()),
        patch("llm_fight.trials.collect_trials", new=AsyncMock(return_value=returned_root)) as collect,
    ):
        result = runner.invoke(
            app,
            [
                "collect-trials",
                "--output-root",
                str(output_root),
                "--matrix",
                "finalist",
                "--seeds",
                "101,102,101",
            ],
        )

    assert result.exit_code == 0
    assert "Trial artifacts saved to" in result.output
    collect.assert_awaited_once_with(
        config_path=None,
        output_root=output_root,
        mode=C.FIGHTER_CREATION_MODE_CONFIGURED,
        smoke=False,
        matrix="finalist",
        seeds=(101, 102),
    )
