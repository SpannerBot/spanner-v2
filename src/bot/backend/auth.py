import secrets

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

bearer = HTTPBearer()


def is_admin(auth: HTTPAuthorizationCredentials = Depends(bearer)):
    """Ensures the user sending the request is an administrator"""
    from src.bot import bot
    empty = secrets.token_hex(32)  # lazy
    token = bot.get_config_value("admin_token", default=empty)
    if token == empty:
        raise HTTPException(
            403,
            "Administrator has not set a login token"
        )

    if secrets.compare_digest("Bearer " + token, auth.credentials) is False:
        raise HTTPException(
            401,
            "Invalid token",
            {
                "WWW-Authenticate": "Bearer"
            }
        )

    return True
