# TODO

This file tracks active implementation work only. Completed historical work from the May 2026 hardening and cleanup pass is summarized in [docs/archive/completed-work-2026-05.md](docs/archive/completed-work-2026-05.md).

## Active Tasks

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
