import os
import textwrap

import discord
from discord.ext import commands
from rich.console import Console

from src.utils import utils
from ..database.models import models

__all__ = ("Bot", "bot")

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
            activity=discord.Activity(name="s!help | check my bio!", type=discord.ActivityType.watching),
            allowed_mentions=discord.AllowedMentions(
                everyone=False,
                users=True,
                roles=False,  # can be overridden at message create level, so does not disable features.
                replied_user=True,
            ),
            debug_guilds=guild_ids,
            owner_ids=owner_ids,
        )

        self.debug = is_debug
        self.console = Console()
        self.terminal = self.console
        self.started_at = self.last_logged_in = None
        self.loop.run_until_complete(models.create_all())

        self.console.log("Owner IDs:", owner_ids)
        self.console.log("Debug Guild IDs:", guild_ids)

    def run(self):
        self.load_extension("src.cogs.debug")
        self.load_extension("src.cogs.info")
        self.load_extension("src.cogs.mod")
        self.load_extension("jishaku")
        self.console.log("Starting bot...")
        self.started_at = discord.utils.utcnow()
        super().run(os.environ["DISCORD_TOKEN"])

    async def sync_commands(self) -> None:
        return await super().sync_commands()

    async def on_connect(self):
        self.console.log("Connected to discord!")
        await super().on_connect()

    async def on_ready(self):
        self.last_logged_in = discord.utils.utcnow()
        self.console.log("Bot is logged in to discord!")
        self.console.log("User: [%s](%s)" % (self.user, discord.utils.oauth_url(self.user.id)))

    async def on_command(self, ctx: commands.Context):
        self.console.log(f"[blue]{ctx.author}[/] used a text command: [b]{ctx.command.qualified_name!r}[/]")

    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type == discord.InteractionType.application_command:
            command_name = interaction.data["name"]
            self.console.log(f"[b]{interaction.user}[/] used application command: [b]{command_name}[/]")
        await super().on_interaction(interaction)

    async def on_command_error(self, context: commands.Context, exception: commands.CommandError) -> None:
        if isinstance(exception, commands.CommandNotFound):
            help_text = textwrap.dedent(
                f"""
                The command you were looking for was not found.
                
                If you want to see a list of commands that are text-based, please run `{context.clean_prefix}help`.
                **Note:** A lot of commands have been moved to discord's application commands.
                Most commands are now slash commands, so you can see them when you run `/`.
                {'However, only a few select servers have access at this time. Join discord.gg/TveBeG7 to beta test!' if self.debug else ''}
                """
            )
            await context.reply(help_text)
        await super().on_command_error(context, exception)


bot = Bot()
