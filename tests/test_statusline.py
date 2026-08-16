"""Testes de `harness.statusline` — a linha sempre visível na barra do CLI.

T-03 do contrato `placar-de-andamento`. O hook gerado é standalone
(stdlib-only, não importa `harness`) porque roda fora do venv do projeto,
igual a `session_start`/`stop_hook`/`boundary_guard`. Por isso os testes
EXECUTAM o artefato de verdade, com stdin de mentira: testar uma cópia da
lógica em vez do arquivo gerado deixaria o arquivo gerado sem prova nenhuma.

Contrato do Claude Code confirmado na documentação oficial
(https://code.claude.com/docs/en/statusline): a chave é `statusLine`, com
`type: "command"` e `command`; o stdin traz `cost.total_cost_usd` e
`context_window.used_percentage`, entre outros.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from harness.attempts import attempts_path
from harness.settings_paths import managed_settings_path
from harness.statusline import (
    HOOK_FILENAME,
    SESSION_STATE_FILE,
    STATE_KEY,
    install_statusline,
    render_statusline_hook,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_contract(tmp_path: Path, features: list[dict[str, Any]], contract: str = "demo") -> None:
    _write(
        tmp_path / ".harness" / "feature_list.json",
        json.dumps({"contract": contract, "features": features}, ensure_ascii=False),
    )


def _feature(feature_id: str, desc: str, *, passes: bool = False) -> dict[str, Any]:
    return {
        "id": feature_id,
        "desc": desc,
        "files": ["src/x.py"],
        "verify_cmd": "pytest -q",
        "depends": [],
        "passes": passes,
    }


def _run_hook(tmp_path: Path, payload: str | None) -> subprocess.CompletedProcess[str]:
    hook = tmp_path / ".harness" / "hooks" / HOOK_FILENAME
    _write(hook, render_statusline_hook())
    return subprocess.run(
        [sys.executable, str(hook)],
        input="" if payload is None else payload,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# REGRA 1 — a linha responde, num relance, onde a sessão está
# ---------------------------------------------------------------------------

def test_line_carries_demand_progress_task_attempt_and_last_verdict(tmp_path: Path) -> None:
    _write_contract(
        tmp_path,
        [
            _feature("T-01", "primeira fatia", passes=True),
            _feature("T-02", "escrever a statusline"),
            _feature("T-03", "outra coisa"),
        ],
    )
    _write(
        attempts_path(tmp_path, "demo", "T-02"),
        json.dumps(
            {
                "result": "fail",
                "recorded_at": "t",
                "failure_line": "E   AssertionError: quebrou",
                "classification": "structural",
            }
        )
        + "\n",
    )

    result = _run_hook(tmp_path, json.dumps({"workspace": {"current_dir": str(tmp_path)}}))

    assert result.returncode == 0
    line = result.stdout.strip()
    assert "\n" not in line               # UMA linha: é uma barra, não um painel
    assert "demo" in line                 # qual demanda
    assert "1/3" in line                   # onde estou
    assert "T-02" in line                  # o que está sendo feito
    assert "2" in line                     # tentativa 2 (uma falha registrada)
    assert "AssertionError" in line or "falhou" in line  # como foi a última prova


def test_all_done_line_says_the_demand_is_finished(tmp_path: Path) -> None:
    _write_contract(tmp_path, [_feature("T-01", "única", passes=True)])

    result = _run_hook(tmp_path, json.dumps({"workspace": {"current_dir": str(tmp_path)}}))

    assert result.returncode == 0
    assert "1/1" in result.stdout


# ---------------------------------------------------------------------------
# REGRA 2 — o custo é render de dado que o CLI já empurra: presente aparece,
# ausente não quebra a linha
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StdinCase:
    payload: str | None
    expect_cost: bool
    why: str


STDIN_CASES = [
    StdinCase(json.dumps({"cost": {"total_cost_usd": 1.2345}}), True, "com custo: aparece"),
    StdinCase(json.dumps({"cost": {}}), False, "cost sem o campo: linha sem custo"),
    StdinCase(json.dumps({}), False, "sem cost nenhum: linha sem custo"),
    StdinCase("", False, "stdin vazio: linha sem custo"),
    StdinCase("isto não é json", False, "stdin corrompido: linha sem custo"),
]


@pytest.mark.parametrize("case", STDIN_CASES, ids=lambda c: c.why)
def test_session_cost_is_optional_and_never_breaks_the_line(
    tmp_path: Path, case: StdinCase
) -> None:
    _write_contract(tmp_path, [_feature("T-01", "tarefa")])

    result = _run_hook(tmp_path, case.payload)

    assert result.returncode == 0
    assert result.stdout.strip()          # sempre sai uma linha
    assert ("$" in result.stdout) is case.expect_cost
    if case.expect_cost:
        assert "1.23" in result.stdout


def test_hook_survives_a_repo_without_any_contract(tmp_path: Path) -> None:
    result = _run_hook(tmp_path, json.dumps({}))

    assert result.returncode == 0
    assert result.stdout.strip()


def test_hook_is_stdlib_only_and_never_imports_harness(tmp_path: Path) -> None:
    source = render_statusline_hook()

    assert "import harness" not in source
    assert "from harness" not in source


# ---------------------------------------------------------------------------
# REGRA 3 — instalar registra a entrada `statusLine` no settings machine-local
# e recompilar não duplica nem deixa órfã
# ---------------------------------------------------------------------------

def test_install_registers_status_line_with_an_absolute_interpreter(tmp_path: Path) -> None:
    hook_path = install_statusline(tmp_path)

    assert hook_path.is_file()
    settings = json.loads(managed_settings_path(tmp_path).read_text(encoding="utf-8"))
    entry = settings["statusLine"]
    assert entry["type"] == "command"
    assert HOOK_FILENAME in entry["command"]
    # Interpretador ABSOLUTO bakeado: a barra do CLI não roda com o PATH do
    # projeto, e um `python` nu ali é o modo de falha do dogfood venv-Windows.
    assert Path(entry["command"].split('"')[1] if '"' in entry["command"] else
                entry["command"].split()[0]).is_absolute()

    state = json.loads((tmp_path / SESSION_STATE_FILE).read_text(encoding="utf-8"))
    assert state[STATE_KEY] == entry["command"]


def test_installing_twice_leaves_exactly_one_entry(tmp_path: Path) -> None:
    install_statusline(tmp_path)
    first = json.loads(managed_settings_path(tmp_path).read_text(encoding="utf-8"))["statusLine"]

    install_statusline(tmp_path)
    settings = json.loads(managed_settings_path(tmp_path).read_text(encoding="utf-8"))

    assert settings["statusLine"] == first
    assert isinstance(settings["statusLine"], dict)


def test_install_replaces_a_stale_entry_from_a_previous_compilation(tmp_path: Path) -> None:
    settings_path = managed_settings_path(tmp_path)
    _write(
        settings_path,
        json.dumps({"statusLine": {"type": "command", "command": "python velho/statusline.py"}}),
    )

    install_statusline(tmp_path)

    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "velho" not in settings["statusLine"]["command"]
    assert HOOK_FILENAME in settings["statusLine"]["command"]


def test_install_preserves_settings_written_by_the_other_installers(tmp_path: Path) -> None:
    settings_path = managed_settings_path(tmp_path)
    _write(
        settings_path,
        json.dumps({"permissions": {"allow": ["Bash(pytest:*)"]}, "hooks": {"SessionStart": []}}),
    )

    install_statusline(tmp_path)

    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert settings["permissions"]["allow"] == ["Bash(pytest:*)"]
    assert "SessionStart" in settings["hooks"]


def test_a_user_written_status_line_is_not_silently_replaced(tmp_path: Path) -> None:
    """Entrada que o harness não instalou (não está no compiled-state) é do
    usuário — o compilador administra o que ele mesmo escreveu, e sobrescrever
    a barra que a pessoa configurou seria o harness decidindo por ela."""
    settings_path = managed_settings_path(tmp_path)
    mine = {"type": "command", "command": "meu-script-pessoal.sh"}
    _write(settings_path, json.dumps({"statusLine": mine}))

    hook_path = install_statusline(tmp_path, replace_foreign=False)

    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert settings["statusLine"] == mine
    assert hook_path.is_file()   # o hook é gravado assim mesmo, só não é registrado


# ---------------------------------------------------------------------------
# REGRA 4 — `compile-session` instala a statusline junto com os outros hooks
# ---------------------------------------------------------------------------

def test_compile_session_installs_the_status_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from harness.cli import main

    _write_contract(tmp_path, [_feature("T-01", "tarefa")])
    _write(tmp_path / "pyproject.toml", '[project]\nname = "x"\n')
    (tmp_path / "tests").mkdir(exist_ok=True)
    # T-01 (contrato setup-fail-closed-sem-init): compile-session exige
    # harness.yaml -- este teste cobre a instalação da statusline, não o
    # gate de setup, então simula um repo que já rodou \harness-creator:init
    # (mesmo padrão de tests/test_cli.py e tests/test_contract.py).
    _write(tmp_path / ".harness" / "harness.yaml", "governance:\n  approval_policy: default\n")

    monkeypatch.setattr(sys, "argv", ["harness", "compile-session", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert HOOK_FILENAME in payload["statusline_hook"]
    assert (tmp_path / ".harness" / "hooks" / HOOK_FILENAME).is_file()
