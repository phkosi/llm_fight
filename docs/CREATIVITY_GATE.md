# Creativity Gate

This gate is opt-in and manual. It is not part of default `pytest`, local smoke
checks, CI, or live model compatibility tests.

Use it when reviewing generated fighters/effects for creative variety after the
deterministic offline tests already pass. The reviewer should inspect generated
profiles, prompts, transcripts, and resulting state snapshots, then flag cases
where the dynamic systems collapse back to fixed humanoid anatomy or
narration-only effects.

Suggested command to gather samples:

```powershell
uv run llmfight play --config llmfight.ini --max-turns 2
```

Set `[General] fighter_creation_mode = generated` in the chosen local config if
you want the LLM to create match-start fighter profiles.

Sample Codex/manual reviewer prompt:

```text
Review these llm_fight generated fighter/effect samples for creativity.
Look for non-humanoid anatomy that survives into state and valid target parts,
and for non-hard-coded effects that have structured mechanics instead of only
narration. Flag repetitive, low-creativity, or humanoid-only outputs. Also flag
effects that sound mechanical but lack mechanics/tags in state.
```

Review criteria:

- At least one body plan uses non-humanoid anatomy such as extra heads, wings,
  tails, tentacles, unusual limbs, or custom organs.
- Non-humanoid parts appear as authoritative valid target parts in prompts,
  judge payloads, and state snapshots.
- At least one effect name is not one of the legacy hard-coded effects and has
  structured mechanics/tags that persist across turns.
- Creative ideas do not rely on stale narration to resurrect expired effects.
- Repeated samples should not all collapse into the same knight/assassin
  humanoid duel unless the config asked for that.
