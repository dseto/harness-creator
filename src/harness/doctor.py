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
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from harness import __version__ as _PIP_VERSION
from harness.boundary_guard import extra_allowed_commands_grammar_problem
from harness.compiler import HARNESS_YAML, STATE_FILE
from harness.session_permissions import FEATURE_LIST_FILE, missing_harness_yaml_warning
from harness.hook_launcher import fail_closed_problem, interpreter_problem
from harness.settings_paths import MANAGED_SETTINGS_FILE, managed_settings_path

PLUGIN_NAME = "harness-creator"
DEFAULT_INSTALLED_PLUGINS_FILE = Path.home() / ".claude" / "plugins" / "installed_plugins.json"

#: Override do caminho do cache de plugin. `run_doctor` recebe `plugins_file`
#: por parâmetro — o que basta para teste in-process, mas não atravessa
#: fronteira de processo: o hook `SessionStart` dispara `python -m
#: harness.autoupdate` num subprocesso, e sem este seam a única forma de
#: exercitar o caminho real seria escrever no `~/.claude` do usuário. É o
#: equivalente, via ambiente, ao parâmetro que já existe.
INSTALLED_PLUGINS_ENV = "HARNESS_INSTALLED_PLUGINS_FILE"


def _default_plugins_file() -> Path:
    override = os.environ.get(INSTALLED_PLUGINS_ENV, "").strip()
    return Path(override) if override else DEFAULT_INSTALLED_PLUGINS_FILE

#: O comando de hook gerado tem a forma `"<interpretador>" "<script>.py" || exit 2`
#: — o path fica entre aspas justamente porque pode conter espaço, e o padrão
#: ancora no `.py` final para não casar o interpretador.
_HOOK_SCRIPT_PATTERN = re.compile(r'"([^"]+\.py)"')

# Nomes dos scripts de hook gerados por este pacote. Um `command` que cite
# qualquer um deles é NOSSO e tem o interpretador verificado; hooks de
# terceiros no mesmo arquivo são ignorados (não cabe ao `doctor` opinar sobre
# eles).
# `guard_tests.py`/`guard_test_runner.py` entraram no achado F8 do dogfood
# venv-Windows: são gerados por `harness compile` (não por `compile-session`),
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


def plugin_update_command(plugin_id: str) -> str:
    """Comando exato que atualiza uma instalação de plugin do Claude Code.

    Fonte única da string: o laudo do `doctor` e o aviso do hook `SessionStart`
    precisam mandar a MESMA coisa, e um comando divergente entre os dois é a
    classe de defeito que faz o usuário rodar algo que não corrige nada."""
    return f"claude plugin update {plugin_id}"


def stale_plugin_installs(
    installed_version: str,
    plugins_file: Path | None = None,
) -> list[dict]:
    """Instalações de plugin ATRÁS do pacote instalado, cada uma com o comando
    que a corrige.

    Existe fora de `run_doctor` porque o hook `SessionStart` precisa da mesma
    comparação para avisar na abertura da sessão, e não pode montar um laudo
    inteiro para isso. Duas cópias da regra de versão divergiriam.

    Silenciosa — lista vazia — em quatro situações que NÃO são defeito:
    arquivo ausente (normal em quem usa `--plugin-dir` ou só pip), JSON
    inválido, nenhuma instalação deste pacote, e versão ilegível de qualquer
    um dos lados.

    Plugin À FRENTE do pacote também devolve vazio: `claude plugin update` não
    corrige cache adiantado, e mandar rodá-lo seria instrução falsa. Mesma
    postura de `harness.autoupdate` para os artefatos compilados."""
    from harness.autoupdate import parse_version

    installed = parse_version(installed_version)
    if installed is None:
        return []

    stale: list[dict] = []
    for install in _read_plugin_installs(plugins_file or _default_plugins_file()):
        cached = parse_version(install.get("version"))
        if cached is None or cached >= installed:
            continue
        stale.append({
            "id": install["id"],
            "version": install["version"],
            "installed_version": installed_version,
            "command": plugin_update_command(install["id"]),
        })
    return stale


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


def repo_issues(target_dir: Path) -> list[str]:
    """Só as issues sobre ESTE repositório: governança compilada, hooks e
    versão do `.harness/`.

    Existe fora de `run_doctor` porque o health check de abertura (§7.2, ver
    `harness.health`) precisa exatamente destas e não das do cache de plugin
    do Claude Code. O cache não é deste repositório, já tem aviso próprio na
    abertura, e esse aviso declara em texto que **não bloqueia nada** — somá-lo
    ao veredito de abertura faria a sessão mandar parar por uma coisa que não
    impede trabalhar.

    Reusada por `run_doctor`, e não copiada: o laudo completo é este conjunto
    MAIS os do plugin. Duas listas de regras de saúde divergiriam, que é a
    lição que o contrato `compilar-as-primeiras-licoes` compilou.
    """
    issues: list[str] = []

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

    for hook in _read_managed_hooks(target_dir):
        if hook["problem"]:
            issues.append(f"hook `{hook['event']}`: {hook['problem']}")

    # --- allowlist que o hook nao consegue ler ---
    # Postura C do Item 9: liberar um comando novo e editar o YAML a mao, entao
    # uma entrada em sintaxe que o parser minimo do hook nao entende vira deny
    # SILENCIOSO — e a lista inteira degrada para vazia junto. O
    # `compile-session` ja avisa, mas o Item 3 tornou o `compile-session`
    # desnecessario justamente para esse fluxo: quem so edita o YAML nunca
    # veria o aviso. O `doctor` e o comando que a pessoa roda quando desconfia
    # de alguma coisa, entao e aqui que a checagem precisa existir tambem.
    if governed:
        grammar_problem = extra_allowed_commands_grammar_problem(target_dir)
        if grammar_problem:
            issues.append(grammar_problem)

    compiled_version = _read_compiled_version(target_dir)
    if compiled_version is not None and compiled_version != _PIP_VERSION:
        issues.append(
            f"`.harness/` foi compilado com a versão {compiled_version}, mas o pacote "
            f"instalado é {_PIP_VERSION} — rode `harness compile` de novo."
        )

    return issues


def run_doctor(
    target_dir: Path,
    plugins_file: Path | None = None,
) -> DoctorReport:
    compiled_version = _read_compiled_version(target_dir)
    plugin_installs = _read_plugin_installs(plugins_file or _default_plugins_file())
    hooks = _read_managed_hooks(target_dir)

    # O laudo completo é o do repositório MAIS o do cache de plugin. A parte do
    # repositório mora em `repo_issues` porque o health check de abertura
    # consome só ela — ver o docstring de lá.
    issues: list[str] = list(repo_issues(target_dir))
    notes: list[str] = []

    governed = (target_dir / HARNESS_YAML).is_file()

    # Issue #72: repositório com sessão compilada (`feature_list.json`) mas
    # sem `harness.yaml` nunca rodou `/harness-creator:init` — TDD e política
    # de aprovação ficaram de fora, e sem este aviso ninguém percebe. Nota
    # (não issue): `compile-session` funciona de propósito sem o yaml (ver
    # `session_permissions.missing_harness_yaml_warning`), então isso não é
    # um erro que bloqueia `doctor`.
    if not governed and (target_dir / FEATURE_LIST_FILE).is_file():
        warning = missing_harness_yaml_warning(target_dir)
        if warning:
            notes.append(warning)

    if compiled_version is None:
        notes.append(
            "`.harness/` ainda não foi compilado neste projeto — rode `harness compile` "
            "se este projeto usa o harness."
        )

    if not plugin_installs:
        notes.append(
            "nenhuma instalação de `harness-creator` encontrada no cache de plugins do "
            "Claude Code (~/.claude/plugins/installed_plugins.json) — normal se você só "
            "usa a biblioteca via pip/`--plugin-dir`, sem o plugin instalado por marketplace."
        )
    # MESMA função que o hook `SessionStart` consome para avisar na abertura da
    # sessão. Antes desta unificação o laudo tinha a comparação própria (`!=`),
    # e duas regras de versão são duas regras que podem divergir.
    for stale in stale_plugin_installs(_PIP_VERSION, plugins_file=plugins_file):
        issues.append(
            f"o plugin `{stale['id']}` está com a versão {stale['version']} no "
            f"cache do Claude Code, mas o pacote instalado é {_PIP_VERSION} — rode "
            f"`{stale['command']}` e reinicie a sessão do Claude Code."
        )

    # Cache À FRENTE do pacote: `stale_plugin_installs` cala de propósito (o
    # `claude plugin update` não corrige isso), mas o `doctor` existe para
    # mostrar divergência — omitir aqui esconderia um estado real. Nota, e não
    # issue, porque a correção é do outro lado e não é urgente.
    from harness.autoupdate import parse_version

    installed = parse_version(_PIP_VERSION)
    for install in plugin_installs:
        cached = parse_version(install.get("version"))
        if installed is not None and cached is not None and cached > installed:
            notes.append(
                f"o plugin `{install['id']}` está na versão {install['version']}, à "
                f"FRENTE do pacote instalado ({_PIP_VERSION}) — `claude plugin update` "
                f"não corrige isso; atualize o pacote com `pip install --upgrade "
                f"harness-creator`."
            )

    return DoctorReport(
        pip_version=_PIP_VERSION,
        compiled_version=compiled_version,
        plugin_installs=plugin_installs,
        issues=issues,
        notes=notes,
        hooks=hooks,
    )
