"""Shared helpers for Judge Phase 2 authorization."""

from __future__ import annotations

from typing import Any

from .engine import constants as C
from .engine.logger import logger


def _attempts_both_invalid_and_failed(p1: dict[str, Any], rolls: dict[str, bool]) -> bool:
    return (
        not rolls.get(C.FIGHTER_A, False)
        and not rolls.get(C.FIGHTER_B, False)
        and not p1.get(f"{C.ATTEMPT}_{C.FIGHTER_A}_valid", False)
        and not p1.get(f"{C.ATTEMPT}_{C.FIGHTER_B}_valid", False)
    )


def _authorized_phase2_sources(p1: dict[str, Any], rolls: dict[str, bool]) -> set[str]:
    return {
        fighter_id
        for fighter_id in (C.FIGHTER_A, C.FIGHTER_B)
        if rolls.get(fighter_id, False) and p1.get(f"{C.ATTEMPT}_{fighter_id}_valid", False)
    }


def _is_authorized_consequence(entry: Any, authorized_sources: set[str], field_name: str) -> bool:
    if not isinstance(entry, dict):
        logger.warning("Dropping Judge Phase 2 %s consequence without source object.", field_name)
        return False
    source = entry.get(C.SOURCE)
    if source not in authorized_sources:
        logger.warning(
            "Dropping Judge Phase 2 %s consequence from unauthorized source %r.",
            field_name,
            source,
        )
        return False
    return True


def _copy_without_source(entry: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(entry)
    sanitized.pop(C.SOURCE, None)
    return sanitized


def _phase2_validation_warning(
    *,
    code: str,
    fighter_id: str,
    field: str,
    source: Any,
    action: str,
    reason: str | None = None,
    canonical_part: str | None = None,
) -> dict[str, Any]:
    warning = {
        "code": code,
        "phase": "judge_phase2",
        "fighter_id": fighter_id,
        "field": field,
        "action": action,
    }
    if source in {C.FIGHTER_A, C.FIGHTER_B}:
        warning[C.SOURCE] = source
    if reason:
        warning["reason"] = reason
    if canonical_part:
        warning["canonical_part"] = canonical_part
    return warning


def _warning_key(warning: dict[str, Any]) -> tuple[Any, Any]:
    return warning.get("code"), warning.get("field")


def _merge_phase2_warnings(*warning_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen = set()
    for warnings in warning_groups:
        for warning in warnings:
            key = _warning_key(warning)
            if key in seen:
                continue
            seen.add(key)
            merged.append(warning)
    return merged
