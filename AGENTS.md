# Guidelines for ChatGPT Codex

This repository contains a turn‑based combat simulator where LLM agents fight under the adjudication of a judge LLM.  Source code lives in `src/` and tests live in `tests/`.

## Running tests
### Setup
- Recommended Python: **3.11**.
- Create a virtual environment and activate it:
  ```bash
  python -m venv .venv
  source .venv/bin/activate  # Windows: .venv\Scripts\activate
  ```
- Install dev requirements (includes `requirements.txt`):
  ```bash
  pip install -r requirements-dev.txt
  ```
- Set `API_URL` to run live API tests; they are skipped if this variable is absent.
- Use **pytest**. From the repository root run:
  ```bash
  pytest -q
  ```
- Format the codebase with **black** before committing:
  ```bash
  black .
  ```
- Then run **flake8** which checks for unused imports:
  ```bash
  flake8
  ```
- Ensure all tests pass before committing.

## Project layout
- `src/` – runtime code.
  - `engine/` – helper modules (`constants.py`, `fighter.py`, `prompts.py`, etc.).
  - `agents.py` – async wrapper for Ollama.
  - `anatomy.py` – body part presets and tissue constants.
  - `cli.py` – Typer command line interface.
  - `config.py` – INI file loader.
  - `discord_bot.py` – optional Discord integration.
  - `judge.py` – judge orchestration logic.
  - `rng.py` – central random number generator.
  - `simulation.py` – batch self‑play harness.
  - `state.py` – fighter dataclasses and state update logic.
  - `validation.py` – JSON schema helpers and guarded LLM calls.
- `tests/` – pytest suite covering `src/` modules.
- Docs live in `README.md` and the `docs/` folder.
- `run.py` – command line entry point.

## Style notes
- Follow standard Python style (PEP8). `.flake8` allows lines up to **120** characters.
- `.flake8` also excludes the `.venv`, `__pycache__`, `build`, and `dist` directories.
- Use type hints where present.
- Logging uses the `logger` from `src/engine/logger.py` – prefer this over `print`.
- Keep constants in `src/engine/constants.py` rather than inline strings.

## Development tips
- When adding functionality ensure accompanying tests are created or updated.
- If you introduce new configuration options update `src/config.py` defaults and document them in the README.
- Async functions that call Ollama are located in `src/agents.py`; they return lists of response strings for `guarded_call` to parse.
- The combat flow is orchestrated in `src/simulation.py`; refer to the design docs for high level behaviour.
- Review `docs/DEVELOPMENT_PLAN.md` before starting work. When you finish an item from "Outstanding Tasks", mark it completed (e.g. move it to "Completed Milestones") and commit the updated file.

## Commit and PR guidelines

Follow these conventions to keep history easy to read and PRs self-explanatory.

### Commit messages
* Use the **imperative mood** in the subject line, e.g. `Add new move`.
* Keep the subject line under **72 characters** and clearly describe the change.
* Include a blank line between the subject and body.
* Provide a body when the change is non-trivial. Explain why the change is needed and wrap lines at 72 characters.
* Reference issues or docs with `Fix #123` or `See docs/xyz` when applicable.

### Pull requests
* Title should summarize the change in a sentence.
* The description should explain what changed and why.
* Mention key reasoning or context if not obvious.
* Mention any tests run (`black`, `flake8`, `pytest`).
* Note breaking changes or follow-up work if needed.

