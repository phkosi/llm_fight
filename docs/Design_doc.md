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
- `display_name`, `class_`, `loadout`, and `environment` from config.

`id` remains the authoritative mechanics key (`A` or `B`). `display_name` is a
human-facing label shown in prompts, traces, and terminal output; omitted names
fall back to the stable id and never replace delta keys, `fighter_id`, or
`winner` values.

Critical invariants:

- Unknown targeted parts are rejected before damage is applied.
- Common natural-language aliases such as `chest` and `left arm` normalize to canonical body parts.
- Burning and bleeding ticks can cause KO/death after effect application.
- Effects created by a delta or wound side effect are visible in state and in the next turn's fighter/judge context before their first eligible tick.
- Effects that existed before the current delta remain eligible and tick once per turn.
- Judge-facing effect removals are structured source-bearing selectors `{source, name, type?, targeted_part?}`. Missing `type` matches both buffs and debuffs; missing `targeted_part` is intentional remove-all for that name/type scope; supplied targets are canonicalized before state mutation.
- Tissue layers keep stable `max_hp`; damage lowers `current_hp` and clamps at zero.
- Humanoid blood-bearing parts define preset `bleed_rate` values; piercing/slashing wounds can create targeted bleeding effects from those rates.
- Burning effects use target-part `burn_rate` for tick damage and mutate the selected active tissue layer directly, so debug logs name the layer that actually lost `current_hp`.
- Destroyed or severed parts apply explicit anatomy consequence tags. Default humanoid heart/head destruction is fatal, torso destruction is incapacitating, and eye/leg loss creates persistent visible consequence debuffs.
- Legacy custom-profile `is_vital` fields are translated to explicit terminal policies at load time.
- Pain thresholds still update status immediately.

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

OpenAI-compatible `/v1/chat/completions` endpoints remain supported and use
`response_format`. In `/v1` mode, native Ollama-only controls such as
`keep_alive`, `options.num_ctx`, `think`, `stream`, and native `format` are not
sent; the app logs one warning that those native settings are ignored. Native
health checks use `/api/tags`, while OpenAI-compatible health checks use
`/v1/models`.

## 7. Configuration

Config is read at call time through `llm_fight.config.CONFIG` or explicit `Config` replacement from the CLI. Avoid import-time copies of config-derived values.

Important keys:

```ini
[General]
ollama_default_model = llama3.2:3b
ollama_api_url = http://localhost:11434/api/chat
ollama_keep_alive = 10m
ollama_num_ctx = 32768
ollama_proxy_mode = auto
max_tokens_fighter = 512
max_tokens_judge = 4096
ollama_temperature = 0.4
best_of_fighter = 1
best_of_judge = 1
max_retries = 1
judge_phase2_failure_policy = fail_open
fighter_A = A
fighter_B = B
fighter_creation_mode = configured

[CONTEXT]
fighter_log_window = 10
judge_log_window = 9999

[SIMULATION]
runs = 1
seed = 42
concurrent_runs = 1
max_turns = 2
```

`ollama_proxy_mode = auto` disables environment proxy use for loopback endpoints
and enables it for remote endpoints. `disabled` always uses direct connections;
`enabled` always honors environment proxies, including loopback.

Prompt budgeting is enforced before transport. Fighter actions, Judge Phase 1,
Judge Phase 2, Judge Phase 2 repair, and generated profile calls reserve
phase-specific completion tokens. Combat-log context is the only prompt content
trimmed automatically: older lines are dropped first, while current state,
attempts, rolls, valid target parts, and active-effect reminders remain
authoritative. If required non-log content cannot fit in `ollama_num_ctx`, the
run surfaces a prompt-budget error rather than sending a one-token request.

Fighter prompts and Judge Phase 1 share a compact state-summary contract:
identity/class, loadout, environment, status, pain/exhaustion/heat, structured
`active_effects`, canonical `valid_target_parts`, shallow `target_parts`
anatomy metadata, and `damaged_parts` only for non-intact, severed, or partially
damaged parts. Effect summaries expose type, name, TTL, magnitude, target,
mechanics, and tags, but not freeform `on_apply` or `on_tick` prose.

`judge_phase2_failure_policy = fail_open` preserves long-run playtests by
recording an exhausted Judge Phase 2 parse/validation retry cycle as a marked
no-op turn with `metadata.fallback_used = true`, empty `delta`, `fight_end =
false`, and `winner = null`. `fail_closed` turns the same condition into a hard
fight failure. Batch CSVs include `p2_fallback_turns` and
`p2_fallback_used`, and summaries count fallback rows separately from error
rows.

Batch runs derive an isolated per-fight RNG stream from `[SIMULATION].seed`
and the run index, so concurrent scheduling or model latency does not change a
run's dice rolls or random effect-layer choices. Batch CSV output stays ordered
by run index and still flushes incrementally whenever the next ordered result is
available.

`fighter_creation_mode = generated` is opt-in. It asks the LLM for structured
fighter profiles before turn 1, validates them with the same custom anatomy
schema used for configured JSON profiles, and suppresses raw rejected generated
profile text from transcripts. Invalid generated profiles fall back to the
configured profile or humanoid preset with sanitized `profile_generation`
metadata.

`save_transcripts = true` writes one fight-scoped JSONL trace per fight under
`transcript_dir`. Each line has `schema_version`, ordered `event_index`,
timestamp, fight id, optional run index, turn, phase, event name, fighter id,
and event data. Active fighter/judge prompt-response exchanges are routed into
that trace as `llm_exchange` events instead of isolated fragment files; direct
non-fight callers of `log_exchange()` keep the legacy wrapper behavior. Trace
writes flush after each event so failures preserve partial history, including
sanitized `fight_error` or `fight_interrupted` events.

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
