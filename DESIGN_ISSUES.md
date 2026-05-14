# Design Issues

Use this file for game design concerns that are not clearly bugs, regressions, security risks, or implementation failures. These entries should not become `TODO.md` tasks automatically unless the user asks for that.

## Entry Template

```markdown
### DESIGN-001: Short title

- Status: open | accepted | deferred | resolved
- Source: playtest | codebase review | user
- Observation: What was seen in play or review.
- Design concern: Why it may weaken the game experience.
- Possible direction: A non-binding direction for future design work.
```

## Open

### DESIGN-001: Default interactive fights are short and draw-heavy

- Status: open
- Source: playtest
- Observation: Playtest loop `transcripts\playtest_loop_20260512_010010` ran 34 default `uv run llmfight play` attempts over 614.1 seconds. Of the 31 runs with winner output, 29 ended in `draw`, 1 ended with `A`, and 1 ended with `B`; every non-crashing completed run rendered exactly 2 turns.
- Design concern: The default interactive experience produces many shallow non-resolutions, which makes it harder to judge tactics, injuries, comeback arcs, or whether fighter differences matter.
- Possible direction: Consider a longer or more decisive default play preset, clearer win-pressure mechanics, or a dedicated quick-play mode that still has enough turns to expose meaningful state changes.

### DESIGN-002: Generated-character pilot mostly exercised fallback profiles

- Status: open
- Source: playtest
- Observation: The generated-character trial collection `uv run llmfight collect-trials --mode generated` wrote accepted artifacts to `transcripts\trials\20260513_233837`, but summaries recorded 35 fallback fighter profiles and only 1 generated fighter profile across 36 fighters. The smoke run at `transcripts\trials\20260513_233748` also fell back for both fighters.
- Design concern: Generated-character mode can be mechanically reviewable while still failing to deliver the intended fantasy of distinct original fighters, custom anatomy, and fresh silhouettes/loadouts.
- Possible direction: Review generated-profile prompting and validation strictness with a dedicated creativity/profile-quality pass before treating generated-mode trials as a reliable creativity benchmark.
