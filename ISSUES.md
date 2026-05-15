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

### ISSUE-005: GitHub CI fails without local llmfight.ini in mocked LLM tests

- Status: resolved
- Task: TODO.md - Restore hermetic CI defaults for mocked LLM tests
- Source: implementation review
- Evidence: GitHub `Run tests` fails with 34 failures. Common root is `[General] ollama_default_model is required for LLM runs. Set it in llmfight.ini or pass --config with a file that sets it.` Local checkouts can pass when they contain an ignored `llmfight.ini`, while CI does not because `*.ini` files are ignored. Remaining failures assert against Rich/Typer-rendered error-panel output.
- Impact: Main CI is red, and local test results are misleading when a developer's ignored config file supplies a model that CI does not have.
- Suggested fix: Provide a test-only default model before test modules import `llm_fight.config`, while preserving tests that intentionally verify missing-model behavior; normalize CLI error assertions that compare Rich/Typer output.
- Tests: Passed `uv run pytest -q tests/test_agents_endpoint.py tests/test_agents_transport.py tests/test_cli_play.py tests/test_cli_simulate.py tests/test_trials.py --cov=llm_fight`; passed `uv run ruff format --check .`; passed `uv run ruff check .`; passed `uv run mypy src/llm_fight`; passed `uv run pytest -q --cov=llm_fight`.

## P2

### ISSUE-001: Split Phase 2 authorization and tests

- Status: tasked
- Task: TODO.md - Split Phase 2 Authorization And Tests
- Source: implementation review
- Evidence: `src/llm_fight/phase2_authorization.py` is 1103 physical LOC; largest functions are `_authorize_fighter_delta` (177 LOC), `authorize_phase2_result` (113 LOC), `_repair_missing_successful_setup` (84 LOC), `_setup_effect_payload` (55 LOC), and `_authorized_scalar_value` (42 LOC). `tests/test_phase2_authorization.py` is 968 physical LOC, above the 800 LOC test-module threshold.
- Impact: Phase 2 authorization now carries source validation, target canonicalization, narration repair, deterministic damage repair, and setup-effect repair in one module, making future gameplay guardrail changes harder to review safely.
- Suggested fix: Split into focused modules such as `phase2_wounds.py`, `phase2_effect_repairs.py`, `phase2_narration.py`, and a small orchestration wrapper; split tests along the same boundaries with shared fighter/p1/p2 fixtures.
- Tests: Preserve the existing Phase 2 authorization, prompt-safety, combat-log, render, and simulation-turn tests; add focused tests for each extracted helper module before deleting the large-file issue.

### ISSUE-002: Judge Phase 2 effect payloads still cause fallback and authority oddities

- Status: resolved
- Task: completed - Harden Judge Phase 2 Effect Payloads
- Source: playtest
- Evidence: Configured finalist retest `uv run llmfight collect-trials --matrix finalist` wrote accepted artifacts to `transcripts/trials/20260514_183917` after smoke root `transcripts/trials/20260514_183741`. `uv run llmfight analyze-trials transcripts/trials/20260514_183917` reported 6 total P2 fallback turns and flagged `baseline_p2_fallback` / `candidate_p2_fallback` across multiple pairs. Runtime warnings included invalid zero-value `stat_tick` mechanics, object-shaped `ttl` fields, and `on_tick: null`; blind reviewers also noted suspicious wrong-side poison/debuff application and invalid target acceptance such as throat attacks.
- Impact: These failures do not block artifact collection, but they block parameter promotion by making otherwise strong samples land in `retest`, reduce trust in tactical causality, and make reviewer outcomes more disagreement-prone.
- Suggested fix: Resolved by tightening Judge Phase 2 effect prompt guidance and adding deterministic `effects_added` authorization cleanup for invalid/no-op mechanics, invalid TTLs, missing magnitude/value, null optional tick text, wrong-side self-debuffs, and effect target aliases.
- Tests: Added validation, prompt, Judge Phase 2 repair, and Phase 2 authorization coverage for zero-valued mechanics, object-shaped TTLs, null text fields, missing magnitude/value, wrong-side effect source, and non-canonical effect targets. Verified with `uv run pytest -q tests/test_phase2_authorization.py tests/test_phase2_authorization_prompt_safety.py tests/test_validation.py tests/engine/test_prompts.py tests/engine/test_judge.py tests/test_render.py tests/test_simulation.py tests/test_simulation_turns.py tests/test_simulation_trace.py tests/engine/test_combat_log.py -p no:cacheprovider` (190 passed), `uv run ruff format --check .`, `uv run ruff check .`, and `uv run mypy src/llm_fight`.

### ISSUE-003: Generated anatomy target resolution can drop successful consequences

- Status: resolved
- Task: completed - Fix Generated-Anatomy Target Consequences
- Source: playtest
- Evidence: Clean generated-mode retest `uv run llmfight collect-trials --mode generated` wrote accepted artifacts to `transcripts/trials/20260514_203736` after smoke root `transcripts/trials/20260514_203355`. `uv run llmfight analyze-trials transcripts/trials/20260514_203736` reported 18/18 completed cells, 3 P2 fallback turns, 16 reviewed blind pairs, and 36 generated profiles with 0 profile fallbacks, but reviewers repeatedly flagged generated-anatomy target conflicts, successful rolls with missing or partial damage consequences, setup/status-only outcomes after successful attacks, `valid` actions scored at `p=0.0`, target-ownership confusion, and custom target-name drift.
- Impact: Generated anatomy now produces useful originality and custom silhouettes, but target/consequence drift blocks clean generated-mode parameter conclusions and weakens readable causality when non-humanoid body parts enter the fight loop.
- Suggested fix: Resolved by adding unique-token custom part normalization, expanding damage intent for sword actions, repairing missing successful damage to custom targets such as wings, adding explicit no-effect warnings when successful damage has no resolvable target, and reporting `valid=true` / `p=0.0` as `zero_probability` without consuming RNG.
- Tests: Added generated/custom anatomy regression coverage for custom target suffix acceptance, successful roll consequence repair, explicit no-effect warning, and `valid=true` / `p=0.0` roll metadata. Verified with `uv run pytest -q tests/test_profile_generation.py tests/test_profiles.py tests/test_phase2_authorization.py tests/test_simulation.py tests/test_simulation_trace.py tests/test_simulation_probabilities.py tests/test_trials.py tests/test_trial_analysis.py tests/test_render.py tests/engine/test_fighter.py tests/engine/test_prompts.py -p no:cacheprovider` (176 passed), `uv run ruff format --check .`, `uv run ruff check .`, and `uv run mypy src/llm_fight`.

### ISSUE-004: Generated play can silently fall back to preset anatomy for one fighter

- Status: resolved
- Task: completed - Standardize LLM Invalid-Output Retries
- Source: playtest
- Evidence: Single live play session on 2026-05-15 used a temporary copy of `llmfight.ini` with `[General] fighter_creation_mode = generated`, `save_transcripts = true`, and `transcript_dir = transcripts/generated_playtest_tmp`, then ran `uv run llmfight play --config <temp-generated-config> --simple-output --max-turns 4`. The setup trace recorded Fighter A profile generation ending with `{"mode":"fallback","nudge":"original","error":"invalid_generated_profile"}`, while Fighter B finished with `{"mode":"generated","nudge":"warrior","error":null}`. The same setup snapshot showed A on the default humanoid part set (`head, heart, left_arm, left_eye, left_leg, right_arm, right_eye, right_leg, torso`) and B on a generated custom set including `armor_core`.
- Impact: A user can intentionally run generated mode and still get a mixed fallback/generated matchup without the session failing fast. That weakens trust in generated-mode playtests, makes one-off UX checks easy to misread, and can hide prompt-regression risk behind a superficially successful fight.
- Suggested fix: Resolved by adding a shared `invalid_output_retries` policy, visible retry events for generated profiles, fighter actions, Judge Phase 1, and Judge Phase 2, and explicit generated-profile fallback warnings in play output.
- Tests: Added config, validation, generated-profile, fighter-action, Judge Phase 1, Judge Phase 2, simulation, CLI play, creativity-gate, and simulation-turn coverage. Verified with `uv run pytest -q tests/test_config.py tests/test_validation.py tests/test_profile_generation.py tests/engine/test_fighter.py tests/engine/test_judge.py tests/test_simulation.py tests/test_cli_play.py tests/test_creativity_gate.py tests/test_simulation_turns.py -p no:cacheprovider` (228 passed), `uv run ruff format --check .`, `uv run ruff check .`, and `uv run mypy src/llm_fight`.

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
