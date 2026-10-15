"""Search API clients (docs/12). HTTP is replaced; no real request is made."""
import io
import json
import urllib.error

import pytest
from pydantic import SecretStr

from hellomyme.ingest import search_source
from hellomyme.ingest.search_source import Brave, Result, SearchError, SerpApi, from_settings


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake(monkeypatch, payload=None, status=None):
    seen = {}

    def urlopen(req, timeout):
        seen["url"], seen["headers"] = req.full_url, dict(req.headers)
        if status:
            raise urllib.error.HTTPError(req.full_url, status, "x", {}, None)
        return _Resp(json.dumps(payload).encode())
    monkeypatch.setattr(search_source.urllib.request, "urlopen", urlopen)
    return seen


def test_serpapi_maps_organic_results(monkeypatch):
    seen = _fake(monkeypatch, {"organic_results": [
        {"link": "https://kr.linkedin.com/in/a", "title": "A - PM - X | LinkedIn", "snippet": "s"}]})
    out = SerpApi("k").search('site:linkedin.com/in "x"', 10)
    assert out == [Result("https://kr.linkedin.com/in/a", "A - PM - X | LinkedIn", "s")]
    assert "engine=google" in seen["url"] and "num=10" in seen["url"] and "api_key=k" in seen["url"]


def test_brave_joins_extra_snippets_and_sends_the_key_as_header(monkeypatch):
    seen = _fake(monkeypatch, {"web": {"results": [
        {"url": "https://www.linkedin.com/in/b", "title": "B | LinkedIn", "description": "d",
         "extra_snippets": ["e1", "e2"]}]}})
    out = Brave("k").search("q", 10)
    assert out == [Result("https://www.linkedin.com/in/b", "B | LinkedIn", "d · e1 · e2")]
    # urllib.request.Request stores header names capitalised this way
    assert seen["headers"]["X-subscription-token"] == "k"
    assert "count=10" in seen["url"]


@pytest.mark.parametrize("status,fatal", [(401, True), (429, True), (500, False)])
def test_http_errors_say_whether_the_provider_is_unusable(monkeypatch, status, fatal):
    _fake(monkeypatch, status=status)
    with pytest.raises(SearchError) as e:
        SerpApi("k").search("q", 10)
    assert (e.value.provider, e.value.status, e.value.fatal) == ("serpapi", status, fatal)


def test_from_settings_keeps_only_providers_with_a_key():
    class S:
        serpapi_key = None
        brave_api_key = SecretStr("b")
    assert [p.name for p in from_settings(S())] == ["brave"]
