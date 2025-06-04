"""Central, seedable PRNG so that simulations are reproducible."""
import random
from typing import Any
from .config import CONFIG
from .engine import constants as C

_seed = int(CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_SEED, int))
_random = random.Random(_seed)

__all__ = ['rand', 'dice', 'seed', 'choice']

def seed(value: int):
    global _random
    _random = random.Random(value)

def rand() -> float:
    """Return float in [0,1)."""
    return _random.random()

def dice(sides: int) -> int:
    """Roll a dice with given sides (inclusive 1..sides)."""
    return _random.randint(1, sides)

def choice(seq: Any) -> Any:
    """Return a random element from a non-empty sequence."""
    return _random.choice(seq)