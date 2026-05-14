# Issues

Use this file for active bugs, regressions, security risks, test gaps, prompt failures, gameplay-system failures, and code-size findings. Resolved historical issues from the May 2026 cleanup and hardening pass are summarized in [docs/archive/resolved-issues-2026-05.md](docs/archive/resolved-issues-2026-05.md).

Use [DESIGN_ISSUES.md](DESIGN_ISSUES.md) for non-bug design concerns such as pacing, fantasy, drama, balance, or boring-but-valid strategies.

## Tracking Fields

- `Status: open | tasked | resolved`
- `Task: none | TODO.md - <section/task>`
- `Source: playtest | codebase review | implementation review`
- `Evidence:`
- `Impact:`
- `Suggested fix:`
- `Tests:`

When a task is added to `TODO.md` for an issue, update that issue with `Task: TODO.md - <section/task>` and mark `Status: tasked`.

## P0

No active issues.

## P1

No active issues.

## P2

### ISSUE-001: Split Phase 2 authorization and tests

- Status: open
- Task: none
- Source: implementation review
- Evidence: `src/llm_fight/phase2_authorization.py` is 1103 physical LOC; largest functions are `_authorize_fighter_delta` (177 LOC), `authorize_phase2_result` (113 LOC), `_repair_missing_successful_setup` (84 LOC), `_setup_effect_payload` (55 LOC), and `_authorized_scalar_value` (42 LOC). `tests/test_phase2_authorization.py` is 968 physical LOC, above the 800 LOC test-module threshold.
- Impact: Phase 2 authorization now carries source validation, target canonicalization, narration repair, deterministic damage repair, and setup-effect repair in one module, making future gameplay guardrail changes harder to review safely.
- Suggested fix: Split into focused modules such as `phase2_wounds.py`, `phase2_effect_repairs.py`, `phase2_narration.py`, and a small orchestration wrapper; split tests along the same boundaries with shared fighter/p1/p2 fixtures.
- Tests: Preserve the existing Phase 2 authorization, prompt-safety, combat-log, render, and simulation-turn tests; add focused tests for each extracted helper module before deleting the large-file issue.

### ISSUE-002: Judge Phase 2 effect payloads still cause fallback and authority oddities

- Status: open
- Task: none
- Source: playtest
- Evidence: Configured finalist retest `uv run llmfight collect-trials --matrix finalist` wrote accepted artifacts to `transcripts/trials/20260514_183917` after smoke root `transcripts/trials/20260514_183741`. `uv run llmfight analyze-trials transcripts/trials/20260514_183917` reported 6 total P2 fallback turns and flagged `baseline_p2_fallback` / `candidate_p2_fallback` across multiple pairs. Runtime warnings included invalid zero-value `stat_tick` mechanics, object-shaped `ttl` fields, and `on_tick: null`; blind reviewers also noted suspicious wrong-side poison/debuff application and invalid target acceptance such as throat attacks.
- Impact: These failures do not block artifact collection, but they block parameter promotion by making otherwise strong samples land in `retest`, reduce trust in tactical causality, and make reviewer outcomes more disagreement-prone.
- Suggested fix: Tighten Judge Phase 2 prompt/schema guidance around positive mechanic values, scalar integer `ttl`, required effect magnitude/value fields, source ownership, and canonical target parts; consider deterministic repair or dropping for zero-value/no-op mechanics before fallback.
- Tests: Add focused Judge Phase 2 validation/repair tests for zero-valued mechanics, object-shaped TTLs, null text fields, wrong-side effect source, and non-canonical target names; preserve existing Phase 2 authorization and simulation-turn tests.

## P3

No active issues.

## Entry Template

```markdown
### ISSUE-###: Short title

- Status: open
- Task: none
- Source:
- Evidence:
- Impact:
- Suggested fix:
- Tests:
```
