# Resolved Issues Summary - May 2026

This archive replaces the long resolved issue ledger that previously lived in root `ISSUES.md`.

## P0 Resolved

- Custom anatomy became reachable at runtime through configured and generated profiles.
- Creative/custom effects gained safe declarative mechanics.

## P1 Resolved

- Judge Phase 2 deltas can no longer bypass validity and dice rolls.
- Judge-only winners no longer end fights without matching Python state.
- Effect payloads are validated before entering state or later prompts.
- Newly created effects survive into the next prompt before ticking.
- Damaging destroyed or severed parts still runs status invariants.
- Oversized prompts now fail before transport instead of degrading to one-token completions.
- Concurrent batch runs use isolated deterministic RNG.
- Invalid batch concurrency fails fast.
- `llmfight play` is responsive before the whole fight finishes.
- Transport logs and proxy handling avoid prompt leakage and unsafe loopback proxy defaults.

## P2 Resolved

- Phase 2 target validity is enforced after model output.
- Fighter and judge prompts include opponent state, anatomy, damaged parts, and active effect metadata.
- Humanoid bleed/burn anatomy now has mechanical meaning.
- Vital-part consequences are explicit instead of coarse.
- Effect removal can target localized effects.
- Judge deltas cannot revive terminal fighters.
- Tissue max HP and current HP are separate.
- Terminal output shows combat changes, rolls, token metadata, Phase 2 fallback markers, and batch failure summaries.
- Fight traces are ordered JSONL artifacts instead of disconnected prompt fragments.
- Configured fighter `name` now flows through prompts, output, traces, and batch metadata.
- Runtime config and RNG ownership are scoped around CLI calls.
- CI/test workflow issues around Rich/Typer output and installed-package behavior were resolved.
- Earlier monolithic modules and oversized functions were split below the repository thresholds.

## P3 Resolved

- Burn tick logs match the layer that actually changes.
- Environment guardrails allow explicitly configured features while blocking invented cover.
- OpenAI-compatible endpoint mode has its own payload and health-check handling.
- Live/perf tests are gated consistently.
- Docs now state the current anatomy/progress/retry contracts.
- Logger setup is library-friendly.
- Test collection no longer bypasses the installed package.
- Non-verbose interactive play no longer duplicates engine turn logs.
- Stale temporary effects from combat narration no longer override current state.
