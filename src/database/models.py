import enum
import uuid
from datetime import datetime, timezone
from pathlib import Path

import databases
import discord.utils
import orm

__all__ = ("CaseType", "Guild", "WelcomeMessage", "ReactionRoles", "Cases", "Errors", "CommandType", "DB_STAT")

models = orm.ModelRegistry(database=databases.Database("sqlite:///main.db"))
DB_STAT = None


class CaseType(enum.IntEnum):
    WARN = 0
    MUTE = 1
    TEMP_MUTE = 2
    KICK = 3
    BAN = 4
    TEMP_BAN = 5
    UN_MUTE = 6
    UN_BAN = 7
    SOFT_BAN = 8


class CommandType(enum.Enum):
    TEXT = "text"
    SLASH = "slash"
    USER = "user context"
    MESSAGE = "message context"


class Guild(orm.Model):
    tablename = "guilds"
    registry = models
    fields = {
        "entry_id": orm.UUID(primary_key=True, default=uuid.uuid4()),
        "id": orm.BigInteger(unique=True, index=True),
        "prefix": orm.String(min_length=1, max_length=16, default="s!"),
        "log_channel": orm.BigInteger(allow_null=True, default=None),
    }


class WelcomeMessage(orm.Model):
    tablename = "welcome_messages"
    registry = models
    fields = {
        "entry_id": orm.UUID(primary_key=True, default=uuid.uuid4()),
        "id": orm.BigInteger(unique=True, index=True),  # guild_id
        "guild": orm.ForeignKey(Guild),
        "message": orm.String(min_length=1, max_length=4029, default=None),
        "embed_data": orm.JSON(default={"type": "auto"}),
        "ignore_bots": orm.Boolean(default=False),
        "delete_after": orm.Integer(default=None),
    }


class ReactionRoles(orm.Model):
    tablename = "reaction_roles"
    registry = models
    fields = {
        "entry_id": orm.UUID(primary_key=True, default=uuid.uuid4()),
        "id": orm.BigInteger(unique=True, index=True),  # guild_id
        "guild": orm.ForeignKey(Guild),
        "message_id": orm.BigInteger(),
        "emoji": orm.String(min_length=1, max_length=16),
        "role": orm.BigInteger(default=None),
    }


class Cases(orm.Model):
    registry = models
    fields = dict(
        entry_id=orm.UUID(primary_key=True, default=uuid.uuid4),
        id=orm.Integer(allow_null=False, default=None),
        guild=orm.ForeignKey(Guild),
        moderator=orm.BigInteger(),
        target=orm.BigInteger(),
        reason=orm.String(min_length=1, max_length=4000),
        created_at=orm.DateTime(allow_null=False, default=discord.utils.utcnow),
        type=orm.Enum(CaseType, default=CaseType.WARN),
        expire_at=orm.DateTime(allow_null=True, default=None),
    )


class Errors(orm.Model):
    registry = models

    @staticmethod
    def calculate_next_case_id():
        now = discord.utils.utcnow()

        global DB_STAT
        if DB_STAT is None:
            DB_STAT = datetime.fromtimestamp((Path.cwd() / "main.db").stat().st_ctime, timezone.utc)

        return round(now.timestamp()) - round(DB_STAT.timestamp())

    fields = dict(
        id=orm.Integer(primary_key=True, default=lambda: round(discord.utils.utcnow().timestamp()) - 1646065759),
        traceback_text=orm.Text(),
        author=orm.BigInteger(),
        guild=orm.BigInteger(allow_null=True),
        channel=orm.BigInteger(allow_null=True),
        command=orm.Text(),
        command_type=orm.Enum(CommandType),
        permissions_channel=orm.BigInteger(),
        permissions_guild=orm.BigInteger(),
        full_message=orm.String(min_length=2, max_length=4000, allow_null=True),
    )
