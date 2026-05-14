"""Trial matrix definitions for local parameter comparisons."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, cast

from llm_fight.engine import constants as C
from llm_fight.token_presets import TOKEN_PRESETS, TOKEN_PRESETS_BY_LABEL, TokenPreset

TrialMode = Literal["configured", "generated"]
TrialMatrix = Literal["full", "finalist", "default-finalization"]

MODEL_ORDER = ("qwen3.6:35b", "gemma4:26b")
TEMPERATURES = (0.2, 0.4, 0.7)
BASELINE_TEMPERATURE = 0.4
BASELINE_TOKEN_PRESET = "default"
DEFAULT_SEED = 42
DEFAULT_FINALIST_SEEDS = (42, 43, 44)
DEFAULT_OLLAMA_NUM_CTX = 90000
DEFAULT_MAX_TURNS = 6


FINALIST_SETTINGS = {
    "qwen3.6:35b": (
        (BASELINE_TEMPERATURE, BASELINE_TOKEN_PRESET),
        (0.2, "expansive"),
    ),
    "gemma4:26b": (
        (BASELINE_TEMPERATURE, BASELINE_TOKEN_PRESET),
        (0.2, "expansive"),
        (0.7, "focused"),
    ),
}
DEFAULT_FINALIZATION_SETTINGS = {
    "qwen3.6:35b": (
        (BASELINE_TEMPERATURE, BASELINE_TOKEN_PRESET),
        (0.2, "expansive"),
        (0.4, "expansive"),
        (0.4, "focused"),
    ),
    "gemma4:26b": (
        (BASELINE_TEMPERATURE, BASELINE_TOKEN_PRESET),
        (0.2, "expansive"),
        (0.7, "focused"),
        (0.2, "default"),
        (0.4, "expansive"),
        (0.7, "expansive"),
    ),
}


@dataclass(frozen=True)
class TrialCellSpec:
    """One model/temperature/token/mode cell in the trial grid."""

    index: int
    mode: TrialMode
    model: str
    temperature: float
    token_preset: TokenPreset
    seed: int = DEFAULT_SEED

    @property
    def cell_id(self) -> str:
        return f"cell-{self.index:04d}"

    @property
    def is_baseline(self) -> bool:
        return self.temperature == BASELINE_TEMPERATURE and self.token_preset.label == BASELINE_TOKEN_PRESET

    def to_manifest(self) -> dict[str, object]:
        return {
            "cell_id": self.cell_id,
            "mode": self.mode,
            "model": self.model,
            "temperature": self.temperature,
            "token_preset": self.token_preset.label,
            "max_tokens_fighter": self.token_preset.fighter_tokens,
            "max_tokens_judge": self.token_preset.judge_tokens,
            "seed": self.seed,
            "is_baseline": self.is_baseline,
        }


@dataclass(frozen=True)
class ProfileTrialSpec:
    """One model/nudge sample for generated-profile evaluation."""

    index: int
    model: str
    nudge: str
    temperature: float = BASELINE_TEMPERATURE
    token_preset: TokenPreset = TOKEN_PRESETS[1]
    seed: int = DEFAULT_SEED

    @property
    def profile_id(self) -> str:
        return f"profile-{self.index:04d}"

    def to_manifest(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "model": self.model,
            "nudge": self.nudge,
            "temperature": self.temperature,
            "token_preset": self.token_preset.label,
            "max_tokens_fighter": self.token_preset.fighter_tokens,
            "max_tokens_judge": self.token_preset.judge_tokens,
            "seed": self.seed,
        }


def normalize_mode(mode: str) -> TrialMode:
    normalized = str(mode).strip().lower()
    if normalized == C.FIGHTER_CREATION_MODE_CONFIGURED:
        return cast(TrialMode, C.FIGHTER_CREATION_MODE_CONFIGURED)
    if normalized == C.FIGHTER_CREATION_MODE_GENERATED:
        return cast(TrialMode, C.FIGHTER_CREATION_MODE_GENERATED)
    raise ValueError("mode must be 'configured' or 'generated'")


def normalize_matrix(matrix: str) -> TrialMatrix:
    normalized = str(matrix).strip().lower()
    if normalized == "defaults":
        normalized = "default-finalization"
    if normalized in {"full", "finalist", "default-finalization"}:
        return cast(TrialMatrix, normalized)
    raise ValueError("matrix must be 'full', 'finalist', or 'default-finalization'")


def parse_seed_list(seed_text: str | None, *, matrix: str = "full") -> tuple[int, ...]:
    """Parse a comma-separated seed list, applying matrix defaults when absent."""
    trial_matrix = normalize_matrix(matrix)
    if seed_text is None or not str(seed_text).strip():
        return DEFAULT_FINALIST_SEEDS if trial_matrix in {"finalist", "default-finalization"} else (DEFAULT_SEED,)
    seeds = []
    for raw_seed in str(seed_text).split(","):
        raw_seed = raw_seed.strip()
        if not raw_seed:
            continue
        try:
            seed = int(raw_seed)
        except ValueError as exc:
            raise ValueError(f"Invalid seed value: {raw_seed!r}") from exc
        if seed not in seeds:
            seeds.append(seed)
    if not seeds:
        raise ValueError("At least one seed is required.")
    return tuple(seeds)


def iter_trial_matrix(
    mode: str,
    *,
    smoke: bool = False,
    matrix: str = "full",
    seeds: Sequence[int] | None = None,
    models: Sequence[str] | None = None,
) -> list[TrialCellSpec]:
    """Return the fixed qwen-then-gemma trial matrix."""
    trial_mode = normalize_mode(mode)
    trial_matrix = normalize_matrix(matrix)
    matrix_seeds = tuple(seeds) if seeds is not None else parse_seed_list(None, matrix=trial_matrix)
    cells = []
    index = 1
    for seed in matrix_seeds:
        for model, temperature, preset in _matrix_settings(trial_matrix, models=models):
            cells.append(
                TrialCellSpec(
                    index=index,
                    mode=trial_mode,
                    model=model,
                    temperature=temperature,
                    token_preset=preset,
                    seed=seed,
                )
            )
            index += 1
    return cells[:1] if smoke else cells


def iter_profile_matrix(*, smoke: bool = False) -> list[ProfileTrialSpec]:
    """Return the fixed model/nudge matrix for profile-only evaluation."""
    profiles = []
    index = 1
    for model in MODEL_ORDER:
        for nudge in C.FIGHTER_CREATION_NUDGES:
            profiles.append(ProfileTrialSpec(index=index, model=model, nudge=nudge))
            index += 1
    return profiles[:1] if smoke else profiles


def _normalize_model_filter(matrix: TrialMatrix, models: Sequence[str] | None) -> tuple[str, ...]:
    selected: tuple[str, ...]
    if models is None:
        selected = MODEL_ORDER
    else:
        selected = tuple(str(model).strip() for model in models if str(model).strip())
        if not selected:
            raise ValueError("At least one model is required when --model is used.")
    unknown = [model for model in selected if model not in MODEL_ORDER]
    if unknown:
        allowed = ", ".join(MODEL_ORDER)
        raise ValueError(f"Unknown trial model(s): {', '.join(unknown)}. Allowed models: {allowed}")
    if matrix == "default-finalization" and len(selected) != 1:
        raise ValueError("default-finalization matrix requires exactly one --model value.")
    return selected


def _matrix_settings(
    matrix: TrialMatrix, *, models: Sequence[str] | None = None
) -> list[tuple[str, float, TokenPreset]]:
    settings = []
    selected_models = _normalize_model_filter(matrix, models)
    if matrix == "full":
        for model in selected_models:
            for temperature in TEMPERATURES:
                for preset in TOKEN_PRESETS:
                    settings.append((model, temperature, preset))
        return settings
    matrix_settings = DEFAULT_FINALIZATION_SETTINGS if matrix == "default-finalization" else FINALIST_SETTINGS
    for model in selected_models:
        for temperature, token_preset in matrix_settings[model]:
            settings.append((model, temperature, TOKEN_PRESETS_BY_LABEL[token_preset]))
    return settings
