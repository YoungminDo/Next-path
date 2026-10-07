"""Login provider abstraction. Kakao + Google first; Apple can be added as another adapter.

Each adapter turns a client-obtained provider token into a stable provider subject. Provider
tokens are verified server-side and never stored.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx

from hellomyme.config import Settings


class AuthError(Exception):
    pass


@dataclass(frozen=True)
class ProviderIdentity:
    provider: str
    subject: str


class AuthProvider(Protocol):
    name: str

    def verify(self, token: str) -> ProviderIdentity: ...


class KakaoProvider:
    name = "KAKAO"

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.url = settings.kakao_user_info_url
        self.client = client or httpx.Client(timeout=5)

    def verify(self, token: str) -> ProviderIdentity:
        resp = self.client.get(self.url, headers={"Authorization": f"Bearer {token}"})
        if resp.status_code != 200 or "id" not in resp.json():
            raise AuthError("kakao token rejected")
        return ProviderIdentity(self.name, str(resp.json()["id"]))


class GoogleProvider:
    name = "GOOGLE"

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.url = settings.google_tokeninfo_url
        self.client_id = settings.google_client_id
        self.client = client or httpx.Client(timeout=5)

    def verify(self, token: str) -> ProviderIdentity:
        if not self.client_id:
            raise AuthError("google login is not configured")
        resp = self.client.get(self.url, params={"id_token": token})
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
    factories = {"KAKAO": lambda: KakaoProvider(settings), "GOOGLE": lambda: GoogleProvider(settings),
                 "DEV": DevProvider}
    if name not in factories:
        raise AuthError(f"provider {name} is not supported yet")
    return factories[name]()
