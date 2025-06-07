"""Configuration loader and writer for LLM Fight Engine (INI-style)."""

from __future__ import annotations
import configparser
from pathlib import Path
from .engine import constants as C

DEFAULTS = {
    C.CONFIG_GENERAL: {
        C.CONFIG_LLAMA_DEFAULT_MODEL: "llama3.2",
        C.CONFIG_LLAMA_API_URL: "http://localhost:11434/v1/chat/completions",
        C.CONFIG_MAX_TOKENS_FIGHTER: "24000",
        C.CONFIG_MAX_TOKENS_JUDGE: "48000",
        C.CONFIG_LLAMA_TEMPERATURE: "0.8",
        C.CONFIG_BEST_OF_FIGHTER: "3",
        C.CONFIG_BEST_OF_JUDGE: "2",
        C.CONFIG_MAX_RETRIES: "2",
        C.CONFIG_LOG_LEVEL: "OFF",
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
        C.CONFIG_RUNS: "10",
        C.CONFIG_SEED: "42",
        C.CONFIG_CONCURRENT_RUNS: "1",
        C.CONFIG_MAX_TURNS: "100",
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
    C.CONFIG_DISCORD: {
        C.CONFIG_DISCORD_TOKEN: "",
        C.CONFIG_DISCORD_CHANNEL: "",
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

        # Load DEFAULTS first using read_dict.
        self.cp.read_dict(DEFAULTS)

        # Then, load the user's file if it exists.
        # According to docs, values from files read later should take precedence.
        if self.path.exists():
            self.cp.read(self.path)
            self._migrate_old_keys()

    def _migrate_old_keys(self):
        """Handle legacy option names for backwards compatibility."""
        aliases = {
            (C.CONFIG_GENERAL, "llm_model"): C.CONFIG_LLAMA_DEFAULT_MODEL,
            (C.CONFIG_GENERAL, "temperature"): C.CONFIG_LLAMA_TEMPERATURE,
        }

        for (section, old_key), new_key in aliases.items():
            if self.cp.has_option(section, old_key):
                value = self.cp.get(section, old_key)
                self.cp.set(section, new_key, value)
                self.cp.remove_option(section, old_key)

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
            except (configparser.NoSectionError, configparser.NoOptionError):
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

    def get_fighter_settings(self, fighter_id: str) -> dict:
        """Return class, loadout, and environment for a fighter."""
        return {
            "class_": self.get(
                fighter_id,
                C.CONFIG_FIGHTER_CLASS,
                str,
                fallback=self.get(C.CONFIG_DEFAULT_FIGHTER, C.CONFIG_FIGHTER_CLASS, str),
            ),
            "loadout": self.get(
                fighter_id,
                C.CONFIG_FIGHTER_LOADOUT,
                str,
                fallback=self.get(C.CONFIG_DEFAULT_FIGHTER, C.CONFIG_FIGHTER_LOADOUT, str),
            ),
            "environment": self.get(
                fighter_id,
                C.CONFIG_FIGHTER_ENVIRONMENT,
                str,
                fallback=self.get(C.CONFIG_DEFAULTS, C.CONFIG_FIGHTER_ENVIRONMENT, str),
            ),
        }


# convenience singleton
CONFIG = Config()
