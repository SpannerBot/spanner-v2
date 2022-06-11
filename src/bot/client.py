import asyncio
import json
import logging
import os
import random
import textwrap
import traceback
import warnings
from pathlib import Path
from typing import List, Optional, Dict, Type, Union, TYPE_CHECKING

import discord
import httpx
from discord import ApplicationCommand
from discord.ext import commands
from rich.console import Console

from src.utils import utils
from ..database import *
from ..database.models import models as db_model

__all__ = ("Bot", "bot")

from ..utils.views import SimplePollView
from ..utils.utils import load_colon_int_list

INTENTS = discord.Intents.default()
logger = logging.getLogger(__name__)


class Bot(commands.Bot):
    if TYPE_CHECKING:
        config: Optional[Dict[str, Union[str, int, float, dict, list, bool, type(None)]]]

    def __init__(self):
        self.console = Console()
        if os.getenv("COLOURS", "True").lower() == "false":
            self.console.log = self.console.print
        self.home = Path(__file__).parents[1]  # /src directory.
        if (self.home / ".." / "config.json").exists():
            with (self.home / ".." / "config.json").open() as config_file:
                loaded = json.load(config_file)
                self.config: Dict[str, Union[str, int, float, dict, list, bool, type(None)]] = loaded
                logger.debug("Loaded config.json")
        else:
            logger.warning("No config.json file exists - falling back to environment variables")
            self.config = None

        if self.config is None:
            _owner_ids = os.getenv("OWNER_IDS")
            if _owner_ids:
                owner_ids = load_colon_int_list(_owner_ids)
            else:
                owner_ids = None
            guild_ids = load_colon_int_list(os.getenv("SLASH_GUILDS", ""))
            is_debug = os.environ["DEBUG"].lower() == "true"
            if not is_debug:
                guild_ids = None
        else:
            owner_ids: Optional[List[int]] = self.get_config_value("owner_ids")
            guild_ids: Optional[List[int]] = self.get_config_value("slash_guilds")
            is_debug: bool = self.get_config_value("debug_mode", "debug")

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

        self.debug = is_debug and guild_ids is not None and len(guild_ids) > 0
        self.terminal = self.console
        self.started_at = self.last_logged_in = None
        self.loop.create_task(db_model.create_all())
        logger.debug("Project home is at %r, and CWD is %r." % (str(self.home.absolute()), str(os.getcwd())))

        if self.owner_ids is not None:
            self.console.log("Owner IDs: %s" % ", ".join(str(x) for x in self.owner_ids))
        if self.debug is not False and guild_ids is not None:
            self.console.log("Debug Guild IDs: %s" % ", ".join(str(x) for x in guild_ids))

    def get_config_value(self, *names: str) -> Union[str, int, float, dict, list, bool, type(None)]:
        """Fetches a config value.

        Lookup is in this order:
            1. config file
            2. environment variables

        names may be multiple names to signify a value that may have had its name changed in the config system
        from when it was an environment variable
        """
        def get(_name: str):
            _r = self.config.get(_name, ...)
            _r2 = self.config.get(_name.lower(), ...)
            _r3 = self.config.get(_name.upper(), ...)
            for _v in (_r, _r2, _r3):
                if _v is not ...:
                    return _v
            return ...

        value = ...
        for name in names:
            if self.config is not None:
                value = get(name)
            else:
                value = os.getenv(name.upper(), ...)
            if value is not ...:
                break

        return value or None

    def _select_token(self) -> str:
        # Selects the token that should be used to run.
        # Basically, use the main token when not in debug mode, but look for a dev token before falling back in dev mode
        primary = self.get_config_value("BOT_TOKEN")
        old = self.get_config_value("DISCORD_TOKEN")
        if bool(old) is False:
            warnings.warn(
                DeprecationWarning("The environment variable `DISCORD_TOKEN` is deprecated in favour of `BOT_TOKEN`.")
            )
            primary = old

        assert primary is not None, "No production token. Please set the BOT_TOKEN environment variable."

        if self.debug:
            debug_token = self.get_config_value("DEV_BOT_TOKEN")
            if debug_token:
                primary = debug_token

        return primary

    async def launch(self):
        def try_load(stripped_path: str, ext_type: str, mandatory: bool) -> None:
            try:
                logger.debug("Loading %r" % stripped_path)
                self.load_extension(stripped_path)
                if self.debug:
                    logger.debug("Loaded extension %s." % stripped_path)
            except (discord.ExtensionError, Exception) as error:
                error = getattr(error, "original", error)
                logger.error(f"Failed to load {ext_type} extension %r" % ext[1:], exc_info=error)
                self.console.log(f"[red]Failed to load extension {ext} - {error!s}[/]")
                if mandatory:
                    self.console.log(f"[red][bold]Extension is marked as critical to functionality[/] - crashing!")
                    raise RuntimeError(f"Failed to load crucial extension {ext!r}.") from error

        # KEY:
        # ! - official extension, found in /src/cogs/official
        # > - user extension, to be placed in /src/cogs/user
        # $ - external module (installed via pip, etc)
        # If an extension is suffixed in `!`, failure to load that extension will throw a fatal error, preventing boot.
        prefixes = {"!": "official", ">": "user", "$": "external"}

        # You should not hardcode user extensions into this tuple as they're automatically detected.
        extensions = (
            # Extensions are loaded in priority order.
            "!debug!",
            "$jishaku",
            "!info",
            "!mod",
            "!util",
            "!config"
        )
        for ext in extensions:
            required = False
            if ext.endswith("!"):
                ext = ext[:-1]
                required = True
            prefix = prefixes[ext[0]]
            ext = ext[1:]
            dest = "src.cogs.%s.%s" % (prefix, ext) if prefix != "external" else ext
            try_load(dest, prefix, required)

        for user_ext in (self.home / "cogs" / "user" / "cogs").glob("*.py"):
            if user_ext.name.startswith("."):
                self.console.log("[i]Skipping loading user cog %r - disabled." % user_ext.name[1:-3])
            else:
                try_load("src.cogs.user.cogs." + user_ext.name[:-3], "user", False)

        self.console.log("Starting bot...")
        self.started_at = discord.utils.utcnow()
        try:
            token = self._select_token()
            await super().start(token)
        except (TypeError, discord.DiscordException) as e:
            self.on_connection_error(e)
            raise

    def on_connection_error(self, error: Exception):
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

    async def register_command(
        self, command: ApplicationCommand, force: bool = True, guild_ids: List[int] = None
    ) -> None:
        if force:
            self.console.log("[red]Force registering command: {!r}".format(command))
        await super().register_command(command, force, guild_ids)

    async def on_connect(self):
        self.console.log("Connected to discord!")
        await super().on_connect()

    async def on_ready(self):
        self.last_logged_in = discord.utils.utcnow()
        self.console.log("Bot is logged in to discord!")
        logger.info("Logged in to discord as %s." % self.user)
        self.console.log(
            "User: [link=%r]%s[/]"
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
        # Only thrown for
        if isinstance(exception, commands.CommandNotFound):
            extra = (
                "However, only a few select servers have access at this time. Join discord.gg/TveBeG7 to beta test!"
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
            return
        await super().on_command_error(context, exception)

    @staticmethod
    async def find_invite(channel: discord.abc.GuildChannel, *, infinite: bool = False) -> Optional[discord.Invite]:
        """
        Returns a random unlimited-use invite from the provided channel

        :param channel: The channel to find invites for.
        :param infinite: If True, this will make sure both max uses and max age are infinite.
        :return: Optional[discord.Invite]
        """
        if not channel.permissions_for(channel.guild.me).create_instant_invite:
            return

        invites = list(
            filter(
                lambda inv: inv.max_uses == 0 and inv.temporary is False and (inv.max_age == 0 if infinite else True),
                await channel.invites(),
            )
        )
        if not invites:
            return
        return random.choice(invites)  # random invite looks better than the same one every time

    async def on_application_command_error(
        self, context: discord.ApplicationContext, exception: discord.DiscordException
    ) -> None:
        static_errors: Dict[Type[discord.DiscordException], str] = {
            commands.MissingPermissions: "You do not have permission to run this command.\n'{e!s}'",
            commands.NotOwner: "This command is owner-only.",
            commands.BotMissingPermissions: "I do not have permission to run this command.\n'{e!s}'",
            commands.CommandOnCooldown: "This command is on cooldown.\n'{e!s}'",
            commands.MaxConcurrencyReached: "This command is currently running too many times.\n'{e!s}'",
        }
        if isinstance(exception, tuple(static_errors.keys())):
            await context.respond(static_errors[type(exception)].format(ctx=context, e=exception), ephemeral=True)
            return

        error = exception
        traceback.print_exception(type(error), error, error.__traceback__)
        exception = getattr(exception, "original", exception)
        try:
            case = await utils.create_error(context, exception)
            ephemeral = True
            if context.interaction.response.is_done():
                original_message = await context.interaction.original_message()
                ephemeral = original_message.flags.ephemeral

            if os.getenv("ERROR_CHANNEL"):
                error_channel_id = os.getenv("ERROR_CHANNEL")
                if not error_channel_id.isdigit():
                    warnings.warn(UserWarning("The environment variable 'ERROR_CHANNEL' is not an integer."))

                error_channel_id = int(error_channel_id)
                error_channel = self.get_channel(error_channel_id)
                exc_embed = discord.Embed(
                    title=f"New error: #{case.id}",
                    description=f"Error: {exception!r}"[:4069],
                    colour=discord.Colour.red(),
                )
                if error_channel and error_channel.can_send(exc_embed):
                    await error_channel.send(embed=exc_embed)

            await context.respond(
                embed=discord.Embed(
                    title="Oh no!",
                    description="There was an error executing your command, causing it to crash.\n"
                    "You can try running this command again if you like, however no change is guaranteed.\n"
                    "\n"
                    "The error was {!r}.\n"
                    "\n"
                    "If you want to speak to a developer, your case ID is `{!s}`.".format(
                        exception.__class__.__name__, case.id
                    ),
                    colour=discord.Colour.red(),
                    timestamp=discord.utils.utcnow(),
                ).set_author(name=context.user.display_name, icon_url=context.user.display_avatar.url),
                ephemeral=ephemeral,
            )
            self.console.log(f"Responded to exception, case ID {case.id}.")
        except (Exception, TypeError):
            self.console.log("Failed to respond to exception:")
            self.console.print_exception()
            await super().on_application_command_error(context, exception)

    async def start(self, token: str, *, reconnect: bool = True) -> None:
        for poll in await SimplePoll.objects.all():
            self.console.log("Registering poll %s to permanent view" % poll.id)
            view = SimplePollView(poll.id, None)
            self.add_view(view, message_id=poll.message)
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
