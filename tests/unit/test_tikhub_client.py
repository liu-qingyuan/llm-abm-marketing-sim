from __future__ import annotations

import io
import urllib.error
from email.message import Message
from typing import Any

import pytest

from llm_abm_sim.data_sources.douyin_models import TIKHUB_OPENAPI_UPDATED, TIKHUB_OPENAPI_VERSION
from llm_abm_sim.data_sources.tikhub_client import (
    ENDPOINT_REGISTRY,
    TikHubClient,
    TikHubClientError,
    TikHubEndpointError,
    TikHubSettings,
    validate_douyin_endpoint,
)


def test_endpoint_registry_is_douyin_only_with_metadata() -> None:
    assert TIKHUB_OPENAPI_VERSION == "V5.3.2"
    assert TIKHUB_OPENAPI_UPDATED == "2026-06-07"
    assert ENDPOINT_REGISTRY
    for endpoint in ENDPOINT_REGISTRY.values():
        assert endpoint.path.startswith("/api/v1/douyin/")
        assert validate_douyin_endpoint(endpoint.path) == endpoint.path


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/tiktok/foo",
        "/api/v1/xiaohongshu/foo",
        "/api/v1/bilibili/foo",
        "https://api.tikhub.io/api/v1/douyin/web/fetch_one_video",
        "/api/v1/douyin/../tiktok/foo",
        "/api/v1/douyin/not_registered",
    ],
)
def test_non_douyin_or_unregistered_endpoint_hard_fails(path: str) -> None:
    with pytest.raises(TikHubEndpointError):
        validate_douyin_endpoint(path)


def test_current_endpoint_registry_uses_search_v2_and_app_v3() -> None:
    assert ENDPOINT_REGISTRY["fetch_video_search_v2"].path == "/api/v1/douyin/search/fetch_video_search_v2"
    assert ENDPOINT_REGISTRY["fetch_general_search_v2"].path == "/api/v1/douyin/search/fetch_general_search_v2"
    assert ENDPOINT_REGISTRY["fetch_challenge_search_v2"].path == "/api/v1/douyin/search/fetch_challenge_search_v2"
    assert ENDPOINT_REGISTRY["fetch_one_video"].path == "/api/v1/douyin/app/v3/fetch_one_video"
    assert ENDPOINT_REGISTRY["fetch_hashtag_video_list"].path == "/api/v1/douyin/app/v3/fetch_hashtag_video_list"
    assert ENDPOINT_REGISTRY["fetch_video_comments"].path == "/api/v1/douyin/app/v3/fetch_video_comments"
    assert ENDPOINT_REGISTRY["fetch_video_comment_replies"].path == "/api/v1/douyin/app/v3/fetch_video_comment_replies"
    assert ENDPOINT_REGISTRY["handler_user_profile"].path == "/api/v1/douyin/app/v3/handler_user_profile"


def test_bearer_auth_is_used_but_not_persisted() -> None:
    calls = []

    def transport(method, url, headers, params, json_body, timeout):
        calls.append((method, url, headers, params, json_body, timeout))
        return {"ok": True}

    client = TikHubClient(TikHubSettings(api_key="secret-token", qps=1000, user_agent="Mozilla/5.0 Test"), transport=transport)
    assert client.fetch_one_video(aweme_id="v1") == {"ok": True}
    assert calls[0][2]["Authorization"] == "Bearer secret-token"
    assert calls[0][2]["User-Agent"] == "Mozilla/5.0 Test"
    assert "/api/v1/douyin/app/v3/fetch_one_video" in calls[0][1]
    assert "secret-token" not in repr(client.endpoint_call_counts)
    assert "secret-token" not in repr(client.settings.redacted())


def test_retry_then_redacted_error() -> None:
    attempts = 0

    class Retryable(Exception):
        status_code = 500

    def transport(method, url, headers, params, json_body, timeout):
        nonlocal attempts
        attempts += 1
        raise Retryable("failed Bearer secret-token")

    client = TikHubClient(
        TikHubSettings(api_key="secret-token", qps=1000, max_retries=1, backoff_seconds=0), transport=transport
    )
    with pytest.raises(Exception) as excinfo:
        client.fetch_one_video(aweme_id="v1")
    assert attempts == 2
    assert "secret-token" not in str(excinfo.value)


def test_real_transport_client_blocks_without_live_gate() -> None:
    client = TikHubClient(TikHubSettings(api_key="secret-token", live_fetch=False))
    with pytest.raises(Exception) as excinfo:
        client.fetch_one_video(aweme_id="v1")
    assert "live request blocked" in str(excinfo.value)
    assert "secret-token" not in str(excinfo.value)


def test_real_transport_client_requires_https_for_live() -> None:
    client = TikHubClient(TikHubSettings(api_key="secret-token", live_fetch=True, base_url="http://api.tikhub.test"))
    with pytest.raises(Exception) as excinfo:
        client.fetch_one_video(aweme_id="v1")
    assert "must use https" in str(excinfo.value)
    assert "secret-token" not in str(excinfo.value)


def test_app_v3_hashtag_video_list_uses_ch_id_param() -> None:
    calls = []

    def transport(method, url, headers, params, json_body, timeout):
        calls.append((method, url, params))
        return {"ok": True}

    client = TikHubClient(TikHubSettings(api_key="secret-token", qps=1000), transport=transport)

    client.fetch_hashtag_video_list(ch_id="cha", cursor=0, sort_type=0)

    assert calls[0][0] == "GET"
    assert "/api/v1/douyin/app/v3/fetch_hashtag_video_list" in calls[0][1]
    assert calls[0][2]["ch_id"] == "cha"


def test_app_v3_comment_replies_uses_item_id_param() -> None:
    calls = []

    def transport(method, url, headers, params, json_body, timeout):
        calls.append((method, url, params))
        return {"ok": True}

    client = TikHubClient(TikHubSettings(api_key="secret-token", qps=1000), transport=transport)

    client.fetch_video_comment_replies(aweme_id="v1", comment_id="c1", cursor=0, count=2)

    assert calls[0][0] == "GET"
    assert "/api/v1/douyin/app/v3/fetch_video_comment_replies" in calls[0][1]
    assert calls[0][2]["item_id"] == "v1"
    assert "aweme_id" not in calls[0][2]


def test_urllib_transport_supports_proxy_user_agent_and_http_error_body(monkeypatch: pytest.MonkeyPatch) -> None:
    events: dict[str, Any] = {}

    class DummyResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return b'{"ok": true}'

    class DummyOpener:
        def open(self, request, timeout):
            events["request"] = request
            events["timeout"] = timeout
            return DummyResponse()

    def fake_proxy_handler(proxies):
        events["proxies"] = proxies
        return "proxy-handler"

    def fake_build_opener(handler):
        events["handler"] = handler
        return DummyOpener()

    monkeypatch.setattr("urllib.request.ProxyHandler", fake_proxy_handler)
    monkeypatch.setattr("urllib.request.build_opener", fake_build_opener)

    result = TikHubClient._urllib_transport(
        "POST",
        "https://api.tikhub.dev/api/v1/douyin/search/fetch_video_search_v2",
        {"User-Agent": "Mozilla/5.0 Test", "Authorization": "Bearer secret-token"},
        {"cursor": 0},
        {"keyword": "锦江酒店"},
        12,
        proxy_url="http://127.0.0.1:7897",
    )

    assert result == {"ok": True}
    assert events["proxies"] == {"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"}
    request = events["request"]
    assert request.headers["User-agent"] == "Mozilla/5.0 Test"
    assert events["timeout"] == 12

    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 403, "Forbidden", Message(), io.BytesIO(b'{"detail":"API Token lacks required permissions"}')
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(Exception) as excinfo:
        TikHubClient._urllib_transport(
            "GET",
            "https://api.tikhub.dev/api/v1/douyin/app/v3/fetch_one_video",
            {"User-Agent": "Mozilla/5.0 Test", "Authorization": "Bearer secret-token"},
            {"aweme_id": "v1"},
            None,
            12,
        )
    assert "HTTP 403" in str(excinfo.value)
    assert "lacks required permissions" in str(excinfo.value)
    assert "secret-token" not in str(excinfo.value)


def test_profile_endpoints_do_not_retry_400_402_429() -> None:
    for endpoint_name, call in [
        ("handler_user_profile", lambda client: client.handler_user_profile("sec")),
        ("fetch_batch_user_profile_v2", lambda client: client.fetch_batch_user_profile(["sec"])),
    ]:
        for status in [400, 402, 429]:
            attempts = 0

            class ProfileHttpError(Exception):
                status_code = status

            def transport(method, url, headers, params, json_body, timeout, *, response_status: int = status):
                nonlocal attempts
                attempts += 1
                raise ProfileHttpError(f"HTTP {response_status}: paid quota or provider error")

            client = TikHubClient(
                TikHubSettings(api_key="secret-token", qps=1000, max_retries=2, backoff_seconds=0),
                transport=transport,
            )
            with pytest.raises(TikHubClientError):
                call(client)
            assert attempts == 1, f"{endpoint_name} retried HTTP {status}"
