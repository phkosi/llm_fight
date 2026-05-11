# TODO

## Qwen 3.6 35B Playtest Follow-Ups

Evidence: ran `uv run llmfight simulate --config playtest_qwen36_35b.ini --runs 6 --output-csv transcripts/qwen36_35b_playtest/sim_results.csv --verbose` with Ollama model `qwen3.6:35b` on 2026-05-11. Results were 2 draws and 4 `error` rows.

Initial acceptance status: this did not satisfy the clean six-simulation gate. Only 2 of 6 runs reached the configured turn limit; 4 aborted during Judge Phase 2 JSON parsing.

Follow-up acceptance attempt: `playtest_qwen36_35b_acceptance.ini` used `max_retries = 4` and `ollama_temperature = 0.2`, but the first run still hit `Validation/JSON parsing failed after 5 attempts` on turn 6, so longer qwen runs remain blocked by structured-output reliability.

Short retry attempt: the same acceptance config later used `max_retries = 8`, `ollama_temperature = 0.2`, and `max_turns = 3` under `transcripts/qwen36_35b_acceptance_short`. Logs showed 3 completed 3-turn draws and part of a fourth run before the process was stopped, but no result CSV was written because batch results are only saved at the end.

Follow-up run after the first fixes: `playtest_qwen36_35b_acceptance.ini` still showed qwen returning empty strings on the first short fighter prompts, and the empty-action guard spent too many calls because it reused `max_retries = 8`. The run was stopped before any CSV rows were written.

Second follow-up run after the fighter retry cap: the first two turns completed, but Judge Phase 2 then returned repeated empty structured/plain-JSON responses and spent too many validation attempts because it still used `max_retries = 8`. The run was stopped before any CSV rows were written.

Root-cause check: direct native Ollama calls to `qwen3.6:35b` returned an empty `message.content` and populated `message.thinking` until the top-level native chat payload included `think = false`; with `think = false`, the same prompt returned normal action text.

- [x] Add a non-empty fighter action guard and retry path. In this playtest, qwen returned empty strings for fighter actions, producing repeated no-action stalemates instead of playable combat.
- [x] Harden Judge Phase 2 structured-output handling for qwen. Multiple P2 calls returned an empty/non-JSON response even with native Ollama `format`, causing `Validation/JSON parsing failed after 2 attempts` and aborting 4 of 6 simulations.
- [x] Reject combat deltas when P1 marks both attempts invalid and both `successful_rolls` are false. One run applied wounds and a `bleeding` effect after both fighters submitted empty attempts.
- [x] Tighten P2 schema validation so nested or misplaced combat result fields inside a fighter delta are rejected instead of accepted as extra properties.
- [x] Add an opt-in live compatibility smoke test for local models that asserts fighter attempts are non-empty and a small batch run completes without `winner=error`.
- [x] Write simulation results incrementally after each completed fight so interrupted live playtests keep partial CSV evidence instead of losing all batch results.
- [x] Cap empty fighter action retries independently from `max_retries` so qwen falls back quickly instead of spending many calls on repeated empty fighter responses.
- [x] Cap Judge Phase 2 parse retries independently from `max_retries` so repeated empty qwen P2 responses degrade into a no-op turn quickly instead of stalling live runs.
- [x] Disable Ollama thinking mode for native `/api/chat` calls by sending top-level `think: false`, so qwen returns usable `message.content` instead of spending the response budget on `message.thinking`.
- [x] Re-run the qwen3.6:35b playtest until the acceptance artifact contains 6 non-error simulation rows, then record the exact command, output CSV path, and winner summary here.

Acceptance run after fixes:

- Command: `uv run llmfight simulate --config playtest_qwen36_35b_acceptance.ini --output-csv transcripts\qwen36_35b_acceptance_short\sim_results_after_fixes_think_false.csv --verbose`
- Output CSV: `transcripts\qwen36_35b_acceptance_short\sim_results_after_fixes_think_false.csv`
- Result rows: 6
- Error rows: 0
- Winner summary: `draw: 5`, `A: 1`
- Notes: qwen produced real fighter actions after native Ollama payloads started sending top-level `think: false`; one malformed P2 turn degraded to the no-op fallback and the simulation continued.

Implemented checks on 2026-05-11:

- `uv run pytest -q tests\engine\test_fighter.py tests\engine\test_judge.py tests\test_validation.py tests\test_simulation.py tests\test_simulation_integration.py tests\test_simulation_failures.py` -> 104 passed.
- `uv run black --check .` -> passed.
- `uv run flake8` -> passed.
- `uv run pytest -q` -> 214 passed, 6 skipped, 1 warning.
- Final verification after acceptance fixes: `uv run pytest -q` -> 215 passed, 6 skipped, 1 warning; `uv run black --check .` -> passed; `uv run flake8` -> passed.

## Gemma 4 26B Playtest Follow-Ups

Evidence: ran `uv run llmfight simulate --config playtest_gemma4_26b.ini --output-csv transcripts\gemma4_26b_playtest\sim_results_initial.csv --verbose` with Ollama model `gemma4:26b` on 2026-05-11. Results were 3 draws, 0 error rows, 4 turns each.

Initial acceptance status: the model completed 3 runs without runtime or JSON/schema crashes, but the transcript exposed two actionable quality/reliability issues.

- [x] Fix the fighter prompt grammar for article-bearing environments. Gemma transcript files such as `transcripts\gemma4_26b_playtest\20260511_220734_906188.json` showed `currently fighting inside a an open arena`, which is confusing prompt UX and can leak awkward wording into model behavior.
- [x] Reject zero-value wounds at schema validation time. The initial gemma run logged `Ignoring non-positive damage amount 0 to neck for fighter A`, meaning Judge Phase 2 emitted a wound object that passed schema validation but could not affect combat state.
- [ ] Investigate suspected Ollama model unload/reload or VRAM residency churn during live playtests. Evidence: user-observed Windows Task Manager screenshot during local Ollama playtesting on 2026-05-11 showed RTX 5090 dedicated GPU memory repeatedly dropping and refilling. Reproduction command: run a live batch such as `uv run llmfight simulate --config playtest_gemma4_26b.ini --output-csv transcripts\gemma4_26b_playtest\sim_results_vram_probe.csv --verbose` while sampling `ollama ps` and GPU memory; check whether request cadence, `keep_alive`, context size, model switches, or Ollama scheduling causes repeated reloads.

Acceptance run after fixes:

- Command: `uv run llmfight simulate --config playtest_gemma4_26b.ini --output-csv transcripts\gemma4_26b_playtest\sim_results_after_fixes.csv --verbose`
- Output CSV: `transcripts\gemma4_26b_playtest\sim_results_after_fixes.csv`
- Result rows: 3
- Error rows: 0
- Winner summary: `draw: 3`
- Notes: post-fix transcript prompts say `inside an open arena`; `sim_after_fixes.out.log` has no non-positive wound warning, no validation failure, and no fallback/no-op warning.
