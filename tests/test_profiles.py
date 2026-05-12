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
    assert profile.parts["second_head"].consequence_tags == [C.CONSEQUENCE_FATAL_IF_DESTROYED]
    assert profile.parts["left_wing"].layers[0].current_hp == profile.parts["left_wing"].layers[0].max_hp


def test_from_profile_damage_and_vital_invariants():
    profile = build_fighter_profile(custom_profile())
    fighter = FighterState.from_profile("A", profile)

    wing_hp = sum(layer.current_hp for layer in fighter.parts["left_wing"].layers)
    wing_max_hp = sum(layer.max_hp for layer in fighter.parts["left_wing"].layers)
    fighter.apply_damage_to_part("left_wing", 5, C.DamageType.SLASHING)
    assert sum(layer.current_hp for layer in fighter.parts["left_wing"].layers) == wing_hp - 5
    assert sum(layer.max_hp for layer in fighter.parts["left_wing"].layers) == wing_max_hp

    fighter.apply_damage_to_part("not_a_part", 99, C.DamageType.SLASHING)
    assert "not_a_part" not in fighter.parts

    head_hp = sum(layer.current_hp for layer in fighter.parts["second_head"].layers)
    fighter.apply_damage_to_part("second_head", head_hp, C.DamageType.BLUNT)
    assert fighter.parts["second_head"].status == C.IS_DESTROYED
    assert fighter.status == C.FighterStatus.DEAD


def test_legacy_multi_vital_profile_uses_explicit_aggregate_group():
    profile = build_fighter_profile(
        custom_profile(
            **{
                C.BODY_PARTS: [
                    {
                        "id": "core_a",
                        "is_vital": True,
                        "layers": [{C.NAME: "core", C.MAX_HP: 5}],
                    },
                    {
                        "id": "core_b",
                        "is_vital": True,
                        "layers": [{C.NAME: "core", C.MAX_HP: 5}],
                    },
                ]
            }
        )
    )
    fighter = FighterState.from_profile("A", profile)

    assert profile.parts["core_a"].consequence_tags == [
        C.CONSEQUENCE_INCAPACITATING_IF_DESTROYED,
        C.CONSEQUENCE_LEGACY_VITAL_GROUP_MEMBER,
    ]
    assert profile.parts["core_a"].consequence_group == C.CONSEQUENCE_GROUP_LEGACY_VITALS

    fighter.apply_damage_to_part("core_a", 5, C.DamageType.GENERIC)
    assert fighter.status == C.FighterStatus.UNCONSCIOUS

    fighter.status = C.FighterStatus.FIGHTING
    fighter.apply_damage_to_part("core_b", 5, C.DamageType.GENERIC)
    assert fighter.status == C.FighterStatus.DEAD


def test_explicit_profile_consequence_tags_are_accepted_without_is_vital():
    profile = build_fighter_profile(
        custom_profile(
            **{
                C.BODY_PARTS: [
                    {
                        "id": "glass_core",
                        C.CONSEQUENCE_TAGS: [C.CONSEQUENCE_FATAL_IF_DESTROYED],
                        "layers": [{C.NAME: "crystal", C.MAX_HP: 8}],
                    },
                    {
                        "id": "left_wing",
                        C.CONSEQUENCE_TAGS: [C.CONSEQUENCE_MOBILITY_MEMBER],
                        C.CONSEQUENCE_GROUP: C.CONSEQUENCE_GROUP_LEGS,
                        "layers": [{C.NAME: "feather", C.MAX_HP: 8}],
                    },
                ]
            }
        )
    )

    assert profile.parts["glass_core"].is_vital is False
    assert profile.parts["glass_core"].consequence_tags == [C.CONSEQUENCE_FATAL_IF_DESTROYED]
    assert profile.parts["left_wing"].consequence_group == C.CONSEQUENCE_GROUP_LEGS


@pytest.mark.parametrize(
    ("tag", "group"),
    [
        (C.CONSEQUENCE_LEGACY_VITAL_GROUP_MEMBER, None),
        (C.CONSEQUENCE_LEGACY_VITAL_GROUP_MEMBER, C.CONSEQUENCE_GROUP_LEGS),
        (C.CONSEQUENCE_VISION_MEMBER, None),
        (C.CONSEQUENCE_MOBILITY_MEMBER, C.CONSEQUENCE_GROUP_VISION),
    ],
)
def test_group_member_consequence_tags_require_matching_group(tag, group):
    body_part = {
        "id": "fragile_core",
        C.CONSEQUENCE_TAGS: [C.CONSEQUENCE_FATAL_IF_DESTROYED],
        "layers": [{C.NAME: "crystal", C.MAX_HP: 8}],
    }
    grouped_part = {
        "id": "limb",
        C.CONSEQUENCE_TAGS: [tag],
        "layers": [{C.NAME: "soft", C.MAX_HP: 5}],
    }
    if group is not None:
        grouped_part[C.CONSEQUENCE_GROUP] = group

    profile = custom_profile(**{C.BODY_PARTS: [body_part, grouped_part]})

    with pytest.raises(FighterProfileError, match="requires consequence_group"):
        build_fighter_profile(profile)


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
                "name = Sir Galant",
                f"anatomy_profile = {profile_path.name}",
                "class = Config Champion",
                "loadout = config spear",
                "environment = config bridge",
            ]
        ),
        encoding="utf-8",
    )

    fighter = FighterState.from_config("A", "A", config=Config(config_path))

    assert fighter.display_name == "Sir Galant"
    assert fighter.class_ == "Config Champion"
    assert fighter.loadout == "config spear"
    assert fighter.environment == "config bridge"
    assert "left_wing" in fighter.parts


def test_profile_defaults_override_seeded_a_b_defaults_when_not_explicit(tmp_path):
    profile_path = write_profile(tmp_path / "fighter.json", custom_profile())
    config_path = tmp_path / "game.ini"
    config_path.write_text(f"[A]\nanatomy_profile = {profile_path.name}\n", encoding="utf-8")

    fighter = FighterState.from_config("A", "A", config=Config(config_path))

    assert fighter.display_name == "A"
    assert fighter.class_ == "Winged Duelist"
    assert fighter.loadout == "hook blades and wing spurs"
    assert fighter.environment == "windy arena"
    assert "left_wing" in fighter.parts


def test_display_name_survives_from_preset_and_generated_profile_paths(tmp_path):
    cfg_path = tmp_path / "fighters.ini"
    cfg_path.write_text("[Knight]\nname = Sir Galant\nclass = Knight\nloadout = sword\n", encoding="utf-8")
    cfg = Config(cfg_path)

    preset_fighter = FighterState.from_preset(C.FIGHTER_A, "humanoid", config_section="Knight", config=cfg)
    generated_profile = build_fighter_profile(custom_profile())
    generated_fighter = FighterState.from_profile(
        C.FIGHTER_A,
        generated_profile,
        config_section="Knight",
        config=cfg,
        allow_config_overrides=False,
    )

    assert preset_fighter.id == C.FIGHTER_A
    assert preset_fighter.display_name == "Sir Galant"
    assert generated_fighter.id == C.FIGHTER_A
    assert generated_fighter.display_name == "Sir Galant"


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
