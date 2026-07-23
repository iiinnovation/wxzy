"""Injectable HTTP helpers for MinerU (and similar) APIs.

Never logs tokens or signed upload URLs in full.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

JsonTransport = Callable[[str, str, dict[str, str], bytes | None, int], tuple[int, bytes]]


def redact_url(url: str) -> str:
    """Drop query/fragment so pre-signed OSS URLs are not persisted."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def default_json_transport(
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None,
    timeout: int,
) -> tuple[int, bytes]:
    req = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as resp:
            return int(resp.status), resp.read()
    except HTTPError as e:
        return int(e.code), e.read()
    except URLError as e:
        raise SystemExit(f"network error calling {redact_url(url)}: {e}") from e


def http_json(
    method: str,
    url: str,
    token: str | None = None,
    body: dict[str, Any] | None = None,
    timeout: int = 60,
    *,
    transport: JsonTransport | None = None,
) -> tuple[int, Any]:
    data: bytes | None = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    runner = transport or default_json_transport
    status, raw = runner(method, url, headers, data, timeout)
    text = raw.decode("utf-8", errors="replace") if raw else ""
    try:
        payload = json.loads(text) if text else None
    except json.JSONDecodeError:
        payload = {"raw": text[:1000]}
    return status, payload


def put_file(upload_url: str, file_path: Path, timeout: int = 300) -> int:
    """Upload with no Content-Type header.

    MinerU docs require: requests.put(url, data=f)
    Adding Content-Type breaks Aliyun OSS pre-signed URL signatures.
    urllib also auto-injects application/x-www-form-urlencoded, so use requests.
    """
    try:
        import requests
    except ImportError as e:  # pragma: no cover
        raise SystemExit("requests is required for OSS upload: pip install requests") from e
    with open(file_path, "rb") as f:
        resp = requests.put(upload_url, data=f, timeout=timeout)
    if resp.status_code not in (200, 201):
        raise SystemExit(f"upload failed HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.status_code
