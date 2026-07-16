"""State machine de revisão do padrão Produtor-Revisor.

Veredito do revisor sobre uma feature: `pending -> in_review -> rejected |
approved`. Este módulo é lógica pura de state machine + I/O do arquivo de
estado — NÃO decide enforcement (isso é `boundary_guard.py`, que IMPORTA as
funções daqui) nem gera artefatos de time (`teams.py`)/CLI.

Schema exato do arquivo de estado (`.harness/review/<feature_id>.json` —
outras tarefas do ROADMAP dependem deste formato, não mudar sem atualizar
consumidores):

    {
      "feature_id": "T-01",
      "status": "pending",
      "iteration": 0,
      "max_iterations": 3,
      "history": [],
      "justification": null,
      "updated_at": "2026-07-16T12:00:00+00:00"
    }

`status` é sempre um de `'pending'`, `'in_review'`, `'rejected'`,
`'approved'` (NUNCA um 5º valor, mesmo ao estourar o limite de iterações —
estourar o limite apenas liga `ReviewResult.escalate`, o `status` continua
`'rejected'`). `history` é uma lista de entradas
`{"iteration": int, "decision": "approved"|"rejected", "note": str,
"at": iso8601}`. `updated_at` é `datetime.now(timezone.utc).isoformat()` a
cada escrita em disco.

Teto duro de iterações (achado de reflect+judge): sem um teto que bloqueia
`submit_for_review`, a escalação ao humano seria só um aviso — o agente
poderia resubmeter indefinidamente. Por isso `submit_for_review` levanta
`ReviewError` quando o registro já rejeitado esgotou `max_iterations`, em
vez de permitir mais uma volta do ciclo.

Gate adicional para diffs de teste (defesa da Fase 2 contra o agente
reescrever o próprio teste pra passar, agora também no revisor):
`record_decision` exige `justification` não-vazia para aprovar uma feature
cujos `files[]` casam o `test_glob` do repo-profile.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness.analyzer import REPO_PROFILE_PATH
from harness.verification.tdd_loop import _glob_to_regex

REVIEW_DIR = ".harness/review"

_VALID_STATUSES = {"pending", "in_review", "rejected", "approved"}


class ReviewError(Exception):
    """Erro de uso do state machine: transição inválida ou justificativa faltando."""


@dataclass
class ReviewResult:
    status: str
    iteration: int
    escalate: bool
    message: str


def _review_path(target_dir: Path, feature_id: str) -> Path:
    return target_dir / REVIEW_DIR / f"{feature_id}.json"


def _default_review(feature_id: str) -> dict[str, Any]:
    return {
        "feature_id": feature_id,
        "status": "pending",
        "iteration": 0,
        "max_iterations": 3,
        "history": [],
        "justification": None,
        "updated_at": "",
    }


def load_review(target_dir: Path, feature_id: str) -> dict[str, Any]:
    """Lê `.harness/review/<feature_id>.json`; se não existir, devolve o
    registro DEFAULT (`status='pending'`, `iteration=0`, etc.) SEM gravar em
    disco — só materializa quando alguma função de transição grava de
    verdade."""
    path = _review_path(target_dir, feature_id)
    if not path.is_file():
        return _default_review(feature_id)

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReviewError(f"{path}: JSON inválido — {exc}") from exc

    return data


def _write_review(target_dir: Path, feature_id: str, record: dict[str, Any]) -> dict[str, Any]:
    record = dict(record)
    record["updated_at"] = datetime.now(timezone.utc).isoformat()
    path = _review_path(target_dir, feature_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return record


def submit_for_review(target_dir: Path, feature_id: str, max_iterations: int = 3) -> dict[str, Any]:
    """Submete a feature `feature_id` para revisão: `pending|rejected ->
    in_review`, incrementando `iteration` em 1.

    Levanta `ReviewError` se o estado atual não for `'pending'` nem
    `'rejected'`. Teto duro (achado de reflect+judge: sem isso a escalação é
    só um aviso, o agente pode resubmeter pra sempre): se `status ==
    'rejected'` e o registro já gravado tem `iteration >= max_iterations`
    (usando o `max_iterations` JÁ GRAVADO no arquivo, não o parâmetro),
    levanta `ReviewError` orientando a escalar ao humano em vez de
    resubmeter. `max_iterations` (parâmetro) só é usado na PRIMEIRA
    submissão (arquivo ainda não existe); depois disso, o valor já gravado
    no arquivo prevalece e o parâmetro é ignorado."""
    target_dir = target_dir.resolve()
    path = _review_path(target_dir, feature_id)
    already_persisted = path.is_file()
    record = load_review(target_dir, feature_id)

    status = record["status"]
    if status not in ("pending", "rejected"):
        raise ReviewError(
            f"submit_for_review: transição inválida a partir do estado '{status}' — "
            "só é permitido submeter a partir de 'pending' ou 'rejected'"
        )

    effective_max_iterations = record["max_iterations"] if already_persisted else max_iterations

    if status == "rejected" and record["iteration"] >= effective_max_iterations:
        raise ReviewError(
            "limite de max_iterations atingido na iteração anterior — não "
            "resubmeta, escale ao humano (ele pode destravar subindo "
            "max_review_iterations no manifesto ou resetando o registro de revisão)"
        )

    record["status"] = "in_review"
    record["iteration"] = record["iteration"] + 1
    record["max_iterations"] = effective_max_iterations

    return _write_review(target_dir, feature_id, record)


def is_test_diff(feature: dict[str, Any], target_dir: Path) -> bool:
    """`True` se algum caminho em `feature.get('files') or []` casar o
    `test_glob` gravado em `.harness/repo-profile.json` (via `_glob_to_regex`
    importada de `harness.verification.tdd_loop` — não reimplementa o
    algoritmo). `False` se não houver profile ou `test_glob`."""
    profile_path = target_dir / REPO_PROFILE_PATH
    if not profile_path.is_file():
        return False

    try:
        profile_data = json.loads(profile_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False

    test_glob_finding = profile_data.get("test_glob")
    if not test_glob_finding:
        return False

    test_glob = test_glob_finding.get("value")
    if not test_glob:
        return False

    pattern = _glob_to_regex(test_glob)
    files = feature.get("files") or []
    return any(pattern.match(Path(f).as_posix()) for f in files)


def record_decision(
    target_dir: Path,
    feature_id: str,
    feature: dict[str, Any],
    decision: str,
    note: str,
    justification: str | None = None,
) -> ReviewResult:
    """Registra o veredito do revisor sobre a feature em revisão.

    Só permitido a partir de `status == 'in_review'` (senão `ReviewError`).
    `decision` deve ser `'approved'` ou `'rejected'` (senão `ReviewError`).

    Se `decision == 'approved'` e `is_test_diff(feature, target_dir)` for
    `True`, `justification` (não-vazia após `.strip()`) é OBRIGATÓRIA — sem
    ela, `ReviewError` (proteção da Fase 2 contra o agente reescrever o
    próprio teste pra passar, agora também gateada pelo revisor).
    `justification` é gravada no registro sempre que fornecida, mesmo em
    decisões não relacionadas a teste.

    Se `decision == 'rejected'`: `status` continua `'rejected'`
    INDEPENDENTE de `escalate` — nunca vira `'approved'` por estourar o
    limite de iterações (divergência deliberada exigida pelo ROADMAP.md).
    `escalate = iteration >= max_iterations`.
    """
    target_dir = target_dir.resolve()
    record = load_review(target_dir, feature_id)

    status = record["status"]
    if status != "in_review":
        raise ReviewError(
            f"record_decision: transição inválida a partir do estado '{status}' — "
            "só é permitido registrar decisão a partir de 'in_review'"
        )

    if decision not in ("approved", "rejected"):
        raise ReviewError(
            f"record_decision: decisão inválida '{decision}' — use 'approved' ou 'rejected'"
        )

    if decision == "approved" and is_test_diff(feature, target_dir):
        if justification is None or not justification.strip():
            raise ReviewError(
                "aprovar diff de teste exige justificativa de por que a "
                "expectativa mudou"
            )

    iteration = record["iteration"]
    max_iterations = record["max_iterations"]

    history_entry = {
        "iteration": iteration,
        "decision": decision,
        "note": note,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    record["history"] = list(record.get("history", [])) + [history_entry]

    if justification is not None:
        record["justification"] = justification

    if decision == "approved":
        record["status"] = "approved"
        escalate = False
        message = f"aprovado na iteração {iteration}"
    else:
        record["status"] = "rejected"
        escalate = iteration >= max_iterations
        if escalate:
            message = (
                f"rejeitado na iteração {iteration} — limite de max_iterations "
                "atingido, ESCALE ao humano em vez de insistir"
            )
        else:
            message = f"rejeitado na iteração {iteration} — refaça e resubmeta"

    record = _write_review(target_dir, feature_id, record)

    return ReviewResult(
        status=record["status"],
        iteration=record["iteration"],
        escalate=escalate,
        message=message,
    )
