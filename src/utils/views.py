import datetime
from io import BytesIO
from typing import Dict, List, Optional, Union

import discord
from discord import ButtonStyle
from discord.ext import pages, commands
from discord.ui import View, Button, button

from src.database import SimplePoll

__all__ = ("YesNoPrompt", "SimplePollViewSeeResultsViewVotersView", "SimplePollView")


class AutoDisableView(View):
    interaction: discord.Interaction = None

    def __init__(self, interaction: discord.Interaction = None, *args, **kwargs):
        super().__init__(**kwargs)
        self.interaction = interaction

    async def on_timeout(self) -> None:
        self.disable_all_items()
        if self.interaction is not None and self.interaction.message is not None:
            await self.interaction.message.edit(view=self)
        self.stop()


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
