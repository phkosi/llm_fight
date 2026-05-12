# Issues

Consolidated from a 14-agent review pass plus a local read-through. Baseline verification during the pass: `uv run pytest -q` -> `235 passed, 6 skipped, 1 warning`.

Severity guide:

- P0: blocks the stated creative/emergent direction.
- P1: likely correctness, security, reliability, or UX failure.
- P2: important gap or design risk.
- P3: lower-risk cleanup, docs, or coverage gap.

Playtest loop tracking fields for new or updated entries:

- `Status: open | tasked | resolved`
- `Task: none | TODO.md - <section/task>`
- `Source: playtest | codebase review | implementation review`
- `Evidence:`
- `Impact:`
- `Suggested fix:`
- `Tests:`

When a task is added to `TODO.md` for an issue, update that issue with `Task: TODO.md - <section/task>` and mark `Status: tasked`.

## P0

### ISSUE-001: Custom anatomy is not reachable at runtime

- Status: resolved
- Task: TODO.md - Structured Custom Fighter Anatomy Profiles; Match-Start LLM Fighter Profile Creation; Creativity Gate For Dynamic Anatomy And Effects
- Source: codebase review
- Area: Gameplay systems, dynamic anatomy
- Evidence: Original review found `_single_fight()` always created both fighters with the `humanoid` preset, `PRESETS` only registered `humanoid`, and fighter config only loaded class/loadout/environment. Resolved by configured custom anatomy profiles, opt-in match-start generated fighter profiles, and deterministic creativity-gate tests proving non-humanoid parts survive into state, prompts, judge payloads, and combat-log snapshots.
- Impact: Dragons, winged fighters, tentacles, extra heads, non-humanoid organs, and asymmetric bodies can only exist as prose. Judge deltas targeting those parts are ignored as nonexistent.
- Suggested fix: Add a structured fighter profile/anatomy source, pass fighter-specific anatomy into state creation, and serialize that anatomy into fighter/judge prompts as authoritative valid parts.
- Tests: Added config/profile tests for custom body parts, simulation tests proving fighter-specific anatomy is used, state tests proving damage to configured custom parts applies, generated-profile tests, and creativity-gate tests for non-humanoid anatomy persistence.

### ISSUE-002: Creative/custom effects have no general mechanics

- Status: resolved
- Task: TODO.md - Declarative Dynamic Effect Mechanics
- Source: codebase review
- Area: Gameplay systems, dynamic effects
- Evidence: `apply_effects()` only handles `burning` and `bleeding` in `src/llm_fight/state.py:360`; `EFFECT_STUNNED` exists but has no handler in `src/llm_fight/engine/constants.py:57`; poison is normalized to generic damage in `src/llm_fight/state.py:58`.
- Impact: Poison, blindness, stun, entanglement, fear, corrosion, freezing, and similar effects may persist by name but do not affect stats, targeting, action validity, probabilities, or available actions.
- Suggested fix: Introduce a safe effect-mechanics contract or registry: tick damage, stat modifiers, action blockers, targeting/visibility penalties, body-part damage, and narrative-only fallback.
- Tests: Add poison DOT, blinded targeting penalty, stunned action restriction, custom safe-mechanic effects, and unknown narrative-only effect behavior. Verified with `uv run pytest -q tests/test_validation.py tests/test_state.py tests/test_simulation.py tests/test_simulation_probabilities.py tests/engine/test_fighter.py tests/engine/test_judge.py tests/engine/test_prompts.py` and `uv run pytest -q`.

## P1

### ISSUE-003: Judge P2 deltas can bypass validity and dice rolls

- Status: resolved
- Task: TODO.md - P2 Authorization And Terminal Outcome Gate
- Source: codebase review
- Area: Security, simulation correctness
- Evidence: P2 receives `successful_rolls` in `src/llm_fight/simulation.py:157`, but returned deltas are applied directly at `src/llm_fight/simulation.py:171`. `_clear_invalid_turn_result()` only clears the narrow case where both attempts are invalid and both rolls failed in `src/llm_fight/simulation.py:55`.
- Impact: A failed roll, invalid single action, or prompt-injected fighter action can still produce wounds, effects, status changes, `fight_end`, and `winner` if the judge ignores prompt instructions.
- Suggested fix: Add deterministic post-P2 authorization before `apply_delta()`. At minimum, make no successful rolls mean no delta/end/winner. For mixed success, add source attribution to deltas and drop consequences from invalid/failed actions.
- Tests: Stub both attempts as valid with rolls false, return P2 damage/status/winner, and assert no state mutation and no fight end. Mixed success/failure coverage verifies only authorized sourced consequences apply. Verified with `uv run pytest -q tests/test_validation.py tests/test_simulation.py tests/test_simulation_integration.py tests/test_simulation_probabilities.py tests/engine/test_judge.py tests/engine/test_prompts.py` and `uv run pytest -q`.

### ISSUE-004: Judge-only winners can end fights without terminal state

- Status: resolved
- Task: TODO.md - P2 Authorization And Terminal Outcome Gate
- Source: codebase review
- Area: Simulation correctness
- Evidence: `_judge_outcome()` accepts `fight_end=true, winner="A"` in `src/llm_fight/simulation.py:30`; `_single_fight()` accepts judge outcome when `_status_outcome()` is `None` in `src/llm_fight/simulation.py:197`.
- Impact: A malformed or overconfident judge result can award a winner while both fighters remain `fighting`.
- Suggested fix: Treat post-delta state as authoritative for combat outcomes. Only accept judge-only endings with a structured, Python-verifiable terminal reason.
- Tests: P2 returns empty delta, both fighters remain fighting, `fight_end=true`, `winner=A` or `winner=null`; the fight continues until normal max-turn resolution. Verified with `uv run pytest -q tests/test_validation.py tests/test_simulation.py tests/test_simulation_integration.py tests/test_simulation_probabilities.py tests/engine/test_judge.py tests/engine/test_prompts.py` and `uv run pytest -q`.

### ISSUE-005: Unvalidated effect payloads can crash, inject prompts, or become permanent junk state

- Status: resolved
- Task: TODO.md - Effect Payload Safety Gate
- Source: codebase review
- Area: Security, validation, effects
- Evidence: `effects_added` accepts any object in `src/llm_fight/validation.py:78`; `apply_delta()` trusts raw `name`, `value`/`magnitude`, `ttl`, `on_apply`, `on_tick`, and `metadata` in `src/llm_fight/state.py:321`; active effect names are replayed into prompts in `src/llm_fight/engine/fighter.py:107` and `src/llm_fight/judge.py:82`. Playtest loop `transcripts\playtest_loop_20260512_010010` ran 34 `uv run llmfight play` attempts over 614.1 seconds; runs 12, 13, and 20 crashed with `TypeError: '>' not supported between instances of 'NoneType' and 'int'` at `Effect.tick()` in `src/llm_fight/state.py:77` after `apply_effects()`.
- Impact: Schema-valid effects can crash ticking with non-integer TTLs, reduce stats with negative magnitudes, persist instruction-like names with `ttl=-1`, or silently become permanent inert typo-effects.
- Suggested fix: Add strict `EffectSchema` plus defensive runtime validation: safe identifier/name length, bounded positive magnitude, `ttl == -1 or ttl >= 1` with max, known type enum, limited metadata keys, `additionalProperties: false`.
- Tests: Reject missing name, non-integer TTL, `ttl=0`, `ttl<-1`, negative magnitude, oversized/instruction-like names, non-object metadata, and unknown properties. Add integration coverage that rejected effects do not reach next prompts.

### ISSUE-006: Newly created effects tick and expire before the next turn can observe them

- Status: resolved
- Task: TODO.md - Effect Creation Turn Boundary
- Source: codebase review
- Area: Gameplay logic, effect timing
- Evidence: `_single_fight()` applies deltas, then immediately calls `apply_effects()` in `src/llm_fight/simulation.py:171`; `Effect.tick()` removes `ttl=1` effects in `src/llm_fight/state.py:395`.
- Impact: A `ttl=1` stun/blind/burn/bleed created this turn disappears before the next fighter or judge prompt sees it. Burning and bleeding can also add same-turn consequences not described by P2.
- Suggested fix: Define TTL semantics explicitly. Tick pre-existing effects at turn start, or mark created-turn effects and skip their first tick.
- Tests: P2 adds `stunned` with `ttl=1` on turn 1; turn 2 fighter/judge context still includes it before the first eligible tick, then it expires after that tick. Burning coverage verifies wound-created burn skips same-turn mechanics while pre-existing targeted burn still ticks. Verified with `uv run pytest -q tests/test_state.py tests/test_simulation.py tests/engine/test_fighter.py tests/engine/test_judge.py` and `uv run pytest -q`.

### ISSUE-007: Damaging severed/destroyed parts bypasses status invariants

- Status: resolved
- Task: TODO.md - Status Invariants And Monotonic Status Changes
- Source: codebase review
- Area: State invariants
- Evidence: The severed/destroyed branch in `src/llm_fight/state.py:195` adds pain at line 198 and returns without `_update_status_from_invariants()`.
- Impact: A fighter can exceed unconscious/death pain thresholds and remain `FIGHTING` until some later mutation happens to re-run invariants.
- Suggested fix: Call `_update_status_from_invariants()` before returning from every state-mutating path, or route all stat mutations through invariant-enforcing helpers.
- Tests: Sever a limb, hit it again enough to cross `MAX_PAIN_BEFORE_DEATH`, and assert status becomes `DEAD`. Repeat for destroyed non-severable parts.

### ISSUE-008: Oversized prompts degrade into 1-token generations

- Status: resolved
- Task: TODO.md - Prompt Budget Guardrails And Context Trimming
- Source: codebase review
- Area: LLM transport, reliability
- Evidence: `compute_completion_tokens()` clamped over-budget prompts to at least `1`; default `judge_log_window` is `9999`. Resolved with strict `PromptBudgetError`, phase-specific completion reserves, deterministic newest-first combat-log trimming, P2 repair budget recomputation, and generated-profile budget fallback safety.
- Impact: Long fights can silently exceed context, then ask the model for a 1-token JSON completion. This causes empty/truncated JSON, retry storms, and no-op P2 turns instead of a clear budget error.
- Suggested fix: Reserve minimum completion budgets per call type, trim/summarize logs before calling the model, and raise a typed prompt-budget error when prompt tokens exceed `num_ctx - reserved_completion`.
- Tests: Added token helper tests, fighter over-budget/no-chat and newest-first trim tests, Judge P1/P2 trim tests, P2 repair budget propagation/no-second-chat coverage, CLI actionable error coverage, generated-profile budget fallback coverage, and full-suite verification.

### ISSUE-009: Global RNG makes concurrent batch runs non-reproducible

- Status: resolved
- Task: TODO.md - Per-Fight RNG For Concurrent Batch Runs
- Source: codebase review
- Area: Simulation correctness, reproducibility
- Evidence: `run_batch()` seeds one module-global RNG in `src/llm_fight/simulation.py:243`, then starts concurrent `_single_fight()` tasks at `src/llm_fight/simulation.py:267`; rolls consume global `rand()` after async waits.
- Impact: Same seed can produce different per-run outcomes depending on async scheduling and model latency.
- Suggested fix: Give each fight an isolated RNG derived from `(batch_seed, run_index)` and pass it through dice resolution and effect ticking.
- Tests: Run a deterministic concurrent batch twice with varied fake async delays and assert identical ordered CSV rows. Verified with `uv run pytest -q tests/test_state.py tests/test_simulation.py tests/test_simulation_integration.py tests/test_simulation_failures.py tests/test_rng.py`.

### ISSUE-010: Invalid batch concurrency can hang forever

- Status: resolved
- Task: TODO.md - Batch Config Validation And Failure Exit Semantics
- Source: codebase review
- Area: CLI/config reliability
- Evidence: `run_batch()` reads `concurrent_runs` in `src/llm_fight/simulation.py:245` and constructs `asyncio.Semaphore(concurrency)` at line 248. With `0`, tasks block forever.
- Impact: A single bad config can make `llmfight simulate` appear frozen.
- Suggested fix: Validate `runs >= 0` and `concurrent_runs >= 1` in `run_batch()` and at the CLI boundary.
- Tests: Config values `concurrent_runs=0` and `-1` fail fast with a clear exception and do not start `_single_fight`. CLI config validation now happens before `ping_ollama()`. Verified with `uv run pytest -q tests/test_cli.py tests/test_simulation.py tests/test_simulation_failures.py tests/test_render.py` and `uv run pytest -q`.

### ISSUE-011: `llmfight play` is silent until the whole fight finishes

- Status: resolved
- Task: TODO.md - Terminal Fight Startup And Progress Feedback
- Source: codebase review
- Area: UX, terminal rendering
- Evidence: `play` awaited `_single_fight(... return_log=True)`, then printed all turn tables afterward. Playtest loop `transcripts\playtest_loop_20260512_010010` captured non-crashing runs where the first visible output line was `Turn 1`, with no pre-fight fighter design view or progress/status surface before the turn table. Resolved with play events, pre-fight fighter design rendering, phase status output, and streamed turn rendering.
- Impact: Slow local LLM runs look frozen for the full fight.
- Suggested fix: Add an `on_turn` callback or async event stream, render each turn as it completes, and show Rich status/spinners for fighter/judge phases.
- Tests: Added CLI/event tests proving generated-profile status appears before fighter designs, fighter designs appear before the first turn, token summaries render from real metadata, and turns are not duplicated.

### ISSUE-012: Prompt payloads can leak through error logs and proxies

- Status: resolved
- Task: TODO.md - Transport Privacy And Endpoint Mode Safety
- Source: codebase review
- Area: Security, privacy
- Evidence: `_post_json()` previously logged `Payload: {payload}` on retry/failure paths in `src/llm_fight/agents.py`; chat and ping previously used unconditional `ClientSession(trust_env=True)`. Resolved by redacted transport log metadata, endpoint-aware proxy policy, shared chat/ping endpoint resolution, and default loopback `trust_env=False` unless `ollama_proxy_mode = enabled`.
- Impact: Transient API failures can dump prompts, combat state, and user scenario text into logs. Local-first users with `HTTP_PROXY` and no `NO_PROXY` can also send prompt bodies through environment proxies.
- Suggested fix: Redact logs to endpoint/model/message counts/token sizes/request id. Default `trust_env=False` for loopback/local endpoints and add explicit proxy opt-in.
- Tests: Added transport failure coverage for 5xx, client error, timeout, and unexpected exception with sentinel prompt text; captured logs omit raw messages, payloads, userinfo, and query strings. Added proxy-mode tests for localhost, `127.x.x.x`, `[::1]`, remote auto, explicit enabled, explicit disabled, and chat/ping `ClientSession(trust_env=...)`.

## P2

### ISSUE-013: P2 target validity is prompt-only

- Status: resolved
- Task: TODO.md - P2 Target Validation Gate
- Source: codebase review
- Area: Validation, gameplay state
- Evidence: `targeted_part` was any string in the static Phase 2 schema; valid target parts were only sent as prompt/input context; unknown parts were warned and ignored later in `apply_damage_to_part()`. Resolved by post-Phase-2 target validation in `simulation.py` that runs after source authorization and before combat-log storage/state application, using the target fighter's canonical anatomy.
- Impact: Narration can describe decisive damage to `neck`, `shoulder`, or `wing` while Python applies no damage.
- Suggested fix: Post-validate P2 deltas against each target fighter's canonical/alias-normalized valid parts before applying. Reject or sanitize invalid wounds.
- Tests: Added simulation coverage for invalid humanoid targets plus terminal claims, alias canonicalization from `neck` to `head`, mixed valid/invalid wounds, invalid-target narration not reaching later prompt summaries, and custom-anatomy ownership where `wing` is valid only for a fighter that actually owns it.

### ISSUE-014: Fighter prompts omit opponent state, anatomy, and effect metadata

- Status: resolved
- Task: TODO.md - Prompt State Context And Environment-Scoped Creativity
- Source: codebase review
- Area: Prompts, gameplay quality
- Evidence: Fighter prompt generation includes acting fighter pain/exhaustion/heat/effect names/loadout in `src/llm_fight/engine/fighter.py:104`; the user prompt only says opponent is visible in `src/llm_fight/engine/fighter.py:147`.
- Impact: Fighters cannot intentionally exploit injuries, target supported anatomy, react to effect TTL/severity, or make informed creative decisions.
- Suggested fix: Add compact self/opponent summaries: class, loadout, status, pain/exhaustion/heat bands, valid target parts, damaged/severed parts, and active effects with TTL/magnitude/target.
- Resolution: Fighter prompts now include shared compact self/opponent JSON summaries with loadout, status, anatomy metadata, damaged/severed parts, and structured active effects, while preserving current-state authority over recent narration.
- Tests: Shared summary, fighter prompt, judge prompt, creativity-gate, and full suite verification passed: `uv run pytest -q` -> 428 passed, 6 skipped, 1 warning.

### ISSUE-015: Judge Phase 1 drops partial injury and effect details

- Status: resolved
- Task: TODO.md - Prompt State Context And Environment-Scoped Creativity
- Source: codebase review
- Area: Prompts, judge quality
- Evidence: `_fighter_summary()` returns effect names only in `src/llm_fight/judge.py:82`; `_damaged_parts()` only reports non-intact/severed/fully depleted layers in `src/llm_fight/judge.py:54`.
- Impact: P1 probability/validity cannot account for poison strength, burn target, partial arm damage, damaged eyes, or custom part durability.
- Suggested fix: Include effect objects and coarse anatomy health bands, vital/severable flags, and partial-damage summaries.
- Resolution: Judge Phase 1 now reuses the shared compact summary contract, including structured `active_effects`, `valid_target_parts`, shallow `target_parts`, and partial `damaged_parts`.
- Tests: Judge P1 tests cover partial layer damage plus structured effect type/TTL/magnitude/target/mechanics/tags; full suite verification passed: `uv run pytest -q` -> 428 passed, 6 skipped, 1 warning.

### ISSUE-016: Default humanoid bleed/burn anatomy is mostly inert

- Status: resolved
- Task: TODO.md - Anatomy-Driven Bleeding, Burning, And Layer Accuracy
- Source: codebase review
- Area: Gameplay mechanics
- Evidence: `BodyPart.bleed_rate` and `burn_rate` default to `0` in `src/llm_fight/anatomy.py:24`; `compose_humanoid()` never sets them; bleeding only auto-creates when `part.bleed_rate > 0` in `src/llm_fight/state.py:268`; burn ticking ignores `burn_rate`.
- Impact: Piercing/slashing default humanoid parts do not automatically bleed, despite README claims. Burn susceptibility cannot be tuned by anatomy.
- Suggested fix: Set intentional preset bleed/burn values or remove the fields and rely on judge-created effects. If retained, use them in creation/ticking.
- Resolution: Humanoid presets now define explicit blood-bearing `bleed_rate` values and baseline `burn_rate=1`; burn ticks scale by `max(1, int(effect_magnitude * max(1, burn_rate)))` while preserving baseline behavior for omitted/custom `burn_rate=0`.
- Tests: Default piercing/slashing creates targeted bleeding without fixture mutation; zero-bleed eye does not auto-bleed; high-burn-rate parts burn harder; full suite verification passed: `uv run pytest -q` -> 405 passed, 6 skipped, 1 warning.

### ISSUE-017: Vital-part consequences are too coarse

- Status: resolved
- Task: TODO.md - Layer Health And Anatomy Consequence Policies
- Source: codebase review
- Area: Gameplay mechanics
- Evidence: Death by anatomy requires all vital parts destroyed in `src/llm_fight/state.py:166`; one destroyed vital only causes unconsciousness in `src/llm_fight/state.py:171`; heart/head/torso are all `is_vital` in `src/llm_fight/anatomy.py:47`.
- Impact: Destroying the heart or head is treated as unconsciousness unless every vital part is destroyed, which weakens organ-specific combat logic.
- Suggested fix: Replace direct `is_vital` status logic with explicit consequence tags/policies such as `fatal_if_destroyed`, `incapacitating_if_destroyed`, `vision_member`, and `mobility_member`.
- Resolution: `src/llm_fight/anatomy.py` now gives humanoid parts explicit consequence tags/groups, `src/llm_fight/profiles.py` translates legacy custom-profile `is_vital` declarations into explicit policies, and `src/llm_fight/state.py` applies those policies for fatal, incapacitating, vision, and mobility consequences.
- Tests: Heart/head fatal, torso incapacitating, one-eye/both-eye, one-leg/both-leg, legacy multi-vital, explicit custom consequence tags, group/tag validation, and full suite verification passed: `uv run pytest -q` -> 401 passed, 6 skipped, 1 warning.

### ISSUE-018: Effect removal is name-only and cannot target one wound

- Status: resolved
- Task: TODO.md - Targeted Effect Removal And Effect Identity
- Source: codebase review
- Area: Effects
- Evidence: `effects_removed` is an array of strings in `src/llm_fight/validation.py:79`; `apply_delta()` removes every buff/debuff with matching name in `src/llm_fight/state.py:337`.
- Impact: Removing `bleeding` from one treated part removes all bleeding effects. Extinguishing one burning limb clears all burning effects.
- Suggested fix: Use structured removals `{name, type, targeted_part}` or stable effect IDs. Keep name-only removal only as explicit remove-all behavior.
- Resolution: Judge-facing removals now use source-bearing `{source, name, type?, targeted_part?}` selectors; Phase 2 authorization preserves and canonicalizes selector fields; runtime state mutation supports selector matching plus legacy string remove-all compatibility.
- Tests: Validation covers structured removals and rejects source-less judge strings/unsafe payloads; state tests cover targeted bleeding/burning removal, type narrowing, untargeted preservation, legacy remove-all, and malformed skip behavior; simulation tests cover authorization/canonicalization/drop warnings, unauthorized invalid-target sanitization, and terminal suppression; property tests cover structured removals; full suite verification passed: `uv run pytest -q` -> 423 passed, 6 skipped, 1 warning.

### ISSUE-019: Judge deltas can revive terminal fighters

- Status: resolved
- Task: TODO.md - Status Invariants And Monotonic Status Changes
- Source: codebase review
- Area: State invariants
- Evidence: `status_change` accepts all fighter statuses in `src/llm_fight/validation.py:80`; `apply_delta()` assigns the new status directly in `src/llm_fight/state.py:344`.
- Impact: A judge can transition `DEAD -> FIGHTING` or `UNCONSCIOUS -> FIGHTING` without an explicit recovery mechanic.
- Suggested fix: Make status transitions monotonic by default and require a separate explicit recovery/resurrection system for downgrades.
- Tests: Add state tests rejecting `DEAD -> FIGHTING` and `UNCONSCIOUS -> FIGHTING`.

### ISSUE-020: Tissue `max_hp` is used as current HP

- Status: resolved
- Task: TODO.md - Layer Health And Anatomy Consequence Policies
- Source: codebase review
- Area: State model
- Evidence: `TissueLayer` only has `max_hp` in `src/llm_fight/anatomy.py:11`; damage subtracts from it in `src/llm_fight/state.py:205`; `CURRENT_HP` exists but is unused in `src/llm_fight/engine/constants.py:20`.
- Impact: Original durability is lost, making healing, percentage summaries, balancing, and dynamic anatomy harder.
- Suggested fix: Add `current_hp`, initialize it from `max_hp`, and mutate only `current_hp`.
- Resolution: `TissueLayer` now initializes `current_hp == max_hp`; damage, destruction, severing, burn ticks, property tests, and judge damaged-layer summaries use `current_hp` while preserving `max_hp`.
- Tests: Damage lowers `current_hp` while `max_hp` stays stable; overkill clamps to zero; serialization and judge summaries preserve both values; property tests check `current_hp` monotonicity and `max_hp` stability; full suite verification passed: `uv run pytest -q` -> 401 passed, 6 skipped, 1 warning.

### ISSUE-021: Combat state changes are mostly hidden in terminal output

- Status: resolved
- Task: TODO.md - Turn Diff And Roll Transparency
- Source: codebase review
- Area: UX, rendering
- Evidence: `CombatTurn` stores before/after state, but `status_changes_text()` only reports status changes in `src/llm_fight/engine/combat_log.py:47`; render only adds that row in `src/llm_fight/engine/render.py:49`.
- Impact: Pain, exhaustion, heat, wounds, effects, and part damage usually exist only in prose, making mechanics hard to inspect.
- Suggested fix: Render a turn diff: stat deltas, wounds by part, effects added/removed/expired, and final fighter state.
- Resolution: `CombatTurn` now derives display diffs from actual before/after state snapshots after authorized deltas and effect ticks, including stats, wounds, body-part layer HP/status/severing, effect add/remove/update, status changes, and explicit no-op turns.
- Tests: Combat-log/render/CLI/simulation coverage verifies stat, wound, body-part, effect, status, no-op, and streamed output visibility; full suite verification passed: `uv run pytest -q` -> 432 passed, 6 skipped, 1 warning.

### ISSUE-022: Roll outcomes are not visible to players

- Status: resolved
- Task: TODO.md - Turn Diff And Roll Transparency
- Source: codebase review
- Area: UX, transparency
- Evidence: `rolls` is computed in `src/llm_fight/simulation.py:116` and passed to P2, but `CombatTurn` has no field for it in `src/llm_fight/engine/combat_log.py:12`.
- Impact: Users see success probabilities but not whether each action actually succeeded.
- Suggested fix: Store `successful_rolls` and optionally raw roll values on `CombatTurn`; render a compact success/failure row.
- Resolution: Simulation now stores per-fighter roll metadata on `CombatTurn`, including validity, probability text/value, raw roll when attempted, success flag, and reason; rich/simple output renders success, failure, invalid/not-rolled, and invalid-probability states.
- Tests: Simulation asserts stored roll metadata without extra RNG calls; combat-log/render/CLI tests prove rolls appear in rich and simple output; full suite verification passed: `uv run pytest -q` -> 432 passed, 6 skipped, 1 warning.

### ISSUE-023: Token/model-call metadata is discarded

- Status: resolved
- Task: TODO.md - Terminal Fight Startup And Progress Feedback
- Source: codebase review
- Area: LLM transport, UX
- Evidence: `_post_json()` parsed the full response but returned only content; `chat()` returned `list[str]`. Resolved by adding `ChatResult` and `chat_with_metadata()` while preserving `chat() -> list[str]` compatibility, extracting native Ollama and OpenAI-compatible token metadata, and surfacing summaries in `llmfight play` when metadata exists.
- Impact: The app cannot show prompt/completion tokens, done reasons, load/eval durations, context pressure, or truncation warnings.
- Suggested fix: Return a typed call result with content plus model/options/token/duration metadata; log/transcript and render it when useful.
- Tests: Mocked native Ollama and OpenAI-compatible metadata extraction, token-summary formatting, CLI token display, and missing-token fallback.

### ISSUE-024: P2 failures are hidden as normal no-op turns

- Status: resolved
- Task: TODO.md - P2 Fallback Visibility And Fail-Open Policy
- Source: codebase review
- Area: Reliability, observability
- Evidence: Judge Phase 2 caught repeated parse failures and returned `_phase2_noop_result()` as an indistinguishable normal no-op. Resolved by engine-owned fallback metadata, visible turn markers, batch fallback CSV/summary accounting, and configurable `judge_phase2_failure_policy = fail_open | fail_closed`.
- Impact: Runs can appear successful while the judge is repeatedly failing.
- Suggested fix: Return explicit `fallback_used`/`llm_error` metadata, surface it in play/batch output, and make fail-open configurable.
- Tests: Added Judge Phase 2 fail-open/fail-closed tests, metadata stripping for LLM-supplied fallback fields, combat-log/render marker tests, single-fight fallback result counting, batch CSV/summary fallback accounting, fail-closed batch error-row coverage, and CLI actionable fail-closed error coverage.

### ISSUE-025: Batch simulations can hide total failure behind exit 0

- Status: resolved
- Task: TODO.md - Batch Config Validation And Failure Exit Semantics
- Source: codebase review
- Area: CLI reliability
- Evidence: `run_batch()` catches exceptions and returns `{winner: "error"}` in `src/llm_fight/simulation.py:252`; CLI prints `Simulation saved to ...` in `src/llm_fight/cli.py:174`.
- Impact: CI/scripts can treat a fully failed batch as success unless they parse the CSV.
- Suggested fix: Track error rows and return nonzero from CLI unless `--continue-on-error` is set.
- Tests: `_single_fight` raises for every run; CLI exits nonzero with an actionable summary. Mixed success/error rows also exit nonzero unless `--continue-on-error` is set. Verified with `uv run pytest -q tests/test_cli.py tests/test_simulation.py tests/test_simulation_failures.py tests/test_render.py` and `uv run pytest -q`.

### ISSUE-026: Transcripts are raw exchange fragments, not fight traces

- Status: resolved
- Task: TODO.md - Fight-Scoped JSONL Trace Transcripts
- Source: codebase review
- Area: Observability, transcripts
- Evidence: `log_exchange()` writes one timestamped prompt/response fragment in `src/llm_fight/transcripts.py:31`; it has no fight id, turn, phase, rolls, deltas, state snapshots, token metrics, or outcome.
- Impact: Transcripts are hard to read, replay, or debug after a session.
- Suggested fix: Write one fight-scoped JSONL trace with ordered events: fighter configs, prompts/responses, rolls, deltas, states, token/latency metrics, and final result.
- Resolution: `save_transcripts = true` now creates one fight-scoped JSONL trace per fight with ordered event indexes, fight/run identity, lifecycle events, active fighter/judge `llm_exchange` events, token metadata, rolls, deltas, before/after state snapshots, sanitized failure events, and final results. Legacy per-exchange JSON fragments remain only for direct non-fight `log_exchange()` callers.
- Tests: Transcript, simulation, batch concurrency, generated-profile redaction, agent logging, and CLI tests cover trace event order, disabled mode, wrapper compatibility, no legacy fight fragments, failure persistence, cancelled sibling task draining, token metadata, roll/delta/state snapshots, and profile text redaction; full suite verification passed: `uv run pytest -q` -> 439 passed, 6 skipped, 1 warning.

### ISSUE-027: Example fighter names are ignored

- Status: resolved
- Task: TODO.md - Configured Fighter Display Names
- Source: codebase review
- Area: Config, UX
- Evidence: `llmfight.ini.example` defines `name` at `llmfight.ini.example:39`, but `get_fighter_settings()` returns only class/loadout/environment in `src/llm_fight/config.py:161`; prompts use `fighter.id` in `src/llm_fight/engine/fighter.py:129`.
- Impact: Users can edit the obvious identity field and see no effect in prompts, transcripts, or output.
- Suggested fix: Implement `display_name`/`name` through config, state, prompts, rendering, and winner output, or remove unsupported example keys.
- Resolution: Config `name` now flows into `FighterState.display_name` for preset, config-profile, and generated-profile paths while stable `id`, delta keys, `fighter_id`, and `winner` remain `A`/`B`. Prompts, compact state summaries, pre-fight render output, turn render labels, JSONL trace state, CLI winner output, and batch CSV metadata expose display names without replacing machine ids.
- Tests: Config fallback, state/profile creation, prompt wording, render labels, CLI winner output, trace/state persistence, and batch CSV display columns cover configured and missing names. Verification passed: `uv run black --check .`, `uv run flake8`, focused tests (`273 passed, 1 warning`), `uv run pytest -q` (`446 passed, 6 skipped, 1 warning`), and `git diff --check`.

### ISSUE-028: Config and RNG rely on process-global state

- Status: resolved
- Task: TODO.md - Runtime Config And RNG Isolation
- Source: codebase review
- Area: Best practices, reproducibility
- Evidence: `CONFIG = Config()` loaded at import time, CLI config loading/replacement and CLI overrides mutated `config_mod.CONFIG` for the process, and `rng.py` seeded the process RNG from whatever config was active at module import. Resolved by `config.use_config()` for temporary programmatic config ownership, `_command_runtime()` in `cli.py` for per-command scoped config/override activation, and `rng.seed_from_config()` plus RNG state save/restore around CLI entry points.
- Impact: CLI invocations in one process can leak config/overrides, and seeds loaded after import may not affect programmatic `play` unless callers remember to reseed.
- Suggested fix: Pass a scoped `Config`/runtime context through simulation and LLM calls, or restore globals in `finally`. Initialize RNG explicitly at entry points.
- Tests: Added CLI success/failure scoping tests, CLI override non-leakage coverage, RNG import-order/seed-from-config coverage, programmatic scoped-config coverage, and design-doc notes. Verified with `uv run pytest -q tests\test_config.py tests\test_rng.py tests\test_rng_seed_import.py tests\test_cli.py tests\test_simulation.py` -> 120 passed, 1 warning; `uv run black --check .`; `uv run flake8`; `uv run pytest -q` -> 454 passed, 6 skipped, 1 warning; `git diff --check`.

### ISSUE-038: GitHub CI fails on Rich/Typer-rendered negative `--runs` output

- Status: resolved
- Task: none
- Source: implementation review
- Area: CI, test reliability, CLI error handling
- Evidence: GitHub Actions run `25747989892`, job `75616361118`, failed only in `uv run pytest -q --cov=llm_fight` on Ubuntu 24.04 / Python 3.14.4. Formatting and lint passed. The single failing test was `tests/test_cli.py::test_cli_simulate_negative_runs_override_fails_before_ping`, where `tests/test_cli.py:653` asserts the plain string `--runs must be 0 or greater` is present in `result.output`. CI captured a Rich/ANSI error panel without that contiguous plain message, while a Windows temp-copy reproduction of the same locked command passed with `446 passed, 6 skipped, 1 warning`.
- Impact: `main` CI is red even though the CLI behavior appears correct: `src/llm_fight/cli.py` rejects negative `--runs` before `ping_ollama()`. Future CLI error tests can also become platform-dependent if they assert directly against styled Rich/Typer output.
- Suggested fix: Make CLI output assertions platform-stable by normalizing captured output in tests, such as stripping ANSI control sequences and/or disabling color for `CliRunner` invocations that assert error text. Prefer a shared helper so future Rich/Typer assertions use the same path.
- Resolution: `tests/test_cli.py` now normalizes captured CLI output through Click's `unstyle()` and whitespace collapse before asserting the negative `--runs` validation text, preserving the existing pre-ping behavior assertion.
- Tests: Re-run `uv run pytest -q --cov=llm_fight` locally and in GitHub Actions. Add or update focused coverage proving `simulate --runs -1` exits nonzero, reports the validation message after normalization, and does not await `ping_ollama()`.

### ISSUE-039: Core simulation/state and large test files are monolithic

- Status: resolved
- Task: TODO.md - State Effect Lifecycle Extraction And State Test Split; Simulation And Phase 2 Test Shard Split; Single Fight Loop Orchestration Extraction; Agents And CLI Test Shard Split; ISSUE-039 Closure Measurement
- Source: codebase review
- Area: Maintainability, AI-agent ergonomics
- Evidence: Code-size review found `src/llm_fight/simulation.py` at 1124 physical LOC with `_single_fight()` at 262 LOC / roughly 102 statements, `run_batch()` at 105 LOC, and `_authorize_fighter_delta()` near the function statement threshold; `src/llm_fight/state.py` at 948 physical LOC with `FighterState` spanning roughly 822 LOC. Test-suite review found `tests/test_simulation.py` at 2783 physical LOC, `tests/test_state.py` at 1200 physical LOC, and `tests/test_agents.py` at 818 physical LOC. This exceeded the `AGENTS.md` code-size issue thresholds for production and test modules; `simulation.py`, `tests/test_simulation.py`, and `tests/test_state.py` also exceeded the urgent 1000+ LOC threshold. First slice extracted Phase 2 authorization into `src/llm_fight/phase2_authorization.py`; second slice extracted the batch harness into `src/llm_fight/batch.py`. Interim measurements before the final ISSUE-039 slices were `simulation.py` 641 LOC with `_single_fight()` still about 265 LOC, `state.py` 953 LOC, `phase2_authorization.py` 375 LOC, `batch.py` 170 LOC, `tests/test_simulation.py` 1499 LOC, `tests/test_phase2_authorization.py` 808 LOC, `tests/test_batch.py` 700 LOC, `tests/test_simulation_failures.py` 39 LOC, `tests/test_state.py` 1202 LOC, `tests/test_agents.py` 819 LOC, and `tests/test_cli.py` 841 LOC. At that point, remaining pressure still applied to `state.py`, `_single_fight()`, `tests/test_simulation.py`, `tests/test_phase2_authorization.py`, `tests/test_state.py`, `tests/test_agents.py`, and `tests/test_cli.py`.
- Resolution: Closure measurement after the issue-backed slices found all ISSUE-039 production and test file thresholds satisfied. Final production measurements: `state.py` 597 LOC, `effects.py` 400 LOC, `simulation.py` 410 LOC, `fight_loop.py` 460 LOC, `phase2_authorization.py` 375 LOC, and `batch.py` 171 LOC; `_single_fight()` is 35 LOC. Final relevant test measurements: `tests/test_state.py` 669 LOC, `tests/test_state_effect_ticks.py` 366 LOC, `tests/test_state_effect_removal.py` 225 LOC, `tests/test_simulation.py` 545 LOC, `tests/test_simulation_trace.py` 415 LOC, `tests/test_simulation_turns.py` 621 LOC, `tests/test_batch.py` 700 LOC, `tests/test_simulation_failures.py` 40 LOC, `tests/test_phase2_authorization.py` 498 LOC, `tests/test_phase2_authorization_prompt_safety.py` 338 LOC, `tests/test_agents.py` 438 LOC, `tests/test_agents_endpoint.py` 219 LOC, `tests/test_agents_transport.py` 181 LOC, `tests/test_cli.py` 67 LOC, `tests/test_cli_play.py` 453 LOC, and `tests/test_cli_simulate.py` 334 LOC.
- Impact: Refactors and reviews require loading broad, mixed-responsibility files into context, which raises risk for missed behavior, duplicate logic, and harder AI-agent edits. The largest files mix orchestration, authorization, state mutation, effects, damage, batch handling, and trace/test concerns.
- Suggested fix: Split `simulation.py` into focused fight-loop, batch, event, and Phase 2 authorization modules; split `state.py` into fighter state/construction, effect mechanics, damage/anatomy mutation, and status invariant modules. Split large tests along matching behavior boundaries: simulation single-fight/profile/trace, batch/progress/CSV, modifiers/config, Phase 2 authorization/target sanitization; state damage/anatomy status, effect creation/ticking, dynamic mechanics/RNG, effect removal/status invariants; agents native payloads, OpenAI-compatible payloads, metadata extraction, retry/config, endpoint/proxy, ping health, and transport privacy.
- Tests: Preserve current behavior with focused extraction commits and run `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy src/llm_fight`, moved focused test files such as `uv run pytest -q tests/test_simulation.py tests/test_state.py tests/test_agents.py`, and `uv run pytest -q` after each slice.

### ISSUE-040: Standalone runtime functions exceed code-size thresholds

- Status: tasked
- Task: TODO.md - Single Fight Loop Orchestration Extraction; Fighter Attempt Prompt Pipeline; Judge Phase 2 Response Pipeline; CLI Play Rendering Helpers; CLI Simulate Batch Helpers; Fighter Profile Builder Extraction; ISSUE-040 Closure Measurement
- Source: codebase review
- Area: Maintainability, AI-agent ergonomics
- Evidence: Code-size review found production functions over the `AGENTS.md` 100+ LOC function threshold: `src/llm_fight/simulation.py::_single_fight()` at about 265 LOC, `src/llm_fight/engine/fighter.py::get_fighter_attempt()` at 144 LOC, `src/llm_fight/cli.py::play()` at 127 LOC, `src/llm_fight/judge.py::judge_phase2()` at 126 LOC, `src/llm_fight/cli.py::simulate()` at 118 LOC, and `src/llm_fight/profiles.py::build_fighter_profile()` at 109 LOC.
- Impact: These functions are not full monolithic modules, but each combines enough prompting, validation, rendering, command orchestration, or profile parsing behavior that small changes require reading a long mixed-responsibility block. That makes reviews and AI-agent edits more brittle.
- Suggested fix: Extract narrow helpers around stable seams: fighter prompt assembly and metadata handling from `get_fighter_attempt()`, CLI event/render/error branches from `play()` and `simulate()`, Phase 2 prompt/message preparation and response handling from `judge_phase2()`, and profile field/layer/body-part construction helpers from `build_fighter_profile()`.
- Tests: Preserve behavior with focused tests around each extraction target, then run `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy src/llm_fight`, relevant focused tests, and `uv run pytest -q`.

## P3

### ISSUE-029: Burn tick logs a random layer but damages the normal outer layer

- Status: resolved
- Task: TODO.md - Anatomy-Driven Bleeding, Burning, And Layer Accuracy
- Source: codebase review
- Area: Gameplay logging
- Evidence: `apply_effects()` chooses `random_layer_to_burn` for logging in `src/llm_fight/state.py:371`, then calls `apply_damage_to_part()`, whose loop starts at the first positive layer in `src/llm_fight/state.py:201`.
- Impact: Logs can say one tissue layer burned while another actually lost HP.
- Suggested fix: Remove random-layer logging or add targeted layer damage.
- Resolution: Burning ticks now mutate the selected active tissue layer directly, keep `max_hp` stable, preserve heat/pain/status side effects, and log the layer and HP that actually changed without creating duplicate burning effects.
- Tests: Fake-RNG multilayer burn asserts the selected last active layer is the mutated layer; caplog asserts the logged layer and HP match the mutation; duplicate-burning regression passed; full suite verification passed: `uv run pytest -q` -> 405 passed, 6 skipped, 1 warning.

### ISSUE-030: Environment guardrail can suppress explicit environment/equipment creativity

- Status: resolved
- Task: TODO.md - Prompt State Context And Environment-Scoped Creativity
- Source: codebase review
- Area: Prompts
- Evidence: Fighter prompt says not to invent walls, pillars, corridors, shadows, cover, terrain, or objects in `src/llm_fight/engine/prompts.py:17`.
- Impact: This helps for open arenas but conflicts with configured environments or equipment that explicitly includes cover, smoke, walls, or shadows.
- Suggested fix: Rephrase as "do not add new features unless they are in environment, equipment, active effects, or created by the current action."
- Resolution: Fighter prompts now allow features literally present in environment, equipment, active effects, durable state summaries, or the current action, while still forbidding unlisted cover, walls, pillars, smoke, shadows, terrain, or objects.
- Tests: Prompt tests cover open arena guardrails and explicit pillar/smoke/cover environments; full suite verification passed: `uv run pytest -q` -> 428 passed, 6 skipped, 1 warning.

### ISSUE-031: OpenAI-compatible endpoint support conflicts with native Ollama assumptions

- Status: resolved
- Task: TODO.md - Transport Privacy And Endpoint Mode Safety
- Source: codebase review
- Area: Transport, docs
- Evidence: `get_ollama_url()` accepted `/v1/chat/completions`, but `ping_ollama()` always checked `/api/tags`; `/v1` payloads necessarily omitted native `num_ctx`/`keep_alive` without surfacing that mode split. Resolved by endpoint mode detection, `/v1/models` health checks for OpenAI-compatible endpoints, native `/api/tags` health checks for native Ollama, and a once-per-endpoint warning when `/v1` ignores native Ollama settings.
- Impact: A compatible `/v1` endpoint can be rejected by CLI health checks or lose context/residency controls.
- Suggested fix: Split native and OpenAI-compatible health checks. Warn when `/v1` is used with native-only settings.
- Tests: Added `/v1/chat/completions` ping coverage proving the health probe uses `/v1/models`; added OpenAI-compatible payload tests proving native `options.num_ctx`, `keep_alive`, `think`, `stream`, and native `format` are omitted and the ignored-native-settings warning is emitted only once.

### ISSUE-032: Live/perf test gating and docs are inconsistent

- Status: resolved
- Task: TODO.md - Live/Perf Gating And Installed-Package Test Workflow
- Source: codebase review
- Area: Test workflow, docs
- Evidence: Live tests required `--run-live` in `tests/conftest.py:15`, but some tests also required `API_URL`; `tests/test_memory_usage.py:3` imported optional `ollama` at collection time; AGENTS live command could include heavy perf coverage while README omitted newer live simulation smoke. Resolved by centralizing `--run-live`, `API_URL`, and `--run-perf` collection gating, moving the optional `ollama` import behind a runtime skip, documenting quick live versus perf commands, and making CI use `uv sync --locked --dev`.
- Impact: `--run-live` can still skip useful smoke tests, accidentally run heavy VRAM probes, or fail collection without live extras.
- Suggested fix: Centralize live gating, move optional imports behind skips, split quick live smoke from perf, and document both.
- Tests: Added pytester coverage for live/perf marker gates. Verified `uv sync --locked --dev`, `uv run pytest -q tests\test_test_gating.py tests\test_packaging.py tests\test_memory_usage.py` -> 6 passed, 1 skipped, and `uv run llmfight --help` -> passed.

### ISSUE-033: Docs do not clearly state current fixed-humanoid/retry/progress contracts

- Status: resolved
- Task: TODO.md - Current Gameplay And Retry Contract Docs
- Source: codebase review
- Area: Documentation
- Evidence: Original review found README known limitations did not state the then-current anatomy/progress boundaries and troubleshooting suggested increasing `max_retries` without explaining capped Judge Phase 2 no-op fallback behavior. The anatomy and `play` progress contracts have since changed, so the resolved docs now state the current contract instead: custom anatomy is mechanical through configured/generated profiles only, prose-only concepts do not create targetable parts, `play` streams phase/completed-turn progress but not raw model tokens, and Judge Phase 2 retries are capped with fail-open no-op or fail-closed error behavior.
- Impact: Users may expect prose-only non-humanoid designs to create mechanics, unlimited retry recovery, or raw token-level streaming that the current app does not provide.
- Suggested fix: Add gameplay contract notes, retry/fallback contract notes, and current play-output behavior until the TODO items are implemented.
- Tests: Documentation-only change. Updated README Known Limitations, README Troubleshooting, and `docs/Design_doc.md` current gameplay contract notes.

### ISSUE-034: Logger setup is not library-friendly

- Status: resolved
- Task: TODO.md - Library-Friendly Logger Setup
- Source: codebase review
- Area: Best practices
- Evidence: Package logger attached a stdout `StreamHandler` at import in `src/llm_fight/engine/logger.py:13`, checked `hasHandlers()`, and left propagation behavior implicit. Resolved by installing only a direct `NullHandler` at import, checking `logger.handlers` directly, keeping propagation enabled for host applications, and wrapping CLI commands in a temporary stderr handler that restores the previous logger state afterward.
- Impact: Logs can mix with CLI stdout, be skipped under root handlers, or duplicate inside host applications.
- Suggested fix: Use `NullHandler` by default; configure CLI handlers to stderr; check `logger.handlers` directly and set propagation deliberately.
- Tests: Added reload/import/root-handler/duplicate-handler coverage plus CLI stderr routing coverage. Verified `uv run pytest -q tests\test_logger.py tests\engine\test_logger_handlers.py tests\test_cli.py` -> 42 passed, 1 warning; focused Ruff and mypy gates passed.

### ISSUE-035: Test suite bypasses installed package behavior

- Status: resolved
- Task: TODO.md - Live/Perf Gating And Installed-Package Test Workflow
- Source: codebase review
- Area: Test workflow
- Evidence: `tests/conftest.py:5` inserted `src` directly into `sys.path`. Resolved by removing manual path insertion, adding package import and installed `llmfight --help` smoke tests, and adding a CI console-script smoke step.
- Impact: Packaging metadata, console-script, or installed-resource regressions can pass tests.
- Suggested fix: Rely on editable install via `uv` and add packaging smoke checks.
- Tests: Added `tests/test_packaging.py` for import and installed console script coverage. Verified `uv sync --locked --dev`, `uv run pytest -q tests\test_test_gating.py tests\test_packaging.py tests\test_memory_usage.py` -> 6 passed, 1 skipped, and `uv run llmfight --help` -> passed.

## Resolved Playtest Issues

### ISSUE-036: Non-verbose interactive play duplicated engine turn logs

- Status: resolved
- Task: TODO.md - Gemma 4 26B Rich Play Loop
- Source: playtest
- Area: UX, terminal rendering
- Evidence: `uv run llmfight play --config playtest_gemma4_26b.ini` produced both plain engine turn logs and the rich turn table in `transcripts\gemma4_26b_playtest\rich_play_20260512_000858.out.log`.
- Impact: Non-verbose interactive play output was doubled and noisy.
- Suggested fix: Implemented by suppressing engine logs for non-verbose `play`; verified by `transcripts\gemma4_26b_playtest\rich_play_20260512_001054.out.log`.
- Tests: Covered by the completed `TODO.md - Gemma 4 26B Rich Play Loop` task and rich-output verification notes.

### ISSUE-037: Stale temporary effects from combat narration overrode current state

- Status: resolved
- Task: TODO.md - Gemma 4 26B Rich Play Loop
- Source: playtest
- Area: Prompts, gameplay state
- Evidence: In `transcripts\gemma4_26b_playtest\rich_play_20260512_001054.out.log` and matching JSON transcript `transcripts\gemma4_26b_playtest\20260512_001117_581884.json`, turn 4 had `debuffs: []` but prompts still treated earlier smoke narration as active.
- Impact: Expired or absent temporary effects could be resurrected by recent narration, causing fighters and judges to reason from stale state.
- Suggested fix: Implemented by making current active effects authoritative in fighter and judge prompts and adding a final `current_state_reminder` to judge payloads.
- Tests: Covered by prompt/judge tests and verified with `transcripts\gemma4_26b_playtest\rich_play_20260512_001652.out.log`.
