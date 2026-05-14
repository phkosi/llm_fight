# Advanced Operation

The README keeps the first-run path focused on `llmfight play`. This page collects lab, debugging, and compatibility details.

## Setup Contract

`pyproject.toml` and `uv.lock` are the dependency source of truth.

```bash
uv sync --locked --all-extras --dev
```

The repository intentionally does not track generated `requirements.txt` exports. Use `uv` for development, CI, and local runs.

## Simulation Lab

Use `simulate` for model evaluation, regression checks, and batch evidence:

```bash
uv run llmfight simulate --runs 3 --output-csv sim_results.csv
uv run llmfight simulate --runs 3 --max-turns 6 --continue-on-error
```

Batch CSV rows include winners, display names, turn counts, and Phase 2 fallback accounting. `winner=error` rows make the command exit nonzero unless `--continue-on-error` is set.

Use `collect-trials` when you need preserved fight evidence and blind A/B packs for parameter comparisons:

```bash
uv run llmfight collect-trials --smoke
uv run llmfight collect-trials --mode generated
```

Trial artifacts are written under `transcripts/trials/<timestamp>/`, which is ignored by Git. The private `manifest.json` contains unblinded model, parameter, path, retry, and reproduction metadata. Judge-facing packs under `blind_packs/` are generated from sanitized summaries and should be reviewed without opening the manifest.

Use `collect-profile-trials` when you need to measure generated-fighter profile reliability without running full fights:

```bash
uv run llmfight collect-profile-trials --smoke
uv run llmfight collect-profile-trials
```

Profile evaluation artifacts are written under `transcripts/profile_trials/<timestamp>/`, which is ignored by Git. The command samples `qwen3.6:35b` and `gemma4:26b` across the fixed creation nudges, then writes `manifest.json`, `analysis.json`, `analysis.md`, `profiles.csv`, and `settings.csv` with validation outcomes, fallback/error codes, model settings, custom target parts, altered body-plan metrics, and schema-backed anatomy/consequence metrics. Use this before prompt changes so generated-mode trial conclusions are not based on fallback profiles.

After blind reviews are recorded in `review_results.json`, use `analyze-trials` to build repeatable local reports without contacting Ollama:

```bash
uv run llmfight analyze-trials transcripts/trials/<timestamp>
uv run llmfight analyze-trials transcripts/trials/<configured> transcripts/trials/<generated>
```

The command writes `analysis.json`, `analysis.md`, `settings.csv`, and `pairs.csv`. A single input root defaults to `<run_root>/analysis/`; multiple roots default to `transcripts/trials/analysis/<timestamp>/`. The reports recompute review totals from structured results, flag note/result contradictions, summarize generated-profile fallback, and mark generated-mode parameter conclusions as blocked while profile fallback remains high.

## Advanced Config

Common first-run settings live in `llmfight.ini.example`. Less common controls can still be placed in `llmfight.ini`.

```ini
[General]
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
log_level = INFO
log_combat_turns = false
save_transcripts = false
transcript_dir = transcripts
transcript_detail = compact
fighter_sentence_limit = 1
fighter_word_limit = 30

[CONTEXT]
fighter_log_window = 10
judge_log_window = 9999

[SIMULATION]
runs = 1
seed = 42
concurrent_runs = 1
max_turns = 6
```

`profile` remains accepted as a legacy alias for `anatomy_profile`, but new examples and docs should use `anatomy_profile`.

## Endpoint Modes

Native Ollama `/api/chat` is the default and supports native controls such as `num_ctx`, `keep_alive`, `think=false`, and schema grammar hints.

```ini
ollama_api_url = http://localhost:11434/api/chat
```

OpenAI-compatible Ollama endpoints are also supported:

```ini
ollama_api_url = http://localhost:11434/v1/chat/completions
```

In `/v1` mode, native Ollama controls are not sent. Health checks use `/v1/models`; native mode uses `/api/tags`.

Proxy handling:

- `auto`: ignore environment proxies for loopback endpoints and honor them for remote endpoints.
- `disabled`: always ignore environment proxies.
- `enabled`: always honor environment proxies.

## Transcripts

Transcripts are opt-in:

```ini
save_transcripts = true
transcript_dir = transcripts
transcript_detail = compact
```

`compact` records fight lifecycle events, fighter readiness, token metadata, rolls, narration, no-op fallback markers, engine-repair metadata, and per-turn mechanical changes without raw prompt/response bodies.

`full` adds raw prompt/response exchanges and full turn snapshots for deep debugging. Do not commit transcript output; the directory is ignored by Git and can contain private prompts or fight state.

## Live And Perf Tests

Default tests do not contact Ollama.

```bash
uv run pytest -q
```

Live tests require an intentionally configured local endpoint:

```bash
uv run pytest -q --run-live
```

Heavy performance probes are separately gated:

```bash
uv run pytest -q --run-live --run-perf tests/test_memory_usage.py
```

## Quality Gates

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src/llm_fight
uv run pytest -q
```
