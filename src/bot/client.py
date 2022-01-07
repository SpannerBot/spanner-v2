import asyncio
import os
import textwrap
import logging

import discord
import httpx
from discord.ext import commands
from rich.console import Console

from src.utils import utils
from ..database.models import models

__all__ = ("Bot", "bot")

INTENTS = discord.Intents.all()
logger = logging.getLogger(__name__)


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
        if os.getenv("COLOURS", "True").lower() == "false":
            self.console.log = self.console.print
        self.terminal = self.console
        self.started_at = self.last_logged_in = None
        self.loop.run_until_complete(models.create_all())

        self.console.log("Owner IDs:", owner_ids)
        self.console.log("Debug Guild IDs:", guild_ids)

    def run(self):
        extensions = ("debug", "info", "mod", "util", "$jishaku")
        for ext in extensions:
            if ext.startswith("$"):
                try:
                    self.load_extension(ext[1:])
                except discord.ExtensionError as e:
                    logger.error("Failed to load external extension %r" % ext[1:], exc_info=e)
                    self.console.log(f"[red]Failed to load extension: {ext}[/]")
                else:
                    logger.debug("Loaded external extension: %s" % ext[1:])
            else:
                try:
                    self.load_extension(f"src.cogs.{ext}")
                except discord.ExtensionError as e:
                    logger.error("Failed to load internal extension 'src.cogs.%s'" % ext, exc_info=e)
                    self.console.log(f"[red]Failed to load extension: {ext}[/]")
                else:
                    logger.debug("Loaded internal extension: src/cogs/%s.py" % ext)
        self.console.log("Starting bot...")
        self.started_at = discord.utils.utcnow()
        try:
            super().run(os.environ["DISCORD_TOKEN"].strip('"').strip("'"))
        except (TypeError, discord.DiscordException) as e:
            self.on_connection_error(e)
            raise

    def on_connection_error(self, error: Exception):
        class ErrorType:
            type_error = TypeError

        logger.error("Connection error.", exc_info=error)

        # NOTE: This would (and used to) be a match case, but `client.py` has to support py 3.9+
        if isinstance(error, discord.GatewayNotFound):
            self.console.log("[red]Failed to connect to websocket: GatewayNotFound; Perhaps there is an outage?[/]")
        elif isinstance(error, discord.LoginFailure):
            self.console.log("[red]Failed to log in: LoginFailure; check your token is valid.[/]")
        elif isinstance(error, TypeError):
            self.console.log("[red]Failed to log in: TypeError - Invalid token type.")
        else:
            self.console.log("[red]Failed to connect: Unknown error: %r" % error)

    async def sync_commands(self) -> None:
        return await super().sync_commands()

    async def on_connect(self):
        self.console.log("Connected to discord!")
        await super().on_connect()

    async def on_ready(self):
        self.last_logged_in = discord.utils.utcnow()
        self.console.log("Bot is logged in to discord!")
        logger.info("Logged in to discord as %s." % self.user)
        self.console.log(
            "User: [link=%s]%s[/]"
            % (
                discord.utils.oauth_url(self.user.id, scopes="bot+applications.commands"),
                self.user,
            )
        )

    async def on_command(self, ctx: commands.Context):
        logger.debug(
            "Text-command %r invoked by %s in *: %s (#: %s).",
            ctx.command.qualified_name,
            ctx.author,
            ctx.guild.id if ctx.guild else "no-guild",
            ctx.channel.id,
        )
        self.console.log(f"[blue]{ctx.author}[/] used a text command: [b]{ctx.command.qualified_name!r}[/]")

    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type == discord.InteractionType.application_command:
            command_name = interaction.data["name"]
            logger.debug(
                "Interaction-command %r invoked by %s in *: %s (#: %s).",
                command_name,
                interaction.user,
                interaction.guild.id if interaction.guild else "no-guild",
                interaction.channel.id,
            )
            self.console.log(f"[b]{interaction.user}[/] used application command: [b]{command_name}[/]")
        await super().on_interaction(interaction)

    async def on_command_error(self, context: commands.Context, exception: commands.CommandError) -> None:
        if isinstance(exception, commands.CommandNotFound):
            extra = (
                "However, only a few select servers have access at this time. Join discord.gg/TveBeG7 to beta " "test!"
                if self.debug
                else ""
            )
            help_text = textwrap.dedent(
                f"""
                The command you were looking for was not found.
                
                If you want to see a list of commands that are text-based, please run `{context.clean_prefix}help`.
                **Note:** A lot of commands have been moved to discord's application commands.
                Most commands are now slash commands, so you can see them when you run `/`.
                {extra}
                """
            )
            await context.reply(help_text, delete_after=30)
        await super().on_command_error(context, exception)

    async def start(self, token: str, *, reconnect: bool = True) -> None:
        self.console.log("Waiting for network...")
        await self.wait_for_network()
        self.console.log("Network ready!")
        async with utils.SessionWrapper():
            while True:
                try:
                    await super().start(token, reconnect=reconnect)
                except (discord.LoginFailure, discord.HTTPException, OSError):
                    await self.wait_for_network()
                else:
                    break

    @staticmethod
    async def wait_for_network(roof: int = 30) -> int:
        attempts = 0
        time_slept = 0
        while True:
            try:
                logger.debug("Waiting for network - attempt %s", attempts)
                response = await utils.session.get("https://discord.com/api/v9/gateway")
                assert response.status_code == 200
                assert response.headers.get("content-type") == "application/json"
                data = response.json()
                assert data.pop("url").startswith("wss://")
            except (httpx.HTTPError, AssertionError, KeyError, OSError):
                sleep_time = min(attempts, roof)
                logger.warning("Network not ready. Waiting %s seconds before trying again.", sleep_time, exc_info=True)
                attempts += 1
                await asyncio.sleep(sleep_time)
                time_slept += sleep_time
            else:
                logger.debug("Network ready after %s seconds (%s attempts).", time_slept, attempts)
                break
        return attempts


bot = Bot()
