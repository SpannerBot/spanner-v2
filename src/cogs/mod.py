import discord
from discord.ext import commands
from src.database import Cases, CaseType
from src.views import YesNoPrompt


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.slash_command(name="hackban")
    async def hackban(self, ctx: discord.ApplicationContext, user_id: str, *, reason: str = "No Reason Provided"):
        """Bans a user by their ID before they can enter the server."""
        if not ctx.author.guild_permissions.ban_members or not ctx.guild.me.guild_permissions.ban_members:
            return await ctx.respond("You do not have the permissions to ban members.", ephemeral=True)
        try:
            user = await commands.UserConverter().convert(ctx, user_id)
        except commands.UserNotFound:
            return await ctx.respond("User not found.", ephemeral=True)
        else:
            view = YesNoPrompt(timeout=300.0)
            await ctx.respond(
                embed=discord.Embed(
                    title="Are you sure you want to hackban {!s}?".format(user),
                    colour=discord.Colour.orange()
                ),
                ephemeral=True
            )
            await view.wait()
            if not view.confirm:
                return await ctx.respond("Hackban cancelled.", ephemeral=True)
            try:
                await ctx.guild.ban(user, reason=reason, delete_message_days=7)
            except discord.HTTPException as e:
                return await ctx.respond("Failed to ban user: {!s}".format(e), ephemeral=True)
            else:
                return await ctx.respond("User {!s} has been banned.".format(user), ephemeral=True)


def setup(bot):
    bot.add_cog(Moderation(bot))
