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
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from harness import __version__ as _PIP_VERSION
from harness.compiler import STATE_FILE

PLUGIN_NAME = "harness-creator"
DEFAULT_INSTALLED_PLUGINS_FILE = Path.home() / ".claude" / "plugins" / "installed_plugins.json"


@dataclass
class DoctorReport:
    pip_version: str
    compiled_version: str | None
    plugin_installs: list[dict]
    issues: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def to_json(self) -> str:
        return json.dumps(
            {
                "pip_version": self.pip_version,
                "compiled_version": self.compiled_version,
                "plugin_installs": self.plugin_installs,
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


def run_doctor(
    target_dir: Path,
    plugins_file: Path | None = None,
) -> DoctorReport:
    compiled_version = _read_compiled_version(target_dir)
    plugin_installs = _read_plugin_installs(plugins_file or DEFAULT_INSTALLED_PLUGINS_FILE)

    issues: list[str] = []
    notes: list[str] = []

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
    )
