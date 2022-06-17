import datetime
import re
import textwrap
from typing import Optional, List

import discord
from discord import SlashCommandGroup
from discord.ext import commands, pages

from src.database import Cases, CaseType, Guild, NoMatch
from src.utils import utils
from src.utils.views import YesNoPrompt


class PermissionsError(commands.CommandError):
    def __init__(self, *, reason: str):
        self.reason = reason

    def __str__(self):
        return self.reason


async def case_id_autocomplete(ctx: discord.AutocompleteContext):
    if not ctx.interaction.guild_id:
        return
    cases: List[Cases] = await Cases.objects.filter(guild__id=ctx.interaction.guild_id).limit(20).order_by("-id").all()
    return [f"(#{case.id}) {str(case.entry_id).upper()}" for case in cases]


class Moderation(commands.Cog):
    case_identifier_regex = re.compile(
        r"Case#[a-fA-F\d]{8}-[a-fA-F\d]{4}-[a-fA-F\d]{4}-[a-fA-F\d]{4}-[a-fA-F\d]{12}\|\s"
    )

    def __init__(self, bot):
        self.bot = bot

    @staticmethod
    async def get_next_case_id(guild: Guild) -> int:
        last_case = await Cases.objects.filter(guild=guild).order_by("-id").limit(2).first()
        if not last_case:
            return 1
        return last_case.id + 1

    @staticmethod
    @discord.utils.deprecated("commands.[bot]_has_permissions and check_hierarchy")
    def check_action_permissions(
        author: discord.Member, target: discord.Member, permission_name: str, *, allow_self: bool = True
    ) -> bool:
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
        return True

    @staticmethod
    def check_hierarchy(
        subject: discord.Member,
        target: discord.Member,
        cannot_be_equal: bool = False,
        ignore_if_subject_is_owner: bool = True,
    ) -> bool:
        """
        Checks role hierarchy is in-tact.

        :param subject: The person who must have the higher role, usually the author.
        :param target: The person who we are comparing roles with; Usually the command target.
        :param cannot_be_equal: If True, this means that the roles cannot be of the same level; subject > target.
        :param ignore_if_subject_is_owner: If True
        :return: ``True`` if the correct conditions are met.
        """
        if ignore_if_subject_is_owner and subject.guild.owner_id == subject.id:
            return True

        if cannot_be_equal:
            comparison = subject.top_role.__gt__
        else:
            comparison = subject.top_role.__ge__

        return comparison(target.top_role)

    def get_log_channel(self, guild: Guild) -> Optional[discord.TextChannel]:
        log_channel_id = guild.log_channel
        if log_channel_id is not None:
            log_channel: Optional[discord.TextChannel] = self.bot.get_channel(log_channel_id)
            if log_channel is not None:
                if log_channel.can_send(discord.Embed):
                    return log_channel

    @staticmethod
    def generate_case_log_embed(ctx: discord.ApplicationContext, case: Cases) -> discord.Embed:
        embed = discord.Embed(
            title=f"Case #{case.id} - {case.type.name.replace('_', '-').title()}",
            description=f"**Moderator**: <@{case.moderator}> (`{case.moderator}`)\n"
            f"**Target**: <@{case.target}> (`{case.target}`)\n"
            f"**Created**: {discord.utils.format_dt(discord.utils.utcnow(), 'R')}\n"
            f"**Type**: {case.type.name.replace('_', '-').lower()}",
            colour=discord.Colour.blurple(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_author(name=ctx.author, icon_url=(ctx.author.avatar or ctx.author.default_avatar).url)

        if case.expire_at:
            embed.description += f"\n**Expires:** {discord.utils.format_dt(case.expire_at, 'R')}"

        paginator = commands.Paginator("", "", 1024)
        for line in case.reason.splitlines():
            paginator.add_line(textwrap.shorten(line, 1024, placeholder="..."))

        if paginator.pages:
            embed.add_field(name="Reason:", value=paginator.pages[0], inline=False)
            if len(paginator.pages) != 1:
                for page in paginator.pages[1:]:
                    embed.add_field(name="\u200b", value=page, inline=False)

        return embed

    async def log_event(self, guild: Guild, *, embed: discord.Embed):
        log_channel = self.get_log_channel(guild)
        if log_channel:
            return await log_channel.send(embed=embed)

    async def log_case(self, ctx: discord.ApplicationContext, case: Cases):
        """Sends a case to the log channel of the current server."""
        await case.guild.load()
        embed = self.generate_case_log_embed(ctx, case)
        log_channel = self.get_log_channel(case.guild)
        if log_channel is not None:
            await log_channel.send(embed=embed)

    @commands.slash_command(name="warn")
    @discord.default_permissions(moderate_members=True)
    @commands.bot_has_permissions(send_messages=True)
    async def warn(
        self,
        ctx: discord.ApplicationContext,
        member: discord.Option(discord.Member, description="The member you want to warn."),
        *,
        reason: discord.Option(str, description="The reason for the warning.", default="No Reason Provided."),
    ):
        """Sends a member a warning and adds it to their log."""
        if ctx.author == member:
            return await ctx.respond("You can't warn yourself, dumbass.", ephemeral=True)
        elif self.check_hierarchy(ctx.author, member) is False:
            return await ctx.respond(f"You must have a higher role than {member.mention}'s.", ephemeral=True)

        await ctx.defer(ephemeral=True)

        guild = await utils.get_guild_config(ctx.guild)
        case = await Cases.objects.create(
            id=await self.get_next_case_id(guild),
            guild=guild,
            moderator=ctx.user.id,
            target=member.id,
            reason=reason,
            type=CaseType.WARN,
        )

        embed = discord.Embed(
            title="You have been warned in %s." % ctx.guild,
            description="The reason was:\n>>> %s" % reason,
            colour=discord.Colour.dark_red(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_footer(text=str(ctx.guild), icon_url=ctx.guild.icon.url if ctx.guild.icon else None)
        embed.add_field(
            name="Think this is incorrect?", value=f"Your case ID is `{case.id}` - you can speak to a moderator."
        )

        await self.log_case(ctx, case)

        try:
            await member.send(embed=embed)
        except discord.Forbidden:
            embed.set_footer(text=embed.footer.text + f" | Please enable DMs, {member.name}.")
            await ctx.send(member.mention, embed=embed)
            content = f"Logged a warning for {member.mention}. Case {case.id}."
        else:
            content = f"Warned {member.mention}. Case {case.id}."

        return await ctx.respond(content, ephemeral=True)

    @commands.slash_command(name="hackban")
    @discord.default_permissions(ban_members=True)
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def hackban(
        self,
        ctx: discord.ApplicationContext,
        user: discord.Option(discord.User, description="The user to ban. You should provide their ID."),
        reason: discord.Option(str, description="The reason for the ban.", default="No Reason Provided."),
    ):
        """Bans a user by their ID before they can enter the server."""
        if member := await discord.utils.get_or_fetch(ctx.guild, "member", user.id, default=None):
            return await self.ban(ctx, member, 7, reason)

        view = YesNoPrompt(ctx.interaction, timeout=300.0)
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
            moderator=ctx.user.id,
            target=user.id,
            reason=reason,
            type=CaseType.BAN,
        )

        await self.log_case(ctx, case)

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
    @discord.default_permissions(ban_members=True)
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def unban(
        self,
        ctx: discord.ApplicationContext,
        user: discord.Option(discord.User, description="The user to unban. You should pass their user ID."),
        *,
        reason: discord.Option(str, description="The reason for the unban.", default="No Reason Provided."),
    ):
        """Unbans a user."""
        try:
            ban = await ctx.guild.fetch_ban(discord.Object(id=user.id))
        except discord.NotFound:
            return await ctx.respond("User is not banned.", ephemeral=True)
        else:
            guild = await utils.get_guild_config(ctx.guild)
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
            view = YesNoPrompt(ctx.interaction, timeout=300.0)
            await ctx.respond(embed=embed, view=view, ephemeral=True)
            await view.wait()
            if not view.confirm:
                return await ctx.edit(content="Did not unban %s." % ban.user, embed=None, view=None)
            else:
                case = await Cases.objects.create(
                    id=await self.get_next_case_id(guild),
                    guild=guild,
                    moderator=ctx.user.id,
                    target=ban.user.id,
                    reason=reason,
                    type=CaseType.UN_BAN,
                )
                await self.log_case(ctx, case)
                await ctx.guild.unban(ban.user, reason=f"Case#{case.entry_id}| " + reason)
                return await ctx.edit(
                    content="User {!s} has been unbanned.\nCase ID: {!s}".format(user, case.id),
                    embed=None,
                    view=None,
                )

    @commands.slash_command(name="ban")
    @discord.default_permissions(ban_members=True)
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def ban(
        self,
        ctx: discord.ApplicationContext,
        member: discord.Option(discord.Member, description="The member you want to ban."),
        delete_messages: discord.Option(
            int,
            description="How many days of their recent messages to delete",
            default=7,
            min_value=0,
            max_value=7,
            autocomplete=discord.utils.basic_autocomplete([0, 1, 2, 3, 4, 5, 6, 7]),
        ),
        reason: discord.Option(str, description="The reason for the ban.", default="No Reason Provided."),
    ):
        """Bans a member from the server."""
        if not self.check_hierarchy(ctx.author, member, cannot_be_equal=True):
            return await ctx.respond(f"You must have a higher role than {member.mention} to ban them.")
        try:
            await ctx.guild.fetch_ban(member)
            return await ctx.respond("User is already banned.", ephemeral=True)
        except discord.NotFound:
            view = YesNoPrompt(ctx.interaction, timeout=300.0)
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
                moderator=ctx.user.id,
                target=member.id,
                reason=reason,
                type=CaseType.BAN,
            )

            await self.log_case(ctx, case)

            try:
                await member.ban(reason=f"Case#{case.entry_id!s}| " + reason, delete_message_days=delete_messages)
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
    @discord.default_permissions(kick_members=True)
    @commands.has_permissions(kick_members=True)
    @commands.bot_has_permissions(kick_members=True)
    async def kick(
        self,
        ctx: discord.ApplicationContext,
        member: discord.Option(discord.Member, description="The member you want to kick."),
        *,
        reason: discord.Option(str, description="The reason for the ban.", default="No Reason Provided."),
    ):
        if not self.check_hierarchy(ctx.author, member, cannot_be_equal=True):
            return await ctx.respond(f"You must have a higher role than {member.mention} to kick them.")

        view = YesNoPrompt(ctx.interaction, timeout=300.0)
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
            moderator=ctx.user.id,
            target=member.id,
            reason=reason,
            type=CaseType.KICK,
        )

        try:
            await member.kick(reason=f"Case#{case.entry_id!s}| " + reason)
        except discord.HTTPException as e:
            await case.delete()
            return await ctx.edit(content="Failed to kick user: {!s}".format(e), embed=None)
        except Exception:
            await case.delete()
            raise
        else:
            await self.log_case(ctx, case)
            return await ctx.edit(
                content="User {!s} has been kicked.\nCase ID: {!s}".format(member, case.id), embed=None, view=None
            )

    @commands.slash_command(name="mute")
    @discord.default_permissions(moderate_members=True)
    async def mute(
        self,
        ctx: discord.ApplicationContext,
        member: discord.Option(discord.Member, description="The member you want to kick."),
        time: discord.Option(
            str, description="How long to mute this member for. Example: `1h30m` (1 hour and 30 minutes).", name="for"
        ),
        reason: discord.Option(str, description="The reason for the ban.", default="No Reason Provided."),
    ):
        """Mutes (time-outs) a user for the specified period of time."""
        if not self.check_hierarchy(ctx.author, member, cannot_be_equal=True):
            return await ctx.respond(f"You must have a higher role than {member.mention} to kick them.")

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

        view = YesNoPrompt(ctx.interaction, timeout=300.0)
        await ctx.respond(
            f"Are you sure you want to mute {member} until <t:{round(end.timestamp())}>?", ephemeral=True, view=view
        )
        await view.wait()
        if not view.confirm:
            await ctx.edit(content="Mute cancelled.", embed=None, view=None)
            return
        await ctx.edit(view=None)

        guild = await utils.get_guild_config(ctx.guild)
        case = await Cases.objects.create(
            id=await self.get_next_case_id(guild),
            guild=guild,
            moderator=ctx.user.id,
            target=member.id,
            reason=reason,
            type=CaseType.TEMP_MUTE,
            expire_at=end,
        )
        await self.log_case(ctx, case)

        try:
            end = discord.utils.utcnow() + datetime.timedelta(seconds=seconds)  # recalculate
            await member.timeout(until=end, reason=f"Case#{case.entry_id!s}| " + reason)
        except discord.HTTPException as e:
            await case.delete()
            return await ctx.edit(content="Failed to unmute user: {!s}".format(e), embed=None)
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
    @discord.default_permissions(moderate_members=True)
    async def unmute(
        self,
        ctx: discord.ApplicationContext,
        member: discord.Option(discord.Member, description="The member you want to unmute."),
        reason: discord.Option(str, description="The reason for the ban.", default="No Reason Provided."),
    ):
        if not self.check_hierarchy(ctx.author, member):
            return await ctx.respond(f"You must have a higher role than or equal to {member.mention} to kick them.")

        end = member.communication_disabled_until

        view = YesNoPrompt(ctx.interaction, timeout=300.0)
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

        guild = await utils.get_guild_config(ctx.guild)
        case = await Cases.objects.create(
            id=await self.get_next_case_id(guild),
            guild=guild,
            moderator=ctx.user.id,
            target=member.id,
            reason=reason,
            type=CaseType.UN_MUTE,
        )
        await self.log_case(ctx, case)

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

    cases_group = SlashCommandGroup(
        "cases", "Case management", default_member_permissions=discord.Permissions(moderate_members=True)
    )

    @cases_group.command(name="delete")
    async def delete_case(
        self,
        ctx: discord.ApplicationContext,
        case_id: discord.Option(
            str,
            description="The case ID you want to delete",
            autocomplete=discord.utils.basic_autocomplete(case_id_autocomplete),
        ),
    ):
        """Deletes a case from records."""
        await ctx.defer(ephemeral=True)
        case_id = re.match(r"\(#(\d+)\)", case_id).group(1)
        guild = await utils.get_guild_config(ctx.guild)
        try:
            case: Cases = await Cases.objects.get(id=case_id, guild=guild)
        except NoMatch:
            return await ctx.respond("Case not found.", ephemeral=True)

        if case.moderator != ctx.author.id:
            if not ctx.author.guild_permissions.administrator:
                return await ctx.respond("You must be an administrator to manage other people's cases.", ephemeral=True)

        view = YesNoPrompt(ctx.interaction, timeout=300.0)
        await ctx.respond("Are you sure you would like to delete case #{!s}?".format(case.entry_id), view=view)
        await view.wait()
        if not view.confirm:
            return await ctx.edit(content="Case deletion cancelled.", view=None)
        await case.delete()
        await self.log_event(
            guild,
            embed=discord.Embed(
                title=f"\N{WASTEBASKET}\U0000fe0f"
                f"{ctx.author} deleted case #{case.id} ({case.type.name.replace('_', '-').title()}) by "
                f"{await self.bot.get_or_fetch_user(case.moderator)}.",
                colour=discord.Colour.red(),
                timestamp=discord.utils.utcnow(),
            ),
        )
        return await ctx.edit(content="Deleted case #{!s}.".format(case.entry_id), view=None)

    @cases_group.command(name="view")
    async def get_case(
        self,
        ctx: discord.ApplicationContext,
        case_id: discord.Option(
            str,
            description="The case ID you want to view.",
            autocomplete=discord.utils.basic_autocomplete(case_id_autocomplete),
        ),
    ):
        """Displays details on a provided case."""
        await ctx.defer(ephemeral=True)
        case_id = re.match(r"\(#(\d+)\)", case_id).group(1)
        guild = await utils.get_guild_config(ctx.guild)
        try:
            case: Cases = await Cases.objects.get(id=case_id, guild=guild)
        except NoMatch:
            return await ctx.respond("Case not found.", ephemeral=True)

        moderator = await self.bot.get_or_fetch_user(case.moderator)
        target = await self.bot.get_or_fetch_user(case.target)
        case_name = utils.case_type_names[case.type.value].title()
        nl = "\n"

        embed = discord.Embed(
            title="Case #{!s}: {!s}".format(case.id, case_name),
            description=f"**Moderator**: {moderator.mention} (`{moderator.id}`)\n"
            f"**Target**: {target.mention} (`{target.id}`)\n"
            f"{f'**Expires**: {discord.utils.format_dt(case.expire_at)}{nl}' if case.expire_at else ''}"
            f"**Reason**: ",
            colour=discord.Colour.greyple(),
            timestamp=case.created_at,
        )
        embed.description += textwrap.shorten(case.reason, 4069 - len(embed.description), placeholder="...")
        embed.set_author(name=moderator.name, icon_url=moderator.avatar.url)
        embed.set_footer(text=target.name, icon_url=target.avatar.url)
        return await ctx.respond(embed=embed, ephemeral=True)

    @cases_group.command(name="edit")
    async def edit_case(
        self,
        ctx: discord.ApplicationContext,
        case_id: discord.Option(
            str,
            description="The case ID you want to edit.",
            autocomplete=discord.utils.basic_autocomplete(case_id_autocomplete),
        ),
        new_reason: discord.Option(
            str,
            description="The new reason for this case.",
            required=False,
            default=...,
        ),
    ):
        """Edits the details of a case."""
        await ctx.defer(ephemeral=True)
        case_id = re.match(r"\(#(\d+)\)", case_id).group(1)
        guild = await utils.get_guild_config(ctx.guild)
        try:
            case: Cases = await Cases.objects.get(id=case_id, guild=guild)
        except NoMatch:
            return await ctx.respond("Case not found.", ephemeral=True)

        if case.moderator != ctx.author.id:
            if not ctx.author.guild_permissions.administrator:
                return await ctx.respond("You must be an administrator to manage other people's cases.", ephemeral=True)

        changes = []

        if new_reason is not ...:
            await case.update(reason=new_reason)
            changes.append("reason")

        if len(changes) != 0:
            await self.log_event(
                guild,
                embed=discord.Embed(
                    title=f"\N{MEMO}"
                    f"{ctx.author} edited case #{case.id} ({case.type.name.replace('_', '-').title()}) by "
                    f"{await self.bot.get_or_fetch_user(case.moderator)}.",
                    description=f"Changes: {', '.join(changes)}",
                    colour=discord.Colour.orange(),
                    timestamp=discord.utils.utcnow(),
                ),
            )
            return await ctx.respond("\N{white heavy check mark} Changes saved.", ephemeral=True)

    cases_list = cases_group.create_subgroup("list", "List cases matching a criteria")

    @cases_list.command(name="all")
    async def list_cases(
        self,
        ctx: discord.ApplicationContext,
        per_page: discord.Option(
            int, description="The number of cases to show per page.", default=10, min_value=1, max_value=25
        ),
    ):
        """Lists all cases for this guild"""
        try:
            self.check_action_permissions(ctx.user, ctx.user, "moderate_members")
        except PermissionsError as e:
            return await ctx.respond(str(e), ephemeral=True)

        guild = await utils.get_guild_config(ctx.guild)
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

            paginator = pages.Paginator(
                [get_page(*args) for args in enumerate(made_pages, 1)], timeout=300, loop_pages=True
            )
            return await paginator.respond(
                ctx.interaction,
                ephemeral=True,
            )

    @cases_list.command(name="user")
    async def list_cases_for(
        self,
        ctx: discord.ApplicationContext,
        user: discord.User,
        per_page: discord.Option(
            int, description="How many cases to show per page", max_value=25, min_value=1, default=10
        ),
    ):
        """Lists all cases for a specific member in this guild. You must provide their ID if they left."""
        try:
            self.check_action_permissions(ctx.user, ctx.user, "moderate_members")
        except PermissionsError as e:
            return await ctx.respond(str(e), ephemeral=True)

        guild = await utils.get_guild_config(ctx.guild)
        cases = await Cases.objects.filter(guild=guild, target=user.id).order_by("-id").all()
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

            paginator = pages.Paginator(
                [get_page(*args) for args in enumerate(made_pages, 1)], timeout=300, loop_pages=True
            )
            return await paginator.respond(
                ctx.interaction,
                ephemeral=True,
            )


def setup(bot):
    bot.add_cog(Moderation(bot))
