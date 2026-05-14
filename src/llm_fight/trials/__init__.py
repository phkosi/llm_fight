"""Trial collection harness for parameter and generated-fighter comparisons."""

from .runner import collect_trials
from .specs import TokenPreset, TrialCellSpec, iter_trial_matrix

__all__ = [
    "TokenPreset",
    "TrialCellSpec",
    "collect_trials",
    "iter_trial_matrix",
]
