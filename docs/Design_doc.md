# LLM Fighters Combat Engine - Design Notes

Status: 2026-05-13. Archived 2025 design notes live in `docs/archive/design-doc-archived-2025.md`.

## Overview

LLM Fighters is a local-first turn-based duel between two LLM-controlled fighters and one Judge/Narrator LLM. Fighters propose free-text actions. The Judge estimates validity and success probability, Python rolls dice, and the Judge returns narration plus structured state deltas.

Python owns deterministic mechanics: configuration, RNG, schema validation, retry policy, prompt budgeting, anatomy state, effect ticks, Phase 2 authorization, winner consistency, logging, transcripts, and CLI workflow.

## Stack

- Python 3.14 or newer.
- Locked `uv` workflow with `uv.lock` committed.
- Runtime package: `llm_fight`, located at `src/llm_fight/`.
- Console script: `llmfight = llm_fight.cli:app`.
- Core runtime deps: `aiohttp`, `jsonschema`, `rich`, `typer`, and `click`.
- Optional extras: `tokens` for `tiktoken`, `live` for Ollama helper-package experiments.

## Product Shape

`llmfight play` is the player front door. It renders fighter designs, live phase status, readable turn sections, roll outcomes, mechanical changes, and the winner.

`llmfight simulate` is a lab/evaluation command for model tuning and regression evidence. It writes batch CSVs and should not drive the first-run player experience.

## Turn Flow

1. Fighter A and Fighter B generate actions concurrently from current state, anatomy, loadout, active effects, and recent history.
2. Judge Phase 1 receives compact state summaries, attempts, and recent combat log, then returns validity and success probabilities.
3. Python resolves rolls through the fight-local RNG.
4. Judge Phase 2 receives attempts, P1 result, successful rolls, valid target parts, current states, and recent combat log, then returns narration and sourced deltas.
5. Python drops consequences from missing, invalid, failed, unknown, or unauthorized sources.
6. Python applies authorized deltas, canonicalizes body parts, ticks eligible effects, updates invariants, and resolves the winner from actual state.
7. Judge-only `fight_end` or `winner` values are ignored unless the resulting Python state is terminal.

## Load-Bearing Guardrails

Do not remove these as “bloat”:

- Layered anatomy, severing, bleeding, burning, pain, exhaustion, heat, body-part consequences, and dynamic effect mechanics.
- Current-state prompt authority and reminders that recent combat log is history.
- Phase 2 source authorization and target canonicalization.
- Strict schemas, post-validation, bounded deltas, prompt budgeting, visible no-op Phase 2 fallback, and metadata-visible engine repair.
- State-authoritative fight endings.
- Opt-in sanitized traces for diagnosing model behavior.

## Anatomy And State

`FighterState` stores mutable fighter state: canonical parts, pain/exhaustion/heat, buffs/debuffs, status, display name, class, theme, loadout, environment, and optional profile-generation metadata.

Stable ids `A` and `B` are the mechanical keys. Display names are user-facing labels only and never replace delta keys, `fighter_id`, or `winner`.

Custom anatomy is mechanical only when it comes from `anatomy_profile` or a validated generated profile. Prose in `class`, `theme`, or `loadout` can influence narration, but it does not create targetable parts by itself. `profile` remains a legacy config alias, but new docs and examples should use `anatomy_profile`.

## LLM I/O

Native Ollama `/api/chat` is the default endpoint. Native requests use schema grammar hints, fixed `num_ctx`, `keep_alive`, `think=false`, and `stream=false`.

OpenAI-compatible `/v1/chat/completions` endpoints remain supported, but native Ollama controls are omitted in that mode. Health checks use `/api/tags` for native mode and `/v1/models` for `/v1` mode.

For advanced endpoint, proxy, transcript, batch, and live-test details, see `docs/ADVANCED.md`.

## Configuration

Config is read at call time through `llm_fight.config.CONFIG`. CLI commands activate a fresh scoped `Config`, apply CLI overrides inside that scope, seed RNG from `[SIMULATION].seed`, and restore previous config/RNG state when the command exits.

Default interactive fights are no longer smoke-test length:

```ini
[SIMULATION]
runs = 1
seed = 42
max_turns = 6
```

Use `uv run llmfight play --max-turns 2 --simple-output` for quick smoke checks.

## Developer Workflow

```bash
uv sync --locked --all-extras --dev
uv run ruff format --check .
uv run ruff check .
uv run mypy src/llm_fight
uv run pytest -q
```

Default tests do not contact Ollama. Live/perf tests are opt-in as documented in `docs/ADVANCED.md`.

## Planning Surfaces

- Root `TODO.md`: active implementation tasks only.
- Root `ISSUES.md`: active bugs, regressions, security risks, prompt failures, test gaps, and code-size findings.
- `DESIGN_ISSUES.md`: product design concerns such as pacing, drama, balance, and readability.
- `docs/archive/`: compact history of resolved work.
