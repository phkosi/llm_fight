"""Chat result and provider metadata helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ChatResult:
    """Text response plus provider metadata when the transport supplies it."""

    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


def metadata_from_response(data: dict[str, Any], *, use_openai: bool) -> dict[str, Any]:
    """Extract real provider metadata without inventing missing token counts."""
    metadata: dict[str, Any] = {}
    if use_openai:
        usage = data.get("usage", {})
        if isinstance(usage, dict):
            mapping = {
                "prompt_tokens": "prompt_tokens",
                "completion_tokens": "completion_tokens",
                "total_tokens": "total_tokens",
            }
            for source, target in mapping.items():
                if usage.get(source) is not None:
                    metadata[target] = usage[source]
        return metadata

    native_mapping = {
        "prompt_eval_count": "prompt_tokens",
        "eval_count": "completion_tokens",
        "total_duration": "total_duration",
        "load_duration": "load_duration",
        "prompt_eval_duration": "prompt_eval_duration",
        "eval_duration": "eval_duration",
        "done_reason": "done_reason",
    }
    for source, target in native_mapping.items():
        if data.get(source) is not None:
            metadata[target] = data[source]
            if target != source:
                metadata[source] = data[source]
    prompt_tokens = metadata.get("prompt_tokens")
    completion_tokens = metadata.get("completion_tokens")
    if isinstance(prompt_tokens, int) and isinstance(completion_tokens, int):
        metadata["total_tokens"] = prompt_tokens + completion_tokens
    return metadata
