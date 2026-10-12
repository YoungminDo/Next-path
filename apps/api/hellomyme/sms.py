"""Sending a verification code by SMS, behind one small interface so the provider is config.

Nothing here logs a phone number; the development "log" sender writes only the last four digits
next to the code.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import UTC, datetime
from typing import Protocol

import httpx

from hellomyme.config import Settings

log = logging.getLogger(__name__)


class SmsUnavailable(Exception):
    pass


class SmsSender(Protocol):
    def send(self, phone_e164: str, text: str) -> None: ...


def _national(phone_e164: str) -> str:
    """+821012345678 -> 01012345678 (Korean providers take the national form)."""
    return "0" + phone_e164[3:] if phone_e164.startswith("+82") else phone_e164


class LogSender:
    """Development only (refused in production): the message goes to the server log."""

    def send(self, phone_e164: str, text: str) -> None:
        log.warning("SMS (not sent, log provider) to ***%s: %s", phone_e164[-4:], text)


class SolapiSender:
    """Solapi messages v4, HMAC-SHA256 auth: signature = HMAC(secret, date + salt)
    (https://solapi.com/developers/api/authentication-api-key)."""

    URL = "https://api.solapi.com/messages/v4/send"

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.key = settings.solapi_api_key.get_secret_value()
        self.secret = settings.solapi_api_secret.get_secret_value()
        self.sender = settings.sms_sender_number
        self.client = client or httpx.Client(timeout=10)

    def _auth(self) -> str:
        date = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
        salt = secrets.token_hex(16)
        sig = hmac.new(self.secret.encode(), (date + salt).encode(), hashlib.sha256).hexdigest()
        return f"HMAC-SHA256 apiKey={self.key}, date={date}, salt={salt}, signature={sig}"

    def send(self, phone_e164: str, text: str) -> None:
        body = {"message": {"to": _national(phone_e164), "from": self.sender, "text": text}}
        try:
            r = self.client.post(self.URL, json=body, headers={"Authorization": self._auth()})
        except httpx.HTTPError as exc:
            raise SmsUnavailable("sms provider unreachable") from exc
        if r.status_code >= 300:
            # The provider's error code only; the body can echo the recipient.
            log.error("solapi send failed: HTTP %s", r.status_code)
            raise SmsUnavailable(f"sms provider refused ({r.status_code})")


_SENDERS: dict[tuple, SmsSender] = {}


def get_sender(settings: Settings) -> SmsSender | None:
    """None: no provider configured, numbers are kept without an SMS check. One sender (and one
    HTTP client) per configuration, reused across requests."""
    if settings.sms_provider == "none":
        return None
    key = (settings.sms_provider, settings.solapi_api_key and settings.solapi_api_key.get_secret_value(),
           settings.sms_sender_number)
    if key not in _SENDERS:
        _SENDERS[key] = SolapiSender(settings) if settings.sms_provider == "solapi" else LogSender()
    return _SENDERS[key]
