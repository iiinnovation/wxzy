from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

WECHAT_CODE2SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"
INVALID_CODE_ERRORS = {40029, 40163}


class WeChatCodeError(RuntimeError):
    """The client code is invalid, expired, or already consumed."""


class WeChatUnavailableError(RuntimeError):
    """The WeChat endpoint could not be reached before the timeout."""


class WeChatProviderError(RuntimeError):
    """The WeChat endpoint returned an unusable response."""


@dataclass(frozen=True)
class WeChatIdentity:
    openid: str


class WeChatCodeExchange:
    def exchange(self, code: str) -> WeChatIdentity:
        raise NotImplementedError


class UrllibWeChatCodeExchange(WeChatCodeExchange):
    def __init__(self, *, app_id: str, app_secret: str, timeout_seconds: float = 5.0) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._timeout_seconds = timeout_seconds

    def exchange(self, code: str) -> WeChatIdentity:
        query = urlencode(
            {
                "appid": self._app_id,
                "secret": self._app_secret,
                "js_code": code,
                "grant_type": "authorization_code",
            }
        )
        request = Request(
            f"{WECHAT_CODE2SESSION_URL}?{query}",
            headers={"Accept": "application/json"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                raw = response.read(64 * 1024 + 1)
        except (TimeoutError, URLError, OSError) as exc:
            raise WeChatUnavailableError from exc

        if len(raw) > 64 * 1024:
            raise WeChatProviderError
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WeChatProviderError from exc
        if not isinstance(payload, dict):
            raise WeChatProviderError

        error_code: object = payload.get("errcode")
        if error_code not in (None, 0, "0"):
            if not isinstance(error_code, str | int):
                raise WeChatProviderError
            try:
                normalized_error_code = int(error_code)
            except (TypeError, ValueError) as exc:
                raise WeChatProviderError from exc
            if normalized_error_code in INVALID_CODE_ERRORS:
                raise WeChatCodeError
            raise WeChatProviderError

        openid = payload.get("openid")
        if not isinstance(openid, str) or not openid.strip() or len(openid) > 128:
            raise WeChatProviderError
        return WeChatIdentity(openid=openid.strip())
