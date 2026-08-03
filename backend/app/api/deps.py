from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.utils.security import decode_token, token_is_current


def current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")

    token = authorization.split(" ", 1)[1].strip()
    user_id = decode_token(token)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User no longer exists")

    # The signature only proves the token was minted by us, not that it's still
    # current. This is what makes a password change actually end other sessions.
    # No extra query: the user row is already loaded above.
    if not token_is_current(token, user.password_hash):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "This session ended because the password changed"
        )
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    """Gate for /admin/*. Being logged in is not being an admin.

    Without this, any signed-up user could read the global event log and stats —
    including other users' channel names and pipeline errors.
    """
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required")
    return user
