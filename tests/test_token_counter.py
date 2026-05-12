import pytest

from llm_fight.engine import constants as C
from llm_fight.utils.token_counter import PromptBudgetError, budget_messages_with_trimmed_log, compute_completion_tokens


def test_compute_completion_tokens_caps_generation_limit():
    messages = [{C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: "short prompt"}]

    assert compute_completion_tokens(messages, requested_max_tokens=64, context_limit=32768) == 64


def test_compute_completion_tokens_respects_remaining_context():
    messages = [{C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: "one two three four five"}]

    with pytest.raises(PromptBudgetError):
        compute_completion_tokens(messages, requested_max_tokens=64, context_limit=3)


def test_compute_completion_tokens_rejects_zero_generation_request():
    messages = [{C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: "short prompt"}]

    with pytest.raises(PromptBudgetError):
        compute_completion_tokens(messages, requested_max_tokens=0, context_limit=32768)


def test_budget_messages_with_trimmed_log_keeps_newest_lines():
    log = "\n".join(f"Turn {idx}: old event" for idx in range(1, 8))

    def build_messages(recent_log):
        return [
            {C.AGENT_ROLE: C.AGENT_SYSTEM, C.AGENT_CONTENT: "Required state stays."},
            {C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: recent_log},
        ]

    messages, max_tokens, trimmed_log = budget_messages_with_trimmed_log(
        build_messages,
        log,
        requested_max_tokens=8,
        context_limit=28,
        min_completion_tokens=8,
        phase=C.PROMPT_PHASE_JUDGE_P2,
        log_window_setting=C.CONFIG_JUDGE_LOG_WINDOW,
    )

    assert max_tokens >= 8
    assert "Required state stays." in messages[0][C.AGENT_CONTENT]
    assert "Turn 7" in trimmed_log
    assert "Turn 1" not in trimmed_log
