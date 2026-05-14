"""Model-aware runtime defaults backed by local trial evidence."""

from __future__ import annotations

from dataclasses import dataclass

from .engine import constants as C
from .token_presets import TOKEN_PRESETS_BY_LABEL

AUTO_TEMPERATURE = "auto"
GENERIC_OLLAMA_NUM_CTX = 32768
DEFAULT_TOKEN_PRESET_LABEL = "default"
DEFAULT_TOKEN_PRESET = TOKEN_PRESETS_BY_LABEL[DEFAULT_TOKEN_PRESET_LABEL]

MODEL_MANAGED_KEYS = (
    C.CONFIG_OLLAMA_NUM_CTX,
    C.CONFIG_MAX_TOKENS_FIGHTER,
    C.CONFIG_MAX_TOKENS_JUDGE,
    C.CONFIG_LLAMA_TEMPERATURE,
)


@dataclass(frozen=True)
class ModelDefaults:
    """Built-in defaults for a model with enough local evidence to manage it."""

    model: str
    ollama_temperature: float | None
    max_tokens_fighter: int
    max_tokens_judge: int
    ollama_num_ctx: int
    token_preset: str
    evidence_status: str
    evidence_root: str
    notes: str

    def config_values(self) -> dict[str, str]:
        values = {
            C.CONFIG_OLLAMA_NUM_CTX: str(self.ollama_num_ctx),
            C.CONFIG_MAX_TOKENS_FIGHTER: str(self.max_tokens_fighter),
            C.CONFIG_MAX_TOKENS_JUDGE: str(self.max_tokens_judge),
        }
        if self.ollama_temperature is not None:
            values[C.CONFIG_LLAMA_TEMPERATURE] = str(self.ollama_temperature)
        return values


GENERIC_DEFAULTS = {
    C.CONFIG_OLLAMA_NUM_CTX: str(GENERIC_OLLAMA_NUM_CTX),
    C.CONFIG_MAX_TOKENS_FIGHTER: str(DEFAULT_TOKEN_PRESET.fighter_tokens),
    C.CONFIG_MAX_TOKENS_JUDGE: str(DEFAULT_TOKEN_PRESET.judge_tokens),
    C.CONFIG_LLAMA_TEMPERATURE: AUTO_TEMPERATURE,
}

MODEL_DEFAULTS = {
    "qwen3.6:35b": ModelDefaults(
        model="qwen3.6:35b",
        ollama_temperature=0.4,
        max_tokens_fighter=DEFAULT_TOKEN_PRESET.fighter_tokens,
        max_tokens_judge=DEFAULT_TOKEN_PRESET.judge_tokens,
        ollama_num_ctx=90000,
        token_preset=DEFAULT_TOKEN_PRESET_LABEL,
        evidence_status="provisional_default",
        evidence_root="transcripts/trials/20260514_183917; transcripts/trials/20260514_203736",
        notes="Keep 0.4/default until targeted default-finalization retests clear reliability gates.",
    ),
    "gemma4:26b": ModelDefaults(
        model="gemma4:26b",
        ollama_temperature=0.4,
        max_tokens_fighter=DEFAULT_TOKEN_PRESET.fighter_tokens,
        max_tokens_judge=DEFAULT_TOKEN_PRESET.judge_tokens,
        ollama_num_ctx=90000,
        token_preset=DEFAULT_TOKEN_PRESET_LABEL,
        evidence_status="provisional_default",
        evidence_root="transcripts/trials/20260514_183917; transcripts/trials/20260514_203736",
        notes="Configured and generated retests did not promote a candidate over 0.4/default.",
    ),
}


def normalize_model_name(model: str | None) -> str:
    """Normalize config-provided model names for registry lookup."""
    return " ".join(str(model or "").strip().split())


def defaults_for_model(model: str | None) -> ModelDefaults | None:
    """Return tested defaults for ``model`` when the registry knows it."""
    return MODEL_DEFAULTS.get(normalize_model_name(model))


def model_default_config_values(model: str | None) -> dict[str, str]:
    """Return config values managed for a known model."""
    defaults = defaults_for_model(model)
    if defaults is None:
        return {}
    return defaults.config_values()
