"""Transactional email via Brevo (formerly Sendinblue).

Mirrors the mock-fallback pattern used by the YouTube/LLM providers
(config.using_real_youtube / using_real_llm): with no BREVO_API_KEY set, this
logs the email instead of sending it, so the app still boots and signup still
works with zero external setup. Once BREVO_API_KEY is set, real emails go out.
"""
from __future__ import annotations

import html

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


def _escape(value: object) -> str:
    """Brief content is derived from third-party video titles, so it reaches
    this template as untrusted text. The app renders it through React, which
    escapes automatically; an HTML email has no such protection, so it is
    escaped explicitly here rather than trusted because it looked fine on-screen.
    """
    return html.escape(str(value if value is not None else ""), quote=True)


def send_brief_email(to_email: str, content: dict, unsubscribe_token: str) -> None:
    """The daily brief, delivered. Only called on days that have something to say."""
    base = settings.frontend_url.rstrip("/")
    unsubscribe_url = f"{base}/unsubscribe?token={unsubscribe_token}"

    opportunities = (content or {}).get("opportunities") or []
    blocks = []
    for index, item in enumerate(opportunities[:3], start=1):
        projection = item.get("projection") or {}
        expected = projection.get("expected_views_display")
        confidence = (item.get("confidence") or {}).get("level")

        meta_bits = [f"{_escape(item.get('momentum'))}/100 momentum"]
        if expected:
            meta_bits.append(f"~{_escape(expected)} views on your channel")
        if confidence and confidence != "solid":
            meta_bits.append(f"{_escape(confidence)} confidence")

        blocks.append(
            f"""
            <div style="margin: 0 0 20px; padding: 16px; border: 1px solid #e5e5e5; border-radius: 8px;">
              <div style="font-size: 12px; color: #888; text-transform: uppercase; letter-spacing: 0.08em;">
                {index} · {" · ".join(meta_bits)}
              </div>
              <div style="margin-top: 6px; font-size: 16px; font-weight: 600; color: #111;">
                {_escape(item.get("subtopic") or item.get("topic"))}
              </div>
              <p style="margin: 8px 0 0; font-size: 14px; line-height: 1.5; color: #444;">
                {_escape(item.get("why_it_matters"))}
              </p>
              <p style="margin: 10px 0 0; font-size: 14px; color: #111;">
                &ldquo;{_escape(item.get("suggested_direction"))}&rdquo;
              </p>
            </div>
            """
        )

    html_body = f"""
    <div style="font-family: -apple-system, sans-serif; max-width: 560px; margin: 0 auto;">
      <p style="font-size: 12px; color: #888; text-transform: uppercase; letter-spacing: 0.08em;">
        Today&rsquo;s Intelligence
      </p>
      <h2 style="margin: 4px 0 20px; font-size: 18px; line-height: 1.4; color: #111;">
        {_escape((content or {}).get("headline"))}
      </h2>
      {"".join(blocks)}
      <p style="margin: 24px 0;">
        <a href="{base}/dashboard"
           style="background: #111; color: #fff; padding: 12px 20px; border-radius: 6px;
                  text-decoration: none; font-weight: 600; font-size: 14px;">
          Open the full brief
        </a>
      </p>
      <p style="color: #999; font-size: 12px; line-height: 1.5;">
        Every number here is computed from your tracked channels&rsquo; real data.<br>
        <a href="{unsubscribe_url}" style="color: #999;">Stop receiving these</a>
      </p>
    </div>
    """
    headline = (content or {}).get("headline") or "Today's intelligence"
    _send(to_email, f"Today: {headline[:80]}", html_body)


def send_password_reset_email(to_email: str, token: str) -> None:
    reset_url = f"{settings.frontend_url.rstrip('/')}/reset-password?token={token}"
    html = f"""
    <div style="font-family: -apple-system, sans-serif; max-width: 480px; margin: 0 auto;">
      <h2 style="color: #111;">Reset your password</h2>
      <p style="color: #444; line-height: 1.5;">
        We received a request to reset the password on your Content Intelligence account.
      </p>
      <p style="margin: 24px 0;">
        <a href="{reset_url}"
           style="background: #111; color: #fff; padding: 12px 20px; border-radius: 6px;
                  text-decoration: none; font-weight: 600;">
          Reset password
        </a>
      </p>
      <p style="color: #888; font-size: 12px;">
        This link expires in 1 hour. If you didn't request this, you can safely ignore this email —
        your password won't change.
      </p>
    </div>
    """
    _send(to_email, "Reset your Content Intelligence password", html)
