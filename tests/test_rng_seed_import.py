import importlib
import random

from src import rng
from src.config import CONFIG
from src.engine import constants as C


def test_rng_seed_import(monkeypatch):
    known_seed = 1234
    original_get = CONFIG.get
    
    with monkeypatch.context() as m:
        def fake_get(section, key, cast=str, fallback=None):
            if section == C.CONFIG_SIMULATION and key == C.CONFIG_SEED:
                return known_seed
            return original_get(section, key, cast, fallback)
        m.setattr(CONFIG, "get", fake_get)
        importlib.reload(rng)
        expected_rng = random.Random(known_seed)
        expected = [expected_rng.random() for _ in range(3)]
        actual = [rng.rand() for _ in range(3)]
        assert actual == expected

    importlib.reload(rng)
