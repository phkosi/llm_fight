# LLM Fighters Combat Engine

[![CI](https://github.com/phkosi/llm_fight/actions/workflows/ci.yml/badge.svg)](https://github.com/phkosi/llm_fight/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.14+](https://img.shields.io/badge/python-3.14%2B-blue.svg)](pyproject.toml)

LLM Fighters is a local-first combat game where two LLM-controlled fighters duel under an LLM judge. Python owns the combat engine: state, anatomy, effects, dice rolls, validation, prompt budgeting, transcripts, and winner authority. Ollama runs the models locally by default.

The project is still experimental, but the first screen should feel like a game, not a benchmark harness: use `llmfight play` for readable fights, and use `llmfight simulate` only when you want batch evidence for tuning or regression checks.

## Quick Start

PowerShell:

```powershell
git clone https://github.com/phkosi/llm_fight.git
cd llm_fight
uv python install 3.14
uv sync --locked --all-extras --dev
Copy-Item llmfight.ini.example llmfight.ini
ollama pull qwen3.6:35b
uv run llmfight play
```

Bash:

```bash
git clone https://github.com/phkosi/llm_fight.git
cd llm_fight
uv python install 3.14
uv sync --locked --all-extras --dev
cp llmfight.ini.example llmfight.ini
ollama pull qwen3.6:35b
uv run llmfight play
```

Make sure Ollama is running before `play` or `simulate`. The CLI checks the configured endpoint before starting.

For a fast plain-text smoke check:

```bash
uv run llmfight play --max-turns 2 --simple-output
```

For low-spec machines, a smaller model can be useful for smoke tests, but the
recommended first play experience assumes a stronger local model than a tiny
3B checker.

## Playing

Run the default interactive fight:

```bash
uv run llmfight play
```

`play` renders both fighter designs before turn 1, shows live phase status while local LLM calls run, prints each completed turn, and ends with the winner. Rich output is the recommended player experience. `--simple-output` exists for terminals, logs, and CI-style checks that should avoid Rich tables.

Useful `play` options:

- `--config path/to/llmfight.ini`: use a different local config.
- `--fighter-a SECTION --fighter-b SECTION`: choose fighter sections from the config.
- `--max-turns N`: cap a fight for tests or quick experiments.
- `--simple-output`: use plain text instead of Rich tables.
- `--verbose`: show debug/progress logs.

## Fighter Config

Copy [llmfight.ini.example](llmfight.ini.example) to `llmfight.ini`; local `.ini` files are ignored by Git.

The default config defines a named knight and assassin. `name` is display-only: prompts, output, and transcripts show the label, but mechanics and JSON keys still use stable ids `A` and `B`.

```ini
[A]
name = Sir Galant
class = Veteran Knight
loadout = longsword and tower shield

[B]
name = Shade
class = Cunning Assassin
loadout = poison dagger and smoke bombs
```

Custom anatomy is supplied through `anatomy_profile`:

```ini
[A]
name = Talon
class = Winged Duelist
loadout = hook blades and wing spurs
anatomy_profile = profiles/winged_duelist.json
```

Profile files define canonical targetable parts:

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

Configured or generated profiles are authoritative. A prose class like `dragon` does not create targetable wings unless a profile defines them.

## Lab Commands

Batch simulation is for evaluation and tuning:

```bash
uv run llmfight simulate --runs 3 --output-csv sim_results.csv
```

Rows with `winner=error` make `simulate` exit nonzero after writing the CSV. Use `--continue-on-error` when automation should keep exit code 0 while preserving evidence.

Advanced config, transcripts, live/perf tests, endpoint modes, and batch workflow notes live in [docs/ADVANCED.md](docs/ADVANCED.md).

## Quality

Use the locked `uv` workflow:

```bash
uv sync --locked --all-extras --dev
uv run ruff format --check .
uv run ruff check .
uv run mypy src/llm_fight
uv run pytest -q
```

Live Ollama tests are opt-in:

```bash
uv run pytest -q --run-live
uv run pytest -q --run-live --run-perf tests/test_memory_usage.py
```

## Architecture

The core loop is:

1. Fighters generate free-text actions from current state, active effects, anatomy, loadout, and recent history.
2. Judge Phase 1 decides action validity and success probabilities.
3. Python rolls dice and records success/failure.
4. Judge Phase 2 narrates the turn and proposes state deltas.
5. Python authorizes deltas, applies damage/effects/status changes, and resolves the winner from actual state.

Do not remove these guardrails when slimming code: state-authoritative outcomes, Phase 2 source authorization, valid target-part checks, prompt budgeting, current-state reminders, and safe effect validation are all load-bearing. No-op Phase 2 fallback stays visible to players; successful engine repair is recorded in metadata/transcripts so the player sees the repaired exchange instead of a noisy warning.

## Known Limits

- Smaller local models can still produce weak narration or malformed structured output.
- Default fighters are intentionally simple; richer drama usually needs stronger models or custom profiles.
- `simulate` is a lab tool, not the intended first-run experience.
- Raw transcripts can contain prompts and fight state. They are opt-in, ignored by Git, and should not be committed.

## License

MIT. See [LICENSE](LICENSE).
