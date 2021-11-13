import subprocess
import discord
from datetime import datetime
from discord.ext import commands
from discord.commands import permissions
from src.bot.client import Bot
from src import utils


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
            colour=discord.Colour.red()
        )
        return await ctx.respond(embed=embed, ephemeral=True)


def setup(bot):
    bot.add_cog(Debug(bot))
