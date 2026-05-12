import importlib
import random

from llm_fight import config as config_mod
from llm_fight import rng
from llm_fight.config import Config
from llm_fight.config import CONFIG
from llm_fight.engine import constants as C


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


def test_rng_seed_from_config_uses_supplied_config(tmp_path):
    cfg_path = tmp_path / "seeded.ini"
    cfg_path.write_text("[SIMULATION]\nseed = 2468\n", encoding="utf-8")
    cfg = Config(cfg_path)

    rng.seed(1)
    rng.seed_from_config(cfg)

    expected_rng = random.Random(2468)
    assert [rng.rand() for _ in range(3)] == [expected_rng.random() for _ in range(3)]


def test_rng_state_can_be_restored_after_scoped_config_seed(tmp_path):
    cfg_path = tmp_path / "seeded.ini"
    cfg_path.write_text("[SIMULATION]\nseed = 1357\n", encoding="utf-8")
    cfg = Config(cfg_path)
    original_config = config_mod.CONFIG

    rng.seed(99)
    state = rng.get_state()
    expected_after_restore = random.Random(99)

    with config_mod.use_config(cfg):
        rng.seed_from_config()
        assert rng.rand() == random.Random(1357).random()

    rng.set_state(state)

    assert config_mod.CONFIG is original_config
    assert rng.rand() == expected_after_restore.random()
