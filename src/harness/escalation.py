"""Escalada ao humano — o formato obrigatório da §8 do design de loop
engineering (contrato `falha-transiente-e-escalada`, T-04).

Até aqui `budget.check_budget` devolvia um veredito de parada com uma razão
em prosa livre — nada obrigava as seis partes que a §8 pede, na ordem que
ela pede:

    O que estava sendo tentado (fatia + critério)
    O que foi tentado (abordagens, em ordem)
    Último erro (cru)
    Classificação (transiente esgotado / estrutural no teto / infra / impossibilidade)
    Estado da spine (atualizada? tree limpa?)
    Sugestão de próximo passo, se houver

Este módulo só RENDERIZA a partir do que já existe em disco: o `feature_list.json`
compilado, o rastro de `attempts.py` e (só-leitura, mesmo padrão de
`finish._tracked_dirty_paths`) `git status --porcelain`. Não decide veredito
— isso é `budget.py` — e não executa `verify_cmd` nem escreve nada.

Um bloco fica fora do alcance mecânico por desenho: "abordagens tentadas" no
sentido de INTENÇÃO (o que se decidiu tentar, e por quê) nunca foi gravado em
lugar nenhum do harness — só o ERRO de cada tentativa foi. O bloco declara
essa lacuna explicitamente, em vez de fingir que tem o dado (mesma fronteira
de D-004: "o julgamento não dá para mecanizar, mas a ausência dá").

"Impossibilidade" — uma das quatro classificações que a §8 lista — também não
é mecanizada aqui: é a mesma classe de julgamento que D-004 já reservou para
as `stop_conditions` em prosa do `spec.md`. Este módulo só produz as
classificações que `budget.py` de fato deriva por contagem: "transiente
esgotado", "estrutural no teto", e as duas de trajetória do §4.3 (contrato
`convergencia-opt-in`) — "trajetória em piora"/"trajetória em platô", que
também ganham uma linha extra na parte "Estado da spine" quando a tarefa tem
`metric_cmd`: série recente + melhor valor e onde ele ocorreu.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from harness.attempts import open_failures, read_attempts
from harness.branching import is_git_repository, unmanaged_dirty_paths
from harness.budget import (
    CONTINUE,
    STOP_ITERATIONS,
    STOP_PLATEAU,
    STOP_SAME_FAILURE,
    STOP_TRANSIENT_EXHAUSTED,
    STOP_WORSENING,
)
from harness.contract import FEATURE_LIST_FILE
from harness.convergence import read_measurements, summarize_trajectory

#: Rótulo em português para a linha "Classificação" do formato do §8. Os dois
#: vereditos estruturais (mesma falha / teto de iterações) caem no mesmo
#: rótulo — a §8 distingue quatro categorias, mais grossas que os vereditos
#: internos de `budget.py`; nenhum verdict devolve "infra" ou
#: "impossibilidade" aqui, ver docstring do módulo.
#:
#: `stop_worsening`/`stop_plateau` (§4.3, contrato `convergencia-opt-in`) são
#: um sinal DIFERENTE das quatro categorias do §8 — não é sobre a execução do
#: loop (código quebrado, ambiente instável), é sobre a TRAJETÓRIA do
#: artefato. Rótulo próprio em vez de forçar em "estrutural": encaixar
#: piora/platô ali confundiria o humano que lê a escalada sobre o que de
#: fato aconteceu.
_CLASSIFICATION_LABEL = {
    STOP_SAME_FAILURE: "estrutural no teto",
    STOP_ITERATIONS: "estrutural no teto",
    STOP_TRANSIENT_EXHAUSTED: "transiente esgotado",
    STOP_WORSENING: "trajetória em piora (§4.3)",
    STOP_PLATEAU: "trajetória em platô (§4.3)",
}


class EscalationError(Exception):
    """Contrato não compilado, feature inexistente, ou veredito `continue`
    (escalar um `continue` não faz sentido — não há nada para escalar)."""


def _load_feature(target_dir: Path, feature_id: str) -> dict[str, Any]:
    path = target_dir / FEATURE_LIST_FILE
    if not path.is_file():
        raise EscalationError(
            f"`{FEATURE_LIST_FILE}` ausente — não há contrato compilado de onde ler "
            "a fatia e o critério."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise EscalationError(f"`{FEATURE_LIST_FILE}` ilegível — {exc}") from exc

    for feature in data.get("features") or []:
        if isinstance(feature, dict) and feature.get("id") == feature_id:
            return feature
    raise EscalationError(f"feature '{feature_id}' não encontrada em {FEATURE_LIST_FILE}")


def _error_trail(records: list[dict[str, Any]]) -> str:
    """A sequência de erros em aberto, em ordem — o que É mecanizável do
    bloco "abordagens tentadas". Ver docstring do módulo para o que NÃO é."""
    trailing = open_failures(records)
    if not trailing:
        return "  (nenhuma tentativa registrada)"
    lines = []
    for index, record in enumerate(trailing, start=1):
        line = record.get("failure_line") or "(sem mensagem)"
        kind = record.get("classification") or "structural"
        lines.append(f"  {index}. [{kind}] {line}")
    return "\n".join(lines)


def _spine_state(target_dir: Path) -> str:
    """`git status --porcelain` só-leitura — mesmo padrão de
    `finish._tracked_dirty_paths`. `progress.md` não é reconferido aqui: todo
    caminho de falha de `verify.run_verify` já chama `update_progress_attempts`
    antes de levantar, então a sincronia é garantia de construção, não algo a
    reinspecionar."""
    if not is_git_repository(target_dir):
        return "fora de um repositório git — não há tree para checar"
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain", "-uno"],
            cwd=target_dir,
            capture_output=True,
            text=True,
        )
    except OSError:
        return "git indisponível — não foi possível checar a tree"
    if proc.returncode != 0:
        return "`git status` falhou — não foi possível checar a tree"

    dirty = unmanaged_dirty_paths(proc.stdout)
    if not dirty:
        return "tree limpa; progress.md sincronizado automaticamente por harness verify"
    shown = ", ".join(dirty[:5]) + ("…" if len(dirty) > 5 else "")
    return f"tree suja ({len(dirty)} arquivo(s) fora do que o harness gerencia): {shown}"


def _trajectory_line(
    target_dir: Path, contract: Any, feature: dict[str, Any]
) -> str | None:
    """Linha extra da parte "Estado da spine" quando a tarefa tem métrica
    (§4.3): série recente + melhor valor e onde ele ocorreu — o humano vê a
    curva, não só o último erro. `None` sem `metric_cmd`/`metric_target` ou
    sem medição registrada ainda (mesmo silêncio de tarefa sem métrica)."""
    metric_cmd = feature.get("metric_cmd")
    metric_target = feature.get("metric_target")
    if not metric_cmd or not metric_target:
        return None

    feature_id = str(feature.get("id") or "")
    measurements = read_measurements(target_dir, contract, feature_id)
    if not measurements:
        return None

    trajectory = summarize_trajectory(measurements, metric_target)
    recent = ", ".join(str(record.get("value")) for record in measurements[-5:])
    best = trajectory["best"]
    best_desc = (
        f"{best['value']} em {best.get('recorded_at') or '?'} "
        f"(commit {best.get('commit') or '?'})"
    )
    return f"Trajetória: últimas medições [{recent}]; melhor: {best_desc}"


def render_escalation(target_dir: Path | str, report: dict[str, Any]) -> str:
    """Monta o bloco de escalada nas seis partes do §8, a partir de um
    `report` já devolvido por `budget.check_budget`.

    Levanta `EscalationError` se `report["verdict"] == "continue"` — não há o
    que escalar — ou se o contrato/feature por trás do `report` não existir
    mais em disco.
    """
    if report.get("verdict") == CONTINUE:
        raise EscalationError(
            "veredito 'continue' não escala — não há parada para diagnosticar"
        )

    target_dir = Path(target_dir).resolve()
    feature_id = report["feature_id"]
    contract = report.get("contract")

    feature = _load_feature(target_dir, feature_id)
    records = read_attempts(target_dir, contract, feature_id)
    label = _CLASSIFICATION_LABEL.get(report["verdict"], report["verdict"])

    spine = _spine_state(target_dir)
    trajectory_line = _trajectory_line(target_dir, contract, feature)
    if trajectory_line:
        spine = f"{spine}\n  {trajectory_line}"

    return (
        "O que estava sendo tentado (fatia + critério):\n"
        f"  {feature.get('desc') or '(sem descrição)'} — prova: `{feature.get('verify_cmd') or '?'}`\n\n"
        "O que foi tentado (abordagens, em ordem):\n"
        f"{_error_trail(records)}\n"
        "  (rastro mecânico = ERRO de cada tentativa, não a intenção; a "
        "abordagem de cada uma é julgamento de quem implementou e não fica "
        "gravada em lugar nenhum do harness)\n\n"
        "Último erro (cru):\n"
        f"  {report.get('last_failure_line') or '(nenhum registrado)'}\n\n"
        "Classificação:\n"
        f"  {label}\n\n"
        "Estado da spine:\n"
        f"  {spine}\n\n"
        "Sugestão de próximo passo:\n"
        f"  {report.get('reason') or '(nenhuma)'}\n"
    )
