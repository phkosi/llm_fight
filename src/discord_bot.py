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
    session.start()
    await interaction.response.send_message("Fight started")

@fight_group.command(name="status")
async def fight_status(interaction: discord.Interaction):
    await interaction.response.send_message(session.status())

@fight_group.command(name="stop")
async def fight_stop(interaction: discord.Interaction):
    session.stop()
    await interaction.response.send_message("Fight stopped")

bot.tree.add_command(fight_group)


def run_bot() -> None:
    token = CONFIG.get(C.CONFIG_DISCORD, C.CONFIG_DISCORD_TOKEN, str, fallback="")
    if not token:
        raise RuntimeError("Discord token not configured")
    bot.run(token)
