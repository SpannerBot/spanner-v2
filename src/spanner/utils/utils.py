import asyncio
import datetime
import re
import sys
import traceback
import typing
import warnings
from functools import partial
from typing import Any, Callable, List, Optional, Iterable, Coroutine

import discord
import httpx
from discord.ext import commands

from database.models import Guild, CommandType, Errors

__all__ = (
    "case_type_names",
    "Emojis",
    "session",
    "run_blocking",
    "get_guild",
    "get_prefix",
    "format_time",
    "parse_time",
    "chunk",
    "SessionWrapper",
    "MaxConcurrency",
    "get_guild_config",
    "load_colon_int_list",
    "TimeFormat",
    "avatar",
    "disable_with_reason",
    "disable_unless_owner",
)

case_type_names = {
    0: "warning",
    1: "mute",
    2: "temporary mute",
    3: "kick",
    4: "ban",
    5: "temporary ban",
    6: "unmute",
    7: "unban",
    8: "soft-ban",
}


class _SessionContainer:
    if typing.TYPE_CHECKING:
        session: httpx.AsyncClient
        get: "session.get"
        post: "session.post"
        put: "session.put"
        delete: "session.delete"

    def __init__(self):
        self.session = httpx.AsyncClient(
            headers={
                "User-Agent": f"DiscordBot (Spanner/v2; https://github.com/EEKIM10/spanner-v2; "
                f"httpx/{httpx.__version__}); pycord/{discord.__version__}; "
                f"python/{'.'.join(map(str, sys.version_info[:3]))})"
            }
        )

    def __getattr__(self, item):
        # hacky but who cares.
        return getattr(self.session, item)

    def __del__(self):
        if warnings:
            warnings.simplefilter("ignore", Warning)
            if self.session is not None and self.session.is_closed is False and asyncio is not None:
                try:
                    asyncio.create_task(self.session.aclose())
                except RuntimeError:
                    pass
            warnings.simplefilter("default", Warning)

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass  # We don't need to close the session

    def __bool__(self):
        return not self.session.is_closed


class SessionWrapper:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await session.session.aclose()


class Emojis:
    YES = "\N{WHITE HEAVY CHECK MARK}"
    NO = "\N{CROSS MARK}"
    ERROR = "\N{CROSS MARK}"
    WARNING = "\N{WARNING SIGN}"
    INFO = "\N{INFORMATION SOURCE}"
    QUESTION = "\N{BLACK QUESTION MARK ORNAMENT}"
    # LOADING = "\N{BLACK SMALL LOADING WHEEL}"

    TEXT_CHANNEL = "<:text_channel:923666787038531635>"
    LOCKED_TEXT_CHANNEL = "<:text_locked:923666787759972444>"
    NSFW_TEXT_CHANNEL = "<:text_nsfw:923666788913410098>"
    VOICE_CHANNEL = "<:voice_channel:923666789798379550>"
    LOCKED_VOICE_CHANNEL = "<:voice_locked:923666790826000464>"
    STAGE_CHANNEL = "<:stage_channel:923666792705032253>"
    CATEGORY = "<:category:924001844290781255>"

    @staticmethod
    def bool(value: bool) -> str:
        return Emojis.YES if value else Emojis.NO


session = _SessionContainer()


async def run_blocking(func: Callable, *args, **kwargs) -> Optional[Any]:
    """
    Run a function in a blocking manner.

    Args:
        func: The function to run.
        *args: The positional arguments to pass to the function.
        **kwargs: The keyword arguments to pass to the function.

    Returns:
        The return value of the function.
    """
    from bot.client import bot

    return await bot.loop.run_in_executor(None, partial(func, *args, **kwargs))


async def get_guild_config(
    guild_id: typing.Union[discord.ApplicationContext, commands.Context, discord.Guild, int]
) -> Guild:
    """
    Fetches a guild's configuration.

    Args:
        guild_id: Any context, the guild object, or the guild's raw ID.

    Returns:
        The fetched or created guild database object
    """
    if hasattr(guild_id, "guild"):
        guild_id = guild_id.guild.id
    elif hasattr(guild_id, "id"):
        guild_id = guild_id.id
    guild_id: int
    return (await Guild.objects.get_or_create({}, id=guild_id))[0]


async def get_prefix(_, message: discord.Message) -> List[str]:
    default = commands.when_mentioned_or("s!")
    # if not message.guild:
    return default(_, message)

    # guild, __ = await Guild.objects.get_or_create({}, id=message.guild.id)
    # return commands.when_mentioned_or(guild.prefix)(_, message)


def format_time(seconds: int):
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)

    values = []

    if days:
        values.append("%d days" % days)
    if hours:
        values.append("%d hours" % hours)
    if minutes:
        values.append("%d minutes" % minutes)
    if seconds:
        values.append("%d seconds" % seconds)
    return ", ".join(values)


class TimeFormat:
    # TIME_DEFINITE_REGEX = re.compile(
    #     r"^((?P<date>\d{1,2}/\d{1,2}/\d{2,4})?\sat\s)?(?P<time>\d{1,2}(:\d{2})?(am|pm)?)$"
    # )
    TIME_RELATIVE_REGEX = re.compile(
        r"(?P<len>\d+(\.(\d{0,8}))?)(\s){0,2}(?P<span>(s(ec(ond)?)?|m(in(ute)?)?|h((ou)?r)?|d(ay)?|w(eek)?)(s)?)",
        re.IGNORECASE | re.VERBOSE,
    )
    TIMESPANS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800, "y": 31536000}

    @staticmethod
    def parse_relative(time: str) -> int:
        """Parses a timespan (e.g. 1d, 3 hours) into seconds.

        Arguments:
            time: str - the provided relative time (like 1h30m)
        Returns:
            int - The converted time in seconds.
        Raises:
            ValueError - the time format was invalid
        """
        time = time.strip()
        matches = tuple(TimeFormat.TIME_RELATIVE_REGEX.finditer(time))
        if len(matches) == 0:
            raise ValueError("Invalid time format")

        total_seconds = 0
        for match in matches:
            length = int(match.group("len"))
            span = match.group("span").lower()[0]
            total_seconds += length * TimeFormat.TIMESPANS[span]

        return total_seconds

    @staticmethod
    def parse_definite(time: str) -> Optional[datetime.datetime]:
        """Similar to parse_relative, except returns a datetime"""
        formats = ("%d/%m/%Y at %I:%M%p", "%d/%m/%Y at %H:%M")
        # match = TimeFormat.TIME_RELATIVE_REGEX.match(time)
        for fmt in formats:
            try:
                dt = datetime.datetime.strptime(time, fmt)
                dt.replace(microsecond=0, tzinfo=datetime.timezone.utc)
                return dt
            except ValueError:
                continue

    @staticmethod
    def format_relative(dt: datetime.datetime) -> str:
        return dt.strftime("%d/%m/%Y at %I:%M%p")


def parse_time(time: str) -> int:
    """Parses a timespan (e.g. 1d, 3 hours) into seconds"""
    return TimeFormat.parse_relative(time)


@discord.utils.deprecated("get_guild_config")
async def get_guild(guild: discord.Guild):
    return await Guild.objects.get(id=guild.id)


@discord.utils.copy_doc(discord.utils.as_chunks)
@discord.utils.deprecated("discord.utils.as_chunks")
def chunk(iterator, max_size: int) -> Iterable:
    return discord.utils.as_chunks(iterator, max_size)


async def create_error(context: typing.Union[commands.Context, discord.ApplicationContext], error: Exception):
    cmd_type = CommandType.TEXT
    kwargs = {
        "traceback_text": "".join(traceback.format_exception(type(error), error, error.__traceback__)),
        "author": getattr(context, "user", context.author).id,
        "guild": context.guild.id if context.guild else None,
        "channel": context.channel.id if context.channel else None,
        "permissions_channel": context.channel.permissions_for(context.me).value
        if hasattr(context.channel, "permissions_for")
        else 0,
        "permissions_guild": context.me.guild_permissions.value if context.me.guild else 0,
        "full_message": context.message.content if context.message is not None else None,
    }
    if isinstance(context, discord.ApplicationContext):
        kwargs["command"] = context.command.qualified_name
        types = {
            0: CommandType.UNKNOWN,
            1: CommandType.SLASH,
            2: CommandType.USER,
            3: CommandType.MESSAGE,
            4: CommandType.AUTOCOMPLETE,
            5: CommandType.MODAL,
        }
        # class InteractionType(Enum):
        # ping = 1
        # application_command = 2
        # component = 3
        # auto_complete = 4
        # modal_submit = 5
        # noinspection PyUnresolvedReferences
        kwargs["command_type"] = types.get(context.interaction.type.value, CommandType.UNKNOWN)
    else:
        kwargs["command_type"] = cmd_type

    entry = await Errors.objects.create(**kwargs)
    return entry


_CONCURRENT_LOCKS = {}


class MaxConcurrency:
    def __init__(self, our_id: int, max_concurrency: int):
        self.max_concurrency = max_concurrency
        self.id = our_id

    def __enter__(self):
        if _CONCURRENT_LOCKS.get(self.id) is not None:
            raise RuntimeError("Concurrency reached for this target")
        _CONCURRENT_LOCKS[self.id] = self

    def __exit__(self, exc_type, exc_val, exc_tb):
        _CONCURRENT_LOCKS.pop(self.id, None)


def load_colon_int_list(raw: str) -> List[int]:
    results = [int(x) for x in raw.split(":") if x]
    return results


def avatar(user: typing.Union[discord.User, discord.Member], *, display: bool = True) -> discord.Asset:
    """Finds the user's current avatar."""
    if display:
        return user.display_avatar
    return user.avatar or user.default_avatar


def disable_with_reason(
    condition: Optional[Callable[[discord.ApplicationContext], typing.Union[bool, Coroutine[Any, Any, bool]]]] = None,
    *,
    reason: str = None,
):
    """Disables a command with a reason, unless the condition provided is met."""

    async def predicate(ctx: discord.ApplicationContext):
        if condition is not None:
            try:
                okay = await discord.utils.maybe_coroutine(condition, ctx)
            except commands.CheckFailure:
                okay = False

            if okay is not True:
                raise commands.DisabledCommand(f"This command is disabled: {reason}")

        else:
            raise commands.DisabledCommand(f"This command is disabled: {reason}")

        return True

    return commands.check(predicate)


def disable_unless_owner(reason: str = "Command is under development."):
    async def is_owner(c: discord.ApplicationContext) -> bool:
        return await c.bot.is_owner(c.author)

    return disable_with_reason(is_owner, reason=reason)
