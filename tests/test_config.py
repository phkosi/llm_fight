import pytest
import configparser
from src.config import Config
from src.engine import constants as C  # For constant keys

# Sample INI content for testing
SAMPLE_INI_CONTENT = """
[General]
llm_model = test_model
max_retries = 5
temperature = 0.75

[FighterA]
name = Arnold
class = Barbarian
loadout = axe and shield
environment = dusty arena

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
    assert settings["class_"] == "Barbarian"
    assert settings["loadout"] == "axe and shield"
    assert settings["environment"] == "dusty arena"

def test_config_get_with_type_conversion(temp_config_instance):
    assert isinstance(temp_config_instance.get(C.CONFIG_GENERAL, C.CONFIG_MAX_RETRIES, int), int)
    assert isinstance(temp_config_instance.get(C.CONFIG_GENERAL, C.CONFIG_LLAMA_TEMPERATURE, float), float)

def test_config_get_with_default_value_section_missing(temp_config_instance):
    assert temp_config_instance.get("MissingSection", "some_key", str, fallback="default_str") == "default_str"
    assert temp_config_instance.get("MissingSection", "some_key", int, fallback=100) == 100
    assert temp_config_instance.get("MissingSection", "some_key", float, fallback=0.5) == 0.5
    assert temp_config_instance.get("MissingSection", "some_key", bool, fallback=True) is True

def test_config_get_with_default_value_key_missing(temp_config_instance):
    assert temp_config_instance.get(C.CONFIG_GENERAL, "missing_key", str, fallback="another_default") == "another_default"
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
    
    with pytest.raises(ValueError): # Non-boolean string should raise error when bool is expected and no fallback
        bool_config.get("Booleans", "other_val", bool)
    assert bool_config.get("Booleans", "other_val", bool, fallback=True) is True # With fallback

def test_config_get_raises_error_if_no_fallback_and_missing(temp_config_instance):
    with pytest.raises(configparser.NoSectionError): # Section missing
        temp_config_instance.get("VeryMissingSection", "key", str)
    with pytest.raises(configparser.NoOptionError): # Key missing in existing section
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
    from src.config import CONFIG
    try:
        # Try accessing a key that IS in DEFAULTS
        assert CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_LLAMA_DEFAULT_MODEL, str) is not None
        # Also check that get with fallback doesn't raise an error for a missing key
        CONFIG.get(C.CONFIG_GENERAL, "some_dummy_key_for_global_test", str, fallback="dummy")
    except Exception as e:
        pytest.fail(f"Global CONFIG instance failed to load or be accessed: {e}") 
