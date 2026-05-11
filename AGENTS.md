# Guidelines for Codex

This repository contains a Python 3.14 turn-based combat simulator where local LLM agents fight under a judge LLM. Source code lives in `src/llm_fight/`; tests live in `tests/`.

## Setup

Use the locked `uv` workflow:

```bash
uv sync --locked --all-extras --dev
```

`pyproject.toml` is the dependency source of truth. `requirements.txt` and `requirements-dev.txt` are generated compatibility exports from `uv.lock`.

Copy `llmfight.ini.example` to `llmfight.ini` before running the app manually.

## Commands

Run the game:

```bash
uv run llmfight play
uv run llmfight simulate
```

Run the optional Discord bot:

```bash
uv run llmfight-discord
```

Run quality checks:

```bash
uv run black --check .
uv run flake8
uv run pytest -q
```

Live Ollama tests are skipped by default. Opt in only when Ollama is intentionally running and configured:

```bash
uv run pytest -q --run-live
```

## Project Layout

- `src/llm_fight/agents.py` - async Ollama client.
- `src/llm_fight/anatomy.py` - body part presets and tissue layers.
- `src/llm_fight/cli.py` - Typer command line interface.
- `src/llm_fight/config.py` - INI loader.
- `src/llm_fight/discord_bot.py` - optional Discord integration.
- `src/llm_fight/judge.py` - judge orchestration.
- `src/llm_fight/rng.py` - central random number generator.
- `src/llm_fight/simulation.py` - fight loop and batch harness.
- `src/llm_fight/state.py` - fighter dataclasses and state update logic.
- `src/llm_fight/validation.py` - JSON schema helpers and guarded LLM calls.
- `src/llm_fight/engine/` - constants, prompts, rendering, logging, and combat-log helpers.

## Style Notes

- Use `apply_patch` for manual edits.
- Keep constants in `src/llm_fight/engine/constants.py`.
- Prefer the repository logger over `print`.
- Add or update tests when changing behavior.
- Update `README.md` and `docs/` when CLI, config, packaging, or gameplay contracts change.
- Do not reintroduce import-time cached config values for runtime behavior; read config at call time or pass explicit config.
