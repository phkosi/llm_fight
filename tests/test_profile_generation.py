import json
from unittest.mock import AsyncMock, patch

import pytest

from llm_fight.config import Config
from llm_fight.engine import constants as C
from llm_fight.profile_generation import (
    PROFILE_GENERATOR_EXAMPLE,
    PROFILE_GENERATOR_SYSTEM_PROMPT,
    ProfileGenerationError,
    generate_fighter_profile,
)
from llm_fight.profiles import build_fighter_profile


def _valid_generated_profile():
    return {
        C.CONFIG_FIGHTER_CLASS: "Rune Beast",
        C.THEME: "rune stone",
        C.LOADOUT: "stone claws and a focus crystal",
        "environment": "open arena",
        C.BODY_PARTS: [
            {
                "id": "core",
                C.NAME: "core",
                "is_vital": True,
                C.CONSEQUENCE_TAGS: [C.CONSEQUENCE_FATAL_IF_DESTROYED],
                "layers": [{C.NAME: "stone", C.MAX_HP: 24}],
            },
            {
                "id": "focus_crystal",
                C.NAME: "focus_crystal",
                "can_be_severed": True,
                "layers": [{C.NAME: "crystal", C.MAX_HP: 12}],
            },
        ],
    }


def test_profile_prompt_and_example_guard_schema_reliability():
    prompt = PROFILE_GENERATOR_SYSTEM_PROMPT.lower()

    assert "exactly these top-level keys" in prompt
    assert '"body_parts"' in prompt
    assert "never use null" in prompt
    assert "omit optional keys" in prompt
    assert "current_hp" in prompt
    assert "fatal_if_destroyed" in prompt
    assert "mobility_member" in prompt
    profile = build_fighter_profile(PROFILE_GENERATOR_EXAMPLE)
    assert "tail" in profile.parts


@pytest.mark.asyncio
async def test_generate_fighter_profile_budget_error_is_sanitized_fallback(tmp_path):
    cfg_path = tmp_path / "tiny.ini"
    cfg_path.write_text(
        "\n".join(
            [
                "[General]",
                "max_tokens_judge = 64",
                "ollama_num_ctx = 80",
                "",
                "[A]",
                "class = Knight",
                "",
                "[B]",
                "class = Assassin",
            ]
        ),
        encoding="utf-8",
    )
    cfg = Config(cfg_path)

    with (
        patch("llm_fight.profile_generation.chat", new=AsyncMock()) as mock_chat,
        pytest.raises(ProfileGenerationError) as exc_info,
    ):
        await generate_fighter_profile(
            C.FIGHTER_A,
            C.FIGHTER_A,
            C.FIGHTER_B,
            "warrior",
            config=cfg,
        )

    assert exc_info.value.code == C.PROFILE_GENERATION_ERROR_FAILED
    mock_chat.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_fighter_profile_payload_guides_valid_anatomy(tmp_path):
    cfg_path = tmp_path / "llmfight.ini"
    cfg_path.write_text(
        "\n".join(
            [
                "[General]",
                "max_tokens_judge = 4096",
                "ollama_num_ctx = 90000",
                "",
                "[A]",
                "class = Knight",
                "",
                "[B]",
                "class = Assassin",
            ]
        ),
        encoding="utf-8",
    )
    cfg = Config(cfg_path)
    captured: dict[str, object] = {}

    async def fake_chat(messages, **kwargs):
        captured["messages"] = messages
        captured["kwargs"] = kwargs
        return [json.dumps(_valid_generated_profile())]

    with patch("llm_fight.profile_generation.chat", new=AsyncMock(side_effect=fake_chat)):
        profile = await generate_fighter_profile(
            C.FIGHTER_A,
            C.FIGHTER_A,
            C.FIGHTER_B,
            "mage",
            config=cfg,
        )

    messages = captured["messages"]
    assert isinstance(messages, list)
    payload = json.loads(messages[1][C.AGENT_CONTENT])
    assert profile.class_ == "Rune Beast"
    assert payload["output_contract"]["top_level_keys"] == [
        C.CONFIG_FIGHTER_CLASS,
        C.THEME,
        C.LOADOUT,
        "environment",
        C.BODY_PARTS,
    ]
    assert payload["output_contract"]["null_policy"] == "Never use null values. Omit optional keys instead."
    assert "class_" in payload["output_contract"]["forbidden_top_level_keys"]
    assert C.ANATOMY in payload["output_contract"]["forbidden_top_level_keys"]
    assert C.CONSEQUENCE_GROUP in payload["body_part_contract"]["allowed_keys"]
    assert payload["body_part_contract"]["grouped_tags"][C.CONSEQUENCE_MOBILITY_MEMBER] == C.CONSEQUENCE_GROUP_LEGS
    assert C.CONSEQUENCE_FATAL_IF_DESTROYED in payload["allowed_consequence_tags"]
    assert "mana_core" in payload["nudge_guidance"]
    assert "valid_example" in payload


@pytest.mark.asyncio
async def test_generate_fighter_profile_accepts_third_validation_attempt(tmp_path):
    cfg_path = tmp_path / "llmfight.ini"
    cfg_path.write_text(
        "\n".join(
            [
                "[General]",
                "max_tokens_judge = 4096",
                "ollama_num_ctx = 90000",
                "",
                "[A]",
                "class = Knight",
                "",
                "[B]",
                "class = Assassin",
            ]
        ),
        encoding="utf-8",
    )
    cfg = Config(cfg_path)
    responses = [
        json.dumps({"class_": "Bad", C.BODY_PARTS: []}),
        json.dumps({C.CONFIG_FIGHTER_CLASS: "Still Bad", C.THEME: "bad"}),
        json.dumps(_valid_generated_profile()),
    ]

    async def fake_chat(*args, **kwargs):
        return [responses.pop(0)]

    with patch("llm_fight.profile_generation.chat", new=AsyncMock(side_effect=fake_chat)) as mock_chat:
        profile = await generate_fighter_profile(
            C.FIGHTER_A,
            C.FIGHTER_A,
            C.FIGHTER_B,
            "monster",
            config=cfg,
        )

    assert profile.class_ == "Rune Beast"
    assert mock_chat.await_count == 3
