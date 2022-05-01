import asyncio
import copy
import locale
import logging
import sys
import textwrap
import time
from collections import deque
from datetime import timedelta
from typing import Dict, List, Literal, Optional, Union

import discord
from discord import SlashCommandGroup
from discord.commands import Option
from discord.ext import commands, pages

from src import utils
from src.bot.client import Bot
from src.database import SimplePoll
from src.utils.views import SimplePollView
from src.vendor.humanize.size import naturalsize

logger = logging.getLogger(__name__)


async def purge(channel: discord.TextChannel, limit: int = 1000, **kwargs) -> Optional[List[discord.Message]]:
    async def run_purge():
        return await channel.purge(
            limit=limit,
            **kwargs
        )

    try:
        return await asyncio.wait_for(
            run_purge(),
            300  # running a purge for more than 5 minutes is a bit OTT
        )
    except asyncio.TimeoutError:
        return


async def purge_permission_check(ctx: discord.ApplicationContext) -> bool:
    if not ctx.guild:
        await ctx.respond("Purge cannot be used in direct messages.")
        return False

    if not ctx.channel.permissions_for(ctx.user).manage_messages:
        await ctx.respond("You do not have permission to delete messages in this channel.", ephemeral=True)
        return False

    bot_perms = discord.Permissions(
        read_messages=True,
        read_message_history=True,
        manage_messages=True
    )
    if not ctx.channel.permissions_for(ctx.me).is_superset(bot_perms):
        await ctx.respond(
            "I am missing permissions to purge in this channel. Please check that I have:\n"
            "\N{BULLET} Read messages\n"
            "\N{BULLET} Read message history\n"
            "\N{BULLET} Manage messages",
            ephemeral=True
        )
        return False

    return True


class Utility(commands.Cog):
    def __init__(self, bot: Bot):
        self.bot: Bot = bot
        self.deleted_snipes: Dict[discord.TextChannel, deque] = {}
        self.edited_snipes: Dict[discord.TextChannel, deque] = {}

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages: List[discord.Message]):
        logger.debug("Got bulk message delete event with %s messages.", len(messages))
        for message in messages:
            logger.debug("Processing message delete for message %s-%s", message.channel.id, message.id)
            await self.on_message_delete(message)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        message_copy = copy.copy(message)
        if message.channel not in self.deleted_snipes:
            logger.debug("Creating new delete-snipe queue for channel %r.", message.channel.id)
            self.deleted_snipes[message.channel] = deque([message_copy], maxlen=1000)
        else:
            self.deleted_snipes[message.channel].append(message_copy)
            logger.debug(
                "Channel %r already has a delete-deque, of size %s.",
                message.channel.id,
                len(self.deleted_snipes[message.channel]),
            )

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.author == self.bot.user:
            return
        if before.channel not in self.edited_snipes:
            logger.debug("Creating new edit-snipe queue for channel %r.", after.channel.id)
            self.edited_snipes[before.channel] = deque([[before, after]], maxlen=1000)
        else:
            self.edited_snipes[before.channel].append([before, after])
            logger.debug(
                "Channel %r already has an edit-deque, of size %s.",
                after.channel.id,
                len(self.edited_snipes[before.channel]),
            )

    # BEGIN COMMANDS

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
        await paginator.respond(ctx.interaction)

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
        await paginator.respond(ctx.interaction)

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

    purge = SlashCommandGroup(
        "purge",
        "Bulk deletes lots of messages at once."
    )

    @purge.command()
    async def limit(
        self,
        ctx: discord.ApplicationContext,
        max_search: Option(
            int,
            "How many messages to delete. Defaults to 100.",
            min_value=10,
            max_value=5000,
            default=100
        )
    ):
        """Deletes up to <max_search> messages."""
        if not await purge_permission_check(ctx):
            return

        await ctx.defer(ephemeral=True)
        messages = await purge(ctx.channel, limit=max_search)
        if messages is None:
            return await ctx.respond("Failed to purge - exceeded maximum time (5 minutes).\n"
                                     "If you need to delete LOTS of messages, discord recommends you clone the channel"
                                     " instead.", ephemeral=True)
        else:
            def get_page(message: discord.Message) -> Union[discord.Embed, List[discord.Embed]]:
                embed = discord.Embed(
                    title=f"Message from {message.author}",
                    description=message.content or "no content",
                    colour=message.author.colour,
                    timestamp=message.created_at
                )
                embed.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)

                footer_text = message.guild.name
                if message.edited_at:
                    date_format = "%a %d %b %Y %r %Z"  # default for en_US.UTF-8
                    try:
                        locale.setlocale(locale.LC_ALL, (ctx.interaction.locale.replace("-", "_"), "UTF-8"))
                        date_format = locale.nl_langinfo(locale.D_T_FMT)
                    except (locale.Error, AttributeError):  # AttributeError can be raised on Windows
                        logger.warning(f"Failed to set locale to {ctx.interaction.locale!r}.")
                    footer_text += f" \N{BULLET} Message was edited at: {message.edited_at.strftime(date_format)}"

                embed.set_footer(text=footer_text, icon_url=ctx.guild.icon.url)

                if len(list(filter(lambda e: e.type == "rich", message.embeds))) != 0:
                    return [embed, *list(filter(lambda e: e.type == "rich", message.embeds))]
                return embed

            paginator = pages.Paginator(
                [get_page(x) for x in messages]
            )
            return await paginator.respond(ctx.interaction, ephemeral=True)

    @commands.slash_command(name="simple-poll")
    async def simple_poll(
            self,
            ctx: discord.ApplicationContext,
            question: str,
            duration: discord.Option(
                str,
                default="1 day"
            ),
            post_in: discord.Option(
                discord.TextChannel,
                default=None
            )
    ):
        """Creates a simple yes or no poll."""
        post_in = post_in or ctx.channel
        post_in: discord.TextChannel
        if not post_in.can_send(discord.Embed()):
            return await ctx.interaction.response.send_message(f"I cannot send a message in {post_in.mention}.",
                                                               ephemeral=True)
        try:
            seconds = utils.parse_time(duration)
            if seconds > 2635200:
                return await ctx.respond("Poll duration must be less than a month.", ephemeral=True)
            elif seconds < 0:
                return await ctx.respond("How did you get *negative* poll time?", ephemeral=True)
            poll_closes = discord.utils.utcnow() + timedelta(seconds=seconds)
        except ValueError:
            return await ctx.respond("Invalid time format. Try passing something like '30 seconds'.", ephemeral=True)

        embed = discord.Embed(
            title=question[:2048],
            description=f"Poll closes {discord.utils.format_dt(poll_closes, 'R')}.",
        )
        embed.set_author(name="%s asks..." % ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
        entry = await SimplePoll.objects.create(
            ends_at=poll_closes,
            owner=ctx.author.id
        )
        view = SimplePollView(entry.id)
        message = await ctx.send(embed=embed, view=view)
        await entry.update(message=message.id)
        self.bot.add_view(view, message_id=message.id)
        await ctx.respond(f"[Poll created.]({message.jump_url})", ephemeral=True)

    # @commands.slash_command()
    # async def poll(
    #         self,
    #         ctx: discord.ApplicationContext,
    #         question: str,
    #         poll_duration: discord.Option(
    #             str,
    #             description="How long the poll should last. Defaults to 1 day.",
    #         )
    # ):
    #     """Creates a poll"""
    #     options = []
    #     selector = utils.views.CreatePollView()
    #
    #     def embed():
    #         return discord.Embed(
    #             title="Current options",
    #             description="\n".join(options),
    #             colour=discord.Colour.purple()
    #         )
    #
    #     message = await ctx.respond(
    #         "Please enter the options for the poll.",
    #         view=selector,
    #         embed=embed()
    #     )
    #     while True:
    #         await message.edit(content="Please enter the options for the poll.", embed=embed(), view=selector)
    #         await selector.wait()
    #         if selector.value == "ADD_NEW":
    #             input_view = utils.views.CreateNewPollOption()
    #             await ctx.send_modal(input_view)
    #             result = await input_view.run()
    #             options.append(result)
    #         elif selector.value == "REMOVE":
    #             view = utils.views.RemovePollOptionDropDown(options)
    #             await message.edit(content="Please select some options to remove.", view=view)
    #             await view.wait()
    #             options = view.value
    #         elif selector.value == "DONE":
    #             break
    #         else:
    #             await message.delete()
    #             return
    #
    #     view = utils.views.PollView(
    #         question=question,
    #     )
    #
    #     await ctx.respond()


def setup(bot):
    bot.add_cog(Utility(bot))
