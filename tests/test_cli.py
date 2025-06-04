from typer.testing import CliRunner

from src.cli import app
from unittest.mock import AsyncMock, patch
from src.engine import constants as C


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Usage" in result.output


def test_cli_play():
    runner = CliRunner()
    fake_result = {C.WINNER: "A", C.LOG_TURN: "1"}
    with patch("src.simulation._single_fight", new=AsyncMock(return_value=fake_result)):
        result = runner.invoke(app, ["play"])
    assert result.exit_code == 0
    assert "Winner: A" in result.output
