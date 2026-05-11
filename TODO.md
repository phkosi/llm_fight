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
- [x] Investigate suspected Ollama model unload/reload or VRAM residency churn during live playtests. Evidence: user-observed Windows Task Manager screenshots during local Ollama playtesting on 2026-05-11 showed RTX 5090 dedicated GPU memory repeatedly dropping and refilling. Initial `keep_alive` alone was not enough. Follow-up evidence in `transcripts\gemma4_26b_playtest\ctx32768_probe_samples.log` showed the likely cause was alternating runner context sizes: a previously loaded `CONTEXT 4096` runner switched to a stable `CONTEXT 32768` runner once the app sent fixed `ollama_num_ctx = 32768` for every fighter and judge call. During the fixed-context run, `ollama ps` stayed on `gemma4:26b`, `100% GPU`, `CONTEXT 32768`, `UNTIL 9 minutes`, and GPU memory stayed near 22.5 GB through the batch and post-run sample.

Acceptance run after fixes:

- Command: `uv run llmfight simulate --config playtest_gemma4_26b.ini --output-csv transcripts\gemma4_26b_playtest\sim_results_after_fixes.csv --verbose`
- Output CSV: `transcripts\gemma4_26b_playtest\sim_results_after_fixes.csv`
- Result rows: 3
- Error rows: 0
- Winner summary: `draw: 3`
- Notes: post-fix transcript prompts say `inside an open arena`; `sim_after_fixes.out.log` has no non-positive wound warning, no validation failure, and no fallback/no-op warning.

## Gemma 4 26B Fixed-Context Playtest Follow-Ups

Evidence: ran `uv run llmfight simulate --config playtest_gemma4_26b.ini --output-csv transcripts\gemma4_26b_playtest\sim_results_ctx32768_probe.csv --verbose` with Ollama model `gemma4:26b`, `ollama_keep_alive = 10m`, and `ollama_num_ctx = 32768` on 2026-05-11. Results were 3 draws, 0 error rows, 4 turns each.

- [x] Reduce environment-feature hallucinations in fighter actions. In `sim_ctx32768_probe.out.log`, gemma used nonexistent `arena pillars`, `arena wall`, and `shadows of the arena's edge` despite the configured environment being `an open arena`; Judge Phase 1 sometimes caught these as physically inconsistent, but the fighter prompt should prevent invented cover/geometry earlier. Reproduction command: `uv run llmfight simulate --config playtest_gemma4_26b.ini --output-csv transcripts\gemma4_26b_playtest\sim_results_ctx32768_probe.csv --verbose`.

Acceptance run after fixed context and environment-prompt fixes:

- Command: `uv run llmfight simulate --config playtest_gemma4_26b.ini --output-csv transcripts\gemma4_26b_playtest\sim_results_final_ctx32768.csv --verbose`
- Output CSV: `transcripts\gemma4_26b_playtest\sim_results_final_ctx32768.csv`
- Result rows: 3
- Error rows: 0
- Winner summary: `draw: 3`
- Residency evidence: `transcripts\gemma4_26b_playtest\final_ctx32768_samples.log` stayed on `gemma4:26b`, `100% GPU`, `CONTEXT 32768`, and roughly 22.7-23.0 GB GPU memory throughout the run and post-run sample.
- Notes: `sim_final_ctx32768.out.log` had no validation failures, fallback/no-op warnings, non-positive wound warnings, or new nonexistent pillar/corridor arena geometry in fighter actions.

## Gemma 4 26B Rich Play Loop

Addresses: ISSUE-036, ISSUE-037

Evidence: ran `uv run llmfight play --config playtest_gemma4_26b.ini` with Ollama model `gemma4:26b` on 2026-05-12. Transcript: `transcripts\gemma4_26b_playtest\rich_play_20260512_000858.out.log`.

- [x] Suppress engine turn logs in non-verbose interactive `play` output. The rich table itself is clear, but the command first prints the plain logger copy of each turn because `playtest_gemma4_26b.ini` has `log_combat_turns = true`, then prints the rich table version again. This makes the full rich output doubled and noisy. Reproduction command: `uv run llmfight play --config playtest_gemma4_26b.ini`. Fixed by suppressing engine logs for non-verbose `play`; verified by `transcripts\gemma4_26b_playtest\rich_play_20260512_001054.out.log`, which starts directly with the rich `Turn 1` table and has no `INFO - Turn` preamble.
- [x] Prevent stale temporary effects from the recent combat log from overriding current state. In `transcripts\gemma4_26b_playtest\rich_play_20260512_001054.out.log` and the matching JSON transcript `transcripts\gemma4_26b_playtest\20260512_001117_581884.json`, turn 4 had `debuffs: []` for both fighters but the fighter and judge still treated the old smoke bomb as active because earlier narration repeated `thick grey haze`. Reproduction command: `uv run llmfight play --config playtest_gemma4_26b.ini`. Fixed by making current active effects authoritative in fighter and judge prompts and adding a final `current_state_reminder` to judge payloads; verified by `transcripts\gemma4_26b_playtest\rich_play_20260512_001652.out.log`, where turn 3 smoke references align with active `obscured` state and turn 4 no longer treats smoke as active.

Successful rich play streak after fixes:

- Command: `uv run llmfight play --config playtest_gemma4_26b.ini`
- Clean run 1: `transcripts\gemma4_26b_playtest\rich_play_20260512_001652.out.log`
- Clean run 2: `transcripts\gemma4_26b_playtest\rich_play_20260512_001755.out.log`
- Clean run 3: `transcripts\gemma4_26b_playtest\rich_play_20260512_001823.out.log`
- Notes: all three runs completed with `Winner: draw`, rich tables only, no `INFO - Turn` duplicate preamble, no validation/fallback/runtime error in stdout, and no new actionable rich-output issue found during review.

## Emergent Fighter Anatomy And Effects

Addresses: ISSUE-001, ISSUE-002

- [ ] Support creative fighter designs with dynamic anatomy and dynamically generated effects, including a match-start variant where LLMs create their own fighter profile before combat. Fighter prompts/config should be able to define non-humanoid bodies such as three arms, two heads, wings, tentacles, tails, or other custom parts, and the judge/simulation should treat those parts as valid combat targets with reasonable tissue, vital/severing, and damage behavior. The fighter-creation variant should use light random nudges such as warrior, mage, monster, trickster, hybrid, or fully original/creative so the system can produce varied characters instead of only mirrored humanoids. The same system should allow successful actions to create new debuffs/effects such as poison, blindness, corrosion, freezing, or entanglement even when they are not hard-coded ahead of time, with the judge proposing reasonable magnitude, TTL, affected stats/body parts, and tick behavior that Python validates and applies safely.

Acceptance goals:

- Creative fighter body plans are represented in state and shown to fighter/judge prompts as authoritative valid target parts.
- The LLM-created-fighter mode produces structured fighter profiles with class/theme, loadout, anatomy, and any starting traits/effects before turn 1.
- Judge-created effects use a structured contract, not only narration, so their current state survives across turns.
- Python validates dynamic parts/effects for sane names, positive values, bounded TTL/magnitude, deterministic tick behavior, and safe fallback/rejection when generated payloads are unusable.
- Existing humanoid fights continue to work unchanged.
- Add deterministic tests with mocked LLM/judge outputs for custom anatomy, generated fighter profiles, valid-target propagation, judge-created poison-style effects, effect expiry, invalid dynamic payload rejection, and transcript/state persistence.
- Add creativity-focused tests or gates that prove the system allows genuinely dynamic outcomes: at minimum, a non-humanoid body plan, a body part not present in the fixed humanoid preset, and an effect not listed in the current hard-coded effect constants must survive into state and prompts.
- Add an opt-in Codex-agent creativity gate for richer samples, where agents review generated fighter/effect artifacts and flag runs that collapse back to fixed humanoid anatomy, purely narrated effects, or repetitive low-creativity designs.

## Terminal Fight Startup And Progress Feedback

Addresses: ISSUE-011, ISSUE-023

- [ ] Show fighter designs before combat starts and provide responsive terminal feedback while LLM calls are running. When `llmfight play` starts, render a clear pre-fight view of both fighters before turn 1, including class/theme, loadout, environment, anatomy/body parts, and starting buffs/debuffs or traits. While fighters and judges are generating, show progress feedback such as a spinner, progress bar, or phase status so the terminal does not look frozen. When available from the LLM transport or transcript metadata, surface useful token stats such as prompt tokens, completion tokens, total tokens, or tokens generated.

Acceptance goals:

- Non-verbose `llmfight play` shows both fighter designs before the first turn result.
- Long-running fighter and judge phases display responsive status for the current step, such as fighter A action, fighter B action, Judge Phase 1, rolls, Judge Phase 2, applying deltas, or ticking effects.
- Token usage is displayed or summarized when available, and omitted cleanly when the provider does not return token data.
- Existing rich turn tables remain readable and are not duplicated by engine logs.
- Add tests or snapshot-style coverage for the pre-fight render, progress/status hooks, token-stat formatting, and missing-token fallback behavior.
