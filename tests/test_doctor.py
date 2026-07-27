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
from harness.compiler import HARNESS_YAML, STATE_FILE
from harness.doctor import run_doctor
from harness.settings_paths import MANAGED_SETTINGS_FILE, managed_settings_path

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


# ---------------- to_json ----------------

def test_to_json_roundtrips_all_fields(tmp_path: Path) -> None:
    _write_compiled_state(tmp_path, _PIP_VERSION)
    report = run_doctor(tmp_path, plugins_file=tmp_path / "no-such-file.json")
    data = json.loads(report.to_json())
    assert data["pip_version"] == _PIP_VERSION
    assert data["compiled_version"] == _PIP_VERSION
    assert data["ok"] is True
    assert "issues" in data and "notes" in data


# ---------------- clone sem compile / repo movido (item 10 do laudo) ----------------

def _write_harness_yaml(tmp_path: Path) -> None:
    path = tmp_path / HARNESS_YAML
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("version: 1\n", encoding="utf-8")


def _write_managed_settings(tmp_path: Path, hook_script: Path) -> None:
    path = managed_settings_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Edit|Write",
                            "hooks": [
                                {"type": "command", "command": f'python "{hook_script}"'}
                            ],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )


def test_harness_yaml_without_managed_settings_is_issue(tmp_path: Path) -> None:
    """O caso do clone: `harness.yaml` viaja versionado, o settings
    machine-local não. Sem este check o repo parece governado e nenhum hook
    roda — falha silenciosa, que era o motivo do P0."""
    _write_harness_yaml(tmp_path)

    report = run_doctor(tmp_path, plugins_file=tmp_path / "no-such-file.json")

    assert not report.ok
    assert any("harness compile" in i and "clone" in i for i in report.issues)


def test_no_harness_yaml_does_not_demand_compile(tmp_path: Path) -> None:
    """Diretório que não usa o harness não é cobrado — o gate é a config
    versionada, não a ausência do settings."""
    report = run_doctor(tmp_path, plugins_file=tmp_path / "no-such-file.json")

    assert report.ok
    assert not any(MANAGED_SETTINGS_FILE in i for i in report.issues)


def test_hook_command_pointing_to_missing_script_is_issue(tmp_path: Path) -> None:
    """Repo movido de lugar: o comando de hook carrega path absoluto (decisão
    de PLAN.md:180-182) e passa a apontar para um diretório inexistente."""
    _write_harness_yaml(tmp_path)
    _write_managed_settings(tmp_path, tmp_path / "caminho" / "antigo" / "boundary_guard.py")

    report = run_doctor(tmp_path, plugins_file=tmp_path / "no-such-file.json")

    assert not report.ok
    assert any("movido de lugar" in i for i in report.issues)


def test_hook_command_pointing_to_existing_script_is_ok(tmp_path: Path) -> None:
    _write_harness_yaml(tmp_path)
    hook_script = tmp_path / ".harness" / "hooks" / "boundary_guard.py"
    hook_script.parent.mkdir(parents=True, exist_ok=True)
    hook_script.write_text("# hook\n", encoding="utf-8")
    _write_managed_settings(tmp_path, hook_script)
    _write_compiled_state(tmp_path, _PIP_VERSION)

    report = run_doctor(tmp_path, plugins_file=tmp_path / "no-such-file.json")

    assert report.ok, report.issues
