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
    assert "20 passed, 0 failed" in result.stdout


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
