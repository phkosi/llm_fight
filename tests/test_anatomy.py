from llm_fight.anatomy import compose_humanoid, PRESETS, BodyPart
from llm_fight.engine import constants as C


def _assert_basic_vitals(preset):
    for part in ("head", "torso", "heart"):
        assert part in preset.parts, f"{part} missing from preset"
        assert isinstance(preset.parts[part], BodyPart)
        assert preset.parts[part].is_vital, f"{part} should be marked vital"


def test_compose_humanoid_has_expected_vitals():
    preset = compose_humanoid()
    assert preset.name == "humanoid"
    _assert_basic_vitals(preset)
    assert preset.parts["heart"].consequence_tags == [C.CONSEQUENCE_FATAL_IF_DESTROYED]
    assert preset.parts["head"].consequence_tags == [C.CONSEQUENCE_FATAL_IF_DESTROYED]
    assert preset.parts["torso"].consequence_tags == [C.CONSEQUENCE_INCAPACITATING_IF_DESTROYED]
    assert preset.parts["torso"].bleed_rate == 2
    assert preset.parts["torso"].burn_rate == 1
    assert preset.parts["head"].bleed_rate == 1
    assert preset.parts["heart"].bleed_rate == 3
    assert preset.parts["left_eye"].consequence_tags == [C.CONSEQUENCE_VISION_MEMBER]
    assert preset.parts["left_eye"].consequence_group == C.CONSEQUENCE_GROUP_VISION
    assert preset.parts["left_eye"].bleed_rate == 0
    assert preset.parts["right_leg"].consequence_tags == [C.CONSEQUENCE_MOBILITY_MEMBER]
    assert preset.parts["right_leg"].consequence_group == C.CONSEQUENCE_GROUP_LEGS
    assert preset.parts["right_leg"].bleed_rate == 1
    assert preset.parts["right_leg"].burn_rate == 1


def test_presets_humanoid_matches_compose():
    from_dict = PRESETS.get("humanoid")
    assert from_dict is not None
    assert from_dict.name == "humanoid"
    _assert_basic_vitals(from_dict)

    recomposed = compose_humanoid()
    assert set(from_dict.parts.keys()) == set(recomposed.parts.keys())
    for name in from_dict.parts:
        assert from_dict.parts[name].is_vital == recomposed.parts[name].is_vital
        assert from_dict.parts[name].consequence_tags == recomposed.parts[name].consequence_tags
        assert from_dict.parts[name].consequence_group == recomposed.parts[name].consequence_group


def test_compose_humanoid_body_parts_do_not_share_tissue_layers():
    preset = compose_humanoid()
    head_skin = preset.parts["head"].layers[0]
    torso_skin = preset.parts["torso"].layers[0]

    assert head_skin is not torso_skin

    head_skin.current_hp -= 3
    assert head_skin.max_hp == 10
    assert torso_skin.current_hp == 10
    assert torso_skin.max_hp == 10


def test_compose_humanoid_initializes_current_hp_from_max_hp():
    preset = compose_humanoid()

    for part in preset.parts.values():
        for layer in part.layers:
            assert layer.current_hp == layer.max_hp
