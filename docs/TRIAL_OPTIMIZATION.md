# Trial Optimization

## North Star

Optimize for tactical emergence: multi-turn adaptation, mechanical consequences, readable causality, and reliable state continuity. Character novelty matters when it creates schema-backed mechanics that survive into state, prompts, and judge payloads.

## Current Evidence

- Configured pilot: `transcripts/trials/20260513_231206`, collected with `uv run llmfight collect-trials` after smoke root `transcripts/trials/20260513_231032`.
- Generated-character pilot: `transcripts/trials/20260513_233837`, collected with `uv run llmfight collect-trials --mode generated` after smoke root `transcripts/trials/20260513_233748`.
- Generated-profile baseline: `transcripts/profile_trials/20260514_180458`, collected with `uv run llmfight collect-profile-trials` after smoke root `transcripts/profile_trials/20260514_180400`.
- Generated-profile prompt pass: `transcripts/profile_trials/20260514_181840`, collected with `uv run llmfight collect-profile-trials` after smoke root `transcripts/profile_trials/20260514_181802`.
- Configured finalist retest: `transcripts/trials/20260514_183917`, collected with `uv run llmfight collect-trials --matrix finalist` after smoke root `transcripts/trials/20260514_183741`; analyzed with `uv run llmfight analyze-trials transcripts/trials/20260514_183917`.
- Generated-mode retest: `transcripts/trials/20260514_203736`, collected with `uv run llmfight collect-trials --mode generated` after smoke root `transcripts/trials/20260514_203355`; analyzed with `uv run llmfight analyze-trials transcripts/trials/20260514_203736`.
- Analyze with `uv run llmfight analyze-trials transcripts/trials/20260513_231206 transcripts/trials/20260513_233837`.

The configured pilot established the first parameter signal. Its structured reviews settle at baseline 13, candidate 1, inconclusive 2, so `0.4/default` remains the provisional default for both tested models unless a cleaner multi-seed retest clears promotion flags.

The generated-character pilot is blocked for parameter conclusions. `review_results.json` recomputes to baseline 5, candidate 8, inconclusive 3, includes note/result contradictions, and records 1 generated fighter profile plus 35 fallback profiles across 36 fighters. Treat generated-mode results as fallback-behavior evidence until profile generation succeeds reliably.

The generated-profile baseline confirmed the prompt reliability gap before prompt changes: 12 profile-only samples produced 1 valid profile and 11 fallbacks, for a 0.9167 fallback rate. `qwen3.6:35b` fell back on all 6 nudges; `gemma4:26b` generated only the `mage` profile and fell back on 5 of 6 nudges. The lone valid profile had an altered/non-humanoid body plan with `brain` as a custom target part, so generated anatomy could work but was not reliable enough for generated-mode trials.

The prompt reliability pass cleared the dedicated profile gate. After tightening the system prompt and user payload around exact top-level keys, allowed body-part keys, no `null` optional fields, allowed consequence tags, a safe terminal-part pattern, a valid example, and nudge-specific custom-part guidance, the profile-only sample produced 12 valid profiles, 0 fallbacks, and 12 altered/non-humanoid body plans. Treat generated-mode profile fallback as unblocked for the next generated retest, while keeping parameter conclusions separate until full generated fights are rerun and judged.

The configured finalist retest produced 15 completed cells and 9 same-model/same-seed blind pairs. Structured blind judging settled at baseline 1, candidate 3, inconclusive 5. Analysis kept every finalist setting at `retest` rather than `promote` because of review disagreements and P2 fallback reliability flags. For `qwen3.6:35b`, `0.2/expansive` is the most promising next-start setting, with 2 candidate wins and 1 inconclusive across 3 seeds; keep `0.4/default` as the committed default until P2 reliability is cleaner. For `gemma4:26b`, keep `0.4/default` as the recommended starting setting: `0.2/expansive` had 1 candidate and 2 inconclusive results, while `0.7/focused` had 1 baseline and 2 inconclusive results.

The generated-mode retest shows the prompt reliability pass worked for profile creation but not yet for parameter promotion. A narrow profile retry fix recovered invalid profile responses during the run; the full run completed 18/18 cells and 16 same-model blind pairs with 36 generated profiles, 0 fallback profiles, 3 P2 fallback turns, and pervasive custom generated anatomy. Blind judging settled at baseline 5, candidate 5, inconclusive 6. No setting promotes from this single-seed evidence. `qwen3.6:35b` `0.4/expansive` and `0.4/focused` are single-seed `retest`; most other qwen generated settings reject or remain inconclusive. `gemma4:26b` `0.2/default`, `0.4/expansive`, and `0.7/expansive` are single-seed `retest`; other gemma generated settings reject or remain inconclusive. Reviewers repeatedly found useful generated anatomy and silhouettes, but also target conflicts, dropped successful consequences, setup/status-only successful hits, P2 fallback, and `p=0.0` UX; treat these as generated-anatomy reliability findings rather than prompt-schema fallback findings.

## Runtime Defaults

Runtime model selection now uses a built-in registry with local config overrides. `[General] ollama_default_model` is required for LLM runs. Tested models currently receive provisional `0.4/default` settings with `max_tokens_fighter = 512`, `max_tokens_judge = 4096`, and `ollama_num_ctx = 90000`; unknown models use generic output/context limits and omit temperature so the provider default applies unless the local config sets a numeric temperature.

Targeted default-finalization evidence should be collected one model at a time:

```bash
uv run llmfight collect-trials --matrix default-finalization --model qwen3.6:35b
uv run llmfight collect-trials --matrix default-finalization --model gemma4:26b
```

Promotion rule: a candidate must beat baseline overall with no profile fallback, no review-result inconsistency, no parse-failure cells, and no worse P2 fallback rate than baseline. If no candidate clears that bar, keep `0.4/default`.

## Analysis Workflow

`analyze-trials` writes ignored local reports under each run root or under `transcripts/trials/analysis/<timestamp>/` for combined runs:

- `analysis.json` for structured aggregation and flags.
- `analysis.md` for reviewer-readable conclusions.
- `settings.csv` for model/temperature/token-preset grouping.
- `pairs.csv` for pair-level review outcomes, metrics, and notes.

The analyzer treats structured review fields as source of truth, but flags stored-total mismatches, missing pair joins, vote-settlement contradictions, note-polarity contradictions, P2 fallback, and generated-profile fallback. Any generated profile fallback or review inconsistency blocks parameter promotion.

Use `uv run llmfight collect-profile-trials` before changing generated-profile prompts. It writes ignored profile-only evidence under `transcripts/profile_trials/<timestamp>/`: `manifest.json`, `analysis.json`, `analysis.md`, `profiles.csv`, and `settings.csv`. The report records validation outcomes, fallback/error codes, model settings, nudges, custom target parts, altered body plans, non-humanoid body-plan rate, and schema-backed anatomy/consequence metrics without running fights.

## Retest Matrix

- Configured `qwen3.6:35b`: treat `0.2/expansive` as promising but still `retest`, not `promote`, because the finalist run had review disagreement and baseline P2 fallback flags.
- Configured `gemma4:26b`: keep `0.4/default` as the provisional start; neither `0.2/expansive` nor `0.7/focused` cleared `retest`.
- Generated mode: profile fallback is below 20% in both the profile-only sample and the full generated retest, and generated-mode recommendations are no longer blocked by profile fallback. No generated setting promotes. For `qwen3.6:35b`, `0.4/expansive` and `0.4/focused` are single-seed `retest`; most other candidates reject or remain inconclusive. For `gemma4:26b`, `0.2/default`, `0.4/expansive`, and `0.7/expansive` are single-seed `retest`; other settings reject or remain inconclusive.

Use at least 3 seeds for finalist retests before changing defaults. The configured finalist support is available as:

```bash
uv run llmfight collect-trials --matrix finalist
```

The command preserves the default `collect-trials` behavior unless `--matrix finalist` is passed. The finalist matrix defaults to seeds `42,43,44` and writes ignored artifacts under `transcripts/trials/`.

## Reliability Follow-Ups

`ISSUE-002` tracks non-blocking Judge Phase 2 reliability evidence from the finalist retest: invalid zero-value effect mechanics, object-shaped TTL fields, null effect text, wrong-side effect application, and non-canonical target acceptance. These issues are why the current parameter evidence should stay in `retest` rather than become default changes.

`ISSUE-003` tracks generated-anatomy target and consequence drift from the generated-mode retest. Generated profiles now often improve originality, anatomy usability, and silhouettes, but custom body parts expose target-conflict and missing-consequence failure modes that need a reliability pass before adding new mechanic schemas.

## Prompt Direction

Do not change combat defaults from the pilot or generated-mode single-seed data alone. The first prompt target kept the current schema and runtime mechanics unchanged, and improved profile reliability through clearer schema contracts rather than broader mechanics. Keep profile prompting stable until a targeted generated-anatomy reliability pass has made custom target parts and successful consequences more dependable. Continue measuring non-humanoid body plans, custom target parts, profile validation success, and schema-backed effect originality before adding new mechanics.
