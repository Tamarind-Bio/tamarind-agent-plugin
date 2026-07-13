from __future__ import annotations

import json
import stat
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "plugins/tamarind/skills/tamarind-api-setup/scripts/safe_auth.py"


def _fake_cli(tmp_path: Path, source: str) -> Path:
    executable = tmp_path / "fake-tamarind"
    executable.write_text(f"#!/usr/bin/env python3\n{source}")
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    return executable


def _run(helper: Path, cli: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(helper), "--cli", str(cli)],
        text=True,
        capture_output=True,
        check=False,
    )


def test_safe_auth_allowlists_fields_and_removes_key_fragments(tmp_path: Path) -> None:
    cli = _fake_cli(
        tmp_path,
        """import json

print(json.dumps({
    "profile": "default",
    "apiKey": "code…alid",
    "hasKey": True,
    "verified": True,
    "apiBase": "https://api.example/",
    "catalogBase": "https://catalog.example/?X-Amz-Signature=must-not-leak-either",
    "futureCredential": "must-not-leak",
}))
""",
    )

    result = _run(HELPER, cli)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload == {
        "hasKey": True,
        "verified": True,
    }
    assert "code" not in result.stdout
    assert "must-not-leak" not in result.stdout
    assert "apiBase" not in result.stdout
    assert "catalogBase" not in result.stdout
    assert "profile" not in result.stdout


def test_safe_auth_preserves_cli_errors_without_parsing_stdout(tmp_path: Path) -> None:
    cli = _fake_cli(
        tmp_path,
        """import sys

print('{"apiKey":"must-not-leak"}')
print("error: authentication failed", file=sys.stderr)
raise SystemExit(3)
""",
    )

    result = _run(HELPER, cli)

    assert result.returncode == 3
    assert result.stdout == ""
    assert result.stderr == "error: authentication failed\n"
    assert "must-not-leak" not in result.stdout + result.stderr
