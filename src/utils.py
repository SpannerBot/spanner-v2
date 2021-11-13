import asyncio
from functools import partial
from typing import Any, Callable, Optional

from discord.ext import commands

from src.database.models import Guild, orm

import discord


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


async def get_prefix(_, message: discord.Message) -> Callable:
    default = commands.when_mentioned_or("s!")
    if not message.guild:
        return default

    try:
        guild = await Guild.objects.get(id=message.guild.id)
    except orm.NoMatch:
        return default
    else:
        return commands.when_mentioned_or(guild.prefix)
