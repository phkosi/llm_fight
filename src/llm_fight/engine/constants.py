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
ANATOMY = "anatomy"
ANATOMY_PROFILE = "anatomy_profile"
PROFILE = "profile"
THEME = "theme"
PROFILE_GENERATION = "profile_generation"
CONSEQUENCE_TAGS = "consequence_tags"
CONSEQUENCE_GROUP = "consequence_group"
CONSEQUENCE_FATAL_IF_DESTROYED = "fatal_if_destroyed"
CONSEQUENCE_INCAPACITATING_IF_DESTROYED = "incapacitating_if_destroyed"
CONSEQUENCE_VISION_MEMBER = "vision_member"
CONSEQUENCE_MOBILITY_MEMBER = "mobility_member"
CONSEQUENCE_LEGACY_VITAL_GROUP_MEMBER = "legacy_vital_group_member"
CONSEQUENCE_GROUP_VISION = "vision"
CONSEQUENCE_GROUP_LEGS = "legs"
CONSEQUENCE_GROUP_LEGACY_VITALS = "legacy_vitals"
CONSEQUENCE_ALLOWED_TAGS = (
    CONSEQUENCE_FATAL_IF_DESTROYED,
    CONSEQUENCE_INCAPACITATING_IF_DESTROYED,
    CONSEQUENCE_VISION_MEMBER,
    CONSEQUENCE_MOBILITY_MEMBER,
    CONSEQUENCE_LEGACY_VITAL_GROUP_MEMBER,
)

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
EFFECT_IMPAIRED_VISION = "impaired_vision"
EFFECT_BLINDED = "blinded"
EFFECT_IMPAIRED_MOBILITY = "impaired_mobility"
EFFECT_GROUNDED = "grounded"
EFFECT_TAG_ANATOMY_CONSEQUENCE = "anatomy_consequence"
EFFECT_TAG_VISION_IMPAIRED = "vision_impaired"
EFFECT_TAG_MOBILITY_IMPAIRED = "mobility_impaired"
EFFECT_MECHANICS = "mechanics"
EFFECT_TAGS = "tags"
EFFECT_MECHANIC_KIND = "kind"
EFFECT_MECHANIC_STAT_TICK = "stat_tick"
EFFECT_MECHANIC_DAMAGE_TICK = "damage_tick"
EFFECT_MECHANIC_TARGETING_MODIFIER = "targeting_modifier"
EFFECT_MECHANIC_ACTION_MODIFIER = "action_modifier"
EFFECT_MECHANIC_STAT = "stat"
EFFECT_MECHANIC_MODIFIER = "modifier"
EFFECT_MECHANIC_OUTGOING_ACCURACY_PENALTY = "outgoing_accuracy_penalty"
EFFECT_MECHANIC_ACTION_BLOCK = "action_block"
EFFECT_MODIFIERS_APPLIED = "effect_modifiers_applied"
EFFECT_MECHANIC_MAX_VALUE = 100
EFFECT_TAG_MAX_LENGTH = 32
EFFECT_MAX_TTL = 20
EFFECT_MAX_MAGNITUDE = 200
EFFECT_NAME_MAX_LENGTH = 48
EFFECT_TEXT_MAX_LENGTH = 160
EFFECT_METADATA_VALUE_MAX_LENGTH = 64
EFFECT_SAFE_NAME_PATTERN = (
    r"^(?!.*(?i:ignore|instruction|system prompt|developer|jailbreak|override|forget previous))[A-Za-z][A-Za-z0-9 _-]*$"
)
EFFECT_SAFE_TEXT_PATTERN = r"^(?!.*(?i:ignore previous|previous instructions|system prompt|developer message|jailbreak|override instructions|forget previous))[^\r\n{}<>`\\]+$"
EFFECT_FORBIDDEN_TEXT_FRAGMENTS = (
    "ignore previous",
    "previous instructions",
    "system prompt",
    "developer message",
    "jailbreak",
    "override instructions",
    "forget previous",
)

# Damage Types


class DamageType(str, Enum):
    PIERCING = "piercing"
    SLASHING = "slashing"
    FIRE = "fire"  # Consistent with C.EFFECT_BURNING usage elsewhere
    BLUNT = "blunt"
    GENERIC = "generic"


DAMAGE_TYPE_PIERCING = DamageType.PIERCING
DAMAGE_TYPE_SLASHING = DamageType.SLASHING
DAMAGE_TYPE_FIRE = DamageType.FIRE
DAMAGE_TYPE_BLUNT = DamageType.BLUNT
DAMAGE_TYPE_GENERIC = DamageType.GENERIC

# Judge & Simulation
NARRATION = "narration"
DELTA = "delta"
FIGHT_END = "fight_end"
WINNER = "winner"
BATCH_ERROR_WINNER = "error"
FIGHTER_A = "A"
FIGHTER_B = "B"
SOURCE = "source"

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
SCHEMA_PATTERN = "pattern"
SCHEMA_PATTERN_PROPERTIES = "patternProperties"
SCHEMA_MIN_PROPERTIES = "minProperties"
SCHEMA_MAX_PROPERTIES = "maxProperties"
SCHEMA_MIN_LENGTH = "minLength"
SCHEMA_MAX_LENGTH = "maxLength"
SCHEMA_MIN_ITEMS = "minItems"
SCHEMA_MAX_ITEMS = "maxItems"
SCHEMA_UNIQUE_ITEMS = "uniqueItems"
SCHEMA_ONE_OF = "oneOf"
SCHEMA_NOT = "not"
SCHEMA_CONST = "const"

# Ollama Agent
AGENT_MODEL = "model"
AGENT_MESSAGES = "messages"
AGENT_FORMAT = "format"
AGENT_OPTIONS = "options"
NUM_CTX = "num_ctx"
AGENT_STREAM = "stream"
AGENT_THINK = "think"
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
AGENT_NUM_PREDICT = "num_predict"
AGENT_RESPONSE_FORMAT = "response_format"
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
CONFIG_OLLAMA_KEEP_ALIVE = "ollama_keep_alive"
CONFIG_OLLAMA_NUM_CTX = "ollama_num_ctx"
CONFIG_OLLAMA_PROXY_MODE = "ollama_proxy_mode"
OLLAMA_PROXY_AUTO = "auto"
OLLAMA_PROXY_DISABLED = "disabled"
OLLAMA_PROXY_ENABLED = "enabled"
CONFIG_JUDGE_PHASE2_FAILURE_POLICY = "judge_phase2_failure_policy"
P2_FAILURE_POLICY_FAIL_OPEN = "fail_open"
P2_FAILURE_POLICY_FAIL_CLOSED = "fail_closed"
CONFIG_MAX_TOKENS_FIGHTER = "max_tokens_fighter"  # Added config key
CONFIG_MAX_TOKENS_JUDGE = "max_tokens_judge"  # Added config key
CONFIG_BEST_OF_FIGHTER = "best_of_fighter"  # Added config key
CONFIG_BEST_OF_JUDGE = "best_of_judge"  # Added config key
CONFIG_MAX_RETRIES = "max_retries"  # Added config key
CONFIG_LOG_LEVEL = "log_level"  # New config key for logger level
CONFIG_LOG_COMBAT_TURNS = "log_combat_turns"  # Log each combat turn
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
CONFIG_FIGHTER_ANATOMY_PROFILE = ANATOMY_PROFILE  # Optional per-fighter anatomy profile JSON path
CONFIG_FIGHTER_PROFILE = PROFILE  # Legacy/alias per-fighter anatomy profile JSON path
CONFIG_FIGHTER_THEME = THEME  # Optional per-fighter generated/profile theme
CONFIG_FIGHTER_CREATION_MODE = "fighter_creation_mode"
FIGHTER_CREATION_MODE_CONFIGURED = "configured"
FIGHTER_CREATION_MODE_GENERATED = "generated"
FIGHTER_CREATION_NUDGES = ("warrior", "mage", "monster", "trickster", "hybrid", "original")
PROFILE_GENERATION_ERROR_INVALID = "invalid_generated_profile"
PROFILE_GENERATION_ERROR_FAILED = "generation_failed"
CONFIG_FIGHTER_SENTENCE_LIMIT = "fighter_sentence_limit"
CONFIG_FIGHTER_WORD_LIMIT = "fighter_word_limit"
CONFIG_FIGHTER_A_SECTION = "fighter_A"  # Config section for fighter A settings
CONFIG_FIGHTER_B_SECTION = "fighter_B"  # Config section for fighter B settings
CONFIG_DEFAULT_FIGHTER = "DEFAULT_FIGHTER"  # Section for fallback fighter stats

# Prompting
CONTEXT_PAIN_DESCRIPTION = "pain_description"
CONTEXT_EXHAUSTION_DESCRIPTION = "exhaustion_description"
CONTEXT_HEAT_DESCRIPTION = "heat_description"
CONTEXT_ENVIRONMENT = "environment"
CONTEXT_RECENT_LOG = "recent_log"
CONTEXT_OPPONENT_NAME = "opponent_name"
CONTEXT_OPPONENT_CLASS = "opponent_class"  # If classes are introduced
CONTEXT_SELF_CLASS = "self_class"  # If classes are introduced
ACTIVE_EFFECTS = "active_effects"
VALID_TARGET_PARTS = "valid_target_parts"
TARGET_PARTS = "target_parts"
DAMAGED_PARTS = "damaged_parts"

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
SUCCESSFUL_ROLLS = "successful_rolls"
VALIDATION_WARNINGS = "validation_warnings"
WARNING_CODE_INVALID_P2_WOUND_TARGET = "invalid_p2_wound_target"
WARNING_CODE_CANONICALIZED_P2_WOUND_TARGET = "canonicalized_p2_wound_target"
WARNING_CODE_INVALID_EFFECT_REMOVAL_TARGET = "invalid_effect_removal_target"
WARNING_CODE_CANONICALIZED_EFFECT_REMOVAL_TARGET = "canonicalized_effect_removal_target"
P2_FALLBACK_USED = "fallback_used"
P2_FALLBACK_REASON = "fallback_reason"
P2_FALLBACK_REASON_PARSE_FAILED = "judge_phase2_parse_failed"
P2_LLM_ERROR = "llm_error"
P2_FALLBACK_POLICY = "policy"
P2_ENGINE_FALLBACK_MARKER = "_engine_phase2_fallback"
LOG_P2_FALLBACK_TURNS = "p2_fallback_turns"
LOG_P2_FALLBACK_USED = "p2_fallback_used"
P2_FALLBACK_MARKER_TEXT = "Warning: Judge Phase 2 fallback; no judge delta applied."
OUTCOME = "outcome"
IN_PROGRESS = "in_progress"
DRAW = "draw"

# Prompt budget phases and minimum completion reserves
PROMPT_PHASE_FIGHTER_ACTION = "fighter action"
PROMPT_PHASE_JUDGE_P1 = "judge phase 1"
PROMPT_PHASE_JUDGE_P2 = "judge phase 2"
PROMPT_PHASE_JUDGE_P2_REPAIR = "judge phase 2 repair"
PROMPT_PHASE_PROFILE_GENERATION = "fighter profile generation"
PROMPT_MIN_COMPLETION_FIGHTER = 64
PROMPT_MIN_COMPLETION_JUDGE_P1 = 256
PROMPT_MIN_COMPLETION_JUDGE_P2 = 512
PROMPT_MIN_COMPLETION_JUDGE_P2_REPAIR = 512
PROMPT_MIN_COMPLETION_PROFILE_GENERATION = 512

# Play events
FIGHT_EVENT_PROFILE_GENERATION_START = "profile_generation_start"
FIGHT_EVENT_PROFILE_GENERATION_END = "profile_generation_end"
FIGHT_EVENT_FIGHTERS_READY = "fighters_ready"
FIGHT_EVENT_FIGHTER_ACTION_START = "fighter_action_start"
FIGHT_EVENT_FIGHTER_ACTION_END = "fighter_action_end"
FIGHT_EVENT_JUDGE_PHASE1_START = "judge_phase1_start"
FIGHT_EVENT_JUDGE_PHASE1_END = "judge_phase1_end"
FIGHT_EVENT_ROLLS_START = "rolls_start"
FIGHT_EVENT_ROLLS_END = "rolls_end"
FIGHT_EVENT_JUDGE_PHASE2_START = "judge_phase2_start"
FIGHT_EVENT_JUDGE_PHASE2_END = "judge_phase2_end"
FIGHT_EVENT_DELTAS_START = "deltas_start"
FIGHT_EVENT_DELTAS_END = "deltas_end"
FIGHT_EVENT_EFFECTS_START = "effects_start"
FIGHT_EVENT_EFFECTS_END = "effects_end"
FIGHT_EVENT_TURN_COMPLETE = "turn_complete"
FIGHT_EVENT_FIGHT_COMPLETE = "fight_complete"
FIGHT_EVENT_TOKEN_METADATA = "token_metadata"
