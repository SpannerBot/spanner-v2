import uuid

import databases
import discord.utils
import orm
import enum

__all__ = (
    "CaseType",
    "Guild",
    "WelcomeMessage",
    "ReactionRoles",
    "Cases"
)

models = orm.ModelRegistry(database=databases.Database("sqlite:///main.db"))


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
        entry_id=orm.UUID(primary_key=True, default=uuid.uuid4()),
        id=orm.Integer(allow_null=False),
        guild=orm.ForeignKey(Guild),
        moderator=orm.BigInteger(),
        target=orm.BigInteger(),
        reason=orm.String(min_length=1, max_length=4000),
        created_at=orm.DateTime(allow_null=False, default=discord.utils.utcnow),
        type=orm.Enum(CaseType, default=CaseType.WARN),
        expire_at=orm.DateTime(allow_null=True, default=None),
    )
