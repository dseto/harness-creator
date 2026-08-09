"""Monta o Pull Request para o humano abrir — comando `harness pr-draft`.

**Por que existe.** Desde o contrato `aviso-plugin-e-ciclo-automatico`, o
ciclo tem UM gate humano (a aprovação do contrato) e vai sozinho até o push da
branch. Abrir o PR, porém, continua sendo ação humana deliberada — é o ponto
em que alguém decide expor o trabalho para revisão e merge, e nenhum caminho
deste pacote automatiza isso.

O que sobra para o humano, então, não pode ser trabalho braçal: montar título,
tabela de tarefas, resumo de evidência e o comando com as flags certas, tudo
isso já está estruturado em `.harness/feature_list.json` e no `spec.md`.

**A divisão entre o que este módulo gera e o que ele deixa em branco é
deliberada.** Ele produz o FATO derivável do contrato (quais tarefas, qual
prova de cada uma, qual o estado da evidência) e deixa marcado com
`PREENCHER` o RACIONAL — o que mudou, por quê, quais decisões de desenho.
Racional não é derivável de dados estruturados, e é justamente a parte que faz
alguém entender o PR. Gerar um texto genérico ali seria pior que deixar o
buraco visível.

**Corpo em arquivo, nunca em `--body` inline.** Acentuação em linha de comando
no PowerShell 5.1 corrompe multi-byte — defeito já vivido neste repositório, e
a razão de `gh` ser sempre chamado com `--body-file` aqui.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harness.session_permissions import FEATURE_LIST_FILE

#: Onde o rascunho é gravado. `.harness/scratch/` tem escrita liberada pelo
#: `boundary_guard` e é auto-ignorado pelo git — o rascunho não pode aparecer
#: no `git status` do PR que ele mesmo descreve.
SCRATCH_DIR = ".harness/scratch"
BODY_FILENAME = "pr-body.md"

#: Base do PR. O repositório protege `main` (ver `governance.protected_branches`),
#: e é para lá que todo contrato converge.
BASE_BRANCH = "main"

_FILL_IN = "<!-- PREENCHER"


class PrDraftError(Exception):
    """Não há contrato compilado a partir do qual montar o PR."""


@dataclass(frozen=True)
class PrDraft:
    title: str
    branch: str | None
    body_path: Path
    command: str


def _load_feature_list(target_dir: Path) -> dict[str, Any]:
    path = target_dir / FEATURE_LIST_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise PrDraftError(
            f"`{FEATURE_LIST_FILE}` ausente ou ilegível — não há contrato a descrever. "
            "Rode `harness compile-contract` antes."
        ) from exc
    if not isinstance(data, dict) or not data.get("features"):
        raise PrDraftError(
            f"`{FEATURE_LIST_FILE}` não tem features — não há contrato a descrever. "
            "Rode `harness compile-contract` antes."
        )
    return data


def _spec_title(target_dir: Path, slug: str) -> str | None:
    """Primeira linha `# Spec: <titulo>` do contrato.

    O slug é kebab-case porque vira nome de branch; título de PR feito dele
    fica ilegível. O `spec.md` já tem a frase escrita para humano."""
    path = target_dir / ".harness" / "work" / slug / "spec.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("# spec:"):
            return stripped.split(":", 1)[1].strip() or None
    return None


def _current_branch(target_dir: Path) -> str | None:
    """Branch corrente, ou None se `target_dir` não é raiz de repositório.

    O gate por `is_git_repository` não é cerimônia: `git rev-parse` SOBE a
    árvore de diretórios até achar um `.git`. Sem o gate, rodar isto num
    diretório qualquer aninhado sob outro repositório (um `~` versionado, por
    exemplo) devolveria a branch de um repositório sem nenhuma relação — e o
    comando sairia com um `--head` errado, que é pior que sair sem nenhum."""
    from harness.branching import is_git_repository

    if not is_git_repository(target_dir):
        return None
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(target_dir), capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    branch = proc.stdout.strip()
    return branch or None


def _evidence_by_id(target_dir: Path) -> dict[str, str]:
    """Estado da evidência por tarefa, vindo do MESMO auditor que o `harness
    finish` usa — o PR não pode afirmar uma situação de prova diferente da que
    fecha o contrato."""
    try:
        from harness.finish import audit_closure

        report = audit_closure(target_dir)
    except Exception:
        return {}
    return {
        str(f.get("id")): str(f.get("evidence") or "?")
        for f in report.get("features") or []
    }


def render_body(data: dict[str, Any], title: str, evidence: dict[str, str]) -> str:
    contract = str(data.get("contract") or "?")
    features = data.get("features") or []

    lines = [
        f"# {title}",
        "",
        "## O que muda para quem usa",
        "",
        f"{_FILL_IN}: 2-3 frases, sem jargão, sobre o efeito prático. -->",
        "",
        "## Decisões de desenho",
        "",
        f"{_FILL_IN}: o que foi decidido e POR QUÊ; o que foi descartado. -->",
        "",
        "## Tarefas",
        "",
        "| id | entrega | prova | evidência |",
        "|---|---|---|---|",
    ]
    for feature in features:
        fid = str(feature.get("id") or "?")
        lines.append(
            f"| {fid} | {feature.get('desc') or ''} | "
            f"`{feature.get('verify_cmd') or ''}` | {evidence.get(fid, '?')} |"
        )

    lines += [
        "",
        "## Verificação",
        "",
        f"Contrato `{contract}`: {len(features)} tarefas, cada uma com evidência "
        f"gravada em `.harness/evidence/{contract}/`.",
        "",
        f"{_FILL_IN}: resultado da suíte completa e do lint. -->",
        "",
    ]
    return "\n".join(lines)


def _command(title: str, branch: str | None, body_path: Path) -> str:
    parts = ["gh pr create", f"--base {BASE_BRANCH}"]
    if branch:
        parts.append(f"--head {branch}")
    parts.append(f'--title "{title}"')
    parts.append(f'--body-file "{body_path}"')
    return " ".join(parts)


def build_pr_draft(target_dir: Path | str) -> PrDraft:
    """Grava o corpo do PR e devolve o comando pronto. Não abre PR nenhum."""
    target_dir = Path(target_dir).resolve()
    data = _load_feature_list(target_dir)
    contract = str(data.get("contract") or "contrato")

    title = _spec_title(target_dir, contract) or contract
    branch = _current_branch(target_dir)

    body_path = target_dir / SCRATCH_DIR / BODY_FILENAME
    body_path.parent.mkdir(parents=True, exist_ok=True)
    body_path.write_text(
        render_body(data, title, _evidence_by_id(target_dir)), encoding="utf-8"
    )

    return PrDraft(
        title=title,
        branch=branch,
        body_path=body_path,
        command=_command(title, branch, body_path),
    )
