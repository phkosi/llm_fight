import pytest
from unittest.mock import AsyncMock

from src.discord_bot import FightSession, session, fight_start, fight_status, fight_stop

class DummyResponse:
    def __init__(self):
        self.send_message = AsyncMock()

class DummyInteraction:
    def __init__(self):
        self.response = DummyResponse()


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
