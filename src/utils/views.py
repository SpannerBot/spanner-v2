import datetime
from typing import Dict, List, Optional, Union
from io import BytesIO

import discord
from discord.ext import pages, commands
from discord.ui import View, Button, Select, button, InputText, Modal
from discord import ButtonStyle
from src.database import SimplePoll


__all__ = ("YesNoPrompt", "PollView", "CreatePollView", "CreateNewPollOption", "RemovePollOptionDropDown")


class YesNoPrompt(View):
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


class SimplePollViewSeeResultsViewVotersView(View):
    # what the fuck
    def __init__(self, voters: Dict[str, bool]):
        super().__init__()
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
            await paginator.respond(interaction, True)
            self.stop()
        else:
            await interaction.response.send_message("Only administrators can view voters.", ephemeral=True)


class SimplePollView(View):
    def __init__(self, poll_id: int):
        super().__init__(timeout=None)
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
                f"This poll ended {discord.utils.format_dt(ends_at, 'R')}" f"\nPress 'See results' to see the results.",
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
        viewable = sum(1 for x in interaction.message.channel.members if x.bot is False)

        embed = discord.Embed(
            title=f"Poll results:",
            description=f"Yes (\N{WHITE HEAVY CHECK MARK}): {total_yes:,} ({percent(total_yes, total)}%)\n"
            f"No (\N{cross mark}): {total_no:,} ({percent(total_no, total)}%)\n"
            f"Total votes: {total:,} "
            f"({percent(total, viewable)}% of members who can vote)\n"
            f"Poll ends/ended {discord.utils.format_dt(ends_at, 'R')}.",
            colour=colour,
        )

        if interaction.user.id == db.owner or datetime.datetime.utcnow() >= ends_at:
            _view = SimplePollViewSeeResultsViewVotersView(self.db.voted)
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


class PollView(View):
    class PollButton(Button):
        def __init__(self, label: str, index: int):
            super().__init__(label=label, style=ButtonStyle.grey)
            self.index = index

        async def callback(self, interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            if str(interaction.user.id) in self.view.entry.results.keys():
                return await interaction.response.send_message("You already voted in this poll.", ephemeral=True)
            else:
                yn = YesNoPrompt(120)
                message = await interaction.followup.send(
                    "Would you like to vote for this option? You cannot go back!", view=yn, ephemeral=True
                )
                await yn.wait()
                if yn.confirm is False:
                    return await message.edit("You have cancelled your vote.", view=None)
                else:
                    self.view.entry.results[str(interaction.user.id)] = self.index
                    await self.view.entry.update(results=self.view.entry.results)
                    await message.edit("You have voted for option {}.".format(self.index), view=None)

    def __init__(self, poll_entry, options: list):
        super().__init__(timeout=None)
        self.entry = poll_entry
        for option in options:
            self.add_item(self.PollButton(label=option, index=options.index(option)))


class CreatePollView(View):
    value: str = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @button(label="Add new option", style=ButtonStyle.green, emoji="\N{HEAVY PLUS SIGN}")
    async def add_new_option(self, *_):
        self.value = "ADD_NEW"
        self.stop()

    @button(label="Remove an option", style=ButtonStyle.red, emoji="\N{HEAVY MINUS SIGN}")
    async def remove_option(self, *_):
        self.value = "REMOVE"
        self.stop()

    @button(label="Create", style=ButtonStyle.green, emoji="\N{WHITE HEAVY CHECK MARK}")
    async def finish(self, *_):
        self.value = "DONE"
        self.stop()

    @button(label="Cancel", style=ButtonStyle.red)
    async def cancel(self, *_):
        self.value = "STOP"
        self.stop()


class CreateNewPollOption(Modal):
    def __init__(self):
        super().__init__(
            title="Create new poll option",
        )
        self.value = None
        self.text_input = InputText(label="Option value", min_length=1, max_length=100, required=True)
        self.add_item(self.text_input)

    async def callback(self, interaction: discord.Interaction):
        self.value = self.text_input.value
        self.stop()

    async def run(self) -> str:
        await self.wait()
        return self.value


class RemovePollOptionDropDown(View):
    class SelectOption(Select):
        def __init__(self, choices: list):
            super().__init__(min_values=1, max_values=len(choices) - 1)
            self.choices = choices
            for opt in choices:
                self.add_option(label=opt, value=str(choices.index(opt)), emoji="\N{cross mark}")

        async def callback(self, interaction: discord.Interaction):
            for choice in self.values:
                self.choices.pop(int(choice))
            self.view.value = self.choices
            self.view.stop()

    def __init__(self, options: list):
        super().__init__()
        self.value = None
        self.add_item(self.SelectOption(options))


class StealEmojiView(View):
    def __init__(self, emoji: Union[discord.Emoji, discord.PartialEmoji]):
        super().__init__(timeout=300)
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
                "You need to have manage emojis permission to steal emojis.",
                ephemeral=ephemeral
            )
        if not interaction.user.guild.me.guild_permissions.manage_emojis:
            return await interaction.response.send_message(
                "I need to have manage emojis permission to steal emojis.",
                ephemeral=ephemeral
            )
        if len(interaction.guild.emojis) >= interaction.guild.emoji_limit:
            return await interaction.response.send_message(
                "You can't have more than {:,} emojis in this server.".format(interaction.guild.emoji_limit),
                ephemeral=ephemeral
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
                "Something went wrong while creating the emoji.\n" + str(e),
                ephemeral=ephemeral
            )
        else:
            btn.disabled = True
            await interaction.message.edit(view=self)
            await interaction.followup.send(
                f"Emoji stolen! `{new_emoji!s}`",
                ephemeral=ephemeral
            )
            self.stop()
