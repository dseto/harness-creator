"""Testes do módulo compartilhado harness.findings.

`Finding`/`Report`/`PENALTY`/`finish` eram definidos byte a byte em
audit.py, runtime_audit.py e team_audit.py (~105 linhas triplicadas —
achado #13 do laudo de simplificação, T-05 do contrato onda-1). Este é o
teste direto do módulo compartilhado; os três consumidores continuam
testados nas próprias suítes (test_audit.py, test_runtime_audit.py,
test_team_audit.py), reimportando os mesmos nomes por compatibilidade.
"""

from __future__ import annotations

import json

from harness.findings import PENALTY, Finding, Report, finish


def test_finding_to_dict_has_the_four_fields() -> None:
    f = Finding("warning", "some_code", "mensagem", "correção")
    assert f.to_dict() == {
        "severity": "warning", "code": "some_code",
        "message": "mensagem", "fix": "correção",
    }


def test_report_to_dict_and_to_json_roundtrip() -> None:
    report = Report(score=85, findings=[Finding("info", "x", "m", "f")])
    as_dict = report.to_dict()
    assert as_dict["score"] == 85
    assert as_dict["findings"] == [{"severity": "info", "code": "x",
                                     "message": "m", "fix": "f"}]
    assert json.loads(report.to_json()) == as_dict


def test_finish_subtracts_penalty_per_severity_and_floors_at_zero() -> None:
    assert finish([]).score == 100
    assert finish([Finding("info", "a", "m", "f")]).score == 95
    assert finish([Finding("warning", "a", "m", "f")]).score == 85
    assert finish([Finding("critical", "a", "m", "f")]).score == 60
    # nunca negativo, mesmo com muitos criticals
    many_criticals = [Finding("critical", str(i), "m", "f") for i in range(5)]
    assert finish(many_criticals).score == 0


def test_penalty_table_matches_documented_weights() -> None:
    assert PENALTY == {"critical": 40, "warning": 15, "info": 5}
