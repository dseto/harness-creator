"""Diagnóstico de consistência de versão entre as 3 camadas de distribuição
do harness-creator — comando `harness doctor`.

O plugin chega ao usuário por 3 caminhos independentes, cada um com seu
próprio ciclo de atualização:

    1. pacote Python instalado (pip)   -> harness.__version__
    2. `.harness/` compilado           -> `plugin_version` gravado pelo
       último `harness compile` em `.harness/compiled-state.json`
    3. cache de plugin do Claude Code  -> `~/.claude/plugins/installed_plugins.json`

Atualizar só uma camada (ex.: `pip install --upgrade` sem rodar `harness
compile` de novo, ou sem rodar `claude plugin update`) deixa as outras
presas na versão antiga sem sinal nenhum — o comportamento observado no
Claude Code (hooks, skills) reflete a camada mais atrasada. `doctor` não
previne isso sozinho: é um diagnóstico sob demanda, rodado pelo usuário
depois de atualizar, que aponta exatamente qual camada ficou pra trás e o
comando exato para corrigir.

**Quarta verificação — interpretador dos hooks** (Item 1 do backlog do
dogfood `Savant.Backend.APP-15167`). Divergência de versão não é o único
estado silencioso: um hook registrado com interpretador irresolúvel
(`python` nu que o PATH de runtime não acha, ou caminho absoluto de um venv
que foi recriado) simplesmente NÃO RODA — e, pela semântica de exit code de
hook do Claude Code, a tool call PASSA sem gate nenhum. É a falha mais
perigosa que este módulo pode diagnosticar, porque o sintoma runtime é uma
linha de `hook error` no transcript e nada mais. Ver `harness.hook_launcher`
para o mecanismo e o risco residual.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from harness import __version__ as _PIP_VERSION
from harness.compiler import STATE_FILE
from harness.hook_launcher import interpreter_problem

PLUGIN_NAME = "harness-creator"
DEFAULT_INSTALLED_PLUGINS_FILE = Path.home() / ".claude" / "plugins" / "installed_plugins.json"

SETTINGS_FILE = ".claude/settings.json"

# Nomes dos scripts de hook gerados por este pacote. Um `command` do
# `settings.json` que cite qualquer um deles é NOSSO e tem o interpretador
# verificado; hooks de terceiros no mesmo arquivo são ignorados (não cabe ao
# `doctor` opinar sobre eles).
MANAGED_HOOK_FILENAMES = ("boundary_guard.py", "session_start.py", "stop_hook.py")


@dataclass
class DoctorReport:
    pip_version: str
    compiled_version: str | None
    plugin_installs: list[dict]
    issues: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    hooks: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def to_json(self) -> str:
        return json.dumps(
            {
                "pip_version": self.pip_version,
                "compiled_version": self.compiled_version,
                "plugin_installs": self.plugin_installs,
                "hooks": self.hooks,
                "ok": self.ok,
                "issues": self.issues,
                "notes": self.notes,
            },
            indent=2,
            ensure_ascii=False,
        )


def _read_compiled_version(target_dir: Path) -> str | None:
    path = target_dir / STATE_FILE
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return None
    return data.get("plugin_version")


def _read_plugin_installs(plugins_file: Path) -> list[dict]:
    if not plugins_file.is_file():
        return []
    try:
        data = json.loads(plugins_file.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return []
    installs = []
    for plugin_id, entries in (data.get("plugins") or {}).items():
        if plugin_id.split("@", 1)[0] != PLUGIN_NAME:
            continue
        for entry in entries:
            installs.append(
                {
                    "id": plugin_id,
                    "version": entry.get("version"),
                    "install_path": entry.get("installPath"),
                }
            )
    return installs


def _read_managed_hooks(target_dir: Path) -> list[dict]:
    """Lista os hooks DESTE pacote registrados em `.claude/settings.json`,
    cada um com o veredito do seu interpretador.

    Degradação graciosa idêntica aos demais leitores deste módulo (arquivo
    ausente ou JSON inválido -> lista vazia): `doctor` nunca lança por causa
    de um settings.json malformado — nesse caso a ausência de hooks vira
    nota, não issue, porque não dá pra distinguir "malformado" de "projeto
    que não usa o harness"."""
    path = target_dir / SETTINGS_FILE
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict):
        return []

    found: list[dict] = []
    hooks_section = data.get("hooks")
    if not isinstance(hooks_section, dict):
        return []
    for event, entries in hooks_section.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            for hook in entry.get("hooks") or []:
                if not isinstance(hook, dict):
                    continue
                command = hook.get("command") or ""
                if not any(name in command for name in MANAGED_HOOK_FILENAMES):
                    continue
                problem = interpreter_problem(command)
                found.append(
                    {
                        "event": event,
                        "command": command,
                        "ok": problem is None,
                        "problem": problem,
                    }
                )
    return found


def run_doctor(
    target_dir: Path,
    plugins_file: Path | None = None,
) -> DoctorReport:
    compiled_version = _read_compiled_version(target_dir)
    plugin_installs = _read_plugin_installs(plugins_file or DEFAULT_INSTALLED_PLUGINS_FILE)
    hooks = _read_managed_hooks(target_dir)

    issues: list[str] = []
    notes: list[str] = []

    for hook in hooks:
        if hook["problem"]:
            issues.append(f"hook `{hook['event']}`: {hook['problem']}")

    if compiled_version is None:
        notes.append(
            "`.harness/` ainda não foi compilado neste projeto — rode `harness compile` "
            "se este projeto usa o harness."
        )
    elif compiled_version != _PIP_VERSION:
        issues.append(
            f"`.harness/` foi compilado com a versão {compiled_version}, mas o pacote "
            f"instalado é {_PIP_VERSION} — rode `harness compile` de novo."
        )

    if not plugin_installs:
        notes.append(
            "nenhuma instalação de `harness-creator` encontrada no cache de plugins do "
            "Claude Code (~/.claude/plugins/installed_plugins.json) — normal se você só "
            "usa a biblioteca via pip/`--plugin-dir`, sem o plugin instalado por marketplace."
        )
    for install in plugin_installs:
        if install["version"] != _PIP_VERSION:
            issues.append(
                f"o plugin `{install['id']}` está com a versão {install['version']} no "
                f"cache do Claude Code, mas o pacote instalado é {_PIP_VERSION} — rode "
                f"`claude plugin update {install['id']}` e reinicie a sessão do Claude Code."
            )

    return DoctorReport(
        pip_version=_PIP_VERSION,
        compiled_version=compiled_version,
        plugin_installs=plugin_installs,
        issues=issues,
        notes=notes,
        hooks=hooks,
    )
