"""Login provider abstraction.

Kakao login is delegated to HMM ID (id.da-sh.io), the company identity provider: HMM ID runs
the Kakao OAuth flow and issues a `dash-access-token`; we verify that token server-side with
`GET /api/v1/auth/me` (backend-only docking, see hmm-id docs/docking-protocol.md). Google and
Apple can be added as further adapters. Provider tokens are verified and never stored.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx

from hellomyme.config import Settings


class AuthError(Exception):
    """The token was rejected: the user must sign in again."""


class AuthUnavailable(Exception):
    """The identity provider could not answer: retry later, never treat as logged in."""


@dataclass(frozen=True)
class ProviderIdentity:
    provider: str
    subject: str


class AuthProvider(Protocol):
    name: str

    def verify(self, token: str) -> ProviderIdentity: ...


class HmmIdProvider:
    name = "HMM_ID"

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.url = settings.hmm_id_base_url.rstrip("/") + "/api/v1/auth/me"
        self.client = client or httpx.Client(timeout=settings.hmm_id_timeout_seconds)

    def verify(self, token: str) -> ProviderIdentity:
        try:
            resp = self.client.get(self.url, headers={"Authorization": f"Bearer {token}",
                                                      "Cache-Control": "no-store"})
        except httpx.HTTPError as exc:
            raise AuthUnavailable("HMM ID unreachable") from exc
        if resp.status_code in (401, 403, 404):
            raise AuthError("HMM ID token rejected")
        if resp.status_code != 200:
            raise AuthUnavailable(f"HMM ID returned {resp.status_code}")
        subject = resp.json().get("id")
        if not subject:
            raise AuthUnavailable("HMM ID response without user id")
        # dash_user_id (e.g. "kakao_12345") is the stable subject shared by every DA-SH SP.
        # Email/name/phone are not copied: the career service does not need them.
        return ProviderIdentity(self.name, str(subject))


class GoogleProvider:
    name = "GOOGLE"

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.url = settings.google_tokeninfo_url
        self.client_id = settings.google_client_id
        self.client = client or httpx.Client(timeout=5)

    def verify(self, token: str) -> ProviderIdentity:
        if not self.client_id:
            raise AuthError("google login is not configured")
        try:
            resp = self.client.get(self.url, params={"id_token": token})
        except httpx.HTTPError as exc:
            raise AuthUnavailable("google unreachable") from exc
        data = resp.json() if resp.status_code == 200 else {}
        if data.get("aud") != self.client_id or not data.get("sub"):
            raise AuthError("google token rejected")
        return ProviderIdentity(self.name, data["sub"])


class DevProvider:
    """Development/test only: token 'dev:<subject>'. Refused in production by Settings."""

    name = "DEV"

    def verify(self, token: str) -> ProviderIdentity:
        if not token.startswith("dev:") or len(token) <= 4:
            raise AuthError("dev token must look like dev:<subject>")
        return ProviderIdentity(self.name, token[4:])


def get_provider(name: str, settings: Settings) -> AuthProvider:
    if name not in settings.auth_providers:
        raise AuthError(f"provider {name} is not enabled")
    factories = {"HMM_ID": lambda: HmmIdProvider(settings),
                 "GOOGLE": lambda: GoogleProvider(settings), "DEV": DevProvider}
    if name not in factories:
        raise AuthError(f"provider {name} is not supported yet")
    return factories[name]()
