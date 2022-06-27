import random

import discord
from discord.ext import commands

from src.database.models import WelcomeMessage
from src.utils import get_guild_config, utils, views


async def is_owner(ctx: discord.ApplicationContext) -> bool:
    if not await ctx.bot.is_owner(ctx.author):
        return False
    return True


class ConfigCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    config = discord.SlashCommandGroup(
        "settings",
        "Manages server settings",
        default_member_permissions=discord.Permissions(manage_guild=True),
        guild_only=True,
    )

    @config.command()
    async def view(self, ctx: discord.ApplicationContext):
        """Shows server settings"""
        guild = await get_guild_config(ctx)
        log_channel = guild.log_channel
        if guild.log_channel is not None:
            log_channel = ctx.guild.get_channel(guild.log_channel)
            if log_channel:
                log_channel = log_channel.mention
            else:
                log_channel = str(guild.log_channel)

        embed = discord.Embed(
            title=f"Settings for {ctx.guild.name!r}:",
            description="Database ID: {0.entry_id!s}\n"
            "Server ID: {0.id!s}\n"
            "(\N{WAVING WHITE FLAG}\U0000fe0f) Prefix: `{0.prefix!s}`\n"
            "Log Channel: {1}\n".format(guild, log_channel),
            colour=discord.Colour.blue(),
        )
        return await ctx.respond(embed=embed)

    @config.command(name="set-log-channel")
    async def set_log_channel(self, ctx: discord.ApplicationContext, channel: discord.TextChannel = None):
        """Sets the channel where moderation events are logged to."""
        guild = await get_guild_config(ctx)
        channel_id = None
        if channel is not None:
            if not channel.can_send(discord.Embed, discord.File):
                return await ctx.respond(
                    f"\N{cross mark} I can't send things I need to be able to send in {channel.mention}.\n"
                    f"Make sure I have view channel, send messages, embed links, and attach files."
                )
            channel_id = channel.id

        await guild.update(log_channel=channel_id)
        if channel:
            return await ctx.respond(f"Set your log channel to {channel.mention}.")
        else:
            return await ctx.respond("Removed your log channel.")

    @config.command(name="toggle-vote-kick")
    @commands.has_permissions(kick_members=True)
    @commands.bot_has_permissions(kick_members=True)
    @utils.disable_with_reason(reason="Command is not ready yet.")
    async def toggle_vote_kick(self, ctx: discord.ApplicationContext, enable: bool = None):
        """Toggles the vote kick command on or off"""

    welcome_message = config.create_subgroup("welcome-message", "Manages your welcome message settings")

    # @commands.message_command(name="set-message")
    # @discord.default_permissions(manage_guild=True)
    # @utils.disable_with_reason(is_owner, reason="Command not ready yet.")
    # async def set_message(self, ctx: discord.ApplicationContext, message: discord.Message):
    #     await ctx.defer()
    #     guild = await utils.get_guild_config(ctx.guild)
    #     _message, _ = await WelcomeMessage.objects.get_or_create(guild=guild, defaults={})
    #     await _message.update(message=message.content)
    #     return await ctx.respond("\N{white heavy check mark}")

    @welcome_message.command(name="set-embed")
    @utils.disable_with_reason(is_owner, reason="Command not ready yet.")
    async def welcome_set_embed(self, ctx: discord.ApplicationContext):
        """Sets the welcome message embed that is sent when someone joins your server."""

        class EmbedModal(discord.ui.Modal):
            def __init__(self):
                super().__init__(
                    discord.ui.InputText(
                        custom_id="title",
                        label="Title",
                        placeholder="Welcome, {user.name}!",
                        max_length=256,
                        required=False,
                    ),
                    discord.ui.InputText(
                        custom_id="description",
                        label="Body",
                        style=discord.InputTextStyle.paragraph,
                        placeholder="We now have {server.members} members!",
                        max_length=4000,
                        required=True,
                    ),
                    discord.ui.InputText(
                        custom_id="colour",
                        label="colour" if ctx.guild_locale == "en-GB" else "color",
                        placeholder="#57F287",
                        required=False,
                        value=random.choice(("green", "#57F287", "57F287")),
                        max_length=12,
                    ),
                    title="Customise your embed",
                )

            async def callback(self, interaction: discord.Interaction):
                await interaction.response.defer(ephemeral=True)
                guild = await get_guild_config(ctx.guild)
                embed_kwargs = {}
                for child in self.children:
                    if child.custom_id == "colour":
                        try:
                            # noinspection PyTypeChecker
                            colour = await commands.ColourConverter().convert(None, child.value)
                        except commands.BadColourArgument:
                            colour = discord.Colour.default()
                        embed_kwargs["colour"] = colour
                    else:
                        embed_kwargs[child.custom_id] = child.value or discord.Embed.Empty

                embed = discord.Embed(**embed_kwargs)
                embed.set_author(name=str(ctx.author), icon_url=str(utils.avatar(ctx.author, display=False)))
                embed.set_footer(text=str(ctx.guild), icon_url=ctx.guild.icon or utils.avatar(ctx.me))
                ynv = views.YesNoPrompt()
                await interaction.followup.send(
                    embeds=[embed, discord.Embed(title="Does this look right?", colour=discord.Colour.orange())],
                    view=ynv,
                )
                await ynv.wait()
                if ynv.confirm:
                    await WelcomeMessage.objects.update_or_create({"embed_data": embed.to_dict()}, guild=guild)
                    return await interaction.edit_original_message(content="Saved.", embed=None, view=None)
                else:
                    return await interaction.edit_original_message(content="Not saved.", view=None, embed=None)

        await ctx.send_modal(EmbedModal())

    @welcome_message.command(name="ignore-bots")
    @utils.disable_with_reason(is_owner, reason="Command not ready yet.")
    async def welcome_ignore_bots(
        self,
        ctx: discord.ApplicationContext,
        ignore_bots: discord.Option(
            str, name="ignore-bots", description="Should welcome messages ignore bots?", choices=["Yes", "No"]
        ),
    ):
        """Sets if the welcome messages should ignore new bots"""
        await ctx.defer()
        guild = await utils.get_guild_config(ctx.guild)
        message, _ = await WelcomeMessage.objects.get_or_create(guild=guild, defaults={})
        await message.update(ignore_bots=ignore_bots)
        return await ctx.respond("\N{white heavy check mark} Will%signore bots" % ("" if ignore_bots else " not "))

    @welcome_message.command(name="delete-message-after")
    @utils.disable_with_reason(is_owner, reason="Command not ready yet.")
    async def welcome_delete_after(
        self,
        ctx: discord.ApplicationContext,
        time: discord.Option(
            str,
            name="after",
            description="How long the message should exist for (e.g. 1h30m). default is forever.",
            default="forever",
        ),
    ):
        try:
            converted = utils.TimeFormat.parse_relative(time)
        except ValueError:
            return await ctx.respond(
                "Time format not recognised. Try a time like '1 hour', '10 minutes', '1m30s' or "
                "'1 minute and 30 seconds."
            )
        await ctx.defer()
        guild = await utils.get_guild_config(ctx.guild)
        message, _ = await WelcomeMessage.objects.get_or_create({}, guild=guild)
        await message.update(delete_after=converted)
        return await ctx.respond(f"Welcome messages will now self-destruct after {utils.format_time(converted)}.")


def setup(bot):
    bot.add_cog(ConfigCog(bot))
