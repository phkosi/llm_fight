# Rewrite Milestones for LLM Fighters

This document captures a full set of milestones to rewrite weak or faulty
parts of the project. Milestones focus on correctness, maintainability, and
observability so the combat loop remains trustworthy when orchestrated by LLMs.

## Current Pain Points (why a rewrite is needed)

- **Fragile LLM client surface** - `src/llm_fight/agents.py` assembles payloads and
  retries manually without a typed request/response model or centralized
  timeout/backoff policy, leaving error handling duplicated and difficult to
  test.
- **Prompt plumbing tied to globals** - Fighter prompts embed config lookups and
  combat-log formatting inline (see `src/llm_fight/engine/fighter.py`), coupling prompt
  construction to runtime state and making deterministic tests or alternate
  prompt strategies awkward.
- **Simulation loop mixes orchestration with mutation** - The fight loop in
  `src/llm_fight/simulation.py` parses probabilities, applies RNG, updates fighter state,
  and writes the combat log in one monolithic coroutine, making it hard to swap
  judge implementations or replay deterministic traces.
- **State mutation lacks guardrails** - `src/llm_fight/state.py` directly mutates shared
  structures while applying deltas and ticking effects. There is no central
  invariant enforcement (e.g., pain/HP floors, bleeding stacking rules), and
  the effect pipeline is intertwined with logging side effects.
- **Observability is ad hoc** - Transcript logging depends on globals and
  scattered logger calls; there is no structured telemetry for LLM latency,
  retries, or RNG decisions to debug questionable fight outcomes.

## Milestones

### 1) Rebuild the LLM I/O and configuration layer
- Introduce a typed request/response abstraction for chat calls with explicit
  timeouts, retry/backoff policy, and structured error envelopes.
- Separate config resolution from runtime logic (inject config into call sites
  instead of relying on module-level singletons) and add validation for
  required keys at startup.
- Provide a pluggable transport interface (aiohttp/local stub) with trace hooks
  for tests and diagnostics.

### 2) Redesign prompt construction and guardrails
- Split fighter and judge prompt builders into pure functions that accept
  explicit inputs (state snapshots, recent log summaries) and return both the
  rendered prompt and a machine-readable schema contract.
- Add unit tests that snapshot prompts for typical and edge-case states (e.g.,
  zero turn history, extreme pain/heat) to ensure determinism across releases.
- Centralize schema definitions and strict parsing so both phases share a
  single contract surface with consistent validation errors.

### 3) Harden state and damage modeling
- Refactor `FighterState`, `BodyPart`, and `Effect` into immutable data models
  with explicit mutation methods that enforce invariants (no negative HP,
  capped pain/exhaustion, severing semantics, bleed stacking rules).
- Isolate side effects (log messages, telemetry) from state transitions so
  tests can validate pure transitions without patching loggers.
- Add property-based tests for damage application, effect expiry, and
  unconscious/death thresholds to replace ad hoc checks.

### 4) Modularize the fight orchestration pipeline
- Extract RNG resolution, judge interaction, delta application, and logging
  into discrete, composable steps with typed inputs/outputs to allow replay,
  deterministic seeding, and simulation of alternative judge strategies.
- Provide a replayable trace format (JSONL) that captures prompts, RNG rolls,
  deltas, and resulting states for each turn; include a verifier that can
  re-run a fight deterministically from the trace.
- Add cancellation and timeout handling around judge calls so batch runs cannot
  hang, and surface partial progress to the CLI.

### 5) Improve observability and developer tooling
- Standardize structured logging and metrics (per-call latency, retries, token
  counts) and wire them into the CLI and batch runner flags.
- Replace ad hoc transcript logging with a configurable sink that supports
  local files and in-memory capture for tests.
- Expand CI to run contract tests against stubbed judge/fighter endpoints and
  enforce formatting/linting on generated prompts and schemas.

### 6) UX and documentation alignment
- Update CLI flows to expose the new tracing/verbosity controls and validate
  configuration before starting simulations.
- Refresh README and design docs to reflect the new architecture, including an
  "implementation contract" section for third-party judge providers.
- Provide migration guidance for existing INI files and scripted integrations
  that relied on the previous globals and side effects.
