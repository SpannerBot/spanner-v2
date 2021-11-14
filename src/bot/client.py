import os

import discord
from pathlib import Path
from discord.ext import commands
from dotenv import load_dotenv
from rich.console import Console

from ..database.models import models
from .. import utils

INTENTS = discord.Intents.all()


class Bot(commands.Bot):
    def __init__(self):
        owner_ids = set(map(int, (os.environ["OWNER_IDS"]).split(":")))
        guild_ids = set(map(int, (os.environ["SLASH_GUILDS"]).split(":")))
        is_debug = os.environ["DEBUG"].lower() == "true"
        if not is_debug:
            guild_ids = None

        super().__init__(
            command_prefix=utils.get_prefix,
            description="eek's personal helper, re-written! | source code: https://github.com/EEKIM10/spanner-v2",
            max_messages=5_000,
            intents=INTENTS,
            chunk_guilds_on_startup=False,
            status=discord.Status.idle,
            activity=discord.Activity(
                name="s!help | check my bio!", type=discord.ActivityType.watching
            ),
            allowed_mentions=discord.AllowedMentions(
                everyone=False,
                users=True,
                roles=False,  # can be overridden at message create level, so does not disable features.
                replied_user=True
            ),
            debug_guilds=guild_ids,
            owner_ids=owner_ids,
        )

        self.debug = is_debug
        self.console = Console()
        self.terminal = self.console
        models.create_all()

        self.console.log("Owner IDs:", owner_ids)
        self.console.log("Debug Guild IDs:", guild_ids)

    def run(self):
        self.load_extension("src.cogs.debug")
        self.console.log("Starting bot...")
        super().run(os.environ["DISCORD_TOKEN"])

    async def sync_commands(self) -> None:
        return await super().sync_commands()

    async def on_connect(self):
        self.console.log("Connected to discord!")
        await super().on_connect()

    async def on_ready(self):
        self.console.log("Bot is logged in to discord!")
        self.console.log("User: [%s](%s)" % (self.user, discord.utils.oauth_url(self.user.id)))


bot = Bot()
