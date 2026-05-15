# TODO

This file tracks active implementation work only. Completed historical work from the May 2026 hardening and cleanup pass is summarized in [docs/archive/completed-work-2026-05.md](docs/archive/completed-work-2026-05.md).

## Active Tasks

### Split Phase 2 Authorization And Tests

Addresses: ISSUE-001

- [ ] Implementation intent: Perform a behavior-preserving extraction of the oversized Phase 2 authorization module and matching tests after Tasks 1-3 have locked the behavior with regression coverage.
- [ ] Acceptance goals: No gameplay semantics change in this task; split wound target authorization, effect authorization/repair, narration repair, warning helpers, and orchestration into smaller units; split `tests/test_phase2_authorization.py` along the same boundaries; warning codes and public behavior stay stable.
- [ ] Required tests: Preserve all current Phase 2 authorization, prompt-safety, combat-log, render, and simulation-turn tests; add focused tests around extracted helpers before moving logic.
- [ ] Verification: Run full quality gates: `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy src/llm_fight`, and `uv run pytest -q`.

## Task Template

```markdown
### Short Task Title

Addresses: ISSUE-###

- [ ] Implementation intent:
- [ ] Acceptance goals:
- [ ] Required tests:
- [ ] Verification:
```
