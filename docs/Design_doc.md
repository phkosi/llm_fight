# LLM Fighters Combat Engine - Design Document

Status: 2026-05-11. Archived design notes remain in `Design_doc_archived_2025.md`.

## 1. Overview

LLM Fighters is a turn-based duel between two local LLM-controlled fighters and one Judge/Narrator LLM. Fighters propose free-text actions. The Judge estimates success probability, Python rolls dice, and the Judge returns a narration plus structured state delta.

Python owns deterministic mechanics: configuration, RNG, schema validation, retry policy, anatomy state, effect ticks, winner consistency, logging, and CLI workflow. The default LLM transport is Ollama native `/api/chat` with structured outputs.

## 2. Stack

- Python 3.14 or newer.
- `uv` lockfile workflow with `uv.lock` committed.
- Runtime package: `llm_fight`, located at `src/llm_fight/`.
- CLI scripts:
  - `llmfight = llm_fight.cli:app`
- Core runtime deps: `aiohttp`, `jsonschema`, `rich`, `typer`, `click`.
- Optional extras:
  - `tokens` for `tiktoken` token counting.
  - `live` for Ollama helper package experiments.

## 3. Package Layout

```text
src/llm_fight/
|-- agents.py          # async Ollama client
|-- anatomy.py         # body presets and fresh tissue layers
|-- cli.py             # Typer CLI
|-- config.py          # INI loader
|-- judge.py           # judge phase orchestration
|-- rng.py             # central PRNG
|-- simulation.py      # fight loop and batch runs
|-- state.py           # FighterState mutation and invariants
|-- transcripts.py     # transcript logging
|-- validation.py      # JSON schemas and guarded_call
|-- engine/
|   |-- combat_log.py
|   |-- constants.py
|   |-- fighter.py
|   |-- logger.py
|   |-- prompts.py
|   `-- render.py
`-- utils/
    |-- json_parser.py
    `-- token_counter.py
```

`run.py` is a compatibility shim only. Prefer `llmfight`.

## 4. Turn Flow

1. Fighter A and Fighter B generate actions concurrently.
2. Judge Phase 1 receives compact fighter summaries, attempts, and recent combat log.
3. Phase 1 returns strict JSON with validity and probability for each attempt.
4. Python rolls success using the central PRNG.
5. Judge Phase 2 receives attempts, full P1 result, `successful_rolls`, combat log context, valid body parts, and current fighter states.
6. Phase 2 returns strict JSON containing narration, delta, `fight_end`, and `winner`. Every state-changing delta entry must include `source: "A" | "B"` for the fighter whose valid current action succeeded.
7. Python drops delta consequences with missing, unknown, invalid, or failed sources before state mutation. Authorized consequences may target either fighter, including self-costs.
8. Python applies authorized deltas, normalizes body-part and damage aliases, ticks eligible effects, re-checks status invariants, and resolves winner consistency from final state. Judge-only `fight_end` or `winner` values are ignored unless the resulting Python state is terminal.

## 5. Anatomy And State

`FighterState` owns mutable per-fighter state:

- `parts`: body-part map with fresh `TissueLayer` instances per part and per fighter.
- `pain`, `exhaustion`, `heat`.
- `buffs` and `debuffs` as `Effect` objects.
- `status`: `fighting`, `unconscious`, or `dead`.
- `class_`, `loadout`, and `environment` from config.

Critical invariants:

- Unknown targeted parts are rejected before damage is applied.
- Common natural-language aliases such as `chest` and `left arm` normalize to canonical body parts.
- Burning and bleeding ticks can cause KO/death after effect application.
- Effects created by a delta or wound side effect are visible in state and in the next turn's fighter/judge context before their first eligible tick.
- Effects that existed before the current delta remain eligible and tick once per turn.
- Destroyed vital parts and pain thresholds update status immediately.

## 6. Ollama I/O

Default endpoint:

```ini
ollama_api_url = http://localhost:11434/api/chat
```

Native Ollama requests use:

- `format` for JSON schema structured outputs.
- `options.num_predict` for generation limit.
- fixed `options.num_ctx` from `ollama_num_ctx` for every fighter and judge call.
- top-level `keep_alive` for model residency between turn requests.
- `stream: false`.

OpenAI-compatible `/v1/chat/completions` endpoints remain supported and use `response_format`.

## 7. Configuration

Config is read at call time through `llm_fight.config.CONFIG` or explicit `Config` replacement from the CLI. Avoid import-time copies of config-derived values.

Important keys:

```ini
[General]
ollama_default_model = llama3.2:3b
ollama_api_url = http://localhost:11434/api/chat
ollama_keep_alive = 10m
ollama_num_ctx = 32768
max_tokens_fighter = 512
max_tokens_judge = 4096
ollama_temperature = 0.4
best_of_fighter = 1
best_of_judge = 1
max_retries = 1
fighter_A = A
fighter_B = B

[CONTEXT]
fighter_log_window = 10
judge_log_window = 9999

[SIMULATION]
runs = 1
seed = 42
concurrent_runs = 1
max_turns = 2
```

Batch runs derive an isolated per-fight RNG stream from `[SIMULATION].seed`
and the run index, so concurrent scheduling or model latency does not change a
run's dice rolls or random effect-layer choices. Batch CSV output stays ordered
by run index and still flushes incrementally whenever the next ordered result is
available.

## 8. Developer Workflow

```bash
uv sync --locked --all-extras --dev
uv run black --check .
uv run flake8
uv run pytest -q
```

Live tests are opt-in:

```bash
uv run pytest -q --run-live
```

CI runs on Python 3.14 with the same locked `uv` workflow.

## 9. Future Work

- Replayable trace format for deterministic debugging.
- Stronger typed request/response objects around LLM calls.
- Better cancellation and timeout reporting for batch runs.
- Visual replay tooling once the combat log format stabilizes.
