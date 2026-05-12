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

- Status: tasked
- Task: TODO.md - Prompt Budget Guardrails And Context Trimming
- Source: codebase review
- Area: LLM transport, reliability
- Evidence: `compute_completion_tokens()` clamps over-budget prompts to at least `1` in `src/llm_fight/utils/token_counter.py:57`; default `judge_log_window` is `9999`.
- Impact: Long fights can silently exceed context, then ask the model for a 1-token JSON completion. This causes empty/truncated JSON, retry storms, and no-op P2 turns instead of a clear budget error.
- Suggested fix: Reserve minimum completion budgets per call type, trim/summarize logs before calling the model, and raise a typed prompt-budget error when prompt tokens exceed `num_ctx - reserved_completion`.
- Tests: Over-budget fighter/judge prompts should not call `chat()`. Long combat logs should be trimmed while preserving a valid completion budget.

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

- Status: tasked
- Task: TODO.md - Terminal Fight Startup And Progress Feedback
- Source: codebase review
- Area: UX, terminal rendering
- Evidence: `play` awaits `_single_fight(... return_log=True)` at `src/llm_fight/cli.py:232`, then prints all turn tables afterward at `src/llm_fight/cli.py:240`. Playtest loop `transcripts\playtest_loop_20260512_010010` captured non-crashing runs where the first visible output line was `Turn 1`, with no pre-fight fighter design view or progress/status surface before the turn table.
- Impact: Slow local LLM runs look frozen for the full fight.
- Suggested fix: Add an `on_turn` callback or async event stream, render each turn as it completes, and show Rich status/spinners for fighter/judge phases.
- Tests: Fake a multi-turn fight/event stream and assert turn 1 renders before turn 2 completes.

### ISSUE-012: Prompt payloads can leak through error logs and proxies

- Status: tasked
- Task: TODO.md - Transport Privacy And Endpoint Mode Safety
- Source: codebase review
- Area: Security, privacy
- Evidence: `_post_json()` logs `Payload: {payload}` on retry/failure paths in `src/llm_fight/agents.py:147`, `154`, `159`, `166`, and `169`; `ClientSession(trust_env=True)` is used for chat and ping in `src/llm_fight/agents.py:111` and `242`.
- Impact: Transient API failures can dump prompts, combat state, and user scenario text into logs. Local-first users with `HTTP_PROXY` and no `NO_PROXY` can also send prompt bodies through environment proxies.
- Suggested fix: Redact logs to endpoint/model/message counts/token sizes/request id. Default `trust_env=False` for loopback/local endpoints and add explicit proxy opt-in.
- Tests: Force client/server/unexpected failures with sentinel secrets and assert logs do not contain raw messages. Test proxy env with localhost keeps proxy trust disabled unless opted in.

## P2

### ISSUE-013: P2 target validity is prompt-only

- Status: tasked
- Task: TODO.md - P2 Target Validation Gate
- Source: codebase review
- Area: Validation, gameplay state
- Evidence: `targeted_part` is any string in `src/llm_fight/validation.py:67`; valid target parts are only sent as prompt/input context in `src/llm_fight/simulation.py:150`; unknown parts are warned and ignored in `src/llm_fight/state.py:184`.
- Impact: Narration can describe decisive damage to `neck`, `shoulder`, or `wing` while Python applies no damage.
- Suggested fix: Post-validate P2 deltas against each target fighter's canonical/alias-normalized valid parts before applying. Reject or sanitize invalid wounds.
- Tests: P2 returns invalid `targeted_part` plus terminal result; assert invalid wound is rejected and no winner is accepted unless state becomes terminal.

### ISSUE-014: Fighter prompts omit opponent state, anatomy, and effect metadata

- Status: tasked
- Task: TODO.md - Prompt State Context And Environment-Scoped Creativity
- Source: codebase review
- Area: Prompts, gameplay quality
- Evidence: Fighter prompt generation includes acting fighter pain/exhaustion/heat/effect names/loadout in `src/llm_fight/engine/fighter.py:104`; the user prompt only says opponent is visible in `src/llm_fight/engine/fighter.py:147`.
- Impact: Fighters cannot intentionally exploit injuries, target supported anatomy, react to effect TTL/severity, or make informed creative decisions.
- Suggested fix: Add compact self/opponent summaries: class, loadout, status, pain/exhaustion/heat bands, valid target parts, damaged/severed parts, and active effects with TTL/magnitude/target.
- Tests: Prompt tests for opponent loadout, custom parts, severed limbs, eye damage, and targeted effect metadata.

### ISSUE-015: Judge Phase 1 drops partial injury and effect details

- Status: tasked
- Task: TODO.md - Prompt State Context And Environment-Scoped Creativity
- Source: codebase review
- Area: Prompts, judge quality
- Evidence: `_fighter_summary()` returns effect names only in `src/llm_fight/judge.py:82`; `_damaged_parts()` only reports non-intact/severed/fully depleted layers in `src/llm_fight/judge.py:54`.
- Impact: P1 probability/validity cannot account for poison strength, burn target, partial arm damage, damaged eyes, or custom part durability.
- Suggested fix: Include effect objects and coarse anatomy health bands, vital/severable flags, and partial-damage summaries.
- Tests: Damage a part partially and add a targeted effect; assert `judge_phase1()` payload includes both.

### ISSUE-016: Default humanoid bleed/burn anatomy is mostly inert

- Status: tasked
- Task: TODO.md - Anatomy-Driven Bleeding, Burning, And Layer Accuracy
- Source: codebase review
- Area: Gameplay mechanics
- Evidence: `BodyPart.bleed_rate` and `burn_rate` default to `0` in `src/llm_fight/anatomy.py:24`; `compose_humanoid()` never sets them; bleeding only auto-creates when `part.bleed_rate > 0` in `src/llm_fight/state.py:268`; burn ticking ignores `burn_rate`.
- Impact: Piercing/slashing default humanoid parts do not automatically bleed, despite README claims. Burn susceptibility cannot be tuned by anatomy.
- Suggested fix: Set intentional preset bleed/burn values or remove the fields and rely on judge-created effects. If retained, use them in creation/ticking.
- Tests: Default piercing/slashing creates bleeding on appropriate parts; custom high-burn-rate part burns harder.

### ISSUE-017: Vital-part consequences are too coarse

- Status: tasked
- Task: TODO.md - Layer Health And Anatomy Consequence Policies
- Source: codebase review
- Area: Gameplay mechanics
- Evidence: Death by anatomy requires all vital parts destroyed in `src/llm_fight/state.py:166`; one destroyed vital only causes unconsciousness in `src/llm_fight/state.py:171`; heart/head/torso are all `is_vital` in `src/llm_fight/anatomy.py:47`.
- Impact: Destroying the heart or head is treated as unconsciousness unless every vital part is destroyed, which weakens organ-specific combat logic.
- Suggested fix: Replace `is_vital` with consequence tags or policies such as `fatal_if_destroyed`, `incapacitating`, `vision`, `mobility`, `circulation`.
- Tests: Heart destruction, head destruction, single-eye/both-eye destruction, and leg destruction should assert the chosen consequences.

### ISSUE-018: Effect removal is name-only and cannot target one wound

- Status: tasked
- Task: TODO.md - Targeted Effect Removal And Effect Identity
- Source: codebase review
- Area: Effects
- Evidence: `effects_removed` is an array of strings in `src/llm_fight/validation.py:79`; `apply_delta()` removes every buff/debuff with matching name in `src/llm_fight/state.py:337`.
- Impact: Removing `bleeding` from one treated part removes all bleeding effects. Extinguishing one burning limb clears all burning effects.
- Suggested fix: Use structured removals `{name, type, targeted_part}` or stable effect IDs. Keep name-only removal only as explicit remove-all behavior.
- Tests: Two bleeding effects on different parts; remove one target and assert the other remains.

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

- Status: tasked
- Task: TODO.md - Layer Health And Anatomy Consequence Policies
- Source: codebase review
- Area: State model
- Evidence: `TissueLayer` only has `max_hp` in `src/llm_fight/anatomy.py:11`; damage subtracts from it in `src/llm_fight/state.py:205`; `CURRENT_HP` exists but is unused in `src/llm_fight/engine/constants.py:20`.
- Impact: Original durability is lost, making healing, percentage summaries, balancing, and dynamic anatomy harder.
- Suggested fix: Add `current_hp`, initialize it from `max_hp`, and mutate only `current_hp`.
- Tests: Damage lowers `current_hp` while `max_hp` stays stable; serialization preserves both.

### ISSUE-021: Combat state changes are mostly hidden in terminal output

- Status: tasked
- Task: TODO.md - Turn Diff And Roll Transparency
- Source: codebase review
- Area: UX, rendering
- Evidence: `CombatTurn` stores before/after state, but `status_changes_text()` only reports status changes in `src/llm_fight/engine/combat_log.py:47`; render only adds that row in `src/llm_fight/engine/render.py:49`.
- Impact: Pain, exhaustion, heat, wounds, effects, and part damage usually exist only in prose, making mechanics hard to inspect.
- Suggested fix: Render a turn diff: stat deltas, wounds by part, effects added/removed/expired, and final fighter state.
- Tests: Snapshot rich/simple output for wounds, stat changes, effects, and no-op turns.

### ISSUE-022: Roll outcomes are not visible to players

- Status: tasked
- Task: TODO.md - Turn Diff And Roll Transparency
- Source: codebase review
- Area: UX, transparency
- Evidence: `rolls` is computed in `src/llm_fight/simulation.py:116` and passed to P2, but `CombatTurn` has no field for it in `src/llm_fight/engine/combat_log.py:12`.
- Impact: Users see success probabilities but not whether each action actually succeeded.
- Suggested fix: Store `successful_rolls` and optionally raw roll values on `CombatTurn`; render a compact success/failure row.
- Tests: Simulation/render tests proving rolls appear in rich and simple output.

### ISSUE-023: Token/model-call metadata is discarded

- Status: tasked
- Task: TODO.md - Terminal Fight Startup And Progress Feedback
- Source: codebase review
- Area: LLM transport, UX
- Evidence: `_post_json()` parses the full response but returns only content in `src/llm_fight/agents.py:139`; `chat()` returns `list[str]` in `src/llm_fight/agents.py:173`.
- Impact: The app cannot show prompt/completion tokens, done reasons, load/eval durations, context pressure, or truncation warnings.
- Suggested fix: Return a typed call result with content plus model/options/token/duration metadata; log/transcript and render it when useful.
- Tests: Mock Ollama metadata and assert extraction plus CLI/verbose display.

### ISSUE-024: P2 failures are hidden as normal no-op turns

- Status: tasked
- Task: TODO.md - P2 Fallback Visibility And Fail-Open Policy
- Source: codebase review
- Area: Reliability, observability
- Evidence: Judge Phase 2 catches repeated parse failures and returns `_phase2_noop_result()` in `src/llm_fight/judge.py:247`.
- Impact: Runs can appear successful while the judge is repeatedly failing.
- Suggested fix: Return explicit `fallback_used`/`llm_error` metadata, surface it in play/batch output, and make fail-open configurable.
- Tests: Repeated P2 failures should produce a visible warning/error marker by default; optional fail-open mode should be covered separately.

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

- Status: tasked
- Task: TODO.md - Fight-Scoped JSONL Trace Transcripts
- Source: codebase review
- Area: Observability, transcripts
- Evidence: `log_exchange()` writes one timestamped prompt/response fragment in `src/llm_fight/transcripts.py:31`; it has no fight id, turn, phase, rolls, deltas, state snapshots, token metrics, or outcome.
- Impact: Transcripts are hard to read, replay, or debug after a session.
- Suggested fix: Write one fight-scoped JSONL trace with ordered events: fighter configs, prompts/responses, rolls, deltas, states, token/latency metrics, and final result.
- Tests: Assert one trace preserves event order and contains turn/phase/fighter metadata.

### ISSUE-027: Example fighter names are ignored

- Status: tasked
- Task: TODO.md - Configured Fighter Display Names
- Source: codebase review
- Area: Config, UX
- Evidence: `llmfight.ini.example` defines `name` at `llmfight.ini.example:39`, but `get_fighter_settings()` returns only class/loadout/environment in `src/llm_fight/config.py:161`; prompts use `fighter.id` in `src/llm_fight/engine/fighter.py:129`.
- Impact: Users can edit the obvious identity field and see no effect in prompts, transcripts, or output.
- Suggested fix: Implement `display_name`/`name` through config, state, prompts, rendering, and winner output, or remove unsupported example keys.
- Tests: Example-supported fighter names appear in runtime prompts and pre-fight/turn/final output.

### ISSUE-028: Config and RNG rely on process-global state

- Status: tasked
- Task: TODO.md - Runtime Config And RNG Isolation
- Source: codebase review
- Area: Best practices, reproducibility
- Evidence: `CONFIG = Config()` loads at import time in `src/llm_fight/config.py:186`; CLI replaces/mutates it in `src/llm_fight/cli.py:28` and `src/llm_fight/cli.py:42`; RNG initializes from current config at `src/llm_fight/rng.py:8`.
- Impact: CLI invocations in one process can leak config/overrides, and seeds loaded after import may not affect programmatic `play` unless callers remember to reseed.
- Suggested fix: Pass a scoped `Config`/runtime context through simulation and LLM calls, or restore globals in `finally`. Initialize RNG explicitly at entry points.
- Tests: Invoke multiple CLI commands with different configs in one process and assert isolation. Import RNG before swapping config and assert entry points still seed correctly.

## P3

### ISSUE-029: Burn tick logs a random layer but damages the normal outer layer

- Status: tasked
- Task: TODO.md - Anatomy-Driven Bleeding, Burning, And Layer Accuracy
- Source: codebase review
- Area: Gameplay logging
- Evidence: `apply_effects()` chooses `random_layer_to_burn` for logging in `src/llm_fight/state.py:371`, then calls `apply_damage_to_part()`, whose loop starts at the first positive layer in `src/llm_fight/state.py:201`.
- Impact: Logs can say one tissue layer burned while another actually lost HP.
- Suggested fix: Remove random-layer logging or add targeted layer damage.
- Tests: Seed RNG, burn a multilayer part, and assert the logged/selected layer matches the mutated layer.

### ISSUE-030: Environment guardrail can suppress explicit environment/equipment creativity

- Status: tasked
- Task: TODO.md - Prompt State Context And Environment-Scoped Creativity
- Source: codebase review
- Area: Prompts
- Evidence: Fighter prompt says not to invent walls, pillars, corridors, shadows, cover, terrain, or objects in `src/llm_fight/engine/prompts.py:17`.
- Impact: This helps for open arenas but conflicts with configured environments or equipment that explicitly includes cover, smoke, walls, or shadows.
- Suggested fix: Rephrase as "do not add new features unless they are in environment, equipment, active effects, or created by the current action."
- Tests: Prompt tests for open arena forbidding invented cover and pillared/smoke environments allowing explicit features.

### ISSUE-031: OpenAI-compatible endpoint support conflicts with native Ollama assumptions

- Status: tasked
- Task: TODO.md - Transport Privacy And Endpoint Mode Safety
- Source: codebase review
- Area: Transport, docs
- Evidence: `get_ollama_url()` accepts `/v1/chat/completions` in `src/llm_fight/agents.py:14`, but `ping_ollama()` always checks `/api/tags` in `src/llm_fight/agents.py:238`; `/v1` payloads omit native `num_ctx`/`keep_alive` in `src/llm_fight/agents.py:199`.
- Impact: A compatible `/v1` endpoint can be rejected by CLI health checks or lose context/residency controls.
- Suggested fix: Split native and OpenAI-compatible health checks. Warn when `/v1` is used with native-only settings.
- Tests: `/v1/chat/completions` URL without `/api/tags` should not fail native-only health check; payload warning tests for ignored native options.

### ISSUE-032: Live/perf test gating and docs are inconsistent

- Status: tasked
- Task: TODO.md - Live/Perf Gating And Installed-Package Test Workflow
- Source: codebase review
- Area: Test workflow, docs
- Evidence: Live tests require `--run-live` in `tests/conftest.py:15`, but some tests also require `API_URL`; `tests/test_memory_usage.py:3` imports optional `ollama` at collection time; AGENTS live command can include heavy perf coverage while README omits newer live simulation smoke.
- Impact: `--run-live` can still skip useful smoke tests, accidentally run heavy VRAM probes, or fail collection without live extras.
- Suggested fix: Centralize live gating, move optional imports behind skips, split quick live smoke from perf, and document both.
- Tests: Pytester-style gating tests plus `uv sync --locked --dev && uv run pytest -q` collection without `live` extra.

### ISSUE-033: Docs do not clearly state current fixed-humanoid/retry/progress contracts

- Status: tasked
- Task: TODO.md - Current Gameplay And Retry Contract Docs
- Source: codebase review
- Area: Documentation
- Evidence: README known limitations do not state that anatomy is fixed humanoid despite `src/llm_fight/simulation.py:95`; troubleshooting suggests increasing `max_retries` in `README.md:205` but P2 parse retries are capped and can no-op in `src/llm_fight/judge.py:200`; play docs do not warn that output is printed after completion.
- Impact: Users may expect non-humanoid designs, unlimited retry recovery, or live progress that the current app does not provide.
- Suggested fix: Add gameplay contract notes, retry/fallback contract notes, and current play-output behavior until the TODO items are implemented.
- Tests: No runtime tests required; optional docs/example consistency checks.

### ISSUE-034: Logger setup is not library-friendly

- Status: tasked
- Task: TODO.md - Library-Friendly Logger Setup
- Source: codebase review
- Area: Best practices
- Evidence: Package logger attaches a stdout `StreamHandler` at import in `src/llm_fight/engine/logger.py:13`, checks `hasHandlers()`, and leaves propagation enabled.
- Impact: Logs can mix with CLI stdout, be skipped under root handlers, or duplicate inside host applications.
- Suggested fix: Use `NullHandler` by default; configure CLI handlers to stderr; check `logger.handlers` directly and set propagation deliberately.
- Tests: Reload logger with a root handler and assert handler/propagation behavior; assert CLI logs go to stderr.

### ISSUE-035: Test suite bypasses installed package behavior

- Status: tasked
- Task: TODO.md - Live/Perf Gating And Installed-Package Test Workflow
- Source: codebase review
- Area: Test workflow
- Evidence: `tests/conftest.py:5` inserts `src` directly into `sys.path`.
- Impact: Packaging metadata, console-script, or installed-resource regressions can pass tests.
- Suggested fix: Rely on editable install via `uv` and add packaging smoke checks.
- Tests: CI step using installed package/import and `llmfight --help` without manual `sys.path` insertion.

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
