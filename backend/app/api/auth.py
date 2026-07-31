from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.config import settings
from app.db import get_db
from app.models import User
from app.schemas import LoginRequest, MessageResponse, SignupRequest, TokenResponse, UserOut
from app.services.email import EmailError, send_verification_email
from app.utils.email_validation import validate_signup_email
from app.utils.logging import logger
from app.utils.security import create_token, create_verify_token, decode_verify_token, hash_password, verify_password
from app.utils.time import utcnow

router = APIRouter(prefix="/auth", tags=["auth"])

# Re-requesting a verification email more often than this just burns Brevo's
# free-tier quota for no benefit — the previous link is still valid.
_RESEND_COOLDOWN = timedelta(seconds=60)


def _send_verification(user: User, db: Session) -> None:
    token = create_verify_token(user.id)
    try:
        send_verification_email(user.email, token)
    except EmailError as exc:
        # Don't fail signup/resend over an email provider hiccup — the user
        # can always hit resend, and this is visible in logs either way.
        logger.warning("verification email to %s failed: %s", user.email, exc)
    user.verification_sent_at = utcnow()
    db.add(user)
    db.commit()


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: SignupRequest, db: Session = Depends(get_db)) -> TokenResponse:
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with that email already exists")

    rejection = validate_signup_email(email)
    if rejection:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, rejection)

    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        niche=payload.niche,
        is_admin=email in settings.admin_emails,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    _send_verification(user, db)

    # Signup always returns a session, even in hard-gate mode (Settings.
    # require_email_verification) — the gate applies to *future* logins
    # (see login() below), not to the initial signup, so an unverified user
    # isn't locked out of the app the moment they create their account.
    return TokenResponse(access_token=create_token(user.id))


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    if settings.require_email_verification and not user.is_verified:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Please verify your email before logging in")
    return TokenResponse(access_token=create_token(user.id))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> User:
    return user


@router.get("/verify", response_model=MessageResponse)
def verify_email(token: str, db: Session = Depends(get_db)) -> MessageResponse:
    user_id = decode_verify_token(token)
    if user_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This verification link is invalid or has expired")

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account no longer exists")

    if not user.is_verified:
        user.is_verified = True
        db.add(user)
        db.commit()
    return MessageResponse(message="Email verified")


@router.post("/resend-verification", response_model=MessageResponse)
def resend_verification(user: User = Depends(current_user), db: Session = Depends(get_db)) -> MessageResponse:
    if user.is_verified:
        return MessageResponse(message="Already verified")

    if user.verification_sent_at and utcnow() - user.verification_sent_at < _RESEND_COOLDOWN:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Please wait a moment before requesting another email")

    _send_verification(user, db)
    return MessageResponse(message="Verification email sent")
