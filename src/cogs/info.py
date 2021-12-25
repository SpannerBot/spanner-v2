import platform
import subprocess
import sys
import unicodedata
from datetime import datetime
from textwrap import shorten
from io import BytesIO
from typing import Union
from urllib.parse import urlparse

import discord
from discord.commands import permissions
from discord.ext import commands
from httpx import AsyncClient

from src import utils
from src.bot.client import Bot

verification_levels = {
    discord.VerificationLevel.none: "Unrestricted",
    discord.VerificationLevel.low: "Must have a verified email",
    discord.VerificationLevel.medium: "Must be registered on Discord for longer than 5 minutes + "
    "must have a verified email",
    discord.VerificationLevel.high: "Must be a member of the server for longer than 10 minutes, "
    "must be registered on discord for longer than 5 minutes, and must have a "
    "verified email",
    discord.VerificationLevel.highest: "Must have a verified phone number",
}

content_filters = {
    discord.ContentFilter.disabled: "No messages are filtered",
    discord.ContentFilter.no_role: "Recommended for servers who use roles for trusted membership",
    discord.ContentFilter.all_members: "Recommended for when you want that squeaky clean shine",
}

content_filter_names = {
    discord.ContentFilter.disabled: "Don't scan any media content",
    discord.ContentFilter.no_role: "Scan media content from members without a role",
    discord.ContentFilter.all_members: "Scan media content from all members",
}


class Info(commands.Cog):
    def __init__(self, bot: Bot):
        self.bot: Bot = bot

    @staticmethod
    def get_user_data(user: Union[discord.User, discord.Member], guild: discord.Guild = None):
        # noinspection PyUnresolvedReferences
        values = [
            f"**ID**: `{user.id}`",
            f"**Username**: {discord.utils.escape_markdown(user.name)}",
            f"**Display Name**: {discord.utils.escape_markdown(user.display_name)}",
            f"**Discriminator/tag**: `#{user.discriminator}`",
            f"**Status**: {user.status.name.title()}" if hasattr(user, "status") else None,
            f"**Created**: <t:{round(user.created_at.timestamp())}:R>",
            f"**Joined**: <t:{round(user.joined_at.timestamp())}:R>" if hasattr(user, "joined_at") else None,
            f"**Mutual Servers (with bot)**: {len(user.mutual_guilds)}",
            f"**Bot?** {utils.Emojis.bool(user.bot)}",
            f"**On Mobile?** {utils.Emojis.bool(user.is_on_mobile())}" if hasattr(user, "is_on_mobile") else None,
            f"**Roles**: {len(user.roles):,}" if hasattr(user, "roles") else None,
            f"**Colour**: {user.colour}" if guild else None,
            f"**Top Role**: {user.top_role.mention}" if hasattr(user, "top_role") else None,
            f"**Avatar URL**: {user.avatar.url}",
        ]

        if guild:
            if user.display_avatar != user.avatar:
                values.append("**Display Avatar**: %s" % user.display_avatar.url)

        values = list(filter(lambda x: x is not None, values))  # remove guild-only shit
        return values

    @staticmethod
    def hyperlink(url: str, text: str = ...):
        if text is ...:
            parsed = urlparse(url)
            text = parsed.hostname.lower()

        return f"[{text}]({url})"

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

    @commands.slash_command(name="whois")
    async def whois(self, ctx: discord.ApplicationContext, user: str):
        """Finds a user based on their ID"""
        if not user.isdigit():
            return await ctx.respond("Invalid user ID.")
        user = int(user)
        user = await self.bot.get_or_fetch_user(user)
        if user is None:
            return await ctx.respond("Unknown user ID.")

        embed = discord.Embed(
            title=f"{user}'s information:",
            description="\n".join(self.get_user_data(user, ctx.guild)),
            colour=user.colour,
            timestamp=user.created_at,
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
        return await ctx.respond(embed=embed)

    @commands.user_command(name="User Info")
    async def user_info(self, ctx: discord.ApplicationContext, user: discord.User = None):
        embeds = []
        user: Union[discord.User, discord.Member]
        user = user or ctx.author
        if user == self.bot.user:
            latency = round(self.bot.latency * 1000, 2)
            spanner_version = await utils.run_blocking(
                subprocess.run, ("git", "rev-parse", "--short", "HEAD"), capture_output=True, encoding="utf-8"
            )
            spanner_version = spanner_version.stdout.strip()

            if platform.system().lower() == "windows":
                os_version = f"{platform.system()} {platform.release()}"
            else:  # linux
                with open("/etc/os-release") as release_file:
                    version_name = "Linux"
                    version_id = "0 (unknown)"
                    for line in release_file.readlines():
                        if line.startswith("NAME"):
                            version_name = line.split("=")[1].strip().title()
                        elif line.startswith("VERSION="):
                            version_id = line.split("=")[1].strip().title()

                    version_string = "%s %s" % (version_name, version_id)

                    kernel_version = await utils.run_blocking(
                        subprocess.run, ("uname", "-r"), capture_output=True, encoding="utf-8", check=True
                    )
                    version_string += ", kernel version `%s`" % kernel_version.stdout.strip()
                    os_version = version_string

            embed = discord.Embed(
                title="My Information:",
                description=f"WebSocket Latency (ping): {latency}ms\n"
                f"Bot Started: <t:{round(self.bot.started_at.timestamp())}:R>\n"
                f"Bot Last Connected: <t:{round(self.bot.last_logged_in.timestamp())}:R>\n"
                f"Bot Created At: <t:{round(self.bot.user.created_at.timestamp())}:R>\n"
                f"\n"
                f"Cached Users: {len(self.bot.users):,}\n"
                f"Guilds: {len(self.bot.guilds):,}\n"
                f"Total Channels: {len(tuple(self.bot.get_all_channels())):,}\n"
                f"Total Emojis: {len(self.bot.emojis):,}\n"
                f"Cached Messages: {len(self.bot.cached_messages):,}\n"
                f"\n"
                f"Python Version: {sys.version.split(' ')[0]}\n"
                f"Pycord Version: {discord.__version__}\n"
                f"Bot Version: v2#{spanner_version}\n"
                f"OS Version: {os_version}",
                colour=0x049319,
                timestamp=discord.utils.utcnow(),
            )
            embeds.append(embed)

        if ctx.guild:
            old_user = user
            try:
                user = ctx.guild.get_member(user.id) or await ctx.guild.fetch_member(user.id)
            except discord.HTTPException:
                user = old_user

        embed = discord.Embed(
            title=f"{user}'s information:",
            description="\n".join(self.get_user_data(user, ctx.guild)),
            colour=user.colour,
            timestamp=user.created_at,
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
        embeds.append(embed)
        return await ctx.respond(embeds=embeds)

    @commands.slash_command(name="channel-info")
    async def channel_info(
        self,
        ctx: discord.ApplicationContext,
        channel: Union[discord.TextChannel, discord.VoiceChannel, discord.StageChannel, discord.CategoryChannel],
    ):
        """Shows you information on a channel."""
        await ctx.defer()
        if isinstance(channel, discord.TextChannel):
            locked = channel.permissions_for(channel.guild.default_role).read_messages is False
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
                f"**NSFW?** {utils.Emojis.bool(nsfw)}",
                f"**Created**: <t:{round(channel.created_at.timestamp())}:R>",
                f"**Invites**: {', '.join(invites)}",
                f"**Webhooks**: {webhooks}",
                f"**Permissions Synced?** {utils.Emojis.bool(channel.permissions_synced)}",
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
            if channel.permissions_for(channel.guild.default_role).read_messages is False:
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
                f"**Permissions Synced**: {utils.Emojis.bool(channel.permissions_synced)}",
                f"**Voice Region**: {channel.rtc_region.value if channel.rtc_region else 'Automatic'}",
                f"**Video Quality**: {channel.video_quality_mode.value}",
            ]
            embed = discord.Embed(
                title="%s%s" % (emoji, channel.name), description="\n".join(values), colour=discord.Colour.og_blurple()
            )
        elif isinstance(channel, discord.CategoryChannel):
            values = [
                f"**ID**: `{channel.id}`",
                f"**Name**: {discord.utils.escape_markdown(channel.name)}",
                f"**Created**: <t:{round(channel.created_at.timestamp())}:R>",
                f"**Position**: {channel.position}",
                f"**Text Channels**: {len(channel.text_channels)}",
                f"**Voice Channels**: {len(channel.voice_channels)}",
                f"**Stage Channels**: {len(channel.stage_channels)}",
            ]
            embed = discord.Embed(
                title="%s%s" % (utils.Emojis.CATEGORY, channel.name),
                description="\n".join(values),
                colour=discord.Colour.dark_grey(),
            )
        elif isinstance(channel, discord.StageChannel):
            # noinspection PyUnresolvedReferences
            values = [
                f"**Name**: {discord.utils.escape_markdown(channel.name)}",
                f"**ID**: `{channel.id}`",
                f"**Category**: {channel.category.name if channel.category else 'No Category'}",
                f"**Bitrate**: {channel.bitrate/1000}kbps",
                f"**In Chat Now**: {len(channel.members)}",
                f"**Created**: <t:{round(channel.created_at.timestamp())}:R>",
                f"**Permissions Synced**: {utils.Emojis.bool(channel.permissions_synced)}",
                f"**Voice Region**: {channel.rtc_region.value if channel.rtc_region else 'Automatic'}",
                f"**Video Quality**: {channel.video_quality_mode.value}",
            ]

            embed = discord.Embed(
                title="%s%s" % (utils.Emojis.STAGE_CHANNEL, channel.name),
                description="\n".join(values),
                colour=discord.Colour.green() if channel.instance else discord.Colour.dark_grey(),
            )

            if channel.instance:
                embed.description += "\n**Topic**: %s" % (channel.topic or "no topic")[:256]
                if len(channel.moderators) >= 40:
                    moderators = ["40+"]
                else:
                    moderators = [x.mention for x in channel.moderators] or ["\N{ghost}"]
                if len(channel.listeners) >= 40:
                    listening = ["40+"]
                else:
                    listening = [x.mention for x in channel.listeners] or ["\N{ghost}"]
                if len(channel.speakers) >= 40:
                    speaking = ["40+"]
                else:
                    speaking = [x.mention for x in channel.speakers] or ["\N{ghost}"]
                embed.add_field(name="Stage Moderators:", value="\n".join(moderators), inline=False)
                embed.add_field(name="Stage Listeners:", value="\n".join(listening), inline=False)
                embed.add_field(name="Stage Speakers:", value="\n".join(speaking), inline=False)
        else:
            return await ctx.respond("Unknown channel type.")

        embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
        embed.timestamp = discord.utils.utcnow()
        return await ctx.respond(embed=embed)

    @commands.message_command(name="Message Info")
    async def message_info(self, ctx: discord.ApplicationContext, message: discord.Message):
        """Shows you all the information about a provided message"""
        jump = "[{}](%s)" % message.jump_url
        content = shorten(str(message.clean_content), 1024 - len(jump) - 2)
        if message.edited_at:
            edit_at = f"<t:{round(message.edited_at.timestamp())}:R>"
        else:
            edit_at = ""
        # noinspection PyTypeChecker
        values = [
            f"**ID**: `{message.id}`",
            f"**Author**: {message.author.mention} ({message.author.id})",
            f"**Embeds**: {len(message.embeds)}",
            f"**Channel**: {message.channel.mention}",
            f"**Mentions @everyone/@here?** {utils.Emojis.bool(message.mention_everyone)}",
            f"**User Mentions**: {len(message.mentions)}",
            f"**Channel Mentions**: {len(message.channel_mentions)}",
            f"**Role Mentions**: {len(message.role_mentions)}",
            f"**URL**: {self.hyperlink(message.jump_url, 'Jump to Message')}",
            f"**Pinned?** {utils.Emojis.bool(message.pinned)}",
            f"**Attachments**: {len(message.attachments)}",
            f"**Created**: <t:{round(message.created_at.timestamp())}:R>",
            f"**Edited**: {edit_at}",
            f"**System Message**: {utils.Emojis.bool(message.is_system())}",
        ]
        embed = discord.Embed(
            title="Message from %s" % message.author.display_name,
            description="\n".join(values),
            colour=message.author.colour,
            timestamp=message.created_at,
            url=message.jump_url,
        )
        if message.content:
            embed.add_field(name="Message Content:", value=content, inline=False)
        embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
        return await ctx.respond(
            embed=embed, ephemeral=ctx.channel.permissions_for(ctx.guild.default_role).send_messages is False
        )

    @commands.slash_command(name="role-info")
    async def role_info(self, ctx: discord.ApplicationContext, *, role: discord.Role):
        """Shows you all the information about a provided role"""
        permissions_endpoint = "https://finitereality.github.io/permissions-calculator/?v=%d"
        values = [
            f"**ID**: `{role.id}`",
            f"**Name**: {role.name}",
            f"**Mention**: {role.mention}",
            f"**Color**: {role.colour}",
            f"**Hoisted?** {utils.Emojis.bool(role.hoist)}",
            f"**Mentionable?** {utils.Emojis.bool(role.mentionable)}",
            f"**Managed By Integration?** {utils.Emojis.bool(role.managed)}",
            f"**Position**: {role.position}",
            f"**Created**: <t:{round(role.created_at.timestamp())}:R>",
            f"**Members**: {len(role.members)}",
            f"**Permissions**: {self.hyperlink(permissions_endpoint % role.permissions.value, 'View Online')}",
        ]
        if role.managed:
            values.append("_Management Information:_")
            values.append(f"**Managed By Bot?**: {utils.Emojis.bool(role.tags.is_bot_managed())}")
            values.append(f"**Managed By Server Boost?**: {utils.Emojis.bool(role.tags.is_premium_subscriber())}")
            values.append(f"**Managed By Integration?**: {utils.Emojis.bool(role.tags.is_integration())}")

            if role.tags.is_bot_managed():
                user = await self.bot.fetch_user(role.tags.bot_id)
                values.append(f"**Managed By**: {user.mention} (`{user.id}`)")
        embed = discord.Embed(
            title=f"{role.name}'s information:",
            description="\n".join(values),
            colour=role.colour,
            timestamp=role.created_at,
        )
        embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
        return await ctx.respond(embed=embed)

    @commands.slash_command(name="invite-info")
    async def invite_info(self, ctx: discord.ApplicationContext, *, invite: str):
        """Gives you information about a provided invite"""
        # NOTE: All responses for this command must be ephemeral due to the sensitive nature.
        # For example, automods may punish users or users may misuse the command to advertise.
        await ctx.defer(ephemeral=True)
        try:
            invite: discord.Invite = await self.bot.fetch_invite(discord.utils.resolve_invite(invite))
        except discord.HTTPException:
            return await ctx.respond("Invalid Invite Code.", ephemeral=True)

        if invite.expires_at:
            expires_at = f"<t:{round(invite.expires_at.timestamp())}:R>"
        else:
            expires_at = f"Never"

        # Since fetch_invite doesn't give us every attr we want, we have to see if we can pull it through a cheaty way.
        if (
            isinstance(
                invite.channel,
                (discord.TextChannel, discord.VoiceChannel, discord.CategoryChannel, discord.StageChannel),
            )
            and invite.channel.permissions_for(invite.guild.me).manage_guild
        ):
            invite: discord.Invite = discord.utils.get(await invite.channel.invites(), id=invite.id)
            max_uses = "{:,}".format(invite.max_uses) if invite.max_uses else "infinite"
            uses = "{:,}".format(invite.uses)
            created_at = f"<t:{round(invite.created_at.timestamp())}:R>"
            is_temporary = utils.Emojis.bool(invite.temporary)
            member_count = "{:,}".format(invite.channel.guild.member_count)
        else:
            max_uses = uses = created_at = is_temporary = "Unknown"
            member_count = "{:,}".format(invite.approximate_member_count)

        values = [
            f"**Code**: `{invite.code}`",
            f"**URL**: {self.hyperlink(invite.url)}",
            f"**Uses**: {uses}",
            f"**Max uses**: {max_uses}",
            f"**Temporary Membership?** {is_temporary}",
            f"**Created**: {created_at}",
            f"**Expires**: {expires_at}",
        ]

        # noinspection PyUnresolvedReferences
        guild_data = [
            f"**ID**: `{invite.guild.id}`",
            f"**Name**: {discord.utils.escape_markdown(invite.guild.name)}",
            f"**Verification Level**: {invite.guild.verification_level.name} "
            f"({verification_levels[invite.guild.verification_level]})",
            f"**Member Count**: {member_count}",
        ]

        embed = discord.Embed(
            title="Information for invite %r:" % invite.code,
            description="\n".join(values),
            colour=ctx.author.colour,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Invite Guild Information:", value="\n".join(guild_data), inline=True)
        embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
        return await ctx.respond(embed=embed, ephemeral=True)

    @commands.slash_command(name="server-info")
    async def server_info(self, ctx: discord.ApplicationContext):
        """Shows information about the server."""
        if not ctx.guild:
            return await ctx.respond("This command can only be used in a server.")

        await ctx.defer()

        filter_level_name = content_filter_names[ctx.guild.explicit_content_filter]
        filter_level_description = content_filters[ctx.guild.explicit_content_filter]
        system_channel_flags = []
        if ctx.guild.system_channel:
            _flag_items = {
                "join_notifications": "Random join message",
                "premium_subscriptions": "Boost message",
                "guild_reminder_notifications": "'Helpful' server setup tips",
                "join_notification_replies": "'Wave to [user]' on join messages",
            }
            for flag, name in _flag_items.items():
                if getattr(ctx.guild.system_channel_flags, flag) is True:
                    system_channel_flags.append(name)

        if ctx.guild.me.guild_permissions.create_instant_invite:
            invites = len(await ctx.guild.invites())
        else:
            invites = "Missing 'create instant invite' permission."

        if ctx.guild.me.guild_permissions.manage_webhooks:
            webhooks = len(await ctx.guild.webhooks())
        else:
            webhooks = "Missing 'manage webhooks' permission."

        if ctx.guild.me.guild_permissions.ban_members:
            bans = f"{len(await ctx.guild.bans()):,}"
        else:
            bans = "Missing 'ban members' permission."

        # noinspection PyUnresolvedReferences
        values = [
            f"**ID**: `{ctx.guild.id}`",
            f"**Name**: {discord.utils.escape_markdown(ctx.guild.name)}",
            f"**Icon URL**: {self.hyperlink(ctx.guild.icon.url)}" if ctx.guild.icon else None,
            f"**Banner URL**: {self.hyperlink(ctx.guild.banner.url)}" if ctx.guild.banner else None,
            f"**Splash URL**: {self.hyperlink(ctx.guild.splash.url)}" if ctx.guild.splash else None,
            f"**Discovery Splash URL**: {self.hyperlink(ctx.guild.discovery_splash.url) if ctx.guild.discovery_splash else 'No discovery splash'}",
            f"**Owner**: {ctx.guild.owner.mention}",
            f"**Created**: <t:{round(ctx.guild.created_at.timestamp())}:R>",
            f"**Emojis**: {len(ctx.guild.emojis)}",
            f"**Roles**: {len(ctx.guild.roles)}",
            f"**Members**: {ctx.guild.member_count:,}",
            f"**VC AFK Timeout**: {utils.format_time(ctx.guild.afk_timeout)}",
            f"**AFK Channel**: {ctx.guild.afk_channel.mention if ctx.guild.afk_channel else 'None'}",
            f"**Moderation requires 2fa?** {utils.Emojis.bool(ctx.guild.mfa_level > 0)}",
            f"**Verification Level**: {ctx.guild.verification_level.name} ({verification_levels[ctx.guild.verification_level]})",
            f"**Content Filter**: {filter_level_name} ({filter_level_description})",
            f"**Default Notifications**: {ctx.guild.default_notifications.name.title().replace('_', ' ')}",
            f"**Features**: {', '.join(str(x).title().replace('_', ' ') for x in ctx.guild.features)}",
            f"**Boost Level**: {ctx.guild.premium_tier}",
            f"**Boost Count**: {ctx.guild.premium_subscription_count:,}",  # if a guild has over 1k boosts im sad
            f"**Invites**: {invites}",
            f"**Webhooks**: {webhooks}",
            f"**Bans**: {bans}",
            f"**Categories**: {len(ctx.guild.categories)}",
            f"**Text Channels**: {len(ctx.guild.text_channels)}",
            f"**Voice Channels**: {len(ctx.guild.voice_channels)}",
            f"**Stage Channels**: {len(ctx.guild.stage_channels)}",
            f"**Approximate Thread Count**: {len(ctx.guild.threads):,}",
            f"**Rules Channel**: {ctx.guild.rules_channel.mention if ctx.guild.rules_channel else 'None'}",
            f"**System Messages Channel**: {ctx.guild.system_channel.mention if ctx.guild.system_channel else 'None'}",
            f"**System Messages Settings**: {', '.join(system_channel_flags) if system_channel_flags else 'None'}",
            f"**Emoji Limit**: {ctx.guild.emoji_limit:,}",
            f"**Sticker Limit**: {ctx.guild.sticker_limit:,}",
            f"**Max VC bitrate**: {ctx.guild.bitrate_limit/1000:.1f}kbps",
            f"**Max Upload Size**: {ctx.guild.filesize_limit/1024/1024:.1f}MB",
        ]
        values = list(filter(lambda x: x is not None, values))
        embed = discord.Embed(
            title=f"{ctx.guild.name} ({ctx.guild.id})",
            description="\n".join(values),
            color=discord.Color.blurple(),
            timestamp=ctx.guild.created_at,
        )
        embed.set_thumbnail(url=ctx.guild.icon.url)
        embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url)
        if ctx.guild.description is not None:
            embed.add_field(name="Guild Description", value=ctx.guild.description)
        return await ctx.respond(embed=embed)

    @commands.slash_command(name="emoji-info")
    async def emoji_info(self, ctx: discord.ApplicationContext, emoji: str):
        try:
            emoji = await commands.PartialEmojiConverter().convert(ctx, emoji)
        except commands.PartialEmojiConversionFailure:
            paginator = commands.Paginator(prefix="", suffix="", max_size=4069)

            def to_string(_chr):
                digit = f"{ord(_chr):x}"
                name = unicodedata.name(_chr, "Name not found.").lower()
                return f"`\\U{digit:>08}`: {name} - {_chr}"

            for char in emoji.strip():
                paginator.add_line(to_string(char))
            embeds = []
            for page in paginator.pages:
                embeds.append(discord.Embed(description=page))
            return await ctx.respond(embeds=embeds)
        else:
            u200b = "\u200b"
            e = discord.Embed(
                title=f"{emoji.name}'s info:",
                description=f"**Name:** {emoji.name}\n"
                f"**ID:** {emoji.id}\n"
                f"**Format:** `{str(emoji).replace(':', u200b + ':')}`\n"
                f"**Animated?:** {utils.Emojis.bool(emoji.animated)}\n"
                f"**Custom?:** {utils.Emojis.bool(emoji.is_custom_emoji())}\n"
                f"**URL:** {self.hyperlink(emoji.url)}\n",
                color=discord.Colour.orange(),
                timestamp=emoji.created_at,
            )
            e.set_image(url=str(emoji.url))
            return await ctx.respond(embed=e)


def setup(bot):
    bot.add_cog(Info(bot))
