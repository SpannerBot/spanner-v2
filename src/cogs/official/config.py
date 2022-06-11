import discord
from discord.ext import commands

from src.utils import get_guild_config


class ConfigCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    config = discord.SlashCommandGroup(
        "settings",
        "Manages server settings",
        default_member_permissions=discord.Permissions(manage_guild=True),
        guild_only=True,
    )

    @config.command()
    async def view(self, ctx: discord.ApplicationContext):
        """Shows server settings"""
        guild = await get_guild_config(ctx)
        log_channel = str(guild.log_channel)
        if guild.log_channel is not None:
            log_channel = ctx.guild.get_channel(guild.log_channel)
            if log_channel:
                log_channel = log_channel.mention

        embed = discord.Embed(
            title=f"Settings for {ctx.guild.name!r}:",
            description="Database ID: {0.entry_id!s}\n"
            "Server ID: {0.id!s}\n"
            "(\N{WAVING WHITE FLAG}\U0000fe0f) Prefix: `{0.prefix!s}`\n"
            "Log Channel: {1}\n".format(guild, log_channel),
            colour=discord.Colour.blue(),
        )
        return await ctx.respond(embed=embed)

    @config.command(name="set-log-channel")
    async def set_log_channel(self, ctx: discord.ApplicationContext, channel: discord.TextChannel = None):
        """Sets the channel where moderation events are logged to."""
        guild = await get_guild_config(ctx)
        channel_id = None
        if channel is not None:
            if not channel.can_send(discord.Embed, discord.File):
                return await ctx.respond(
                    f"\N{cross mark} I can't send things I need to be able to send in {channel.mention}.\n"
                    f"Make sure I have view channel, send messages, embed links, and attach files."
                )
            channel_id = channel.id

        await guild.update(log_channel=channel_id)
        if channel:
            return await ctx.respond(f"Set your log channel to {channel.mention}.")
        else:
            return await ctx.respond("Removed your log channel.")


def setup(bot):
    bot.add_cog(ConfigCog(bot))
