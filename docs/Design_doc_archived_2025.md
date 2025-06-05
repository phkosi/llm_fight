# Archived Design Document (May 2025)
# LLM Fighters Combat Engine – Detailed Design Document (v0.5)
This file preserves the original design for historical reference.


> **Status · 2025‑05‑31**  This document defines the first working milestone of the local‑LLM 1‑vs‑1 fighting simulator.  It is formatted in GitHub‑flavoured Markdown and should render correctly in most viewers (Discord, GitHub, VS Code, etc.).

---

## Table of Contents

1. [Overview](#1-overview)
2. [High‑Level Architecture](#2-high-level-architecture)
3. [Data Model](#3-data-model)
4. [Prompt Engineering](#4-prompt-engineering)
5. [Validation & Retries](#5-validation--retries)
6. [Simulation Harness](#6-simulation-harness)
7. [Configuration (INI)](#7-configuration-ini)
8. [Performance Notes](#8-performance-notes)
9. [Future Work](#9-future-work)

---

## 1  Overview

A **turn‑based duel** between two LLM agents (the *Fighters*) adjudicated by a third LLM (*Judge/Narrator*).  Python controls randomness, persistence, and retries.  All models run locally through **Ollama `llama3.2:latest`** on a single‑GPU workstation.

Key features:

* *Free‑text* fighter actions – creativity encouraged.
* *Dwarf Fortress*‑inspired damage: multi‑layer body parts, limb loss, pain, bleeding.
* Judge decides success **probability** → Python rolls dice → Judge narrates outcome.
* Generous context: **24 k tokens per Fighter**, **48 k tokens for Judge**.
* Guardrails with `jsonschema`; automatic retries; `best_of` speculative completions.

---

## 2  High‑Level Architecture

```
src/
├── anatomy.py      # presets & tissue constants
├── agents.py       # async Ollama client
├── cli.py          # Typer runner (play / simulate / add‑char)
├── config.py       # INI loader & migration
├── engine/         # helper modules
│   ├─ combat_log.py
│   ├─ constants.py
│   ├─ fighter.py
│   ├─ logger.py
│   └─ prompts.py
├── judge.py        # phase‑1 & phase‑2 orchestration
├── rng.py          # central PRNG
├── simulation.py   # batch self‑play harness
├── state.py        # FighterState dataclasses + delta apply
└── validation.py   # JSON‑schema + guarded_call()
```

### 2.1  Turn Flow (simultaneous proposals)

```
┌── Fighter A ─┐  async   ┌── Judge P1 ─┐
└──────────────┘          └─────────────┘
       ▲                       │  JSON {prob}
       │                       ▼  RNG rolls
┌── Fighter B ─┐          ┌── Judge P2 ─┐
└──────────────┘          └─────────────┘
```

*Two* fighter prompts run in parallel; their JSON is fed into a **single** Judge call per phase.

---

## 3  Data Model

```python
@dataclass
class TissueLayer:
    name: str        # 'skin', 'fat', ...
    max_hp: int

@dataclass
class BodyPart:
    name: str
    layers: list[TissueLayer]
    severed: bool = False
    bleed_rate: int = 0
    burn_rate:  int = 0

@dataclass
class Effect:
    name: str           # 'burning', 'stunned', ...
    magnitude: float
    ttl: int            # turns remaining (‑1 = infinite)
    on_apply: str
    on_tick: str | None

@dataclass
class FighterState:
    id: str
    parts: dict[str, BodyPart]
    pain: int = 0
    exhaustion: int = 0
    heat: int = 0
    buffs: list[Effect] = field(default_factory=list)
    debuffs: list[Effect] = field(default_factory=list)
    status: Literal['fighting','unconscious','dead'] = 'fighting'
```

*Presets*: `humanoid`, `quadruped`, … stored in **anatomy.py**.

---

## 4  Prompt Engineering

### 4.1  Fighter (A and B)

```text
SYSTEM:
You are {name}, a {class_} currently fighting inside a {environment}.
Pain: {pain_desc}   Exhaustion: {exhaustion_desc}   Heat: {heat_desc}
Active effects: {effects_list}
Last {turn_window} turns:
{recent_log}
Your equipment: {loadout}
---
Respond with ONE sentence describing what you attempt next. ≤ 30 words.
(No outcome narration.  Raw text only.)
```

*Sample output*: “*I thrust my staff downward, releasing an arc of flame toward Viper’s torso.*”

### 4.2  Judge Phase 1 — Probability

```text
SYSTEM: You are an impartial combat arbiter.  Return STRICT JSON.
SCHEMA per fighter: {prob: 0‑1, predicted: str, potential:{wounds:[...],buffs:[...],debuffs:[...]}}
```

*Sample output (abridged)*:

```json
{"A":{"prob":0.64,"predicted":"flame scorches torso","potential":{"wounds":["torso"],"debuffs":["burning"]}},"B":{...}}
```

### 4.3  Dice Roll (Python)

```python
rolls = {k: random.random() < data[k]['prob'] for k in ('A','B')}
```

### 4.4  Judge Phase 2 — Narration + Delta

```text
SYSTEM: You are the combat narrator.  Output JSON ONLY as:
{ narration:str, delta:{A:{...},B:{...}}, fight_end:bool, winner:'A'|'B'|null }
```

*Sample output omitted here for brevity — see design §4 in canvas.*

---

## 5  Validation & Retries

* `jsonschema` enforces **Judge P1** and **Judge P2** schemas.
* `guarded_call()` loops ≤ `max_retries` (INI) per request.
* `best_of_fighter` / `best_of_judge` spawn *N* speculative completions and pick the shortest passing schema.

---

## 6  Simulation Harness

*CLI*:

```bash
python -m llm_fight.cli simulate           # runs [SIMULATION] runs
```

Outputs `sim_results.csv` with winner, turn‑count, KO/bleed statistics (future: bar chart).

---

## 7  Configuration (INI excerpt)

```ini
[General]
model              = llama3.2
ollama_api_url     = http://localhost:11434/v1/chat/completions
max_tokens_fighter = 24000
max_tokens_judge   = 48000
best_of_fighter    = 3
best_of_judge      = 2
max_retries        = 2

[CONTEXT]
fighter_log_window = 10
judge_log_window   = 9999

[SIMULATION]
runs               = 1000
seed               = 42
```

---

## 8  Performance Notes

* Two fighter prompts + Judge phases keep GPU VRAM ≤ 12 GB (llama‑3‑8B context fits \~4 GB each).
* Async `gather()` overlaps fighter calls; Judge is sequential but single call per phase.
* Log summarisation triggers when total tokens > 48 k.

---

## 9  Future Work

1. **Discord bot** using Ollama’s OpenAI‑compat endpoint.  Per‑channel fight sessions.
2. **Visualiser** (Godot) that replays combat log with sprite limb masking.
3. **Infection & weather** modifiers after MVP is stable.

---

© 2025 LLM Fighters Project
