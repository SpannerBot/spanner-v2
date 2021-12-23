import subprocess
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

    @commands.slash_command(name="version")
    @permissions.is_owner()
    async def debug(self, ctx: discord.ApplicationContext):
        """Shows debug information."""
        await ctx.defer(ephemeral=True)

        spanner_version = await utils.run_blocking(
            subprocess.run, ("git", "rev-parse", "HEAD", "--short"), capture_output=True
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

    @commands.slash_command(name="screenshot-url")
    @permissions.is_owner()
    async def screenshot_url(
        self,
        ctx: discord.ApplicationContext,
        url: str,
        compress_with_zlib: bool = False,
        width: int = 1920,
        height: int = 1080,
    ):
        """Sends a screenshot of the provided URL."""
        await ctx.defer(ephemeral=True)
        try:
            screenshot_data = await utils.screenshot_page(
                url=url, compress=compress_with_zlib, width=width, height=height
            )
        except RuntimeError:
            return await ctx.respond("That URL is unavailable.", ephemeral=True)
        x = BytesIO()
        x.write(screenshot_data)
        x.seek(0)
        return await ctx.respond(file=discord.File(x, filename="screenshot.png"), ephemeral=True)


def setup(bot):
    bot.add_cog(Debug(bot))
