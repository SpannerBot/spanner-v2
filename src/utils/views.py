import datetime
import os

import discord
from discord.ui import View, Item, Button, Select, button, InputText, Modal
from discord import ButtonStyle, InputTextStyle
from src.database import Polls, SimplePoll


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


class SimplePollView(View):
    def __init__(self, poll_id: int):
        super().__init__(
            timeout=None
        )
        self.poll_id = poll_id
        self.db = None

    async def get_db(self):
        if self.db:
            return self.db
        self.db = await SimplePoll.objects.get(id=self.poll_id)
        return self.db

    @button(custom_id="yes", emoji="\N{white heavy check mark}")
    async def confirm(self, btn: discord.Button, interaction: discord.Interaction):
        db = await self.get_db()
        if datetime.datetime.utcnow() >= db.ends_at:
            for child in self.children:
                if isinstance(child, Button):
                    if child.label in ("See results", "Delete poll"):
                        continue
                    child.disabled = True
                await interaction.edit_original_message(view=self)
            return await interaction.response.send_message(f"This poll ended {discord.utils.format_dt(db.ends_at)}",
                                                           ephemeral=True)
        if str(interaction.user.id) in db.voted.keys():
            return await interaction.response.send_message("You already voted!", ephemeral=True)
        else:
            db.voted[str(interaction.user.id)] = True
            await db.update(voted=db.voted)
            await interaction.response.send_message("You voted \N{WHITE HEAVY CHECK MARK}!", ephemeral=True)

    @button(custom_id="no", emoji="\N{cross mark}")
    async def deny(self, btn: discord.Button, interaction: discord.Interaction):
        db = await self.get_db()
        if datetime.datetime.utcnow() >= db.ends_at:
            for child in self.children:
                if isinstance(child, Button):
                    if child.label in ("See results", "Delete poll"):
                        continue
                    child.disabled = True
                await interaction.edit_original_message(view=self)
            return await interaction.response.send_message(f"This poll ended {discord.utils.format_dt(db.ends_at)}",
                                                           ephemeral=True)
        if str(interaction.user.id) in db.voted.keys():
            return await interaction.response.send_message("You already voted!", ephemeral=True)
        else:
            db.voted[str(interaction.user.id)] = False
            await db.update(voted=db.voted)
            await interaction.response.send_message("You voted \N{cross mark}!", ephemeral=True)

    @button(custom_id="view", label="See results", emoji="\N{eyes}", row=2)
    async def view_results(self, btn: discord.Button, interaction: discord.Interaction):
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

        embed = discord.Embed(
            title=f"Poll results:",
            description=f"Yes (\N{WHITE HEAVY CHECK MARK}): {total_yes:,} ({percent(total_yes, total)}%)\n"
                        f"No (\N{cross mark}): {total_no:,} ({percent(total_no, total)}%)\n"
                        f"Total votes: {total:,} "
                        f"({percent(total, len(interaction.message.channel.members))}% of members who can vote)\n"
                        f"Poll ends {discord.utils.format_dt(db.ends_at, 'R')}.",
            colour=colour
        )

        if interaction.user.id == db.owner or datetime.datetime.utcnow() >= db.ends_at:
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            return await interaction.response.send_message("You cannot view results yet!", ephemeral=True)

    @button(custom_id="delete", label="Delete poll", style=ButtonStyle.red, emoji="\N{wastebasket}\U0000fe0f", row=2)
    async def delete(self, btn: discord.Button, interaction: discord.Interaction):
        db = await self.get_db()
        if interaction.user.id != db.owner:
            return await interaction.response.send_message("You can't delete this poll!", ephemeral=True)
        else:
            await interaction.delete_original_message()
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
                return await interaction.response.send_message(
                    "You already voted in this poll.",
                    ephemeral=True
                )
            else:
                yn = YesNoPrompt(120)
                message = await interaction.followup.send(
                    "Would you like to vote for this option? You cannot go back!",
                    view=yn,
                    ephemeral=True
                )
                await yn.wait()
                if yn.confirm is False:
                    return await message.edit(
                        "You have cancelled your vote.",
                        view=None
                    )
                else:
                    self.view.entry.results[str(interaction.user.id)] = self.index
                    await self.view.entry.update(results=self.view.entry.results)
                    await message.edit(
                        "You have voted for option {}.".format(self.index),
                        view=None
                    )

    def __init__(self, poll_entry, options: list):
        super().__init__(timeout=None)
        self.entry = poll_entry
        for option in options:
            self.add_item(
                self.PollButton(
                    label=option,
                    index=options.index(option)
                )
            )


class CreatePollView(View):
    value: str = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @button(label="Add new option", style=ButtonStyle.green, emoji="\N{HEAVY PLUS SIGN}")
    async def add_new_option(self, btn: discord.Button, interaction: discord.Interaction):
        self.value = "ADD_NEW"
        self.stop()

    @button(label="Remove an option", style=ButtonStyle.red, emoji="\N{HEAVY MINUS SIGN}")
    async def remove_option(self, btn: discord.Button, interaction: discord.Interaction):
        self.value = "REMOVE"
        self.stop()

    @button(label="Create", style=ButtonStyle.green, emoji="\N{WHITE HEAVY CHECK MARK}")
    async def finish(self, *args):
        self.value = "DONE"
        self.stop()

    @button(label="Cancel", style=ButtonStyle.red)
    async def cancel(self, btn: discord.Button, interaction: discord.Interaction):
        self.value = "STOP"
        self.stop()


class CreateNewPollOption(Modal):
    def __init__(self):
        super().__init__(
            title="Create new poll option",
        )
        self.value = None
        self.text_input = InputText(
                label="Option value",
                min_length=1,
                max_length=100,
                required=True
            )
        self.add_item(
            self.text_input
        )

    async def callback(self, interaction: discord.Interaction):
        self.value = self.text_input.value
        self.stop()

    async def run(self) -> str:
        await self.wait()
        return self.value


class RemovePollOptionDropDown(View):
    class SelectOption(Select):
        def __init__(self, choices: list):
            super().__init__(
                min_values=1, max_values=len(choices)-1
            )
            self.choices = choices
            for opt in choices:
                self.add_option(
                    label=opt,
                    value=str(choices.index(opt)),
                    emoji="\N{cross mark}"
                )

        async def callback(self, interaction: discord.Interaction):
            for choice in self.values:
                self.choices.pop(int(choice))
            self.view.value = self.choices
            self.view.stop()

    def __init__(self, options: list):
        super().__init__()
        self.value = None
        self.add_item(
            self.SelectOption(options)
        )
