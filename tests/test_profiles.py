import json

import pytest

from llm_fight.config import Config
from llm_fight.engine import constants as C
from llm_fight.profiles import FighterProfileError, build_fighter_profile, resolve_fighter_profile
from llm_fight.state import FighterState


def custom_profile(**overrides):
    profile = {
        C.CONFIG_FIGHTER_CLASS: "Winged Duelist",
        C.THEME: "sky hunter",
        C.LOADOUT: "hook blades and wing spurs",
        "environment": "windy arena",
        C.BODY_PARTS: [
            {
                "id": "second_head",
                C.NAME: "second head",
                "is_vital": True,
                "layers": [{C.NAME: "bone", C.MAX_HP: 10}],
            },
            {
                "id": "left_wing",
                C.NAME: "left wing",
                "can_be_severed": True,
                C.BLEED_RATE: 2,
                C.BURN_RATE: 1,
                "layers": [
                    {C.NAME: "feathers", C.MAX_HP: 8},
                    {C.NAME: "muscle", C.MAX_HP: 12},
                ],
            },
            {
                "id": "tail",
                C.NAME: "tail",
                "can_be_severed": True,
                "layers": [{C.NAME: "muscle", C.MAX_HP: 14}],
            },
        ],
    }
    profile.update(overrides)
    return profile


def write_profile(path, profile=None):
    path.write_text(json.dumps(profile or custom_profile()), encoding="utf-8")
    return path


def test_build_fighter_profile_creates_non_humanoid_parts():
    profile = build_fighter_profile(custom_profile())

    assert set(profile.parts) == {"second_head", "left_wing", "tail"}
    assert profile.parts["left_wing"].can_be_severed is True
    assert profile.parts["second_head"].is_vital is True


def test_from_profile_damage_and_vital_invariants():
    profile = build_fighter_profile(custom_profile())
    fighter = FighterState.from_profile("A", profile)

    wing_hp = sum(layer.max_hp for layer in fighter.parts["left_wing"].layers)
    fighter.apply_damage_to_part("left_wing", 5, C.DamageType.SLASHING)
    assert sum(layer.max_hp for layer in fighter.parts["left_wing"].layers) == wing_hp - 5

    fighter.apply_damage_to_part("not_a_part", 99, C.DamageType.SLASHING)
    assert "not_a_part" not in fighter.parts

    head_hp = sum(layer.max_hp for layer in fighter.parts["second_head"].layers)
    fighter.apply_damage_to_part("second_head", head_hp, C.DamageType.BLUNT)
    assert fighter.parts["second_head"].status == C.IS_DESTROYED
    assert fighter.status == C.FighterStatus.DEAD


def test_relative_profile_paths_resolve_config_dir_before_cwd(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    cwd_dir = tmp_path / "cwd"
    config_dir.mkdir()
    cwd_dir.mkdir()
    write_profile(config_dir / "fighter.json", custom_profile())
    write_profile(
        cwd_dir / "fighter.json",
        custom_profile(
            **{
                C.BODY_PARTS: [
                    {
                        "id": "cwd_only_core",
                        "is_vital": True,
                        "layers": [{C.NAME: "core", C.MAX_HP: 5}],
                    }
                ]
            }
        ),
    )
    config_path = config_dir / "game.ini"
    config_path.write_text("[A]\nanatomy_profile = fighter.json\n", encoding="utf-8")

    monkeypatch.chdir(cwd_dir)
    profile = resolve_fighter_profile("A", config=Config(config_path))

    assert "left_wing" in profile.parts
    assert "cwd_only_core" not in profile.parts


def test_conflicting_profile_aliases_raise(tmp_path):
    config_path = tmp_path / "game.ini"
    config_path.write_text("[A]\nanatomy_profile = a.json\nprofile = b.json\n", encoding="utf-8")

    with pytest.raises(ValueError, match="anatomy_profile and profile"):
        resolve_fighter_profile("A", config=Config(config_path))


def test_fighter_section_settings_override_profile_defaults(tmp_path):
    profile_path = write_profile(tmp_path / "fighter.json", custom_profile())
    config_path = tmp_path / "game.ini"
    config_path.write_text(
        "\n".join(
            [
                "[A]",
                f"anatomy_profile = {profile_path.name}",
                "class = Config Champion",
                "loadout = config spear",
                "environment = config bridge",
            ]
        ),
        encoding="utf-8",
    )

    fighter = FighterState.from_config("A", "A", config=Config(config_path))

    assert fighter.class_ == "Config Champion"
    assert fighter.loadout == "config spear"
    assert fighter.environment == "config bridge"
    assert "left_wing" in fighter.parts


def test_profile_defaults_override_seeded_a_b_defaults_when_not_explicit(tmp_path):
    profile_path = write_profile(tmp_path / "fighter.json", custom_profile())
    config_path = tmp_path / "game.ini"
    config_path.write_text(f"[A]\nanatomy_profile = {profile_path.name}\n", encoding="utf-8")

    fighter = FighterState.from_config("A", "A", config=Config(config_path))

    assert fighter.class_ == "Winged Duelist"
    assert fighter.loadout == "hook blades and wing spurs"
    assert fighter.environment == "windy arena"
    assert "left_wing" in fighter.parts


def test_invalid_profile_without_vital_part_is_rejected():
    profile = custom_profile(
        **{
            C.BODY_PARTS: [
                {
                    "id": "tail",
                    "layers": [{C.NAME: "muscle", C.MAX_HP: 10}],
                }
            ]
        }
    )

    with pytest.raises(FighterProfileError, match="vital"):
        build_fighter_profile(profile)
