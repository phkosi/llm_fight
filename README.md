# LLM Fighters Combat Engine

A turn-based duel between two LLM agents (the *Fighters*) adjudicated by a third LLM (*Judge/Narrator*). This project uses Python for randomness, persistence, and retries, with all models running locally through Ollama.

## Overview

LLM Fighters is a combat simulator where AI agents, powered by local Large Language Models (LLMs), engage in strategic, turn-based combat. The engine focuses on creative, free-text actions and a detailed, *Dwarf Fortress*-inspired damage model. A Judge LLM determines the probability of success for actions, Python handles the dice rolls, and the Judge then narrates the outcomes.

## Key Features

*   **Free-text Fighter Actions:** Encourages creative and descriptive combat maneuvers.
*   **Detailed Damage Model:** Features multi-layer body parts, limb loss, pain, and bleeding mechanics.
*   **Probabilistic Combat Resolution:** A Judge LLM assesses action success probability, with Python resolving the outcome via random number generation.
*   **Generous Context Windows:** Supports 24k tokens per Fighter and 48k tokens for the Judge.
*   **Robust Validation:** Utilizes `jsonschema` for validating LLM outputs.
*   **Automatic Retries & Speculative Completions:** Implements `guarded_call()` for retries and `best_of` selection for improved output quality.
*   **Local LLM Execution:** Designed to run with Ollama and `llama3.2:latest` on a single-GPU workstation.

## High-Level Architecture

The core logic resides in the `src/engine/` directory.

```
src/
├── engine/            # core logic
│   ├── anatomy.py      # presets & tissue constants
│   ├── state.py        # FighterState dataclasses + delta apply
│   ├── prompts.py      # verbatim system templates
│   ├── agents.py       # async Ollama client
│   ├── judge.py        # phase‑1 & phase‑2 orchestration
│   ├── fighter.py      # builds fighter context & queries LLM
│   ├── validation.py   # JSON‑schema + guarded_call()
│   ├── rng.py          # central PRNG
│   └── simulation.py   # batch self‑play harness
└── cli.py             # Typer runner (play / simulate / add‑char)
config.py          # INI loader & migration
```

### Turn Flow (Simultaneous Proposals)

1.  **Fighter A & B Actions (Async):** Both fighters simultaneously propose their actions based on the current game state and their character prompts.
2.  **Judge Phase 1 (Probability Assessment):** The Judge LLM receives both proposed actions and outputs a JSON object containing:
    *   The probability of success (0-1) for each action.
    *   A predicted brief outcome.
    *   Potential wounds, buffs, and debuffs.
3.  **Dice Roll (Python):** The Python engine uses the probabilities from Judge Phase 1 to perform a random roll for each fighter, determining if their action succeeds or fails.
4.  **Judge Phase 2 (Narration & State Delta):** The Judge LLM receives the outcomes of the dice rolls and generates:
    *   A narrative description of what happened during the turn.
    *   A JSON delta describing changes to each fighter's state (HP, effects, etc.).
    *   A boolean indicating if the fight has ended and the winner, if any.

```
┌── Fighter A ─┐  async   ┌── Judge P1 ─┐
└──────────────┘          └─────────────┘
       ▲                       │  JSON {prob}
       │                       ▼  RNG rolls
┌── Fighter B ─┐          ┌── Judge P2 ─┐
└──────────────┘          └─────────────┘
```

## Getting Started

### Prerequisites

*   Python 3.x
*   Ollama installed and running with the `llama3.2:latest` model (or as configured).
    *   Ensure Ollama is accessible and the specified model is pulled.

### Installation

1.  Clone the repository:
    ```bash
    git clone <repository_url>
    cd llm_fight
    ```
2.  (Recommended) Create and activate a virtual environment:
    ```bash
    python -m venv .venv
    source .venv/bin/activate  # On Windows use `.venv\Scripts\activate`
    ```
3.  Install runtime dependencies:
    ```bash
    pip install -r requirements.txt
    ```
4.  For development and testing, install the additional dev requirements:
    ```bash
    pip install -r requirements-dev.txt
    ```
5.  Copy the example configuration and customize as needed:
    ```bash
    cp llmfight.ini.example llmfight.ini
    ```

### Running Tests

With the dev dependencies installed you can execute the test suite using
`pytest`:

```bash
pytest -q
```

When calling the async functions in `src/agents.py` within standalone scripts
or tests, ensure the underlying aiohttp session is closed:

```python
import asyncio
from src.agents import close_session

asyncio.run(close_session())
```

## Running the Simulation

The simulation harness can be run via the command-line interface.

```bash
python -m src.cli simulate
```
This command will execute the number of simulation runs specified in the configuration file (see below) and output results to `sim_results.csv` by default. Use `--output-csv PATH` to change the file location.

To run a single fight and display the winner:

```bash
python -m src.cli play
```

## Discord Bot

This project ships with a simple Discord bot that lets you host fights in a
Discord server. The steps below walk through creating the bot application,
configuring `llmfight`, and running the bot. No prior Discord experience is
assumed.

1. **Create a Discord application and bot token**
   1. Visit <https://discord.com/developers/applications> and log in.
   2. Click **New Application**, give it a name, and confirm.
   3. In the sidebar choose **Bot** and click **Add Bot**. Use the **Reset
      Token** button to reveal the token and copy it somewhere safe. This token
      allows the bot to log in – keep it private.

2. **Invite the bot to your server**
   1. In the developer portal open **OAuth2 → URL Generator**.
   2. Under **Scopes** tick `bot` and `applications.commands`.
   3. Under **Bot Permissions** select at minimum **Send Messages** and **Use
      Application Commands**.
   4. Copy the generated URL and open it in your browser to invite the bot to a
      server where you have permission to add members.

3. **Install project dependencies** (if you have not done so already):
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure `llmfight.ini`**
   Create a file named `llmfight.ini` in the project root (or edit the existing
   one) and add the following section:

   ```ini
   [DISCORD]
   discord_token = your-bot-token       ; required
   discord_channel = channel-name-or-id ; optional, limit commands to this channel
   ```

   The `discord_channel` option is optional. When provided, the bot only
   responds to commands issued from that channel.

5. **Run the bot**
   ```bash
   python -m src.discord_bot
   ```

   On first start Discord may take a minute to register the slash commands.
   Once ready, use `/fight start` to begin a session, `/fight status` to check
   on it, and `/fight stop` to end it. Only one fight session is kept in memory
   at a time.

## Configuration

The simulation is configured using `llmfight.ini`. Start by copying `llmfight.ini.example` to `llmfight.ini` and editing values as needed. Key settings include:

```ini
[General]
ollama_default_model = llama3.2  ; Ollama model to use
ollama_api_url      = http://localhost:11434/v1/chat/completions ; Local Ollama endpoint
max_tokens_fighter   = 24000     ; Max context tokens for fighter prompts
max_tokens_judge     = 48000     ; Max context tokens for judge prompts
ollama_temperature   = 0.8       ; Temperature for Ollama completions
best_of_fighter      = 3         ; Number of speculative completions for fighter actions
best_of_judge        = 2         ; Number of speculative completions for judge phases
max_retries          = 2         ; Max retries for LLM calls on validation failure

[CONTEXT]
fighter_log_window = 10          ; Number of recent turns to include in fighter's context
judge_log_window   = 9999        ; Number of recent turns for judge (effectively all)

[SIMULATION]
runs               = 1000        ; Number of simulation runs
seed               = 42          ; PRNG seed for reproducibility
concurrent_runs    = 1           ; Number of fights to execute simultaneously

[FighterA]
class       = Barbarian
loadout     = axe and shield
environment = dusty arena
```
You can also configure the Discord bot:

```ini
[DISCORD]
discord_token = your-bot-token       ; required
discord_channel = channel-name-or-id ; optional, limit commands to this channel
```
The `config.py` file is responsible for loading and managing these configurations.

The Ollama endpoint defaults to `http://localhost:11434/v1/chat/completions`.
You can change this in `llmfight.ini` using `ollama_api_url` or override it at
runtime with the `API_URL` environment variable (useful when tunneling a remote
service with ngrok):

```bash
export API_URL="https://your-ngrok-url.ngrok-free.app/v1/chat/completions"
```

To expose a local Ollama instance so that it can be reached over the
internet, bind the service to all interfaces and tunnel it with ngrok:

```powershell
$Env:OLLAMA_HOST = "0.0.0.0:11434"
ngrok http 11434 --host-header="localhost:11434"
```
Use the resulting public ngrok URL with `API_URL` as shown above.


## Directory Structure

```
llm_fight/
├── src/                      # Source code
│   ├── engine/               # Core combat engine logic
│   │   ├── anatomy.py        # Body part presets and tissue constants
│   │   ├── state.py          # FighterState dataclasses and state update logic
│   │   ├── prompts.py        # System prompt templates for LLMs
│   │   ├── agents.py         # Asynchronous Ollama client
│   │   ├── judge.py          # Judge LLM orchestration (Phase 1 & 2)
│   │   ├── fighter.py        # Fighter LLM interaction logic
│   │   ├── validation.py     # JSON schema validation and guarded LLM calls
│   │   ├── rng.py            # Centralized Pseudo-Random Number Generator
│   │   └── simulation.py     # Batch simulation harness
│   └── cli.py                # Command Line Interface (Typer based)
├── tests/                    # Unit and integration tests
│   └── engine/               # Tests for the engine components
├── .gitignore                # Specifies intentionally untracked files
├── config.py                 # Configuration loader and migration
├── docs/
│   └── DEVELOPMENT_PLAN.md   # Ongoing development roadmap
│   └── Design_doc.md         # Detailed design document
├── README.md                 # This file
└── run.py                    # (Assumed) A script to run/launch the application
```

## Data Model

The core data structure for a fighter is `FighterState`:

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
    ttl: int            # turns remaining (-1 = infinite)
    on_apply: str
    on_tick: str | None

@dataclass
class FighterState:
    id: str
    parts: dict[str, BodyPart] # Keyed by part name
    pain: int = 0
    exhaustion: int = 0
    heat: int = 0
    buffs: list[Effect] = field(default_factory=list)
    debuffs: list[Effect] = field(default_factory=list)
    status: Literal['fighting','unconscious','dead'] = 'fighting'
    class_: str = 'Generic Fighter'
    loadout: str = 'their bare fists and wits'
    environment: str = 'an open arena'
```
Body part presets like `humanoid` and `quadruped` are defined in `src/engine/anatomy.py`.

## Combat Log

Each fight records its history using a `CombatLog` object.  Every turn is
stored as a `CombatTurn` with fields like the fighter attempts, judge outputs
and the resulting narration.  Logs can be queried for the most recent turns or
converted into a plain-text summary.

```python
from src.engine.combat_log import CombatLog, CombatTurn

log = CombatLog()
log.append(CombatTurn(turn=1, judge_p2={"narration": "A strikes B"}))
print(log.to_summary())
```

The example above would output:

```
Turn 1: A strikes B
```

## Future Work

1.  **Discord Bot:** Implement a Discord bot using Ollama's OpenAI-compatible endpoint for per-channel fight sessions.
2.  **Visualizer:** Develop a Godot-based visualizer to replay combat logs with sprite limb masking.
3.  **Advanced Modifiers:** Introduce infection and weather modifiers after the MVP is stable.

## Contributing

Details on contributing to the project will be added here.

## License

This project is licensed under the [MIT License](LICENSE) (assuming MIT, please update if different).

---
© 2025 LLM Fighters Project
