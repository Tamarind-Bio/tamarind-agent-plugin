from __future__ import annotations

import json
import stat
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = (
    ROOT
    / "plugins/tamarind/skills/tamarind-submit-and-poll/scripts/safe_status.py"
)


def _fake_cli(tmp_path: Path, source: str) -> Path:
    executable = tmp_path / "fake-tamarind"
    executable.write_text(f"#!/usr/bin/env python3\n{source}")
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    return executable


def _run(helper: Path, cli: Path, job_name: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(helper), job_name, "--cli", str(cli)],
        text=True,
        capture_output=True,
        check=False,
    )


def test_safe_status_redacts_nested_urls_without_using_a_shell(tmp_path: Path) -> None:
    cli = _fake_cli(
        tmp_path,
        """import json
import sys

print(json.dumps({
    "JobName": sys.argv[-1],
    "resultUrl": "https://secret.example/result",
    "nested": {"uploadUrl": "https://secret.example/upload", "keep": 2},
    "items": [{"headUrl": "https://secret.example/head", "ok": True}],
}))
""",
    )
    marker = tmp_path / "must-not-exist"
    hostile_name = f"job; touch {marker}"

    result = _run(HELPER, cli, hostile_name)

    assert result.returncode == 0, result.stderr
    assert not marker.exists()
    assert "secret.example" not in result.stdout
    payload = json.loads(result.stdout)
    assert payload["JobName"] == hostile_name
    assert payload["redactedFields"] == ["resultUrl"]
    assert payload["nested"] == {"keep": 2, "redactedFields": ["uploadUrl"]}
    assert payload["items"] == [{"ok": True, "redactedFields": ["headUrl"]}]


def test_safe_status_preserves_cli_error_and_discards_stdout(tmp_path: Path) -> None:
    cli = _fake_cli(
        tmp_path,
        """import sys

print("https://secret.example/partial")
print("error: Job missing not found", file=sys.stderr)
raise SystemExit(4)
""",
    )

    result = _run(HELPER, cli, "missing")

    assert result.returncode == 4
    assert result.stdout == ""
    assert result.stderr == "error: Job missing not found\n"
    assert "Traceback" not in result.stderr
    assert "secret.example" not in result.stdout + result.stderr


def test_safe_status_rejects_malformed_success_without_echoing_it(
    tmp_path: Path,
) -> None:
    cli = _fake_cli(
        tmp_path,
        'print("not-json https://secret.example/result")\n',
    )

    result = _run(HELPER, cli, "malformed")

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == (
        "error: Tamarind CLI status succeeded without valid JSON output\n"
    )
    assert "Traceback" not in result.stderr
    assert "secret.example" not in result.stdout + result.stderr
