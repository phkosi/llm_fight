# Completed Work Summary - May 2026

This is a compact archive of the completed root `TODO.md` history that was removed from the active tracker during the lean-repo cleanup.

## Model Playtest Hardening

- Qwen 3.6 35B and Gemma 4 26B playtest loops exposed empty fighter actions, malformed Judge Phase 2 JSON, stale temporary effects, duplicate rich/plain turn output, context-size runner churn, and open-arena hallucinations.
- Completed fixes added non-empty action fallback, native Ollama `think=false`, capped Judge Phase 2 parse repair, visible Phase 2 fallback turns, fixed context sizing, current-state prompt authority, and cleaner interactive rendering.

## Emergent Engine Work

- Added structured custom fighter anatomy through `anatomy_profile`.
- Added optional match-start generated fighter profiles.
- Added creativity-gate coverage proving non-humanoid parts and dynamic effects survive into state, prompts, judge payloads, and traces.
- Added declarative dynamic effect mechanics for safe stat ticks, damage ticks, targeting modifiers, and action blockers.

## State And Judge Guardrails

- Added deterministic Phase 2 source authorization and target validation.
- Made Python state authoritative for outcomes instead of accepting judge-only winners.
- Added monotonic status changes and invariant updates after state mutations.
- Added effect payload validation, fresh-turn effect timing, targeted effect removal, layer current HP, anatomy consequence policies, and anatomy-driven bleed/burn behavior.

## UX And Observability

- Streamed `play` progress with fighter design views, status updates, turn rendering, roll visibility, and mechanical diffs.
- Added fight-scoped JSONL traces with event order, token metadata, rolls, deltas, state snapshots, sanitized errors, and final results.
- Added batch failure accounting, incremental CSV writing, and visible Phase 2 fallback columns.
- Collected local trial evidence with `uv run llmfight collect-trials --smoke`, `uv run llmfight collect-trials`, `uv run llmfight collect-trials --mode generated --smoke`, and `uv run llmfight collect-trials --mode generated`.
- Accepted configured-fighter artifacts at `transcripts/trials/20260513_231206` after smoke root `transcripts/trials/20260513_231032`; 18/18 cells completed, 16 blind same-model pairs were reviewed, and normalized judging settled at baseline 13, candidate 1, inconclusive 2.
- Accepted generated-character artifacts at `transcripts/trials/20260513_233837` after smoke root `transcripts/trials/20260513_233748`; 18/18 cells completed, 16 blind same-model pairs were reviewed, structured judging settled at baseline 5, candidate 8, inconclusive 3, and generated profile metadata recorded 1 generated fighter profile plus 35 fallback fighter profiles.
- Added `collect-profile-trials` for profile-only generated-fighter evaluation without running fights. The live baseline at `transcripts/profile_trials/20260514_180458` after smoke root `transcripts/profile_trials/20260514_180400` sampled `qwen3.6:35b` and `gemma4:26b` across all fixed creation nudges, wrote ignored JSON/Markdown/CSV reports, and measured 1 valid generated profile plus 11 fallbacks for a 0.9167 fallback rate before prompt changes.
- Improved generated-profile prompt reliability while keeping the schema and runtime mechanics unchanged. The live prompt-pass report at `transcripts/profile_trials/20260514_181840` after smoke root `transcripts/profile_trials/20260514_181802` measured 12 valid generated profiles, 0 fallbacks, and 12 altered/non-humanoid body plans across the tested models and fixed nudges.
- Added opt-in multi-seed finalist support to `collect-trials` without changing the default full matrix. `uv run llmfight collect-trials --matrix finalist` now runs the configured finalist settings for `qwen3.6:35b` and `gemma4:26b` across seeds `42,43,44`, records matrix and seed metadata in manifests, and builds blind packs against the same model and seed baseline.
- Ran the configured finalist retest at `transcripts/trials/20260514_183917` after smoke root `transcripts/trials/20260514_183741`, judged 9 same-model/same-seed blind pairs, and analyzed the run. Outcomes were baseline 1, candidate 3, inconclusive 5; `qwen3.6:35b` `0.2/expansive` is promising but remains `retest`, while `gemma4:26b` stays on `0.4/default` as the provisional start. `ISSUE-002` records the P2 fallback/effect-payload reliability findings that blocked promotion.
- Ran the clean generated-mode retest at `transcripts/trials/20260514_203736` after smoke root `transcripts/trials/20260514_203355`, judged 16 same-model blind pairs, and analyzed the run. A narrow generated-profile retry fix recovered invalid profile responses, producing 36 generated profiles and 0 profile fallbacks across 36 fighter slots; blind outcomes were baseline 5, candidate 5, inconclusive 6. No generated setting promoted: generated-mode recommendations are no longer blocked by profile fallback, but single-seed evidence, review disagreements, P2 fallback, and generated-anatomy target/consequence drift keep candidates at `retest` or `reject`. `ISSUE-003` records the generated-anatomy reliability findings.
- Added model-aware runtime defaults and finalized `qwen3.6:35b` on `0.4/expansive` after targeted configured and generated default-finalization retests. Evidence roots: `transcripts/trials/20260514_235729`, `transcripts/trials/20260515_000524`, and analysis output `transcripts/trials/analysis/20260515_003931`; combined blind outcomes were baseline 5, candidate 10, inconclusive 3, with `0.4/expansive` clearing the promotion rule.

## Repo And Test Hygiene

- Moved to Python 3.14, `uv`, `ruff`, `mypy`, and installed-console-script testing.
- Split oversized simulation, batch, Phase 2 authorization, state/effect, CLI, agents, fighter prompt, judge Phase 2, and profile-builder tests.
- Made logging library-friendly and stderr-owned by the CLI.
- Closed the earlier monolithic-file and oversized-function issues after measured refactor slices.
