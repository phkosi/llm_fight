"""Trial collection harness for parameter and generated-fighter comparisons."""

from .analysis import analyze_trials
from .profile_eval import collect_profile_trials
from .runner import collect_trials
from .specs import (
    ProfileTrialSpec,
    TokenPreset,
    TrialCellSpec,
    iter_profile_matrix,
    iter_trial_matrix,
    parse_seed_list,
)

__all__ = [
    "ProfileTrialSpec",
    "TokenPreset",
    "TrialCellSpec",
    "analyze_trials",
    "collect_profile_trials",
    "collect_trials",
    "iter_profile_matrix",
    "iter_trial_matrix",
    "parse_seed_list",
]
