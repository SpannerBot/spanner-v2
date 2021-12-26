import re

import discord
from discord import ApplicationContext as Context
from discord.ext.commands import UserNotFound
from discord.ext.commands.converter import *

__all__ = (
    "UserConverter",
)


# Patched from commands.UserConverter due to incompatibility with interactions
class UserConverter(IDConverter[discord.User]):
    """Converts to a :class:`~discord.User`.

    All lookups are via the global user cache.

    The lookup strategy is as follows (in order):

    1. Lookup by ID.
    2. Lookup by mention.
    3. Lookup by name#discrim
    4. Lookup by name

    .. versionchanged:: 1.5
         Raise :exc:`.UserNotFound` instead of generic :exc:`.BadArgument`

    .. versionchanged:: 1.6
        This converter now lazily fetches users from the HTTP APIs if an ID is passed
        and it's not available in cache.
    """

    # noinspection PyProtectedMember
    async def convert(self, ctx: Context, argument: str) -> discord.User:
        match = self._get_id_match(argument) or re.match(r'<@!?([0-9]{15,20})>$', argument)
        state = ctx._state

        if match is not None:
            user_id = int(match.group(1))
            result = await ctx.bot.get_or_fetch_user(user_id)
            if result is None:
                raise UserNotFound(argument) from None

            return result

        arg = argument

        # Remove the '@' character if this is the first character from the argument
        if arg[0] == '@':
            # Remove first character
            arg = arg[1:]

        # check for discriminator if it exists,
        if len(arg) > 5 and arg[-5] == '#':
            discrim = arg[-4:]
            name = arg[:-5]

            def predicate(u) -> bool:
                return u.name == name and u.discriminator == discrim

            result = discord.utils.find(predicate, state._users.values())
            if result is not None:
                return result

        def predicate(u) -> bool:
            return u.name == arg

        result = discord.utils.find(predicate, state._users.values())

        if result is None:
            raise UserNotFound(argument)

        return result
