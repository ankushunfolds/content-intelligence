"""Transactional email via Brevo (formerly Sendinblue).

Mirrors the mock-fallback pattern used by the YouTube/LLM providers
(config.using_real_youtube / using_real_llm): with no BREVO_API_KEY set, this
logs the email instead of sending it, so the app still boots and signup still
works with zero external setup. Once BREVO_API_KEY is set, real emails go out.
"""
from __future__ import annotations

import httpx

from app.config import settings
from app.utils.logging import logger

_BREVO_ENDPOINT = "https://api.brevo.com/v3/smtp/email"
_TIMEOUT_SECONDS = 10.0


class EmailError(Exception):
    """Raised when Brevo rejects or fails to deliver an email."""


def _send(to_email: str, subject: str, html_content: str) -> None:
    if not settings.brevo_api_key:
        logger.warning(
            "BREVO_API_KEY not set — skipping send, would have emailed %s: %s",
            to_email,
            subject,
        )
        return

    try:
        response = httpx.post(
            _BREVO_ENDPOINT,
            headers={
                "api-key": settings.brevo_api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json={
                "sender": {"name": settings.brevo_sender_name, "email": settings.brevo_sender_email},
                "to": [{"email": to_email}],
                "subject": subject,
                "htmlContent": html_content,
            },
            timeout=_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise EmailError(f"Brevo request failed: {exc}") from exc

    if response.status_code >= 400:
        raise EmailError(f"Brevo error {response.status_code}: {response.text[:300]}")


def send_verification_email(to_email: str, token: str) -> None:
    verify_url = f"{settings.frontend_url.rstrip('/')}/verify?token={token}"
    html = f"""
    <div style="font-family: -apple-system, sans-serif; max-width: 480px; margin: 0 auto;">
      <h2 style="color: #111;">Verify your email</h2>
      <p style="color: #444; line-height: 1.5;">
        Confirm this is your email address to finish setting up your
        Content Intelligence account.
      </p>
      <p style="margin: 24px 0;">
        <a href="{verify_url}"
           style="background: #111; color: #fff; padding: 12px 20px; border-radius: 6px;
                  text-decoration: none; font-weight: 600;">
          Verify email
        </a>
      </p>
      <p style="color: #888; font-size: 12px;">
        This link expires in 24 hours. If you didn't create this account, you can ignore this email.
      </p>
    </div>
    """
    _send(to_email, "Verify your Content Intelligence account", html)
