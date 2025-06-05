"""Constants and enums used throughout the LLM Fight simulation engine."""

from enum import Enum

# General
STATUS = "status"
NAME = "name"
DESCRIPTION = "description"
EFFECTS = "effects"
TARGET = "target"
SOURCE = "source"
VALUE = "value"
TYPE = "type"

# Fighter States & Attributes
PAIN = "pain"
EXHAUSTION = "exhaustion"
HEAT = "heat"
MAX_HP = "max_hp"
CURRENT_HP = "current_hp"
IS_DESTROYED = "is_destroyed"
WOUNDS = "wounds"
DEBUFFS = "debuffs"
BUFFS = "buffs"
LOADOUT = "loadout"
EQUIPMENT = "equipment"  # Part of loadout
ITEMS = "items"  # Part of loadout

# Body Parts & Anatomy
BODY_PARTS = "body_parts"
TISSUE_LAYERS = "tissue_layers"
BLEED_RATE = "bleed_rate"
BURN_RATE = "burn_rate"

# Statuses


class FighterStatus(str, Enum):
    FIGHTING = "fighting"
    UNCONSCIOUS = "unconscious"
    DEAD = "dead"


STATUS_FIGHTING = FighterStatus.FIGHTING
STATUS_UNCONSCIOUS = FighterStatus.UNCONSCIOUS
STATUS_DEAD = FighterStatus.DEAD
STATUS_SEVERED = "severed"  # for body parts
MAX_PAIN_THRESHOLD = 100  # Threshold for unconsciousness (already implicitly used)
MAX_PAIN_BEFORE_DEATH = 200  # New constant for death by pain

# Effects
EFFECT_ON_APPLY = "on_apply"
EFFECT_ON_TICK = "on_tick"
EFFECT_TTL = "ttl"  # Time To Live
EFFECT_BLEEDING = "bleeding"
EFFECT_BURNING = "burning"
EFFECT_STUNNED = "stunned"

# Damage Types


class DamageType(str, Enum):
    PIERCING = "piercing"
    SLASHING = "slashing"
    FIRE = "fire"  # Consistent with C.EFFECT_BURNING usage elsewhere
    GENERIC = "generic"


DAMAGE_TYPE_PIERCING = DamageType.PIERCING
DAMAGE_TYPE_SLASHING = DamageType.SLASHING
DAMAGE_TYPE_FIRE = DamageType.FIRE
DAMAGE_TYPE_GENERIC = DamageType.GENERIC

# Judge & Simulation
NARRATION = "narration"
DELTA = "delta"
FIGHT_END = "fight_end"
WINNER = "winner"
FIGHTER_A = "A"
FIGHTER_B = "B"

# Delta Keys (for Judge P2)
PAIN_INCREASE = "pain_increase"
EXHAUSTION_INCREASE = "exhaustion_increase"
HEAT_INCREASE = "heat_increase"
EFFECTS_ADDED = "effects_added"
EFFECTS_REMOVED = "effects_removed"
STATUS_CHANGE = "status_change"  # For overall fighter status

# Schema related
SCHEMA_TYPE = "type"
SCHEMA_PROPERTIES = "properties"
SCHEMA_ITEMS = "items"
SCHEMA_REQUIRED = "required"
SCHEMA_ENUM = "enum"
SCHEMA_MINIMUM = "minimum"
SCHEMA_MAXIMUM = "maximum"
SCHEMA_OBJECT = "object"
SCHEMA_STRING = "string"
SCHEMA_INTEGER = "integer"
SCHEMA_NUMBER = "number"
SCHEMA_BOOLEAN = "boolean"
SCHEMA_ARRAY = "array"
SCHEMA_NULL = "null"
SCHEMA_ADDITIONAL_PROPERTIES = "additionalProperties"
SCHEMA_PATTERN_PROPERTIES = "patternProperties"
SCHEMA_MIN_PROPERTIES = "minProperties"
SCHEMA_MAX_PROPERTIES = "maxProperties"

# Ollama Agent
AGENT_MODEL = "model"
AGENT_MESSAGES = "messages"
AGENT_FORMAT = "format"
AGENT_OPTIONS = "options"
AGENT_STREAM = "stream"
AGENT_KEEP_ALIVE = "keep_alive"
AGENT_ROLE = "role"
AGENT_CONTENT = "content"
AGENT_SYSTEM = "system"
AGENT_USER = "user"
AGENT_ASSISTANT = "assistant"
AGENT_RESPONSE = "response"  # Key for Ollama's response content
METADATA = "metadata"
OLLAMA_CHOICES = "choices"  # Added for Ollama specific response
OLLAMA_MESSAGE = "message"  # Added for Ollama specific response
TEMPERATURE = "temperature"  # Added for payload key
AGENT_MAX_TOKENS = "max_tokens"  # Added for payload key
CONTENT_TYPE = "Content-Type"  # Added for headers
APPLICATION_JSON = "application/json"  # Added for headers

# Config file keys
CONFIG_GENERAL = "General"
CONFIG_CONTEXT = "CONTEXT"  # Added config section name
CONFIG_SIMULATION = "SIMULATION"  # Added config section name
CONFIG_FIGHTER_LOG_WINDOW = "fighter_log_window"
CONFIG_JUDGE_LOG_WINDOW = "judge_log_window"
CONFIG_LLAMA_API_URL = "ollama_api_url"
CONFIG_LLAMA_DEFAULT_MODEL = "ollama_default_model"
CONFIG_LLAMA_TEMPERATURE = "ollama_temperature"
CONFIG_MAX_TOKENS_FIGHTER = "max_tokens_fighter"  # Added config key
CONFIG_MAX_TOKENS_JUDGE = "max_tokens_judge"  # Added config key
CONFIG_BEST_OF_FIGHTER = "best_of_fighter"  # Added config key
CONFIG_BEST_OF_JUDGE = "best_of_judge"  # Added config key
CONFIG_MAX_RETRIES = "max_retries"  # Added config key
CONFIG_LOG_LEVEL = "log_level"  # New config key for logger level
CONFIG_TRANSCRIPT_DIR = "transcript_dir"
CONFIG_SAVE_TRANSCRIPTS = "save_transcripts"
CONFIG_RUNS = "runs"  # Added config key
CONFIG_SEED = "seed"  # Added config key
CONFIG_MAX_TURNS = "max_turns"  # Added config key for simulation
CONFIG_CONCURRENT_RUNS = "concurrent_runs"  # Simulation option controlling async concurrency
CONFIG_DEFAULTS = "DEFAULTS"  # For configparser default section
CONFIG_FIGHTER_CLASS = "class"  # Per-fighter class
CONFIG_FIGHTER_LOADOUT = "loadout"  # Per-fighter starting gear
CONFIG_FIGHTER_ENVIRONMENT = "environment"  # Fighting environment
CONFIG_DISCORD = "DISCORD"
CONFIG_DISCORD_TOKEN = "discord_token"
CONFIG_DISCORD_CHANNEL = "discord_channel"

# Prompting
CONTEXT_PAIN_DESCRIPTION = "pain_description"
CONTEXT_EXHAUSTION_DESCRIPTION = "exhaustion_description"
CONTEXT_HEAT_DESCRIPTION = "heat_description"
CONTEXT_ENVIRONMENT = "environment"
CONTEXT_RECENT_LOG = "recent_log"
CONTEXT_OPPONENT_NAME = "opponent_name"
CONTEXT_OPPONENT_CLASS = "opponent_class"  # If classes are introduced
CONTEXT_SELF_CLASS = "self_class"  # If classes are introduced

# Validation outcomes
VALIDATION_PROB = "prob"
VALIDATION_PREDICTED = "predicted"

# File paths (example, might not be needed if handled by Pathlib or similar)
# PROMPT_TEMPLATES_DIR = "prompt_templates"
# FIGHTER_PROFILES_DIR = "fighter_profiles"

# Combat Log
LOG_TURN = "turn"
LOG_NARRATION = "narration"
LOG_ATTEMPT_A = "attempt_A"
LOG_ATTEMPT_B = "attempt_B"
LOG_JUDGE_P1_A = "judge_p1_A"
LOG_JUDGE_P1_B = "judge_p1_B"
LOG_JUDGE_P2 = "judge_p2"
LOG_STATE_A_BEFORE = "state_A_before"
LOG_STATE_B_BEFORE = "state_B_before"
LOG_STATE_A_AFTER = "state_A_after"
LOG_STATE_B_AFTER = "state_B_after"
EFFECT_FIRE_FROM_EFFECT = "fire_from_effect"

# Misc
ACTION = "action"
REASONING = "reasoning"
ATTEMPT = "attempt"
CONFIDENCE = "confidence"
MOVE_DESCRIPTION = "move_description"
TARGETED_PART = "targeted_part"
AGGRESSION = "aggression"
DEFENSIVENESS = "defensiveness"
PREDICTION = "prediction"
OUTCOME = "outcome"
IN_PROGRESS = "in_progress"
DRAW = "draw"
