import subprocess
from datetime import datetime
from io import BytesIO

import discord
from discord.commands import permissions
from discord.ext import commands
from httpx import AsyncClient

from src import utils
from src.bot.client import Bot


class Info(commands.Cog):
    def __init__(self, bot: Bot):
        self.bot: Bot = bot

    @commands.user_command()
    async def avatar(self, ctx: discord.ApplicationContext, user: discord.User):
        """Shows you someone's avatar."""
        await ctx.defer()
        avatar: discord.Asset = user.display_avatar.with_static_format("png")
        avatar_data: bytes = await avatar.read()
        fs_limit = ctx.guild.filesize_limit if ctx.guild else 1024 * 1024 * 8  # 8mb

        if len(avatar_data) >= fs_limit:
            return await ctx.respond(avatar.url, embed=discord.Embed(colour=user.colour).set_image(url=avatar.url))
        else:
            bio = BytesIO()
            bio.write(avatar_data)
            bio.seek(0)
            ext = avatar.url.split(".")[-1]
            ext = ext[: ext.index("?")]
            file = discord.File(bio, filename=f"avatar.{ext}")
            return await ctx.respond(
                embed=discord.Embed(colour=user.colour).set_image(url=f"attachment://avatar.{ext}"), file=file
            )

    @commands.slash_command(name="channel-info")
    async def channel_info(
        self,
        ctx: discord.ApplicationContext,
        channel: discord.Option(
            discord.TextChannel,
            # channel_types=[discord.TextChannel, discord.VoiceChannel, discord.CategoryChannel, discord.StageChannel],
            channel_types=[discord.ChannelType.text, discord.ChannelType.voice, discord.ChannelType.category, discord.ChannelType.stage_voice]
        ),
    ):
        """Shows you information on a channel."""
        await ctx.defer()
        if isinstance(channel, discord.TextChannel):
            locked = channel.permissions_for(channel.guild.default_role).read_messages
            nsfw = channel.is_nsfw()

            emoji = utils.Emojis.TEXT_CHANNEL
            if locked:
                emoji = utils.Emojis.LOCKED_TEXT_CHANNEL
            if nsfw:
                emoji = utils.Emojis.NSFW_TEXT_CHANNEL

            invites = []
            if channel.permissions_for(channel.guild.me).manage_channels:
                invites = [x.id for x in await channel.invites()]

            webhooks = ""
            if channel.permissions_for(channel.guild.me).manage_webhooks:
                webhooks = len(await channel.webhooks())

            values = [
                f"**Name**: {discord.utils.escape_markdown(channel.name)}",
                f"**ID**: `{channel.id}`",
                f"**Category**: {channel.category.name if channel.category else 'None'}",
                f"**Members who can see it**: {len(channel.members)}",
                f"**NSFW?** {'Yes' if nsfw else 'No'}",
                f"**Created**: <t:{round(channel.created_at.timestamp())}:R>",
                f"**Invites**: {', '.join(invites)}",
                f"**Webhooks**: {webhooks}",
                f"**Permissions Synced?** {'Yes' if channel.permissions_synced else 'No'}",
                f"**Slowmode**: {utils.format_time(channel.slowmode_delay)}",
                f"**Auto archive inactive threads after**: "
                f"{utils.format_time(channel.default_auto_archive_duration * 60)}",
                f"**Position**: {channel.position}",
                f"**Threads**: {len(channel.threads)}",
            ]

            embed = discord.Embed(
                title="%s%s" % (emoji, channel.name), description="\n".join(values), colour=discord.Colour.greyple()
            )
        elif isinstance(channel, discord.VoiceChannel):
            emoji = utils.Emojis.VOICE_CHANNEL
            if not channel.permissions_for(channel.guild.default_role).read_messages:
                emoji = utils.Emojis.LOCKED_VOICE_CHANNEL

            # noinspection PyUnresolvedReferences
            values = [
                f"**Name**: {discord.utils.escape_markdown(channel.name)}",
                f"**ID**: `{channel.id}`",
                f"**Category**: {channel.category.name if channel.category else 'No Category'}",
                f"**Bitrate**: {channel.bitrate/1000}kbps",
                f"**User Limit**: {channel.user_limit}",
                f"**In Chat Now**: {len(channel.members)}",
                f"**Created**: <t:{round(channel.created_at.timestamp())}:R>",
                f"**Permissions Synced**: {'Yes' if channel.permissions_synced else 'No'}",
                f"**Voice Region**: {channel.rtc_region.value if channel.rtc_region else 'Automatic'}",
                f"**Video Quality**: {channel.video_quality_mode.value}",
            ]
            embed = discord.Embed(
                title="%s%s" % (emoji, channel.name), description="\n".join(values), colour=discord.Colour.og_blurple()
            )
        elif isinstance(channel, discord.CategoryChannel):
            embed = discord.Embed()
        else:
            embed = discord.Embed()

        return await ctx.respond(embed=embed)


def setup(bot):
    bot.add_cog(Info(bot))
