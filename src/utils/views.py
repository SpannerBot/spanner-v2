import asyncio
import datetime
import os
import textwrap
import warnings
from io import BytesIO
from typing import Dict, List, Optional, Union, Coroutine, Callable, Any, Tuple

import discord
import validators
from discord import ButtonStyle
from discord.ext import pages, commands
from discord.ui import View, Button, button
from discord.webhook.async_ import async_context

from src.database import SimplePoll

__all__ = ("YesNoPrompt", "SimplePollView", "StealEmojiView", "EmbedCreatorView")


class AutoDisableView(View):
    interaction: discord.Interaction = None
    children: List[Union[discord.ui.Select, discord.ui.Button]]

    def __init__(self, interaction: discord.Interaction = None, *args, **kwargs):
        super().__init__(**kwargs)
        self.interaction = interaction

    async def on_timeout(self) -> None:
        if not hasattr(self, "ctx"):
            warnings.warn(FutureWarning("{0.__class__.__name__!r} does not have a context attribute.".format(self)))
        self.disable_all_items()
        try:
            if self.interaction is not None:
                try:
                    message = self.interaction.message or await self.interaction.original_message()
                except discord.HTTPException:
                    pass
                else:
                    await message.edit(view=self)
        finally:
            self.stop()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not hasattr(self, "ctx"):
            warnings.warn(FutureWarning("{0.__class__.__name__!r} does not have a context attribute.".format(self)))

        if hasattr(self, "ctx"):
            self.ctx: discord.ApplicationContext
            return self.ctx.author == interaction.user
        elif self.interaction is not None:
            return self.interaction.user == interaction.user
        return True

    async def on_error(self, error: Exception, item: discord.ui.Item, interaction: discord.Interaction) -> None:
        if not hasattr(self, "ctx"):
            warnings.warn(FutureWarning("{0.__class__.__name__!r} does not have a context attribute.".format(self)))
        await interaction.followup.send("Error: {!s}\nIn: {!s}".format(error, item))
        await super().on_error(error, item, interaction)


class TenMinuteTimeoutModal(discord.ui.Modal):
    def __init__(self, *children, title: str, custom_id: str = None, timeout: float = 600.0):
        super().__init__(*children, title=title, custom_id=custom_id, timeout=timeout)


class YesNoPrompt(AutoDisableView):
    confirm: bool = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @button(label="Yes", style=ButtonStyle.green)
    async def confirm_yes(self, *_):
        self.confirm = True
        self.stop()

    @button(label="No", style=ButtonStyle.red)
    async def confirm_no(self, *_):
        self.stop()


class SimplePollViewSeeResultsViewVotersView(AutoDisableView):
    # what the fuck
    def __init__(self, voters: Dict[str, bool], *args):
        super().__init__(*args)
        self.voters = voters

    @button(label="View voters", style=ButtonStyle.green)
    async def view_voters(self, _, interaction: discord.Interaction):
        if interaction.guild is None:
            return
        if interaction.user.guild_permissions.administrator:
            voted_yes: List[int] = [int(x) for x, y in self.voters.items() if y]
            voted_no: List[int] = [int(x) for x, y in self.voters.items() if not y]
            await interaction.response.defer(ephemeral=True)
            await interaction.guild.query_members(
                user_ids=voted_yes + voted_no,
            )  # this caches them
            voted_yes: List[Optional[discord.Member]] = list(map(lambda x: interaction.guild.get_member(x), voted_yes))
            voted_no: List[Optional[discord.Member]] = list(map(lambda x: interaction.guild.get_member(x), voted_no))
            voted_yes: List[discord.Member] = list(filter(lambda x: x is not None, voted_yes))
            voted_no: List[discord.Member] = list(filter(lambda x: x is not None, voted_no))

            def generate_group(group: List[discord.Member], vote_type: str) -> List[discord.Embed]:
                boring_paginator = commands.Paginator(prefix="", suffix="", max_size=4069)
                for member in group:
                    boring_paginator.add_line(member.mention)

                embeds = []
                for page in boring_paginator.pages:
                    embeds.append(discord.Embed(title="Members who voted %s:" % vote_type, description=page))
                return embeds

            fancy_pages = []
            if voted_yes:
                fancy_pages.extend(generate_group(voted_yes, "yes"))
            if voted_no:
                fancy_pages.extend(generate_group(voted_no, "no"))
            paginator = pages.Paginator(fancy_pages, timeout=300, disable_on_timeout=True)
            await interaction.response.defer(invisible=True)  # prevents paginator from fucking up original message
            await paginator.respond(interaction, True)
            self.stop()
        else:
            await interaction.response.send_message("Only administrators can view voters.", ephemeral=True)


class SimplePollView(AutoDisableView):
    def __init__(self, poll_id: int, *args):
        super().__init__(*args, timeout=None)
        self.poll_id = poll_id
        self.db = None

    async def get_db(self):
        if self.db:
            return self.db
        self.db = await SimplePoll.objects.get(id=self.poll_id)
        return self.db

    @button(custom_id="yes", emoji="\N{white heavy check mark}")
    async def confirm(self, _, interaction: discord.Interaction):
        db = await self.get_db()
        ends_at = datetime.datetime.fromtimestamp(float(db.ends_at))
        ends_at.replace(tzinfo=datetime.timezone.utc)
        if datetime.datetime.utcnow() >= ends_at:
            for child in self.children:
                if isinstance(child, Button):
                    if child.label in ("See results", "Delete poll"):
                        continue
                    child.disabled = True
            src_message = await interaction.channel.fetch_message(db.message)
            await src_message.edit(view=self)
            return await interaction.response.send_message(
                f"This poll ended {discord.utils.format_dt(ends_at, 'R')}" f"\nPress 'See results' to see the results.",
                ephemeral=True,
            )
        if str(interaction.user.id) in db.voted.keys():
            return await interaction.response.send_message("You already voted!", ephemeral=True)
        else:
            db.voted[str(interaction.user.id)] = True
            await db.update(voted=db.voted)
            await interaction.response.send_message("You voted \N{WHITE HEAVY CHECK MARK}!", ephemeral=True)

    @button(custom_id="no", emoji="\N{cross mark}")
    async def deny(self, _, interaction: discord.Interaction):
        db = await self.get_db()
        ends_at = datetime.datetime.fromtimestamp(float(db.ends_at))
        ends_at.replace(tzinfo=datetime.timezone.utc)
        if datetime.datetime.utcnow() >= ends_at:
            for child in self.children:
                if isinstance(child, Button):
                    if child.label in ("See results", "Delete poll"):
                        continue
                    child.disabled = True
            src_message = await interaction.channel.fetch_message(db.message)
            await src_message.edit(view=self)
            return await interaction.response.send_message(
                f"This poll ended {discord.utils.format_dt(ends_at, 'R')}\nPress 'See results' to see the results.",
                ephemeral=True,
            )
        if str(interaction.user.id) in db.voted.keys():
            return await interaction.response.send_message("You already voted!", ephemeral=True)
        else:
            db.voted[str(interaction.user.id)] = False
            await db.update(voted=db.voted)
            await interaction.response.send_message("You voted \N{cross mark}!", ephemeral=True)

    @button(custom_id="view", label="See results", emoji="\N{eyes}", row=2)
    async def view_results(self, _, interaction: discord.Interaction):
        db = await self.get_db()
        total_yes = len([x for x in db.voted.values() if x])
        total_no = len([x for x in db.voted.values() if not x])
        total = len(db.voted.keys())

        def percent(part: int, whole: int) -> float:
            return round((part / whole) * 100, 1)

        if total_yes > total_no:
            colour = discord.Colour.green()
        elif total_yes < total_no:
            colour = discord.Colour.red()
        else:
            colour = discord.Colour.blue()

        ends_at = datetime.datetime.fromtimestamp(float(db.ends_at))
        ends_at.replace(tzinfo=datetime.timezone.utc)
        # viewable = sum(1 for x in interaction.message.channel.members if x.bot is False)

        embed = discord.Embed(
            title=f"Poll results:",
            description=f"Yes (\N{WHITE HEAVY CHECK MARK}): {total_yes:,} ({percent(total_yes, total)}%)\n"
            f"No (\N{cross mark}): {total_no:,} ({percent(total_no, total)}%)\n"
            f"Total votes: {total:,}\n"
            # f"({percent(total, viewable)}% of members who can vote)\n"
            f"Poll ends/ended {discord.utils.format_dt(ends_at, 'R')}.",
            colour=colour,
        )

        if interaction.user.id == db.owner or datetime.datetime.utcnow() >= ends_at:
            _view = SimplePollViewSeeResultsViewVotersView(self.db.voted, interaction)
            if not interaction.user.guild_permissions.administrator:
                _view = None
            return await interaction.response.send_message(embed=embed, ephemeral=True, view=_view)
        else:
            return await interaction.response.send_message("You cannot view results yet!", ephemeral=True)

    @button(custom_id="delete", label="Delete poll", style=ButtonStyle.red, emoji="\N{wastebasket}\U0000fe0f", row=2)
    async def delete(self, _, interaction: discord.Interaction):
        db = await self.get_db()
        if interaction.user.id != db.owner:
            return await interaction.response.send_message("You can't delete this poll!", ephemeral=True)
        else:
            message = await interaction.channel.fetch_message(db.message)
            await message.delete()
            await db.delete()
            self.stop()


class StealEmojiView(AutoDisableView):
    def __init__(self, *args, emoji: Union[discord.Emoji, discord.PartialEmoji]):
        super().__init__(*args, timeout=300)
        self.emoji = emoji

    @button(label="Steal", style=ButtonStyle.green, emoji="\U00002b07\U0000fe0f")
    async def steal_emoji(self, btn: discord.Button, interaction: discord.Interaction):
        if not interaction.user.guild:
            btn.disabled = True
            await interaction.message.edit(view=self)
            await interaction.response.send_message("You should not be able to see this button in DMs?")
            self.stop()
            return

        ephemeral = not interaction.channel.permissions_for(interaction.user).send_messages

        if not interaction.user.guild_permissions.manage_emojis:
            return await interaction.response.send_message(
                "You need to have manage emojis permission to steal emojis.", ephemeral=ephemeral
            )
        if not interaction.user.guild.me.guild_permissions.manage_emojis:
            return await interaction.response.send_message(
                "I need to have manage emojis permission to steal emojis.", ephemeral=ephemeral
            )
        if len(interaction.guild.emojis) >= interaction.guild.emoji_limit:
            return await interaction.response.send_message(
                "You can't have more than {:,} emojis in this server.".format(interaction.guild.emoji_limit),
                ephemeral=ephemeral,
            )

        await interaction.response.defer(ephemeral=ephemeral)

        # Create a buffer and save the emoji to it
        buffer = BytesIO()
        await self.emoji.save(buffer)  # save emoji to buffer
        buffer.seek(0)  # reset buffer to read from it again
        # create the emoji in the server with the same info
        try:
            new_emoji = await interaction.guild.create_custom_emoji(
                name=self.emoji.name,
                image=buffer.read(),
                reason="Stolen by {!s} from {!s}.".format(
                    interaction.user,
                    "%r" % interaction.guild.name if interaction.guild else "an unknown server",
                ),
            )
        except discord.HTTPException as e:
            return await interaction.response.send_message(
                "Something went wrong while creating the emoji.\n" + str(e), ephemeral=ephemeral
            )
        else:
            btn.disabled = True
            await interaction.message.edit(view=self)
            await interaction.followup.send(f"Emoji stolen! `{new_emoji!s}`", ephemeral=ephemeral)
            self.stop()


class EmbedCreatorView(AutoDisableView):
    EXAMPLE_EMBED = discord.Embed(
        title="Example title",
        description="Example description",
        colour=discord.Colour(0xFFFFFE),
        timestamp=discord.utils.utcnow(),
        url="https://dev.nexy7574.cyou",
        fields=[discord.EmbedField(name="Example field name", value="Example field description")],
    )
    EXAMPLE_EMBED.set_author(
        name="Example Author Name",
        icon_url="https://cdn.discordapp.com/attachments/729375722858086400/990664167977521243/unknown.png",
    )
    EXAMPLE_EMBED.set_footer(
        text="Example Footer Text",
        icon_url="https://cdn.discordapp.com/attachments/729375722858086400/990664167977521243/unknown.png",
    )
    EXAMPLE_EMBED.set_image(
        url="https://cdn.discordapp.com/attachments/729375722858086400/990664167977521243/unknown.png"
    )
    EXAMPLE_EMBED.set_thumbnail(
        url="https://cdn.discordapp.com/attachments/729375722858086400/990664167977521243/unknown.png"
    )

    def __init__(self, ctx: discord.ApplicationContext, existing_embed: discord.Embed = None):
        self.ctx = ctx
        self.embed = existing_embed or self.EXAMPLE_EMBED.copy()
        super().__init__(ctx.interaction, timeout=600)

    @staticmethod
    async def defer_invisible(interaction: discord.Interaction):
        # We need to defer invisibly, but until 2.0.0rc2 or whatever is released with invisible responses,
        # we'll need to do it manually
        context = async_context.get()
        await interaction.response._locked_response(
            context.create_interaction_response(
                interaction.id,
                interaction.token,
                session=interaction._session,
                type=discord.InteractionResponseType.deferred_message_update.value,
                data=None,
            )
        )
        interaction.response._responded = True

    @staticmethod
    def simple_modal_callback(item: Union[discord.ui.Button, discord.ui.Select, discord.ui.Modal]):
        async def inner(interaction: discord.Interaction):
            await EmbedCreatorView.defer_invisible(interaction)
            item.stop()

        return inner

    async def edit(
        self,
        content: str = discord.utils.MISSING,
        embed: discord.Embed = discord.utils.MISSING,
        update_view: bool = False,
        interaction: discord.Interaction = None,
    ):
        if content:
            content = os.urandom(3).hex() + " | " + content

        interaction = interaction or self.ctx.interaction
        if update_view:
            coro = interaction.edit_original_message(content=content, embed=embed, view=self)
        else:
            coro = interaction.edit_original_message(content=content, embed=embed)
        await coro

    @staticmethod
    async def send_modal(interaction: discord.Interaction, modal: discord.ui.Modal, timeout: float = 300) -> bool:
        await interaction.response.send_modal(modal)
        try:
            await asyncio.wait_for(modal.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    @button(label="Change title")
    async def modify_title(self, _, interaction: discord.Interaction):
        new_title = None

        async def callback(_interaction: discord.Interaction):
            nonlocal new_title
            await self.defer_invisible(_interaction)
            new_title = modal.children[0].value or discord.Embed.Empty
            modal.stop()

        modal = TenMinuteTimeoutModal(
            discord.ui.InputText(
                label="Title:",
                placeholder="Empty for no title",
                max_length=256,
                required=False,
                value=self.embed.title or None,
            ),
            title="Modify Embed",
        )
        modal.callback = callback
        if not await self.send_modal(interaction, modal):
            await self.edit("Title not modified (timed out waiting for modal submission)")
        else:
            self.embed.title = new_title
            await self.edit("Title successfully modified.", self.embed)

    @button(label="Modify description")
    async def modify_description(self, _, interaction: discord.Interaction):
        new_description = None

        async def callback(_interaction: discord.Interaction):
            nonlocal new_description
            await self.defer_invisible(_interaction)
            new_description = modal.children[0].value or discord.Embed.Empty
            modal.stop()

        modal = TenMinuteTimeoutModal(
            discord.ui.InputText(
                style=discord.InputTextStyle.long,
                label="Description:",
                placeholder="Empty for no description",
                min_length=1,
                max_length=4000,
                required=True,
                value=self.embed.description or None,
            ),
            title="Modify Embed",
        )
        modal.callback = callback
        if not await self.send_modal(interaction, modal):
            await self.edit("Description not modified (timed out waiting for modal submission)")
        else:
            self.embed.description = new_description
            await self.edit("Description successfully modified.", self.embed)

    @button(label="Change Sidebar Colour")
    async def modify_sidebar_colour(self, _, interaction: discord.Interaction):
        view = EmbedCreatorColourPickerView(self)
        view.ctx = self.ctx
        new_interaction: discord.Interaction = await interaction.response.send_message(
            "Each colour represents a colour in the discord role colour picker.", view=view
        )
        await view.wait()
        self.embed.colour = view.chosen or discord.Colour.default()
        await new_interaction.delete_original_message(delay=0.1)
        await self.edit(embed=self.embed)

    @button(label="Change url")
    async def change_url(self, _, interaction: discord.Interaction):
        modal = TenMinuteTimeoutModal(
            discord.ui.InputText(label="url", required=False, value=self.embed.author.url or None),
            title="Change url",
        )
        modal.callback = self.simple_modal_callback(modal)
        if not await self.send_modal(interaction, modal):
            await self.edit(content="url was not changed (timed out)")
        else:
            value = modal.children[0].value
            if value:
                try:
                    raise validators.url(value)
                except validators.ValidationFailure:
                    return await self.edit("URL was invalid.")
                except TypeError:
                    modal.children[0].value = value
            self.embed.url = modal.children[0].value
            if modal.children[0].value:
                await self.edit(content="Changed url.", embed=self.embed)
            else:
                await self.edit(content="Removed url.", embed=self.embed)

    @button(label="Set thumbnail (small image)")
    async def modify_thumbnail_url(self, _, interaction: discord.Interaction):
        modal = TenMinuteTimeoutModal(
            discord.ui.InputText(
                label="Image URL (blank for none):",
                placeholder="Must be one of: PNG, JP(E)G, WEBP, GIF",
                required=False,
                value=self.embed.thumbnail.url or None,
            ),
            title="Change thumbnail URL",
        )
        modal.callback = self.simple_modal_callback(modal)
        if not await self.send_modal(interaction, modal):
            await self.edit(content="Thumbnail was not changed (timed out)")
        else:
            value = modal.children[0].value
            if value:
                try:
                    raise validators.url(value)
                except validators.ValidationFailure:
                    return await self.edit("URL was invalid.")
                except TypeError:
                    modal.children[0].value = value
            self.embed.set_thumbnail(url=modal.children[0].value or discord.Embed.Empty)
            if modal.children[0].value:
                await self.edit(content="Changed thumbnail.", embed=self.embed)
            else:
                await self.edit(content="Removed thumbnail.", embed=self.embed)

    @button(label="Set image (large image)")
    async def modify_image_url(self, _, interaction: discord.Interaction):
        modal = TenMinuteTimeoutModal(
            discord.ui.InputText(
                label="Image URL (blank for none):",
                placeholder="Must be one of: PNG, JP(E)G, WEBP, GIF",
                required=False,
                value=self.embed.image.url or None,
            ),
            title="Change big image URL",
        )
        modal.callback = self.simple_modal_callback(modal)
        if not await self.send_modal(interaction, modal):
            await self.edit(content="Image was not changed (timed out)")
        else:
            value = modal.children[0].value
            if value:
                try:
                    raise validators.url(value)
                except validators.ValidationFailure:
                    return await self.edit("URL was invalid.")
                except TypeError:
                    modal.children[0].value = value
            self.embed.set_image(url=modal.children[0].value or discord.Embed.Empty)
            if modal.children[0].value:
                await self.edit(content="Changed image.", embed=self.embed)
            else:
                await self.edit(content="Removed image.", embed=self.embed)

    @button(label="Modify author details")
    async def modify_author(self, _, interaction: discord.Interaction):
        view = EmbedCreatorAuthorEditor(self)
        view.ctx = self.ctx
        new_interaction: discord.Interaction = await interaction.response.send_message(
            "The 'author' segment is the small text above the title.", view=view
        )
        await view.wait()
        await new_interaction.delete_original_message(delay=0.1)
        await self.edit(embed=self.embed)

    @button(label="Modify footer details")
    async def modify_footer(self, _, interaction: discord.Interaction):
        view = EmbedCreatorFooterEditor(self)
        view.ctx = self.ctx
        new_interaction: discord.Interaction = await interaction.response.send_message(
            "The 'footer' segment is the small text at the very bottom of the embed.", view=view
        )
        await view.wait()
        await new_interaction.delete_original_message(delay=0.1)
        await self.edit(embed=self.embed)

    @button(label="Manage fields")
    async def modify_fields(self, _, interaction: discord.Interaction):
        view = EmbedCreatorFieldManager(self)
        view.ctx = self.ctx
        self.disable_all_items()
        await self.edit(update_view=True)
        new_interaction: discord.Interaction = await interaction.response.send_message(view=view)
        await view.wait()
        await new_interaction.delete_original_message(delay=0.1)
        self.enable_all_items()
        await self.edit(embed=self.embed, update_view=True)

    @button(label="Send to", style=discord.ButtonStyle.green, emoji="\U00002b06", row=3)
    async def send_to(self, _, interaction: discord.Interaction):
        self.disable_all_items()
        await self.edit(update_view=True)
        view = EmbedCreatorSendToSelector(self)
        new_interaction: discord.Interaction = await interaction.response.send_message(
            "Where would you like to send this embed?", view=view
        )
        await view.wait()
        msg = await view.choice.send(f"Sent by {interaction.user.mention}.", embed=self.embed)
        await new_interaction.delete_original_message(delay=0.1)
        self.enable_all_items()
        await self.edit("[message sent](%s)" % msg.jump_url, update_view=True)

    @button(label="Destroy", style=discord.ButtonStyle.danger, emoji="\U0001f5d1", row=3)
    async def destroy_us(self, _, interaction: discord.Interaction):
        await self.defer_invisible(interaction)
        await interaction.delete_original_message(delay=0.01)
        self.stop()


class EmbedCreatorColourPickerView(AutoDisableView):
    def __init__(self, parent: EmbedCreatorView):
        self.parent = parent
        self.ctx = parent.ctx
        self.chosen: discord.Colour = parent.embed.colour
        super().__init__()
        _RAINBOW = ["red", "orange", "yellow", "green", "blue", "purple", "magenta", "grey"]
        _METHODS = ["to_rgb", "from_rgb", "from_hsv", "default", "random", "r", "g", "b", "embed_background"]
        colour_names = []
        for attr in dir(discord.Colour(0xFFFFFF)):
            if attr.startswith(("_", "brand", "dark")) or attr in _METHODS or "gray" in attr or "nitro" in attr:
                continue
            cls = getattr(discord.Colour, attr)
            if not callable(cls):
                continue
            colour_names.append(attr)

        # def sort_colours(n):
        #     for rn in _RAINBOW:
        #         if rn in n:
        #             return _RAINBOW.index(rn)
        #     return -1

        colour_names.sort(key=lambda c: getattr(discord.Colour, c)().value, reverse=True)

        def get_callback(
            _button: discord.ui.Button, clr: discord.Colour
        ) -> Callable[[discord.Interaction], Coroutine[Any, Any, None]]:
            async def callback(interaction: discord.Interaction):
                await EmbedCreatorView.defer_invisible(interaction)
                _button.view.chosen = clr
                await self.parent.edit(f"Set colour to {clr}.")
                _button.view.stop()

            return callback

        for name in colour_names:
            btn = discord.ui.Button(
                label=name.replace("_", " ").title(),
            )
            btn.callback = get_callback(btn, getattr(discord.Colour, name)())
            try:
                self.add_item(btn)
            except ValueError:
                break

    @button(label="Custom (Hex)", emoji="\N{PENCIL}", style=discord.ButtonStyle.primary)
    async def custom_hex(self, _, interaction: discord.Interaction):
        modal = TenMinuteTimeoutModal(
            discord.ui.InputText(
                label="Colour (#hex):",
                placeholder=str(self.chosen) if self.chosen else "#FFFFFF",
                max_length=7,
                required=False,
                value=str(self.chosen) if self.chosen else "#FFFFFE",
            ),
            title="Set your colour",
        )
        modal.callback = EmbedCreatorView.simple_modal_callback(modal)
        if not await EmbedCreatorView.send_modal(interaction, modal, 120):
            await self.parent.edit(content="Colour not updated (timed out)")
            self.stop()
        else:
            new = modal.children[0].value
            if new:
                try:
                    if new[0] != "#":
                        new = "#" + new
                    # noinspection PyTypeChecker
                    colour = await commands.ColourConverter().convert(None, new)
                except commands.BadColourArgument:
                    await self.parent.edit(content=f"Colour failed to convert.")
                else:
                    await self.parent.edit(content=f"Set colour to {colour}.")
                    self.chosen = colour
                    self.stop()


class EmbedCreatorAuthorEditor(AutoDisableView):
    def __init__(self, parent: EmbedCreatorView):
        self.ctx = parent.ctx
        self.parent = parent
        super().__init__()

    @button(label="Change text")
    async def change_text(self, _, interaction: discord.Interaction):
        modal = TenMinuteTimeoutModal(
            discord.ui.InputText(
                label="Author text", required=False, max_length=256, value=self.parent.embed.author.name or None
            ),
            title="Change author text",
        )
        modal.callback = self.parent.simple_modal_callback(modal)
        if not await self.parent.send_modal(interaction, modal):
            await self.parent.edit(content="Author text was not changed (timed out)")
        else:
            if not modal.children[0].value:
                self.parent.embed.remove_author()
                await self.parent.edit(content="Removed author text.", embed=self.parent.embed)
            else:
                self.parent.embed.set_author(
                    name=modal.children[0].value,
                    url=self.parent.embed.author.url,
                    icon_url=self.parent.embed.author.icon_url,
                )
                await self.parent.edit(content="Changed author text.", embed=self.parent.embed)
        self.stop()

    @button(label="Change url")
    async def change_url(self, _, interaction: discord.Interaction):
        modal = TenMinuteTimeoutModal(
            discord.ui.InputText(label="Author url", required=False, value=self.parent.embed.author.url or None),
            title="Change author url",
        )
        modal.callback = self.parent.simple_modal_callback(modal)
        if not await self.parent.send_modal(interaction, modal):
            await self.parent.edit(content="Author url was not changed (timed out)")
        else:
            value = modal.children[0].value
            if value:
                try:
                    raise validators.url(value)
                except validators.ValidationFailure:
                    return await self.parent.edit("URL was invalid.")
                except TypeError:
                    modal.children[0].value = value
            self.parent.embed.set_author(
                name=self.parent.embed.author.name,
                url=modal.children[0].value or discord.Embed.Empty,
                icon_url=self.parent.embed.author.icon_url,
            )
            if modal.children[0].value:
                await self.parent.edit(content="Changed author url.", embed=self.parent.embed)
            else:
                await self.parent.edit(content="Removed author url.", embed=self.parent.embed)
        self.stop()

    @button(label="Change icon url")
    async def change_icon_url(self, _, interaction: discord.Interaction):
        modal = TenMinuteTimeoutModal(
            discord.ui.InputText(
                label="Author icon url", required=False, value=self.parent.embed.author.icon_url or None
            ),
            title="Change author icon url",
        )
        modal.callback = self.parent.simple_modal_callback(modal)
        if not await self.parent.send_modal(interaction, modal):
            await self.parent.edit(content="Author url was not changed (timed out)")
        else:
            value = modal.children[0].value
            if value:
                try:
                    raise validators.url(value)
                except validators.ValidationFailure:
                    return await self.parent.edit("URL was invalid.")
                except TypeError:
                    modal.children[0].value = value
            self.parent.embed.set_author(
                name=self.parent.embed.author.name,
                url=self.parent.embed.author.url,
                icon_url=modal.children[0].value or discord.Embed.Empty,
            )
            if modal.children[0].value:
                await self.parent.edit(content="Changed author icon url.", embed=self.parent.embed)
            else:
                await self.parent.edit(content="Removed author icon url.", embed=self.parent.embed)
        self.stop()


class EmbedCreatorFooterEditor(AutoDisableView):
    def __init__(self, parent: EmbedCreatorView):
        self.ctx = parent.ctx
        self.parent = parent
        super().__init__()

    @button(label="Change text")
    async def change_text(self, _, interaction: discord.Interaction):
        modal = TenMinuteTimeoutModal(
            discord.ui.InputText(
                label="Footer text", required=False, max_length=2048, value=self.parent.embed.footer.text or None
            ),
            title="Change footer text",
        )
        modal.callback = self.parent.simple_modal_callback(modal)
        if not await self.parent.send_modal(interaction, modal):
            await self.parent.edit(content="footer text was not changed (timed out)")
        else:
            if not modal.children[0].value:
                self.parent.embed.remove_footer()
                await self.parent.edit(content="Removed footer text.", embed=self.parent.embed)
            else:
                self.parent.embed.set_footer(
                    text=modal.children[0].value or discord.Embed.Empty, icon_url=self.parent.embed.footer.icon_url
                )
                await self.parent.edit(content="Changed footer text.", embed=self.parent.embed)
        self.stop()

    @button(label="Change icon url")
    async def change_icon_url(self, _, interaction: discord.Interaction):
        modal = TenMinuteTimeoutModal(
            discord.ui.InputText(
                label="footer icon url", required=False, value=self.parent.embed.footer.icon_url or None
            ),
            title="Change footer icon url",
        )
        modal.callback = self.parent.simple_modal_callback(modal)
        if not await self.parent.send_modal(interaction, modal):
            await self.parent.edit(content="footer url was not changed (timed out)")
        else:
            value = modal.children[0].value
            if value:
                try:
                    raise validators.url(value)
                except validators.ValidationFailure:
                    return await self.parent.edit("URL was invalid.")
                except TypeError:
                    modal.children[0].value = value
            self.parent.embed.set_footer(
                text=self.parent.embed.footer.text, icon_url=modal.children[0].value or discord.Embed.Empty
            )
            if modal.children[0].value:
                await self.parent.edit(content="Changed footer icon url.", embed=self.parent.embed)
            else:
                await self.parent.edit(content="Removed footer icon url.", embed=self.parent.embed)
        self.stop()


class EmbedCreatorFieldManager(AutoDisableView):
    children: List[discord.ui.Button]

    def __init__(self, parent: EmbedCreatorView):
        self.parent = parent
        super().__init__()

    def control(self):
        if len(self.parent.embed.fields) == 0:
            self.disable_all_items(exclusions=[self.children[0]])
        else:
            self.enable_all_items()

        if len(self.parent.embed.fields) == 25:
            self.children[0].disabled = True
        else:
            self.children[0].disabled = False

    @button(label="Add Field", style=discord.ButtonStyle.green)
    async def add_field(self, _, interaction: discord.Interaction):
        remaining = len(self.parent.embed)
        if remaining < 2:
            return await interaction.followup.send("Embed is full.")
        modal = TenMinuteTimeoutModal(
            discord.ui.InputText(
                custom_id="name", label="Field title:", placeholder="Required", min_length=1, max_length=256
            ),
            discord.ui.InputText(
                custom_id="value",
                label="Content:",
                placeholder="Required",
                min_length=1,
                max_length=1024,
                style=discord.InputTextStyle.long,
            ),
            discord.ui.InputText(
                custom_id="inline",
                label="inline?",
                placeholder="y for yes, n for no",
                max_length=1,
                min_length=1,
                value="y",
            ),
            title="Create new field",
        )
        modal.callback = EmbedCreatorView.simple_modal_callback(modal)
        if not await EmbedCreatorView.send_modal(interaction, modal):
            await self.parent.edit(content="Field was not added (timed out)")
        else:
            inline = modal.children[-1].value[0].lower() == "y"
            size = len(modal.children[0].value) + len(modal.children[1].value)
            if size > remaining:
                await self.parent.edit(
                    content=f"Field was not added (not enough space - only {remaining} characters"
                    f" remaining, field was {size:,} characters)"
                )
            else:
                new_field_hash = hash(modal.children[0].value) + hash(modal.children[1].value)
                current_fields = [hash(x.name) + hash(x.value) for x in self.parent.embed.fields]
                if new_field_hash in current_fields:
                    await self.parent.edit("Field already exists.")
                else:
                    self.parent.embed.add_field(
                        name=modal.children[0].value, value=modal.children[1].value, inline=inline
                    )
                    await self.parent.edit(
                        content=f"Added field #{len(self.parent.embed.fields)}.", embed=self.parent.embed
                    )

    @button(label="Edit Field", style=discord.ButtonStyle.green)
    async def edit_field(self, _, interaction: discord.Interaction):
        view = EmbedCreatorFieldManagerFieldEditor(self.parent)
        view.ctx = self.parent.ctx
        new_interaction: discord.Interaction = await interaction.response.send_message(
            "Select a field to edit", view=view
        )
        await view.wait()
        await new_interaction.delete_original_message(delay=0.1)
        await self.parent.edit(embed=self.parent.embed)

    @button(label="Remove Field", style=discord.ButtonStyle.green)
    async def remove_field(self, _, interaction: discord.Interaction):
        view = EmbedCreatorFieldManagerFieldRemover(self.parent)
        view.ctx = self.parent.ctx
        new_interaction: discord.Interaction = await interaction.response.send_message(
            "Select a fields to remove", view=view
        )
        await view.wait()
        await new_interaction.delete_original_message(delay=0.1)
        await self.parent.edit(embed=self.parent.embed)

    @button(label="Done", style=discord.ButtonStyle.primary)
    async def finished(self, _, interaction):
        await EmbedCreatorView.defer_invisible(interaction)
        self.stop()


class EmbedCreatorSendToSelector(AutoDisableView):
    def __init__(self, parent: EmbedCreatorView):
        self.ctx = parent.ctx
        self.parent = parent
        self.choice: discord.TextChannel = self.ctx.channel
        super().__init__()
        for selector in self.create_selector(self.ctx)[:4]:
            self.add_item(selector)

    @staticmethod
    def create_selector(ctx: discord.ApplicationContext) -> List[discord.ui.Select]:
        def allowed(channel: discord.TextChannel):
            if channel.can_send(discord.Embed):
                if channel.permissions_for(ctx.author).is_superset(
                    discord.Permissions(read_messages=True, send_messages=True, embed_links=True)
                ):
                    return True
            return False

        channels = filter(allowed, ctx.guild.text_channels)
        channels = list(channels)
        channels.sort(key=lambda c: c.position)

        def get_callback(selector: discord.ui.Select):
            async def callback(interaction: discord.Interaction):
                await EmbedCreatorView.defer_invisible(interaction)
                selector.view.choice = selector.view.ctx.bot.get_channel(int(selector.values[0]))
                selector.view.stop()

            return callback

        selectors = []
        for chunk in discord.utils.as_chunks(channels, 25):
            _selector = discord.ui.Select(placeholder="Select a channel")
            for _channel in chunk:
                _selector.add_option(
                    label=str(_channel),
                    value=str(_channel.id),
                    emoji=discord.utils.get(ctx.bot.emojis, name="text_channel") or "\U00000023\U0000fe0f\U000020e3",
                )
            _selector.callback = get_callback(_selector)
            selectors.append(_selector)

        return selectors

    @button(label="stop", style=discord.ButtonStyle.danger)
    async def cancel(self, _, interaction: discord.Interaction):
        await EmbedCreatorView.defer_invisible(interaction)
        self.stop()


class EmbedCreatorFieldManagerFieldEditor(AutoDisableView):
    def __init__(self, parent: EmbedCreatorView):
        self.parent = parent
        super().__init__()
        self.selected_field: Optional[Tuple[int, discord.EmbedField]] = None
        self.select = discord.ui.Select(
            options=[
                discord.SelectOption(
                    label=f"Field #{n+1} ({textwrap.shorten(field.name, 25, placeholder='...')})", value=str(n)
                )
                for n, field in enumerate(self.parent.embed.fields)
            ]
        )
        self.select.callback = self.callback
        self.add_item(self.select)

    async def callback(self, interaction: discord.Interaction):
        await EmbedCreatorView.defer_invisible(interaction)
        value = int(self.select.values[0])
        self.selected_field = value, self.parent.embed.fields[value]
        self.enable_all_items()
        self.remove_item(self.select)
        await interaction.edit_original_message(view=self)

    @button(label="Edit", emoji="\N{pencil}", custom_id="edit", disabled=True)
    async def edit_selection(self, _, interaction: discord.Interaction):
        remaining = len(self.parent.embed)
        if remaining < 2:
            return await interaction.followup.send("Embed is full.")
        modal = TenMinuteTimeoutModal(
            discord.ui.InputText(
                custom_id="name",
                label="Field title:",
                placeholder="Required",
                min_length=1,
                max_length=256,
                value=self.selected_field[1].name,
            ),
            discord.ui.InputText(
                custom_id="value",
                label="Content:",
                placeholder="Required",
                min_length=1,
                max_length=1024,
                value=self.selected_field[1].value,
                style=discord.InputTextStyle.long,
            ),
            discord.ui.InputText(
                custom_id="inline",
                label="inline?",
                placeholder="y for yes, n for no",
                max_length=1,
                min_length=1,
                value={True: "y", False: "n"}[self.selected_field[1].inline],
            ),
            title="Edit field",
        )
        modal.callback = EmbedCreatorView.simple_modal_callback(modal)
        if not await EmbedCreatorView.send_modal(interaction, modal):
            await self.parent.edit(content="Field was not edited (timed out)")
        else:
            inline = modal.children[-1].value[0].lower() == "y"
            size = len(modal.children[0].value) + len(modal.children[1].value)
            if size > remaining:
                await self.parent.edit(
                    content=f"Field was not added (not enough space - only {remaining} characters"
                    f" remaining, field was {size:,} characters)"
                )
            else:
                self.parent.embed.remove_field(self.selected_field[0])
                self.parent.embed.insert_field_at(
                    index=self.selected_field[0],
                    name=modal.children[0].value,
                    value=modal.children[1].value,
                    inline=inline,
                )
                await self.parent.edit(
                    content=f"Added field #{len(self.parent.embed.fields)}.", embed=self.parent.embed
                )
        self.stop()


class EmbedCreatorFieldManagerFieldRemover(AutoDisableView):
    def __init__(self, parent: EmbedCreatorView):
        self.parent = parent
        self.ctx = parent.ctx
        super().__init__()
        self.select = discord.ui.Select(
            options=[
                discord.SelectOption(
                    label=f"Field #{n+1} ({textwrap.shorten(field.name, 80, placeholder='...')})",
                    value=str(hash(field.name) + hash(field.value)),
                )
                for n, field in enumerate(self.parent.embed.fields)
            ]
        )
        self.select.max_values = len(self.select.options)
        self.select.callback = self.callback
        self.add_item(self.select)

    async def callback(self, interaction: discord.Interaction):
        await EmbedCreatorView.defer_invisible(interaction)
        copy = self.parent.embed.fields.copy()
        for field in copy:
            if str(hash(field.name) + hash(field.value)) in self.select.values:
                self.parent.embed.remove_field(self.parent.embed.fields.index(field))
        self.enable_all_items()
        await interaction.edit_original_message(view=self)
        await self.parent.edit(f"Removed {len(self.select.values)} fields.", embed=self.parent.embed)
        self.stop()
