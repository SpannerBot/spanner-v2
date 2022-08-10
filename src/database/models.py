import datetime
import enum
import uuid
from typing import TYPE_CHECKING, Optional

import databases
import discord.utils
import orm

__all__ = (
    "CaseType",
    "Guild",
    "WelcomeMessage",
    "ReactionRoles",
    "Cases",
    "Errors",
    "CommandType",
    "DB_STAT",
)

models = orm.ModelRegistry(databases.Database("sqlite:///main.db"))
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
    UNKNOWN = "unknown"
    TEXT = "text"
    SLASH = "slash"
    USER = "user context"
    MESSAGE = "message context"
    AUTOCOMPLETE = "autocomplete"
    MODAL = "modal context"


class Guild(orm.Model):
    tablename = "guilds"
    registry = models
    fields = {
        "entry_id": orm.UUID(primary_key=True, default=uuid.uuid4),
        "id": orm.BigInteger(unique=True, index=True),
        "prefix": orm.String(min_length=1, max_length=16, default="s!"),
        "log_channel": orm.BigInteger(allow_null=True, default=None),
        "disable_snipe": orm.Boolean(default=False),
    }

    if TYPE_CHECKING:
        entry_id: uuid.UUID
        id: int
        prefix: str
        log_channel: Optional[int]
        disable_snipe: bool


class WelcomeMessage(orm.Model):
    tablename = "welcome_messages"
    registry = models
    fields = {
        "entry_id": orm.UUID(primary_key=True, default=uuid.uuid4),
        "guild": orm.ForeignKey(Guild),
        "message": orm.String(min_length=1, max_length=4029, default=None, allow_null=True),
        "embed_data": orm.JSON(default={"type": "auto"}),
        "ignore_bots": orm.Boolean(default=False),
        "delete_after": orm.Integer(default=3600 * 6),
    }

    if TYPE_CHECKING:
        entry_id: uuid.UUID
        id: int
        guild: Guild
        message: Optional[str]
        embed_data: dict
        ignore_bots: bool
        delete_after: Optional[int]


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

    if TYPE_CHECKING:
        entry_id: uuid.UUID
        id: int
        guild: Guild
        message_id: int
        emoji: str
        role: Optional[int]


class Cases(orm.Model):
    registry = models
    fields = dict(
        entry_id=orm.UUID(primary_key=True, default=uuid.uuid4),
        # new_id=orm.BigInteger(default=discord.utils.generate_snowflake, unique=True),
        id=orm.Integer(),
        guild=orm.ForeignKey(Guild),
        moderator=orm.BigInteger(),
        target=orm.BigInteger(),
        reason=orm.String(min_length=1, max_length=4000),
        created_at=orm.DateTime(allow_null=False, default=discord.utils.utcnow),
        type=orm.Enum(CaseType, default=CaseType.WARN),
        expire_at=orm.DateTime(allow_null=True, default=None),
    )

    if TYPE_CHECKING:
        entry_id: uuid.UUID
        id: int
        guild: Guild
        moderator: int
        target: int
        reason: str
        created_at: datetime.datetime
        type: CaseType
        expire_at: Optional[datetime.datetime]


class Errors(orm.Model):
    registry = models

    @staticmethod
    def calculate_next_case_id():
        return discord.utils.generate_snowflake()

    fields = dict(
        id=orm.Integer(primary_key=True, default=discord.utils.generate_snowflake),
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

    if TYPE_CHECKING:
        id: int
        traceback_text: str
        author: int
        guild: Optional[int]
        channel: Optional[int]
        command: str
        command_type: CommandType
        permissions_channel: int
        permissions_guild: int
        full_message: Optional[str]


class APIToken(orm.Model):
    registry = models
    fields = {
        "id": orm.BigInteger(primary_key=True, default=discord.utils.generate_snowflake),
        "secret": orm.Text()
    }
