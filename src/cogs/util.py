import copy
import sys
import textwrap
from collections import deque
from typing import Dict, List, Literal

import discord
from discord import SlashCommandGroup
from discord.commands import permissions
from discord.ext import commands, pages

from src.bot.client import Bot
from src.vendor.humanize.size import naturalsize


class Utility(commands.Cog):
    def __init__(self, bot: Bot):
        self.bot: Bot = bot
        self.deleted_snipes: Dict[discord.TextChannel, deque] = {}
        self.edited_snipes: Dict[discord.TextChannel, deque] = {}

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages: List[discord.Message]):
        for message in messages:
            await self.on_message_delete(message)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        message_copy = copy.copy(message)
        if message.channel not in self.deleted_snipes:
            self.deleted_snipes[message.channel] = deque([message_copy], maxlen=1000)
        else:
            self.deleted_snipes[message.channel].append(message_copy)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.author == self.bot.user:
            return
        if before.channel not in self.edited_snipes:
            self.edited_snipes[before.channel] = deque([[before, after]], maxlen=1000)
        else:
            self.edited_snipes[before.channel].append([before, after])

    snipe = SlashCommandGroup(
        "snipe",
        "Shows you deleted and edited messages in the current channel, up to 1000, newest to oldest.",
    )

    @snipe.command()
    async def deleted(self, ctx: discord.ApplicationContext):
        """Shows you deleted messages in the current channel, up to 1000 messages ago. Newest -> oldest"""
        await ctx.defer()
        _pages = []
        if ctx.channel in self.deleted_snipes:
            for message in reversed(self.deleted_snipes[ctx.channel]):
                embed = discord.Embed(
                    description=message.content or "[no content]",
                    timestamp=message.created_at,
                    colour=message.author.colour if message.author.colour else discord.Colour.random(),
                )
                embed.set_author(name=f"{message.author.display_name}", icon_url=message.author.avatar.url)
                if not message.content and len(message.embeds) == 1:
                    embed = message.embeds[0]
                    embed.set_footer(text=f"[from {message.author}] | " + embed.footer.text)

                _pages.append(embed)
        else:
            return await ctx.respond("No snipes of this type.")

        paginator = pages.Paginator(_pages)
        await paginator.send(ctx)

    @snipe.command()
    async def edits(self, ctx: discord.ApplicationContext):
        """Shows you edited messages in the current channel, up to 1000 messages ago. Newest -> oldest"""
        await ctx.defer()
        _pages = []
        if ctx.channel in self.edited_snipes:
            for message in reversed(self.edited_snipes[ctx.channel]):
                embed = discord.Embed(
                    timestamp=message[1].created_at,
                    colour=message[1].author.colour if message[1].author.colour else discord.Colour.random(),
                )
                embed.set_author(name=f"{message[1].author.display_name}", icon_url=message[1].author.avatar.url)
                embed.add_field(
                    name="Before", value=textwrap.shorten(message[0].content, 1024, placeholder="...") or "[no content]"
                )
                embed.add_field(
                    name="After", value=textwrap.shorten(message[1].content, 1024, placeholder="...") or "[no content]"
                )

                _pages.append(embed)
        else:
            return await ctx.respond("No snipes of this type.")

        paginator = pages.Paginator(_pages)
        await paginator.send(ctx)

    @snipe.command(name="info")
    async def snipes_info(self, ctx: discord.ApplicationContext, snipe_type: str = "all"):
        """(owner only) displays information on a specific snipe cache"""
        await ctx.defer()

        def generate_embed(attr_name: Literal["deleted_snipes", "edited_snipes"]):
            attr = getattr(self, attr_name)
            size = sys.getsizeof(attr)
            embed = discord.Embed(
                title=f"self.{attr_name}:",
                description=f"**Channel Entries (keys)**: {len(attr):,}\n"
                            f"**Total Messages**: {sum(len(channel_snipes) for channel_snipes in attr.values()):,}\n"
                            f"**Memory used**: {naturalsize(size, True)}",
                colour=discord.Colour.random(),
            )
            return embed

        embeds = []

        if snipe_type == "all":
            embeds.append(generate_embed("deleted_snipes"))
            embeds.append(generate_embed("edited_snipes"))
        elif snipe_type == "deleted":
            embeds.append(generate_embed("deleted_snipes"))
        elif snipe_type == "edited":
            embeds.append(generate_embed("edited_snipes"))
        else:
            embeds.append(discord.Embed(description="Invalid snipe type."))
        return await ctx.respond(embeds=embeds)


def setup(bot):
    bot.add_cog(Utility(bot))
