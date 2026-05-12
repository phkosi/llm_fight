import pytest
import configparser
from llm_fight.config import Config
from llm_fight.engine import constants as C  # For constant keys

# Sample INI content for testing
SAMPLE_INI_CONTENT = """
[General]
llm_model = test_model
max_retries = 5
temperature = 0.75
fighter_A = FighterA
fighter_B = FighterB


[DEFAULTS]
environment = dusty arena

[DEFAULT_FIGHTER]
class = Generic Fighter
loadout = their bare fists and wits

[FighterA]
name = Arnold
class = Barbarian
loadout = axe and shield


[FighterB]
name = Beth
class = Ranger
loadout = bow and arrows

[NonExistentSection]
key = value
"""


@pytest.fixture
def mock_config_file(tmp_path):
    config_file = tmp_path / "test_config.ini"
    with open(config_file, "w") as f:
        f.write(SAMPLE_INI_CONTENT)
    return str(config_file)


@pytest.fixture
def temp_config_instance(mock_config_file):
    # Create a temporary Config instance that reads from the mock file
    # We need to ensure this doesn't interfere with the global CONFIG instance if it's already loaded.
    # The Config class constructor takes a file path, so this should be fine.
    return Config(mock_config_file)


def test_config_loading_correct_values(temp_config_instance):
    assert temp_config_instance.get(C.CONFIG_GENERAL, C.CONFIG_LLAMA_DEFAULT_MODEL, str) == "test_model"
    assert temp_config_instance.get(C.CONFIG_GENERAL, C.CONFIG_MAX_RETRIES, int) == 5
    assert temp_config_instance.get(C.CONFIG_GENERAL, C.CONFIG_LLAMA_TEMPERATURE, float) == 0.75
    assert temp_config_instance.get("FighterA", "name", str) == "Arnold"


def test_get_fighter_settings(temp_config_instance):
    settings = temp_config_instance.get_fighter_settings("FighterA")
    assert settings[C.DISPLAY_NAME] == "Arnold"
    assert settings["class_"] == "Barbarian"
    assert settings["loadout"] == "axe and shield"
    assert settings["environment"] == "dusty arena"


def test_get_fighter_settings_display_name_falls_back_to_stable_id(tmp_path):
    file_path = tmp_path / "names.ini"
    file_path.write_text(
        """
[General]
fighter_A = CustomKnight

[CustomKnight]
class = Knight
loadout = sword
""",
        encoding="utf-8",
    )
    cfg = Config(file_path)

    settings = cfg.get_fighter_settings("CustomKnight", display_name_fallback=C.FIGHTER_A)

    assert settings[C.DISPLAY_NAME] == C.FIGHTER_A
    assert cfg.get_fighter_display_name("CustomKnight", fallback=C.FIGHTER_A) == C.FIGHTER_A


def test_get_fighter_settings_cleans_blank_display_name(tmp_path):
    file_path = tmp_path / "blank_name.ini"
    file_path.write_text("[A]\nname =   \nclass = Knight\nloadout = sword\n", encoding="utf-8")
    cfg = Config(file_path)

    settings = cfg.get_fighter_settings("A", display_name_fallback=C.FIGHTER_A)

    assert settings[C.DISPLAY_NAME] == C.FIGHTER_A


def test_config_get_with_type_conversion(temp_config_instance):
    assert isinstance(temp_config_instance.get(C.CONFIG_GENERAL, C.CONFIG_MAX_RETRIES, int), int)
    assert isinstance(temp_config_instance.get(C.CONFIG_GENERAL, C.CONFIG_LLAMA_TEMPERATURE, float), float)


def test_config_get_with_default_value_section_missing(temp_config_instance):
    assert temp_config_instance.get("MissingSection", "some_key", str, fallback="default_str") == "default_str"
    assert temp_config_instance.get("MissingSection", "some_key", int, fallback=100) == 100
    assert temp_config_instance.get("MissingSection", "some_key", float, fallback=0.5) == 0.5
    assert temp_config_instance.get("MissingSection", "some_key", bool, fallback=True) is True


def test_config_get_with_default_value_key_missing(temp_config_instance):
    assert (
        temp_config_instance.get(C.CONFIG_GENERAL, "missing_key", str, fallback="another_default") == "another_default"
    )
    assert temp_config_instance.get(C.CONFIG_GENERAL, "missing_key_int", int, fallback=20) == 20


def test_config_get_boolean_conversion(tmp_path):
    bool_ini_content = """
[Booleans]
yes_val = yes
true_val = true
on_val = on
1_val = 1
no_val = no
false_val = false
off_val = off
0_val = 0
other_val = something
    """
    config_file = tmp_path / "bool_test.ini"
    with open(config_file, "w") as f:
        f.write(bool_ini_content)

    bool_config = Config(str(config_file))

    assert bool_config.get("Booleans", "yes_val", bool) is True
    assert bool_config.get("Booleans", "true_val", bool) is True
    assert bool_config.get("Booleans", "on_val", bool) is True
    assert bool_config.get("Booleans", "1_val", bool) is True
    assert bool_config.get("Booleans", "no_val", bool) is False
    assert bool_config.get("Booleans", "false_val", bool) is False
    assert bool_config.get("Booleans", "off_val", bool) is False
    assert bool_config.get("Booleans", "0_val", bool) is False

    with pytest.raises(ValueError):  # Non-boolean string should raise error when bool is expected and no fallback
        bool_config.get("Booleans", "other_val", bool)
    assert bool_config.get("Booleans", "other_val", bool, fallback=True) is True  # With fallback


def test_config_get_boolean_string_fallback(tmp_path, temp_config_instance):
    bool_ini_content = """
[Booleans]
other_val = something
    """
    config_file = tmp_path / "bool_fallback.ini"
    with open(config_file, "w") as f:
        f.write(bool_ini_content)

    cfg = Config(str(config_file))

    assert cfg.get("Booleans", "other_val", bool, fallback="False") is False
    assert cfg.get("Booleans", "other_val", bool, fallback="0") is False

    assert temp_config_instance.get("MissingSection", "missing_bool", bool, fallback="False") is False
    assert temp_config_instance.get("MissingSection", "missing_bool", bool, fallback="0") is False


def test_config_get_raises_error_if_no_fallback_and_missing(temp_config_instance):
    with pytest.raises(configparser.NoSectionError):  # Section missing
        temp_config_instance.get("VeryMissingSection", "key", str)
    with pytest.raises(configparser.NoOptionError):  # Key missing in existing section
        temp_config_instance.get(C.CONFIG_GENERAL, "very_missing_key", str)


def test_config_get_raises_type_error_on_bad_conversion(temp_config_instance):
    # This should raise ValueError due to custom error message in Config.get
    with pytest.raises(ValueError, match=r"Failed to cast value 'test_model'.*to int"):
        temp_config_instance.get(C.CONFIG_GENERAL, C.CONFIG_LLAMA_DEFAULT_MODEL, int)


# Test that the global CONFIG instance can also be used, assuming it loads a default config.ini
# This is a bit more of an integration test for the global CONFIG.
# It depends on the actual content of `config.ini` or `config.ini.default`.
# We can make it more robust by ensuring a known default exists or skipping if not.


def test_global_config_instance_loads():
    # This test assumes that either config.ini or config.ini.default exists and is loadable,
    # or that the DEFAULTS in Config are sufficient.
    # A simple check to see if a known default key can be accessed.
    from llm_fight.config import CONFIG

    try:
        # Try accessing a key that IS in DEFAULTS
        assert CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_LLAMA_DEFAULT_MODEL, str) is not None
        # Also check that get with fallback doesn't raise an error for a missing key
        CONFIG.get(C.CONFIG_GENERAL, "some_dummy_key_for_global_test", str, fallback="dummy")
    except Exception as e:
        pytest.fail(f"Global CONFIG instance failed to load or be accessed: {e}")


def test_default_max_turns_loaded(temp_config_instance):
    assert temp_config_instance.get(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, int) == 2


def test_default_ollama_keep_alive_loaded(temp_config_instance):
    assert temp_config_instance.get(C.CONFIG_GENERAL, C.CONFIG_OLLAMA_KEEP_ALIVE, str) == "10m"


def test_default_ollama_num_ctx_loaded(temp_config_instance):
    assert temp_config_instance.get(C.CONFIG_GENERAL, C.CONFIG_OLLAMA_NUM_CTX, int) == 32768


def test_default_ollama_proxy_mode_loaded(temp_config_instance):
    assert temp_config_instance.get(C.CONFIG_GENERAL, C.CONFIG_OLLAMA_PROXY_MODE, str) == C.OLLAMA_PROXY_AUTO


def test_default_fighter_creation_mode_loaded(temp_config_instance):
    assert temp_config_instance.get_fighter_creation_mode() == C.FIGHTER_CREATION_MODE_CONFIGURED


def test_default_judge_phase2_failure_policy_loaded(temp_config_instance):
    assert temp_config_instance.get_judge_phase2_failure_policy() == C.P2_FAILURE_POLICY_FAIL_OPEN


def test_invalid_fighter_creation_mode_raises(tmp_path):
    file_path = tmp_path / "bad_mode.ini"
    file_path.write_text("[General]\nfighter_creation_mode = surprise\n", encoding="utf-8")

    with pytest.raises(ValueError, match="fighter_creation_mode"):
        Config(file_path).get_fighter_creation_mode()


def test_invalid_judge_phase2_failure_policy_raises(tmp_path):
    file_path = tmp_path / "bad_p2_policy.ini"
    file_path.write_text("[General]\njudge_phase2_failure_policy = maybe\n", encoding="utf-8")

    with pytest.raises(ValueError, match="judge_phase2_failure_policy"):
        Config(file_path).get_judge_phase2_failure_policy()


def test_fighter_section_names(temp_config_instance):
    assert temp_config_instance.get(C.CONFIG_GENERAL, C.CONFIG_FIGHTER_A_SECTION, str) == "FighterA"
    assert temp_config_instance.get(C.CONFIG_GENERAL, C.CONFIG_FIGHTER_B_SECTION, str) == "FighterB"


def test_config_save_roundtrip(tmp_path):
    file_path = tmp_path / "round.ini"
    cfg = Config(file_path)
    cfg.set("Custom", "answer", 42)
    cfg.save()

    new_cfg = Config(file_path)
    assert new_cfg.get("Custom", "answer", int) == 42


def test_config_reads_utf8_bom(tmp_path):
    file_path = tmp_path / "bom.ini"
    file_path.write_text("[General]\nmax_retries = 7\n", encoding="utf-8-sig")

    cfg = Config(file_path)

    assert cfg.get(C.CONFIG_GENERAL, C.CONFIG_MAX_RETRIES, int) == 7


def test_use_config_restores_previous_global_config(tmp_path):
    from llm_fight import config as config_mod

    file_path = tmp_path / "scoped.ini"
    file_path.write_text("[SIMULATION]\nseed = 987\n", encoding="utf-8")
    original = config_mod.CONFIG
    scoped = Config(file_path)

    with config_mod.use_config(scoped):
        assert config_mod.CONFIG is scoped
        assert config_mod.CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_SEED, int) == 987

    assert config_mod.CONFIG is original
