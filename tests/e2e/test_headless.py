"""E2E: harness compilado + Claude Code real em modo headless (`claude -p`).

Diferente do resto da suíte E2E (que só exercita nossos próprios hooks/CLI),
isto invoca o binário `claude` de verdade — custa tokens reais e exige CLI
instalada/autenticada. Por isso é OPT-IN via HARNESS_E2E_HEADLESS=1, e
sempre com --output-format json + timeout (nunca sem timeout, mesmo já
tendo confirmado empiricamente que -p não trava sem TTY).

Achado que este teste documenta: em `-p` sem TTY, uma ação `ask` é negada
automaticamente e a sessão SEGUE ATÉ O FIM (exit code 0, sem hang) — mas o
exit code não sinaliza o bloqueio. O sinal real está no campo
`permission_denials` do JSON de saída.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from harness.compiler import compile_project

pytestmark = pytest.mark.skipif(
    os.environ.get("HARNESS_E2E_HEADLESS") != "1",
    reason="opt-in: custa tokens reais e exige `claude` CLI autenticada "
           "(rode com HARNESS_E2E_HEADLESS=1)",
)

HARNESS_YAML = """\
governance:
  approval_policy: balanced
verification:
  enforce_tdd: true
  test_command: "dotnet test"
  test_glob: "MinimumAPI.Tests/**/*.cs"
"""


@pytest.fixture(autouse=True)
def _require_claude_cli():
    if shutil.which("claude") is None:
        pytest.skip("binário `claude` não encontrado no PATH")


def _init(project: Path) -> None:
    path = project / ".harness" / "harness.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(HARNESS_YAML, encoding="utf-8")


def _run_headless(cwd: Path, prompt: str) -> dict:
    proc = subprocess.run(
        ["claude", "-p", prompt, "--output-format", "json"],
        cwd=str(cwd), capture_output=True, text=True, timeout=90,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_headless_edit_on_gated_file_is_denied_not_hung(api_project: Path) -> None:
    _init(api_project)
    compile_project(api_project)

    out = _run_headless(
        api_project,
        "adiciona um comentário no topo do arquivo MinimumAPI/Program.cs "
        "dizendo // teste headless",
    )

    assert out["is_error"] is False           # nunca trava / nunca crasha
    denials = out["permission_denials"]
    assert any(d["tool_name"] == "Edit" for d in denials), out


def test_headless_read_only_task_has_no_denials(api_project: Path) -> None:
    _init(api_project)
    compile_project(api_project)

    out = _run_headless(
        api_project,
        "lê o arquivo MinimumAPI/Program.cs e diz em uma frase o que ele faz",
    )

    assert out["is_error"] is False
    assert out["permission_denials"] == []    # read liberado em balanced
