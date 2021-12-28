import datetime
import re
import textwrap
import uuid

import discord
from discord import SlashCommandGroup
from discord.ext import commands, pages

from src.utils import utils
from src.database import Cases, CaseType, Guild, NoMatch
from src.utils.views import YesNoPrompt


class PermissionsError(commands.CommandError):
    def __init__(self, *, reason: str):
        self.reason = reason

    def __str__(self):
        return self.reason


class Moderation(commands.Cog):
    case_identifier_regex = re.compile(
        r"Case#[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}\|\s"
    )

    def __init__(self, bot):
        self.bot = bot

    @staticmethod
    async def get_next_case_id(guild: Guild) -> int:
        last_case = await Cases.objects.filter(guild=guild).order_by("-id").first()
        if not last_case:
            return 1
        return last_case.id + 1

    @staticmethod
    def check_action_permissions(
        author: discord.Member, target: discord.Member, permission_name: str, *, allow_self: bool = True
    ) -> bool:
        # Step 1: Check if the bot has the required permissions.
        if getattr(author.guild.me.guild_permissions, permission_name) is False:
            raise PermissionsError(reason="I do not have the required permissions to perform this action.")
        # Step 2: Check if the author is immune to permissions checks.
        if author.guild_permissions.administrator:
            return True
        elif author.guild.owner_id == author.id:
            return True
        else:
            # Step 2.1: Check if the author is higher than the target.
            if author.top_role <= target.top_role:
                if author.id != target.id or (author.id == target.id and not allow_self):
                    raise PermissionsError(reason="You cannot perform this action on a user higher than you.")
            # Step 2.2: Check if the bot is higher than the target.
            if target.top_role >= author.guild.me.top_role:
                if author.id != target.id or (author.id == target.id and not allow_self):
                    raise PermissionsError(
                        reason="You cannot perform actions on users with a higher or equal role than me."
                    )
            # Step 2.3: Check if the author has the required permissions.
            if getattr(author.guild_permissions, permission_name) is False:
                raise PermissionsError(
                    reason="You do not have the required permissions to perform this action "
                    f"(hint: {permission_name.replace('_', ' ')!r})."
                )
        return True

    @commands.slash_command(name="hackban")
    async def hackban(self, ctx: discord.ApplicationContext, user_id: str, *, reason: str = "No Reason Provided"):
        """Bans a user by their ID before they can enter the server."""
        try:
            self.check_action_permissions(ctx.author, ctx.author, "ban_members")
        except PermissionsError as e:
            return await ctx.respond(str(e), ephemeral=True)

        try:
            user = await commands.UserConverter().convert(ctx, user_id)
        except commands.UserNotFound:
            return await ctx.respond("User not found.", ephemeral=True)
        else:
            if await discord.utils.get_or_fetch(ctx.guild, "member", user.id, default=None):
                return await ctx.respond("User is already in the server. Please use regular /ban.", ephemeral=True)

            view = YesNoPrompt(timeout=300.0)
            await ctx.respond(
                embed=discord.Embed(
                    title="Are you sure you want to hackban {!s}?".format(user), colour=discord.Colour.orange()
                ).set_footer(text=str(user), icon_url=user.display_avatar.url),
                view=view,
                ephemeral=True,
            )
            await view.wait()
            if not view.confirm:
                return await ctx.respond("Hackban cancelled.", ephemeral=True, view=None, embed=None)

            guild = await Guild.objects.get(id=ctx.guild.id)
            case = await Cases.objects.create(
                id=await self.get_next_case_id(guild),
                guild=guild,
                moderator=ctx.author.id,
                target=user.id,
                reason=reason,
                type=CaseType.BAN,
            )

            try:
                await ctx.guild.ban(user, reason=f"Case#{case.entry_id!s}| " + reason, delete_message_days=7)
            except discord.HTTPException as e:
                await case.delete()
                return await ctx.edit(content="Failed to ban user: {!s}".format(e), embed=None, view=None)
            except Exception:
                await case.delete()
                raise
            else:
                return await ctx.edit(
                    content="User {!s} has been banned.\nCase ID: {!s}".format(user, case.id), embed=None, view=None
                )

    @commands.slash_command(name="unban")
    async def unban(self, ctx: discord.ApplicationContext, user_id: str, *, reason: str = "No Reason Provided"):
        try:
            self.check_action_permissions(ctx.author, ctx.author, "ban_members")
        except PermissionsError as e:
            return await ctx.respond(str(e), ephemeral=True)

        try:
            user = await commands.UserConverter().convert(ctx, user_id)
        except commands.UserNotFound:
            return await ctx.respond("User not found.", ephemeral=True)
        else:
            try:
                ban = await ctx.guild.fetch_ban(discord.Object(id=user.id))
            except discord.NotFound:
                return await ctx.respond("User is not banned.", ephemeral=True)
            else:
                guild = await utils.get_guild(ctx.guild)
                if ban.reason:
                    ban_reason = self.case_identifier_regex.sub("", ban.reason, 1)
                else:
                    ban_reason = ban.reason
                ban_reason = textwrap.shorten(ban_reason, width=1024, placeholder="...") if ban.reason else None
                embed = discord.Embed(
                    title="Are you sure you want to unban %s?" % ban.user,
                    description=f"They were previously banned for:\n\n{ban_reason}" if ban_reason else None,
                    colour=discord.Colour.orange(),
                )
                embed.set_footer(text=str(ban.user), icon_url=ban.user.avatar.url)
                view = YesNoPrompt(timeout=300.0)
                await ctx.respond(embed=embed, view=view, ephemeral=True)
                await view.wait()
                if not view.confirm:
                    return await ctx.edit(content="Did not unban %s." % ban.user, embed=None, view=None)
                else:
                    case = await Cases.objects.create(
                        id=await self.get_next_case_id(guild),
                        guild=guild,
                        moderator=ctx.author.id,
                        target=ban.user.id,
                        reason=reason,
                        type=CaseType.UN_BAN,
                    )
                    await ctx.guild.unban(ban.user, reason=f"Case#{case.entry_id}| " + reason)
                    return await ctx.edit(
                        content="User {!s} has been unbanned.\nCase ID: {!s}".format(user, case.id),
                        embed=None,
                        view=None,
                    )

    @commands.slash_command(name="ban")
    async def ban(self, ctx: discord.ApplicationContext, member: discord.Member, *, reason: str = "No Reason Provided"):
        try:
            self.check_action_permissions(ctx.author, member, "ban_members", allow_self=False)
        except PermissionsError as e:
            return await ctx.respond(str(e), ephemeral=True)

        try:
            await ctx.guild.fetch_ban(member)
            return await ctx.respond("User is already banned.", ephemeral=True)
        except discord.NotFound:
            view = YesNoPrompt(timeout=300.0)
            await ctx.respond(
                embed=discord.Embed(
                    title="Are you sure you want to ban {!s}?".format(member), colour=discord.Colour.orange()
                ).set_footer(text=str(member), icon_url=member.display_avatar.url),
                view=view,
                ephemeral=True,
            )
            await view.wait()
            if not view.confirm:
                return await ctx.edit(content="Ban cancelled.", embed=None, view=None)

            guild = await Guild.objects.get(id=ctx.guild.id)
            case = await Cases.objects.create(
                id=await self.get_next_case_id(guild),
                guild=guild,
                moderator=ctx.author.id,
                target=member.id,
                reason=reason,
                type=CaseType.BAN,
            )

            try:
                await member.ban(reason=f"Case#{case.entry_id!s}| " + reason, delete_message_days=7)
            except discord.HTTPException as e:
                await case.delete()
                return await ctx.edit(content="Failed to ban user: {!s}".format(e), embed=None, view=None)
            except Exception:
                await case.delete()
                raise
            else:
                return await ctx.edit(
                    content="User {!s} has been banned.\nCase ID: {!s}".format(member, case.id), embed=None, view=None
                )

    @commands.slash_command(name="kick")
    async def kick(
        self, ctx: discord.ApplicationContext, member: discord.Member, *, reason: str = "No Reason Provided"
    ):
        try:
            self.check_action_permissions(ctx.author, member, "kick_members", allow_self=False)
        except PermissionsError as e:
            return await ctx.respond(str(e), ephemeral=True)

        view = YesNoPrompt(timeout=300.0)
        await ctx.respond(
            embed=discord.Embed(
                title="Are you sure you want to kick {!s}?".format(member), colour=discord.Colour.orange()
            ).set_footer(text=str(member), icon_url=member.display_avatar.url),
            view=view,
            ephemeral=True,
        )
        await view.wait()
        if not view.confirm:
            return await ctx.edit(content="Kick cancelled.", embed=None, view=None)

        guild = await Guild.objects.get(id=ctx.guild.id)
        case = await Cases.objects.create(
            id=await self.get_next_case_id(guild),
            guild=guild,
            moderator=ctx.author.id,
            target=member.id,
            reason=reason,
            type=CaseType.KICK,
        )

        try:
            await member.kick(reason=f"Case#{case.entry_id!s}| " + reason)
        except discord.HTTPException as e:
            await case.delete()
            return await ctx.edit(content="Failed to ban user: {!s}".format(e), embed=None)
        except Exception:
            await case.delete()
            raise
        else:
            return await ctx.edit(
                content="User {!s} has been kicked.\nCase ID: {!s}".format(member, case.id), embed=None, view=None
            )

    @commands.slash_command(name="mute")
    async def mute(
        self, ctx: discord.ApplicationContext, member: discord.Member, time: str, reason: str = "No Reason Provided"
    ):
        try:
            self.check_action_permissions(ctx.author, member, "moderate_members", allow_self=False)
        except PermissionsError as e:
            return await ctx.respond(str(e), ephemeral=True)

        try:
            seconds = utils.parse_time(time)
        except ValueError:
            return await ctx.respond("Invalid time format. Try passing something like '30 seconds'.", ephemeral=True)
        else:
            max_time = discord.utils.utcnow() + datetime.timedelta(days=28)
            end = discord.utils.utcnow() + datetime.timedelta(seconds=seconds)
            if end > max_time or (end - discord.utils.utcnow()).total_seconds() <= 60:
                return await ctx.respond(
                    "You can't mute a user for more than 28 days or less than 1 minute.", ephemeral=True
                )

        view = YesNoPrompt(timeout=300.0)
        await ctx.respond(
            f"Are you sure you want to mute {member} until <t:{round(end.timestamp())}>?", ephemeral=True, view=view
        )
        await view.wait()
        if not view.confirm:
            await ctx.edit(content="Mute cancelled.", embed=None, view=None)
            return
        await ctx.edit(view=None)

        guild = await utils.get_guild(ctx.guild)
        case = await Cases.objects.create(
            id=await self.get_next_case_id(guild),
            guild=guild,
            moderator=ctx.author.id,
            target=member.id,
            reason=reason,
            type=CaseType.TEMP_MUTE,
            expire_at=end,
        )

        try:
            end = discord.utils.utcnow() + datetime.timedelta(seconds=seconds)  # recalculate
            await member.timeout(until=end, reason=f"Case#{case.entry_id!s}| " + reason)
        except discord.HTTPException as e:
            await case.delete()
            return await ctx.edit(content="Failed to mute user: {!s}".format(e), embed=None)
        except Exception:
            await case.delete()
            raise
        else:
            return await ctx.edit(
                content=f"User {member} has been muted and will be unmuted <t:{round(end.timestamp())}:R>.\n"
                f"Case ID: {case.id!s}",
                embed=None,
                view=None,
            )

    @commands.slash_command(name="unmute")
    async def unmute(self, ctx: discord.ApplicationContext, member: discord.Member, reason: str = "No Reason Provided"):
        try:
            self.check_action_permissions(ctx.author, member, "moderate_members", allow_self=False)
        except PermissionsError as e:
            return await ctx.respond(str(e), ephemeral=True)

        end = member.communication_disabled_until

        view = YesNoPrompt(timeout=300.0)
        await ctx.respond(
            f"Are you sure you want to unmute {member}?"
            + (f" Their current mute will automatically expire <t:{round(end.timestamp())}:R>" if end else ""),
            ephemeral=True,
            view=view,
        )
        await view.wait()
        if not view.confirm:
            await ctx.edit(content="Unmute cancelled.", embed=None, view=None)
            return
        await ctx.edit(view=None)

        guild = await utils.get_guild(ctx.guild)
        case = await Cases.objects.create(
            id=await self.get_next_case_id(guild),
            guild=guild,
            moderator=ctx.author.id,
            target=member.id,
            reason=reason,
            type=CaseType.UN_MUTE,
        )

        try:
            await member.remove_timeout(reason=f"Case#{case.entry_id!s}| " + reason)
        except discord.HTTPException as e:
            await case.delete()
            return await ctx.edit(content="Failed to mute user: {!s}".format(e), embed=None)
        except Exception:
            await case.delete()
            raise
        else:
            return await ctx.edit(
                content=f"User {member} has been unmuted.\n" f"Case ID: {case.id!s}", embed=None, view=None
            )

    cases_group = SlashCommandGroup("cases", "Case management")

    @cases_group.command(name="delete")
    async def delete_case(self, ctx: discord.ApplicationContext, case_id: int):
        try:
            self.check_action_permissions(ctx.author, ctx.author, "moderate_members")
        except PermissionsError as e:
            return await ctx.respond(str(e), ephemeral=True)

        guild = await utils.get_guild(ctx.guild)
        try:
            case = await Cases.objects.get(id=case_id, guild=guild)
        except NoMatch:
            return await ctx.respond("Case not found.", ephemeral=True)

        view = YesNoPrompt(timeout=300.0)
        await ctx.respond("Are you sure you would like to delete case #{!s}?".format(case.entry_id), view=view)
        await view.wait()
        if not view.confirm:
            return await ctx.edit(content="Case deletion cancelled.", view=None)
        await case.delete()
        return await ctx.edit(content="Deleted case #{!s}.".format(case.entry_id), view=None)

    @cases_group.command(name="view")
    async def get_case(self, ctx: discord.ApplicationContext, case_id: str):
        try:
            self.check_action_permissions(ctx.author, ctx.author, "moderate_members")
        except PermissionsError as e:
            return await ctx.respond(str(e), ephemeral=True)

        guild = await utils.get_guild(ctx.guild)
        try:
            case = await Cases.objects.get(id=case_id, guild=guild)
        except NoMatch:
            try:
                case = await Cases.objects.get(entry_id=uuid.UUID(case_id), guild=guild)
            except (NoMatch, ValueError):
                return await ctx.respond("Case not found.", ephemeral=True)

        moderator = await self.bot.get_or_fetch_user(case.moderator)
        target = await self.bot.get_or_fetch_user(case.target)
        case_name = utils.case_type_names[case.type.value].title()
        nl = "\n"

        embed = discord.Embed(
            title="Case #{!s}: {!s}".format(case.id, case_name),
            description=f"**Moderator**: {moderator.mention} (`{moderator.id}`)\n"
            f"**Target**: {target.mention} (`{target.id}`)\n"
            f"{f'**Expires**: <t:{round(case.expires_at.timestamp())}:R>{nl}' if case.expires_at else ''}"
            f"**Reason**: ",
            colour=discord.Colour.greyple(),
            timestamp=case.created_at,
        )
        embed.description += textwrap.shorten(case.reason, 4069 - len(embed.description), placeholder="...")
        embed.set_author(name=moderator.name, icon_url=moderator.avatar.url)
        embed.set_footer(text=target.name, icon_url=target.avatar.url)
        return await ctx.respond(embed=embed, ephemeral=True)

    @cases_group.command(name="list")
    async def list_cases(self, ctx: discord.ApplicationContext, per_page: int = 10):
        """Lists all cases for this guild"""
        try:
            self.check_action_permissions(ctx.author, ctx.author, "moderate_members")
        except PermissionsError as e:
            return await ctx.respond(str(e), ephemeral=True)

        guild = await utils.get_guild(ctx.guild)
        cases = await Cases.objects.filter(guild=guild).order_by("-id").all()
        if not cases:
            return await ctx.respond("No cases found.", ephemeral=True)
        else:
            paginator = commands.Paginator("", "", max_size=4069)
            fmt = "{0!s}: {1!s} | `{2!s}` | <t:{3}>"
            for chunk in utils.chunk(cases, per_page):
                paginator.add_line(f"{len(chunk)} entries:", empty=True)
                for case in chunk:
                    paginator.add_line(
                        fmt.format(
                            case.id,
                            utils.case_type_names[case.type.value].title(),
                            self.bot.get_user(case.target) or case.target,
                            round(case.created_at.timestamp()),
                        )
                    )
                paginator.close_page()

            made_pages = paginator.pages

            def get_page(n: int, desc: str) -> discord.Embed:
                percent = round(n / len(made_pages) * 100)
                return discord.Embed(
                    title="Cases | Page #{!s}".format(n),
                    description=desc,
                    colour=discord.Colour.blue(),
                    timestamp=discord.utils.utcnow(),
                ).set_footer(text=f"{percent}% ({n}/{len(made_pages)} pages)")

            paginator = pages.Paginator([get_page(*args) for args in enumerate(made_pages, 1)], timeout=300)
            return await paginator.send(ctx, ephemeral=True)


def setup(bot):
    bot.add_cog(Moderation(bot))
