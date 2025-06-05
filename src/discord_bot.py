import discord
from discord.ext import commands
from discord import app_commands

from .state import FighterState
from .engine.combat_log import CombatLog
from .engine.logger import logger
from .engine import constants as C
from .config import CONFIG

class FightSession:
    """Simple container for an active fight."""
    def __init__(self) -> None:
        self.active: bool = False
        self.A: FighterState | None = None
        self.B: FighterState | None = None
        self.log: CombatLog = CombatLog()

    def start(self) -> None:
        logger.info("Starting new fight session")
        self.A = FighterState.from_preset('A', 'humanoid')
        self.B = FighterState.from_preset('B', 'humanoid')
        self.log = CombatLog()
        self.active = True

    def stop(self) -> None:
        logger.info("Stopping fight session")
        self.active = False

    def status(self) -> str:
        if not self.active:
            return "No active fight"
        return f"Turns: {len(self.log)} - A {self.A.status} / B {self.B.status}"

session = FightSession()

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

fight_group = app_commands.Group(name="fight", description="Fight control")

@fight_group.command(name="start")
async def fight_start(interaction: discord.Interaction):
    if not _check_channel(interaction):
        await interaction.response.send_message(
            f"Commands are restricted to {ALLOWED_CHANNEL}", ephemeral=True
        )
        return
    session.start()
    await interaction.response.send_message("Fight started")

@fight_group.command(name="status")
async def fight_status(interaction: discord.Interaction):
    if not _check_channel(interaction):
        await interaction.response.send_message(
            f"Commands are restricted to {ALLOWED_CHANNEL}", ephemeral=True
        )
        return
    await interaction.response.send_message(session.status())

@fight_group.command(name="stop")
async def fight_stop(interaction: discord.Interaction):
    if not _check_channel(interaction):
        await interaction.response.send_message(
            f"Commands are restricted to {ALLOWED_CHANNEL}", ephemeral=True
        )
        return
    session.stop()
    await interaction.response.send_message("Fight stopped")

bot.tree.add_command(fight_group)

# channel name or id allowed to invoke commands; set in run_bot()
ALLOWED_CHANNEL: str = ""


def _check_channel(interaction: discord.Interaction) -> bool:
    """Return True if commands are allowed in this interaction's channel."""
    if not ALLOWED_CHANNEL:
        return True
    channel = getattr(interaction, "channel", None)
    if channel is None:
        return False
    name = getattr(channel, "name", None)
    cid = getattr(channel, "id", None)
    return str(name) == ALLOWED_CHANNEL or str(cid) == ALLOWED_CHANNEL


def run_bot() -> None:
    token = CONFIG.get(C.CONFIG_DISCORD, C.CONFIG_DISCORD_TOKEN, str, fallback="").strip()
    channel = CONFIG.get(C.CONFIG_DISCORD, C.CONFIG_DISCORD_CHANNEL, str, fallback="").strip()

    if not token:
        raise RuntimeError("Discord token not configured")

    global ALLOWED_CHANNEL
    ALLOWED_CHANNEL = channel

    try:
        bot.run(token)
    except Exception as e:  # Catch discord.py startup errors
        logger.error("Failed to start Discord bot", exc_info=True)
        raise RuntimeError(f"Failed to start Discord bot: {e}") from e
