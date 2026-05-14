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
- Accepted generated-character artifacts at `transcripts/trials/20260513_233837` after smoke root `transcripts/trials/20260513_233748`; 18/18 cells completed, 16 blind same-model pairs were reviewed, normalized judging settled at baseline 6, candidate 10, inconclusive 0, and generated profile metadata recorded 1 generated fighter profile plus 35 fallback fighter profiles.

## Repo And Test Hygiene

- Moved to Python 3.14, `uv`, `ruff`, `mypy`, and installed-console-script testing.
- Split oversized simulation, batch, Phase 2 authorization, state/effect, CLI, agents, fighter prompt, judge Phase 2, and profile-builder tests.
- Made logging library-friendly and stderr-owned by the CLI.
- Closed the earlier monolithic-file and oversized-function issues after measured refactor slices.
