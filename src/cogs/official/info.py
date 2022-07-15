import datetime
import platform
import re
import subprocess
import sys
import textwrap
import time
from io import BytesIO
from textwrap import shorten
from typing import Union, Tuple, Optional, List
from urllib.parse import urlparse

import bs4
import discord
import httpx
import unicodedata
from bs4 import BeautifulSoup
from discord.ext import commands, pages

from src import utils
from src.bot.client import Bot
from src.utils.views import StealEmojiView

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

nsfw_levels = {
    discord.NSFWLevel.default: "Uncategorized",
    discord.NSFWLevel.explicit: "Guild contains NSFW content",
    discord.NSFWLevel.safe: "Guild does not contain NSFW content",
    discord.NSFWLevel.age_restricted: "Guild *may* contain NSFW content",
}


async def unfurl_invite_url(url: str) -> Union[Tuple[str, re.Match], Tuple[None, None]]:
    from src.bot.client import bot

    # bot.console.log(f"(UNFURLER) Preparing to unfurl {url}")
    # Dear maintainers,
    # This dictionary is designed to fully automate and streamline the gathering of scraped data.
    # If it has to have its own function, define it in a lambda. If you cannot do that, the service cannot be used.
    # Make sure that:
    # * The `domain` regex returns a URl that can be parsed.
    # * The `invites.server` regex has a `url` group in it that returns the invite URL
    # * The `invites.bot` regex has a `client_id` group in it that returns the client ID
    # * The `invites.server` regex returns a discord(app).gg|com URL
    # * Do not include an invite type in the `invites` dictionary if that domain does not support that type of invite.
    # * `query_tags.names` is as minimal as possible. The more we search, the more performance hit we take.
    # * `query_tags.max_search` is also as minimal as can be, if not exact. Again, fewer iterations = more performance

    s_r = r"(?:https?://)?discord(app)?\.(com|gg)(/invite)?/.{5,16}"
    b_r = r"(?:https?://)?discord.com/oauth2/authorize\?.*(?P<client_id>client_id=\d+).*"
    regexes = (
        {
            "domain": re.compile(r"(https?://)?dsc.(gg|lol)/.+"),
            "invites": {
                "server": re.compile(r"window\.location\.href(\s)?=(\s)?\"(?P<url>%s)\"" % s_r),
                "bot": re.compile(r"window\.location\.href\s?=\s?\"(?P<url>%s)\"" % b_r),
            },
            "query_tags": {"names": ("script",), "max_search": 3},
        },
        {
            "domain": re.compile(r"(https?://)?invite.gg/.+"),
            "invites": {"server": re.compile(r"href=([\"'])(?P<url>%s)([\"'])" % s_r)},
            "query_tags": {"names": ("a",), "max_search": 2},
        },
        {
            "domain": re.compile(r"(https?://)?bit.ly/.+"),
            "trust_status": (301, 302, 307, 308),
            "invites": {"server": re.compile(s_r), "bot": re.compile(b_r)},
            "query_tags": {
                # backup
                "names": ("a",),
                "max_search": 3,  # there's only one A tag there
            },
        },
    )

    def qualify(unsanitary_url: str) -> str:
        return urlparse(unsanitary_url, "https").geturl()

    url = qualify(url)

    if re.compile(b_r).match(url):
        return "bot", re.compile(b_r).match(url)  # lazy

    if re.compile(s_r).match(url):
        return "server", re.compile(s_r).match(url)

    try:
        _invite = await bot.fetch_invite(url)
    except discord.HTTPException:
        pass
    else:
        return "server", _invite.url

    for entry in regexes:
        if entry["domain"].match(url):
            trusted_statuses = entry.get("trust_status", None)
            if trusted_statuses is not None:
                try:
                    bot.console.log(f"(UNFURLER) HEAD {url!r}")
                    head: httpx.Response = await utils.session.head(url)
                except httpx.HTTPError:
                    raise
                else:
                    if head.status_code in trusted_statuses and head.headers.get("Location") is not None:
                        location = qualify(head.headers["Location"])
                        for invite_type, invite_regex in entry["invites"].items():
                            if _m := invite_regex.match(location):
                                return invite_type, _m

            try:
                get: httpx.Response = await utils.session.get(url)
                get.raise_for_status()
            except httpx.HTTPError:
                raise
            else:
                soup = await utils.run_blocking(BeautifulSoup, get.text, features="html.parser")
                # noinspection PyTypeChecker
                for tag_name in entry["query_tags"]["names"]:
                    found_tags = soup.html.find_all(tag_name)
                    for tag in found_tags[: entry["query_tags"]["max_search"]]:
                        tag: bs4.Tag
                        for invite_type, invite_regex in entry["invites"].items():
                            location = tag.get_text(strip=True)
                            if _m := invite_regex.match(location):
                                return invite_type, _m
    return None, None


class Info(commands.Cog):
    def __init__(self, bot: Bot):
        self.bot: Bot = bot

    def get_user_data(self, user: Union[discord.User, discord.Member], guild: discord.Guild = None) -> List[str]:
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
        ]

        if user.avatar is not None:
            values.append(f"**Avatar URL**: {self.hyperlink(user.avatar.url)}")

        if user.bot is True:
            link = discord.utils.oauth_url(
                user.id,
                scopes=("bot", "applications.commands"),
            )
            values.append(f"**Bot Invite**: {self.hyperlink(link)}")

        if isinstance(user, discord.Member):
            if user.display_avatar != user.avatar:
                values.append("**Display Avatar**: %s" % self.hyperlink(user.display_avatar.url))

            if user.communication_disabled_until and user.communication_disabled_until >= discord.utils.utcnow():
                values.append(f"**Timeout expires:** <t:{round(user.communication_disabled_until.timestamp())}:R>")

        values = list(filter(lambda x: x is not None, values))  # remove guild-only shit
        return values

    async def get_server_data(
        self, ctx: Union[discord.ApplicationContext, commands.Context], guild: discord.Guild = None
    ) -> discord.Embed:
        guild = guild or ctx.guild
        filter_level_name = content_filter_names[guild.explicit_content_filter]
        filter_level_description = content_filters[guild.explicit_content_filter]
        system_channel_flags = []
        if guild.system_channel:
            _flag_items = {
                "join_notifications": "Random join message",
                "premium_subscriptions": "Boost message",
                "guild_reminder_notifications": "'Helpful' server setup tips",
                "join_notification_replies": "'Wave to [user]' on join messages",
            }
            for flag, name in _flag_items.items():
                if getattr(guild.system_channel_flags, flag) is True:
                    system_channel_flags.append(name)

        if guild.me.guild_permissions.manage_guild:
            invites = len(await guild.invites())
        else:
            invites = "Missing 'manage server' permission."

        if guild.me.guild_permissions.manage_webhooks:
            webhooks = len(await guild.webhooks())
        else:
            webhooks = "Missing 'manage webhooks' permission."

        if guild.me.guild_permissions.ban_members:
            bans = f"{len(await guild.bans().flatten()):,}"
        else:
            bans = "Missing 'ban members' permission."

        discovery_splash = "No discovery splash"
        if guild.discovery_splash:
            discovery_splash = self.hyperlink(guild.discovery_splash.url)

        if guild.owner is None:
            await guild.query_members(user_ids=[guild.owner_id], cache=True)

        # noinspection PyUnresolvedReferences
        values = [
            f"**ID**: `{guild.id}`",
            f"**Name**: {discord.utils.escape_markdown(guild.name)}",
            f"**Icon URL**: {self.hyperlink(guild.icon.url)}" if guild.icon else None,
            f"**Banner URL**: {self.hyperlink(guild.banner.url)}" if guild.banner else None,
            f"**Splash URL**: {self.hyperlink(guild.splash.url)}" if guild.splash else None,
            f"**Discovery Splash URL**: {discovery_splash}",
            f"**Owner**: {guild.owner.mention}",
            f"**Created**: {discord.utils.format_dt(guild.created_at, 'R')}",
            f"**Locale**: {guild.preferred_locale}",
            f"**NSFW Level**: {nsfw_levels[guild.nsfw_level]}",
            f"**Emojis**: {len(guild.emojis)}",
            f"**Stickers**: {len(guild.stickers)}",
            f"**Roles**: {len(guild.roles)}",
            f"**Members**: {guild.member_count:,}",
            f"**VC AFK Timeout**: {utils.format_time(guild.afk_timeout)}",
            f"**AFK Channel**: {guild.afk_channel.mention if guild.afk_channel else 'None'}",
            f"**Moderation requires 2fa?** {utils.Emojis.bool(guild.mfa_level > 0)}",
            f"**Verification Level**: {guild.verification_level.name} "
            f"({verification_levels[guild.verification_level]})",
            f"**Content Filter**: {filter_level_name} ({filter_level_description})",
            f"**Default Notifications**: {guild.default_notifications.name.title().replace('_', ' ')}",
            f"**Features**: {', '.join(str(x).title().replace('_', ' ') for x in guild.features)}",
            f"**Boost Level**: {guild.premium_tier}",
            f"**Boost Count**: {guild.premium_subscription_count:,}",  # if a guild has over 1k boosts im sad
            f"**Boost Progress Bar Enabled?** {utils.Emojis.bool(guild.premium_progress_bar_enabled)}",
            f"**Invites**: {invites}",
            f"**Webhooks**: {webhooks}",
            f"**Bans**: {bans}",
            f"**Categories**: {len(guild.categories)}",
            f"**Text Channels**: {len(guild.text_channels)}",
            f"**Voice Channels**: {len(guild.voice_channels)}",
            f"**Stage Channels**: {len(guild.stage_channels)}",
            f"**Approximate Thread Count**: {len(guild.threads):,}",
            f"**Rules Channel**: {guild.rules_channel.mention if guild.rules_channel else 'None'}",
            f"**System Messages Channel**: {guild.system_channel.mention if guild.system_channel else 'None'}",
            f"**System Messages Settings**: {', '.join(system_channel_flags) if system_channel_flags else 'None'}",
            f"**Emoji Limit**: {guild.emoji_limit:,}",
            f"**Sticker Limit**: {guild.sticker_limit:,}",
            f"**Max VC bitrate**: {guild.bitrate_limit/1000:.1f}kbps",
            f"**Max Upload Size**: {guild.filesize_limit/1024/1024:.1f}MB",
            f"**Max Members**: {guild.max_members or 500000:,}",
            f"**Max Online Members**: {guild.max_presences or guild.max_members or 500000:,}",
            f"**Max Video Channel Users**: {guild.max_video_channel_users}",
            f"**Scheduled Events**: {len(guild.scheduled_events)}",
        ]
        values = list(filter(lambda x: x is not None, values))
        embed = discord.Embed(
            title=f"{guild.name} ({guild.id})",
            description="\n".join(values),
            color=discord.Color.blurple(),
            timestamp=guild.created_at,
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
        if guild.description is not None:
            embed.add_field(name="Guild Description", value=guild.description)

        return embed

    @staticmethod
    def first_line(text: str, max_length: int = 100, placeholder: str = "...") -> str:
        line = text.splitlines(False)[0]
        return textwrap.shorten(line, max_length, placeholder=placeholder)

    @staticmethod
    def hyperlink(url: str, text: str = ...):
        if text is ...:
            parsed = urlparse(url)
            text = parsed.hostname.lower()

        return f"[{text}]({url})"

    @staticmethod
    async def parse_avatar(
        avatar: discord.Asset, fs_limit: int = 1024 * 1024 * 8
    ) -> Tuple[Optional[str], discord.Embed, Optional[discord.File]]:
        avatar_data: bytes = await avatar.read()

        content = None
        file = None

        if len(avatar_data) >= fs_limit:
            content = avatar.url
            embed = discord.Embed(colour=discord.Colour.orange())
            embed.set_image(url=avatar.url)
        else:
            bio = BytesIO()
            bio.write(avatar_data)
            bio.seek(0)
            ext = avatar.url.split(".")[-1]
            ext = ext[: ext.index("?")]
            file = discord.File(bio, filename=f"avatar.{ext}")
            embed = discord.Embed(colour=discord.Colour.dark_orange()).set_image(url=f"attachment://avatar.{ext}")

        if file is not None:
            embed.set_footer(text="persistent file - even if the user's avatar changes, this image will still work.")
        else:
            embed.set_footer(text="cached file - if the user's avatar changes, this image will break.")
        return content, embed, file

    @commands.slash_command()
    @commands.bot_has_permissions(embed_links=True, attach_files=True)
    async def avatar(self, ctx: discord.ApplicationContext, user: discord.User):
        """Shows you someone's avatar."""
        await ctx.defer()

        if ctx.guild:
            user: Union[discord.Member, discord.User] = await discord.utils.get_or_fetch(
                ctx.guild, "member", user.id, default=user
            )

        embeds = []
        files = []
        if hasattr(user, "guild_avatar") and user.guild_avatar is not None:
            content, embed, file = await self.parse_avatar(user.guild_avatar)
            if content:
                await ctx.respond(content, embed=embed, file=file)
            else:
                embeds.append(embed)
                if file:
                    files.append(file)

        content, embed, file = await self.parse_avatar(user.avatar)
        if content:
            await ctx.respond(content, embed=embed, file=file)
        else:
            embeds.append(embed)
            if file:
                files.append(file)

            return await ctx.respond(None, embeds=embeds, files=files)

    @commands.user_command(name="Avatar")
    @commands.bot_has_permissions(embed_links=True, attach_files=True)
    async def get_user_avatar(self, ctx: discord.ApplicationContext, user: discord.User):
        return await self.avatar(ctx, user)

    @commands.slash_command(name="user-info")
    async def user_info(self, ctx: discord.ApplicationContext, user: discord.User = None):
        """Shows you information about a user."""
        embeds = []
        user: Union[discord.User, discord.Member]
        user = user or ctx.user
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
                        if line.startswith("NAME="):
                            version_name = line.split("=")[1].strip().strip('"')
                        elif line.startswith("VERSION="):
                            version_id = line.split("=")[1].strip().strip('"')

                    version_string = "%s %s" % (version_name, version_id)

                    kernel_version = await utils.run_blocking(
                        subprocess.run, ("uname", "-r"), capture_output=True, encoding="utf-8", check=True
                    )
                    version_string += ", kernel version `%s`" % kernel_version.stdout.strip()
                    os_version = version_string

            sys_started = discord.utils.utcnow() - datetime.timedelta(seconds=time.monotonic())

            embed = discord.Embed(
                title="My Information:",
                description=f"WebSocket Latency (ping): {latency}ms\n"
                f"Bot Started: {discord.utils.format_dt(self.bot.started_at, 'R')}\n"
                f"System Started: {discord.utils.format_dt(sys_started, 'R')}\n"
                f"Bot Last Connected: {discord.utils.format_dt(self.bot.last_logged_in, 'R')}\n"
                f"Bot Created: {discord.utils.format_dt(self.bot.user.created_at, 'R')}\n"
                f"\n"
                f"Cached Users: {len(self.bot.users):,}\n"
                f"Guilds: {len(self.bot.guilds):,}\n"
                f"Total Channels: {len(tuple(self.bot.get_all_channels())):,}\n"
                f"Total Emojis: {len(self.bot.emojis):,}\n"
                f"Cached Messages: {len(self.bot.cached_messages):,}\n"
                f"\n"
                f"Python Version: {sys.version.split(' ')[0]}\n"
                f"Pycord Version: {discord.__version__}\n"
                f"Bot Version: [v2#{spanner_version}](https://github.com/EEKIM10/spanner-v2/tree/{spanner_version})\n"
                f"OS Version: {os_version}\n",
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
        embed.set_author(name=ctx.user.display_name, icon_url=ctx.user.display_avatar.url)
        embeds.append(embed)
        return await ctx.respond(embeds=embeds)

    @commands.user_command(name="User Info")
    async def user_info_user_command(self, ctx: discord.ApplicationContext, user: Union[discord.User, discord.Member]):
        return await self.user_info(ctx, user)

    @commands.slash_command(name="channel-info")
    async def channel_info(
        self,
        ctx: discord.ApplicationContext,
        channel: discord.Option(
            discord.abc.GuildChannel,
            description="The channel to get information on. Defaults to the current channel.",
            default=None,
            channel_types=[
                discord.ChannelType.text,
                discord.ChannelType.voice,
                discord.ChannelType.category,
                discord.ChannelType.stage_voice,
                discord.ChannelType.news,
                discord.ChannelType.news_thread,
                discord.ChannelType.private_thread,
                discord.ChannelType.public_thread,
                discord.ChannelType.forum,
            ],
        ),
    ):
        """Shows you information on a channel."""
        channel: discord.abc.GuildChannel = channel or ctx.channel
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
                f"**Created**: {discord.utils.format_dt(channel.created_at, 'R')}",
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
        elif isinstance(channel, discord.StageChannel):
            # noinspection PyUnresolvedReferences
            values = [
                f"**Name**: {discord.utils.escape_markdown(channel.name)}",
                f"**ID**: `{channel.id}`",
                f"**Category**: {channel.category.name if channel.category else 'No Category'}",
                f"**Bitrate**: {(channel.bitrate or 64000)/1000}kbps",
                f"**In Chat Now**: {len(channel.members)}",
                f"**Created**: {discord.utils.format_dt(channel.created_at, 'R')}",
                f"**Permissions Synced**: {utils.Emojis.bool(channel.permissions_synced)}",
                f"**Voice Region**: {channel.rtc_region.value if channel.rtc_region else 'Automatic'}",
                f"**Video Quality**: {channel.video_quality_mode.name}",
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
        elif isinstance(channel, discord.VoiceChannel):
            emoji = utils.Emojis.VOICE_CHANNEL
            if channel.permissions_for(channel.guild.default_role).read_messages is False:
                emoji = utils.Emojis.LOCKED_VOICE_CHANNEL

            # noinspection PyUnresolvedReferences
            values = [
                f"**Name**: {discord.utils.escape_markdown(channel.name)}",
                f"**ID**: `{channel.id}`",
                f"**Category**: {channel.category.name if channel.category else 'No Category'}",
                f"**Bitrate**: {(channel.bitrate or 64000) / 1000}kbps",
                f"**User Limit**: {channel.user_limit}",
                f"**In Chat Now**: {len(channel.members)}",
                f"**Created**: {discord.utils.format_dt(channel.created_at, 'R')}",
                f"**Permissions Synced**: {utils.Emojis.bool(channel.permissions_synced)}",
                f"**Voice Region**: {channel.rtc_region.value if channel.rtc_region else 'Automatic'}",
                f"**Video Quality**: {channel.video_quality_mode.value}",
            ]
            embed = discord.Embed(
                title="%s%s" % (emoji, channel.name), description="\n".join(values), colour=discord.Colour.og_blurple()
            )
            if "TEXT_IN_VOICE_ENABLED" in ctx.guild.features:
                embed.set_footer(
                    text="Warning: You have text-in-voice enabled - I am, however, currently unable to fetch "
                    "information on the text portion of voice channels."
                )
        elif isinstance(channel, discord.CategoryChannel):
            values = [
                f"**ID**: `{channel.id}`",
                f"**Name**: {discord.utils.escape_markdown(channel.name)}",
                f"**Created**: {discord.utils.format_dt(channel.created_at, 'R')}",
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
        else:
            # noinspection PyUnresolvedReferences
            return await ctx.respond(
                "It doesn't look like I support this channel type yet!\n"
                "Recently discord has added a whole host of new channel types since this command was written"
                ". Currently, the only supported channel types are text, voice (and stage), and categories.\n"
                "If another type of channel works, not all information will be available, and some may be missing."
                " Updating this command is a low priority, so you may have to wait a while for support for the channel"
                f" type of {channel.type.name.replace('_', ' ').title()!r} to be supported.\n"
                f"Join the support server "
            )

        embed.set_author(name=ctx.user.display_name, icon_url=ctx.user.display_avatar.url)
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

        if message.reference is not None:
            resolved = message.reference.resolved
            if resolved is None:
                try:
                    channel = self.bot.get_channel(message.reference.channel_id)
                    resolved = await channel.fetch_message(message.reference.message_id)
                except discord.HTTPException:
                    pass
            if resolved is not None and not isinstance(resolved, discord.DeletedReferencedMessage):
                embed.add_field(
                    name="In reply to:",
                    value=f"[Message from {resolved.author.mention}]({message.jump_url})",
                    inline=False,
                )
        elif message.interaction is not None:
            embed.add_field(
                name=f"In response to:",
                value=f"Command {message.interaction.name!r} from {message.interaction.user.mention} for "
                f"{message.author.mention}",
                inline=False,
            )

        embed.set_author(name=ctx.user.display_name, icon_url=ctx.user.display_avatar.url)

        embeds = [embed]
        for embed in message.embeds:
            if embed.type == "rich":
                fields = []
                if embed.author:
                    fields.append(
                        f"**Author**:\n"
                        f"\\* Name: {textwrap.shorten(embed.author.name or '*Blank*', 100, placeholder='...')}\n"
                        f"\\* URL: {self.hyperlink(embed.author.url) if embed.author.url else '*Blank*'}"
                    )
                if embed.title:
                    fields.append(f"**Title**:\n> {textwrap.shorten(embed.title, 1000, placeholder='...')}")
                if embed.description:
                    fields.append(f"**Description**:\n> {self.first_line(embed.description, 2000)}")
                if embed.thumbnail.url is not discord.Embed.Empty:
                    fields.append(
                        f"**Thumbnail URL**: {self.hyperlink(embed.thumbnail.url)} "
                        f"{self.hyperlink(embed.thumbnail.proxy_url, text='(proxy)')}"
                    )
                fields.append(f"**Colour**: {embed.colour or discord.Colour.default()}")
                if embed.fields:
                    fields.append(f"**Fields**: {len(embed.fields)}/25")
                if embed.footer is not discord.Embed.Empty:
                    shortened_text = textwrap.shorten(
                        discord.utils.escape_markdown(embed.footer.text or "*Blank*"), 100, placeholder="..."
                    )
                    fields.append(
                        f"**Footer**:\n"
                        f"\\* Text: {shortened_text}\n"
                        f"\\* Icon: {self.hyperlink(embed.footer.icon_url) if embed.footer.icon_url else '*Blank*'}"
                    )
                if embed.timestamp:
                    fields.append(f"**Timestamp**: {discord.utils.format_dt(embed.timestamp, 'F')}")
                if embed.image:
                    fields.append(
                        f"**Image URL**: "
                        f"{self.hyperlink(embed.image.url)} {self.hyperlink(embed.image.proxy_url, '(proxy)')}"
                    )
                fields.append(f"**Total size**: {len(embed):,}/6,000 characters")

                for n, field in enumerate(fields):
                    fields[n] = field.replace("\u200b", "[ZWSP]")

                embeds.append(
                    discord.Embed(
                        title=f"Information on embed #{len(embeds)}:",
                        description="\n".join(fields),
                        colour=embed.colour or discord.Colour.default(),
                    )
                )

        return await ctx.respond(
            embeds=embeds[:10], ephemeral=ctx.channel.permissions_for(ctx.guild.default_role).send_messages is False
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
        embed.set_author(name=ctx.user.display_name, icon_url=ctx.user.display_avatar.url)
        return await ctx.respond(embed=embed)

    @commands.slash_command(name="invite-info")
    async def invite_info(self, ctx: discord.ApplicationContext, *, invite: str):
        """Gives you information about a provided invite"""
        # NOTE: All responses for this command must be ephemeral due to the sensitive nature.
        # For example, automods may punish users or users may misuse the command to advertise.
        await ctx.defer(ephemeral=True)
        # self.bot.console.log(invite)
        try:
            invite_matches = await unfurl_invite_url(invite)
        except httpx.HTTPError as e:
            return await ctx.respond(str(e) + ".", ephemeral=True)
        except (KeyError, ValueError, TypeError):
            try:
                # noinspection PyTypeChecker
                converted = await commands.InviteConverter().convert(ctx, invite)
            except commands.BadInviteArgument as e:
                return await ctx.respond(str(e) + ".", ephemeral=True)
            else:
                invite: discord.Invite = converted
        else:
            self.bot.console.log(invite_matches)
            if all(v is not None for v in invite_matches) and invite_matches[0] == "bot":
                self.bot.console.log()
                client_id = int(invite_matches[1].group("client_id").split("=")[-1])
                try:
                    user: discord.User = await self.bot.get_or_fetch_user(client_id)
                except discord.HTTPException as e:
                    return await ctx.respond(f"Failed to resolve invite data: {e}", ephemeral=True)
                else:
                    embed = discord.Embed(
                        title=f"Invite - {user}",
                        description=f"Run `/user-info user:{user.id}` to get this bot's information.",
                    )
                    embed.set_thumbnail(url=user.display_avatar.url)
                    return await ctx.respond(embed=embed, ephemeral=True)

            invite: str = invite_matches[-1].group("url") if invite_matches[-1] == "server" else invite

            try:
                invite: discord.Invite = await self.bot.fetch_invite(invite)
            except discord.HTTPException:
                return await ctx.respond("Invalid Invite Code.", ephemeral=True)

        if invite.expires_at:
            expires_at = discord.utils.format_dt(invite.expires_at, "R")
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
            f"**Creator**: {invite.inviter} (`{invite.inviter.id if invite.inviter else 'unknown'}`)",
        ]

        # noinspection PyUnresolvedReferences
        guild_data = [
            f"**ID**: `{invite.guild.id}`",
            f"**Name**: {discord.utils.escape_markdown(invite.guild.name)}",
            f"**Verification Level**: {invite.guild.verification_level.name} "
            f"({verification_levels[invite.guild.verification_level]})",
            f"**Member Count**: {member_count}",
            f"**Invite Channel**: <#{invite.channel.id}> ({getattr(invite.channel, 'name', 'unknown-channel')!r})",
        ]

        embed = discord.Embed(
            title="Information for invite %r:" % invite.code,
            description="\n".join(values),
            colour=ctx.user.colour,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Invite Guild Information:", value="\n".join(guild_data), inline=True)
        embed.set_author(name=ctx.user.display_name, icon_url=ctx.user.display_avatar.url)
        return await ctx.respond(embed=embed, ephemeral=True)

    @commands.slash_command(name="server-info")
    @discord.guild_only()
    async def server_info(self, ctx: discord.ApplicationContext):
        """Shows information about the server."""
        if not ctx.guild:
            return await ctx.respond("This command can only be used in a server.")

        await ctx.defer()
        embed = await self.get_server_data(ctx)
        return await ctx.respond(embed=embed)

    @commands.command(name="server-info")
    @commands.is_owner()
    @commands.guild_only()
    async def server_info_text_command(self, ctx: commands.Context, *, guild: str = None):
        """Shows information about a server"""
        if guild is None:
            guild = ctx.guild
        else:
            for g in self.bot.guilds:
                if guild.lower() in g.name.lower() or str(g.id) == guild:
                    guild = g
                    break

        async with ctx.typing():
            embed = await self.get_server_data(ctx, guild)
        return await ctx.reply(embed=embed)

    @commands.slash_command(name="emoji-info")
    async def emoji_info(self, ctx: discord.ApplicationContext, emoji: str):
        """Shows you information on an emoji, both built-in (e.g. faces) and custom ones."""
        try:
            # noinspection PyTypeChecker
            emoji = await commands.PartialEmojiConverter().convert(ctx, emoji)
        except commands.PartialEmojiConversionFailure:
            paginator = commands.Paginator(prefix="", suffix="", max_size=4069)
            paginator.add_line(
                "Emoji was not detected as a custom emoji. Assuming you wanted the unicode information.", empty=True
            )

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
            e = discord.Embed(
                title=f"{emoji.name}'s info:",
                description=f"**Name:** {emoji.name}\n"
                f"**ID:** {emoji.id}\n"
                f"**Created:** {discord.utils.format_dt(emoji.created_at, 'R')}\n"
                f"**Format:** `{str(emoji)}`\n"
                f"**Animated?:** {utils.Emojis.bool(emoji.animated)}\n"
                f"**Custom?:** {utils.Emojis.bool(emoji.is_custom_emoji())}\n"
                f"**URL:** {self.hyperlink(emoji.url)}\n",
                color=discord.Colour.orange(),
                timestamp=emoji.created_at,
            )
            try:
                # noinspection PyTypeChecker
                emoji_full = await commands.EmojiConverter().convert(ctx, str(emoji.id))
            except commands.EmojiNotFound:
                emoji_full = None
            else:
                e.description += f"**Server name:** {emoji_full.guild.name if emoji_full.guild else 'N/A'}\n"
            e.set_image(url=str(emoji.url))
            view = None
            if ctx.guild:
                if ctx.author.guild_permissions.manage_emojis:
                    if ctx.author.guild_permissions.manage_emojis:
                        if len(ctx.guild.emojis) < ctx.guild.emoji_limit:
                            if getattr(emoji_full, "guild", None) != ctx.guild:
                                if discord.utils.get(ctx.guild.emojis, name=emoji.name) is None:
                                    view = StealEmojiView(ctx.interaction, emoji=emoji_full or emoji)
            return await ctx.respond(embed=e, view=view)

    @commands.message_command(name="Emoji Info")
    async def emoji_info_message_command(self, ctx: discord.ApplicationContext, message: discord.Message):
        await ctx.defer(ephemeral=True)
        embeds = []
        for word in re.finditer(r"<(a?):([\w_]{1,32}):(\d{15,20})>", message.content):
            try:
                # noinspection PyTypeChecker
                emoji = await commands.PartialEmojiConverter().convert(ctx, word.group())
            except commands.PartialEmojiConversionFailure:
                continue
            else:
                e = discord.Embed(
                    title=f"{emoji.name}'s info:",
                    description=f"**Name:** {emoji.name}\n"
                    f"**ID:** {emoji.id}\n"
                    f"**Created:** {discord.utils.format_dt(emoji.created_at, 'R')}\n"
                    f"**Format:** `{str(emoji)}`\n"
                    f"**Animated?:** {utils.Emojis.bool(emoji.animated)}\n"
                    f"**Custom?:** {utils.Emojis.bool(emoji.is_custom_emoji())}\n"
                    f"**URL:** {self.hyperlink(emoji.url)}\n",
                    color=discord.Colour.orange(),
                    timestamp=emoji.created_at,
                )
                try:
                    # noinspection PyTypeChecker
                    emoji_full = await commands.EmojiConverter().convert(ctx, str(emoji.id))
                except commands.EmojiNotFound:
                    pass
                else:
                    e.description += f"**Server name:** {emoji_full.guild.name if emoji_full.guild else 'N/A'}\n"
                e.set_image(url=str(emoji.url))
                embeds.append(e)

        if embeds:
            paginator = pages.Paginator(embeds, disable_on_timeout=True)
            await paginator.respond(ctx.interaction, ephemeral=True)
        else:
            return await ctx.respond("No emojis found.")


def setup(bot):
    bot.add_cog(Info(bot))
