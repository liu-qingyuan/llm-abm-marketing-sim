from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from .douyin_models import TIKHUB_OPENAPI_UPDATED, TIKHUB_OPENAPI_VERSION

Transport = Callable[[str, str, dict[str, str], dict[str, Any] | None, dict[str, Any] | None, float], Any]

DEFAULT_TIKHUB_BASE_URL = "https://api.tikhub.dev"
DEFAULT_TIKHUB_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

SENSITIVE_KEY_PARTS = ("authorization", "cookie", "api_key", "apikey", "token", "secret", "password")


class TikHubClientError(RuntimeError):
    """Raised for TikHub client failures with secrets redacted."""


class TikHubEndpointError(ValueError):
    """Raised when a non-Douyin or unregistered endpoint is requested."""


@dataclass(frozen=True)
class TikHubEndpoint:
    name: str
    method: Literal["GET", "POST"]
    path: str


ENDPOINT_REGISTRY: dict[str, TikHubEndpoint] = {
    # Current live path: Douyin Search V2 + App V3.
    "fetch_video_search_v2": TikHubEndpoint(
        "fetch_video_search_v2", "POST", "/api/v1/douyin/search/fetch_video_search_v2"
    ),
    "fetch_general_search_v2": TikHubEndpoint(
        "fetch_general_search_v2", "POST", "/api/v1/douyin/search/fetch_general_search_v2"
    ),
    "fetch_challenge_search_v2": TikHubEndpoint(
        "fetch_challenge_search_v2", "POST", "/api/v1/douyin/search/fetch_challenge_search_v2"
    ),
    "fetch_one_video": TikHubEndpoint("fetch_one_video", "GET", "/api/v1/douyin/app/v3/fetch_one_video"),
    "fetch_one_video_v2": TikHubEndpoint("fetch_one_video_v2", "GET", "/api/v1/douyin/app/v3/fetch_one_video_v2"),
    "fetch_hashtag_video_list": TikHubEndpoint(
        "fetch_hashtag_video_list", "GET", "/api/v1/douyin/app/v3/fetch_hashtag_video_list"
    ),
    "fetch_video_comments": TikHubEndpoint(
        "fetch_video_comments", "GET", "/api/v1/douyin/app/v3/fetch_video_comments"
    ),
    "fetch_video_comment_replies": TikHubEndpoint(
        "fetch_video_comment_replies", "GET", "/api/v1/douyin/app/v3/fetch_video_comment_replies"
    ),
    "handler_user_profile": TikHubEndpoint(
        "handler_user_profile", "GET", "/api/v1/douyin/app/v3/handler_user_profile"
    ),
    # Legacy compatibility endpoints: never used before V2/App V3 in live collection.
    "fetch_topic_query": TikHubEndpoint("fetch_topic_query", "POST", "/api/v1/douyin/index/fetch_topic_query"),
    "fetch_challenge_posts": TikHubEndpoint("fetch_challenge_posts", "POST", "/api/v1/douyin/web/fetch_challenge_posts"),
    "fetch_batch_user_profile_v2": TikHubEndpoint(
        "fetch_batch_user_profile_v2", "GET", "/api/v1/douyin/web/fetch_batch_user_profile_v2"
    ),
    "fetch_video_search_v1": TikHubEndpoint("fetch_video_search_v1", "POST", "/api/v1/douyin/search/fetch_video_search_v1"),
}
ALLOWED_ENDPOINT_PATHS = frozenset(endpoint.path for endpoint in ENDPOINT_REGISTRY.values())
PROFILE_ENDPOINT_NAMES = frozenset({"handler_user_profile", "fetch_batch_user_profile_v2"})


class TikHubSettings(BaseModel):
    api_key: str = ""
    base_url: str = DEFAULT_TIKHUB_BASE_URL
    proxy_url: str = ""
    user_agent: str = DEFAULT_TIKHUB_USER_AGENT
    platform: str = "douyin"
    live_fetch: bool = False
    max_videos: int | None = Field(default=20, ge=0)
    max_comments_per_video: int | None = Field(default=100, ge=0)
    max_replies_per_comment: int | None = Field(default=50, ge=0)
    max_users: int | None = Field(default=500, ge=0)
    max_search_pages: int | None = Field(default=1, ge=1)
    search_page_size: int = Field(default=20, ge=1)
    request_timeout_seconds: float = Field(default=45.0, gt=0)
    qps: float = Field(default=5.0, gt=0)
    max_retries: int = Field(default=2, ge=0)
    backoff_seconds: float = Field(default=0.25, ge=0)

    @field_validator("platform")
    @classmethod
    def _douyin_only(cls, value: str) -> str:
        if value.lower() != "douyin":
            raise ValueError("TikHub MVP supports only TIKHUB_PLATFORM=douyin")
        return "douyin"

    @field_validator("base_url", "proxy_url")
    @classmethod
    def _url_no_path(cls, value: str, info) -> str:
        clean = value.rstrip("/")
        if not clean:
            return ""
        if not clean.startswith(("http://", "https://")):
            raise ValueError(f"{info.field_name.upper()} must be an HTTP(S) URL")
        return clean

    @field_validator("user_agent")
    @classmethod
    def _user_agent_browser_like(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            return DEFAULT_TIKHUB_USER_AGENT
        return clean

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> TikHubSettings:
        env = os.environ if env is None else env
        return cls(
            api_key=env.get("TIKHUB_API_KEY", ""),
            base_url=env.get("TIKHUB_BASE_URL", DEFAULT_TIKHUB_BASE_URL),
            proxy_url=env.get("TIKHUB_PROXY_URL", ""),
            user_agent=env.get("TIKHUB_USER_AGENT", DEFAULT_TIKHUB_USER_AGENT),
            platform=env.get("TIKHUB_PLATFORM", "douyin"),
            live_fetch=_truthy(env.get("TIKHUB_LIVE_FETCH", "0")),
            max_videos=_optional_int(env.get("TIKHUB_MAX_VIDEOS"), 20),
            max_comments_per_video=_optional_int(env.get("TIKHUB_MAX_COMMENTS_PER_VIDEO"), 100),
            max_replies_per_comment=_optional_int(env.get("TIKHUB_MAX_REPLIES_PER_COMMENT"), 50),
            max_users=_optional_int(env.get("TIKHUB_MAX_USERS"), 500),
            max_search_pages=_optional_int(env.get("TIKHUB_MAX_SEARCH_PAGES"), 1),
            search_page_size=int(env.get("TIKHUB_SEARCH_PAGE_SIZE", "20")),
            request_timeout_seconds=float(env.get("TIKHUB_REQUEST_TIMEOUT_SECONDS", "45")),
            qps=float(env.get("TIKHUB_QPS", "5")),
            max_retries=int(env.get("TIKHUB_MAX_RETRIES", "2")),
            backoff_seconds=float(env.get("TIKHUB_BACKOFF_SECONDS", "0.25")),
        )

    def business_limits_unbounded(self) -> bool:
        return all(
            value is None
            for value in (
                self.max_videos,
                self.max_comments_per_video,
                self.max_replies_per_comment,
                self.max_users,
                self.max_search_pages,
            )
        )

    def live_readiness(self) -> tuple[bool, str]:
        if not self.live_fetch:
            return False, "TIKHUB_LIVE_FETCH is not enabled"
        if not self.api_key:
            return False, "TIKHUB_API_KEY is required when TIKHUB_LIVE_FETCH=1"
        return True, "ready"

    def redacted(self) -> dict[str, Any]:
        data = self.model_dump()
        if data.get("api_key"):
            data["api_key"] = "<redacted>"
        return redact_secrets(data)


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _optional_int(value: str | None, default: int) -> int | None:
    if value is None or str(value).strip() == "":
        return default
    normalized = str(value).strip().lower()
    if normalized in {"none", "null", "unbounded", "unlimited"}:
        return None
    return int(normalized)


def redact_secrets(value: Any, secrets: list[str] | tuple[str, ...] | None = None) -> Any:
    explicit = [secret for secret in (secrets or []) if secret]
    if isinstance(value, dict):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            key_lower = str(key).lower()
            if any(part in key_lower for part in SENSITIVE_KEY_PARTS):
                redacted[key] = "<redacted>"
            else:
                redacted[key] = redact_secrets(item, explicit)
        return redacted
    if isinstance(value, list):
        return [redact_secrets(item, explicit) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_secrets(item, explicit) for item in value)
    if isinstance(value, str):
        redacted_text = value
        for secret in explicit:
            redacted_text = redacted_text.replace(secret, "<redacted>")
        # Plain/multiline header dumps, including strings with escaped "\n"
        # boundaries from repr/JSON error messages.
        redacted_text = re.sub(
            r"(?i)(^|\\n|\r\n|\n|\r)\s*(authorization|cookie)\s*:\s*.*?(?=(\\n|\r\n|\n|\r|$))",
            lambda match: f"{match.group(1)}{match.group(2)}: <redacted>",
            redacted_text,
        )
        redacted_text = re.sub(
            r"(?i)([\"'](?:authorization|cookie)[\"']\s*:\s*)([\"'])(.*?)(\2)",
            r"\1\2<redacted>\4",
            redacted_text,
        )
        redacted_text = re.sub(
            r"(?i)\b(authorization|cookie)\s*:\s*([^,\n\r}]+)",
            r"\1: <redacted>",
            redacted_text,
        )
        if "Bearer " in redacted_text:
            redacted_text = redacted_text.replace(redacted_text.split("Bearer ", 1)[1].split()[0], "<redacted>")
        return redacted_text
    return value


def validate_douyin_endpoint(path: str) -> str:
    if path.startswith(("http://", "https://")):
        raise TikHubEndpointError("TikHub endpoint must be a relative registered Douyin path")
    if ".." in path or not path.startswith("/"):
        raise TikHubEndpointError("TikHub endpoint path is invalid")
    if not path.startswith("/api/v1/douyin/"):
        raise TikHubEndpointError("TikHub MVP allows only /api/v1/douyin/... endpoints")
    if path not in ALLOWED_ENDPOINT_PATHS:
        raise TikHubEndpointError(f"TikHub endpoint is not registered for this MVP: {path}")
    return path


@dataclass
class QPSGuard:
    qps: float
    _last_call: float = field(default=0.0, init=False)

    def wait(self) -> None:
        interval = 1.0 / self.qps
        now = time.monotonic()
        wait_for = self._last_call + interval - now
        if wait_for > 0:
            time.sleep(wait_for)
        self._last_call = time.monotonic()


class TikHubClient:
    def __init__(self, settings: TikHubSettings | None = None, *, transport: Transport | None = None) -> None:
        self.settings = settings or TikHubSettings.from_env()
        self._live_gate_required = transport is None
        self.transport = transport or (
            lambda method, url, headers, params, json_body, timeout: self._urllib_transport(
                method, url, headers, params, json_body, timeout, proxy_url=self.settings.proxy_url
            )
        )
        self.qps_guard = QPSGuard(self.settings.qps)
        self.endpoint_call_counts: dict[str, int] = {}

    @property
    def openapi_metadata(self) -> dict[str, str]:
        return {"version": TIKHUB_OPENAPI_VERSION, "updated": TIKHUB_OPENAPI_UPDATED}

    def request(
        self,
        endpoint: str | TikHubEndpoint,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        ep = self._resolve_endpoint(endpoint)
        validate_douyin_endpoint(ep.path)
        if self._live_gate_required:
            ready, reason = self.settings.live_readiness()
            if not ready:
                raise TikHubClientError(f"TikHub live request blocked: {reason}")
            if not self.settings.base_url.startswith("https://"):
                raise TikHubClientError("TikHub live request blocked: TIKHUB_BASE_URL must use https")
        headers = {"Accept": "application/json", "User-Agent": self.settings.user_agent}
        if self.settings.api_key:
            headers["Authorization"] = f"Bearer {self.settings.api_key}"
        attempt = 0
        while True:
            self.qps_guard.wait()
            self.endpoint_call_counts[ep.name] = self.endpoint_call_counts.get(ep.name, 0) + 1
            try:
                return self.transport(
                    ep.method,
                    self.settings.base_url + ep.path,
                    headers,
                    params,
                    json_body,
                    self.settings.request_timeout_seconds,
                )
            except Exception as exc:  # noqa: BLE001 - normalize transport and HTTP failures.
                retryable = _is_retryable(exc)
                if ep.name in PROFILE_ENDPOINT_NAMES and _exception_status(exc) in {400, 402, 429}:
                    retryable = False
                if attempt < self.settings.max_retries and retryable:
                    time.sleep(self.settings.backoff_seconds * (2**attempt))
                    attempt += 1
                    continue
                message = redact_secrets(str(exc), [self.settings.api_key])
                raise TikHubClientError(f"TikHub request failed for {ep.name}: {message}") from None

    def fetch_topic_query(self, **payload: Any) -> Any:
        return self.request(ENDPOINT_REGISTRY["fetch_topic_query"], json_body=payload)

    def fetch_challenge_posts(self, **payload: Any) -> Any:
        return self.request(ENDPOINT_REGISTRY["fetch_challenge_posts"], json_body=payload)

    def fetch_video_search_v2(self, **payload: Any) -> Any:
        return self.request(ENDPOINT_REGISTRY["fetch_video_search_v2"], json_body=payload)

    def fetch_general_search_v2(self, **payload: Any) -> Any:
        return self.request(ENDPOINT_REGISTRY["fetch_general_search_v2"], json_body=payload)

    def fetch_challenge_search_v2(self, **payload: Any) -> Any:
        return self.request(ENDPOINT_REGISTRY["fetch_challenge_search_v2"], json_body=payload)

    def fetch_video_search(self, **payload: Any) -> Any:
        return self.fetch_video_search_v2(**payload)

    def fetch_legacy_video_search_v1(self, **payload: Any) -> Any:
        return self.request(ENDPOINT_REGISTRY["fetch_video_search_v1"], json_body=payload)

    def fetch_one_video(self, **params: Any) -> Any:
        return self.request(ENDPOINT_REGISTRY["fetch_one_video"], params=params)

    def fetch_hashtag_video_list(self, **params: Any) -> Any:
        return self.request(ENDPOINT_REGISTRY["fetch_hashtag_video_list"], params=params)

    def fetch_video_comments(self, **params: Any) -> Any:
        return self.request(ENDPOINT_REGISTRY["fetch_video_comments"], params=params)

    def fetch_video_comment_replies(self, **params: Any) -> Any:
        if "item_id" not in params and "aweme_id" in params:
            params = dict(params)
            params["item_id"] = params.pop("aweme_id")
        return self.request(ENDPOINT_REGISTRY["fetch_video_comment_replies"], params=params)

    def fetch_batch_user_profile(self, sec_user_ids: list[str]) -> Any:
        return self.request(ENDPOINT_REGISTRY["fetch_batch_user_profile_v2"], params={"sec_user_ids": ",".join(sec_user_ids)})

    def handler_user_profile(self, sec_user_id: str) -> Any:
        return self.request(ENDPOINT_REGISTRY["handler_user_profile"], params={"sec_user_id": sec_user_id})

    def _resolve_endpoint(self, endpoint: str | TikHubEndpoint) -> TikHubEndpoint:
        if isinstance(endpoint, TikHubEndpoint):
            return endpoint
        if endpoint in ENDPOINT_REGISTRY:
            return ENDPOINT_REGISTRY[endpoint]
        for registered in ENDPOINT_REGISTRY.values():
            if registered.path == endpoint:
                return registered
        validate_douyin_endpoint(endpoint)
        raise TikHubEndpointError(f"TikHub endpoint is not registered for this MVP: {endpoint}")

    @staticmethod
    def _urllib_transport(
        method: str,
        url: str,
        headers: dict[str, str],
        params: dict[str, Any] | None,
        json_body: dict[str, Any] | None,
        timeout: float,
        *,
        proxy_url: str = "",
    ) -> Any:
        if params:
            encoded = urllib.parse.urlencode({key: value for key, value in params.items() if value is not None})
            url = f"{url}?{encoded}"
        data = None
        request_headers = dict(headers)
        if json_body is not None:
            data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url=url, data=data, headers=request_headers, method=method)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})) if proxy_url else None
        try:
            if opener is None:
                with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - explicit user-gated live API client.
                    payload = response.read().decode("utf-8")
            else:
                with opener.open(request, timeout=timeout) as response:  # noqa: S310 - explicit user-gated live API client.
                    payload = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:2000]
            raise TikHubClientError(f"HTTP {exc.code}: {body}") from None
        return json.loads(payload) if payload else {}


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, (TimeoutError, ConnectionError, urllib.error.URLError)):
        return True
    status = _exception_status(exc)
    return status == 429 or (isinstance(status, int) and 500 <= status <= 599)


def _exception_status(exc: Exception) -> int | None:
    status = getattr(exc, "code", None) or getattr(exc, "status", None) or getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    match = re.search(r"\bHTTP\s+(\d{3})\b", str(exc), flags=re.IGNORECASE)
    return int(match.group(1)) if match else None
