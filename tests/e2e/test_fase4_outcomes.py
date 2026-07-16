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

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PLUGIN_ROOT / "src"
PATTERNS_DIR = PLUGIN_ROOT / "teams" / "patterns"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from harness.boundary_guard import (  # noqa: E402
    evaluate_feature_list_edit,
    render_boundary_guard,
)
from harness.review import ReviewError, record_decision, submit_for_review  # noqa: E402
from harness.supervisor import dispatch_next, on_feature_verified  # noqa: E402
from harness.team_audit import audit_team  # noqa: E402
from harness.teams import (  # noqa: E402
    TeamError,
    generate_team,
    list_patterns,
    load_pattern,
    recommend_pattern,
)

EXPECTED_PATTERNS = {
    "producer-reviewer",
    "supervisor",
    "pipeline",
    "expert-pool",
    "fan-out-fan-in",
    "hierarchical-delegation",
}
DECLARATIVE_PATTERNS = {
    "pipeline",
    "expert-pool",
    "fan-out-fan-in",
    "hierarchical-delegation",
}
FORBIDDEN_REVIEW_TOOLS = {"Edit", "Write"}


def _iso(offset_seconds: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)).isoformat()


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _make_contract_project(tmp_path: Path, feature_id: str = "T-01") -> Path:
    """Projeto sintético mínimo com um contrato de 1 feature (passes=false)."""
    project = tmp_path / "proj"
    project.mkdir(exist_ok=True)
    verify_cmd = f'"{sys.executable}" -c "import sys; sys.exit(0)"'
    _write_json(project / ".harness" / "feature_list.json", {
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
    _write_json(project / ".harness" / "evidence" / f"{feature_id}.json", {
        "feature_id": feature_id,
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

def test_catalog_exposes_six_patterns_with_tool_invariant():
    names = list_patterns()
    assert set(names) == EXPECTED_PATTERNS, (
        f"catálogo deveria expor exatamente os 6 padrões do ROADMAP, veio: {names}"
    )

    # Os dois priorizados são completos: papéis com tools declaradas.
    pr = load_pattern("producer-reviewer")
    role_names = {r.name for r in pr.roles}
    assert {"producer", "reviewer"} <= role_names
    for role in pr.roles:
        assert role.tools, f"producer-reviewer: papel '{role.name}' sem tools declaradas"

    sup = load_pattern("supervisor")
    sup_role_names = {r.name for r in sup.roles}
    assert {"supervisor", "producer", "reviewer"} <= sup_role_names
    for role in sup.roles:
        assert role.tools, f"supervisor: papel '{role.name}' sem tools declaradas"

    # Invariante central: reviewer e supervisor NUNCA têm Edit/Write.
    for pattern in (pr, sup):
        for role in pattern.roles:
            if role.name in ("reviewer", "supervisor"):
                overlap = FORBIDDEN_REVIEW_TOOLS & set(role.tools)
                assert not overlap, (
                    f"{pattern.name}/{role.name}: papel de revisão/orquestração "
                    f"com ferramenta de escrita {overlap}"
                )

    # Os 4 declarativos carregam com papéis, mas sem tools detalhado.
    for name in DECLARATIVE_PATTERNS:
        pattern = load_pattern(name)
        assert pattern.roles, f"{name}: padrão declarativo sem papéis"
        assert all(not r.tools for r in pattern.roles), (
            f"{name}: padrão declarativo não deveria fixar tools por papel"
        )


def test_load_pattern_unknown_raises_team_error():
    with pytest.raises(TeamError):
        load_pattern("padrao-que-nao-existe")


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


def test_generate_team_supervisor_pattern_keeps_supervisor_readonly(tmp_path):
    project = tmp_path / "target-sup"
    project.mkdir()
    generate_team(project, "supervisor")

    supervisor_md = project / ".claude" / "agents" / "supervisor.md"
    reviewer_md = project / ".claude" / "agents" / "reviewer.md"
    assert supervisor_md.is_file() and reviewer_md.is_file()
    assert not (FORBIDDEN_REVIEW_TOOLS & _frontmatter_tools(supervisor_md))
    assert not (FORBIDDEN_REVIEW_TOOLS & _frontmatter_tools(reviewer_md))

    manifest = json.loads(
        (project / ".harness" / "team" / "manifest.json").read_text(encoding="utf-8")
    )
    assert {"supervisor", "producer", "reviewer"} <= set(manifest["roles"])


# ---------------------------------------------------------------------------
# Outcome 3 — state machine: escala, nunca força aprovação; teto duro
# ---------------------------------------------------------------------------

def test_review_never_approves_by_exhaustion_and_hard_cap_blocks_resubmit(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    feature = {"id": "T-09", "files": []}

    # 3 ciclos submit -> reject com max_iterations=3.
    for expected_iteration in (1, 2, 3):
        record = submit_for_review(project, "T-09", max_iterations=3)
        assert record["status"] == "in_review"
        assert record["iteration"] == expected_iteration
        result = record_decision(
            project, "T-09", feature, "rejected", f"problema na rodada {expected_iteration}"
        )
        assert result.status == "rejected", (
            "estourar o limite NUNCA pode virar 'approved' — divergência "
            "deliberada da fonte exigida pelo ROADMAP"
        )
        if expected_iteration < 3:
            assert result.escalate is False
        else:
            assert result.escalate is True, (
                "na iteração == max_iterations a rejeição deve escalar ao humano"
            )

    # Estado em disco continua 'rejected' (nunca um 5º estado, nunca approved).
    on_disk = json.loads(
        (project / ".harness" / "review" / "T-09.json").read_text(encoding="utf-8")
    )
    assert on_disk["status"] == "rejected"
    assert all(entry["decision"] == "rejected" for entry in on_disk["history"])

    # Teto DURO: resubmeter além do limite falha — escalação não é só aviso.
    with pytest.raises(ReviewError):
        submit_for_review(project, "T-09")

    # Nem dá para registrar aprovação por fora (estado não é in_review).
    with pytest.raises(ReviewError):
        record_decision(project, "T-09", feature, "approved", "tentando forçar")

    final = json.loads(
        (project / ".harness" / "review" / "T-09.json").read_text(encoding="utf-8")
    )
    assert final["status"] == "rejected"


def test_review_approving_test_diff_requires_justification(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    _write_json(project / ".harness" / "repo-profile.json", {
        "test_glob": {"value": "tests/**/*.py"},
    })
    feature = {"id": "T-10", "files": ["tests/test_app.py"]}

    submit_for_review(project, "T-10")
    with pytest.raises(ReviewError):
        record_decision(project, "T-10", feature, "approved", "lgtm")

    # Continua in_review (a tentativa inválida não pode ter transicionado).
    on_disk = json.loads(
        (project / ".harness" / "review" / "T-10.json").read_text(encoding="utf-8")
    )
    assert on_disk["status"] == "in_review"

    result = record_decision(
        project, "T-10", feature, "approved", "lgtm",
        justification="expectativa mudou porque o contrato da API mudou",
    )
    assert result.status == "approved"


# ---------------------------------------------------------------------------
# Outcome 4 — feature-lock estendido (veto do revisor), versão importável
# ---------------------------------------------------------------------------

def test_feature_lock_requires_approved_review_when_team_declared(tmp_path):
    project = _make_contract_project(tmp_path)
    _write_evidence(project, "T-01", _iso(0))
    _write_team_manifest(project)
    payload = _transition_payload(project)

    # Sem review file algum -> deny (status default 'pending').
    decision, reason = evaluate_feature_list_edit("Write", payload, project)
    assert decision == "deny"
    assert "T-01" in reason

    # Review em in_review -> deny.
    _write_review(project, "T-01", "in_review", _iso(10))
    decision, reason = evaluate_feature_list_edit("Write", payload, project)
    assert decision == "deny"

    # Review rejeitada -> deny.
    _write_review(project, "T-01", "rejected", _iso(10))
    decision, reason = evaluate_feature_list_edit("Write", payload, project)
    assert decision == "deny"

    # Review aprovada e mais nova que a evidência -> allow citando a revisão.
    _write_review(project, "T-01", "approved", _iso(60))
    decision, reason = evaluate_feature_list_edit("Write", payload, project)
    assert decision == "allow", f"esperava allow com revisão aprovada fresca, veio: {reason}"
    assert "revis" in reason.lower()


def test_feature_lock_without_manifest_behaves_like_fase3(tmp_path):
    """Zero regressão: sem time compilado, evidência fresca basta."""
    project = _make_contract_project(tmp_path)
    _write_evidence(project, "T-01", _iso(0))
    payload = _transition_payload(project)

    decision, reason = evaluate_feature_list_edit("Write", payload, project)
    assert decision == "allow"
    assert "revis" not in reason.lower(), (
        "sem manifesto, a mensagem não deveria citar revisão de time"
    )

    # Manifesto SEM os dois papéis também não ativa o gate.
    _write_team_manifest(project, roles=["stage_1", "stage_2"])
    decision, _ = evaluate_feature_list_edit("Write", payload, project)
    assert decision == "allow"


def test_feature_lock_denies_stale_approval_older_than_evidence(tmp_path):
    """O achado específico do reflect+judge: aprovação que ficou obsoleta
    porque a evidência foi regravada DEPOIS dela (produtor editou de novo e
    re-rodou verify) tem que ser negada até nova aprovação."""
    project = _make_contract_project(tmp_path)
    _write_team_manifest(project)
    payload = _transition_payload(project)

    # Aprovação ANTIGA (t-60s), evidência NOVA (agora): o revisor aprovou um
    # diff que não é o que a evidência mais recente cobriu.
    _write_review(project, "T-01", "approved", _iso(-60))
    _write_evidence(project, "T-01", _iso(0))

    decision, reason = evaluate_feature_list_edit("Write", payload, project)
    assert decision == "deny", (
        "aprovação mais antiga que a evidência mais recente TEM que ser negada "
        f"(aprovação obsoleta) — veio: {decision} / {reason}"
    )
    assert "T-01" in reason

    # Sanidade do mesmo cenário invertido: reaprovação posterior libera.
    _write_review(project, "T-01", "approved", _iso(60))
    decision, _ = evaluate_feature_list_edit("Write", payload, project)
    assert decision == "allow"


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


def test_feature_lock_test_diff_approval_requires_justification_on_disk(tmp_path):
    """Defesa em profundidade: mesmo um registro 'approved' gravado por fora
    da API de review.py precisa de justification para diff de teste."""
    project = _make_contract_project(tmp_path)
    data = json.loads((project / ".harness" / "feature_list.json").read_text(encoding="utf-8"))
    data["features"][0]["files"] = ["tests/test_app.py"]
    _write_json(project / ".harness" / "feature_list.json", data)
    _write_json(project / ".harness" / "repo-profile.json", {
        "test_glob": {"value": "tests/**/*.py"},
    })
    _write_team_manifest(project)
    _write_evidence(project, "T-01", _iso(0))
    payload = _transition_payload(project)

    _write_review(project, "T-01", "approved", _iso(60), justification=None)
    decision, reason = evaluate_feature_list_edit("Write", payload, project)
    assert decision == "deny"
    assert "justificativa" in reason.lower()

    _write_review(project, "T-01", "approved", _iso(60),
                  justification="expectativa mudou pelo novo contrato")
    decision, _ = evaluate_feature_list_edit("Write", payload, project)
    assert decision == "allow"


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
        (project / ".harness" / "evidence" / "T-01.json").read_text(encoding="utf-8")
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
    assert (project / ".harness" / "evidence" / "T-01.json").is_file()
    assert not (project / ".harness" / "review").exists(), (
        "sem manifesto de time, verify não deveria criar registro de revisão"
    )


# ---------------------------------------------------------------------------
# Outcome 6 — team_audit detecta os 3 invariantes
# ---------------------------------------------------------------------------

def _generated_team(tmp_path: Path) -> Path:
    project = tmp_path / "audit-target"
    project.mkdir()
    generate_team(project, "producer-reviewer")
    return project


def test_team_audit_healthy_team_scores_100(tmp_path):
    project = _generated_team(tmp_path)
    report = audit_team(project)
    assert report.score == 100, report.to_json()
    assert report.findings == [], report.to_json()


def test_team_audit_detects_orphan_agent(tmp_path):
    project = _generated_team(tmp_path)
    rogue = project / ".claude" / "agents" / "rogue.md"
    rogue.write_text(
        "---\nname: rogue\ndescription: agente intruso\ntools: Read\n---\n\ncorpo\n",
        encoding="utf-8",
    )
    report = audit_team(project)
    codes = {(f.severity, f.code) for f in report.findings}
    assert ("warning", "orphan_team_agent") in codes, report.to_json()
    assert report.score < 100


def test_team_audit_detects_reviewer_extra_tool(tmp_path):
    """O invariante mais importante: reviewer ganhando Edit por edição manual."""
    project = _generated_team(tmp_path)
    reviewer_md = project / ".claude" / "agents" / "reviewer.md"
    text = reviewer_md.read_text(encoding="utf-8")
    tampered = text.replace("tools: Read, Grep, Glob, Bash",
                            "tools: Read, Grep, Glob, Bash, Edit", 1)
    assert tampered != text, "sabotagem do teste não aplicou — layout do frontmatter mudou?"
    reviewer_md.write_text(tampered, encoding="utf-8")

    report = audit_team(project)
    critical = [f for f in report.findings if f.severity == "critical"]
    assert any(
        f.code == "team_agent_extra_tools" and "Edit" in f.message for f in critical
    ), report.to_json()


def test_team_audit_detects_managed_block_drift(tmp_path):
    project = _generated_team(tmp_path)
    reviewer_md = project / ".claude" / "agents" / "reviewer.md"
    text = reviewer_md.read_text(encoding="utf-8")
    tampered = text.replace(
        "Ferramentas mínimas deste papel",
        "Pode usar qualquer ferramenta que quiser", 1
    )
    assert tampered != text
    reviewer_md.write_text(tampered, encoding="utf-8")

    report = audit_team(project)
    codes = {(f.severity, f.code) for f in report.findings}
    assert ("warning", "team_agent_drift") in codes, report.to_json()


# ---------------------------------------------------------------------------
# Outcome 7 — precedência corrigida de recommend_pattern
# ---------------------------------------------------------------------------

def test_recommend_pattern_supervisor_signal_beats_has_tests():
    # O cenário exato que a ordem errada quebrava: repo real (has_tests=True)
    # + pedido explícito de supervisor.
    pattern, justification = recommend_pattern(
        {"has_tests": True},
        "Quero um SUPERVISOR central coordenando o trabalho",
    )
    assert pattern == "supervisor", (
        f"sinal explícito da descrição tem que vencer has_tests=True — veio "
        f"'{pattern}' ({justification})"
    )

    # Sinal de distribuição/paralelismo também vence.
    pattern, _ = recommend_pattern(
        {"has_tests": True}, "distribuir múltiplas features em paralelo"
    )
    assert pattern == "supervisor"


def test_recommend_pattern_other_branches():
    # Sinal de revisão sem sinal de supervisor.
    pattern, justification = recommend_pattern(
        {"has_tests": False}, "preciso de review rigoroso de qualidade"
    )
    assert pattern == "producer-reviewer"

    # has_tests sozinho.
    pattern, _ = recommend_pattern({"has_tests": True}, "melhorar o app")
    assert pattern == "producer-reviewer"

    # Default sem nenhum sinal.
    pattern, justification = recommend_pattern({"has_tests": False}, "melhorar o app")
    assert pattern == "producer-reviewer"
    assert justification


# ---------------------------------------------------------------------------
# Outcome 8 — dispatch_next respeita depends[] (primeiro consumidor real)
# ---------------------------------------------------------------------------

def test_dispatch_next_respects_depends(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    features = {
        "features": [
            {"id": "B", "passes": False, "depends": ["A"]},
            {"id": "A", "passes": False},
            {"id": "C", "passes": False, "depends": ["fantasma"]},
        ]
    }
    _write_json(project / ".harness" / "feature_list.json", features)

    # B vem primeiro no arquivo mas depende de A não-passada -> A é a próxima.
    nxt = dispatch_next(project)
    assert nxt is not None and nxt["id"] == "A"

    # A passa -> B fica pronta; C (dep inexistente) NUNCA fica pronta.
    features["features"][1]["passes"] = True
    _write_json(project / ".harness" / "feature_list.json", features)
    nxt = dispatch_next(project)
    assert nxt is not None and nxt["id"] == "B"

    features["features"][0]["passes"] = True
    _write_json(project / ".harness" / "feature_list.json", features)
    assert dispatch_next(project) is None, (
        "dependência para id inexistente não pode deixar a feature pronta"
    )

    # Sem contrato -> None, sem exceção.
    assert dispatch_next(tmp_path / "vazio") is None


def test_on_feature_verified_is_noop_without_full_team(tmp_path):
    project = _make_contract_project(tmp_path)
    assert on_feature_verified(project, "T-01") is None

    _write_team_manifest(project, roles=["producer"])
    assert on_feature_verified(project, "T-01") is None
    assert not (project / ".harness" / "review").exists()

    _write_team_manifest(project)  # producer+reviewer
    result = on_feature_verified(project, "T-01")
    assert result is not None and result["status"] == "in_review"
