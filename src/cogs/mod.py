import textwrap
import uuid

import discord
from discord.ext import commands

from src import utils
from src.database import Cases, CaseType, Guild, NoMatch
from src.views import YesNoPrompt


class PermissionsError(commands.CommandError):
    def __init__(self, *, reason: str):
        self.reason = reason

    def __str__(self):
        return self.reason


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @staticmethod
    async def get_next_case_id(guild: Guild) -> int:
        last_case = await Cases.objects.filter(guild=guild).order_by("-id").first()
        if not last_case:
            return 1
        return last_case.id + 1

    @staticmethod
    def check_action_permissions(author: discord.Member, target: discord.Member, permission_name: str) -> bool:
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
                raise PermissionsError(
                    reason="You cannot perform actions on users with a higher or equal role than you."
                )
            # Step 2.2: Check if the bot is higher than the target.
            if target.top_role <= author.guild.me.top_role:
                raise PermissionsError(
                    reason="You cannot perform actions on users with a higher or equal role than me."
                )
            # Step 2.3: Check if the author has the required permissions.
            if getattr(author.guild_permissions, permission_name) is False:
                raise PermissionsError(reason="You do not have the required permissions to perform this action.")
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
                ban_reason = textwrap.shorten(ban.reason, width=1024, placeholder="...") if ban.reason else None
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
            self.check_action_permissions(ctx.author, member, "ban_members")
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
            self.check_action_permissions(ctx.author, member, "kick_members")
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

    @commands.slash_command(name="get-case")
    async def get_case(self, ctx: discord.ApplicationContext, case_id: str):
        try:
            self.check_action_permissions(ctx.author, ctx.author, "manage_guild")
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
            timestamp=case.created_at
        )
        embed.description += textwrap.shorten(case.reason, 4069-len(embed.description), placeholder="...")
        embed.set_author(name=moderator.name, icon_url=moderator.avatar.url)
        embed.set_footer(text=target.name, icon_url=target.avatar.url)
        return await ctx.respond(embed=embed, ephemeral=True)


def setup(bot):
    bot.add_cog(Moderation(bot))
