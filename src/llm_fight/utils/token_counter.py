import re
from collections.abc import Callable
from dataclasses import dataclass

from ..engine import constants as C

try:  # tiktoken is optional for more accurate counts
    import tiktoken

    _ENCODING = None
    _ENCODING_MODEL = None

    def _get_encoding() -> tiktoken.Encoding:
        """Return a tiktoken encoding for the configured model."""
        global _ENCODING, _ENCODING_MODEL
        from .. import config as config_mod

        model = config_mod.CONFIG.get(
            C.CONFIG_GENERAL,
            C.CONFIG_LLAMA_DEFAULT_MODEL,
            str,
            fallback="",
        )
        if _ENCODING is None or model != _ENCODING_MODEL:
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


def count_message_tokens(messages: list[dict[str, str]]) -> int:
    """Count tokens across a list of chat messages."""
    return sum(count_tokens(m.get(C.AGENT_CONTENT, "")) for m in messages)


@dataclass
class PromptBudgetError(ValueError):
    """Raised when a prompt cannot leave enough completion budget."""

    phase: str
    prompt_tokens: int
    context_limit: int
    requested_max_tokens: int
    reserved_completion: int
    log_window_setting: str | None = None

    def __str__(self) -> str:
        pieces = [
            f"Prompt budget exceeded for {self.phase}:",
            f"prompt uses about {self.prompt_tokens} tokens",
            f"context limit is {self.context_limit}",
            f"reserved completion is {self.reserved_completion}",
            f"requested max completion is {self.requested_max_tokens}.",
        ]
        if self.log_window_setting:
            pieces.append(
                f"Reduce [{C.CONFIG_CONTEXT}] {self.log_window_setting}, "
                f"increase [{C.CONFIG_GENERAL}] {C.CONFIG_OLLAMA_NUM_CTX}, "
                "or shorten configured fighter/profile text."
            )
        else:
            pieces.append(
                f"Increase [{C.CONFIG_GENERAL}] {C.CONFIG_OLLAMA_NUM_CTX} or shorten configured fighter/profile text."
            )
        return " ".join(pieces)


def compute_max_tokens(messages: list[dict[str, str]], limit: int) -> int:
    """Return remaining tokens available for completion."""
    used = count_message_tokens(messages)
    remaining = limit - used
    return remaining


def _completion_reserve(requested_max_tokens: int, min_completion_tokens: int) -> int:
    if requested_max_tokens < 1:
        return 1
    return max(1, min(requested_max_tokens, min_completion_tokens))


def compute_completion_tokens(
    messages: list[dict[str, str]],
    requested_max_tokens: int,
    context_limit: int,
    *,
    min_completion_tokens: int = 1,
    phase: str = "LLM call",
    log_window_setting: str | None = None,
) -> int:
    """Return a generation cap or raise if the prompt cannot safely fit."""
    prompt_tokens = count_message_tokens(messages)
    reserved_completion = _completion_reserve(requested_max_tokens, min_completion_tokens)
    if requested_max_tokens < 1 or context_limit - prompt_tokens < reserved_completion:
        raise PromptBudgetError(
            phase=phase,
            prompt_tokens=prompt_tokens,
            context_limit=context_limit,
            requested_max_tokens=requested_max_tokens,
            reserved_completion=reserved_completion,
            log_window_setting=log_window_setting,
        )
    return min(requested_max_tokens, context_limit - prompt_tokens)


def _log_lines(recent_log: str) -> list[str]:
    if not recent_log:
        return []
    return recent_log.splitlines() or [recent_log]


def budget_messages_with_trimmed_log(
    build_messages: Callable[[str], list[dict[str, str]]],
    recent_log: str,
    *,
    requested_max_tokens: int,
    context_limit: int,
    min_completion_tokens: int,
    phase: str,
    log_window_setting: str,
) -> tuple[list[dict[str, str]], int, str]:
    """Fit messages by dropping oldest combat-log lines, preserving required context."""
    full_messages = build_messages(recent_log)
    try:
        max_tokens = compute_completion_tokens(
            full_messages,
            requested_max_tokens,
            context_limit,
            min_completion_tokens=min_completion_tokens,
            phase=phase,
            log_window_setting=log_window_setting,
        )
        return full_messages, max_tokens, recent_log
    except PromptBudgetError:
        pass

    lines = _log_lines(recent_log)
    empty_log = ""
    empty_messages = build_messages(empty_log)
    empty_max_tokens = compute_completion_tokens(
        empty_messages,
        requested_max_tokens,
        context_limit,
        min_completion_tokens=min_completion_tokens,
        phase=phase,
        log_window_setting=log_window_setting,
    )
    if not lines:
        return empty_messages, empty_max_tokens, empty_log

    best_keep = 0
    low = 1
    high = len(lines)
    while low <= high:
        mid = (low + high) // 2
        candidate_log = "\n".join(lines[-mid:])
        candidate_messages = build_messages(candidate_log)
        try:
            compute_completion_tokens(
                candidate_messages,
                requested_max_tokens,
                context_limit,
                min_completion_tokens=min_completion_tokens,
                phase=phase,
                log_window_setting=log_window_setting,
            )
        except PromptBudgetError:
            high = mid - 1
        else:
            best_keep = mid
            low = mid + 1

    if best_keep <= 0:
        return empty_messages, empty_max_tokens, empty_log

    trimmed_log = "\n".join(lines[-best_keep:])
    messages = build_messages(trimmed_log)
    max_tokens = compute_completion_tokens(
        messages,
        requested_max_tokens,
        context_limit,
        min_completion_tokens=min_completion_tokens,
        phase=phase,
        log_window_setting=log_window_setting,
    )
    return messages, max_tokens, trimmed_log
