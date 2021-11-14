import subprocess
from functools import partial
from typing import Any, Callable, Optional, Union, List
from threading import Thread
from urllib.parse import quote

import aiohttp
import httpx
from discord.ext import commands

from src.database.models import Guild, orm

import discord

try:
    import zlib
except ImportError:
    zlib = None


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

    try:
        guild = await Guild.objects.get(id=message.guild.id)
    except orm.NoMatch:
        return default(_, message)
    else:
        return commands.when_mentioned_or(guild.prefix)(_, message)


async def screenshot_page(
        session: httpx.AsyncClient = None,
        *,
        url: str,
        compress: bool = False,
        width: int = 1920,
        height: int = 1080
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
            timeout=httpx.Timeout(120)
        )
    async with session:
        response = await session.get("http://localhost:3000/screenshot/" + quote(url),
                                     params=dict(width=width, height=height))
        if response.status_code != 200:
            raise RuntimeError(f"Could not get screenshot of {url}: {response.status_code}")

        content: bytes = await response.aread()
        if compress:
            if not zlib:
                raise RuntimeError("zlib is not installed")
            content: bytes = await run_blocking(zlib.compress, content, 9)
        return content
