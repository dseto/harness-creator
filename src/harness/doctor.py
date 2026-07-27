"""Diagnóstico de saúde da instalação — comando `harness doctor`.

Três famílias de problema, todas SILENCIOSAS: nada falha, o Claude Code
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

**3. Hook registrado que não roda** (Item 1 do backlog do dogfood
venv-Windows). Um hook com interpretador irresolúvel
(`python` nu que o PATH de runtime não acha, ou caminho absoluto de um venv
que foi recriado) simplesmente NÃO RODA — e, pela semântica de exit code de
hook do Claude Code, a tool call PASSA sem gate nenhum. É a falha mais
perigosa que este módulo pode diagnosticar, porque o sintoma runtime é uma
linha de `hook error` no transcript e nada mais. Ver `harness.hook_launcher`
para o mecanismo e o risco residual.

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
from harness.hook_launcher import fail_closed_problem, interpreter_problem
from harness.settings_paths import MANAGED_SETTINGS_FILE, managed_settings_path

PLUGIN_NAME = "harness-creator"
DEFAULT_INSTALLED_PLUGINS_FILE = Path.home() / ".claude" / "plugins" / "installed_plugins.json"

#: O comando de hook gerado tem a forma `"<interpretador>" "<script>.py" || exit 2`
#: — o path fica entre aspas justamente porque pode conter espaço, e o padrão
#: ancora no `.py` final para não casar o interpretador.
_HOOK_SCRIPT_PATTERN = re.compile(r'"([^"]+\.py)"')

# Nomes dos scripts de hook gerados por este pacote. Um `command` que cite
# qualquer um deles é NOSSO e tem o interpretador verificado; hooks de
# terceiros no mesmo arquivo são ignorados (não cabe ao `doctor` opinar sobre
# eles).
# `guard_tests.py`/`guard_test_runner.py` entraram no achado F8 do dogfood do
# MiojoSimulator: são gerados por `harness compile` (não por `compile-session`),
# ficaram de fora do Item 1/1b, e o `doctor` também não os olhava — o laudo de um
# alvo com os dois instalados e lançados por `python` nu devolvia `"hooks": []`,
# um verde falso sobre o estado exatamente que o check existe para pegar.
MANAGED_HOOK_FILENAMES = (
    "boundary_guard.py", "session_start.py", "stop_hook.py",
    "guard_tests.py", "guard_test_runner.py",
)


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
                if not isinstance(hook, dict):
                    continue
                command = hook.get("command") or ""
                # Só hooks NOSSOS. Um `settings.local.json` pode registrar hook
                # de terceiro; não cabe ao `doctor` opinar sobre a existência
                # do script alheio (mesma postura de `_read_managed_hooks`).
                if not any(name in command for name in MANAGED_HOOK_FILENAMES):
                    continue
                scripts.extend(_HOOK_SCRIPT_PATTERN.findall(command))
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


def _read_managed_hooks(target_dir: Path) -> list[dict]:
    """Lista os hooks DESTE pacote registrados no settings GERENCIADO
    (`.claude/settings.local.json` — ver `harness.settings_paths`), cada um com
    o veredito do seu interpretador.

    Degradação graciosa idêntica aos demais leitores deste módulo (arquivo
    ausente ou JSON inválido -> lista vazia): `doctor` nunca lança por causa
    de um settings.json malformado — nesse caso a ausência de hooks vira
    nota, não issue, porque não dá pra distinguir "malformado" de "projeto
    que não usa o harness"."""
    path = managed_settings_path(target_dir)
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
                # Dois modos de fail-open independentes: interpretador que
                # não resolve (Item 1) e ausência do sufixo `|| exit 2`
                # (Item 1b). Reportados juntos porque a consequência é a
                # mesma — tool call passa sem gate — e a correção também
                # (recompilar; qual dos dois comandos regrava depende de qual
                # hook é, e a mensagem nomeia os dois).
                problems = [
                    p for p in (interpreter_problem(command), fail_closed_problem(command))
                    if p is not None
                ]
                problem = " | ".join(problems) if problems else None
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
