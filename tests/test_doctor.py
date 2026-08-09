"""Testes do diagnóstico de consistência de versão (`harness.doctor`).

3 camadas independentes de distribuição podem divergir: pacote pip
(`harness.__version__`, fixo no processo de teste), `.harness/compiled-state.json`
(gravado pelo `harness compile`) e o cache de plugin do Claude Code
(`installed_plugins.json`, aqui sempre um path fake via `plugins_file` —
nunca o `~/.claude/plugins/installed_plugins.json` real da máquina)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

import harness
from harness.compiler import HARNESS_YAML, STATE_FILE
from harness.doctor import run_doctor, stale_plugin_installs
from harness.settings_paths import MANAGED_SETTINGS_FILE, managed_settings_path
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

def test_a_directory_that_does_not_use_the_harness_is_never_scolded(tmp_path: Path) -> None:
    """Diretório cru: nunca compilado, sem settings, sem instalação de plugin.
    Tudo isso é NOTA, não issue — o gate do doctor é a config versionada
    (`harness.yaml`), não a ausência do estado de máquina."""
    report = run_doctor(tmp_path, plugins_file=tmp_path / "no-such-file.json")

    assert report.ok
    assert report.compiled_version is None
    assert any("ainda não foi compilado" in n for n in report.notes)
    assert report.plugin_installs == []
    assert any("nenhuma instalação" in n for n in report.notes)
    assert report.hooks == []
    assert not any(MANAGED_SETTINGS_FILE in i for i in report.issues)


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
def test_doctor_flags_an_allowlist_the_hook_cannot_read(tmp_path: Path) -> None:
    """Postura C do Item 9: liberar comando é editar o YAML à mão. Uma entrada
    em sintaxe que o parser mínimo do hook não entende vira deny SILENCIOSO — e
    derruba a lista inteira junto. O `compile-session` avisa, mas o Item 3 o
    tornou desnecessário justamente para esse fluxo: quem só edita o YAML nunca
    veria o aviso. O `doctor` é o comando que a pessoa roda quando desconfia."""
    from harness.doctor import run_doctor

    harness_yaml = tmp_path / ".harness" / "harness.yaml"
    harness_yaml.parent.mkdir(parents=True, exist_ok=True)
    harness_yaml.write_text(
        "governance:\n  extra_allowed_commands:\n    - &ancora alembic upgrade\n",
        encoding="utf-8",
    )

    report = run_doctor(tmp_path)

    assert any("extra_allowed_commands" in issue for issue in report.issues), report.issues
    assert report.ok is False


def test_doctor_silent_when_the_allowlist_parses(tmp_path: Path) -> None:
    from harness.doctor import run_doctor

    harness_yaml = tmp_path / ".harness" / "harness.yaml"
    harness_yaml.parent.mkdir(parents=True, exist_ok=True)
    harness_yaml.write_text(
        "governance:\n  extra_allowed_commands:\n    - alembic upgrade\n",
        encoding="utf-8",
    )

    report = run_doctor(tmp_path)

    assert not any("extra_allowed_commands" in issue for issue in report.issues), report.issues


# Item 1 do backlog do dogfood venv-Windows: hook com interpretador
# irresolúvel não roda, e a tool call PASSA sem gate. É estado silencioso em
# runtime — o `doctor` é o único lugar onde ele fica visível.

def _write_settings_with_hook(tmp_path: Path, command: str, event: str = "PreToolUse") -> None:
    # O script precisa existir em disco: um comando de hook apontando para
    # script ausente é, por si só, uma instalação quebrada (repo movido de
    # lugar) e o `doctor` reporta isso separadamente.
    for script in re.findall(r'"([^"]+\.py)"', command):
        script_path = Path(script)
        # Só path ABSOLUTO (o que `hook_command` produz). Path relativo nestes
        # fixtures é string de formato legado, não arquivo — criá-lo escreveria
        # na raiz do repo do produto, porque resolve contra o cwd do pytest.
        if not script_path.is_absolute():
            continue
        script_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.write_text("# hook" + chr(10), encoding="utf-8")

    path = tmp_path / ".claude" / "settings.local.json"
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
    path = tmp_path / ".claude" / "settings.local.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ nao é json", encoding="utf-8")
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
                                {"type": "command", "command": hook_command(hook_script)}
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
    # O hook e NOSSO e o script existe: nada a reportar sobre ele.
    assert report.hooks[0]["ok"] is True


def test_hook_without_fail_closed_suffix_is_reported(tmp_path: Path) -> None:
    """Item 1b: hook compilado por versão <= 0.17.7 tem o interpretador certo
    mas não tem o `|| exit 2` — falha ABERTO se o processo não iniciar. O
    interpretador está vivo, então só o segundo check dispara."""
    import sys

    _write_settings_with_hook(tmp_path, f'"{sys.executable}" ".harness/hooks/boundary_guard.py"')
    report = run_doctor(tmp_path, plugins_file=tmp_path / "no-such-file.json")
    assert report.hooks[0]["ok"] is False
    assert "exit 2" in report.hooks[0]["problem"]
    assert any("exit 2" in issue for issue in report.issues)


def test_hook_with_both_problems_reports_both(tmp_path: Path) -> None:
    """Formato totalmente legado: interpretador nu E sem sufixo. Os dois
    problemas são independentes e precisam aparecer juntos — corrigir só um
    deixaria o fail-open de pé."""
    _write_settings_with_hook(tmp_path, 'python ".harness/hooks/session_start.py"')
    report = run_doctor(tmp_path, plugins_file=tmp_path / "no-such-file.json")
    problem = report.hooks[0]["problem"]
    assert "PATH" in problem
    assert "exit 2" in problem


# ---------------- issue #72: governança parcial sem harness.yaml ----------------

def test_feature_list_without_harness_yaml_is_a_note_not_an_issue(tmp_path: Path) -> None:
    """Sessão compilada (`feature_list.json`) sem `harness.yaml` nunca rodou
    `/harness-creator:init` — TDD e política de aprovação ficaram de fora.
    É NOTA (doctor continua `ok`), não issue: `compile-session` funciona sem
    o yaml de propósito."""
    feature_list_path = tmp_path / ".harness" / "feature_list.json"
    feature_list_path.parent.mkdir(parents=True, exist_ok=True)
    feature_list_path.write_text("{}", encoding="utf-8")

    report = run_doctor(tmp_path, plugins_file=tmp_path / "no-such-file.json")

    assert report.ok
    assert any(".harness/harness.yaml" in n and "/harness-creator:init" in n for n in report.notes)


def test_feature_list_with_harness_yaml_present_has_no_partial_governance_note(tmp_path: Path) -> None:
    feature_list_path = tmp_path / ".harness" / "feature_list.json"
    feature_list_path.parent.mkdir(parents=True, exist_ok=True)
    feature_list_path.write_text("{}", encoding="utf-8")
    (tmp_path / HARNESS_YAML).write_text("governance:\n  approval_policy: default\n", encoding="utf-8")

    report = run_doctor(tmp_path, plugins_file=tmp_path / "no-such-file.json")

    assert not any("/harness-creator:init" in n for n in report.notes)


# ---------------- T-01: cache de plugin atrasado, reutilizável fora do laudo ----------------
#
# O hook `SessionStart` precisa da MESMA comparação para avisar na abertura da
# sessão, e ele não pode importar o laudo inteiro. A função existe para não
# nascer uma segunda regra de versão capaz de divergir desta.

def _installed_plugins(tmp_path: Path, entries: dict[str, str]) -> Path:
    path = tmp_path / "installed_plugins.json"
    path.write_text(
        json.dumps({
            "plugins": {
                plugin_id: [{"installPath": str(tmp_path / "cache"), "version": version}]
                for plugin_id, version in entries.items()
            }
        }),
        encoding="utf-8",
    )
    return path


@dataclass(frozen=True)
class StaleCase:
    cached: str
    installed: str
    expect_stale: bool
    why: str


STALE_CASES = [
    StaleCase("0.30.0", "0.31.0", True, "cache atras: e o caso alvo"),
    StaleCase("0.9.0", "0.10.0", True, "atras em semver, a frente em ordem alfabetica"),
    StaleCase("0.31.0", "0.31.0", False, "em dia"),
    StaleCase("0.32.0", "0.31.0", False, "cache a frente: update nao corrige isso"),
    StaleCase("0.31", "0.31.0", False, "componente omitido equivale a zero"),
    StaleCase("nao-e-versao", "0.31.0", False, "versao ilegivel: nao afirmar defasagem"),
]


@pytest.mark.parametrize("case", STALE_CASES, ids=lambda c: c.why)
def test_only_a_plugin_behind_the_installed_package_is_reported(
    tmp_path: Path, case: StaleCase
) -> None:
    plugins_file = _installed_plugins(tmp_path, {"harness-creator@local": case.cached})

    stale = stale_plugin_installs(case.installed, plugins_file=plugins_file)

    assert bool(stale) is case.expect_stale


def test_a_stale_plugin_carries_the_exact_command_that_fixes_it() -> None:
    """O valor da função é entregar o comando pronto — quem consome (hook de
    sessão) não pode ter de montar a string do id."""
    import harness.doctor as doctor_module

    entry = {"id": "harness-creator@harness-creator-local", "version": "0.30.0"}
    command = doctor_module.plugin_update_command(entry["id"])

    assert command == "claude plugin update harness-creator@harness-creator-local"


def test_the_reported_entry_has_id_versions_and_command(tmp_path: Path) -> None:
    plugins_file = _installed_plugins(tmp_path, {"harness-creator@marketplace": "0.30.0"})

    stale = stale_plugin_installs("0.31.0", plugins_file=plugins_file)

    assert len(stale) == 1
    entry = stale[0]
    assert entry["id"] == "harness-creator@marketplace"
    assert entry["version"] == "0.30.0"
    assert entry["installed_version"] == "0.31.0"
    assert entry["command"] == "claude plugin update harness-creator@marketplace"


@dataclass(frozen=True)
class SilentCase:
    write: object
    why: str


SILENT_CASES = [
    SilentCase(None, "arquivo ausente: normal em quem usa --plugin-dir ou so pip"),
    SilentCase("{ nao e json", "json invalido nunca vira afirmacao de defasagem"),
    SilentCase(json.dumps({"plugins": {}}), "nenhum plugin registrado"),
    SilentCase(json.dumps({"plugins": {"outro-plugin@x": [{"version": "0.1.0"}]}}),
               "plugin de terceiro nao e problema deste pacote"),
]


@pytest.mark.parametrize("case", SILENT_CASES, ids=lambda c: c.why)
def test_nothing_is_reported_when_there_is_nothing_to_say(
    tmp_path: Path, case: SilentCase
) -> None:
    plugins_file = tmp_path / "installed_plugins.json"
    if case.write is not None:
        plugins_file.write_text(str(case.write), encoding="utf-8")

    assert stale_plugin_installs("0.31.0", plugins_file=plugins_file) == []


def test_the_plugins_file_can_be_pointed_elsewhere_through_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sem este seam, exercitar o caminho real através do subprocesso do hook
    exigiria escrever no `~/.claude` de quem roda a suíte."""
    from harness.doctor import INSTALLED_PLUGINS_ENV

    plugins_file = _installed_plugins(tmp_path, {"harness-creator@local": "0.0.1"})
    monkeypatch.setenv(INSTALLED_PLUGINS_ENV, str(plugins_file))

    stale = stale_plugin_installs("0.31.0")

    assert len(stale) == 1
    assert stale[0]["version"] == "0.0.1"


def test_a_plugin_ahead_of_the_package_is_a_note_with_the_other_fix(tmp_path: Path) -> None:
    """`stale_plugin_installs` cala nesse caso porque `claude plugin update`
    não corrige — mas o `doctor` existe para mostrar divergência, e omitir
    esconderia um estado real. Nota, não issue: a correção é do outro lado."""
    plugins_file = _installed_plugins(tmp_path, {"harness-creator@local": "99.0.0"})

    report = run_doctor(tmp_path, plugins_file=plugins_file)

    assert not any("claude plugin update" in i for i in report.issues)
    assert any("pip install --upgrade" in n for n in report.notes)


def test_the_doctor_report_uses_the_same_function_it_exposes(tmp_path: Path) -> None:
    """Se o laudo mantivesse a comparação própria, as duas regras poderiam
    divergir — que é exatamente o defeito que este contrato remove."""
    plugins_file = _installed_plugins(tmp_path, {"harness-creator@local": "0.0.1"})

    report = run_doctor(tmp_path, plugins_file=plugins_file)
    stale = stale_plugin_installs(_PIP_VERSION, plugins_file=plugins_file)

    assert stale
    assert not report.ok
    assert any(stale[0]["command"] in issue for issue in report.issues)
