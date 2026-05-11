from llm_fight.anatomy import compose_humanoid, PRESETS, BodyPart


def _assert_basic_vitals(preset):
    for part in ("head", "torso", "heart"):
        assert part in preset.parts, f"{part} missing from preset"
        assert isinstance(preset.parts[part], BodyPart)
        assert preset.parts[part].is_vital, f"{part} should be marked vital"


def test_compose_humanoid_has_expected_vitals():
    preset = compose_humanoid()
    assert preset.name == "humanoid"
    _assert_basic_vitals(preset)


def test_presets_humanoid_matches_compose():
    from_dict = PRESETS.get("humanoid")
    assert from_dict is not None
    assert from_dict.name == "humanoid"
    _assert_basic_vitals(from_dict)

    recomposed = compose_humanoid()
    assert set(from_dict.parts.keys()) == set(recomposed.parts.keys())
    for name in from_dict.parts:
        assert from_dict.parts[name].is_vital == recomposed.parts[name].is_vital


def test_compose_humanoid_body_parts_do_not_share_tissue_layers():
    preset = compose_humanoid()
    head_skin = preset.parts["head"].layers[0]
    torso_skin = preset.parts["torso"].layers[0]

    assert head_skin is not torso_skin

    head_skin.max_hp -= 3
    assert torso_skin.max_hp == 10
