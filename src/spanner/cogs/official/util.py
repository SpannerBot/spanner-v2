import asyncio
import logging

import discord
from discord import SlashCommandGroup
from discord.commands import Option
from discord.ext import commands

from bot.client import Bot
from utils.views import EmbedCreatorView, AutoDisableView

logger = logging.getLogger(__name__)


MAX_SEARCH_OPT = Option(int, "How many messages to delete. Defaults to 100.", min_value=10, max_value=5000, default=100)


class Utility(commands.Cog):
    def __init__(self, bot: Bot):
        self.bot: Bot = bot

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
        max_search: MAX_SEARCH_OPT,
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

    @purge.command(name="messages-by")
    @commands.bot_has_permissions(manage_messages=True, read_messages=True, read_message_history=True)
    async def by(
        self,
        ctx: discord.ApplicationContext,
        author: discord.User,
        max_search: MAX_SEARCH_OPT,
        ignore_pinned: Option(bool, "If pinned messages should be left alone. Defaults to True.", default=True),
    ):
        """Deletes up to <max_search> messages by <author>."""

        def check(_m: discord.Message):
            if ignore_pinned is False:
                if _m.pinned:
                    return False

            return _m.author == author

        await ctx.defer(ephemeral=True)
        messages = await ctx.channel.purge(
            limit=max_search,
            check=check,
            reason=f"Authorised by {ctx.author}.",
        )
        value = f"Deleted {len(messages):,} messages by {author.mention}."
        return await ctx.respond(value, ephemeral=True)

    @purge.command(name="messages-by-bots")
    @commands.bot_has_permissions(manage_messages=True, read_messages=True, read_message_history=True)
    async def by(
        self,
        ctx: discord.ApplicationContext,
        max_search: MAX_SEARCH_OPT,
        ignore_pinned: Option(bool, "If pinned messages should be left alone. Defaults to True.", default=True),
    ):
        """Deletes up to <max_search> messages by non-humans."""

        def check(_m: discord.Message):
            if ignore_pinned is False:
                if _m.pinned:
                    return False

            return _m.author.bot or _m.author.system

        await ctx.defer(ephemeral=True)
        messages = await ctx.channel.purge(
            limit=max_search,
            check=check,
            reason=f"Authorised by {ctx.author}.",
        )
        authors = [x.author.id for x in messages]
        authors_count = {}
        for author in authors:
            authors_count[author] = authors_count.get(author, 0) + 1
        top_authors = list(set(authors))
        top_authors.sort(key=lambda a: authors_count[a], reverse=True)
        top_authors = top_authors[:10]
        value = f"Deleted {len(messages):,} messages by bots or system.\nAuthor breakdown:\n" + "\n".join(
            f"<@{uid}>: {authors_count[uid]:,} ({round(authors_count[uid] / len(messages))}% of messages)"
            for uid in top_authors
        )
        return await ctx.respond(value, ephemeral=True)

    @purge.command(name="messages-by-humans")
    @commands.bot_has_permissions(manage_messages=True, read_messages=True, read_message_history=True)
    async def by(
        self,
        ctx: discord.ApplicationContext,
        max_search: MAX_SEARCH_OPT,
        ignore_pinned: Option(bool, "If pinned messages should be left alone. Defaults to True.", default=True),
    ):
        """Deletes up to <max_search> messages by humans."""

        def check(_m: discord.Message):
            if ignore_pinned is False:
                if _m.pinned:
                    return False

            return not any((_m.author.bot, _m.author.system))

        await ctx.defer(ephemeral=True)
        messages = await ctx.channel.purge(
            limit=max_search,
            check=check,
            reason=f"Authorised by {ctx.author}.",
        )
        authors = [x.author.id for x in messages]
        authors_count = {}
        for author in authors:
            authors_count[author] = authors_count.get(author, 0) + 1
        top_authors = list(set(authors))
        top_authors.sort(key=lambda a: authors_count[a], reverse=True)
        top_authors = top_authors[:10]
        value = f"Deleted {len(messages):,} messages by humans.\nAuthor breakdown:\n" + "\n".join(
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
