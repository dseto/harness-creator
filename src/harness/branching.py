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
    if status.stdout.strip():
        raise BranchingError(
            "working tree suja (tracked modificado/staged) — commit ou stash "
            "antes de compilar a sessão; criar a branch de contrato com "
            "sujeira misturaria trabalho de outro contexto"
        )

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
