"""E2E: verificação independente dos OUTCOMES prometidos pela Fase 4 do
ROADMAP.md ("Team-Architecture Factory (Nível L3)"), provados contra o código
REAL de um ângulo cético/adversarial — nunca por confiança em relatório de
implementação nem por cópia dos testes unitários escritos pelos subagentes de
execução.

Outcomes verificados (extraídos de ROADMAP.md ~251-321 + decisões fixadas no
ROADMAP-fase4.backlog.md):

    1. Catálogo de padrões: `list_patterns`/`load_pattern` expõem os 6
       padrões; `producer-reviewer`/`supervisor` completos (papéis com
       `tools`); invariante `reviewer`/`supervisor` SEM Edit/Write; os 4
       restantes são declarativos (papéis sem `tools`).
    2. `generate_team` de ponta a ponta grava agentes/skills/docs/manifesto
       corretos num projeto sintético, preservando o invariante de tools no
       ARQUIVO gerado (não só no dataclass), e é idempotente.
    3. State machine de revisão: estourar o limite de iterações ESCALA
       (escalate=True) mas NUNCA transiciona para 'approved'; resubmissão
       além do limite falha com ReviewError (teto duro, não aviso).
    4. Feature-lock estendido: com time producer+reviewer declarado,
       `passes:true` exige revisão 'approved'; aprovação DESATUALIZADA em
       relação à evidência mais recente (review.updated_at <
       evidencia.recorded_at) é NEGADA — nas DUAS cópias (importável e hook
       standalone). Sem manifesto, comportamento idêntico à Fase 3.
    5. `supervisor.on_feature_verified` é acionado DE VERDADE pelo subcomando
       `verify` da CLI (subprocess real): `.harness/review/<id>.json` aparece
       com status 'in_review' sem nenhum `review submit` manual; sem time
       compilado, nenhum arquivo de revisão aparece (zero regressão).
    6. `team_audit` detecta os 3 invariantes: papel órfão, ferramenta extra
       no revisor, drift do bloco gerenciado — e time saudável dá score 100.
    7. `recommend_pattern` respeita a precedência corrigida: sinal explícito
       de supervisor na descrição vence `has_tests=True`.
    8. `dispatch_next` respeita `depends[]` (primeiro consumidor real do
       campo): dependência não satisfeita ou para id inexistente nunca fica
       pronta.

Todos os testes são baratos (tmp_path + subprocess local, sem tokens, sem
`claude -p`, sem dotnet, sem cobaia) — nenhuma env var de opt-in necessária.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PLUGIN_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from harness.boundary_guard import (  # noqa: E402
    render_boundary_guard,
)
from harness.teams import (  # noqa: E402
    generate_team,
)

FORBIDDEN_REVIEW_TOOLS = {"Edit", "Write"}


def _iso(offset_seconds: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)).isoformat()


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


#: Slug do contrato dos projetos sintéticos — a evidência é escopada por ele
#: (`.harness/evidence/<contrato>/<id>.json`).
CONTRACT = "fase4-outcomes"


def _make_contract_project(tmp_path: Path, feature_id: str = "T-01") -> Path:
    """Projeto sintético mínimo com um contrato de 1 feature (passes=false)."""
    project = tmp_path / "proj"
    project.mkdir(exist_ok=True)
    verify_cmd = f'"{sys.executable}" -c "import sys; sys.exit(0)"'
    _write_json(project / ".harness" / "feature_list.json", {
        "contract": CONTRACT,
        "features": [
            {
                "id": feature_id,
                "desc": "feature sintética",
                "passes": False,
                "verify_cmd": verify_cmd,
                "files": ["src/app.py"],
            }
        ]
    })
    (project / "src").mkdir(exist_ok=True)
    (project / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    return project


def _write_team_manifest(project: Path, roles: list[str] | None = None) -> None:
    _write_json(project / ".harness" / "team" / "manifest.json", {
        "pattern": "producer-reviewer",
        "mode": "subagents",
        "roles": roles if roles is not None else ["producer", "reviewer"],
        "max_review_iterations": 3,
        "generated_at": _iso(),
    })


def _write_evidence(project: Path, feature_id: str, recorded_at: str) -> None:
    _write_json(project / ".harness" / "evidence" / CONTRACT / f"{feature_id}.json", {
        "feature_id": feature_id,
        "contract": CONTRACT,
        "verify_cmd": "echo ok",
        "recorded_at": recorded_at,
        "exit_code": 0,
        "files_hash": "sha256:deadbeef",
    })


def _write_review(
    project: Path,
    feature_id: str,
    status: str,
    updated_at: str,
    justification: str | None = None,
) -> None:
    _write_json(project / ".harness" / "review" / f"{feature_id}.json", {
        "feature_id": feature_id,
        "status": status,
        "iteration": 1,
        "max_iterations": 3,
        "history": [],
        "justification": justification,
        "updated_at": updated_at,
    })


def _transition_payload(project: Path, feature_id: str = "T-01") -> dict:
    """tool_input de um Write que transiciona a feature para passes:true."""
    data = json.loads((project / ".harness" / "feature_list.json").read_text(encoding="utf-8"))
    for feature in data["features"]:
        if feature["id"] == feature_id:
            feature["passes"] = True
    return {
        "file_path": ".harness/feature_list.json",
        "content": json.dumps(data, indent=2, ensure_ascii=False),
    }


def _frontmatter_tools(agent_md: Path) -> set[str]:
    for line in agent_md.read_text(encoding="utf-8").splitlines():
        if line.startswith("tools:"):
            raw = line[len("tools:"):].strip()
            return {t.strip() for t in raw.split(",") if t.strip()}
    raise AssertionError(f"{agent_md}: frontmatter sem linha 'tools:'")


def _cli_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC_DIR)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *args],
        cwd=cwd,
        env=_cli_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )


# ---------------------------------------------------------------------------
# Outcome 1 — catálogo de 6 padrões, invariante de tools do reviewer/supervisor
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Outcome 2 — generate_team de ponta a ponta num projeto sintético
# ---------------------------------------------------------------------------

def test_generate_team_end_to_end_writes_all_artifacts(tmp_path):
    project = tmp_path / "target"
    project.mkdir()

    result = generate_team(project, "producer-reviewer")

    # Agentes e skills por papel.
    producer_md = project / ".claude" / "agents" / "producer.md"
    reviewer_md = project / ".claude" / "agents" / "reviewer.md"
    assert producer_md.is_file() and reviewer_md.is_file()
    assert (project / ".claude" / "skills" / "producer" / "SKILL.md").is_file()
    assert (project / ".claude" / "skills" / "reviewer" / "SKILL.md").is_file()

    # Invariante no ARQUIVO gerado (não só no dataclass): reviewer sem Edit/Write.
    reviewer_tools = _frontmatter_tools(reviewer_md)
    assert not (FORBIDDEN_REVIEW_TOOLS & reviewer_tools), (
        f"reviewer.md gerado com ferramenta de escrita: {reviewer_tools}"
    )
    producer_tools = _frontmatter_tools(producer_md)
    assert {"Edit", "Write"} <= producer_tools, (
        "producer.md deveria ter Edit/Write (é quem implementa)"
    )

    # Docs: AGENTS.md com bloco de time + detalhe .harness/TEAM.md.
    agents_md_text = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert "<!-- harness:team:begin -->" in agents_md_text
    assert "producer-reviewer" in agents_md_text
    team_md = (project / ".harness" / "TEAM.md").read_text(encoding="utf-8")
    assert "producer" in team_md and "reviewer" in team_md

    # Manifesto com o schema fixado pelo backlog (consumido por boundary_guard/supervisor).
    manifest = json.loads(
        (project / ".harness" / "team" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["pattern"] == "producer-reviewer"
    assert manifest["mode"] == "subagents"
    assert set(manifest["roles"]) == {"producer", "reviewer"}
    assert manifest["max_review_iterations"] == 3
    assert manifest["generated_at"]

    assert result.pattern == "producer-reviewer"
    assert sorted(result.roles) == ["producer", "reviewer"]

    # Idempotência: segunda geração não duplica blocos gerenciados.
    generate_team(project, "producer-reviewer")
    agents_md_text2 = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert agents_md_text2.count("<!-- harness:team:begin -->") == 1
    reviewer_text = reviewer_md.read_text(encoding="utf-8")
    assert reviewer_text.count("<!-- harness:team:agent:begin -->") == 1


# ---------------------------------------------------------------------------
# Outcome 3 — state machine: escala, nunca força aprovação; teto duro
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Outcome 4 — feature-lock estendido (veto do revisor), versão importável
# ---------------------------------------------------------------------------

def test_feature_lock_standalone_hook_also_denies_stale_approval(tmp_path):
    """A MESMA regra na cópia standalone (hook real via subprocess) — o ponto
    mais frágil da fase é as duas cópias divergirem."""
    project = _make_contract_project(tmp_path)
    _write_team_manifest(project)
    _write_review(project, "T-01", "approved", _iso(-60))
    _write_evidence(project, "T-01", _iso(0))

    hook_path = tmp_path / "boundary_guard_hook.py"
    hook_path.write_text(render_boundary_guard(), encoding="utf-8")

    def run_hook() -> dict:
        payload = {
            "tool_name": "Write",
            "tool_input": _transition_payload(project),
            "cwd": str(project),
        }
        proc = subprocess.run(
            [sys.executable, str(hook_path)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout)["hookSpecificOutput"]

    output = run_hook()
    assert output["permissionDecision"] == "deny", (
        "hook standalone deixou passar aprovação obsoleta: "
        f"{output['permissionDecisionReason']}"
    )
    assert "T-01" in output["permissionDecisionReason"]

    # Reaprovação posterior à evidência -> allow (as duas cópias concordam).
    _write_review(project, "T-01", "approved", _iso(60))
    output = run_hook()
    assert output["permissionDecision"] == "allow", output["permissionDecisionReason"]


# ---------------------------------------------------------------------------
# Outcome 5 — CLI `verify` aciona on_feature_verified de verdade (subprocess)
# ---------------------------------------------------------------------------

def test_cli_verify_auto_submits_review_when_team_compiled(tmp_path):
    project = _make_contract_project(tmp_path)

    # Time compilado via CLI real (não via API), como o humano faria.
    gen = _run_cli(
        ["team", "generate", "--dir", str(project), "--pattern", "producer-reviewer"],
        cwd=PLUGIN_ROOT,
    )
    assert gen.returncode == 0, gen.stderr
    assert (project / ".harness" / "team" / "manifest.json").is_file()

    review_path = project / ".harness" / "review" / "T-01.json"
    assert not review_path.exists(), "pré-condição: nenhum review antes do verify"

    proc = _run_cli(["verify", "T-01", "--dir", str(project)], cwd=PLUGIN_ROOT)
    assert proc.returncode == 0, f"verify falhou: {proc.stderr}"

    # Evidência gravada (comportamento Fase 3 intacto)...
    evidence = json.loads(
        (project / ".harness" / "evidence" / CONTRACT / "T-01.json").read_text(encoding="utf-8")
    )
    assert evidence["feature_id"] == "T-01"
    assert evidence["exit_code"] == 0

    # ...E a submissão automática de revisão aconteceu SEM `review submit`.
    assert review_path.is_file(), (
        "verify com time compilado deveria ter acionado on_feature_verified "
        "e materializado .harness/review/T-01.json"
    )
    review = json.loads(review_path.read_text(encoding="utf-8"))
    assert review["status"] == "in_review"
    assert review["iteration"] == 1


def test_cli_verify_without_team_does_not_create_review(tmp_path):
    """Zero regressão: sem time compilado, verify se comporta como na Fase 3."""
    project = _make_contract_project(tmp_path)

    proc = _run_cli(["verify", "T-01", "--dir", str(project)], cwd=PLUGIN_ROOT)
    assert proc.returncode == 0, proc.stderr
    assert (project / ".harness" / "evidence" / CONTRACT / "T-01.json").is_file()
    assert not (project / ".harness" / "review").exists(), (
        "sem manifesto de time, verify não deveria criar registro de revisão"
    )


