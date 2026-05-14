"""Trial matrix definitions for local parameter comparisons."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from llm_fight.engine import constants as C

TrialMode = Literal["configured", "generated"]

MODEL_ORDER = ("qwen3.6:35b", "gemma4:26b")
TEMPERATURES = (0.2, 0.4, 0.7)
BASELINE_TEMPERATURE = 0.4
BASELINE_TOKEN_PRESET = "default"
DEFAULT_SEED = 42
DEFAULT_OLLAMA_NUM_CTX = 90000
DEFAULT_MAX_TURNS = 6


@dataclass(frozen=True)
class TokenPreset:
    """Coupled fighter/judge completion budgets for one trial cell."""

    label: str
    fighter_tokens: int
    judge_tokens: int


TOKEN_PRESETS = (
    TokenPreset("focused", fighter_tokens=384, judge_tokens=3072),
    TokenPreset("default", fighter_tokens=512, judge_tokens=4096),
    TokenPreset("expansive", fighter_tokens=768, judge_tokens=6144),
)


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


def normalize_mode(mode: str) -> TrialMode:
    normalized = str(mode).strip().lower()
    if normalized == C.FIGHTER_CREATION_MODE_CONFIGURED:
        return cast(TrialMode, C.FIGHTER_CREATION_MODE_CONFIGURED)
    if normalized == C.FIGHTER_CREATION_MODE_GENERATED:
        return cast(TrialMode, C.FIGHTER_CREATION_MODE_GENERATED)
    raise ValueError("mode must be 'configured' or 'generated'")


def iter_trial_matrix(mode: str, *, smoke: bool = False) -> list[TrialCellSpec]:
    """Return the fixed qwen-then-gemma trial matrix."""
    trial_mode = normalize_mode(mode)
    cells = []
    index = 1
    for model in MODEL_ORDER:
        for temperature in TEMPERATURES:
            for preset in TOKEN_PRESETS:
                cells.append(
                    TrialCellSpec(
                        index=index,
                        mode=trial_mode,
                        model=model,
                        temperature=temperature,
                        token_preset=preset,
                    )
                )
                index += 1
    return cells[:1] if smoke else cells
