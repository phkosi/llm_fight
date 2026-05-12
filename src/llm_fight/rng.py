"""Central, seedable PRNG so that simulations are reproducible."""

import random
from typing import Any
from . import config as config_mod
from .engine import constants as C

_random = random.Random()

__all__ = ["rand", "dice", "seed", "seed_from_config", "get_state", "set_state", "choice"]


def seed(value: int):
    global _random
    _random = random.Random(value)


def seed_from_config(config=None) -> None:
    """Seed the process RNG from the supplied or active config."""
    cfg = config or config_mod.CONFIG
    seed(cfg.get(C.CONFIG_SIMULATION, C.CONFIG_SEED, int))


def get_state() -> object:
    """Return the current process RNG state for later restoration."""
    return _random.getstate()


def set_state(state: object) -> None:
    """Restore a process RNG state captured by ``get_state``."""
    _random.setstate(state)


def rand() -> float:
    """Return float in [0,1)."""
    return _random.random()


def dice(sides: int) -> int:
    """Roll a dice with given sides (inclusive 1..sides)."""
    return _random.randint(1, sides)


def choice(seq: Any) -> Any:
    """Return a random element from a non-empty sequence."""
    return _random.choice(seq)


seed_from_config()
