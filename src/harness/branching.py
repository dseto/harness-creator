"""Branching: fluxo branch-first gerenciado pela CLI (finding C, dogfood 2026-07-22).

Sob a regra "nunca commit direto na main, só via PR", a branch de trabalho
precisa existir ANTES de o agente começar — e criar branch é decisão de
CONTROLE, não do agente: o boundary_guard não libera nenhum comando git de
branch (`checkout`/`switch`/`branch` seguem fora de `FIXED_GIT_SEQUENCES`).
Em vez disso, `harness compile-session` chama `ensure_contract_branch` antes
de instalar qualquer artefato, posicionando o repo em `contract/<slug>`. O
agente ainda consegue acionar isso pelo caminho sancionado, porque
`FIXED_HARNESS_SEQUENCES` já libera `harness compile-session`.

Dirty tree conta SÓ tracked modificado/staged (`git status --porcelain -uno`)
— untracked NÃO: o fluxo real `compile-contract → compile-session` deixa
`.harness/**` untracked exatamente neste momento, e é na branch de contrato
que esses artefatos devem ser commitados (`git switch` preserva untracked).
Contar untracked abortaria o fluxo canônico sempre.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml
from pydantic import ValidationError

from harness.config import HarnessConfig

HARNESS_YAML_RELATIVE_PATH = ".harness/harness.yaml"
CONTRACT_BRANCH_PREFIX = "contract/"

#: Artefatos que o PRÓPRIO harness grava no fluxo que antecede a criação da
#: branch — `analyze` produz o `repo-profile.json`, `compile-contract` produz o
#: `feature_list.json`. Num repo que versiona `.harness/` eles são tracked, e
#: contá-los como sujeira fechava o agente num deadlock a partir do SEGUNDO
#: contrato: compile-contract suja o feature_list -> compile-session recusa a
#: tree e manda commitar na branch atual -> a branch atual é protegida e o
#: guard nega o commit, sugerindo `git checkout -b` -> que o guard também nega.
#: As três mensagens apontavam umas para as outras sem abrir caminho.
#:
#: A isenção é segura porque `git switch`/`switch -c` preserva a working tree:
#: o conteúdo viaja para a branch de contrato, que é exatamente onde ele deve
#: ser commitado. Nada aqui é descartado. Sujeira de qualquer arquivo FORA
#: deste conjunto continua abortando com a mesma mensagem.
HARNESS_MANAGED_PATHS = frozenset({
    ".harness/feature_list.json",
    ".harness/repo-profile.json",
    ".harness/progress.md",
})

#: Mesma isenção, para as árvores inteiras que o harness gerencia. A evidência
#: nasce de `harness verify` a cada tarefa, então num repo que versiona
#: `.harness/` ela fica tracked-suja durante toda a demanda.
HARNESS_MANAGED_PREFIXES = (".harness/evidence/",)


class BranchingError(Exception):
    """Falha de pré-condição ou de git ao posicionar a branch de contrato."""


def _git(target_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *args], cwd=target_dir, capture_output=True, text=True,
        )
    except OSError as exc:  # git ausente do PATH, diretório inexistente
        raise BranchingError(f"não foi possível executar git: {exc}") from exc


def ensure_contract_branch(target_dir: Path, contract: str) -> str:
    """Garante que `target_dir` está na branch `contract/<contract>`.

    Idempotente: já na branch → no-op; branch existe → `git switch`
    (recompile do mesmo contrato = continuação); não existe → `git switch -c`
    a partir do HEAD atual (inclusive detached — merge de branch antiga
    não-mergeada é decisão do humano, não daqui).

    Levanta `BranchingError` em: diretório fora de repo git, slug vazio,
    repo sem commit inicial, ou tracked modificado/staged (ver docstring do
    módulo sobre untracked). Retorna o nome da branch ativa ao final.
    """
    target_dir = Path(target_dir).resolve()

    if not contract:
        raise BranchingError(
            "feature_list.json sem slug de contrato — não há nome para a branch"
        )

    if not _has_git_root(target_dir):
        raise BranchingError(
            f"{target_dir} não é a raiz de um repositório git — "
            "branch_per_contract exige git (ou desligue em "
            "governance.branch_per_contract)"
        )

    if _git(target_dir, "rev-parse", "--verify", "HEAD").returncode != 0:
        raise BranchingError(
            "repositório sem commit inicial — crie o commit inicial antes de "
            "compilar a sessão"
        )

    branch = CONTRACT_BRANCH_PREFIX + contract

    head = _git(target_dir, "rev-parse", "--abbrev-ref", "HEAD")
    if head.returncode == 0 and head.stdout.strip() == branch:
        return branch

    status = _git(target_dir, "status", "--porcelain", "-uno")
    if status.returncode != 0:
        raise BranchingError(f"git status falhou: {status.stderr.strip()[:200]}")
    unmanaged = unmanaged_dirty_paths(status.stdout)
    if unmanaged:
        raise BranchingError(_dirty_tree_problem(unmanaged, branch))

    exists = _git(target_dir, "rev-parse", "--verify", f"refs/heads/{branch}")
    if exists.returncode == 0:
        switched = _git(target_dir, "switch", branch)
    else:
        switched = _git(target_dir, "switch", "-c", branch)
    if switched.returncode != 0:
        raise BranchingError(
            f"git switch para {branch} falhou: {switched.stderr.strip()[:200]}"
        )
    return branch


#: Quantos arquivos sujos a mensagem nomeia antes de resumir. Listar tudo num
#: repo com dezenas de modificações vira parede de texto e some com a saída.
_DIRTY_SAMPLE = 5


def unmanaged_dirty_paths(porcelain: str) -> list[str]:
    """Caminhos tracked sujos de `git status --porcelain` que NÃO estão em
    `HARNESS_MANAGED_PATHS` — ou seja, a sujeira que de fato é trabalho de
    outro contexto. Exportada porque `harness.finish` faz o mesmo julgamento
    ao auditar o fecho da demanda, e duplicar a regra em dois lugares é como
    ela se torna inconsistente."""
    paths: list[str] = []
    for line in (porcelain or "").splitlines():
        if len(line) <= 3:
            continue
        path = line[3:].strip().strip('"')
        # Rename/copy vêm como `old -> new`; o que importa é o destino.
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if not path or path in HARNESS_MANAGED_PATHS:
            continue
        if path.startswith(HARNESS_MANAGED_PREFIXES):
            continue
        paths.append(path)
    return paths


def _dirty_tree_problem(files: list[str], branch: str) -> str:
    """Razão de recusa da árvore suja, nomeando os arquivos e as saídas.

    Achado F6 do dogfood venv-Windows: a mensagem antiga dizia
    "commit ou stash antes de compilar a sessão" e parava aí. No alvo real, os
    arquivos modificados **eram** os `files[]` do próprio contrato — o trabalho
    já estava em andamento quando o harness foi instalado, que é o caso mais
    provável de quem adota a ferramenta num projeto vivo, e não o de quem
    começa do zero. Mandar "stashear" ali é conselho ruim: o stash esconde
    exatamente o que o contrato existe para governar. Dizer QUAIS arquivos e
    QUAIS são as três saídas custa nada e evita a decisão errada."""
    listed = ", ".join(files[:_DIRTY_SAMPLE])
    if len(files) > _DIRTY_SAMPLE:
        listed += f" (+{len(files) - _DIRTY_SAMPLE})"
    return (
        "working tree suja (tracked modificado/staged) — criar a branch de "
        f"contrato com sujeira misturaria trabalho de outro contexto. Sujo: {listed}. "
        "Três saídas, e a escolha depende de o trabalho pendente PERTENCER ou "
        "não a este contrato: (1) se pertence — caso comum de quem instala o "
        "harness no meio de uma feature —, commite AGORA, na branch atual, e "
        f"rode de novo: o `git switch -c {branch}` leva o commit junto, sem "
        "perder nada; (2) se é de outro contexto, `git stash` e retome depois; "
        "(3) se este repo não quer branch por contrato, desligue em "
        "`governance.branch_per_contract` do .harness/harness.yaml. NÃO stashe "
        "trabalho que é deste contrato — é justamente o que ele vai governar."
    )


def _has_git_root(target_dir: Path) -> bool:
    """True se existe `.git` (diretório ou arquivo de worktree) na PRÓPRIA
    raiz de `target_dir`. Deliberadamente NÃO usa `git rev-parse
    --is-inside-work-tree`: esse walk sobe diretórios e um target-dir de
    sandbox/tmp aninhado num repo do usuário (ex.: home versionado) seria
    tratado como repo — a branch seria criada no repo ERRADO."""
    return (Path(target_dir) / ".git").exists()


def is_git_repository(target_dir: Path) -> bool:
    """True se `target_dir` é a raiz de um repo git. Usado pelo
    compile-session para degradar com AVISO (não erro) em diretórios sem git
    — sandboxes e suites e2e continuam funcionando sem `git init`."""
    return _has_git_root(Path(target_dir).resolve())


def load_branch_per_contract(target_dir: Path) -> bool:
    """Lê `governance.branch_per_contract` de `target_dir/.harness/harness.yaml`.

    Mesma degradação graciosa de `load_extra_allowed_commands`
    (boundary_guard): ausente/YAML inválido/schema divergente → default do
    modelo (`True` — o fluxo seguro é o padrão)."""
    default = HarnessConfig().governance.branch_per_contract
    yaml_path = Path(target_dir) / HARNESS_YAML_RELATIVE_PATH
    if not yaml_path.is_file():
        return default
    try:
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return default
    if not isinstance(raw, dict):
        return default
    try:
        config = HarnessConfig.model_validate(raw)
    except ValidationError:
        return default
    return config.governance.branch_per_contract
