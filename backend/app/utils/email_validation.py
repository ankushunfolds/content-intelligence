"""Second layer of email sanity checking, on top of pydantic's EmailStr.

EmailStr only confirms the string *looks like* an email (has an @, a
plausible domain shape). It says nothing about whether that domain can
actually receive mail, or whether it's a known throwaway-inbox service. Both
of those are cheap to check for free — no external account, no API key — and
catch the overwhelming majority of junk signups:

  - a typo'd domain ("gmial.com") has no MX record at all
  - a disposable-mail domain (mailinator.com, etc.) resolves fine but is a
    known dead end for anything you'd actually want to reach a person through

This is deliberately *not* proof the person owns the inbox — that's what the
Brevo verification email (utils/security.create_verify_token +
services/email.send_verification_email) is for. This module just stops
obviously-fake addresses before they ever reach that step.
"""
from __future__ import annotations

import socket

from app.utils.logging import logger

try:
    import dns.exception
    import dns.resolver

    _DNS_AVAILABLE = True
except ImportError:  # pragma: no cover - dnspython not installed
    _DNS_AVAILABLE = False

# Not exhaustive — there is no complete list, disposable-mail services appear
# faster than anyone can catalog them. This covers the well-known, long-lived
# ones responsible for most throwaway signups. Extend as needed.
DISPOSABLE_DOMAINS: frozenset[str] = frozenset(
    {
        "mailinator.com",
        "guerrillamail.com",
        "guerrillamail.info",
        "guerrillamail.biz",
        "guerrillamail.de",
        "guerrillamailblock.com",
        "10minutemail.com",
        "10minutemail.net",
        "temp-mail.org",
        "tempmail.com",
        "tempmail.net",
        "throwawaymail.com",
        "yopmail.com",
        "yopmail.fr",
        "yopmail.net",
        "trashmail.com",
        "getnada.com",
        "sharklasers.com",
        "dispostable.com",
        "maildrop.cc",
        "mintemail.com",
        "fakeinbox.com",
        "mailnesia.com",
        "spamgourmet.com",
        "mytemp.email",
        "moakt.com",
        "emailondeck.com",
        "mohmal.com",
        "tempinbox.com",
        "discard.email",
        "mailcatch.com",
        "spam4.me",
        "33mail.com",
        "burnermail.io",
        "inboxbear.com",
    }
)

_MX_CACHE: dict[str, bool] = {}
_MX_TIMEOUT_SECONDS = 3.0


def _domain_of(email: str) -> str:
    return email.rsplit("@", 1)[-1].strip().lower()


def is_disposable_domain(email: str) -> bool:
    return _domain_of(email) in DISPOSABLE_DOMAINS


def has_mx_record(domain: str) -> bool:
    """Best-effort check that `domain` can receive mail.

    Fails *open* (returns True) on anything that looks like our problem —
    missing dnspython, timeouts, resolver hiccups — rather than blocking a
    legitimate signup because of a flaky DNS lookup. Only a confirmed
    "this domain has no mail server" (NXDOMAIN / NoAnswer) counts as a
    rejection.
    """
    if not _DNS_AVAILABLE:
        return True

    if domain in _MX_CACHE:
        return _MX_CACHE[domain]

    result = True
    try:
        answers = dns.resolver.resolve(domain, "MX", lifetime=_MX_TIMEOUT_SECONDS)
        result = len(answers) > 0
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        # A domain with no MX might still accept mail via a bare A record
        # (rare, but valid per RFC 5321). Check that before rejecting.
        try:
            socket.getaddrinfo(domain, None)
            result = True
        except socket.gaierror:
            result = False
    except (dns.exception.Timeout, dns.resolver.NoNameservers, Exception) as exc:  # noqa: BLE001
        logger.warning("MX lookup for %s failed (%s) — allowing signup rather than blocking on DNS", domain, exc)
        result = True

    _MX_CACHE[domain] = result
    return result


def validate_signup_email(email: str) -> str | None:
    """Return a user-facing rejection reason, or None if the email is fine."""
    domain = _domain_of(email)
    if is_disposable_domain(email):
        return "Disposable email addresses aren't allowed. Please use a permanent email address."
    if not has_mx_record(domain):
        return f"The domain \"{domain}\" doesn't appear to accept email. Please check for a typo."
    return None
