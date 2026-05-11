# LLM Fighters Combat Engine

A turn-based duel between two LLM agents, the Fighters, adjudicated by a third LLM, the Judge/Narrator. Python owns randomness, state updates, validation, retries, logging, and CLI workflow. Ollama runs the models locally by default.

## Overview

LLM Fighters is a combat simulator where local LLM agents propose free-text actions in a detailed damage model inspired by layered anatomy systems. The Judge estimates each action's success probability, Python rolls the dice, and the Judge narrates the result as a structured state delta.

## Key Features

- Free-text fighter actions for creative combat maneuvers.
- Multi-layer body parts with pain, bleeding, burning, unconsciousness, death, and limb loss.
- Two-phase judge flow: probability assessment first, narration and state delta second.
- Native Ollama `/api/chat` structured-output calls by default, with `/v1/chat/completions` compatibility.
- JSON Schema validation with retry handling for brittle model output.
- Typer CLI commands for single fights and batch simulation.
- Optional Discord bot entrypoint.

## Requirements

- Python 3.14 or newer.
- `uv` for locked dependency management.
- Ollama running locally with a cheap model such as `llama3.2:3b`.

Install `uv` if it is not already available:

```bash
python -m pip install "uv>=0.11.13,<0.12"
```

## Installation

```bash
git clone <repository_url>
cd llm_fight
uv sync --locked
cp llmfight.ini.example llmfight.ini
```

On PowerShell, copy the example config with:

```powershell
Copy-Item llmfight.ini.example llmfight.ini
```

`pyproject.toml` is the source of truth for dependencies. `uv.lock` is committed. `requirements.txt` and `requirements-dev.txt` are compatibility exports generated from the lockfile.

For development with all extras and tools:

```bash
uv sync --locked --all-extras --dev
```

## Running The Game

Start Ollama and make sure your configured model is pulled:

```bash
ollama pull llama3.2:3b
```

Run a single fight:

```bash
uv run llmfight play --max-turns 2 --simple-output
```

Run a batch simulation:

```bash
uv run llmfight simulate --runs 1 --max-turns 2
```

Both commands accept `--config PATH`, `--fighter-a SECTION`, and `--fighter-b SECTION`.
Use `--max-turns N` for a short single-fight smoke test. `simulate` also accepts `--runs N`.

## Discord Bot

Install with the Discord extra:

```bash
uv sync --locked --extra discord
```

Configure `llmfight.ini`:

```ini
[DISCORD]
discord_token = your-bot-token
discord_channel = channel-name-or-id
```

Run the bot:

```bash
uv run llmfight-discord
```

The bot exposes `/fight start`, `/fight status`, and `/fight stop`.

## Configuration

Copy `llmfight.ini.example` to `llmfight.ini` and edit as needed.

```ini
[General]
ollama_default_model = llama3.2:3b
ollama_api_url = http://localhost:11434/api/chat
max_tokens_fighter = 512
max_tokens_judge = 4096
ollama_temperature = 0.4
best_of_fighter = 1
best_of_judge = 1
max_retries = 1
log_level = INFO
log_combat_turns = false
save_transcripts = false
transcript_dir = transcripts
fighter_sentence_limit = 1
fighter_word_limit = 30
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

[DEFAULTS]
environment = an open arena

[DEFAULT_FIGHTER]
class = Generic Fighter
loadout = their bare fists and wits

[A]
name = Sir Galant
class = Veteran Knight
loadout = longsword and tower shield

[B]
name = Shade
class = Cunning Assassin
loadout = poison dagger and smoke bombs
```

The default endpoint is native Ollama `/api/chat`. If you need the OpenAI-compatible endpoint, set:

```ini
ollama_api_url = http://localhost:11434/v1/chat/completions
```

You can also override the endpoint at runtime:

```bash
export API_URL="http://localhost:11434/api/chat"
```

On PowerShell:

```powershell
$env:API_URL = "http://localhost:11434/api/chat"
```

## Testing And Quality

```bash
uv run black --check .
uv run flake8
uv run pytest -q
```

Live Ollama tests are skipped by default. Opt in explicitly:

```bash
uv run pytest -q --run-live
```

CI uses Python 3.14 and runs:

```bash
uv sync --locked --all-extras --dev
uv run black --check .
uv run flake8
uv run pytest -q --cov=llm_fight
```

## Architecture

The installable package lives under `src/llm_fight/`.

```text
src/llm_fight/
|-- agents.py          # async Ollama client
|-- anatomy.py         # body part presets and tissue layers
|-- cli.py             # Typer commands
|-- config.py          # INI loader and migrations
|-- discord_bot.py     # optional Discord integration
|-- judge.py           # phase-1 and phase-2 orchestration
|-- rng.py             # central PRNG
|-- simulation.py      # single-fight and batch simulation loops
|-- state.py           # FighterState and delta/effect application
|-- transcripts.py     # prompt/response transcript logging
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

`run.py` is kept as a compatibility shim; prefer `llmfight`.

## Turn Flow

1. Fighter A and Fighter B propose actions concurrently.
2. Judge Phase 1 validates plausibility and returns success probabilities.
3. Python rolls against those probabilities.
4. Judge Phase 2 receives the attempts, full P1 result, successful rolls, combat log, valid body parts, and current fighter state.
5. Python validates and applies deltas, ticks effects, and resolves winner consistency from the resulting state.

## License

This project is licensed under the [MIT License](LICENSE).
