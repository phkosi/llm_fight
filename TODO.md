# TODO

This file tracks active implementation work only. Completed historical work from the May 2026 hardening and cleanup pass is summarized in [docs/archive/completed-work-2026-05.md](docs/archive/completed-work-2026-05.md).

## Active Tasks

### Restore hermetic CI defaults for mocked LLM tests

Addresses: ISSUE-005

- [x] Implementation intent: Make non-live unit tests independent of repo-local ignored `llmfight.ini` and normalize CLI error assertions where Rich/Typer styling wraps messages.
- [x] Acceptance goals: CI passes without a checked-in `llmfight.ini`; runtime commands still require a model; explicit missing-model tests still fail before `ping_ollama`.
- [x] Required tests: Agent endpoint/transport tests, CLI play/simulate tests, collect-trials default-finalization validation, and existing missing-model tests.
- [x] Verification: `uv run pytest -q tests/test_agents_endpoint.py tests/test_agents_transport.py tests/test_cli_play.py tests/test_cli_simulate.py tests/test_trials.py --cov=llm_fight`, then the full CI gate.

## Task Template

```markdown
### Short Task Title

Addresses: ISSUE-###

- [ ] Implementation intent:
- [ ] Acceptance goals:
- [ ] Required tests:
- [ ] Verification:
```
