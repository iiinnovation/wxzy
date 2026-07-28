from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRODUCTION = ROOT / "deploy" / "production"


def test_production_compose_keeps_database_private() -> None:
    compose = (PRODUCTION / "compose.yml").read_text(encoding="utf-8")

    assert "127.0.0.1:${WXZY_API_HOST_PORT:-18000}:8000" in compose
    assert compose.count("\n    ports:") == 1
    assert "5432:5432" not in compose
    assert "internal: true" in compose
    assert "no-new-privileges:true" in compose
    assert "read_only: true" in compose


def test_production_cors_allows_android_capacitor_origin() -> None:
    compose = (PRODUCTION / "compose.yml").read_text(encoding="utf-8")

    assert "CORS_ORIGINS: https://servicewechat.com,https://localhost" in compose


def test_production_image_runs_as_non_root() -> None:
    dockerfile = (ROOT / "server" / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (ROOT / "server" / ".dockerignore").read_text(encoding="utf-8")

    assert "USER app" in dockerfile
    assert "COPY --chown=app:app" in dockerfile
    assert ".env.*" in dockerignore
    assert "wxzy*.db" in dockerignore


def test_production_scripts_have_valid_bash_syntax() -> None:
    scripts = [
        PRODUCTION / "deploy.sh",
        PRODUCTION / "backup.sh",
        PRODUCTION / "restore.sh",
        PRODUCTION / "set-wechat-secret.sh",
    ]
    result = subprocess.run(
        ["bash", "-n", *(str(path) for path in scripts)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    deploy = (PRODUCTION / "deploy.sh").read_text(encoding="utf-8")
    assert "production secrets are missing or still use placeholders" in deploy
    assert "=(|replace_|REPLACE_)" not in deploy

    secret_script = (PRODUCTION / "set-wechat-secret.sh").read_text(encoding="utf-8")
    assert "read -r -s" in secret_script
    assert "WeChat AppSecret saved" in secret_script


def test_production_environment_does_not_offer_api_docs() -> None:
    env = os.environ.copy()
    env.update(
        {
            "APP_ENV": "production",
            "AUTH_MODE": "wechat",
            "WECHAT_APP_ID": "test-app",
            "WECHAT_APP_SECRET": "test-secret",
            "DATABASE_URL": "sqlite+pysqlite:///:memory:",
        }
    )
    script = (
        "from app.main import app; "
        "paths={getattr(r, 'path', None) for r in app.routes}; "
        "assert '/docs' not in paths; "
        "assert '/redoc' not in paths; "
        "assert '/openapi.json' not in paths; "
        "assert '/health' in paths"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT / "server",
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_production_environment_example_requires_secrets() -> None:
    example = (PRODUCTION / "env.production.example").read_text(encoding="utf-8")

    assert "POSTGRES_PASSWORD=replace_with_url_safe_random_value" in example
    assert "WECHAT_APP_SECRET=replace_on_server" in example
    assert "API_TOKEN=" not in example
