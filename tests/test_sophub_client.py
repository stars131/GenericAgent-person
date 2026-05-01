import io
import json
import sys
import urllib.error
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "memory" / "skill_search"))

from skill_search import SophubAuthError, raw_sop, read_sop, search, upload_sop  # noqa: E402
from skill_search import engine  # noqa: E402


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.data


def test_search_uses_sophub_api_and_maps_preview(monkeypatch):
    seen = {}
    payload = {
        "items": [
            {
                "id": "abc123",
                "title": "GitHub 项目学习方法论 SOP",
                "preview": "# GitHub 项目学习方法论 SOP\n适用场景",
                "file_type": "markdown",
                "author_name_snapshot": "GenericAgent",
                "stats": {"stars_avg": 5.0, "review_count": 1},
            }
        ],
        "total": 1,
    }

    def fake_urlopen(req, timeout=30):
        seen["url"] = req.full_url
        seen["method"] = req.get_method()
        return FakeResponse(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    monkeypatch.setattr(engine.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.delenv("SOPHUB_API", raising=False)
    monkeypatch.delenv("SKILL_SEARCH_API", raising=False)

    results = search("github project", top_k=3)

    assert seen["method"] == "GET"
    assert seen["url"].startswith("https://fudankw.cn/sophub/api/sops?")
    assert "q=github+project" in seen["url"]
    assert "page_size=3" in seen["url"]
    assert results[0].skill.key == "abc123"
    assert results[0].skill.name == "GitHub 项目学习方法论 SOP"
    assert results[0].skill.raw_url == "https://fudankw.cn/sophub/raw/abc123"


def test_read_sop_maps_content(monkeypatch):
    payload = {
        "id": "abc123",
        "title": "SOP title",
        "content": "# Full content",
        "file_type": "markdown",
    }

    def fake_urlopen(req, timeout=30):
        return FakeResponse(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(engine.urllib.request, "urlopen", fake_urlopen)

    sop = read_sop("abc123")

    assert sop.id == "abc123"
    assert sop.title == "SOP title"
    assert sop.content == "# Full content"


def test_raw_sop_decodes_utf8(monkeypatch):
    def fake_urlopen(req, timeout=30):
        assert req.full_url.endswith("/raw/abc123")
        return FakeResponse("# 中文 SOP".encode("utf-8"))

    monkeypatch.setattr(engine.urllib.request, "urlopen", fake_urlopen)

    assert raw_sop("abc123") == "# 中文 SOP"


def test_upload_requires_auth_without_key(monkeypatch):
    monkeypatch.delenv("SOPHUB_API_KEY", raising=False)
    monkeypatch.delenv("SKILL_SEARCH_KEY", raising=False)
    monkeypatch.setattr(engine, "_keychain_api_key", lambda: None)

    with pytest.raises(SophubAuthError):
        upload_sop("title", "content")


def test_http_error_is_wrapped(monkeypatch):
    def fake_urlopen(req, timeout=30):
        raise urllib.error.HTTPError(
            req.full_url,
            429,
            "rate limited",
            hdrs=None,
            fp=io.BytesIO(b'{"error":"rate_limited"}'),
        )

    monkeypatch.setattr(engine.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(engine.SkillSearchError, match="429"):
        search("anything")
