import re
from typing import List, Dict
from ..engine import constants as C

_TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)


def count_tokens(text: str) -> int:
    """Return a naive token count of ``text``."""
    return len(_TOKEN_RE.findall(text))


def count_message_tokens(messages: List[Dict[str, str]]) -> int:
    """Count tokens across a list of chat messages."""
    return sum(count_tokens(m.get(C.AGENT_CONTENT, "")) for m in messages)


def compute_max_tokens(messages: List[Dict[str, str]], limit: int) -> int:
    """Return remaining tokens available for completion."""
    used = count_message_tokens(messages)
    remaining = limit - used
    return max(1, remaining)
