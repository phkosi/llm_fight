# TODO

This file tracks active implementation work only. Completed historical work from the May 2026 hardening and cleanup pass is summarized in [docs/archive/completed-work-2026-05.md](docs/archive/completed-work-2026-05.md).

## Active Tasks

### Standardize LLM Invalid-Output Retries

Addresses: ISSUE-004

- [ ] Implementation intent: Add a shared invalid-output retry policy for generated profiles, fighter actions, Judge Phase 1, and Judge Phase 2. Define the policy as initial attempt plus up to 2 invalid-output retries before fallback/error, and surface each retry plus any final generated-profile preset fallback outside verbose-only logger output.
- [ ] Acceptance goals: Generated profile invalid outputs retry up to 2 times; every retry and final fallback is visible in `play` output/simple output and transcript events or metadata; non-verbose mode still shows these warnings; existing successful generated-profile and configured-fighter paths remain unchanged.
- [ ] Required tests: Add unit/CLI tests for profile retry warnings, final generated-profile fallback warnings, fighter empty-action retry warnings, Judge P1 invalid JSON/schema retries, and Judge P2 invalid JSON/schema retries.
- [ ] Verification: Run targeted retry tests, then `uv run pytest -q tests/test_profile_generation.py tests/test_simulation.py tests/test_cli_play.py tests/test_validation.py -p no:cacheprovider`.

### Harden Judge Phase 2 Effect Payloads

Addresses: ISSUE-002

- [ ] Implementation intent: Preserve the strict Phase 2 schema while improving prompt guidance, retry behavior, and deterministic authorization for invalid effect payloads and source/target oddities.
- [ ] Acceptance goals: Zero-value/no-op effect mechanics, object or non-scalar TTLs, null text fields, missing effect magnitude/value, wrong-side source ownership, and non-canonical effect targets do not silently pass into state or hide otherwise usable turns behind fail-open fallback.
- [ ] Required tests: Add validation/prompt/authorization tests for zero-valued mechanics, object-shaped TTLs, null text fields, missing magnitude/value, wrong-side effect source, and non-canonical target names.
- [ ] Verification: Run targeted Phase 2 authorization, validation, prompt, render, and simulation tests.

### Fix Generated-Anatomy Target Consequences

Addresses: ISSUE-003

- [ ] Implementation intent: After Phase 2 effect hardening, improve generated/custom anatomy target matching so successful generated-anatomy actions resolve to a canonical target consequence or an explicit no-effect reason.
- [ ] Acceptance goals: Custom body parts such as wings, tentacles, armor cores, and unusual limbs canonicalize consistently across prompts, Judge Phase 1, Judge Phase 2, state application, and summaries; successful rolls produce matching wounds/effects or clear no-effect warnings; `valid=true` with `p=0.0` is retried, normalized, or explicitly justified.
- [ ] Required tests: Add generated-anatomy regression tests for custom target acceptance, called-shot mapping, successful roll consequences, no-effect explanations, `valid`/`p=0.0` handling, and high-damage generated limb outcomes.
- [ ] Verification: Run generated-profile, Phase 2 authorization, simulation trace, trial-summary, and render tests.

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
