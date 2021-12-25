import io
import subprocess
import textwrap
import traceback
from contextlib import redirect_stdout
from datetime import datetime
from io import BytesIO

import discord
from discord.commands import permissions
from discord.ext import commands

from src import utils
from src.bot.client import Bot


class Debug(commands.Cog):
    def __init__(self, bot: Bot):
        self.bot: Bot = bot
        self.loaded_at = datetime.now()
        self._last_result = None

    def cleanup_code(self, content):
        """Automatically removes code blocks from the code."""
        # remove ```py\n```
        if content.startswith("```") and content.endswith("```"):
            return "\n".join(content.split("\n")[1:-1])

        # remove `foo`
        return content.strip("` \n")

    def get_syntax_error(self, e):
        if e.text is None:
            return f"```py\n{e.__class__.__name__}: {e}\n```"
        return f'```py\n{e.text}{"^":>{e.offset}}\n{e.__class__.__name__}: {e}```'

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

    @commands.slash_command(pass_context=True, hidden=True, name="eval")
    @permissions.is_owner()
    async def _eval(self, ctx, body: str, private: bool = False):
        """Evaluates a code"""
        await ctx.defer(ephemeral=private)

        env = {
            "bot": self.bot,
            "ctx": ctx,
            "channel": ctx.channel,
            "author": ctx.author,
            "guild": ctx.guild,
            "message": ctx.message,
            "_": self._last_result,
        }

        env.update(globals())

        body = self.cleanup_code(body)
        stdout = io.StringIO()

        to_compile = f'async def func():\n{textwrap.indent(body, "  ")}'

        try:
            exec(to_compile, env)
        except Exception as e:
            return await ctx.respond(f"```py\n{e.__class__.__name__}: {e}\n```", ephemeral=private)

        func = env["func"]
        try:
            with redirect_stdout(stdout):
                ret = await func()
        except Exception as e:
            value = stdout.getvalue()
            await ctx.respond(f"```py\n{value}{traceback.format_exc()}\n```", ephemeral=private)
        else:
            value = stdout.getvalue()

            if ret is None:
                if value:
                    await ctx.respond(f"```py\n{value}\n```", ephemeral=private)
            else:
                self._last_result = ret
                await ctx.respond(f"```py\n{value}{ret}\n```", ephemeral=private)

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

        def purge_check(_message: discord.Message):
            return _message.author == self.bot.user

        try:
            deleted_messages = await ctx.channel.purge(limit=max_search, check=purge_check)
        except discord.Forbidden:
            deleted_messages = []
            async for message in ctx.channel.history(limit=max_search):
                if message.author == self.bot.user:
                    await message.delete(delay=0.01)
                    deleted_messages.append("\0")
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
