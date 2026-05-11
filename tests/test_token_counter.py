from llm_fight.engine import constants as C
from llm_fight.utils.token_counter import compute_completion_tokens


def test_compute_completion_tokens_caps_generation_limit():
    messages = [{C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: "short prompt"}]

    assert compute_completion_tokens(messages, requested_max_tokens=64, context_limit=32768) == 64


def test_compute_completion_tokens_respects_remaining_context():
    messages = [{C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: "one two three four five"}]

    assert compute_completion_tokens(messages, requested_max_tokens=64, context_limit=3) == 1


def test_compute_completion_tokens_never_returns_less_than_one():
    messages = [{C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: "short prompt"}]

    assert compute_completion_tokens(messages, requested_max_tokens=0, context_limit=32768) == 1
