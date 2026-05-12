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

Run quality checks:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src/llm_fight
uv run pytest -q
```

Live Ollama tests are skipped by default. Opt in only when Ollama is intentionally running and configured:

```bash
uv sync --locked --all-extras --dev
uv run pytest -q --run-live
```

Heavy performance probes are separately gated:

```bash
uv run pytest -q --run-live --run-perf tests/test_memory_usage.py
```

## Playtest Loop

Invoke this workflow when the user asks for the "playtest loop".

Default playtest command:

```bash
uv run llmfight play
```

If the user names a config, include it explicitly:

```bash
uv run llmfight play --config <path>
```

During each playtest pass, inspect terminal output, generated transcripts, state changes, prompt behavior, gameplay logic, and user-facing responsiveness. Add bugs, regressions, security risks, test gaps, prompt failures, and gameplay-system failures to `ISSUES.md`. If an issue already exists, append new evidence to the existing entry instead of creating a duplicate.

Use `DESIGN_ISSUES.md` for game design concerns that are not clearly erroneous, such as pacing problems, unclear fantasy, weak drama, boring but valid strategies, or balance concerns. Do not automatically create `TODO.md` implementation tasks from design issues unless the user asks.

## Code Size Review

During codebase reviews, implementation reviews, playtest-loop code review passes, and before committing broad Python changes, check for monolithic Python files and oversized functions. If a file crosses the thresholds below, add or update an `ISSUES.md` entry instead of leaving the finding only in chat. If a matching issue already exists, append current evidence there rather than creating a duplicate.

Use these thresholds:

- Production modules under `src/`: target 150-350 physical LOC, warn at 500 LOC, create/update an issue at 700 LOC, and treat 1000+ LOC as urgent refactor pressure.
- Test modules under `tests/`: target under 500 physical LOC, create/update an issue at 800 LOC, and treat 1000+ LOC as urgent test-suite refactor pressure.
- Functions or methods: target under 75 LOC, create/update an issue for 100+ LOC or for roughly 50+ statements when this contributes to a large-file problem.
- Generated files, vendored code, and intentionally flat constants/enums may be exempt, but note the exemption in the review.

When logging a code-size issue, include the measured LOC, the largest functions/classes, why the current responsibilities are too broad, suggested split boundaries, and tests needed to keep behavior stable during extraction.

`ISSUES.md` issue entries should support these tracking fields:

- `Status: open | tasked | resolved`
- `Task: none | TODO.md - <section/task>`
- `Source: playtest | codebase review | implementation review`
- `Evidence:`
- `Impact:`
- `Suggested fix:`
- `Tests:`

When unresolved `ISSUES.md` entries need implementation work, use architect subagents to design tasks for `TODO.md`. Each issue-backed TODO task should include `Addresses: ISSUE-###`, implementation intent, acceptance goals, and required tests. Once a task exists, update the source issue with `Task: TODO.md - <section/task>` and mark its status as `tasked` to avoid duplicate task creation.

A review subagent must review each proposed TODO task against the codebase before implementation. If the task design has problems, revise the task first. If approved, implement exactly one TODO task at a time.

After implementation, give the diff to review subagents and iterate until no blocking issues remain. Before committing any codebase change, a hard gate is a 2-subagent review of the diff with both reviewers reporting no blocking issues.

Continue the loop from issues to tasks to implementation to review to playtest until no actionable issues remain. If 5 consecutive playtest runs find no issues, replace the next playtest pass with a full codebase review focused on gameplay systems, logic and reasoning, and prompt strength. Add review findings to `ISSUES.md`, and add non-error design concerns to `DESIGN_ISSUES.md`.

## Project Layout

- `src/llm_fight/agents.py` - async Ollama client.
- `src/llm_fight/anatomy.py` - body part presets and tissue layers.
- `src/llm_fight/cli.py` - Typer command line interface.
- `src/llm_fight/config.py` - INI loader.
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
