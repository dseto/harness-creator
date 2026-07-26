"""Testes do diagnóstico de consistência de versão (`harness.doctor`).

3 camadas independentes de distribuição podem divergir: pacote pip
(`harness.__version__`, fixo no processo de teste), `.harness/compiled-state.json`
(gravado pelo `harness compile`) e o cache de plugin do Claude Code
(`installed_plugins.json`, aqui sempre um path fake via `plugins_file` —
nunca o `~/.claude/plugins/installed_plugins.json` real da máquina)."""

from __future__ import annotations

import json
from pathlib import Path

import harness
from harness.compiler import STATE_FILE
from harness.doctor import run_doctor
from harness.hook_launcher import hook_command

_PIP_VERSION = harness.__version__


def _write_compiled_state(tmp_path: Path, version: str) -> None:
    path = tmp_path / STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"plugin_version": version}), encoding="utf-8")


def _write_installed_plugins(tmp_path: Path, plugin_id: str, version: str) -> Path:
    path = tmp_path / "installed_plugins.json"
    path.write_text(
        json.dumps(
            {
                "plugins": {
                    plugin_id: [
                        {"installPath": str(tmp_path / "cache"), "version": version}
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    return path


# ---------------- compiled_version ----------------

def test_compiled_version_none_when_never_compiled(tmp_path: Path) -> None:
    report = run_doctor(tmp_path, plugins_file=tmp_path / "no-such-file.json")
    assert report.compiled_version is None
    assert any("ainda não foi compilado" in n for n in report.notes)
    assert report.ok  # nunca compilado é nota, não issue


def test_compiled_version_matching_pip_is_ok(tmp_path: Path) -> None:
    _write_compiled_state(tmp_path, _PIP_VERSION)
    report = run_doctor(tmp_path, plugins_file=tmp_path / "no-such-file.json")
    assert report.compiled_version == _PIP_VERSION
    assert report.ok


def test_compiled_version_mismatch_is_issue(tmp_path: Path) -> None:
    _write_compiled_state(tmp_path, "0.0.1")
    report = run_doctor(tmp_path, plugins_file=tmp_path / "no-such-file.json")
    assert not report.ok
    assert any("harness compile" in i for i in report.issues)


# ---------------- plugin_installs ----------------

def test_no_plugin_installs_found_is_note_not_issue(tmp_path: Path) -> None:
    report = run_doctor(tmp_path, plugins_file=tmp_path / "no-such-file.json")
    assert report.plugin_installs == []
    assert any("nenhuma instalação" in n for n in report.notes)
    assert report.ok


def test_plugin_install_matching_pip_is_ok(tmp_path: Path) -> None:
    plugins_file = _write_installed_plugins(
        tmp_path, "harness-creator@harness-creator-local", _PIP_VERSION
    )
    report = run_doctor(tmp_path, plugins_file=plugins_file)
    assert report.plugin_installs == [
        {
            "id": "harness-creator@harness-creator-local",
            "version": _PIP_VERSION,
            "install_path": str(tmp_path / "cache"),
        }
    ]
    assert report.ok


def test_plugin_install_stale_is_issue_with_fix_command(tmp_path: Path) -> None:
    plugins_file = _write_installed_plugins(
        tmp_path, "harness-creator@harness-creator-local", "0.0.1"
    )
    report = run_doctor(tmp_path, plugins_file=plugins_file)
    assert not report.ok
    assert any(
        "claude plugin update harness-creator@harness-creator-local" in i
        for i in report.issues
    )


def test_plugin_install_of_other_plugin_is_ignored(tmp_path: Path) -> None:
    plugins_file = _write_installed_plugins(tmp_path, "outro-plugin@marketplace", "0.0.1")
    report = run_doctor(tmp_path, plugins_file=plugins_file)
    assert report.plugin_installs == []
    assert report.ok


# ---------------- interpretador dos hooks ----------------
# Item 1 do backlog do dogfood Savant.Backend: hook com interpretador
# irresolúvel não roda, e a tool call PASSA sem gate. É estado silencioso em
# runtime — o `doctor` é o único lugar onde ele fica visível.

def _write_settings_with_hook(tmp_path: Path, command: str, event: str = "PreToolUse") -> None:
    path = tmp_path / ".claude" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"hooks": {event: [{"matcher": "*", "hooks": [
            {"type": "command", "command": command}
        ]}]}}),
        encoding="utf-8",
    )


def test_hook_with_baked_interpreter_is_ok(tmp_path: Path) -> None:
    _write_settings_with_hook(
        tmp_path, hook_command(tmp_path / ".harness" / "hooks" / "boundary_guard.py")
    )
    report = run_doctor(tmp_path, plugins_file=tmp_path / "no-such-file.json")
    assert len(report.hooks) == 1
    assert report.hooks[0]["ok"] is True
    assert report.hooks[0]["event"] == "PreToolUse"
    assert report.ok


def test_hook_with_bare_python_is_issue(tmp_path: Path) -> None:
    _write_settings_with_hook(tmp_path, 'python ".harness/hooks/boundary_guard.py"')
    report = run_doctor(tmp_path, plugins_file=tmp_path / "no-such-file.json")
    assert not report.ok
    assert report.hooks[0]["ok"] is False
    assert any("PreToolUse" in i and "compile-session" in i for i in report.issues)


def test_hook_with_dead_interpreter_is_issue(tmp_path: Path) -> None:
    ghost = tmp_path / ".venv" / "Scripts" / "python.exe"
    _write_settings_with_hook(
        tmp_path, f'"{ghost}" ".harness/hooks/stop_hook.py"', event="Stop"
    )
    report = run_doctor(tmp_path, plugins_file=tmp_path / "no-such-file.json")
    assert not report.ok
    assert any("não existe mais em disco" in i for i in report.issues)


def test_third_party_hook_is_ignored(tmp_path: Path) -> None:
    # Não cabe ao doctor opinar sobre hooks que não são deste pacote — mesmo
    # que estejam com interpretador nu.
    _write_settings_with_hook(tmp_path, 'python "outro_plugin/hook.py"')
    report = run_doctor(tmp_path, plugins_file=tmp_path / "no-such-file.json")
    assert report.hooks == []
    assert report.ok


def test_malformed_settings_does_not_raise(tmp_path: Path) -> None:
    path = tmp_path / ".claude" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ nao é json", encoding="utf-8")
    report = run_doctor(tmp_path, plugins_file=tmp_path / "no-such-file.json")
    assert report.hooks == []
    assert report.ok


def test_no_settings_file_yields_no_hooks(tmp_path: Path) -> None:
    report = run_doctor(tmp_path, plugins_file=tmp_path / "no-such-file.json")
    assert report.hooks == []
    assert report.ok


# ---------------- to_json ----------------

def test_to_json_roundtrips_all_fields(tmp_path: Path) -> None:
    _write_compiled_state(tmp_path, _PIP_VERSION)
    report = run_doctor(tmp_path, plugins_file=tmp_path / "no-such-file.json")
    data = json.loads(report.to_json())
    assert data["pip_version"] == _PIP_VERSION
    assert data["compiled_version"] == _PIP_VERSION
    assert data["ok"] is True
    assert "issues" in data and "notes" in data
    assert data["hooks"] == []
