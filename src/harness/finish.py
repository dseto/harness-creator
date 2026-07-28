"""Finish: encerramento da demanda — audita o fecho e varre os descartáveis.

Itens 5+7 do backlog do dogfood miojo. O ciclo tinha início bem definido
(`preflight` → `init` → `plan` → `compile-contract` → `compile-session`) e
nenhum fim: depois que `harness supervise` devolvia `next: null`, o repo
simplesmente ficava como estava. Na prática isso acumulava sobra a cada
demanda — o `progress.md` descrevendo um contrato de duas versões atrás, o
`scratch/` guardando arquivos de semanas antes, e nenhuma conferência de que as
provas registradas ainda valiam para o código em disco.

Duas metades, nesta ordem e nada além disso:

1. `audit_closure` — SÓ LEITURA. Devolve os bloqueadores do fecho. Nunca
   escreve, nunca executa `verify_cmd`.
2. `sweep_disposables` — apaga/reescreve apenas o que é descartável dentro do
   `.harness/`. Só roda com a auditoria limpa.

O que este módulo deliberadamente NÃO faz (ver `.harness/work/harness-finish/
spec.md`, seção Não-objetivos):

- `git commit`/`git push`/`gh pr create`. Ação de rede irreversível dentro de um
  subcomando que está na allowlist do agente transformaria o próprio `finish`
  em bypass do runtime floor — é a razão de `enable`/`disable` estarem FORA de
  `_HARNESS_SUBCOMMANDS` no boundary_guard.
- Gerar "sugestões de melhoria". Isso é saída de modelo, não de CLI: aqui saem
  os fatos, e quem redige a mensagem de fecho é o agente.
- Apagar histórico. `.harness/work/`, `.harness/evidence/` e o
  `feature_list.json` ficam intactos — são o registro do que foi feito.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from harness.branching import unmanaged_dirty_paths
from harness.contract import FEATURE_LIST_FILE
from harness.killswitch import SENTINEL_RELATIVE_PATH, is_disabled
from harness.verify import compute_files_hash, evidence_path

PROGRESS_FILE = ".harness/progress.md"
SCRATCH_DIR = ".harness/scratch"

#: Preservado ao esvaziar o scratch: é o arquivo que mantém a pasta fora do
#: `git status`, e apagá-lo faria o próximo rascunho poluir o repo.
SCRATCH_KEEP = {".gitignore"}


class FinishError(Exception):
    """Falha ao encerrar a demanda (varredura pedida com fecho reprovado)."""


def _blocker(kind: str, problem: str) -> dict[str, str]:
    return {"kind": kind, "problem": problem}


def _load_feature_list(target_dir: Path) -> dict[str, Any] | None:
    path = target_dir / FEATURE_LIST_FILE
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _tracked_dirty_paths(target_dir: Path) -> list[str]:
    """Tracked modificado/staged, já sem os artefatos gerenciados pelo harness.

    Usa `unmanaged_dirty_paths` de `branching` em vez de reimplementar o
    julgamento: são a mesma pergunta feita em dois momentos do ciclo (criar a
    branch, fechar a demanda), e duplicar a regra é como ela fica inconsistente.
    Repo sem git -> lista vazia: o `finish` degrada como o resto do harness em
    sandbox/e2e, em vez de virar erro.
    """
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain", "-uno"],
            cwd=target_dir,
            capture_output=True,
            text=True,
        )
    except OSError:
        return []
    if proc.returncode != 0:
        return []
    return unmanaged_dirty_paths(proc.stdout)


def audit_closure(target_dir: Path | str) -> dict[str, Any]:
    """Audita o fecho da demanda. SÓ LEITURA — nada em disco muda aqui.

    Devolve `{"contract": <slug|None>, "blockers": [...], "features": [...]}`.
    Cada bloqueador é `{"kind": ..., "problem": <frase para o humano>}`. Fecho
    íntegro -> `blockers == []`.

    Os `kind` possíveis e o que cada um significa:

    - `killswitch_active` — o `boundary_guard` está em no-op, logo a demanda
      inteira rodou sem governança;
    - `no_contract` — `feature_list.json` ausente ou ilegível;
    - `feature_not_passed` — feature ainda sem `passes: true`;
    - `evidence_missing` — feature com `passes: true` e nenhum arquivo de
      evidência (marcação à mão, o que o passo 13 do lifecycle proíbe);
    - `evidence_stale` — o `files_hash` da evidência não bate com o conteúdo
      atual dos `files[]`: o código mudou depois da prova;
    - `tree_residue` — tracked sujo fora dos `files[]` do contrato e fora dos
      artefatos gerenciados pelo harness.
    """
    target_dir = Path(target_dir).resolve()
    blockers: list[dict[str, str]] = []
    features_report: list[dict[str, Any]] = []

    if is_disabled(target_dir):
        blockers.append(
            _blocker(
                "killswitch_active",
                f"o harness está desativado (`{SENTINEL_RELATIVE_PATH}` presente) — o "
                "boundary_guard rodou em no-op durante esta demanda, então nada foi "
                "governado. Religue com `harness enable` e reveja o que passou antes "
                "de encerrar.",
            )
        )

    data = _load_feature_list(target_dir)
    if data is None:
        blockers.append(
            _blocker(
                "no_contract",
                f"`{FEATURE_LIST_FILE}` ausente ou ilegível — não há contrato a fechar. "
                "Rode `harness compile-contract` antes.",
            )
        )
        return {"contract": None, "blockers": blockers, "features": []}

    contract = str(data.get("contract") or "") or None
    declared_files: set[str] = set()

    for feature in data.get("features") or []:
        feature_id = str(feature.get("id") or "?")
        files = list(feature.get("files") or [])
        declared_files.update(files)
        evidence_state = "n/a"

        if feature.get("passes") is not True:
            blockers.append(
                _blocker(
                    "feature_not_passed",
                    f"{feature_id} ainda não passou (`passes` != true) — "
                    f"rode `harness verify {feature_id}` antes de encerrar.",
                )
            )
        else:
            path = evidence_path(target_dir, contract, feature_id)
            if not path.is_file():
                evidence_state = "missing"
                blockers.append(
                    _blocker(
                        "evidence_missing",
                        f"{feature_id} está marcada como passando, mas não há evidência "
                        f"em `{path.relative_to(target_dir).as_posix()}` — feature "
                        "marcada à mão não fecha demanda.",
                    )
                )
            else:
                evidence_state = _evidence_state(target_dir, path, files)
                if evidence_state == "stale":
                    blockers.append(
                        _blocker(
                            "evidence_stale",
                            f"a evidência de {feature_id} é anterior ao código: o "
                            "`files_hash` gravado não bate com o conteúdo atual dos "
                            f"`files[]`. Rode `harness verify {feature_id}` de novo "
                            "para carimbar uma prova válida.",
                        )
                    )

        features_report.append(
            {
                "id": feature_id,
                "desc": feature.get("desc"),
                "passes": feature.get("passes") is True,
                "evidence": evidence_state,
            }
        )

    residue = [p for p in _tracked_dirty_paths(target_dir) if p not in declared_files]
    if residue:
        blockers.append(
            _blocker(
                "tree_residue",
                "há mudança tracked fora dos `files[]` do contrato: "
                + ", ".join(sorted(residue))
                + ". Ou o arquivo pertence a alguma tarefa (use `harness task add-file`), "
                "ou é trabalho de outro contexto e não deve entrar neste fecho.",
            )
        )

    return {"contract": contract, "blockers": blockers, "features": features_report}


def render_closed_progress(report: dict[str, Any]) -> str:
    """Conteúdo do `.harness/progress.md` de uma demanda encerrada.

    Deliberadamente curto e sem histórico: o arquivo é um resumo de ESTADO para
    a próxima sessão retomar, não um diário. O registro permanente do que foi
    feito é a evidência em `.harness/evidence/<contrato>/`, que o `finish`
    nunca toca. Manter narrativa antiga aqui foi o que produziu, neste repo,
    um `progress.md` afirmando por duas versões seguidas que havia trabalho não
    commitado esperando aprovação humana.
    """
    contract = report.get("contract") or "?"
    lines = [
        "# Claude Progress",
        "",
        # Header CANÔNICO (`Contrato: ` + crase), e não uma variação com o
        # "ENCERRADO" embutido na mesma linha. `templates.install_templates` só
        # restaura o progresso do contrato seguinte quando consegue ler o slug
        # antigo por este formato exato; um header decorado devolvia `None` e a
        # regeneração era pulada em silêncio, fazendo a sessão seguinte herdar
        # o resumo da demanda anterior. Foi o que aconteceu na v0.25.0: o
        # `SessionStart` injetou "nenhuma feature pendente" numa sessão com seis
        # tarefas a fazer — o modo de falha que este comando existe para matar.
        f"Contrato: `{contract}`",
        "",
        "_Demanda ENCERRADA por `harness finish`._",
        "",
        "## Features",
        "",
    ]
    features = report.get("features") or []
    if features:
        lines.append("| id | desc | status |")
        lines.append("| --- | --- | --- |")
        for feature in features:
            lines.append(f"| {feature.get('id', '')} | {feature.get('desc', '')} | done |")
    else:
        lines.append("_Nenhuma feature no contrato._")
    lines += [
        "",
        "## Última atualização",
        "",
        "_(vazio — demanda encerrada; o próximo `compile-session` regenera este "
        "arquivo a partir do contrato novo. A prova do que foi entregue está em "
        "`.harness/evidence/`.)_",
        "",
    ]
    return "\n".join(lines)


def sweep_disposables(target_dir: Path | str) -> dict[str, Any]:
    """Varre os descartáveis do `.harness/` depois de uma demanda encerrada.

    Roda `audit_closure` primeiro e levanta `FinishError` se houver qualquer
    bloqueador — limpar por cima de um fecho quebrado apagaria justamente o
    rastro necessário para consertá-lo. Com o fecho íntegro:

    - reescreve `.harness/progress.md` via `render_closed_progress`;
    - esvazia `.harness/scratch/`, preservando o `.gitignore` da pasta.

    NÃO toca em `.harness/work/`, `.harness/evidence/` nem no
    `feature_list.json` — são o histórico auditável da demanda. NÃO executa
    git nem gh. Devolve `{"contract", "progress", "scratch_removed"}`.
    """
    target_dir = Path(target_dir).resolve()
    report = audit_closure(target_dir)
    if report["blockers"]:
        kinds = ", ".join(sorted({b["kind"] for b in report["blockers"]}))
        raise FinishError(
            f"fecho reprovado na auditoria ({kinds}) — nada foi varrido. "
            "Rode `harness finish` para ver os bloqueadores em detalhe."
        )

    progress_path = target_dir / PROGRESS_FILE
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    progress_path.write_text(render_closed_progress(report), encoding="utf-8")

    removed: list[str] = []
    scratch_path = target_dir / SCRATCH_DIR
    if scratch_path.is_dir():
        for entry in sorted(scratch_path.iterdir()):
            if entry.name in SCRATCH_KEEP:
                continue
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()
            removed.append(entry.name)

    return {
        "contract": report["contract"],
        "progress": str(progress_path),
        "scratch_removed": removed,
    }


def _evidence_state(target_dir: Path, path: Path, files: list[str]) -> str:
    """`"fresh"` se o `files_hash` da evidência bate com o conteúdo atual dos
    `files`; `"stale"` caso contrário. Evidência ilegível conta como `stale` —
    prova que não pode ser lida não prova nada."""
    try:
        evidence = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return "stale"
    recorded = str(evidence.get("files_hash") or "")
    return "fresh" if recorded and recorded == compute_files_hash(files, target_dir) else "stale"
