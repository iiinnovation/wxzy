from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "miniprogram" / "tests" / "test_auth_client.js"


def test_miniprogram_auth_client_node_suite() -> None:
    assert SCRIPT.is_file()
    result = subprocess.run(
        ["node", str(SCRIPT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(
            "miniprogram auth client tests failed\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    assert "passed" in result.stdout
    assert "failed" in result.stdout
