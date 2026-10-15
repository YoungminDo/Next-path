"""Search API clients for search ingest (docs/12). Each returns (url, title, snippet) rows only;
nothing here stores or logs a result. 401/403/429 mean the provider is unusable for the rest of
a run (bad key or quota); anything else is one failed query."""
from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

FATAL = {401, 403, 429}
TIMEOUT = 30


@dataclass(frozen=True)
class Result:
    url: str
    title: str
    snippet: str


class SearchError(Exception):
    """fatal = the provider is unusable for the rest of the run (bad key, quota).
    The message never contains the request URL: the SerpAPI key sits in its query string."""

    def __init__(self, provider: str, status: int | None, message: str):
        super().__init__(f"{provider}: {status or 'network'} {message}")
        self.provider, self.status = provider, status
        self.fatal = status in FATAL


def _get_json(provider: str, url: str, headers: dict | None = None) -> dict:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        code, reason = exc.code, str(exc.reason)
        exc.close()
        raise SearchError(provider, code, reason) from None
    except (OSError, http.client.HTTPException, ValueError) as exc:
        raise SearchError(provider, None, str(exc)) from None
    if not isinstance(data, dict):
        raise SearchError(provider, None, "unexpected response")
    return data


class SerpApi:
    name, model_version = "serpapi", "serpapi-google"

    def __init__(self, key: str):
        self._key = key

    def search(self, query: str, count: int) -> list[Result]:
        url = "https://serpapi.com/search.json?" + urllib.parse.urlencode(
            {"engine": "google", "q": query, "num": count, "hl": "ko", "gl": "kr", "api_key": self._key})
        data = _get_json(self.name, url)
        return [Result(r.get("link") or "", r.get("title") or "", r.get("snippet") or "")
                for r in (data.get("organic_results") or []) if isinstance(r, dict)]


class Brave:
    name, model_version = "brave", "brave"

    def __init__(self, key: str):
        self._key = key

    def search(self, query: str, count: int) -> list[Result]:
        url = "https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode(
            {"q": query, "count": count, "country": "KR", "search_lang": "ko"})
        data = _get_json(self.name, url, {"Accept": "application/json",
                                          "X-Subscription-Token": self._key})
        return [Result(r.get("url") or "", r.get("title") or "",
                       " · ".join(p for p in [r.get("description") or ""]
                                  + list(r.get("extra_snippets") or []) if p))
                for r in ((data.get("web") or {}).get("results") or []) if isinstance(r, dict)]


def from_settings(settings) -> list[SerpApi | Brave]:
    out: list[SerpApi | Brave] = []
    if settings.serpapi_key:
        out.append(SerpApi(settings.serpapi_key.get_secret_value()))
    if settings.brave_api_key:
        out.append(Brave(settings.brave_api_key.get_secret_value()))
    return out
