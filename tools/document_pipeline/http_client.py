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


def _resolve_public_a_record(hostname: str, timeout: int = 8) -> str | None:
    """Resolve a public A record via DoH, bypassing local Fake-IP DNS.

    Local Clash/mihomo Fake-IP (198.18.0.0/16) is fine for small API calls but
    frequently resets large OSS body uploads. Prefer the real edge IP.
    """
    import re
    from urllib.error import URLError
    from urllib.parse import quote
    from urllib.request import Request, urlopen

    if not hostname or re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", hostname):
        return hostname or None

    endpoints = (
        f"https://dns.alidns.com/resolve?name={quote(hostname)}&type=A",
        f"https://cloudflare-dns.com/dns-query?name={quote(hostname)}&type=A",
    )
    headers_list = (
        {"Accept": "application/json"},
        {"Accept": "application/dns-json"},
    )
    for url, headers in zip(endpoints, headers_list, strict=True):
        try:
            req = Request(url, headers=headers, method="GET")
            with urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="replace"))
        except (URLError, TimeoutError, json.JSONDecodeError, OSError):
            continue
        answers = payload.get("Answer") or payload.get("answer") or []
        if not isinstance(answers, list):
            continue
        for ans in answers:
            if not isinstance(ans, dict):
                continue
            # type 1 == A
            if int(ans.get("type") or 0) != 1:
                continue
            data = str(ans.get("data") or "").strip()
            if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", data):
                # Skip Fake-IP ranges if a resolver still returns them.
                if data.startswith("198.18."):
                    continue
                return data
    return None


def _put_file_with_curl(
    upload_url: str,
    file_path: Path,
    *,
    resolve_ip: str | None,
    timeout: int,
) -> int:
    """PUT via curl so we can pin SNI host to a real OSS IP with --resolve."""
    import subprocess

    cmd = [
        "curl",
        "-sS",
        "--fail-with-body",
        "--noproxy",
        "*",
        "--http1.1",
        "-T",
        str(file_path),
        "-o",
        "/dev/null",
        "-w",
        "%{http_code}",
        "--max-time",
        str(max(int(timeout), 60)),
        # Explicitly clear Content-Type; pre-signed OSS URLs reject extra headers.
        "-H",
        "Content-Type:",
        "-H",
        "Expect:",
    ]
    host = urlsplit(upload_url).hostname
    if resolve_ip and host:
        cmd.extend(["--resolve", f"{host}:443:{resolve_ip}"])
    cmd.append(upload_url)
    size_mb = file_path.stat().st_size / (1024 * 1024)
    target = f"{urlsplit(upload_url).hostname}{'@'+resolve_ip if resolve_ip else ''}"
    print(
        f"[put_file] curl upload start size={size_mb:.1f}MB host={target}",
        flush=True,
    )
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as e:  # pragma: no cover
        raise RuntimeError("curl not available for OSS upload") from e
    code_txt = (proc.stdout or "").strip()
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()[:300]
        raise RuntimeError(f"curl upload failed rc={proc.returncode}: {err or code_txt}")
    try:
        status = int(code_txt)
    except ValueError as e:
        raise RuntimeError(f"curl upload returned non-http code: {code_txt!r}") from e
    if status not in (200, 201):
        raise SystemExit(f"upload failed HTTP {status}")
    print(f"[put_file] curl upload ok HTTP {status}", flush=True)
    return status


def put_file(
    upload_url: str,
    file_path: Path,
    timeout: int = 600,
    *,
    max_attempts: int = 6,
) -> int:
    """Upload with no Content-Type header.

    MinerU docs require: requests.put(url, data=f)
    Adding Content-Type breaks Aliyun OSS pre-signed URL signatures.
    urllib also auto-injects application/x-www-form-urlencoded, so use requests.

    Local transparent proxies (Fake-IP / utun) can reset large mid-body PUTs.
    Prefer curl --resolve against a public A record, then fall back to requests
    with retries and proxy disabled.
    """
    import time

    try:
        import requests
        from requests import exceptions as req_exc
    except ImportError as e:  # pragma: no cover
        raise SystemExit("requests is required for OSS upload: pip install requests") from e

    host = urlsplit(upload_url).hostname or ""
    resolve_ip = _resolve_public_a_record(host) if host else None
    attempts = max(1, int(max_attempts))
    last_error: Exception | None = None

    # Path 1: curl direct-to-real-IP (most reliable under Clash Fake-IP).
    for attempt in range(1, attempts + 1):
        try:
            return _put_file_with_curl(
                upload_url,
                file_path,
                resolve_ip=resolve_ip,
                timeout=timeout,
            )
        except SystemExit:
            raise
        except Exception as exc:  # noqa: BLE001 - retry network-ish failures
            last_error = exc
            if attempt >= min(3, attempts):
                break
            time.sleep(min(2 ** (attempt - 1), 8))
            # Refresh edge IP between attempts; OSS CNAME can rotate.
            resolve_ip = _resolve_public_a_record(host) if host else resolve_ip

    # Path 2: requests with proxy disabled (works when Fake-IP path is stable).
    session = requests.Session()
    session.trust_env = False
    for attempt in range(1, attempts + 1):
        try:
            with open(file_path, "rb") as f:
                resp = session.put(
                    upload_url,
                    data=f,
                    timeout=timeout,
                    proxies={"http": None, "https": None},
                    headers={},
                )
            if resp.status_code not in (200, 201):
                raise SystemExit(
                    f"upload failed HTTP {resp.status_code}: {resp.text[:300]}"
                )
            return resp.status_code
        except SystemExit:
            raise
        except (
            req_exc.ConnectionError,
            req_exc.Timeout,
            req_exc.ChunkedEncodingError,
            OSError,
        ) as exc:
            last_error = exc
            if attempt >= attempts:
                break
            time.sleep(min(2 ** (attempt - 1), 8))
    assert last_error is not None
    raise last_error
