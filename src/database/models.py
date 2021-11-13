import orm
import databases

models = orm.ModelRegistry(database=databases.Database("sqlite:///main.db"))


class Guild(orm.Model):
    tablename = "guilds"
    registry = models
    fields = {
        "id": orm.BigInteger(primary_key=True, index=True),
        "prefix": orm.String(min_length=1, max_length=16, default="s!"),
        "log_channel": orm.BigInteger(default=None)
    }


class WelcomeMessage(orm.Model):
    tablename = "welcome_messages"
    registry = models
    fields = {
        "id": orm.BigInteger(primary_key=True, index=True),  # guild_id
        "guild": orm.ForeignKey(Guild),
        "message": orm.String(min_length=1, max_length=4029, default=None),
        "embed_data": orm.JSON(default={"type": "auto"}),
        "ignore_bots": orm.Boolean(default=False),
        "delete_after": orm.Integer(default=None)
    }


class ReactionRoles(orm.Model):
    tablename = "reaction_roles"
    registry = models
    fields = {
        "id": orm.BigInteger(primary_key=True, index=True),  # guild_id
        "guild": orm.ForeignKey(Guild),
        "message_id": orm.BigInteger(),
        "emoji": orm.String(min_length=1, max_length=16),
        "role": orm.BigInteger(default=None)
    }
