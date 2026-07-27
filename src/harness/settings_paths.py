"""Fronteira machine-local do output compilado — destino único do settings.

Política canônica (Seção 3 de
`docs/project/AUDIT-footprint-raiz-e-versionamento-2026-07-26.md`):

    Especificação, contrato e prova são versionados. Saída de compilação que
    carrega dado de máquina é machine-local e regenerada por `compile`.

Todo output que o harness mescla em settings carrega dado desta máquina: o
comando de hook leva path ABSOLUTO (decisão de `docs/project/PLAN.md:180-182`
— cmd.exe não expande `$VAR`) e a superfície de sessão enumera arquivos do
contrato ativo. Por isso o destino é `.claude/settings.local.json`, que o
Claude Code já lê com precedência sobre o `.claude/settings.json` do time.

Antes desta fronteira o merge caía no `settings.json`, que os projetos-alvo
commitam: um clone em outro path recebia um `PreToolUse` apontando para um
diretório inexistente — **o repositório parecia governado e nenhum guard
rodava**. Falha silenciosa, não erro visível.

Duas garantias, ambas idempotentes e não-destrutivas:

1. `prepare_managed_settings` é o ÚNICO ponto por onde os cinco escritores
   (`compiler`, `boundary_guard`, `session_start`, `stop_hook`,
   `session_permissions`) resolvem o arquivo — a troca de destino não pode
   ficar pela metade em um deles.
2. `ensure_machine_local_gitignores` escreve as regras em arquivos
   TOOL-OWNED (`.claude/.gitignore`, `.harness/.gitignore`), nunca no
   `.gitignore` da raiz do usuário (decisão preservada de
   `boundary_guard.py`). Sem isso o arquivo machine-local depende do
   gitignore GLOBAL da máquina para não ser commitado.

Sem migração do `.claude/settings.json`: o produto é pré-produção, não existe
base instalada, e a instalação é sempre feita do zero. O arquivo do time
nunca é lido nem escrito por este módulo.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from harness.killswitch import SENTINEL_RELATIVE_PATH

CLAUDE_DIR = ".claude"
HARNESS_DIR = ".harness"

#: Destino de TODO output gerenciado pelo harness (machine-local).
MANAGED_SETTINGS_FILE = ".claude/settings.local.json"
#: Arquivo do time, versionado e autorado por humano — o harness não toca.
TEAM_SETTINGS_FILE = ".claude/settings.json"

# Basename do sentinel do kill-switch, derivado da fonte única (killswitch).
_DISABLE_SENTINEL_BASENAME = SENTINEL_RELATIVE_PATH.rsplit("/", 1)[-1]

#: Linhas garantidas em `.harness/.gitignore` — o que é estado de máquina.
HARNESS_GITIGNORE_LINES: tuple[str, ...] = (
    _DISABLE_SENTINEL_BASENAME,
    "compiled-state.json",
    "compiled-state-session.json",
    "hooks/",
    # Contagem de ciclos de fricção (harness.metrics): conta operações DESTA
    # máquina, não fato do repositório.
    "metrics.json",
)
#: Linhas garantidas em `.claude/.gitignore`. Só o arquivo gerenciado —
#: `agents/` e `skills/` são saída versionada de `harness team generate`.
CLAUDE_GITIGNORE_LINES: tuple[str, ...] = ("settings.local.json",)

#: Área de artefato temporário de verificação (screenshot, dump de rede, HTML
#: de debug). Auto-ignorada: `*` + `!.gitignore`.
SCRATCH_DIR = f"{HARNESS_DIR}/scratch"
_SCRATCH_GITIGNORE_CONTENT = "*\n!.gitignore\n"


# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------

def managed_settings_path(target_dir: Path | str) -> Path:
    """`.claude/settings.local.json` de `target_dir` — onde o harness escreve."""
    return Path(target_dir) / MANAGED_SETTINGS_FILE


def team_settings_path(target_dir: Path | str) -> Path:
    """`.claude/settings.json` de `target_dir` — do time, nunca tocado aqui."""
    return Path(target_dir) / TEAM_SETTINGS_FILE


# ---------------------------------------------------------------------------
# .gitignore tool-owned
# ---------------------------------------------------------------------------

def ensure_gitignore_lines(path: Path, lines: tuple[str, ...]) -> bool:
    """Garante cada entrada de `lines` em `path`, preservando o conteúdo já
    presente. Retorna `True` se escreveu (alguma linha faltava)."""
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    present = set(existing.split())
    missing = [line for line in lines if line not in present]
    if not missing:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = existing.rstrip("\n") + "\n" if existing.strip() else ""
    path.write_text(prefix + "\n".join(missing) + "\n", encoding="utf-8")
    return True


def ensure_machine_local_gitignores(target_dir: Path | str) -> list[Path]:
    """Escreve/completa `.harness/.gitignore` e `.claude/.gitignore`.

    O `.gitignore` da RAIZ do alvo continua intocado — decisão de design
    preservada: o harness não edita arquivo que pertence ao projeto.
    Ambos os arquivos gerados SÃO versionados: são a própria regra, e sem
    viajar no clone o ignore não vale para mais ninguém.

    Retorna os paths efetivamente escritos nesta chamada (vazio quando já
    estava tudo lá).
    """
    target_dir = Path(target_dir)
    written: list[Path] = []
    for subdir, lines in (
        (HARNESS_DIR, HARNESS_GITIGNORE_LINES),
        (CLAUDE_DIR, CLAUDE_GITIGNORE_LINES),
    ):
        path = target_dir / subdir / ".gitignore"
        if ensure_gitignore_lines(path, lines):
            written.append(path)
    return written


# ---------------------------------------------------------------------------
# ponto único de acesso dos escritores
# ---------------------------------------------------------------------------

def ensure_scratch_surface(target_dir: Path | str) -> Path:
    """Garante `.harness/scratch/` com `.gitignore` auto-contido.

    A pasta se ignora sozinha (`*` + `!.gitignore`), sem tocar no `.gitignore`
    da raiz do usuário: o `git status` fica limpo mesmo que o agente esqueça
    screenshot ou dump de rede lá. Um `.gitignore` já existente nunca é
    sobrescrito — pode ter sido customizado.

    Retorna o path do diretório.
    """
    target_dir = Path(target_dir)
    scratch_dir = target_dir / SCRATCH_DIR
    scratch_dir.mkdir(parents=True, exist_ok=True)
    gitignore = scratch_dir / ".gitignore"
    if not gitignore.is_file():
        gitignore.write_text(_SCRATCH_GITIGNORE_CONTENT, encoding="utf-8")
    return scratch_dir


def prepare_managed_settings(target_dir: Path | str) -> tuple[Path, dict[str, Any]]:
    """Devolve `(path do settings.local.json, conteúdo atual)`, garantindo
    antes os `.gitignore` tool-owned e a superfície de scratch.

    Todo escritor de settings passa por aqui: é o que impede a fronteira de
    valer em quatro módulos e não no quinto. JSON inválido no arquivo
    gerenciado PROPAGA o erro (é output nosso — sobrescrever calado apagaria
    o registro do que está ativo na sessão, incluindo as aprovações
    interativas que o Claude Code guarda no mesmo arquivo).

    `ensure_scratch_surface` entrou aqui, e não só em `install_boundary_guard`,
    porque o bloco gerenciado que `harness compile` escreve no `AGENTS.md`
    manda salvar artefato temporário em `.harness/scratch/` — mas a pasta só
    nascia no `compile-session`. Entre um comando e outro a instrução apontava
    para um diretório inexistente. Amarrar as duas coisas ao mesmo ponto único
    é o que impede a assimetria de voltar.
    """
    target_dir = Path(target_dir)
    ensure_machine_local_gitignores(target_dir)
    ensure_scratch_surface(target_dir)

    path = managed_settings_path(target_dir)
    settings: dict[str, Any] = {}
    if path.is_file():
        settings = json.loads(path.read_text(encoding="utf-8-sig"))
    return path, settings


def write_managed_settings(path: Path, settings: dict[str, Any]) -> None:
    """Grava o settings gerenciado no formato único (indent 2, UTF-8, `\\n`
    final) que os cinco escritores usavam duplicado."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
