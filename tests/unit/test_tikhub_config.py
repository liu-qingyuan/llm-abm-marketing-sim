from __future__ import annotations

from llm_abm_sim.data_sources.tikhub_client import TikHubSettings


def test_defaults_are_offline_safe() -> None:
    settings = TikHubSettings.from_env({})
    assert settings.live_fetch is False
    assert settings.base_url == "https://api.tikhub.dev"
    assert settings.proxy_url == ""
    assert "Mozilla/5.0" in settings.user_agent
    assert settings.platform == "douyin"
    assert settings.request_timeout_seconds == 45
    assert settings.qps == 5
    ready, reason = settings.live_readiness()
    assert ready is False
    assert "not enabled" in reason


def test_env_overrides_limits_and_readiness_without_key() -> None:
    settings = TikHubSettings.from_env(
        {
            "TIKHUB_BASE_URL": "https://example.test/",
            "TIKHUB_LIVE_FETCH": "1",
            "TIKHUB_MAX_VIDEOS": "2",
            "TIKHUB_MAX_COMMENTS_PER_VIDEO": "3",
            "TIKHUB_MAX_REPLIES_PER_COMMENT": "4",
            "TIKHUB_MAX_USERS": "5",
            "TIKHUB_REQUEST_TIMEOUT_SECONDS": "46",
            "TIKHUB_QPS": "6",
            "TIKHUB_PROXY_URL": "http://127.0.0.1:7897",
            "TIKHUB_USER_AGENT": "Mozilla/5.0 Custom Browser",
        }
    )
    assert settings.base_url == "https://example.test"
    assert settings.proxy_url == "http://127.0.0.1:7897"
    assert settings.user_agent == "Mozilla/5.0 Custom Browser"
    assert settings.live_fetch is True
    assert settings.max_videos == 2
    assert settings.max_comments_per_video == 3
    assert settings.max_replies_per_comment == 4
    assert settings.max_users == 5
    assert settings.request_timeout_seconds == 46
    assert settings.qps == 6
    ready, reason = settings.live_readiness()
    assert ready is False
    assert "TIKHUB_API_KEY" in reason


def test_live_readiness_requires_explicit_key() -> None:
    settings = TikHubSettings.from_env({"TIKHUB_LIVE_FETCH": "1", "TIKHUB_API_KEY": "secret"})
    assert settings.live_readiness() == (True, "ready")
    assert settings.redacted()["api_key"] == "<redacted>"


def test_unbounded_env_limits_use_none_without_overloading_zero() -> None:
    settings = TikHubSettings.from_env(
        {
            "TIKHUB_MAX_VIDEOS": "unbounded",
            "TIKHUB_MAX_COMMENTS_PER_VIDEO": "none",
            "TIKHUB_MAX_REPLIES_PER_COMMENT": "null",
            "TIKHUB_MAX_USERS": "unlimited",
            "TIKHUB_MAX_SEARCH_PAGES": "unbounded",
        }
    )
    assert settings.max_videos is None
    assert settings.max_comments_per_video is None
    assert settings.max_replies_per_comment is None
    assert settings.max_users is None
    assert settings.max_search_pages is None
    assert settings.business_limits_unbounded() is True

    zero_settings = TikHubSettings.from_env(
        {
            "TIKHUB_MAX_VIDEOS": "0",
            "TIKHUB_MAX_COMMENTS_PER_VIDEO": "0",
            "TIKHUB_MAX_REPLIES_PER_COMMENT": "0",
            "TIKHUB_MAX_USERS": "0",
        }
    )
    assert zero_settings.max_videos == 0
    assert zero_settings.max_comments_per_video == 0
    assert zero_settings.max_replies_per_comment == 0
    assert zero_settings.max_users == 0
    assert zero_settings.business_limits_unbounded() is False
