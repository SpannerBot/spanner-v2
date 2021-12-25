import asyncio
import subprocess
import sys
from functools import partial
from threading import Thread
from typing import Any, Callable, List, Optional, Union
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


__all__ = ("session", "run_blocking", "get_prefix", "screenshot_page")

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
        if self.session is not None and self.session.is_closed is False:
            asyncio.create_task(self.session.aclose())

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass  # We don't need to close the session

    def __bool__(self):
        return not self.session.is_closed


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


async def screenshot_page(
    session: httpx.AsyncClient = None, *, url: str, compress: bool = False, width: int = 1920, height: int = 1080
) -> bytes:
    """
    Take a screenshot of a web page.

    Args:
        session: The session to use for the request.
        url: The URL to take the screenshot of.
        compress: Whether or not to compress the image.
        width: The width of the screenshot.
        height: The height of the screenshot.

    Returns:
        The screenshot of the page.
    """
    if not session:
        session = httpx.AsyncClient(
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.132 Safari/537.36",
            },
            timeout=httpx.Timeout(120),
        )
    async with session:
        response = await session.get(
            "http://localhost:3000/screenshot/" + quote(url), params=dict(width=width, height=height)
        )
        if response.status_code != 200:
            raise RuntimeError(f"Could not get screenshot of {url}: {response.status_code}")

        content: bytes = await response.aread()
        if compress:
            if not zlib:
                raise RuntimeError("zlib is not installed")
            content: bytes = await run_blocking(zlib.compress, content, 9)
        return content


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


async def get_guild(guild: discord.Guild) -> Guild:
    return await Guild.objects.get(id=guild.id)
