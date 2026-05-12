from unittest.mock import AsyncMock, patch

from click import ClickException
from typer.testing import CliRunner

from llm_fight.cli import app


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Usage" in result.output


def test_cli_unknown_option():
    runner = CliRunner()
    result = runner.invoke(app, ["simulate", "--unknown"])
    assert result.exit_code != 0
    assert "No such option" in result.output


def test_cli_missing_option_value():
    runner = CliRunner()
    result = runner.invoke(app, ["simulate", "--output-csv"])
    assert result.exit_code != 0
    assert "requires an argument" in result.output


def test_cli_invalid_path():
    runner = CliRunner()
    with (
        patch(
            "llm_fight.simulation.run_batch",
            new=AsyncMock(side_effect=ClickException("invalid path")),
        ),
        patch("llm_fight.cli.ping_ollama", new=AsyncMock()),
    ):
        result = runner.invoke(app, ["simulate", "--output-csv", "bad/out.csv"])
    assert result.exit_code != 0
    assert "invalid path" in result.output


def test_cli_invalid_config_file(tmp_path):
    runner = CliRunner()
    cfg = tmp_path / "bad.ini"
    cfg.write_text("not an ini file")

    result = runner.invoke(app, ["play", "--config", str(cfg), "--simple-output"])

    assert result.exit_code != 0
    assert "Could not read config file" in result.output


def test_cli_unexpected_argument():
    runner = CliRunner()
    result = runner.invoke(app, ["play", "extra"])
    assert result.exit_code != 0
    assert "unexpected extra argument" in result.output


def test_cli_ollama_unreachable():
    runner = CliRunner()
    with patch("llm_fight.cli.ping_ollama", new=AsyncMock(side_effect=ConnectionError("offline"))):
        result = runner.invoke(app, ["play"])
    assert result.exit_code != 0
    assert "offline" in result.output
