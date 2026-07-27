from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_miniprogram_page_utils_node_suite() -> None:
    script = ROOT / "miniprogram" / "tests" / "test_page_utils.js"
    result = subprocess.run(
        ["node", str(script)], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "32 passed, 0 failed" in result.stdout


def test_wxml_custom_components_are_declared() -> None:
    custom_tags = {
        "plan-summary",
        "progress-bar",
        "rating-control",
        "source-drawer",
        "state-view",
    }
    miniprogram = ROOT / "miniprogram"

    for template_path in miniprogram.rglob("*.wxml"):
        template = template_path.read_text(encoding="utf-8")
        used = {tag for tag in custom_tags if f"<{tag}" in template}
        if not used:
            continue
        config_path = template_path.with_suffix(".json")
        config = json.loads(config_path.read_text(encoding="utf-8"))
        declared = set(config.get("usingComponents", {}))
        assert used <= declared, f"{template_path}: missing {sorted(used - declared)}"


def test_study_session_fast_recall_contract() -> None:
    miniprogram = ROOT / "miniprogram"
    page_template = (miniprogram / "pages" / "study-session" / "study-session.wxml").read_text(
        encoding="utf-8"
    )
    page_logic = (miniprogram / "pages" / "study-session" / "study-session.js").read_text(
        encoding="utf-8"
    )
    rating_template = (
        miniprogram / "components" / "rating-control" / "rating-control.wxml"
    ).read_text(encoding="utf-8")

    assert 'data-mode="quick"' in page_template
    assert 'data-mode="writing"' in page_template
    assert 'wx:if="{{writingExpanded}}"' in page_template
    assert '<scroll-view wx:else scroll-y class="task-area">' in page_template
    assert "answer-review-scroll" not in page_template
    assert '<view class="rating-section">' in page_template
    assert '<checkbox-group bindchange="onAnswerPointsChange">' in page_template
    assert 'recommended-rating="{{recommendedRating}}"' in page_template
    assert "quickReview.buildAnswerPayload" in page_logic
    assert "建议 · Again" in rating_template


def test_me_page_allows_wechat_login_without_dev_token() -> None:
    page = ROOT / "miniprogram" / "pages" / "me"
    logic = (page / "me.js").read_text(encoding="utf-8")
    template = (page / "me.wxml").read_text(encoding="utf-8")

    assert "if (!apiBase)" in logic
    assert "if (!apiBase || !token)" not in logic
    assert "服务可达，请点击微信登录" in logic
    assert "开发 Token（可选）" in template
