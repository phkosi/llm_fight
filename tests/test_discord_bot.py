import pytest
from unittest.mock import AsyncMock, MagicMock

import llm_fight.discord_bot as discord_bot
from llm_fight.discord_bot import (
    FightSession,
    session,
    fight_start,
    fight_status,
    fight_stop,
    run_bot,
    bot,
)
from llm_fight.engine import constants as C


class DummyResponse:
    def __init__(self):
        self.send_message = AsyncMock()


class DummyInteraction:
    def __init__(self, channel_name="general"):
        self.response = DummyResponse()
        self.channel = DummyChannel(channel_name)


class DummyChannel:
    def __init__(self, name):
        self.name = name
        self.id = name


def test_fight_session_start_stop():
    fs = FightSession()
    assert not fs.active
    fs.start()
    assert fs.active
    assert fs.A is not None and fs.B is not None
    fs.stop()
    assert not fs.active


@pytest.mark.asyncio
async def test_command_flow():
    session.stop()
    i1 = DummyInteraction()
    await fight_start.callback(i1)
    assert session.active
    i1.response.send_message.assert_called_with("Fight started")

    i2 = DummyInteraction()
    await fight_status.callback(i2)
    i2.response.send_message.assert_called_with(session.status())

    i3 = DummyInteraction()
    await fight_stop.callback(i3)
    assert not session.active
    i3.response.send_message.assert_called_with("Fight stopped")


@pytest.mark.asyncio
async def test_channel_restriction(monkeypatch):
    session.stop()
    monkeypatch.setattr("llm_fight.discord_bot.ALLOWED_CHANNEL", "allowed")

    wrong = DummyInteraction("other")
    await fight_start.callback(wrong)
    wrong.response.send_message.assert_called_with("Commands are restricted to allowed", ephemeral=True)
    assert not session.active

    right = DummyInteraction("allowed")
    await fight_start.callback(right)
    assert session.active
    right.response.send_message.assert_called_with("Fight started")


def _patch_config(monkeypatch, token: str, channel: str):
    def fake_get(section, key, cast=str, fallback=None):
        if key == C.CONFIG_DISCORD_TOKEN:
            return token
        if key == C.CONFIG_DISCORD_CHANNEL:
            return channel
        return fallback

    monkeypatch.setattr("llm_fight.discord_bot.config_mod.CONFIG.get", fake_get)


def test_run_bot_missing_token(monkeypatch):
    _patch_config(monkeypatch, token="", channel="mychan")
    with pytest.raises(RuntimeError, match="Discord token not configured"):
        run_bot()


def test_run_bot_missing_channel(monkeypatch):
    _patch_config(monkeypatch, token="token", channel="")
    monkeypatch.setattr(bot, "run", MagicMock())
    run_bot()
    bot.run.assert_called_once_with("token")


def test_run_bot_start_failure(monkeypatch):
    _patch_config(monkeypatch, token="token", channel="chan")
    monkeypatch.setattr(bot, "run", MagicMock(side_effect=ValueError("boom")))
    with pytest.raises(RuntimeError, match="Failed to start Discord bot: boom"):
        run_bot()
    assert discord_bot.ALLOWED_CHANNEL == "chan"
