"""Diagnóstico de saúde da instalação — comando `harness doctor`.

Duas famílias de problema, ambas SILENCIOSAS: nada falha, o Claude Code
simplesmente roda menos governança do que o repositório aparenta ter.

**1. Divergência de versão entre as 3 camadas de distribuição.** O plugin
chega ao usuário por 3 caminhos independentes, cada um com seu próprio ciclo
de atualização:

    1. pacote Python instalado (pip)   -> harness.__version__
    2. `.harness/` compilado           -> `plugin_version` gravado pelo
       último `harness compile` em `.harness/compiled-state.json`
    3. cache de plugin do Claude Code  -> `~/.claude/plugins/installed_plugins.json`

Atualizar só uma camada (ex.: `pip install --upgrade` sem rodar `harness
compile` de novo, ou sem rodar `claude plugin update`) deixa as outras
presas na versão antiga sem sinal nenhum — o comportamento observado no
Claude Code (hooks, skills) reflete a camada mais atrasada.

**2. Compilação ausente ou apontando para o lugar errado.** Contrapartida
executável do trade-off assumido na Seção 3 de
`docs/project/AUDIT-footprint-raiz-e-versionamento-2026-07-26.md`: o output
compilado é machine-local, então **um clone novo não nasce governado**. O
repositório clonado tem `harness.yaml`, `work/**` e `feature_list.json`
versionados — parece instalado —, mas sem `.claude/settings.local.json` nenhum
hook roda. O mesmo vale para o repo que mudou de lugar no disco: o comando de
hook carrega path absoluto (decisão de `docs/project/PLAN.md:180-182`) e passa
a apontar para um diretório que não existe mais. Antes deste check as duas
situações só apareciam como prosa em `TUTORIAL.md`.

`doctor` não previne nada sozinho: é diagnóstico sob demanda, que aponta qual
camada ficou pra trás e o comando exato para corrigir.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from harness import __version__ as _PIP_VERSION
from harness.compiler import HARNESS_YAML, STATE_FILE
from harness.settings_paths import MANAGED_SETTINGS_FILE, managed_settings_path

PLUGIN_NAME = "harness-creator"
DEFAULT_INSTALLED_PLUGINS_FILE = Path.home() / ".claude" / "plugins" / "installed_plugins.json"

#: Os comandos de hook gerados têm a forma `python "<path absoluto>.py"` — o
#: path fica entre aspas justamente porque pode conter espaço.
_HOOK_SCRIPT_PATTERN = re.compile(r'"([^"]+\.py)"')


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


def _managed_hook_scripts(settings_path: Path) -> list[str]:
    """Todos os scripts `.py` referenciados por comando de hook no settings
    gerenciado. Lê QUALQUER evento (`PreToolUse`, `SessionStart`, `Stop`, ...)
    em vez de enumerar os que hoje existem: hook novo entra na cobertura sem
    tocar aqui. JSON quebrado devolve lista vazia — a ausência de settings já
    é reportada pelo check anterior, e um erro de parse aqui viraria ruído
    duplicado."""
    if not settings_path.is_file():
        return []
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(settings, dict):
        return []

    scripts: list[str] = []
    for entries in (settings.get("hooks") or {}).values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            for hook in entry.get("hooks") or []:
                if isinstance(hook, dict):
                    scripts.extend(_HOOK_SCRIPT_PATTERN.findall(hook.get("command") or ""))
    return scripts


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

    # --- compilação ausente / apontando para o lugar errado ---
    # Gatear em `harness.yaml` é o que distingue "clone de projeto governado"
    # de "diretório qualquer": sem a config versionada não há nada a compilar,
    # e cobrar `harness compile` de um projeto que não usa o harness seria
    # ruído. Ver Seção 3 do laudo de footprint.
    governed = (target_dir / HARNESS_YAML).is_file()
    settings_path = managed_settings_path(target_dir)
    if governed and not settings_path.is_file():
        issues.append(
            f"`{HARNESS_YAML}` existe mas `{MANAGED_SETTINGS_FILE}` não — o output "
            "compilado é machine-local e NÃO viaja no clone: este repositório parece "
            "governado e nenhum hook está rodando. Rode `harness compile` (e "
            "`harness compile-session` se houver contrato ativo)."
        )
    for script in _managed_hook_scripts(settings_path):
        if not Path(script).is_file():
            issues.append(
                f"o comando de hook em `{MANAGED_SETTINGS_FILE}` aponta para `{script}`, "
                "que não existe — típico de repositório movido de lugar (o path é "
                "absoluto por design). Rode `harness compile` para recompilar os hooks "
                "no caminho atual."
            )

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
