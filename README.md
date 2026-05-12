# LLM Fighters Combat Engine

[![CI](https://github.com/phkosi/llm_fight/actions/workflows/ci.yml/badge.svg)](https://github.com/phkosi/llm_fight/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.14+](https://img.shields.io/badge/python-3.14%2B-blue.svg)](pyproject.toml)

LLM Fighters is an experimental local-first combat simulator where two LLM-controlled fighters duel under a third LLM judge. Python owns the mechanics: state, randomness, validation, retries, logging, and CLI workflow. Ollama runs the models locally by default.

## Project Status

This project is a playable proof of concept, not a stable game engine yet. It is built to explore free-text combat actions, structured LLM judging, and layered anatomy state. Expect model-dependent behavior, nondeterministic outcomes, and occasional structured-output failures with smaller local models.

Current defaults are tuned for a cheap local smoke test with `llama3.2:3b`. Stronger models will usually produce better narration and more coherent combat deltas.

## What It Does

- Lets two fighters propose free-text combat actions.
- Uses a two-phase Judge/Narrator LLM flow: probability assessment, then narration and state delta.
- Applies Python-side dice rolls, JSON Schema validation, retries, damage, effects, KO/death checks, and winner consistency.
- Models multi-layer body parts with pain, bleeding, burning, unconsciousness, death, and limb loss.
- Provides a Typer CLI for single fights and batch simulations.

## Requirements

- Python 3.14 or newer.
- [`uv`](https://docs.astral.sh/uv/) for the locked development workflow.
- [Ollama](https://ollama.com/) running locally.
- A pulled Ollama model. The default tested smoke model is `llama3.2:3b`.

Install `uv` if needed:

```bash
python -m pip install "uv>=0.11.13,<0.12"
```

If Python 3.14 is not already available, `uv` can install it:

```bash
uv python install 3.14
```

## Quick Start

PowerShell:

```powershell
git clone https://github.com/phkosi/llm_fight.git
cd llm_fight
uv python install 3.14
uv sync --locked --all-extras --dev
Copy-Item llmfight.ini.example llmfight.ini
ollama pull llama3.2:3b
uv run llmfight play --max-turns 2 --simple-output
```

Bash:

```bash
git clone https://github.com/phkosi/llm_fight.git
cd llm_fight
uv python install 3.14
uv sync --locked --all-extras --dev
cp llmfight.ini.example llmfight.ini
ollama pull llama3.2:3b
uv run llmfight play --max-turns 2 --simple-output
```

Make sure the Ollama server is running before `play` or `simulate`. The CLI checks the configured endpoint before starting a fight.

## Usage

Run a short single-fight smoke test:

```bash
uv run llmfight play --max-turns 2 --simple-output
```

`play` renders the fighter designs before turn 1 and shows live phase status
while fighter and judge calls are running. When the configured provider returns
real token usage metadata, `play` summarizes prompt/completion/total tokens at
the end; providers that omit usage metadata are handled silently.

Run a one-fight batch simulation:

```bash
uv run llmfight simulate --runs 1 --max-turns 2 --output-csv sim_results.csv
```

Batch simulation rows with `winner=error` make `llmfight simulate` exit nonzero after the CSV is written. Use `--continue-on-error` when an automation should keep exit code 0 while preserving an error-producing CSV for inspection.

Use an alternate config file:

```bash
uv run llmfight play --config path/to/llmfight.ini --max-turns 2
```

Select fighter sections from the config:

```bash
uv run llmfight play --fighter-a A --fighter-b B
```

Useful command options:

- `--max-turns N`: cap a fight quickly during smoke tests.
- `--runs N`: override batch simulation run count.
- `--continue-on-error`: keep batch simulation exit code 0 even if the CSV contains `winner=error` rows.
- `--simple-output`: print plain text instead of Rich tables.
- `--verbose`: show more progress/debug output.

## Configuration

Copy [llmfight.ini.example](llmfight.ini.example) to `llmfight.ini` and adjust it locally. Local `.ini` files are ignored by Git so secrets and machine-specific settings are not committed.

Minimal local settings:

```ini
[General]
ollama_default_model = llama3.2:3b
ollama_api_url = http://localhost:11434/api/chat
ollama_keep_alive = 10m
ollama_num_ctx = 32768
max_tokens_fighter = 512
max_tokens_judge = 4096
best_of_fighter = 1
best_of_judge = 1
max_retries = 1
fighter_creation_mode = configured

[SIMULATION]
runs = 1
max_turns = 2
```

Fighter sections can optionally point to a custom anatomy JSON profile. Omit
the key, leave it empty, or set it to `humanoid` to keep the default body plan.
Relative JSON paths are resolved from the active config file directory first,
then the current working directory.

```ini
[A]
class = Winged Duelist
loadout = hook blades
anatomy_profile = profiles/winged_duelist.json

[B]
profile = humanoid
```

Profile files use canonical part ids:

```json
{
  "class": "Winged Duelist",
  "loadout": "hook blades and wing spurs",
  "environment": "an open arena",
  "body_parts": [
    {
      "id": "second_head",
      "is_vital": true,
      "layers": [{"name": "bone", "max_hp": 10}]
    },
    {
      "id": "left_wing",
      "can_be_severed": true,
      "layers": [{"name": "feathers", "max_hp": 8}]
    }
  ]
}
```

Set `fighter_creation_mode = generated` to opt into match-start profile
generation. In generated mode, the model creates structured fighter profiles
before turn 1 using the same profile schema and anatomy validation. Generated
profile class, theme, loadout, environment, and anatomy are authoritative for
that fight; if generation fails validation, the game falls back to the
configured profile or default humanoid fighter and records sanitized
`profile_generation` metadata in state/logs. Raw rejected generated profile
text is not written to transcripts.

The default endpoint is native Ollama `/api/chat`. OpenAI-compatible Ollama endpoints are also supported:

For native Ollama, `ollama_keep_alive` is sent with each chat request so the model can stay resident between fighter and judge calls during local playtests. `ollama_num_ctx` is the fixed context window sent to every fighter and judge call in a run; keep it stable to avoid runner reloads caused by alternating context sizes. Increase `ollama_keep_alive` for long runs if you want the model resident after the CLI exits, and lower it if you want VRAM freed sooner.

```ini
ollama_api_url = http://localhost:11434/v1/chat/completions
```

You can override the endpoint at runtime.

Bash:

```bash
export API_URL="http://localhost:11434/api/chat"
```

PowerShell:

```powershell
$env:API_URL = "http://localhost:11434/api/chat"
```

## Testing And Quality

Run the standard local checks:

```bash
uv run black --check .
uv run flake8
uv run pytest -q
```

Run the CI-equivalent test command:

```bash
uv run pytest -q --cov=llm_fight
```

Live Ollama tests are skipped by default. To opt in, set `API_URL` and run only the live tests:

Bash:

```bash
export API_URL="http://localhost:11434/api/chat"
uv run pytest -q --run-live tests/test_live_api.py tests/test_live_judge.py
```

PowerShell:

```powershell
$env:API_URL = "http://localhost:11434/api/chat"
uv run pytest -q --run-live tests/test_live_api.py tests/test_live_judge.py
```

CI runs on Python 3.14 using the locked `uv` workflow. See [.github/workflows/ci.yml](.github/workflows/ci.yml).

## Architecture

The installable package lives under `src/llm_fight/`. The core flow is:

1. Fighter A and Fighter B propose actions concurrently.
2. Judge Phase 1 returns validity and success probabilities.
3. Python rolls against those probabilities.
4. Judge Phase 2 receives attempts, the full P1 result, successful rolls, combat log, valid body parts, and fighter state.
5. Judge Phase 2 deltas must mark each mechanical consequence with the source fighter whose valid action succeeded.
6. Python drops consequences from invalid, failed, missing, or unknown sources before applying deltas, then ticks eligible effects and resolves the winner from resulting state.
7. Judge-only `fight_end` or `winner` values are ignored unless Python state becomes terminal.

Effects created by a turn delta or wound side effect are fresh for that turn: they are shown in the resulting state and in the next turn's fighter/judge context before their first eligible tick. Pre-existing effects still tick once per turn.

For more detail, see [docs/Design_doc.md](docs/Design_doc.md).

## Known Limitations

- Combat balance and judge consistency are still evolving.
- Output quality depends heavily on the local model.
- Small models may occasionally fail strict JSON output even with retries.
- Formal releases are not established yet; `main` is the current development line.

## Troubleshooting

- `Cannot reach Ollama server`: start Ollama and confirm `http://localhost:11434/api/tags` responds.
- `model not found`: run `ollama pull llama3.2:3b` or set `ollama_default_model` to a model you have locally.
- `LLM output could not be parsed`: try a stronger model, increase `max_tokens_judge`, or increase `max_retries`.
- `uv sync` cannot find Python 3.14: run `uv python install 3.14`.

## Contributing And Support

Contributions are welcome for bug reports, documentation, tests, and small gameplay fixes. Please open an issue before large architecture or combat-system changes.

- Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.
- Use [GitHub Issues](https://github.com/phkosi/llm_fight/issues) for bugs, questions, and feature ideas. Include your OS, Python version, Ollama version, model name, command, and relevant logs with secrets removed.
- See [SECURITY.md](SECURITY.md) for private vulnerability reporting.

## License

This project is licensed under the [MIT License](LICENSE).
