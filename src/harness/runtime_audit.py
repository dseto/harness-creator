"""Auditoria RUNTIME: schema + frescor + invariantes dos artefatos mutáveis.

Mecanismo DISTINTO de `harness.audit` (que faz diff byte-exato dos artefatos
COMPILADOS/determinísticos contra o que `compiler.render` geraria). Este
módulo audita os artefatos que MUDAM durante a execução autônoma da sessão:
`claude-progress.md`, `.harness/feature_list.json` e `.harness/evidence/*.json`
— nunca diff byte-exato, sempre schema + frescor + invariantes de negócio.

Invariantes verificados por `audit_runtime`:
  (1) `.harness/feature_list.json` existe, é JSON válido e tem o schema
      esperado (`contract`, `compiled_at`, `features[]` com
      `id`/`desc`/`files`/`verify_cmd`/`depends`/`passes`) — ausência ou
      schema quebrado é `critical`.
  (2) `claude-progress.md` existe — `warning` se ausente.
  (3) toda feature com `passes: true` tem evidência correspondente em
      `.harness/evidence/<id>.json`: arquivo existe, é JSON válido, tem
      `feature_id == id`, os campos obrigatórios do schema de
      `harness.verify` (`verify_cmd`, `recorded_at`, `exit_code`,
      `files_hash`) e `exit_code == 0` — qualquer violação é `critical`
      citando o id da feature.
  (4) no máximo 1 feature "em progresso" — reaproveita
      `harness.stop_hook.is_feature_in_progress` (nunca reimplementa a
      lógica de `git diff`); duas ou mais é `critical` citando os ids.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from harness.contract import FEATURE_LIST_FILE
from harness.stop_hook import is_feature_in_progress
from harness.verify import EVIDENCE_DIR

PROGRESS_FILE = "claude-progress.md"

_REQUIRED_FEATURE_FIELDS = ("id", "desc", "files", "verify_cmd", "depends", "passes")
_REQUIRED_EVIDENCE_FIELDS = ("verify_cmd", "recorded_at", "exit_code", "files_hash")


@dataclass
class RuntimeFinding:
    severity: str          # "critical" | "warning" | "info"
    code: str              # slug estável p/ máquina
    message: str           # frase p/ humano
    fix: str               # como corrigir

    def to_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "code": self.code,
                "message": self.message, "fix": self.fix}


@dataclass
class RuntimeAuditReport:
    score: int
    findings: list[RuntimeFinding] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"score": self.score, "findings": [f.to_dict() for f in self.findings]}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


_PENALTY = {"critical": 40, "warning": 15, "info": 5}


def _finish(findings: list[RuntimeFinding]) -> RuntimeAuditReport:
    score = 100
    for f in findings:
        score -= _PENALTY.get(f.severity, 0)
    return RuntimeAuditReport(score=max(0, score), findings=findings)


def audit_runtime(target_dir: Path) -> RuntimeAuditReport:
    target_dir = target_dir.resolve()
    findings: list[RuntimeFinding] = []

    # --- 1. claude-progress.md existe (warning se ausente) ---
    progress_path = target_dir / PROGRESS_FILE
    if not progress_path.is_file():
        findings.append(RuntimeFinding(
            "warning", "missing_progress_file",
            f"{PROGRESS_FILE} não existe — sem rastro de progresso legível.",
            "Rode `harness compile-session` para gerar o template inicial.",
        ))

    # --- 2. feature_list.json existe, é JSON válido e tem o schema esperado ---
    feature_list_path = target_dir / FEATURE_LIST_FILE
    if not feature_list_path.is_file():
        findings.append(RuntimeFinding(
            "critical", "missing_feature_list",
            f"{FEATURE_LIST_FILE} não existe — nenhum contrato compilado.",
            "Rode `harness compile-contract --slug <slug>` para gerar o feature_list.",
        ))
        return _finish(findings)

    try:
        data = json.loads(feature_list_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        findings.append(RuntimeFinding(
            "critical", "invalid_feature_list",
            f"{FEATURE_LIST_FILE} não é JSON válido: {exc}",
            "Corrija o arquivo ou recompile o contrato (`harness compile-contract`).",
        ))
        return _finish(findings)

    if not isinstance(data, dict) or "contract" not in data or "compiled_at" not in data \
            or not isinstance(data.get("features"), list):
        findings.append(RuntimeFinding(
            "critical", "invalid_feature_list_schema",
            f"{FEATURE_LIST_FILE} não tem o schema esperado "
            "(`contract`, `compiled_at`, `features[]`).",
            "Recompile o contrato (`harness compile-contract`) para regenerar o arquivo.",
        ))
        return _finish(findings)

    features: list[dict[str, Any]] = data["features"]
    valid_features: list[dict[str, Any]] = []
    for feature in features:
        if not isinstance(feature, dict):
            findings.append(RuntimeFinding(
                "critical", "invalid_feature_schema",
                f"Entrada de feature malformada em {FEATURE_LIST_FILE}: {feature!r}",
                "Recompile o contrato (`harness compile-contract`).",
            ))
            continue
        missing = [f for f in _REQUIRED_FEATURE_FIELDS if f not in feature]
        if missing:
            fid = feature.get("id", "?")
            findings.append(RuntimeFinding(
                "critical", "invalid_feature_schema",
                f"Feature '{fid}' em {FEATURE_LIST_FILE} sem campos obrigatórios: "
                f"{', '.join(missing)}.",
                "Recompile o contrato (`harness compile-contract`).",
            ))
            continue
        valid_features.append(feature)

    # --- 3. toda feature com passes:true tem evidência válida e exit_code == 0 ---
    for feature in valid_features:
        if not feature.get("passes"):
            continue

        feature_id = feature["id"]
        evidence_path = target_dir / EVIDENCE_DIR / f"{feature_id}.json"

        if not evidence_path.is_file():
            findings.append(RuntimeFinding(
                "critical", "missing_evidence",
                f"Feature '{feature_id}' marcada passes:true mas sem evidência em "
                f"{EVIDENCE_DIR}/{feature_id}.json.",
                f"Rode `harness verify {feature_id}` para gerar a evidência.",
            ))
            continue

        try:
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            findings.append(RuntimeFinding(
                "critical", "invalid_evidence_json",
                f"Evidência de '{feature_id}' ({EVIDENCE_DIR}/{feature_id}.json) "
                f"não é JSON válido: {exc}",
                f"Rode `harness verify {feature_id}` novamente para regravar a evidência.",
            ))
            continue

        if not isinstance(evidence, dict):
            findings.append(RuntimeFinding(
                "critical", "invalid_evidence_schema",
                f"Evidência de '{feature_id}' não é um objeto JSON válido.",
                f"Rode `harness verify {feature_id}` novamente para regravar a evidência.",
            ))
            continue

        if evidence.get("feature_id") != feature_id:
            findings.append(RuntimeFinding(
                "critical", "evidence_feature_id_mismatch",
                f"Evidência em {EVIDENCE_DIR}/{feature_id}.json tem feature_id "
                f"'{evidence.get('feature_id')}', esperado '{feature_id}'.",
                f"Rode `harness verify {feature_id}` novamente para regravar a evidência.",
            ))
            continue

        missing_evidence_fields = [
            f for f in _REQUIRED_EVIDENCE_FIELDS if f not in evidence
        ]
        if missing_evidence_fields:
            findings.append(RuntimeFinding(
                "critical", "invalid_evidence_schema",
                f"Evidência de '{feature_id}' sem campos obrigatórios: "
                f"{', '.join(missing_evidence_fields)}.",
                f"Rode `harness verify {feature_id}` novamente para regravar a evidência.",
            ))
            continue

        if evidence.get("exit_code") != 0:
            findings.append(RuntimeFinding(
                "critical", "evidence_exit_code_nonzero",
                f"Evidência de '{feature_id}' tem exit_code="
                f"{evidence.get('exit_code')} (esperado 0) — verify_cmd falhou.",
                f"Corrija a feature e rode `harness verify {feature_id}` novamente.",
            ))

    # --- 4. no máximo 1 feature "em progresso" ---
    in_progress_ids = [
        feature["id"] for feature in valid_features
        if is_feature_in_progress(feature, target_dir)
    ]
    if len(in_progress_ids) > 1:
        ids = ", ".join(in_progress_ids)
        findings.append(RuntimeFinding(
            "critical", "multiple_features_in_progress",
            f"Mais de uma feature 'em progresso' simultaneamente: {ids}.",
            "Finalize e faça commit de uma feature por vez antes de iniciar a próxima.",
        ))

    return _finish(findings)
