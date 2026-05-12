from unittest.mock import AsyncMock, patch

import pytest

from llm_fight.config import Config
from llm_fight.engine import constants as C
from llm_fight.profile_generation import ProfileGenerationError, generate_fighter_profile


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
