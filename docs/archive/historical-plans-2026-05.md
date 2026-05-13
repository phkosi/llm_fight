# Historical Planning Notes - May 2026

This file replaces the active `docs/DEVELOPMENT_PLAN.md` and `docs/REWRITE_MILESTONES.md` documents. Those files described a rewrite-era backlog that has mostly been completed or superseded.

## Superseded Milestones

- Core state updates, body-part mechanics, structured combat logs, dynamic loadouts/classes/environments, async batch concurrency, and CLI visualization were implemented.
- Prompt/context hardening, parsing retries, failure scenarios, property tests, Python 3.14 packaging, and the locked `uv` workflow were implemented.
- The earlier rewrite concerns around fixed humanoid state, weak observability, prompt drift, brittle validation, global RNG, and oversized files were converted into issue-backed implementation slices and resolved.

## Current Planning Surfaces

- Use root `TODO.md` only for active implementation tasks.
- Use root `ISSUES.md` for active bugs, regressions, security risks, prompt failures, test gaps, and code-size findings.
- Use `DESIGN_ISSUES.md` for product design concerns such as pacing, drama, balance, and readability.
- Use `docs/ADVANCED.md` for operator/developer details that should not clutter first-run README flow.
