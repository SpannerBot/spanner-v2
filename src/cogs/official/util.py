import asyncio
import copy
import logging
import sys
import textwrap
from collections import deque
from typing import Dict, List, Literal

import discord
from discord import SlashCommandGroup
from discord.commands import Option, permissions
from discord.ext import commands, pages

from src.bot.client import Bot
from src.utils.views import EmbedCreatorView, AutoDisableView
from src.vendor.humanize.size import naturalsize

logger = logging.getLogger(__name__)


class Utility(commands.Cog):
    def __init__(self, bot: Bot):
        self.bot: Bot = bot
        self.deleted_snipes: Dict[discord.TextChannel, deque] = {}
        self.edited_snipes: Dict[discord.TextChannel, deque] = {}
        self.poll_expire_loop.start()

    def cog_unload(self):
        self.poll_expire_loop.cancel()

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
    @discord.guild_only()
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
    @permissions.guild_only()
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
    @commands.is_owner()
    async def snipes_info(
        self, ctx: discord.ApplicationContext, snipe_type: discord.Option(choices=["all", "deleted", "edited"])
    ):
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
        "Bulk deletes lots of messages at once.",
        default_member_permissions=discord.Permissions(
            manage_messages=True, read_messages=True, read_message_history=True
        ),
        guild_only=True,
    )

    @purge.command(name="number")
    @commands.bot_has_permissions(manage_messages=True, read_messages=True, read_message_history=True)
    async def limit(
        self,
        ctx: discord.ApplicationContext,
        max_search: Option(
            int, "How many messages to delete. Defaults to 100.", min_value=10, max_value=5000, default=100
        ),
        ignore_pinned: Option(bool, "If pinned messages should be left alone. Defaults to True.", default=True),
    ):
        """Deletes up to <max_search> messages."""

        await ctx.defer(ephemeral=True)
        messages = await ctx.channel.purge(
            limit=max_search,
            check=lambda _m: (_m.pinned is False) if ignore_pinned else True,
            reason=f"Authorised by {ctx.author}.",
        )
        authors = [x.author.id for x in messages]
        authors_count = {}
        for author in authors:
            authors_count[author] = authors_count.get(author, 0) + 1
        top_authors = list(set(authors))
        top_authors.sort(key=lambda a: authors_count[a], reverse=True)
        top_authors = top_authors[:10]
        value = f"Deleted {len(messages):,} messages.\nAuthor breakdown:\n" + "\n".join(
            f"<@{uid}>: {authors_count[uid]:,} ({round(authors_count[uid] / len(messages))}% of messages)"
            for uid in top_authors
        )
        return await ctx.respond(value, ephemeral=True)

    @commands.message_command(name="Delete after this")
    @commands.bot_has_permissions(manage_messages=True, read_messages=True, read_message_history=True)
    @commands.has_permissions(manage_messages=True, read_messages=True, read_message_history=True)
    @discord.default_permissions(manage_messages=True, read_messages=True, read_message_history=True)
    async def purge_after_message(self, ctx: discord.ApplicationContext, message: discord.Message):
        max_messages = None
        ignore_pins = True

        class MaxMessagesModal(discord.ui.Modal):
            def __init__(self):
                super().__init__(
                    discord.ui.InputText(
                        label="Maximum messages to delete:",
                        placeholder="Enter a number between 1 and 5,000.",
                        min_length=1,
                        max_length=4,
                        value="100",
                    ),
                    discord.ui.InputText(
                        label="Ignore pinned messages?",
                        placeholder="Yes or No",
                        min_length=2,
                        max_length=3,
                        value="Yes",
                    ),
                    title="Purge settings",
                )

            async def callback(self, interaction: discord.Interaction):
                nonlocal max_messages, ignore_pins
                max_messages = min(5000, max(0, int(self.children[0].value)))
                ignore_pins = self.children[1].value[0].lower() == "y"
                ctx.interaction = interaction
                self.stop()

        modal = MaxMessagesModal()
        await ctx.send_modal(modal)
        try:
            await asyncio.wait_for(modal.wait(), timeout=120)
        except asyncio.TimeoutError:
            return
        await ctx.defer()
        messages = await ctx.channel.purge(
            limit=max_messages,
            check=lambda _m: (_m.pinned is False) if ignore_pins else True,
            reason=f"Authorised by {ctx.author}.",
            after=message,
        )
        authors = [x.author.id for x in messages]
        authors_count = {}
        for author in authors:
            authors_count[author] = authors_count.get(author, 0) + 1
        top_authors = list(set(authors))
        top_authors.sort(key=lambda a: authors_count[a], reverse=True)
        top_authors = top_authors[:10]
        value = (
            f"Deleted {len(messages):,} messages after [this message]({message.jump_url}).\nAuthor breakdown:\n"
            + "\n".join(
                f"<@{uid}>: {authors_count[uid]:,} ({round(authors_count[uid] / len(messages) * 100)}% of messages)"
                for uid in top_authors
            )
        )
        return await ctx.respond(value, ephemeral=True)

    @commands.message_command(name="Delete before this")
    @commands.bot_has_permissions(manage_messages=True, read_messages=True, read_message_history=True)
    @commands.has_permissions(manage_messages=True, read_messages=True, read_message_history=True)
    @discord.default_permissions(manage_messages=True, read_messages=True, read_message_history=True)
    async def purge_before_message(self, ctx: discord.ApplicationContext, message: discord.Message):
        max_messages = None
        ignore_pins = True

        class MaxMessagesModal(discord.ui.Modal):
            def __init__(self):
                super().__init__(
                    discord.ui.InputText(
                        label="Maximum messages to delete:",
                        placeholder="Enter a number between 1 and 5,000.",
                        min_length=1,
                        max_length=4,
                        value="100",
                    ),
                    discord.ui.InputText(
                        label="Ignore pinned messages?",
                        placeholder="Yes or No",
                        min_length=2,
                        max_length=3,
                        value="Yes",
                    ),
                    title="Purge settings",
                )

            async def callback(self, interaction: discord.Interaction):
                nonlocal max_messages, ignore_pins
                max_messages = min(5000, max(0, int(self.children[0].value)))
                ignore_pins = self.children[1].value[0].lower() == "y"
                ctx.interaction = interaction
                self.stop()

        modal = MaxMessagesModal()
        await ctx.send_modal(modal)
        try:
            await asyncio.wait_for(modal.wait(), timeout=120)
        except asyncio.TimeoutError:
            return
        await ctx.defer(ephemeral=True)
        messages = await ctx.channel.purge(
            limit=max_messages,
            check=lambda _m: (_m.pinned is False) if ignore_pins else True,
            reason=f"Authorised by {ctx.author}.",
            before=message,
        )
        authors = [x.author.id for x in messages]
        authors_count = {}
        for author in authors:
            authors_count[author] = authors_count.get(author, 0) + 1
        top_authors = list(set(authors))
        top_authors.sort(key=lambda a: authors_count[a], reverse=True)
        top_authors = top_authors[:10]
        value = (
            f"Deleted {len(messages):,} messages before [this message]({message.jump_url}).\nAuthor breakdown:\n"
            + "\n".join(
                f"<@{uid}>: {authors_count[uid]:,} ({round(authors_count[uid] / len(messages) * 100)}% of messages)"
                for uid in top_authors
            )
        )
        return await ctx.respond(value, ephemeral=True)

    embed_command = discord.SlashCommandGroup("embed", description="Embed management")

    @embed_command.command(name="create")
    @commands.bot_has_permissions(embed_links=True)
    # @utils.disable_unless_owner()
    async def create_embed(
        self,
        ctx: discord.ApplicationContext,
        use_guide: discord.Option(
            bool, description="If true, will use a pre-filled embed with example values.", default=True
        ),
    ):
        """Guides you through creating an embed."""
        view = EmbedCreatorView(ctx)
        if use_guide is False:
            view.embed = discord.Embed(description="Edit this with the buttons below.")
        await ctx.respond(embed=view.embed, view=view)

    @commands.message_command(name="Edit Embed")
    @discord.default_permissions(send_messages=True, embed_links=True, manage_messages=True)
    @commands.bot_has_permissions(embed_links=True)
    async def edit_embed(self, ctx: discord.ApplicationContext, message: discord.Message):
        embeds = list(filter(lambda e: e.type == "rich", message.embeds))
        if len(embeds) == 0:
            return await ctx.respond("No embeds found.")
        if len(embeds) > 1:

            class EmbedSelector(AutoDisableView):
                class Btn(discord.ui.Button):
                    def __init__(self, n: int, is_rich: bool):
                        super().__init__(
                            label=f"Embed {n+1}",
                            disabled=not is_rich,
                            custom_id=str(n),
                            emoji="%d\U0000fe0f\U000020e3" % (n + 1),
                        )

                    async def callback(self, interaction: discord.Interaction):
                        await EmbedCreatorView.defer_invisible(interaction)
                        self.view.chosen = int(self.custom_id)
                        self.view.stop()

                def __init__(self):
                    super().__init__()
                    self.chosen = None
                    for embed in message.embeds:
                        self.add_item(self.Btn(message.embeds.index(embed), embed.type == "rich"))

            _view = EmbedSelector()
            await ctx.respond("Select an embed to edit:", view=_view)
            await _view.wait()
            if _view.chosen is not None:
                chosen_embed = message.embeds[_view.chosen]
                await ctx.delete(delay=0.2)
            else:
                return await ctx.delete(delay=0.1)
        else:
            chosen_embed = embeds[0]
        view = EmbedCreatorView(ctx, chosen_embed)
        return await ctx.respond(embed=chosen_embed, view=view)


def setup(bot):
    bot.add_cog(Utility(bot))
