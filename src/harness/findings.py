"""Fonte única de `Finding`/`Report`/`PENALTY`/`finish` — compartilhada por
`audit.py`, `runtime_audit.py` e `team_audit.py`.

Os três mecanismos de auditoria são genuinamente distintos (diff byte-exato
dos artefatos compilados; schema+frescor+invariantes dos artefatos
mutáveis da sessão; catálogo de time vs. agentes gerados) — só a definição
de achado e a forma do relatório eram idênticas byte a byte nos três
módulos. Cada consumidor reimporta estes nomes sob o alias histórico
próprio (`AuditReport`, `RuntimeFinding`, `TeamAuditReport`...), então
nenhum código externo precisa mudar.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Finding:
    severity: str          # "critical" | "warning" | "info"
    code: str               # slug estável p/ máquina
    message: str            # frase p/ humano
    fix: str                # como corrigir

    def to_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "code": self.code,
                "message": self.message, "fix": self.fix}


@dataclass
class Report:
    score: int
    findings: list[Finding] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"score": self.score, "findings": [f.to_dict() for f in self.findings]}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


PENALTY = {"critical": 40, "warning": 15, "info": 5}


def finish(findings: list[Finding]) -> Report:
    score = 100
    for f in findings:
        score -= PENALTY.get(f.severity, 0)
    return Report(score=max(0, score), findings=findings)
