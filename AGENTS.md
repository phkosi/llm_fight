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
- Use **pytest**.  From the repository root run:
  ```bash
  pytest -q
  ```
- A lightweight **flake8** configuration checks for unused imports. Run:
  ```bash
  flake8
  ```
- Ensure all tests pass before committing.

## Project layout
- `src/` – runtime code.
  - `engine/` – helper modules (`constants.py`, `fighter.py`, `prompts.py`, etc.).
  - `config.py` – INI file loader.
  - `agents.py` – async wrapper for Ollama.
  - `state.py` – fighter dataclasses and state update logic.
  - `simulation.py` – batch self‑play harness.
  - `judge.py` – judge orchestration logic.
- `tests/` – pytest suite covering `src/` modules.
- Docs live in `README.md` and `docs/Design_doc.md`.

## Style notes
- Follow standard Python style (PEP8). `.flake8` allows lines up to **120** characters.
- Use type hints where present.
- Logging uses the `logger` from `src/engine/logger.py` – prefer this over `print`.
- Keep constants in `src/engine/constants.py` rather than inline strings.

## Development tips
- When adding functionality ensure accompanying tests are created or updated.
- If you introduce new configuration options update `src/config.py` defaults and document them in the README.
- Async functions that call Ollama are located in `src/agents.py`; they return lists of response strings for `guarded_call` to parse.
- The combat flow is orchestrated in `src/simulation.py`; refer to the design docs for high level behaviour.
- Review `docs/DEVELOPMENT_PLAN.md` before starting work. When you finish an item from "Outstanding Tasks", mark it completed (e.g. move it to "Completed Milestones") and commit the updated file.

