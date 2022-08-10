import io
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Union, List

import discord
import httpx
import orm
from discord.ext import bridge
from discord.ext import commands, pages as pagination

from src.bot.client import Bot
from src.database import Errors, models
from src.utils import utils


async def get_similar_case_ids(ctx: discord.AutocompleteContext) -> List[int]:
    results: List[int] = [x.id for x in await Errors.objects.all() if str(ctx.value) in str(x.id)]
    results.sort(reverse=True)  # brings the newest case IDs first
    return results


class Debug(commands.Cog):
    def __init__(self, bot: Bot):
        self.bot: Bot = bot
        self.loaded_at = datetime.now()

    @commands.command(name="type", hidden=True)
    @commands.is_owner()
    async def find_id_type(self, ctx: commands.Context, *, obj: int):
        converters = (
            commands.GuildConverter,
            commands.GuildChannelConverter,
            commands.RoleConverter,
            commands.MemberConverter,
            commands.UserConverter,
            commands.MessageConverter,
            commands.EmojiConverter,
            commands.PartialEmojiConverter,
            commands.ObjectConverter,
        )
        result: Union[
            discord.Guild,
            discord.abc.GuildChannel,
            discord.Role,
            discord.Member,
            discord.User,
            discord.Message,
            discord.Emoji,
            discord.PartialEmoji,
            discord.Object,
        ]
        async with ctx.channel.typing():
            for converter in converters:
                try:
                    result = await converter().convert(ctx, str(obj))
                except (commands.BadArgument, commands.ConversionError):
                    continue
                else:
                    break

        if isinstance(result, discord.abc.GuildChannel):
            # noinspection PyUnresolvedReferences
            return await ctx.reply(
                f"{result.id} is a {result.type.name} channel ({result.mention}) in {result.guild.name} "
                f"({result.guild.id})"
            )
        return await ctx.reply(
            f"{obj} is a {result.__class__.__name__!r} with ID {result.id}.",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @bridge.bridge_command(name="ping")
    async def ping(self, ctx: discord.ApplicationContext):
        """Shows the bot's latency."""
        await ctx.respond(f"Pong! {round(self.bot.latency * 1000, 2)}ms")

    @commands.slash_command(name="clean")
    async def clean_bot_message(self, ctx: discord.ApplicationContext, max_search: discord.Option(int, default=100)):
        """Deletes all messages sent by the bot up to <max_search> messages."""
        if ctx.author.id not in self.bot.owner_ids:
            if not ctx.channel.permissions_for(ctx.author).manage_messages:
                return await ctx.respond("You don't have permission to do that.")

        if max_search <= 0:
            if ctx.author not in self.bot.owner_ids:
                max_search = 10
            else:
                max_search = None
        else:
            max_search = max(10, min(10_000, max_search))

        await ctx.defer()

        prefixes = ("s!", ctx.me.mention)
        if ctx.guild:
            guild = await utils.get_guild(ctx.guild)
            prefixes = (guild.prefix, ctx.me.mention)

        def purge_check(_message: discord.Message):
            return _message.author == self.bot.user or _message.content.startswith(prefixes)

        try:
            deleted_messages = await ctx.channel.purge(limit=max_search + 1, check=purge_check)
        except discord.Forbidden:
            deleted_messages = []
            async for message in ctx.channel.history(limit=max_search):
                if purge_check(message):
                    await message.delete(delay=0.01)
                    deleted_messages.append(b"\0")
        except discord.HTTPException as e:
            code = (
                f"[{e.code}: {e.text[:100]}](https://discord.com/developers/docs/topics/"
                f"opcodes-and-status-codes#json:~:text={e.code})"
            )
            await ctx.respond(f"Failed to delete messages: {code}")
            return
        try:
            await ctx.respond(f"Deleted {len(deleted_messages)} messages.", ephemeral=True)
        except discord.HTTPException:
            pass

    @commands.slash_command()
    async def invite(self, ctx: discord.ApplicationContext):
        """Gets the bot's invite link."""
        url = discord.utils.oauth_url(self.bot.user.id, scopes=("bot", "applications.commands"))
        await ctx.respond(f'[Did you know you can click on my profile and click "add to server"?]({url})')

    @commands.command()
    @commands.is_owner()
    async def err(self, ctx):
        """Raises an error."""
        raise FileNotFoundError("Artificial error.")

    @commands.slash_command(name="get-error-case")
    @commands.is_owner()
    async def get_error_case(
        self,
        ctx: discord.ApplicationContext,
        case_id: discord.Option(
            str, "The ID of the case", autocomplete=discord.utils.basic_autocomplete(get_similar_case_ids)
        ),
        ephemeral: discord.Option(bool, "Whether to send the error message as an ephemeral message", default=False),
    ):
        """Fetches an error case"""

        if models.DB_STAT is None:
            models.DB_STAT = datetime.fromtimestamp((Path.cwd() / "main.db").stat().st_ctime, timezone.utc)

        try:
            case = await Errors.objects.get(id=case_id)
        except orm.NoMatch:
            return await ctx.respond("No case with that ID exists.", ephemeral=ephemeral)
        else:
            await ctx.defer(ephemeral=ephemeral)

            author = (await self.bot.get_or_fetch_user(case.author)) or ctx.me
            guild = self.bot.get_guild(case.guild) or author.dm_channel or ctx.guild
            channel = self.bot.get_channel(case.channel) or ctx.channel

            p = "https://discordapi.com/permissions.html#{!s}"
            guild_p = p.format(case.permissions_guild)
            channel_p = p.format(case.permissions_channel)

            full_message = "unavailable"
            if case.full_message is not None:
                try:
                    async with utils.session.post(
                            "https://h.nexy7574.cyou/documents",
                            data=case.full_message
                    ) as response:
                        full_message = "[available here](https://h.nexy7574.cyou/" + response.json()["key"] + ")"
                except httpx.HTTPError:
                    pass

            traceback_text = "```py\n{}\n```".format(case.traceback_text)
            if len(traceback_text) > 2000:
                async with utils.session.post(
                    "https://h.nexy7574.cyou/documents", data=case.traceback_text
                ) as response:
                    traceback_text = "[traceback available here](https://h.nexy7574.cyou/{})".format(
                        response.json()["key"]
                    )

            pages = [
                discord.Embed(
                    title="Context",
                    description=f"**Error ID:** `{case.id}`\n"
                    f"**Raised**: {discord.utils.format_dt(discord.utils.snowflake_time(case.id), 'R')}\n"
                    f"**Author**: {author.mention} (`{case.author}`)\n"
                    f"**Guild**: {guild} (`{case.guild}`)\n"
                    f"**Channel**: {getattr(channel, 'mention', 'DMs')} (`{case.channel}`)\n"
                    f"**Command**: {case.command}\n"
                    f"**Interaction Type**: {case.command_type.value} command\n"
                    f"**Permissions**: [guild]({guild_p}) | [channel-specific]({channel_p})\n"
                    f"**Full Message Content**: {full_message}",
                    colour=discord.Colour.blue(),
                ),
                traceback_text,
            ]

            class CustomView(discord.ui.View):
                @discord.ui.button(label="Delete", style=discord.ButtonStyle.red, emoji="\N{WASTEBASKET}")
                async def delete_callback(self, button: discord.ui.Button, interaction: discord.Interaction):
                    await case.delete()
                    button.disabled = True
                    await paginator.update(pages, show_disabled=False, timeout=300, custom_view=self)
                    await interaction.response.send_message(f"Deleted case #{case.id}.", ephemeral=True)

            paginator = pagination.Paginator(pages, show_disabled=False, timeout=300, custom_view=CustomView())
            await paginator.respond(ctx.interaction, ephemeral=ephemeral)

    @commands.command()
    @commands.is_owner()
    async def trace(self, ctx: commands.Context, *, seconds: int = 30):
        if seconds % 5:
            return await ctx.send("Seconds must be a multiple of 5.")

        try:
            from src.utils import Tracer
        except ImportError:
            return await ctx.send("Tracer is not ready.")

        t = Tracer(self.bot)
        ends_at = discord.utils.utcnow() + timedelta(seconds=seconds)
        message = await ctx.send("Tracing... (competes {})".format(discord.utils.format_dt(ends_at, "R")))
        t.start()
        async with ctx.channel.typing():
            await discord.utils.sleep_until(ends_at)  # may end up being inaccurate but like, who cares
        data = io.BytesIO()
        t.stop(data)
        data.seek(0)
        try:
            await message.edit(
                content="Trace complete.\n",
                file=discord.File(data, filename="trace.json"),
            )
        except discord.HTTPException:
            return
        finally:
            del t

    @commands.group(name="cogs", invoke_without_subcommand=True)
    @commands.is_owner()
    async def cogs(self, ctx: commands.Context):
        """Cog management. This command on its own lists all cogs."""
        return await ctx.reply("wip")


def setup(bot):
    bot.add_cog(Debug(bot))
