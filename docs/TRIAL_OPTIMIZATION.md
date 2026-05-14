# Trial Optimization

## North Star

Optimize for tactical emergence: multi-turn adaptation, mechanical consequences, readable causality, and reliable state continuity. Character novelty matters when it creates schema-backed mechanics that survive into state, prompts, and judge payloads.

## Current Evidence

- Configured pilot: `transcripts/trials/20260513_231206`, collected with `uv run llmfight collect-trials` after smoke root `transcripts/trials/20260513_231032`.
- Generated-character pilot: `transcripts/trials/20260513_233837`, collected with `uv run llmfight collect-trials --mode generated` after smoke root `transcripts/trials/20260513_233748`.
- Analyze with `uv run llmfight analyze-trials transcripts/trials/20260513_231206 transcripts/trials/20260513_233837`.

The configured pilot is the only current parameter signal strong enough for provisional defaults. Its structured reviews settle at baseline 13, candidate 1, inconclusive 2, so `0.4/default` remains the provisional default for both tested models pending multi-seed retests.

The generated-character pilot is blocked for parameter conclusions. `review_results.json` recomputes to baseline 5, candidate 8, inconclusive 3, includes note/result contradictions, and records 1 generated fighter profile plus 35 fallback profiles across 36 fighters. Treat generated-mode results as fallback-behavior evidence until profile generation succeeds reliably.

## Analysis Workflow

`analyze-trials` writes ignored local reports under each run root or under `transcripts/trials/analysis/<timestamp>/` for combined runs:

- `analysis.json` for structured aggregation and flags.
- `analysis.md` for reviewer-readable conclusions.
- `settings.csv` for model/temperature/token-preset grouping.
- `pairs.csv` for pair-level review outcomes, metrics, and notes.

The analyzer treats structured review fields as source of truth, but flags stored-total mismatches, missing pair joins, vote-settlement contradictions, note-polarity contradictions, P2 fallback, and generated-profile fallback. Any generated profile fallback or review inconsistency blocks parameter promotion.

## Retest Matrix

- Configured `qwen3.6:35b`: baseline plus `0.2/expansive`.
- Configured `gemma4:26b`: baseline plus `0.2/expansive` and `0.7/focused`.
- Generated mode: rerun only after generated-profile fallback is below 20% in a dedicated profile-generation sample.

Use at least 3 seeds for finalist retests before changing defaults.

## Prompt Direction

Do not change combat defaults from the pilot alone. First prompt target is generated-profile reliability while keeping the current schema: improve profile prompt clarity, nudge handling, valid anatomy examples, and explicit terminal/vital consequence requirements. Measure non-humanoid body plans, custom target parts, profile validation success, and schema-backed effect originality before adding new mechanics.
