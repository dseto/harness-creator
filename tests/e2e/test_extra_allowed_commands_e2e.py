"""E2E (gate final da demanda `extra-allowed-commands`): prova REAL, não
sintética, do cenário motivador (dogfood `entebate`/`elegant-heisenberg`).

Regra permanente do ROADMAP: toda fase fecha com prova real (mock em disco +
hook real via subprocess) e uma evidência legível commitada em markdown.
Este teste monta um repo mock cujo produto é um CLI (`python -m mar_committee`,
mesmo nome do cenário real que motivou a demanda) — contrato ativo com
`passes:true` mas SEM `verify_cmd` cobrindo o CLI, e
`.harness/harness.yaml` declarando `governance.extra_allowed_commands`.
Instala o `boundary_guard.py` de verdade (`install_boundary_guard`, função
real do pacote — o mesmo caminho que `harness compile-session` percorre) e
invoca o script instalado via `subprocess.run` DE VERDADE, duas vezes: um
comando declarado (esperado `allow`) e um comando não declarado, fora de
`verify_cmd`/superfície (esperado `deny`). Grava
`tests/e2e/evidence/extra-allowed-commands-dogfood-2026-07-22.md` com os
dois JSONs de decisão reais.

Não usa `HARNESS_E2E_DOGFOOD`: não invoca claude/dotnet, é barato e roda no
gate padrão da suíte.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from harness.boundary_guard import (
    BOUNDARY_HOOK_FILENAME,
    HOOKS_DIR,
    install_boundary_guard,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_PATH = (
    Path(__file__).resolve().parent / "evidence" / "extra-allowed-commands-dogfood-2026-07-22.md"
)


def _write_feature_list(target: Path) -> None:
    path = target / ".harness" / "feature_list.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "contract": "mar-committee-mock",
        "compiled_at": "2026-07-22T00:00:00+00:00",
        "features": [
            {
                "id": "T-01",
                "desc": "avaliação MAR do pipeline",
                "files": ["src/mar_committee/pipeline.py"],
                "verify_cmd": "pytest -q",
                "depends": [],
                "passes": True,
            }
        ],
    }), encoding="utf-8")


def _write_profile(target: Path) -> None:
    path = target / ".harness" / "repo-profile.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "languages": [{"value": "python", "evidence": "pyproject.toml", "confidence": 1.0}],
        "package_manager": None,
        "test_command": {"value": "pytest", "evidence": "pyproject.toml", "confidence": 1.0},
        "test_glob": {"value": "tests/**/*.py", "evidence": "tests/test_x.py", "confidence": 1.0},
        "extras": {},
    }), encoding="utf-8")


def _write_harness_yaml(target: Path) -> None:
    path = target / ".harness" / "harness.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "governance:\n"
        "  extra_allowed_commands:\n"
        '    - "python -m mar_committee"\n',
        encoding="utf-8",
    )


def _run_hook(script: Path, tool_input_command: str, cwd: Path) -> dict:
    payload = {
        "tool_name": "Bash",
        "cwd": str(cwd),
        "tool_input": {"command": tool_input_command},
    }
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["hookSpecificOutput"]


def _write_evidence(allow_result: dict, deny_result: dict) -> None:
    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    content = f"""\
# Evidência dogfood — `governance.extra_allowed_commands` (gate final da demanda)

**Data:** 2026-07-22
**Teste:** `tests/e2e/test_extra_allowed_commands_e2e.py::test_extra_allowed_commands_e2e_dogfood`

Prova REAL exigida pelo ROADMAP: mock em disco de um repo cujo produto é um
CLI (`python -m mar_committee` — mesmo comando do cenário real do repo
`entebate` que motivou esta demanda), contrato ativo com a feature
`passes:true` mas SEM `verify_cmd` cobrindo o CLI, e `.harness/harness.yaml`
declarando `governance.extra_allowed_commands: ["python -m mar_committee"]`.
`install_boundary_guard` (função REAL do pacote, mesmo caminho de
`harness compile-session`) instala o hook em disco; os dois blocos JSON
abaixo são a **saída literal** do script instalado, invocado via
`subprocess.run` (interpretador `{sys.executable}`).

Script instalado em `{HOOKS_DIR}/{BOUNDARY_HOOK_FILENAME}` (relativo à raiz
do mock efêmero em `tmp_path` — o path absoluto varia por rodada e não entra
na evidência versionada).

---

## Comando declarado em `extra_allowed_commands` — `python -m mar_committee config-show`

Sem esta feature, o guard negaria: nenhum `verify_cmd` do contrato cobre o
CLI do produto (só `pytest -q`), e não há sequência fixa (`git`/`harness`)
nem utilitário read-only que case.

```json
{json.dumps(allow_result, indent=2, ensure_ascii=False)}
```

## Comando NÃO declarado — `algum-cli-nao-declarado --flag`

Continua fora da superfície (`verify_cmd`/lint/build/install/git local) —
`extra_allowed_commands` libera só o que foi explicitamente declarado, não
qualquer comando.

```json
{json.dumps(deny_result, indent=2, ensure_ascii=False)}
```

---

## Interpretação

O comando declarado (`python -m mar_committee config-show`, prefixado por
`python -m mar_committee`) recebe **allow** — o cenário real que motivou a
demanda (CLI do próprio produto bloqueado mesmo com contrato `passes:true`)
está resolvido sem precisar de um contrato ad-hoc cujos `verify_cmd` SEJAM os
subcomandos do CLI. Um comando fora da superfície declarada continua **deny**
— `extra_allowed_commands` amplia a superfície de forma explícita e auditável,
não abre um allow genérico.
"""
    EVIDENCE_PATH.write_text(content, encoding="utf-8")


def test_extra_allowed_commands_e2e_dogfood(tmp_path: Path) -> None:
    mock_root = tmp_path / "mar_committee_mock"
    mock_root.mkdir()

    _write_feature_list(mock_root)
    _write_profile(mock_root)
    _write_harness_yaml(mock_root)

    script = install_boundary_guard(mock_root)
    assert script.is_file()

    allow_result = _run_hook(script, "python -m mar_committee config-show", mock_root)
    assert allow_result["permissionDecision"] == "allow", allow_result

    deny_result = _run_hook(script, "algum-cli-nao-declarado --flag", mock_root)
    assert deny_result["permissionDecision"] == "deny", deny_result

    _write_evidence(allow_result, deny_result)

    assert EVIDENCE_PATH.is_file()
    written = EVIDENCE_PATH.read_text(encoding="utf-8")
    assert '"permissionDecision": "allow"' in written
    assert '"permissionDecision": "deny"' in written
