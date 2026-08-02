from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.config import settings
from app.db import get_db
from app.models import User
from app.schemas import (
    ForgotPasswordRequest,
    LoginRequest,
    MessageResponse,
    ResetPasswordRequest,
    SignupRequest,
    TokenResponse,
    UserOut,
)
from app.services.email import EmailError, send_password_reset_email, send_verification_email
from app.utils.email_validation import validate_signup_email
from app.utils.logging import logger
from app.utils.rate_limit import enforce_rate_limit
from app.utils.security import (
    _decode_signed,
    create_reset_token,
    create_token,
    create_verify_token,
    decode_reset_token,
    decode_verify_token,
    hash_password,
    verify_password,
)
from app.utils.time import utcnow

router = APIRouter(prefix="/auth", tags=["auth"])

# Re-requesting a verification email more often than this just burns Brevo's
# free-tier quota for no benefit — the previous link is still valid.
_RESEND_COOLDOWN = timedelta(seconds=60)

# Generous enough that a real person fumbling their password a few times, or
# a beta tester signing up two accounts, never notices. Tight enough to stop
# scripted spam. Per-IP, so it doesn't penalize other users behind the same
# NAT/office network beyond this window.
_SIGNUP_LIMIT = {"max_attempts": 5, "window_seconds": 600}
_LOGIN_LIMIT = {"max_attempts": 10, "window_seconds": 600}
# Same shape as signup: generous for a real person, tight enough to stop
# someone hammering the endpoint to spam another person's inbox.
_RESET_REQUEST_LIMIT = {"max_attempts": 5, "window_seconds": 600}


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
def signup(payload: SignupRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    enforce_rate_limit(request, "signup", **_SIGNUP_LIMIT)
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
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    enforce_rate_limit(request, "login", **_LOGIN_LIMIT)
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


@router.post("/forgot-password", response_model=MessageResponse)
def forgot_password(payload: ForgotPasswordRequest, request: Request, db: Session = Depends(get_db)) -> MessageResponse:
    enforce_rate_limit(request, "forgot-password", **_RESET_REQUEST_LIMIT)
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    # Always return the same message whether or not the account exists —
    # otherwise this endpoint becomes a way to check who has an account here.
    generic = MessageResponse(message="If that email has an account, a reset link is on its way")
    if user is None:
        return generic

    token = create_reset_token(user.id, user.password_hash)
    try:
        send_password_reset_email(user.email, token)
    except EmailError as exc:
        logger.warning("password reset email to %s failed: %s", user.email, exc)
    return generic


@router.post("/reset-password", response_model=MessageResponse)
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)) -> MessageResponse:
    # Decoding requires the user's *current* password hash, so we have to try
    # every candidate the token's signature could belong to — but the token
    # itself carries no plaintext email, only a signed user id once decoded.
    # Simplest correct approach: decode the outer signature first (cheap,
    # no DB hit needed) to recover the claimed user id, then verify the
    # embedded password-hash fingerprint against that specific user.
    from app.utils.security import _decode_signed  # local import: internal helper, not part of the public API

    raw = _decode_signed(payload.token)
    if raw is None or raw.get("purpose") != "reset_password":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This reset link is invalid or has expired")

    user = db.get(User, int(raw["sub"]))
    if user is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This reset link is invalid or has expired")

    user_id = decode_reset_token(payload.token, user.password_hash)
    if user_id is None or user_id != user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This reset link is invalid or has expired")

    user.password_hash = hash_password(payload.password)
    db.add(user)
    db.commit()
    return MessageResponse(message="Password updated — you can sign in now")
