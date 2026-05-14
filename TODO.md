# TODO

This file tracks active implementation work only. Completed historical work from the May 2026 hardening and cleanup pass is summarized in [docs/archive/completed-work-2026-05.md](docs/archive/completed-work-2026-05.md).

## Active Tasks

### Generated Profile Prompt Reliability Pass

Addresses: DESIGN-002

- [ ] Implementation intent: Use the profile evaluation evidence to improve generated-profile prompting and user payload guidance while keeping the current profile schema and runtime mechanics unchanged.
- [ ] Acceptance goals: Generated profile fallback falls below 20% on the dedicated profile sample for the tested models; valid outputs include non-humanoid or meaningfully altered body plans often enough to evaluate generated mode.
- [ ] Required tests: Prompt/payload regression tests, profile validation tests, and existing generated-profile simulation tests.
- [ ] Verification: Standard quality gates plus a live profile evaluation report saved under ignored `transcripts/`; update `docs/TRIAL_OPTIMIZATION.md` with the new fallback rate and prompt conclusions.

### Multi-Seed Finalist Trial Support

Addresses: none

- [ ] Implementation intent: Extend trial collection to support a small finalist matrix and multiple seeds without changing default `collect-trials` behavior.
- [ ] Acceptance goals: Can run configured finalists: `qwen3.6:35b` baseline plus `0.2/expansive`, and `gemma4:26b` baseline plus `0.2/expansive` and `0.7/focused`, across at least 3 seeds; artifacts remain ignored under `transcripts/`.
- [ ] Required tests: Matrix/spec tests for default-vs-finalist behavior, seed expansion, manifest metadata, blind-pack pairing, and CLI wiring.
- [ ] Verification: Standard quality gates plus a smoke finalist collection with fake/offline tests; live full collection only when models are intentionally available.

### Finalist Retest And Model Preset Recommendation

Addresses: none

- [ ] Implementation intent: Run the multi-seed configured finalist trials, analyze them, judge blind packs, and turn the results into provisional model-specific parameter recommendations.
- [ ] Acceptance goals: `docs/TRIAL_OPTIMIZATION.md` names the recommended starting settings per tested model, evidence roots, review outcomes, reliability flags, and whether any setting remains `retest` instead of `promote`.
- [ ] Required tests: No new code required unless analysis gaps are found; add tests only for any tooling fix needed during the retest.
- [ ] Verification: `uv run llmfight analyze-trials <finalist roots...>`; standard quality gates if files change; 2-subagent review before commit.

### Generated-Mode Retest After Profile Reliability

Addresses: DESIGN-002

- [ ] Implementation intent: After generated-profile fallback is below 20%, rerun generated-character trials, analyze the new artifacts, and re-review blocked or contradictory generated-mode pairs.
- [ ] Acceptance goals: Generated-mode recommendations are no longer blocked by profile fallback; note/result contradictions are resolved or explicitly marked inconclusive; docs distinguish prompt-quality findings from parameter findings.
- [ ] Required tests: Reuse existing trial/analysis tests; add regressions only if rerun evidence exposes tooling defects.
- [ ] Verification: Generated smoke and full collection, `analyze-trials`, blind review results, standard quality gates for tracked updates, and 2-subagent review before commit.

## Task Template

```markdown
### Short Task Title

Addresses: ISSUE-###

- [ ] Implementation intent:
- [ ] Acceptance goals:
- [ ] Required tests:
- [ ] Verification:
```
