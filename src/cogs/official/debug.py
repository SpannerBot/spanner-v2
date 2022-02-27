import subprocess
from datetime import datetime
from typing import Union

import discord
from discord.commands import permissions
from discord.ext import commands

from src.bot.client import Bot
from src.utils import utils


class Debug(commands.Cog):
    def __init__(self, bot: Bot):
        self.bot: Bot = bot
        self.loaded_at = datetime.now()

    @commands.command(name="type")
    @commands.is_owner()
    async def find_id_type(self, ctx: commands.Context, *, obj: int):
        converters = (
            commands.GuildChannelConverter,
            commands.MemberConverter,
            commands.UserConverter,
            commands.ObjectConverter,
        )
        result: Union[
            discord.abc.GuildChannel,
            discord.Member,
            discord.User,
            discord.Object
        ]
        async with ctx.channel.typing():
            for converter in converters:
                try:
                    result = await converter().convert(ctx, str(obj))
                except (commands.BadArgument, commands.ConversionError):
                    continue
                else:
                    break

        if isinstance(result, discord.abc.GuildChannel):
            # noinspection PyUnresolvedReferences
            return await ctx.reply(
                f"{result.id} is a {result.type.name} channel ({result.mention}) in {result.guild.name} "
                f"({result.guild.id})"
            )
        return await ctx.reply(
            f"{obj} is a {result.__class__.__name__} with ID {result.id}."
        )

    @commands.slash_command(name="version")
    @permissions.is_owner()
    async def debug(self, ctx: discord.ApplicationContext):
        """Shows debug information."""
        await ctx.defer(ephemeral=True)

        spanner_version = await utils.run_blocking(
            subprocess.run, ("git", "rev-parse", "--short", "HEAD"), capture_output=True
        )
        spanner_version = spanner_version.stdout.decode("utf-8").strip()

        embed = discord.Embed(
            title="Debug Information:",
            description=f"Current Revision: {spanner_version}\n"
            f"Discord.py version: {discord.__version__}\n"
            f"Cached Messages: {len(self.bot.cached_messages)}",
            colour=discord.Colour.red(),
        )
        return await ctx.respond(embed=embed, ephemeral=True)

    @commands.slash_command(name="ping")
    @permissions.is_owner()
    async def ping(self, ctx: discord.ApplicationContext):
        """Shows the bot's latency."""
        await ctx.respond(f"Pong! {round(self.bot.latency * 1000, 2)}ms")

    @commands.slash_command(name="clean")
    async def clean_bot_message(self, ctx: discord.ApplicationContext, max_search: int = 1000):
        """Deletes all messages sent by the bot up to <max_search> messages."""
        if ctx.author.id not in self.bot.owner_ids:
            if not ctx.channel.permissions_for(ctx.author).manage_messages:
                return await ctx.respond("You don't have permission to do that.")

        if max_search <= 0:
            if ctx.author not in self.bot.owner_ids:
                max_search = 10
            else:
                max_search = None
        else:
            max_search = max(10, min(10_000, max_search))

        await ctx.defer()

        prefixes = (
            "s!",
            ctx.me.mention
        )
        if ctx.guild:
            guild = await utils.get_guild(ctx.guild)
            prefixes = (
                guild.prefix,
                ctx.me.mention
            )

        def purge_check(_message: discord.Message):
            return _message.author == self.bot.user or _message.content.startswith(prefixes)

        try:
            deleted_messages = await ctx.channel.purge(limit=max_search+1, check=purge_check)
        except discord.Forbidden:
            deleted_messages = []
            async for message in ctx.channel.history(limit=max_search):
                if purge_check(message):
                    await message.delete(delay=0.01)
                    deleted_messages.append(b"\0")
        except discord.HTTPException as e:
            code = (
                f"[{e.code}: {e.text[:100]}](https://discord.com/developers/docs/topics/"
                f"opcodes-and-status-codes#json:~:text={e.code})"
            )
            await ctx.respond(f"Failed to delete messages: {code}")
            return
        try:
            await ctx.respond(f"Deleted {len(deleted_messages)} messages.", ephemeral=True)
        except discord.HTTPException:
            pass

    @commands.slash_command()
    async def invite(self, ctx: discord.ApplicationContext):
        """Gets the bot's invite link."""
        await ctx.respond(discord.utils.oauth_url(self.bot.user.id, scopes=("bot", "applications.commands")))


def setup(bot):
    bot.add_cog(Debug(bot))
