from discord.ext import commands


class MemberMock:
    def __init__(self, username: str):
        pass


class WelcomeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
