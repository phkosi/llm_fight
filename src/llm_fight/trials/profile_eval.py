"""Profile-only evaluation artifacts for generated fighter reliability."""

from __future__ import annotations

import csv
import json
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from llm_fight import config as config_mod
from llm_fight import rng
from llm_fight.anatomy import BodyPart
from llm_fight.engine import constants as C
from llm_fight.profile_generation import (
    ProfileGenerationError,
    generate_fighter_profile,
    profile_generation_metadata,
)
from llm_fight.profiles import FighterProfile

from .analysis_metrics import HUMANOID_PARTS
from .artifacts import create_timestamped_root, relative_to_root, sha256_file, write_json
from .runner import materialize_cell_config
from .specs import ProfileTrialSpec, TrialCellSpec, TrialMode, iter_profile_matrix
from .summaries import sanitized_error

ProfileGenerator = Callable[..., Awaitable[FighterProfile]]

PROFILE_FIELDS = [
    "profile_id",
    "model",
    "nudge",
    "temperature",
    "token_preset",
    "seed",
    "status",
    "validation_outcome",
    "error",
    "metadata_count",
    "part_count",
    "custom_target_part_count",
    "custom_target_parts",
    "missing_humanoid_part_count",
    "missing_humanoid_parts",
    "altered_body_plan",
    "non_humanoid_body_plan",
    "vital_part_count",
    "terminal_consequence_tag_count",
    "schema_consequence_tag_count",
    "severable_part_count",
    "tissue_layer_count",
    "config_path",
    "result_path",
    "profile_path",
]

SETTING_FIELDS = [
    "model",
    "temperature",
    "token_preset",
    "profiles",
    "generated",
    "fallback",
    "error",
    "fallback_rate",
    "error_rate",
    "altered_body_plan_count",
    "custom_target_part_count",
    "custom_target_parts",
]


async def collect_profile_trials(
    *,
    config_path: Path | None = None,
    output_root: Path = Path("transcripts/profile_trials"),
    smoke: bool = False,
    timestamp: str | None = None,
    profile_generator: ProfileGenerator | None = None,
) -> Path:
    """Sample generated fighter profiles without running fights."""
    run_root = create_timestamped_root(output_root, timestamp)
    (run_root / "profiles").mkdir()
    specs = iter_profile_matrix(smoke=smoke)
    profiles = [
        await _collect_profile(run_root, config_path=config_path, spec=spec, profile_generator=profile_generator)
        for spec in specs
    ]
    analysis = _build_analysis(run_root, smoke=smoke, profiles=profiles)
    write_json(run_root / "analysis.json", analysis)
    (run_root / "analysis.md").write_text(_render_markdown(analysis), encoding="utf-8")
    _write_csv(run_root / "profiles.csv", _profile_csv_rows(profiles), PROFILE_FIELDS)
    _write_csv(run_root / "settings.csv", _settings_csv_rows(analysis["settings"]), SETTING_FIELDS)
    manifest = _build_manifest(run_root, smoke=smoke, profiles=profiles)
    write_json(run_root / "manifest.json", manifest)
    return run_root


async def _collect_profile(
    run_root: Path,
    *,
    config_path: Path | None,
    spec: ProfileTrialSpec,
    profile_generator: ProfileGenerator | None,
) -> dict[str, Any]:
    profile_dir = run_root / "profiles" / spec.profile_id
    profile_dir.mkdir(parents=True, exist_ok=True)
    cfg = materialize_cell_config(
        config_path,
        _profile_spec_as_trial_cell(spec),
        profile_dir,
        profile_dir / "transcripts",
    )
    metadata: list[dict[str, Any]] = []
    generator = profile_generator or generate_fighter_profile
    profile: FighterProfile | None = None
    error: str | None = None
    error_detail: dict[str, str] | None = None
    status = "generated"

    previous_rng_state = rng.get_state()
    try:
        with config_mod.use_config(cfg):
            rng.seed_from_config(cfg)
            profile = await generator(
                C.FIGHTER_A,
                C.FIGHTER_A,
                C.FIGHTER_B,
                spec.nudge,
                config=cfg,
                on_metadata=lambda item: metadata.append(_jsonable_dict(item)),
            )
    except ProfileGenerationError as exc:
        status = "fallback"
        error = exc.code
    except Exception as exc:  # pragma: no cover - exercised through tests with fake generators
        status = "error"
        error = type(exc).__name__
        error_detail = sanitized_error(exc)
    finally:
        rng.set_state(previous_rng_state)

    metrics = profile_originality_metrics(profile) if profile is not None else _empty_profile_metrics()
    profile_path = profile_dir / "profile.json"
    result_path = profile_dir / "result.json"
    if profile is not None:
        write_json(profile_path, profile_to_dict(profile))
    result: dict[str, Any] = {
        **spec.to_manifest(),
        "status": status,
        "validation_outcome": "valid" if status == "generated" else status,
        "error": error,
        "error_detail": error_detail,
        "metadata": metadata,
        "metrics": metrics,
        "profile_generation": profile_generation_metadata(spec.nudge, mode=status, error=error),
        "config_path": relative_to_root(profile_dir / "config.ini", run_root),
        "result_path": relative_to_root(result_path, run_root),
        "profile_path": relative_to_root(profile_path, run_root) if profile is not None else "",
    }
    write_json(result_path, result)
    hashes = {
        "config": sha256_file(profile_dir / "config.ini"),
        "result": sha256_file(result_path),
    }
    if profile is not None:
        hashes["profile"] = sha256_file(profile_path)
    result["hashes"] = hashes
    return result


def _profile_spec_as_trial_cell(spec: ProfileTrialSpec) -> TrialCellSpec:
    return TrialCellSpec(
        index=spec.index,
        mode=cast(TrialMode, C.FIGHTER_CREATION_MODE_GENERATED),
        model=spec.model,
        temperature=spec.temperature,
        token_preset=spec.token_preset,
        seed=spec.seed,
    )


def profile_originality_metrics(profile: FighterProfile | None) -> dict[str, Any]:
    """Return schema-backed anatomy originality metrics for a generated profile."""
    if profile is None:
        return _empty_profile_metrics()
    part_ids = set(profile.parts)
    custom_target_parts = sorted(part_ids - HUMANOID_PARTS)
    missing_humanoid_parts = sorted(HUMANOID_PARTS - part_ids)
    consequence_tags = sorted(
        {tag for part in profile.parts.values() for tag in part.consequence_tags if tag in C.CONSEQUENCE_ALLOWED_TAGS}
    )
    tissue_layers = sorted({layer.name for part in profile.parts.values() for layer in part.layers})
    return {
        "part_count": len(part_ids),
        "custom_target_part_count": len(custom_target_parts),
        "custom_target_parts": custom_target_parts,
        "missing_humanoid_part_count": len(missing_humanoid_parts),
        "missing_humanoid_parts": missing_humanoid_parts,
        "altered_body_plan": bool(part_ids and part_ids != HUMANOID_PARTS),
        "non_humanoid_body_plan": bool(custom_target_parts),
        "vital_part_count": sum(1 for part in profile.parts.values() if part.is_vital),
        "terminal_consequence_tag_count": sum(
            _terminal_tag_count(part.consequence_tags) for part in profile.parts.values()
        ),
        "schema_consequence_tag_count": sum(len(part.consequence_tags) for part in profile.parts.values()),
        "distinct_consequence_tags": consequence_tags,
        "severable_part_count": sum(1 for part in profile.parts.values() if part.can_be_severed),
        "tissue_layer_count": sum(len(part.layers) for part in profile.parts.values()),
        "distinct_tissue_layers": tissue_layers,
        "starting_effect_count": 0,
        "starting_effects_supported": False,
    }


def profile_to_dict(profile: FighterProfile) -> dict[str, Any]:
    """Serialize a validated profile to the public profile JSON shape."""
    return {
        C.CONFIG_FIGHTER_CLASS: profile.class_,
        C.THEME: profile.theme,
        C.LOADOUT: profile.loadout,
        "environment": profile.environment,
        C.BODY_PARTS: [{"id": part_id, **_body_part_to_dict(part)} for part_id, part in sorted(profile.parts.items())],
    }


def _body_part_to_dict(part: BodyPart) -> dict[str, Any]:
    return {
        C.NAME: part.name,
        "is_vital": part.is_vital,
        "can_be_severed": part.can_be_severed,
        C.BLEED_RATE: part.bleed_rate,
        C.BURN_RATE: part.burn_rate,
        C.CONSEQUENCE_TAGS: list(part.consequence_tags),
        C.CONSEQUENCE_GROUP: part.consequence_group,
        "layers": [{C.NAME: layer.name, C.MAX_HP: layer.max_hp} for layer in part.layers],
    }


def _build_analysis(run_root: Path, *, smoke: bool, profiles: list[dict[str, Any]]) -> dict[str, Any]:
    settings = _aggregate_settings(profiles)
    return {
        "schema_version": 1,
        "artifact_type": "profile_evaluation",
        "generated_at": datetime.now(UTC).isoformat(),
        "design_north_star": "tactical_emergence",
        "artifact_root": str(run_root),
        "smoke": smoke,
        "profile_count": len(profiles),
        "totals": _aggregate_totals(profiles),
        "settings": settings,
        "nudges": _aggregate_nudges(profiles),
        "profiles": _profile_csv_rows(profiles),
    }


def _build_manifest(run_root: Path, *, smoke: bool, profiles: list[dict[str, Any]]) -> dict[str, Any]:
    report_paths = {
        "analysis_json": "analysis.json",
        "analysis_md": "analysis.md",
        "profiles_csv": "profiles.csv",
        "settings_csv": "settings.csv",
    }
    return {
        "schema_version": 1,
        "artifact_type": "profile_evaluation",
        "smoke": smoke,
        "artifact_root": str(run_root),
        "models": sorted({str(profile["model"]) for profile in profiles}),
        "nudges": list(C.FIGHTER_CREATION_NUDGES),
        "profiles": [_manifest_profile(profile) for profile in profiles],
        "reports": {
            key: {"path": value, "sha256": sha256_file(run_root / value)} for key, value in report_paths.items()
        },
    }


def _manifest_profile(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in profile.items()
        if key not in {"metadata", "metrics", "error_detail", "profile_generation"}
    }


def _aggregate_totals(profiles: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(str(profile["status"]) for profile in profiles)
    total = len(profiles)
    return {
        "profiles": total,
        "generated": counts["generated"],
        "fallback": counts["fallback"],
        "error": counts["error"],
        "fallback_rate": _rate(counts["fallback"], total),
        "error_rate": _rate(counts["error"], total),
        "altered_body_plan_count": sum(1 for profile in profiles if profile["metrics"]["altered_body_plan"]),
        "non_humanoid_body_plan_count": sum(1 for profile in profiles if profile["metrics"]["non_humanoid_body_plan"]),
        "custom_target_part_count": sum(int(profile["metrics"]["custom_target_part_count"]) for profile in profiles),
    }


def _aggregate_settings(profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for profile in profiles:
        key = (str(profile["model"]), str(profile["temperature"]), str(profile["token_preset"]))
        groups.setdefault(key, []).append(profile)
    rows = []
    for (model, temperature, token_preset), group in sorted(groups.items()):
        totals = _aggregate_totals(group)
        custom_parts = sorted(
            {part for profile in group for part in profile["metrics"].get("custom_target_parts", []) if str(part)}
        )
        rows.append(
            {
                "model": model,
                "temperature": temperature,
                "token_preset": token_preset,
                "profiles": totals["profiles"],
                "generated": totals["generated"],
                "fallback": totals["fallback"],
                "error": totals["error"],
                "fallback_rate": totals["fallback_rate"],
                "error_rate": totals["error_rate"],
                "altered_body_plan_count": totals["altered_body_plan_count"],
                "custom_target_part_count": totals["custom_target_part_count"],
                "custom_target_parts": custom_parts,
            }
        )
    return rows


def _aggregate_nudges(profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for nudge in C.FIGHTER_CREATION_NUDGES:
        group = [profile for profile in profiles if profile["nudge"] == nudge]
        if not group:
            continue
        totals = _aggregate_totals(group)
        rows.append({"nudge": nudge, **totals})
    return rows


def _profile_csv_rows(profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for profile in profiles:
        metrics = profile["metrics"]
        rows.append(
            {
                "profile_id": profile["profile_id"],
                "model": profile["model"],
                "nudge": profile["nudge"],
                "temperature": profile["temperature"],
                "token_preset": profile["token_preset"],
                "seed": profile["seed"],
                "status": profile["status"],
                "validation_outcome": profile["validation_outcome"],
                "error": profile.get("error") or "",
                "metadata_count": len(profile.get("metadata", [])),
                "part_count": metrics["part_count"],
                "custom_target_part_count": metrics["custom_target_part_count"],
                "custom_target_parts": ";".join(metrics["custom_target_parts"]),
                "missing_humanoid_part_count": metrics["missing_humanoid_part_count"],
                "missing_humanoid_parts": ";".join(metrics["missing_humanoid_parts"]),
                "altered_body_plan": metrics["altered_body_plan"],
                "non_humanoid_body_plan": metrics["non_humanoid_body_plan"],
                "vital_part_count": metrics["vital_part_count"],
                "terminal_consequence_tag_count": metrics["terminal_consequence_tag_count"],
                "schema_consequence_tag_count": metrics["schema_consequence_tag_count"],
                "severable_part_count": metrics["severable_part_count"],
                "tissue_layer_count": metrics["tissue_layer_count"],
                "config_path": profile["config_path"],
                "result_path": profile["result_path"],
                "profile_path": profile["profile_path"],
            }
        )
    return rows


def _settings_csv_rows(settings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**row, "custom_target_parts": ";".join(row["custom_target_parts"])} for row in settings]


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _render_markdown(analysis: dict[str, Any]) -> str:
    totals = analysis["totals"]
    lines = [
        "# Generated Profile Evaluation",
        "",
        (
            "Design north star: tactical emergence through generated profiles that validate reliably, "
            "alter anatomy in schema-backed ways, and remain usable by the fight engine."
        ),
        "",
        "## Totals",
        "",
        f"- Profiles: {totals['profiles']}",
        (f"- Outcomes: generated {totals['generated']}, fallback {totals['fallback']}, error {totals['error']}"),
        f"- Fallback rate: {totals['fallback_rate']}",
        f"- Altered body plans: {totals['altered_body_plan_count']}",
        f"- Non-humanoid body plans: {totals['non_humanoid_body_plan_count']}",
        "",
        "## Settings",
        "",
        "| Model | Temp | Tokens | Profiles | Generated | Fallback | Error | Fallback Rate | Custom Parts |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in analysis["settings"]:
        custom_parts = ", ".join(row["custom_target_parts"]) if row["custom_target_parts"] else "none"
        lines.append(
            f"| {row['model']} | {row['temperature']} | {row['token_preset']} | {row['profiles']} | "
            f"{row['generated']} | {row['fallback']} | {row['error']} | {row['fallback_rate']} | "
            f"{custom_parts} |"
        )
    lines.extend(
        [
            "",
            "## Nudges",
            "",
            "| Nudge | Profiles | Generated | Fallback | Error |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in analysis["nudges"]:
        lines.append(
            f"| {row['nudge']} | {row['profiles']} | {row['generated']} | {row['fallback']} | {row['error']} |"
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            (
                "- Starting effects are intentionally measured as unsupported; this harness does not add "
                "runtime mechanics."
            ),
            "- Treat fallback rows as blocked evidence for generated-mode parameter recommendations.",
        ]
    )
    return "\n".join(lines) + "\n"


def _empty_profile_metrics() -> dict[str, Any]:
    return {
        "part_count": 0,
        "custom_target_part_count": 0,
        "custom_target_parts": [],
        "missing_humanoid_part_count": 0,
        "missing_humanoid_parts": [],
        "altered_body_plan": False,
        "non_humanoid_body_plan": False,
        "vital_part_count": 0,
        "terminal_consequence_tag_count": 0,
        "schema_consequence_tag_count": 0,
        "distinct_consequence_tags": [],
        "severable_part_count": 0,
        "tissue_layer_count": 0,
        "distinct_tissue_layers": [],
        "starting_effect_count": 0,
        "starting_effects_supported": False,
    }


def _terminal_tag_count(tags: list[str]) -> int:
    return sum(
        1
        for tag in tags
        if tag
        in {
            C.CONSEQUENCE_FATAL_IF_DESTROYED,
            C.CONSEQUENCE_INCAPACITATING_IF_DESTROYED,
            C.CONSEQUENCE_LEGACY_VITAL_GROUP_MEMBER,
        }
    )


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _jsonable_dict(value: dict[str, Any]) -> dict[str, Any]:
    try:
        json.dumps(value)
        return value
    except TypeError:
        return {str(key): str(item) for key, item in value.items()}
