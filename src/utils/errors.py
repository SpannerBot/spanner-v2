from discord.ext import commands


__all__ = "PermissionsError",


class PermissionsError(commands.CommandError):
    def __init__(self, *, reason: str):
        self.reason = reason

    def __str__(self):
        return self.reason
