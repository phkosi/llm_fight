import re
from typing import List, Dict

from ..engine import constants as C

try:  # tiktoken is optional for more accurate counts
    import tiktoken

    _ENCODING = None
    _ENCODING_MODEL = None

    def _get_encoding() -> "tiktoken.Encoding":
        """Return a tiktoken encoding for the configured model."""
        global _ENCODING, _ENCODING_MODEL
        from .. import config as config_mod

        model = config_mod.CONFIG.get(
            C.CONFIG_GENERAL,
            C.CONFIG_LLAMA_DEFAULT_MODEL,
            str,
            fallback="",
        )
        if _ENCODING is None or _ENCODING_MODEL != model:
            try:
                _ENCODING = tiktoken.encoding_for_model(model)
            except Exception:
                _ENCODING = tiktoken.get_encoding("cl100k_base")
            _ENCODING_MODEL = model
        return _ENCODING

    def count_tokens(text: str) -> int:
        """Return a token count of ``text`` using ``tiktoken``."""
        return len(_get_encoding().encode(text))

except Exception:  # pragma: no cover - fallback when tiktoken missing
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


def compute_completion_tokens(messages: List[Dict[str, str]], requested_max_tokens: int, context_limit: int) -> int:
    """Return a generation cap that fits inside the configured context."""
    return max(1, min(requested_max_tokens, compute_max_tokens(messages, context_limit)))
