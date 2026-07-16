"""Testes do team_audit: mecanismo DISTINTO de audit.py (diff byte-exato de
compilados) e de runtime_audit.py (invariantes de feature/evidence da Fase
3) — audita especificamente os artefatos de TIME da Fase 4: papel órfão,
agente sem papel/ferramenta além do mínimo do catálogo, e drift do bloco
gerenciado."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from harness.team_audit import TEAM_AGENT_BEGIN, TEAM_AGENT_END, audit_team
from harness.teams import install_team_agents, load_pattern


def _codes(report) -> set[str]:
    return {f.code for f in report.findings}


def _write_pattern_yaml(patterns_dir: Path, name: str, roles: list[dict]) -> None:
    patterns_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "name": name,
        "description": f"Padrão de teste {name}.",
        "when_to_use": "Cenário de teste do team_audit.",
        "roles": roles,
    }
    (patterns_dir / f"{name}.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False), encoding="utf-8"
    )


def _write_manifest(target_dir: Path, pattern_name: str, roles: list[str]) -> None:
    payload = {
        "pattern": pattern_name,
        "mode": "subagents",
        "roles": roles,
        "max_review_iterations": 3,
        "generated_at": "2026-07-16T12:00:00+00:00",
    }
    path = target_dir / ".harness" / "team" / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. sem manifest.json -> score 100, finding info
# ---------------------------------------------------------------------------

def test_missing_manifest_is_info_with_score_100(tmp_path: Path) -> None:
    report = audit_team(tmp_path)
    assert report.score == 100
    assert _codes(report) == {"no_team_manifest"}
    assert next(f for f in report.findings if f.code == "no_team_manifest").severity == "info"


# ---------------------------------------------------------------------------
# manifest.json com JSON inválido -> critical
# ---------------------------------------------------------------------------

def test_invalid_manifest_json_is_critical(tmp_path: Path) -> None:
    manifest_path = tmp_path / ".harness" / "team" / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text("{ not valid json", encoding="utf-8")

    report = audit_team(tmp_path)
    assert "invalid_team_manifest_json" in _codes(report)
    assert any(f.severity == "critical" for f in report.findings)


# ---------------------------------------------------------------------------
# 2. manifesto citando padrão inexistente -> critical
# ---------------------------------------------------------------------------

def test_manifest_referencing_unknown_pattern_is_critical(tmp_path: Path) -> None:
    patterns_dir = tmp_path / "patterns"
    patterns_dir.mkdir()  # catálogo vazio — nenhum padrão cadastrado
    _write_manifest(tmp_path, "padrao-fantasma", roles=["worker"])

    report = audit_team(tmp_path, patterns_dir=patterns_dir)
    assert "unknown_team_pattern" in _codes(report)
    assert any(f.severity == "critical" for f in report.findings)


# ---------------------------------------------------------------------------
# 3. papel órfão -> warning
# ---------------------------------------------------------------------------

def test_orphan_agent_file_is_warning(tmp_path: Path) -> None:
    patterns_dir = tmp_path / "patterns"
    _write_pattern_yaml(
        patterns_dir,
        "solo",
        roles=[{"name": "worker", "responsibilities": "Faz o trabalho.", "tools": []}],
    )
    pattern = load_pattern("solo", patterns_dir)
    install_team_agents(tmp_path, pattern)
    _write_manifest(tmp_path, "solo", roles=["worker"])

    # agente órfão: não corresponde a nenhum papel do padrão atual
    ghost_path = tmp_path / ".claude" / "agents" / "ghost.md"
    ghost_path.write_text(
        "---\nname: ghost\ndescription: Fantasma.\ntools: \n---\n\nConteúdo qualquer.\n",
        encoding="utf-8",
    )

    report = audit_team(tmp_path, patterns_dir=patterns_dir)
    assert "orphan_team_agent" in _codes(report)
    finding = next(f for f in report.findings if f.code == "orphan_team_agent")
    assert finding.severity == "warning"
    assert "ghost.md" in finding.message


# ---------------------------------------------------------------------------
# 4. papel do padrão sem agente gerado -> critical
# ---------------------------------------------------------------------------

def test_role_with_tools_missing_agent_file_is_critical(tmp_path: Path) -> None:
    patterns_dir = tmp_path / "patterns"
    _write_pattern_yaml(
        patterns_dir,
        "revisado",
        roles=[
            {"name": "reviewer", "responsibilities": "Revisa.", "tools": ["Read", "Grep"]},
        ],
    )
    _write_manifest(tmp_path, "revisado", roles=["reviewer"])
    # NENHUM agente gerado em .claude/agents/

    report = audit_team(tmp_path, patterns_dir=patterns_dir)
    assert "missing_team_agent" in _codes(report)
    finding = next(f for f in report.findings if f.code == "missing_team_agent")
    assert finding.severity == "critical"
    assert "reviewer" in finding.message


# ---------------------------------------------------------------------------
# 5. agente com ferramenta extra além de role.tools -> critical
# ---------------------------------------------------------------------------

def test_agent_with_tools_beyond_role_minimum_is_critical(tmp_path: Path) -> None:
    patterns_dir = tmp_path / "patterns"
    _write_pattern_yaml(
        patterns_dir,
        "revisado",
        roles=[
            {"name": "reviewer", "responsibilities": "Revisa.", "tools": ["Read", "Grep"]},
        ],
    )
    pattern = load_pattern("revisado", patterns_dir)
    install_team_agents(tmp_path, pattern)
    _write_manifest(tmp_path, "revisado", roles=["reviewer"])

    reviewer_path = tmp_path / ".claude" / "agents" / "reviewer.md"
    text = reviewer_path.read_text(encoding="utf-8")
    # edição manual: revisor ganha Edit, que NÃO está em role.tools
    text = text.replace("tools: Read, Grep", "tools: Read, Grep, Edit")
    reviewer_path.write_text(text, encoding="utf-8")

    report = audit_team(tmp_path, patterns_dir=patterns_dir)
    assert "team_agent_extra_tools" in _codes(report)
    finding = next(f for f in report.findings if f.code == "team_agent_extra_tools")
    assert finding.severity == "critical"
    assert "Edit" in finding.message
    assert "reviewer" in finding.message


# ---------------------------------------------------------------------------
# 6. bloco gerenciado divergente -> warning
# ---------------------------------------------------------------------------

def test_managed_block_drift_is_warning(tmp_path: Path) -> None:
    patterns_dir = tmp_path / "patterns"
    _write_pattern_yaml(
        patterns_dir,
        "solo",
        roles=[{"name": "producer", "responsibilities": "Produz.", "tools": ["Read"]}],
    )
    pattern = load_pattern("solo", patterns_dir)
    install_team_agents(tmp_path, pattern)
    _write_manifest(tmp_path, "solo", roles=["producer"])

    producer_path = tmp_path / ".claude" / "agents" / "producer.md"
    text = producer_path.read_text(encoding="utf-8")
    start = text.index(TEAM_AGENT_BEGIN) + len(TEAM_AGENT_BEGIN)
    end = text.index(TEAM_AGENT_END)
    text = text[:start] + "\nConteúdo editado manualmente, fora de sincronia.\n" + text[end:]
    producer_path.write_text(text, encoding="utf-8")

    report = audit_team(tmp_path, patterns_dir=patterns_dir)
    assert "team_agent_drift" in _codes(report)
    finding = next(f for f in report.findings if f.code == "team_agent_drift")
    assert finding.severity == "warning"


# ---------------------------------------------------------------------------
# 7. caso saudável -> score 100, zero findings
# ---------------------------------------------------------------------------

def test_healthy_team_generated_for_real_has_zero_findings(tmp_path: Path) -> None:
    patterns_dir = tmp_path / "patterns"
    _write_pattern_yaml(
        patterns_dir,
        "producer-reviewer-teste",
        roles=[
            {"name": "producer", "responsibilities": "Implementa.", "tools": ["Read", "Edit", "Write", "Bash"]},
            {"name": "reviewer", "responsibilities": "Revisa.", "tools": ["Read", "Grep", "Bash"]},
        ],
    )
    pattern = load_pattern("producer-reviewer-teste", patterns_dir)
    install_team_agents(tmp_path, pattern)  # gera de verdade, sem edição manual
    _write_manifest(
        tmp_path, "producer-reviewer-teste", roles=[r.name for r in pattern.roles]
    )

    report = audit_team(tmp_path, patterns_dir=patterns_dir)
    assert report.findings == []
    assert report.score == 100
