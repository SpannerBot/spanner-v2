import asyncio
import re
import subprocess
import typing
import warnings
import sys
from functools import partial
from threading import Thread
from typing import Any, Callable, List, Optional, Union, Iterable, Sized
from urllib.parse import quote

import aiohttp
import discord
import httpx
from discord.ext import commands

from src.database.models import Guild, orm

try:
    import zlib
except ImportError:
    zlib = None

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
    "SessionWrapper"
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
                asyncio.create_task(self.session.aclose())
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
    from src.bot.client import bot

    return await bot.loop.run_in_executor(None, partial(func, *args, **kwargs))


async def get_prefix(_, message: discord.Message) -> List[str]:
    default = commands.when_mentioned_or("s!")
    if not message.guild:
        return default(_, message)

    guild, __ = await Guild.objects.get_or_create({}, id=message.guild.id)
    return commands.when_mentioned_or(guild.prefix)(_, message)


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


TIME_REGEX = re.compile(
    r"(?P<len>[0-9]+(\.([0-9]{0,8}))?)(\s){0,2}(?P<span>(s(ec(ond)?)?|m(in(ute)?)?|h((ou)?r)?|d(ay)?|w(eek)?)(s)?)",
    re.IGNORECASE | re.VERBOSE,
)
TIMESPANS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_time(time: str) -> int:
    """Parses a timespan (e.g. 1d, 3 hours) into seconds"""
    time = time.strip()
    match = TIME_REGEX.match(time)
    if not match:
        raise ValueError("Invalid time format")
    length = int(match.group("len"))
    span = match.group("span").lower()[0]
    return length * TIMESPANS[span]


async def get_guild(guild: discord.Guild) -> Guild:
    return await Guild.objects.get(id=guild.id)


def chunk(iterable: Sized, max_chunk_size: int) -> Iterable:
    """Yield successive n-sized chunks from lst."""
    # I have taken this function SO MANY TIMES
    # https://stackoverflow.com/questions/312443/how-do-you-split-a-list-into-evenly-sized-chunks source

    for i in range(0, len(iterable), max_chunk_size):
        yield iterable[i : i + max_chunk_size]
