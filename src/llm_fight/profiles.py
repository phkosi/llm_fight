"""Structured fighter profile loading and validation."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from jsonschema import ValidationError, validate

from .anatomy import BodyPart, TissueLayer
from . import config as config_mod
from .config import Config
from .engine import constants as C
from .validation import FighterProfileSchema

_CANONICAL_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_SAFE_TEXT_RE = re.compile(C.EFFECT_SAFE_TEXT_PATTERN)
_FORBIDDEN_TEXT = C.EFFECT_FORBIDDEN_TEXT_FRAGMENTS


class FighterProfileError(ValueError):
    """Raised when a configured fighter profile is unsafe or invalid."""


@dataclass(frozen=True)
class FighterProfile:
    """Validated fighter defaults plus canonical anatomy parts."""

    class_: str | None
    theme: str | None
    loadout: str | None
    environment: str | None
    parts: dict[str, BodyPart]


def _contains_forbidden_text(value: str) -> bool:
    lowered = value.lower()
    return any(fragment in lowered for fragment in _FORBIDDEN_TEXT)


def _safe_text(value: Any, *, field_name: str, max_length: int = C.EFFECT_TEXT_MAX_LENGTH) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise FighterProfileError(f"Profile field '{field_name}' must be a string.")
    text = value.strip()
    if not text:
        return None
    if len(text) > max_length or _contains_forbidden_text(text) or not _SAFE_TEXT_RE.fullmatch(text):
        raise FighterProfileError(f"Profile field '{field_name}' contains unsafe text.")
    return text


def _canonical_part_id(value: Any, *, field_name: str) -> str:
    text = _safe_text(value, field_name=field_name, max_length=C.EFFECT_METADATA_VALUE_MAX_LENGTH)
    if not text:
        raise FighterProfileError(f"Profile field '{field_name}' must not be empty.")
    normalized = text.strip().lower().replace("-", "_").replace(" ", "_")
    if not _CANONICAL_ID_RE.fullmatch(normalized):
        raise FighterProfileError(f"Profile field '{field_name}' must be a canonical snake_case id.")
    return normalized


def _bounded_non_bool_int(value: Any, *, field_name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise FighterProfileError(f"Profile field '{field_name}' must be an integer.")
    if value < minimum or value > maximum:
        raise FighterProfileError(f"Profile field '{field_name}' must be between {minimum} and {maximum}.")
    return value


def _consequence_group(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _canonical_part_id(value, field_name=field_name)


def _consequence_tags(value: Any, *, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise FighterProfileError(f"Profile field '{field_name}' must be a list.")
    tags: list[str] = []
    for tag in value:
        normalized = _canonical_part_id(tag, field_name=f"{field_name}[]")
        if normalized not in C.CONSEQUENCE_ALLOWED_TAGS:
            raise FighterProfileError(f"Profile field '{field_name}' contains unknown consequence tag: {normalized}")
        if normalized not in tags:
            tags.append(normalized)
    return tags


def _validate_consequence_policy(part_id: str, tags: list[str], group: str | None) -> None:
    required_groups = {
        C.CONSEQUENCE_VISION_MEMBER: C.CONSEQUENCE_GROUP_VISION,
        C.CONSEQUENCE_MOBILITY_MEMBER: C.CONSEQUENCE_GROUP_LEGS,
        C.CONSEQUENCE_LEGACY_VITAL_GROUP_MEMBER: C.CONSEQUENCE_GROUP_LEGACY_VITALS,
    }
    for tag, required_group in required_groups.items():
        if tag in tags and group != required_group:
            raise FighterProfileError(
                f"Body part '{part_id}' consequence tag '{tag}' requires consequence_group '{required_group}'."
            )


def build_fighter_profile(raw_profile: dict[str, Any]) -> FighterProfile:
    """Return a validated, normalized profile from raw JSON data."""
    if not isinstance(raw_profile, dict):
        raise FighterProfileError("Fighter profile must be a JSON object.")
    try:
        validate(raw_profile, FighterProfileSchema)
    except ValidationError as exc:
        raise FighterProfileError(f"Invalid fighter profile: {exc.message}") from exc

    raw_parts = raw_profile.get(C.BODY_PARTS, raw_profile.get(C.ANATOMY, []))
    parts: dict[str, BodyPart] = {}
    has_survival_consequence = False
    legacy_vital_count = sum(
        1 for raw_part in raw_parts if bool(raw_part.get("is_vital", False)) and not raw_part.get(C.CONSEQUENCE_TAGS)
    )

    for raw_part in raw_parts:
        part_id = _canonical_part_id(raw_part.get("id"), field_name="body_part.id")
        if part_id in parts:
            raise FighterProfileError(f"Duplicate body part id after normalization: {part_id}")

        display_name = _safe_text(
            raw_part.get(C.NAME, part_id),
            field_name=f"{part_id}.name",
            max_length=C.EFFECT_METADATA_VALUE_MAX_LENGTH,
        )
        layers = []
        layer_names: set[str] = set()
        for raw_layer in raw_part.get("layers", []):
            layer_name = _canonical_part_id(raw_layer.get(C.NAME), field_name=f"{part_id}.layers.name")
            if layer_name in layer_names:
                raise FighterProfileError(f"Duplicate layer name '{layer_name}' in body part '{part_id}'.")
            layer_names.add(layer_name)
            layers.append(
                TissueLayer(
                    name=layer_name,
                    max_hp=_bounded_non_bool_int(
                        raw_layer.get(C.MAX_HP),
                        field_name=f"{part_id}.{layer_name}.max_hp",
                        minimum=1,
                        maximum=500,
                    ),
                )
            )

        is_vital = bool(raw_part.get("is_vital", False))
        consequence_tags = _consequence_tags(
            raw_part.get(C.CONSEQUENCE_TAGS),
            field_name=f"{part_id}.{C.CONSEQUENCE_TAGS}",
        )
        consequence_group = _consequence_group(
            raw_part.get(C.CONSEQUENCE_GROUP),
            field_name=f"{part_id}.{C.CONSEQUENCE_GROUP}",
        )
        if is_vital and not consequence_tags:
            if legacy_vital_count == 1:
                consequence_tags = [C.CONSEQUENCE_FATAL_IF_DESTROYED]
            else:
                consequence_tags = [
                    C.CONSEQUENCE_INCAPACITATING_IF_DESTROYED,
                    C.CONSEQUENCE_LEGACY_VITAL_GROUP_MEMBER,
                ]
                consequence_group = C.CONSEQUENCE_GROUP_LEGACY_VITALS

        _validate_consequence_policy(part_id, consequence_tags, consequence_group)

        if any(
            tag
            in {
                C.CONSEQUENCE_FATAL_IF_DESTROYED,
                C.CONSEQUENCE_INCAPACITATING_IF_DESTROYED,
                C.CONSEQUENCE_LEGACY_VITAL_GROUP_MEMBER,
            }
            for tag in consequence_tags
        ):
            has_survival_consequence = True
        parts[part_id] = BodyPart(
            name=display_name or part_id,
            layers=layers,
            is_vital=is_vital,
            can_be_severed=bool(raw_part.get("can_be_severed", False)),
            bleed_rate=_bounded_non_bool_int(
                raw_part.get(C.BLEED_RATE, 0),
                field_name=f"{part_id}.{C.BLEED_RATE}",
                minimum=0,
                maximum=50,
            ),
            burn_rate=_bounded_non_bool_int(
                raw_part.get(C.BURN_RATE, 0),
                field_name=f"{part_id}.{C.BURN_RATE}",
                minimum=0,
                maximum=50,
            ),
            consequence_tags=consequence_tags,
            consequence_group=consequence_group,
        )

    if not parts:
        raise FighterProfileError("Fighter profile must contain at least one body part.")
    if not has_survival_consequence:
        raise FighterProfileError("Fighter profile must mark at least one body part as vital or terminal.")

    return FighterProfile(
        class_=_safe_text(raw_profile.get(C.CONFIG_FIGHTER_CLASS), field_name=C.CONFIG_FIGHTER_CLASS),
        theme=_safe_text(raw_profile.get(C.THEME), field_name=C.THEME),
        loadout=_safe_text(raw_profile.get(C.LOADOUT), field_name=C.LOADOUT),
        environment=_safe_text(raw_profile.get("environment"), field_name="environment"),
        parts=parts,
    )


def _unique_paths(paths: list[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.resolve()
        if resolved not in seen:
            unique.append(path)
            seen.add(resolved)
    return unique


def resolve_profile_path(reference: str, config: Config | None = None) -> Path | None:
    """Resolve a profile reference to a JSON file, or ``None`` for humanoid."""
    ref = str(reference or "").strip()
    if not ref or ref.lower() == "humanoid":
        return None

    raw_path = Path(ref).expanduser()
    if raw_path.is_absolute():
        candidates = [raw_path]
    else:
        cfg = config or config_mod.CONFIG
        config_base = Path(getattr(cfg, "path", Path.cwd())).expanduser().resolve().parent
        candidates = _unique_paths([config_base / raw_path, Path.cwd() / raw_path])

    for candidate in candidates:
        if candidate.exists():
            return candidate

    searched = ", ".join(str(path) for path in candidates)
    raise FighterProfileError(f"Fighter profile '{ref}' was not found. Searched: {searched}")


def load_fighter_profile(path: Path) -> FighterProfile:
    """Load and validate a fighter profile JSON file."""
    try:
        raw_profile = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FighterProfileError(f"Fighter profile '{path}' is not valid JSON: {exc}") from exc
    return build_fighter_profile(raw_profile)


def resolve_fighter_profile(section: str, config: Config | None = None) -> FighterProfile | None:
    """Resolve the configured profile for a fighter section, if any."""
    cfg = config or config_mod.CONFIG
    reference = cfg.get_fighter_profile_reference(section)
    path = resolve_profile_path(reference or "", config=cfg)
    if path is None:
        return None
    return load_fighter_profile(path)
