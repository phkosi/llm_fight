"""Shared completion-budget presets for runtime defaults and trials."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TokenPreset:
    """Coupled fighter/judge completion budgets."""

    label: str
    fighter_tokens: int
    judge_tokens: int


TOKEN_PRESETS = (
    TokenPreset("focused", fighter_tokens=384, judge_tokens=3072),
    TokenPreset("default", fighter_tokens=512, judge_tokens=4096),
    TokenPreset("expansive", fighter_tokens=768, judge_tokens=6144),
)
TOKEN_PRESETS_BY_LABEL = {preset.label: preset for preset in TOKEN_PRESETS}
