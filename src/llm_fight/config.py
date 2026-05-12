"""Configuration loader and writer for LLM Fight Engine (INI-style)."""

from __future__ import annotations
import configparser
from pathlib import Path
from .engine import constants as C

DEFAULTS = {
    C.CONFIG_GENERAL: {
        C.CONFIG_LLAMA_DEFAULT_MODEL: "llama3.2:3b",
        C.CONFIG_LLAMA_API_URL: "http://localhost:11434/api/chat",
        C.CONFIG_OLLAMA_KEEP_ALIVE: "10m",
        C.CONFIG_OLLAMA_NUM_CTX: "32768",
        C.CONFIG_MAX_TOKENS_FIGHTER: "512",
        C.CONFIG_MAX_TOKENS_JUDGE: "4096",
        C.CONFIG_LLAMA_TEMPERATURE: "0.4",
        C.CONFIG_BEST_OF_FIGHTER: "1",
        C.CONFIG_BEST_OF_JUDGE: "1",
        C.CONFIG_MAX_RETRIES: "1",
        C.CONFIG_LOG_LEVEL: "INFO",
        C.CONFIG_LOG_COMBAT_TURNS: "false",
        C.CONFIG_SAVE_TRANSCRIPTS: "false",
        C.CONFIG_TRANSCRIPT_DIR: "transcripts",
        C.CONFIG_FIGHTER_SENTENCE_LIMIT: "1",
        C.CONFIG_FIGHTER_WORD_LIMIT: "30",
        C.CONFIG_FIGHTER_A_SECTION: "A",
        C.CONFIG_FIGHTER_B_SECTION: "B",
    },
    C.CONFIG_CONTEXT: {
        C.CONFIG_FIGHTER_LOG_WINDOW: "10",
        C.CONFIG_JUDGE_LOG_WINDOW: "9999",
    },
    C.CONFIG_SIMULATION: {
        C.CONFIG_RUNS: "1",
        C.CONFIG_SEED: "42",
        C.CONFIG_CONCURRENT_RUNS: "1",
        C.CONFIG_MAX_TURNS: "2",
    },
    C.CONFIG_DEFAULTS: {
        C.CONFIG_FIGHTER_ENVIRONMENT: "an open arena",
    },
    C.CONFIG_DEFAULT_FIGHTER: {
        C.CONFIG_FIGHTER_CLASS: "Generic Fighter",
        C.CONFIG_FIGHTER_LOADOUT: "their bare fists and wits",
    },
    "A": {
        C.CONFIG_FIGHTER_CLASS: "Veteran Knight",
        C.CONFIG_FIGHTER_LOADOUT: "longsword and tower shield",
    },
    "B": {
        C.CONFIG_FIGHTER_CLASS: "Cunning Assassin",
        C.CONFIG_FIGHTER_LOADOUT: "poison dagger and smoke bombs",
    },
}


class Config:
    """Simple wrapper around configparser with migration helpers.

    Default values are seeded from :data:`DEFAULTS`. The
    ``concurrent_runs`` option lives under the ``[SIMULATION]`` section.
    """

    def __init__(self, path: Path | str = "llmfight.ini"):
        self.path = Path(path)
        self.cp = configparser.ConfigParser()
        self._explicit_cp = configparser.ConfigParser()

        # Load DEFAULTS first using read_dict.
        self.cp.read_dict(DEFAULTS)

        # Then, load the user's file if it exists.
        # According to docs, values from files read later should take precedence.
        if self.path.exists():
            self._explicit_cp.read(self.path, encoding="utf-8-sig")
            self.cp.read(self.path, encoding="utf-8-sig")
            self._migrate_old_keys()

    def _migrate_old_keys(self):
        """Handle legacy option names for backwards compatibility."""
        aliases = {
            (C.CONFIG_GENERAL, "llm_model"): C.CONFIG_LLAMA_DEFAULT_MODEL,
            (C.CONFIG_GENERAL, "temperature"): C.CONFIG_LLAMA_TEMPERATURE,
        }

        for parser in (self.cp, self._explicit_cp):
            for (section, old_key), new_key in aliases.items():
                if parser.has_option(section, old_key):
                    value = parser.get(section, old_key)
                    parser.set(section, new_key, value)
                    parser.remove_option(section, old_key)

    # --- public API -----------------------------------------------------
    def save(self):
        with self.path.open("w", encoding="utf-8") as fp:
            self.cp.write(fp)

    def get(self, section: str, key: str, cast=str, fallback=None):
        has_section = self.cp.has_section(section)
        has_option = self.cp.has_option(section, key) if has_section else False

        if cast is bool:

            def _parse_bool(value):
                if isinstance(value, bool):
                    return value
                lowered = str(value).strip().lower()
                if lowered in configparser.ConfigParser.BOOLEAN_STATES:
                    return configparser.ConfigParser.BOOLEAN_STATES[lowered]
                raise ValueError(f"'{value}' is not a valid boolean")

            try:
                if not has_option:
                    if fallback is not None:
                        return _parse_bool(fallback)
                    if not has_section:
                        raise configparser.NoSectionError(section)
                    else:
                        raise configparser.NoOptionError(key, section)

                return self.cp.getboolean(section, key)
            except ValueError:
                if fallback is not None:
                    return _parse_bool(fallback)
                original_value = "<not found>"
                if has_option:
                    original_value = self.cp.get(section, key)
                raise ValueError(
                    f"Value for '{key}' in section '{section}' ('{original_value}') is not a valid boolean and no fallback provided."
                )
            except configparser.NoSectionError, configparser.NoOptionError:
                if fallback is not None:
                    return _parse_bool(fallback)
                raise

        # For other types
        if not has_option:  # Key or section missing
            if fallback is not None:
                try:
                    return cast(fallback)
                except ValueError as e:
                    raise ValueError(
                        f"Failed to cast fallback '{fallback}' for key '{key}' in section '{section}' to {cast.__name__}: {e}"
                    ) from e
            # Re-raise the specific error if no fallback
            if not has_section:
                raise configparser.NoSectionError(section)
            else:  # Section exists, but option doesn't
                raise configparser.NoOptionError(key, section)

        val_str = self.cp.get(section, key)
        try:
            return cast(val_str)
        except ValueError as e:
            raise ValueError(
                f"Failed to cast value '{val_str}' for key '{key}' in section '{section}' to {cast.__name__}: {e}"
            ) from e

    def set(self, section: str, key: str, value):
        if not self.cp.has_section(section):
            self.cp.add_section(section)
        self.cp[section][key] = str(value)
        if not self._explicit_cp.has_section(section):
            self._explicit_cp.add_section(section)
        self._explicit_cp[section][key] = str(value)

    def _explicit_section_value(self, section: str, key: str) -> str | None:
        """Return a user-authored/runtime value set directly on ``section``."""
        if not self._explicit_cp.has_section(section):
            return None
        if not self._explicit_cp.has_option(section, key):
            return None
        return self._explicit_cp.get(section, key)

    def get_fighter_profile_reference(self, fighter_id: str) -> str | None:
        """Return the optional custom anatomy profile reference for a fighter."""
        anatomy_profile = self._explicit_section_value(fighter_id, C.CONFIG_FIGHTER_ANATOMY_PROFILE)
        profile_alias = self._explicit_section_value(fighter_id, C.CONFIG_FIGHTER_PROFILE)

        anatomy_value = (anatomy_profile or "").strip()
        alias_value = (profile_alias or "").strip()
        if anatomy_value and alias_value and anatomy_value != alias_value:
            raise ValueError(
                f"Fighter section '{fighter_id}' defines both anatomy_profile and profile with different values."
            )
        return anatomy_value or alias_value or None

    def _fighter_setting(self, fighter_id: str, key: str, *, profile_default: str | None, fallback: str) -> str:
        explicit_value = self._explicit_section_value(fighter_id, key)
        if explicit_value is not None:
            return explicit_value
        if profile_default:
            return profile_default
        return self.get(fighter_id, key, str, fallback=fallback)

    def get_fighter_settings(self, fighter_id: str, profile_defaults: dict | None = None) -> dict:
        """Return class, loadout, and environment for a fighter."""
        profile_defaults = profile_defaults or {}
        default_class = self.get(C.CONFIG_DEFAULT_FIGHTER, C.CONFIG_FIGHTER_CLASS, str)
        default_loadout = self.get(C.CONFIG_DEFAULT_FIGHTER, C.CONFIG_FIGHTER_LOADOUT, str)
        default_environment = self.get(C.CONFIG_DEFAULTS, C.CONFIG_FIGHTER_ENVIRONMENT, str)
        return {
            "class_": self._fighter_setting(
                fighter_id,
                C.CONFIG_FIGHTER_CLASS,
                profile_default=profile_defaults.get("class_"),
                fallback=default_class,
            ),
            "theme": self._fighter_setting(
                fighter_id,
                C.CONFIG_FIGHTER_THEME,
                profile_default=profile_defaults.get(C.THEME),
                fallback=profile_defaults.get(C.THEME) or "",
            ),
            "loadout": self._fighter_setting(
                fighter_id,
                C.CONFIG_FIGHTER_LOADOUT,
                profile_default=profile_defaults.get("loadout"),
                fallback=default_loadout,
            ),
            "environment": self._fighter_setting(
                fighter_id,
                C.CONFIG_FIGHTER_ENVIRONMENT,
                profile_default=profile_defaults.get("environment"),
                fallback=default_environment,
            ),
        }


# convenience singleton
CONFIG = Config()
