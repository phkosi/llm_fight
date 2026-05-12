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

## Structured Custom Fighter Anatomy Profiles

Addresses: ISSUE-001

- [x] Add profile-backed custom fighter anatomy while preserving the current humanoid default. Config or test-authored fighter profiles should be able to define canonical non-humanoid body parts such as `left_wing`, `tail`, `second_head`, `tentacle_1`, or `third_arm`, and the simulation should create `FighterState` objects from those profiles instead of always hard-coding the humanoid preset.

Acceptance goals:

- Add a schema-backed profile builder for fighter class/theme, loadout, environment, and anatomy/body parts.
- Add an explicit config contract for custom anatomy: `anatomy_profile = <json-path-or-humanoid>` is the canonical fighter-section key; `profile = <json-path-or-humanoid>` is accepted as an alias. If both keys are present with different values, raise a config validation error. Missing, empty, or explicit `humanoid` keeps the current humanoid preset. For this slice, non-humanoid profile values are JSON file paths only; resolve relative paths against the active config file directory first, then the current working directory; absolute paths are used as-is. Bare ids other than `humanoid` are out of scope unless a built-in profile registry is added in this same task.
- Profile `class`, `theme`, `loadout`, and `environment` provide defaults; explicit fighter-section `class`, `loadout`, and `environment` values override profile values. Anatomy/body parts come from the profile whenever `anatomy_profile` or `profile` is set.
- Add a resolver such as `resolve_fighter_profile(section)` that returns either the existing `humanoid` preset or a validated profile dict, and make `_single_fight()` construct fighters only through this resolver.
- Validate profile body parts for sane canonical ids, display names, bounded part/layer counts, positive bounded layer HP, duplicate canonical names, at least one targetable part, and at least one vital part unless an explicit safe non-vital policy is added.
- Keep `FighterState.from_preset("humanoid")` and existing humanoid fights unchanged.
- Add a `FighterState.from_profile()` or equivalent resolver and make `_single_fight()` create fighters through a profile/preset resolver rather than hard-coding both fighters to humanoid.
- Show custom anatomy as authoritative valid target parts in fighter prompts, Judge Phase 1 summaries, Judge Phase 2 inputs, combat-log state snapshots, and transcripts/state JSON.
- Keep prompt anatomy summaries compact; do not dump full tissue-layer JSON into every fighter prompt unless needed.
- Update `llmfight.ini.example`, README, or docs for the new profile key and default humanoid behavior.

Required tests:

- Default config still creates humanoid fighters with existing parts.
- A custom profile creates non-humanoid parts such as `left_wing`, `tail`, and `second_head`.
- Relative profile paths resolve against the active config file directory before the current working directory.
- Setting both `profile` and `anatomy_profile` to different values raises a config validation error.
- Fighter-section class/loadout/environment override profile defaults while profile anatomy remains authoritative.
- Damage to a configured custom part applies; damage to an unknown part is rejected.
- A custom vital part can affect fighter status through existing invariant logic.
- A temp config with fighter-specific profile paths causes `_single_fight()` to build A/B from those profiles and pass their custom `valid_target_parts` into Judge Phase 1 and Phase 2.
- Fighter prompts include own/opponent valid custom target parts without relying on old narration.
- Transcript/combat-log state snapshots preserve custom parts.

Verification: `uv run pytest -q tests/test_profiles.py tests/test_config.py tests/test_state.py tests/test_simulation.py tests/test_simulation_integration.py tests/engine/test_fighter.py tests/engine/test_judge.py tests/engine/test_prompts.py tests/test_validation.py` -> 232 passed; `uv run black --check .`; `uv run flake8`; `uv run pytest -q` -> 312 passed, 6 skipped; `git diff --check`; 2 implementation reviewers passed.

## Declarative Dynamic Effect Mechanics

Addresses: ISSUE-002

- [x] Add a safe declarative mechanics contract for judge-created effects so effects such as poison, blindness, corrosion, freezing, entanglement, or mobility impairment can persist and affect state even when their names are not hard-coded constants.

Acceptance goals:

- Extend effect validation with bounded, non-executable `mechanics`, while preserving current `burning` and `bleeding` behavior.
- Support deterministic mechanic kinds such as `stat_tick` for pain/exhaustion/heat, `damage_tick` for a validated target part and damage type, `targeting_modifier` for blindness/vision impairment, and `action_modifier` with a conservative full `action_block` for stunned, entangled, or otherwise action-limited states. Prompt-facing tags may describe those mechanics, but must not be the only behavior for effects that claim to alter targeting or actions.
- Reject arbitrary formulas, Python code, probabilities, unbounded values, unknown target selectors, unsafe names/text, and mechanics targeting nonexistent body parts.
- Effects with `mechanics: []` may remain narrative-only; effects with invalid mechanics must not enter state or future prompts.
- Fresh effect timing remains authoritative: newly created effects are visible in the next fighter/judge context before their first eligible tick.
- Dynamic effect current state is serialized into fighter/judge context from `FighterState.to_json()`, not resurrected from old narration.

Required tests:

- A judge-created poison-style effect with stat ticks increases pain/exhaustion deterministically, observes fresh-turn timing, and expires.
- A dynamic damage tick affects a validated targeted body part and rejects unknown targets.
- A blinded or vision-impaired mechanic deterministically affects targeting/visibility and is visible in fighter/judge context.
- A stunned, action-limited, or entangled `action_block` mechanic deterministically invalidates the affected fighter's action and expires.
- Invalid mechanic payloads are rejected before they appear in buffs/debuffs or later prompts.
- Prompt/judge summaries include active dynamic effect name, TTL, magnitude, target, and mechanics/tags.
- Existing `burning`, `bleeding`, narrative-only unknown effects, and effect payload safety tests continue to pass.

Verification: `uv run pytest -q tests/test_validation.py tests/test_state.py tests/test_simulation.py tests/test_simulation_probabilities.py tests/engine/test_fighter.py tests/engine/test_judge.py tests/engine/test_prompts.py` -> 219 passed; `uv run black --check .`; `uv run flake8`; `uv run pytest -q` -> 326 passed, 6 skipped; `git diff --check`; 2 implementation reviewers passed after narrowing `action_modifier` to `action_block`.

## Match-Start LLM Fighter Profile Creation

Addresses: ISSUE-001

- [x] Add an optional match-start fighter creation mode where the LLM creates structured fighter profiles before turn 1, using bounded random nudges such as warrior, mage, monster, trickster, hybrid, or fully original/creative.

Clarified implementation contract:

- Add `[General] fighter_creation_mode = configured | generated`; default `configured`. In `configured` mode, `_single_fight()` must keep using the existing `FighterState.from_config()` path and must make no profile-generation LLM calls.
- In `generated` mode, generate one profile per resolved fighter section before turn 1 using `chat(..., schema=FighterProfileSchema)`, then validate with `guarded_call()` and `build_fighter_profile()`.
- Generated profile class/theme/loadout/environment/anatomy are authoritative in `generated` mode. Configured fighter values are prompt seed/fallback context only. If generation fails, fall back to the existing configured/preset `FighterState.from_config()` behavior.
- Starting effects are out of scope for this task; starting traits are represented only through generated class/theme/loadout/environment. Add starting effects later with an explicit `EffectSchema`-backed contract.
- Define a fixed `FIGHTER_CREATION_NUDGES = ("warrior", "mage", "monster", "trickster", "hybrid", "original")` list and select exactly one nudge per fighter through a helper that accepts `random.Random | None`; batch runs inherit deterministic nudges from `_derive_fight_seed()`.
- Profile-generation LLM calls must suppress raw transcript logging or write only sanitized generation metadata; rejected generated profile text must never be written to transcript files, prompts, state, or combat logs.
- Add a concrete serialized metadata contract: `FighterState.profile_generation: dict | None`, included by `FighterState.to_json()`, with shape `{"mode": "generated" | "fallback", "nudge": "<fixed-nudge>", "error": null | "invalid_generated_profile" | "generation_failed"}`. In fallback cases, also copy this sanitized metadata into `CombatLog.profile_generation` or an equivalent top-level combat-log metadata field. Do not store raw rejected LLM text in either place.

Acceptance goals:

- Add an opt-in config mode for generated fighter profiles; the default remains config/preset-backed humanoid behavior.
- Reuse the same profile schema and sanitizer as configured custom anatomy.
- Generate class/theme, loadout, environment-compatible flavor, and anatomy/body parts before the first combat turn.
- Use the fight-local RNG or simulation seed for deterministic nudge selection in tests and batch runs.
- On invalid LLM-created profiles, retry a small bounded number of times, then fall back to the configured/preset profile with a visible warning and transcript/state marker.
- Do not let generated profile text inject prompt instructions or bypass anatomy/effect validation.

Required tests:

- Mocked LLM profile creation produces a non-humanoid fighter before turn 1 and the resulting custom parts enter state and judge payloads.
- Random nudges are deterministic under a fixed seed/fight RNG.
- Invalid generated profiles fall back safely without crashing or leaking unsafe body/effect text into prompts.
- With `save_transcripts = true`, invalid generated profile text is not written to transcript files.
- Existing non-generated play/simulate paths do not make an extra profile-generation LLM call.

Verification: `uv run pytest -q tests/test_config.py tests/test_agents.py tests/test_profiles.py tests/test_simulation.py` -> 73 passed; `uv run black --check .`; `uv run flake8`; `uv run pytest -q` -> 333 passed, 6 skipped, 1 warning; `git diff --check`.

## Creativity Gate For Dynamic Anatomy And Effects

Addresses: ISSUE-001

- [x] Add creativity-focused tests and an opt-in Codex-agent/manual review gate proving the dynamic systems allow genuinely non-humanoid body plans and non-hard-coded effects instead of collapsing back to fixed humanoid anatomy or pure narration.

Acceptance goals:

- Add deterministic unit/integration tests that prove at least one non-humanoid body part absent from the humanoid preset survives into state, prompts, judge payloads, and transcript/state artifacts.
- Add deterministic unit/integration tests that prove at least one non-hard-coded effect with declarative mechanics survives into state and prompts, ticks deterministically, and expires.
- Add an opt-in review command or documented gate where Codex agents can review generated fighter/effect samples for creative variety and flag repetitive low-creativity outputs.
- Keep the agent creativity gate outside default pytest and local smoke checks; default tests should remain deterministic and offline.

Required tests:

- Deterministic offline test proving a non-humanoid body part absent from `PRESETS["humanoid"]` survives into `FighterState.to_json()`, fighter prompts, Judge Phase 1, Judge Phase 2, and combat-log state snapshots.
- Deterministic offline test proving a non-hard-coded declarative effect enters state, appears in prompts with mechanics/tags, ticks once after the fresh-turn delay, and expires.
- Documentation or command test proving the Codex/manual creativity gate is opt-in and excluded from default `pytest`.

Verification: `uv run pytest -q tests/test_creativity_gate.py tests/test_state.py tests/test_simulation.py tests/engine/test_fighter.py tests/engine/test_judge.py` -> 150 passed; `uv run black --check .`; `uv run flake8`; `uv run pytest -q` -> 336 passed, 6 skipped, 1 warning; `git diff --check`.

## Terminal Fight Startup And Progress Feedback

Addresses: ISSUE-011, ISSUE-023

- [x] Show fighter designs before combat starts and provide responsive terminal feedback while LLM calls are running. When `llmfight play` starts, render a clear pre-fight view of both fighters before turn 1, including class/theme, loadout, environment, anatomy/body parts, and starting buffs/debuffs or traits. While fighters and judges are generating, show progress feedback such as a spinner, progress bar, or phase status so the terminal does not look frozen. When available from the LLM transport or transcript metadata, surface useful token stats such as prompt tokens, completion tokens, total tokens, or tokens generated.

Clarified implementation contract:

- This task applies to `llmfight play` only. Do not change `run_batch()` behavior, batch CSV output, or `simulate` completion-progress semantics.
- Add an internal optional play-event hook to `_single_fight()`, such as `on_event(event: FightEvent)`, without changing the default return shape.
- Emit play events for profile generation for A/B when `fighter_creation_mode = generated`, fighters ready/pre-fight state, fighter A/B action generation, Judge Phase 1, rolls, Judge Phase 2, applying deltas, ticking effects, turn complete, and fight complete.
- Render the pre-fight design only after configured/generated fighters are built and before turn 1 action generation. In generated mode, show status while profile generation is running.
- Add `render.make_fighter_design_view()` for rich/plain output showing fighter id, class/theme, loadout, environment, body parts, active buffs/debuffs, and profile-generation metadata when present.
- Define token metadata explicitly. Add a typed call result or optional metadata path for `chat()` that preserves existing string-list behavior for current callers unless intentionally migrated. Extract native Ollama fields such as `prompt_eval_count`, `eval_count`, `total_duration`, `load_duration`, `prompt_eval_duration`, `eval_duration`, and `done_reason` when present, and OpenAI-compatible `usage.prompt_tokens`, `usage.completion_tokens`, and `usage.total_tokens` when present.
- Attach token metadata to play events and/or `CombatLog` turns so `llmfight play` can summarize it. Missing metadata must render nothing or a clear `tokens unavailable` fallback without crashing; do not display guessed, zero, or placeholder token counts as real usage.
- Rich mode should use a spinner/status surface. `--simple-output` should avoid Rich-only controls and may use plain phase lines, but must not look frozen before the first turn.

Acceptance goals:

- Non-verbose `llmfight play` shows both fighter designs before the first turn result.
- Long-running fighter and judge phases display responsive status for the current step, such as fighter A action, fighter B action, Judge Phase 1, rolls, Judge Phase 2, applying deltas, or ticking effects.
- Token usage is displayed or summarized when available, and omitted cleanly when the provider does not return token data.
- Existing rich turn tables remain readable and are not duplicated by engine logs.
- Add tests or snapshot-style coverage for the pre-fight render, progress/status hooks, token-stat formatting, and missing-token fallback behavior.
- Add tests for pre-fight render before the first turn table, generated-profile status before generated fighter design display, phase event ordering with mocked async calls, native Ollama and OpenAI-compatible token metadata extraction, missing-token fallback, and no `simulate`/`run_batch` API or output regression.

Verification: `uv run pytest -q tests/test_agents.py tests/test_render.py tests/test_simulation.py tests/test_cli.py tests/engine/test_fighter.py tests/engine/test_judge.py tests/test_validation.py` -> 218 passed, 1 warning; `uv run black --check .`; `uv run flake8`; `uv run pytest -q` -> 344 passed, 6 skipped, 1 warning; `git diff --check`.

## Effect Payload Safety Gate

Addresses: ISSUE-005

- [x] Harden judge-created effect payload validation so malformed `effects_added` entries are rejected before they can become active `Effect` objects or appear in later prompts. Add a narrow `EffectSchema` used by `DeltaSchema`, plus a defensive runtime sanitizer in `FighterState.apply_delta()` for callers that bypass schema validation. This task is only a safety/crash fix: preserve the current simple known-effect behavior for `burning` and `bleeding`, allow unknown-but-safe narrative effect names to remain inert, and do not implement the broader dynamic effects registry/mechanics system yet.

Acceptance goals:

- `effects_added` items are strict objects with bounded fields: safe short `name`, one required positive bounded `value` or `magnitude`, required integer `ttl` of `-1` or `1..MAX_EFFECT_TTL`, optional `type` limited to `buffs` or `debuffs`, optional short plain-text `on_apply`/`on_tick`, and optional `metadata`.
- Missing `ttl` or missing magnitude is rejected rather than defaulted to permanent `ttl=-1` or `magnitude=1.0`.
- `metadata` is omitted or an object with `additionalProperties: false`; for this task, allow only `targeted_part` as a short safe string matching a current body part. Reject oversized, non-string, unknown-key, or instruction-like metadata values.
- Missing or invalid effect payloads are skipped with a warning, not coerced into permanent effects.
- `Effect.tick()` defensively expires/removes impossible TTLs instead of raising, so old bad state or direct test construction cannot crash the fight loop.
- Rejected effect names and text never appear in subsequent fighter or judge prompt payloads.
- Existing valid `burning`/`bleeding` effects, magnitude alias support, permanent effects with `ttl=-1`, and humanoid fights continue to work.

Required tests:

- Add `EffectSchema` coverage for valid canonical effects and invalid missing name, missing TTL, `ttl=null`, non-integer TTL, `ttl=0`, `ttl<-1`, TTL above max, missing magnitude, negative/zero/oversized magnitude, unknown `type`, oversized/instruction-like names, non-object metadata, unknown metadata keys, and unknown top-level properties.
- Add state tests proving `apply_delta()` skips invalid effects without appending buffs/debuffs; valid `value` and `magnitude` effects still append correctly; `apply_effects()` no longer crashes when an invalid TTL somehow exists.
- Add tests rejecting instruction-like, oversized, or control-character `on_apply`, `on_tick`, and `metadata` values.
- Add prompt/integration coverage where a malicious or invalid effect from mocked Judge Phase 2 is rejected, the next turn continues, and the rejected name/text/metadata is absent from fighter/judge prompt payloads.
- Keep or add property-style coverage that fuzzes mixed effect payloads through `apply_delta()` and asserts no crash, no active `ttl=0` effects, and no duplicate permanent effects.

## P2 Authorization And Terminal Outcome Gate

Addresses: ISSUE-003, ISSUE-004

- [x] Add a deterministic post-Phase-2 authorization gate before `FighterState.apply_delta()` and before accepting `fight_end` or `winner`. Python state remains authoritative: judge-declared endings are ignored unless authorized deltas and effect ticks produce terminal fighter state.

Acceptance goals:

- Extend `DeltaSchema`/`JudgeP2Schema` so every mechanically meaningful Phase 2 consequence carries `source: "A" | "B"`. Consequences missing `source`, with an unknown source, or sourced to a fighter without both a valid Phase 1 attempt and a successful roll are dropped before `apply_delta()`.
- Attribution is required for all state-changing entries: scalar stat increases, wounds, effects added, effects removed, and status changes. If scalar fields remain scalar in legacy input, wrap them in source-bearing consequence objects before implementation; do not infer source from target fighter id.
- A valid successful source may produce authorized consequences against either fighter, including self-costs or opponent damage. Authorization is based on consequence `source`, not on the target fighter whose delta contains it.
- If no fighter has both a valid Phase 1 attempt and a successful roll, all Phase 2 deltas, `fight_end`, and `winner` are stripped before state mutation.
- Mixed-success turns require source attribution for Phase 2 consequences; consequences from invalid or failed actions are dropped.
- If both fighters remain `fighting` after authorized deltas and effect ticks, judge-only `fight_end=true` and `winner` are logged and ignored. This includes `fight_end=true, winner=null`, which should continue rather than become a judge-only draw.
- Existing state-terminal outcomes still override contradictory judge winners.
- Update `JUDGE_P2_SYSTEM_PROMPT`, `JudgeP2Schema`, validation tests, and README/docs Phase 2 contract text to document source attribution and Python-authoritative terminal outcomes.

Required tests:

- Validation/schema tests cover source-bearing consequences for scalar stat changes, wounds, effects added, effects removed, and status changes, plus rejection or sanitization of missing/unknown sources.
- Valid attempts with both rolls false plus Phase 2 wounds/status/winner cause no mutation and no fight end.
- One successful fighter plus one failed or invalid fighter drops failed-source consequences while applying successful-source consequences.
- Empty delta plus `fight_end=true, winner=A` and `fight_end=true, winner=null` both continue when both fighters remain `fighting`.
- Existing inconsistent-judge-winner coverage still proves post-delta state outcome wins.

## Effect Creation Turn Boundary

Addresses: ISSUE-006

- [x] Define effect timing so effects created during turn N survive into the next fighter and judge prompt before their first tick. Newly created burn, bleed, stun, or similar effects should not apply mechanics or expire in the same post-delta tick that created them.

Acceptance goals:

- Add an internal freshness/eligibility mechanism so effects created by `apply_delta()` or wound side effects are skipped by the current turn's effect tick exactly once.
- Pre-existing effects must remain eligible and tick once during the turn. Directly constructed/appended effects in tests default to pre-existing/eligible unless explicitly marked fresh.
- Any internal freshness marker must not leak into fighter/judge prompt payloads unless intentionally documented.
- Do not satisfy this task by moving all effect ticks before prompt construction. The first eligible tick for a newly created effect must occur only after it has appeared in the next fighter prompt and next judge input.
- Effects created by Phase 2 deltas or wound side effects are present in `state_after` and in turn N+1 prompt payloads.
- A `ttl=1` effect created on turn N is observable on turn N+1, then expires after its first eligible tick.
- Burning or bleeding created by same-turn damage does not add extra same-turn damage or stat loss beyond the authorized Phase 2 delta.
- Pre-existing effects continue ticking once per turn.
- If a wound finds an existing targeted burning/bleeding effect and does not create a new one, that existing effect remains pre-existing and eligible to tick this turn. Only effects actually created during the current delta/wound application are skipped.
- Update README and `docs/Design_doc.md` to describe the timing contract: deltas create effects, fresh effects are visible in the next prompt, and only eligible/pre-existing effects tick.

Required tests:

- Phase 2 adds `stunned` with `ttl=1`; turn N `state_after` contains it with TTL unchanged, and next-turn fighter plus judge Phase 1/Phase 2 inputs include it before it ticks.
- The effect expires only after its first eligible tick.
- Fire wound creates burning; immediate same-turn effect tick does not add burn damage, but the next eligible tick does.
- Pre-existing burn/bleed still ticks once in the same turn, including when same-turn damage hits a part that already has the matching targeted effect.
- Existing direct `apply_effects()` tests distinguish pre-existing effects from newly created effects.

## Status Invariants And Monotonic Status Changes

Addresses: ISSUE-007, ISSUE-019

- [x] Make fighter status invariants run after every state-mutating path and make judge-driven status changes monotonic by default. `fighting -> unconscious -> dead` is allowed; `dead` or `unconscious` cannot be revived to `fighting` through an ordinary Phase 2 delta.

Acceptance goals:

- Damaging severed or destroyed parts still rechecks pain/death invariants before returning.
- `status_change` can worsen status but cannot downgrade `dead` or `unconscious` without a future explicit recovery mechanic.
- Direct status changes and invariant-derived status changes use the same severity ordering.
- Invalid or downgrade status attempts are logged and leave state unchanged.

Required tests:

- Sever a limb, then hit it again enough to cross `MAX_PAIN_BEFORE_DEATH`; fighter becomes `dead`.
- Destroy a non-severable part, then hit it again enough to cross the death threshold; fighter becomes `dead`.
- `dead -> fighting`, `dead -> unconscious`, and `unconscious -> fighting` deltas are rejected.
- `fighting -> unconscious` and `unconscious -> dead` still work.

## Per-Fight RNG For Concurrent Batch Runs

Addresses: ISSUE-009

- [x] Replace batch use of module-global RNG with an isolated per-fight RNG derived from `(batch_seed, run_index)`, and pass that RNG through roll resolution and effect ticking.

Acceptance goals:

- Preserve `run_batch()`'s public API: keep `run_batch(output_csv="sim_results.csv", fighter_a_section=None, fighter_b_section=None, progress=None) -> Path` unchanged.
- Add fight-local RNG narrowly, not via a runtime-context refactor: `_single_fight(..., return_log: bool = False, fight_rng: random.Random | None = None)`. Use `fight_rng.random()` for success rolls, falling back to existing module-global `rand()` only when `fight_rng is None`.
- `_single_fight()` accepts an optional fight-local RNG and uses it for success rolls.
- Add `FighterState.apply_effects(rng: random.Random | None = None)` and use `rng.choice(...)` for burn/effect layer selection when provided, falling back to existing `llm_fight.rng.choice(...)` for compatibility.
- `run_batch()` derives stable per-run seeds before scheduling concurrent tasks using a deterministic helper such as `_derive_fight_seed(batch_seed: int, run_index: int) -> int`; do not use Python's process-randomized `hash()`.
- `run_batch()` creates indexed tasks and passes each task its own RNG.
- CSV rows are written in stable run-index order while still flushing incrementally when the next ordered result is available. Later completed rows may wait in memory until preceding runs finish.
- Progress callback semantics remain completion-based: call `progress(completed_count, runs)` whenever a fight task completes, not only when an ordered row flushes.
- Existing public `rng.py` helpers remain for compatibility unless all callers are migrated.
- Update README or `docs/Design_doc.md` to state that batch seeds produce stable per-run RNG streams under concurrency, and CSV output remains ordered by run index while still flushing incrementally.

Required tests:

- Run the same concurrent batch twice with the same seed and varied fake async delays; ordered CSV rows are identical.
- Changing the base seed changes deterministic roll outcomes.
- Per-fight RNG prevents one slow fight from changing another fight's roll sequence.
- Existing zero-run, error-row, progress-callback, and incremental-flush tests are preserved or intentionally updated, including explicit completion-based progress callback ordering.

## Prompt Budget Guardrails And Context Trimming

Addresses: ISSUE-008

- [x] Prevent oversized fighter and judge prompts from degrading into 1-token generations by adding phase-aware prompt budgets, deterministic combat-log trimming, and clear pre-transport failures when the required prompt cannot fit.

Acceptance goals:

- Over-budget prompts never call `chat()` with `max_tokens=1`.
- Fighter, Judge Phase 1, Judge Phase 2, and Phase 2 repair calls each keep a documented minimum completion reserve.
- Long `recent_combat_log` payloads are reduced deterministically while preserving current fighter state, attempts, rolls, valid target parts, and current effect reminders.
- Prompt-budget failures surface as clear CLI errors, not retry storms or silent no-op turns.
- Existing normal-size prompts keep their current token caps.
- Judge Phase 2 repair recomputes its own prompt budget after adding repair-only fields instead of reusing the original Phase 2 budget.
- Fighter profile generation uses the same strict budget policy, even though it has no combat log to trim.
- All production prompt paths stop using the old clamp-to-one behavior or document why a non-production compatibility helper remains.
- Prompt-budget errors never include raw prompt/message content.
- Judge Phase 1 intentionally uses `fighter_log_window` because it evaluates current attempts with the same short context available to fighters; Judge Phase 2 continues to use `judge_log_window` and trims deterministically when needed.

Required tests:

- `compute_completion_tokens` or its replacement raises or returns a typed over-budget result instead of clamping to `1`.
- Fighter, Judge Phase 1, Judge Phase 2, and repair paths do not call `chat()` when required non-log content alone exceeds budget.
- Long combat logs are trimmed and still leave at least the phase minimum completion budget.
- CLI converts the typed budget error into an actionable message mentioning context, prompt size, and log-window settings.
- Profile generation budget errors are sanitized/fallback-safe and do not use a one-token completion.

Verification: `uv run pytest -q tests/engine/test_judge.py tests/test_simulation_failures.py tests/test_cli.py` -> 47 passed, 1 warning; `uv run black --check .`; `uv run flake8`; `uv run pytest -q` -> 357 passed, 6 skipped, 1 warning; `git diff --check`.

## Batch Config Validation And Failure Exit Semantics

Addresses: ISSUE-010, ISSUE-025

- [x] Fail fast on invalid batch settings and make simulation error rows affect CLI exit status unless the user explicitly opts into continuing with an error-producing CSV.

Acceptance goals:

- `concurrent_runs=0` and negative concurrency fail immediately with a clear config or CLI error.
- Negative `runs` fails at config/runtime boundaries as well as the existing CLI override guard.
- `llmfight simulate` validates batch settings after CLI overrides and before contacting Ollama, and `run_batch()` validates again before opening the CSV, creating the semaphore, or starting `_single_fight` tasks.
- Batch CSV writing remains incremental for completed runs.
- After the CSV is written, `llmfight simulate` exits nonzero if `error_rows > 0` unless `--continue-on-error` is set. This applies to both all-error and mixed success/error batches. `runs=0` has `error_rows=0` and exits 0.
- Add a shared batch-summary path: either have `run_batch()` return a `BatchResult(path, total_runs, completed_rows, error_rows)`, or keep `run_batch()` returning `Path` and add a CSV summary helper used by both verbose output and exit-code handling. Define `completed_rows` as rows where `winner != "error"`.
- Add an explicit opt-in such as `--continue-on-error` for CI/playtest cases that want a CSV even with error rows.
- Verbose summary output includes total runs, completed rows, and error rows.
- Update README/docs to document `--continue-on-error` and the default nonzero exit when batch error rows are produced.

Required tests:

- `run_batch()` with `concurrent_runs=0` and `-1` raises quickly and does not hang or start `_single_fight`.
- `runs=0` still writes a header-only CSV and exits successfully.
- CLI simulate exits nonzero when every mocked fight fails.
- CLI simulate exits nonzero for mixed success/error rows unless `--continue-on-error` is set.
- `--continue-on-error` exits 0 but prints an error-row warning.

## Transport Privacy And Endpoint Mode Safety

Addresses: ISSUE-012, ISSUE-031

- [ ] Redact transport logs, make proxy use explicit for local endpoints, and split native Ollama behavior from OpenAI-compatible endpoint behavior.

Acceptance goals:

- Retry/error logs do not contain raw prompt payloads or sentinel secrets.
- Localhost, `127.0.0.1`, and `::1` endpoints do not honor `HTTP_PROXY`/`HTTPS_PROXY` unless explicitly opted in.
- Remote endpoint proxy behavior is documented and configurable.
- `/v1/chat/completions` endpoints are not rejected just because `/api/tags` is unavailable.
- Native-only options are sent only to native Ollama and produce one clear warning/doc note in OpenAI-compatible mode.
- README, docs, and `llmfight.ini.example` document endpoint modes and proxy opt-in.

Required tests:

- Force 5xx, client error, timeout, and unexpected exception with sentinel prompt text; captured logs omit the sentinel and raw `messages`.
- `ClientSession` receives `trust_env=False` for loopback by default.
- Explicit proxy opt-in flips `trust_env=True`.
- Mock `/v1/chat/completions` plus missing `/api/tags`; `ping_ollama()` succeeds through the compatible health path.
- `/v1` payloads omit native `options.num_ctx`/`keep_alive` and emit the expected warning.

## P2 Target Validation Gate

Addresses: ISSUE-013

- [ ] Post-validate Judge Phase 2 wound targets against each fighter's canonical body parts before applying deltas.

Acceptance goals:

- Unknown Phase 2 wound targets never reach `apply_damage_to_part()`.
- Known aliases are accepted and rewritten to canonical part names.
- A Phase 2 result with only invalid target damage cannot end the fight or award a winner.
- Mixed valid/invalid wound lists apply only the valid canonicalized wounds.
- Sanitization warnings can be surfaced later by render/transcript work without replaying unsafe raw text into prompts.
- Existing humanoid valid-target behavior remains unchanged.

Required tests:

- Phase 2 returns `targeted_part="wing"` for a humanoid plus `fight_end=true`; no damage, no terminal winner, and a warning marker result.
- Phase 2 returns `targeted_part="neck"`; it canonicalizes to `head` and applies damage.
- Mixed valid and invalid wounds apply only the valid wound.
- Invalid target text does not appear in subsequent fighter/judge prompt payloads except as a redacted warning code if metadata is carried forward.

## P2 Fallback Visibility And Fail-Open Policy

Addresses: ISSUE-024

- [ ] Make Judge Phase 2 no-op fallback explicit in state, output, transcripts, and batch accounting, with a configurable fail-open/fail-closed policy.

Acceptance goals:

- Repeated Phase 2 parse/validation failures are visible by default in `play` output and verbose `simulate` summaries.
- Marked fallback no-op turns remain mechanically safe: no delta, no winner, no fight end.
- Batch results can count fallback turns separately from hard `winner=error` rows.
- A fail-closed policy turns repeated Phase 2 failure into a fight error instead of a no-op.
- Existing qwen-style fail-open behavior remains available when explicitly configured.

Required tests:

- Mock repeated Phase 2 failures and assert the recorded turn has `fallback_used=true` metadata.
- Render/simple-output tests show a compact warning marker for fallback turns.
- Default policy test proves the run continues but is visibly marked.
- Fail-closed policy test proves the fight/batch returns an error row or raises through CLI as designed.
- Batch summary tests include fallback count and hard error count separately.

## Layer Health And Anatomy Consequence Policies

Addresses: ISSUE-017, ISSUE-020

- [ ] Split tissue maximum durability from mutable combat health, then replace coarse `is_vital` outcome logic with explicit anatomy consequence policies.

Acceptance goals:

- Damage lowers `current_hp` and never changes `max_hp`.
- Existing humanoid fights serialize cleanly and run without schema or prompt regressions.
- Status changes come from explicit consequence policies, not from counting all vital parts.
- Heart and head destruction produce the chosen fatal outcome immediately.
- Single-eye, both-eye, and leg destruction produce explicit non-death consequences visible in state.

Required tests:

- State tests for `current_hp` mutation, `max_hp` stability, overkill clamping, destruction, severing, and serialization.
- Anatomy tests for initialized `current_hp == max_hp` and humanoid consequence tags.
- Consequence tests for heart, head, torso, one eye, both eyes, one leg, and both legs.
- Property tests updated so HP monotonicity checks `current_hp`, while `max_hp` remains stable.

## Anatomy-Driven Bleeding, Burning, And Layer Accuracy

Addresses: ISSUE-016, ISSUE-029

- [ ] Make humanoid bleed/burn anatomy meaningful and make burn tick logging match the layer that actually takes damage.

Acceptance goals:

- Default piercing/slashing damage creates targeted bleeding on appropriate humanoid parts.
- Parts with `bleed_rate = 0` do not auto-create bleeding.
- A custom high-`burn_rate` part takes more burn tick damage than a normal part under the same effect.
- Burn logs/debug reports identify the exact layer whose HP changed.
- Burning/bleeding effects keep stable targeted metadata for later prompt and removal work.

Required tests:

- Default humanoid bleeding from piercing and slashing without manually setting `bleed_rate`.
- No bleeding on a zero-bleed part.
- Burn tick tests comparing normal and high-burn-rate parts.
- Multilayer burn test proving the logged or returned layer is the mutated layer.
- Regression test that a burning tick does not create duplicate burning effects for the same part.

## Targeted Effect Removal And Effect Identity

Addresses: ISSUE-018

- [ ] Replace name-only effect removal with structured targeted removal while preserving explicit legacy remove-all behavior.

Acceptance goals:

- Removing bleeding from one part leaves bleeding on other parts intact.
- Removing burning from one limb leaves burning on another limb intact.
- Name-only removal still removes all matching effects and is documented as remove-all.
- Buff and debuff effects with the same name can be removed separately when `type` is supplied.
- Malformed removal objects are rejected by schema or skipped safely before state mutation.

Required tests:

- Validation tests for valid string removals, valid structured removals, invalid unknown fields, missing `name`, bad `type`, and unsafe `targeted_part`.
- State tests with two bleeding effects on different parts and one targeted removal.
- State tests for same-name buff/debuff removal by `type`.
- Judge prompt/schema tests proving `effects_removed` documents structured targeted removal.
- Property coverage for mixed add/remove deltas with no accidental broad deletion.

## Prompt State Context And Environment-Scoped Creativity

Addresses: ISSUE-014, ISSUE-015, ISSUE-030

- [ ] Add shared compact fighter-state summary helpers for fighter prompts and Judge Phase 1, and rephrase environment guardrails so configured environment/equipment/effect features are usable while invented open-arena cover remains forbidden.

Acceptance goals:

- Fighter prompts include actionable opponent state, anatomy, damage, and effect metadata without relying on recent narration.
- Judge Phase 1 payload includes partial injuries and structured effect details, not effect names only.
- Explicit environments like pillars, smoke, or cover are allowed when configured; open arena prompts still forbid invented cover.
- Prompt payloads stay compact enough for existing context-budget behavior.

Required tests:

- Prompt tests cover opponent loadout, custom/manual body parts, partial eye/limb damage, severed parts, effect TTL/magnitude/target, open arena guardrails, and explicit-feature environments.
- Update `docs/Design_doc.md` or README prompt/state-summary contract if the payload shape changes.

## Turn Diff And Roll Transparency

Addresses: ISSUE-021, ISSUE-022

- [ ] Store roll outcomes on `CombatTurn` and render visible mechanical turn diffs for roll success, stat changes, wounds, body-part changes, effects, and status changes.

Acceptance goals:

- Rich and simple `play` output shows whether each action succeeded or failed.
- Mechanical changes are visible even when narration is vague.
- No-op turns are distinguishable from turns with hidden state changes.
- Existing turn tables remain readable and non-duplicated.

Required tests:

- Simulation tests prove `CombatTurn` stores roll metadata.
- Combat-log/render snapshot-style tests cover rolls, wounds, stat deltas, effects, status changes, and no-op turns.
- README usage/output examples are updated if the visible play format changes.

## Fight-Scoped JSONL Trace Transcripts

Addresses: ISSUE-026

- [ ] Replace isolated prompt/response transcript fragments with one fight-scoped JSONL trace containing ordered events for each fight.

Acceptance goals:

- With `save_transcripts = true`, each fight produces one readable ordered trace file.
- Every event has fight id, turn, phase, and relevant fighter metadata.
- Failed or interrupted fights still preserve events written so far.
- `save_transcripts = false` remains silent.
- Existing transcript tests either remain compatible through a wrapper or are migrated cleanly.

Required tests:

- Transcript tests for one-file-per-fight, event order, metadata fields, disabled mode, and failure-path persistence.
- Mocked simulation coverage proving rolls, deltas, and states appear in the trace.
- README/docs document the trace format and config.

## Configured Fighter Display Names

Addresses: ISSUE-027

- [ ] Implement config `name` as an end-to-end fighter display name while preserving stable ids `A` and `B` for machine logic.

Acceptance goals:

- `llmfight.ini.example` names appear during play.
- Prompts make both display name and stable Fighter A/B id clear.
- Missing names fall back to the fighter id without changing behavior.
- Result objects and CSV winner ids remain stable, with display names added only where safe.

Required tests:

- Config tests for `name` loading and fallback.
- `FighterState.from_preset`, prompt, render, transcript, and CLI winner-output tests.
- README/config docs explain fighter names versus ids.

## Runtime Config And RNG Isolation

Addresses: ISSUE-028

- [ ] Introduce scoped runtime ownership for config and randomness. Prefer passing an explicit runtime context/config/RNG through simulation entry points and helpers; at minimum, make CLI config replacement/restoration exception-safe and seed RNG explicitly after config loading.

Acceptance goals:

- Multiple CLI invocations in one process do not leak config overrides.
- RNG imported before a config swap still uses the active entry-point seed.
- Programmatic callers can run with explicit config without mutating global state permanently.
- Existing simple CLI usage remains unchanged.

Required tests:

- `CliRunner` tests invoking different configs sequentially in one process.
- RNG/config import-order regression tests.
- Simulation tests for deterministic seeded runs after config load.
- Update `docs/Design_doc.md` if a runtime-context API is introduced.

## Live/Perf Gating And Installed-Package Test Workflow

Addresses: ISSUE-032, ISSUE-035

- [ ] Centralize live/perf test gating and stop bypassing installed package behavior.

Acceptance goals:

- `uv sync --locked --dev && uv run pytest -q` collects and runs without the `live` extra.
- `--run-live` runs quick live smoke tests only when `API_URL` is set.
- Heavy perf tests require an explicit separate opt-in such as `--run-perf`.
- CI exercises the installed package path and console script behavior.

Required tests:

- Add pytester-style tests for live/perf marker gating if practical.
- Add packaging smoke coverage for import and `llmfight --help` without manual `sys.path` insertion.
- Update README, AGENTS live-test commands, and CI notes.

## Current Gameplay And Retry Contract Docs

Addresses: ISSUE-033

- [ ] Document the current runtime contracts honestly until the larger gameplay/UX tasks land: fixed humanoid anatomy, mostly prose non-humanoid concepts, post-fight `play` output until streaming progress is implemented, and capped Judge Phase 2 no-op fallback behavior.

Acceptance goals:

- New users are not led to expect custom anatomy, live turn streaming, or unlimited retry recovery.
- Troubleshooting distinguishes stronger-model/token advice from capped Phase 2 fallback behavior.
- Docs remain easy to update once the corresponding TODO items are implemented.

Required tests:

- README Known Limitations and Troubleshooting updates.
- `docs/Design_doc.md` current-contract note.
- Optional docs consistency check for referenced commands/config keys.

## Library-Friendly Logger Setup

Addresses: ISSUE-034

- [ ] Make package logging library-friendly by using a `NullHandler` by default, avoiding stdout handlers at import time, checking direct `logger.handlers` rather than `hasHandlers()`, and configuring CLI-owned handlers to stderr only when running CLI commands.

Acceptance goals:

- Importing `llm_fight` does not write to stdout or attach a visible console handler.
- Host applications with root handlers do not suppress or duplicate package handlers unexpectedly.
- CLI verbose/log output goes to stderr and does not corrupt normal stdout output.
- Repeated imports or CLI invocations do not add duplicate handlers.

Required tests:

- Logger reload tests for root-handler, direct-handler, propagation, and duplicate-handler cases.
- CLI tests asserting logs use stderr.
- Update developer docs only if logging behavior or troubleshooting changes.
