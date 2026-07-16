"""Testes do catálogo de padrões de time e do motor de análise/seleção
(Fase 4 do ROADMAP: Team-Architecture Factory)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.teams import (
    DEFAULT_PATTERNS_DIR,
    TEAM_AGENT_BEGIN,
    TEAM_AGENT_END,
    TEAM_BEGIN,
    TEAM_END,
    TEAM_SKILL_BEGIN,
    TEAM_SKILL_END,
    TeamError,
    TeamGenerationResult,
    TeamPattern,
    TeamRole,
    analyze_domain,
    generate_team,
    install_team_agents,
    install_team_docs,
    install_team_manifest,
    install_team_skills,
    list_patterns,
    load_pattern,
    recommend_pattern,
    render_agent_md,
    render_skill_md,
    render_team_block,
    render_team_detail,
)

_EXPECTED_PATTERNS = {
    "producer-reviewer",
    "supervisor",
    "pipeline",
    "expert-pool",
    "fan-out-fan-in",
    "hierarchical-delegation",
}


# ---------------------------------------------------------------------------
# list_patterns / load_pattern (catálogo real do repo)
# ---------------------------------------------------------------------------

def test_list_patterns_lists_the_six_real_catalog_names() -> None:
    assert set(list_patterns(DEFAULT_PATTERNS_DIR)) == _EXPECTED_PATTERNS


def test_load_pattern_producer_reviewer_has_expected_roles_without_edit_write() -> None:
    pattern = load_pattern("producer-reviewer", DEFAULT_PATTERNS_DIR)

    assert isinstance(pattern, TeamPattern)
    assert pattern.name == "producer-reviewer"
    role_names = {role.name for role in pattern.roles}
    assert role_names == {"producer", "reviewer"}

    reviewer = next(role for role in pattern.roles if role.name == "reviewer")
    assert isinstance(reviewer, TeamRole)
    assert "Edit" not in reviewer.tools
    assert "Write" not in reviewer.tools

    producer = next(role for role in pattern.roles if role.name == "producer")
    assert "Edit" in producer.tools
    assert "Write" in producer.tools


def test_load_pattern_supervisor_has_expected_roles_without_edit_write() -> None:
    pattern = load_pattern("supervisor", DEFAULT_PATTERNS_DIR)

    role_names = {role.name for role in pattern.roles}
    assert role_names == {"supervisor", "producer", "reviewer"}

    supervisor_role = next(role for role in pattern.roles if role.name == "supervisor")
    assert "Edit" not in supervisor_role.tools
    assert "Write" not in supervisor_role.tools

    reviewer = next(role for role in pattern.roles if role.name == "reviewer")
    assert "Edit" not in reviewer.tools
    assert "Write" not in reviewer.tools


def test_load_pattern_missing_raises_team_error() -> None:
    with pytest.raises(TeamError):
        load_pattern("inexistente", DEFAULT_PATTERNS_DIR)


def test_load_pattern_declarative_templates_load_without_tools_detail(tmp_path: Path) -> None:
    for name in ("pipeline", "expert-pool", "fan-out-fan-in", "hierarchical-delegation"):
        pattern = load_pattern(name, DEFAULT_PATTERNS_DIR)
        assert pattern.name == name
        assert pattern.description
        assert pattern.when_to_use
        assert len(pattern.roles) >= 1


# ---------------------------------------------------------------------------
# load_pattern — schema quebrado (sintéticos)
# ---------------------------------------------------------------------------

def test_load_pattern_schema_missing_roles_raises_team_error(tmp_path: Path) -> None:
    (tmp_path / "broken.yaml").write_text(
        "name: broken\ndescription: sem roles\n", encoding="utf-8"
    )
    with pytest.raises(TeamError):
        load_pattern("broken", tmp_path)


# ---------------------------------------------------------------------------
# analyze_domain
# ---------------------------------------------------------------------------

def test_analyze_domain_without_repo_profile(tmp_path: Path) -> None:
    domain = analyze_domain(tmp_path)
    assert domain == {"profile": None, "languages": [], "has_tests": False}


def test_analyze_domain_with_repo_profile_present(tmp_path: Path) -> None:
    profile = {
        "languages": [{"value": "python", "evidence": "pyproject.toml", "confidence": 1.0}],
        "package_manager": None,
        "test_command": None,
        "test_glob": {"value": "tests/**/*.py", "evidence": "tests/test_x.py", "confidence": 1.0},
        "extras": {},
        "unknowns": [],
        "analyzed_at": "2026-07-16T00:00:00+00:00",
        "manifest_snapshot": {},
    }
    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    (harness_dir / "repo-profile.json").write_text(json.dumps(profile), encoding="utf-8")

    domain = analyze_domain(tmp_path)
    assert domain["profile"] == profile
    assert domain["languages"] == ["python"]
    assert domain["has_tests"] is True


def test_analyze_domain_with_repo_profile_without_test_glob(tmp_path: Path) -> None:
    profile = {
        "languages": [],
        "package_manager": None,
        "test_command": None,
        "test_glob": None,
        "extras": {},
        "unknowns": [],
        "analyzed_at": "2026-07-16T00:00:00+00:00",
        "manifest_snapshot": {},
    }
    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    (harness_dir / "repo-profile.json").write_text(json.dumps(profile), encoding="utf-8")

    domain = analyze_domain(tmp_path)
    assert domain["has_tests"] is False


# ---------------------------------------------------------------------------
# recommend_pattern — os três ramos + o caso crítico de precedência
# ---------------------------------------------------------------------------

def test_recommend_pattern_supervisor_signal_wins_even_with_has_tests_true() -> None:
    """Caso crítico (achado de reflect+judge): has_tests=True E descrição
    contendo 'supervisor' DEVE recomendar 'supervisor', não
    'producer-reviewer' — é exatamente o cenário que a ordem errada quebrava."""
    domain = {"profile": {}, "languages": ["python"], "has_tests": True}
    pattern_name, justification = recommend_pattern(
        domain, "Quero um supervisor para distribuir as tarefas"
    )
    assert pattern_name == "supervisor"
    assert justification


def test_recommend_pattern_supervisor_signal_without_tests() -> None:
    domain = {"profile": None, "languages": [], "has_tests": False}
    pattern_name, _ = recommend_pattern(domain, "preciso distribuir o trabalho em paralelo")
    assert pattern_name == "supervisor"


def test_recommend_pattern_review_signal_without_supervisor_signal() -> None:
    domain = {"profile": None, "languages": [], "has_tests": False}
    pattern_name, justification = recommend_pattern(
        domain, "quero revisão de qualidade automatizada"
    )
    assert pattern_name == "producer-reviewer"
    assert justification


def test_recommend_pattern_has_tests_true_without_any_description_signal() -> None:
    domain = {"profile": {}, "languages": ["python"], "has_tests": True}
    pattern_name, justification = recommend_pattern(domain, "implementar uma nova feature")
    assert pattern_name == "producer-reviewer"
    assert "has_tests" in justification


def test_recommend_pattern_default_with_no_signal_at_all() -> None:
    domain = {"profile": None, "languages": [], "has_tests": False}
    pattern_name, justification = recommend_pattern(domain, "algo qualquer sem sinal nenhum")
    assert pattern_name == "producer-reviewer"
    assert justification


# ---------------------------------------------------------------------------
# render_agent_md / install_team_agents (SUBAGENTE 03)
# ---------------------------------------------------------------------------

def _producer_reviewer_pattern() -> TeamPattern:
    return load_pattern("producer-reviewer", DEFAULT_PATTERNS_DIR)


def test_render_agent_md_with_tools_has_expected_frontmatter_and_block() -> None:
    pattern = _producer_reviewer_pattern()
    producer = next(role for role in pattern.roles if role.name == "producer")

    rendered = render_agent_md(producer, pattern)

    assert rendered.startswith("---\n")
    assert f"name: {producer.name}\n" in rendered
    assert f"description: {producer.responsibilities}\n" in rendered
    assert "tools: " in rendered
    assert ", ".join(producer.tools) in rendered
    assert TEAM_AGENT_BEGIN in rendered
    assert TEAM_AGENT_END in rendered
    assert rendered.index(TEAM_AGENT_BEGIN) < rendered.index(TEAM_AGENT_END)
    assert f"Papel: {producer.name} (time {pattern.name}, gerado pelo harness-creator)" in rendered
    assert producer.responsibilities in rendered
    assert "harness audit-team" in rendered


def test_render_agent_md_without_tools_uses_empty_tools_frontmatter() -> None:
    role = TeamRole(name="orquestrador", responsibilities="Coordena o fluxo.", tools=[])
    pattern = TeamPattern(
        name="pipeline", description="d", when_to_use="w", roles=[role]
    )

    rendered = render_agent_md(role, pattern)

    assert "tools: \n" in rendered
    assert "Ferramentas mínimas deste papel: ." in rendered


def test_install_team_agents_writes_one_file_per_role(tmp_path: Path) -> None:
    pattern = _producer_reviewer_pattern()

    written = install_team_agents(tmp_path, pattern)

    names = {path.name for path in written}
    assert names == {"producer.md", "reviewer.md"}
    for path in written:
        assert path.parent == tmp_path / ".claude" / "agents"
        assert path.is_file()

    reviewer_path = tmp_path / ".claude" / "agents" / "reviewer.md"
    reviewer_role = next(role for role in pattern.roles if role.name == "reviewer")
    text = reviewer_path.read_text(encoding="utf-8")
    assert "name: reviewer" in text
    assert reviewer_role.responsibilities in text


def test_install_team_agents_is_idempotent_replaces_block_without_duplicating(
    tmp_path: Path,
) -> None:
    pattern = _producer_reviewer_pattern()

    install_team_agents(tmp_path, pattern)
    producer_path = tmp_path / ".claude" / "agents" / "producer.md"
    original_text = producer_path.read_text(encoding="utf-8")

    # Simula conteúdo do usuário fora do bloco gerenciado.
    with_user_content = original_text + "\n\n## Notas do usuário\nNão apagar.\n"
    producer_path.write_text(with_user_content, encoding="utf-8")

    install_team_agents(tmp_path, pattern)
    second_text = producer_path.read_text(encoding="utf-8")

    assert second_text.count(TEAM_AGENT_BEGIN) == 1
    assert second_text.count(TEAM_AGENT_END) == 1
    assert "## Notas do usuário" in second_text
    assert "Não apagar." in second_text


# ---------------------------------------------------------------------------
# render_skill_md / install_team_skills (SUBAGENTE 03)
# ---------------------------------------------------------------------------

def test_render_skill_md_has_expected_frontmatter_and_block() -> None:
    pattern = _producer_reviewer_pattern()
    reviewer = next(role for role in pattern.roles if role.name == "reviewer")

    rendered = render_skill_md(reviewer, pattern)

    assert rendered.startswith("---\n")
    assert f"name: {reviewer.name}\n" in rendered
    assert f"description: {reviewer.responsibilities}\n" in rendered
    assert (
        f"when_to_use: Papel {reviewer.name} do time {pattern.name}" in rendered
    )
    assert ".claude/agents/reviewer.md" in rendered
    assert "disable-model-invocation: false" in rendered
    assert TEAM_SKILL_BEGIN in rendered
    assert TEAM_SKILL_END in rendered
    assert rendered.index(TEAM_SKILL_BEGIN) < rendered.index(TEAM_SKILL_END)
    assert reviewer.responsibilities in rendered


def test_install_team_skills_writes_one_file_per_role(tmp_path: Path) -> None:
    pattern = _producer_reviewer_pattern()

    written = install_team_skills(tmp_path, pattern)

    relative = {path.relative_to(tmp_path) for path in written}
    assert relative == {
        Path(".claude/skills/producer/SKILL.md"),
        Path(".claude/skills/reviewer/SKILL.md"),
    }
    for path in written:
        assert path.is_file()

    reviewer_path = tmp_path / ".claude" / "skills" / "reviewer" / "SKILL.md"
    reviewer_role = next(role for role in pattern.roles if role.name == "reviewer")
    text = reviewer_path.read_text(encoding="utf-8")
    assert "name: reviewer" in text
    assert reviewer_role.responsibilities in text


def test_install_team_skills_is_idempotent_replaces_block_without_duplicating(
    tmp_path: Path,
) -> None:
    pattern = _producer_reviewer_pattern()

    install_team_skills(tmp_path, pattern)
    producer_path = tmp_path / ".claude" / "skills" / "producer" / "SKILL.md"
    original_text = producer_path.read_text(encoding="utf-8")

    with_user_content = original_text + "\n\n## Notas do usuário\nNão apagar.\n"
    producer_path.write_text(with_user_content, encoding="utf-8")

    install_team_skills(tmp_path, pattern)
    second_text = producer_path.read_text(encoding="utf-8")

    assert second_text.count(TEAM_SKILL_BEGIN) == 1
    assert second_text.count(TEAM_SKILL_END) == 1
    assert "## Notas do usuário" in second_text
    assert "Não apagar." in second_text


# ---------------------------------------------------------------------------
# render_team_block / render_team_detail / install_team_docs /
# install_team_manifest / generate_team (SUBAGENTE 06)
# ---------------------------------------------------------------------------

def test_render_team_block_cites_pattern_and_roles() -> None:
    pattern = _producer_reviewer_pattern()

    rendered = render_team_block(pattern, "subagents")

    assert TEAM_BEGIN in rendered
    assert TEAM_END in rendered
    assert rendered.index(TEAM_BEGIN) < rendered.index(TEAM_END)
    assert pattern.name in rendered
    assert "subagents" in rendered
    for role in pattern.roles:
        assert f".claude/agents/{role.name}.md" in rendered
    assert ".harness/TEAM.md" in rendered
    assert "harness supervise" not in rendered


def test_render_team_block_supervisor_cites_harness_supervise() -> None:
    pattern = load_pattern("supervisor", DEFAULT_PATTERNS_DIR)

    rendered = render_team_block(pattern, "subagents")

    assert "harness supervise" in rendered


def test_render_team_detail_cites_responsibilities_and_tools_per_role() -> None:
    pattern = _producer_reviewer_pattern()

    rendered = render_team_detail(pattern, "subagents")

    for role in pattern.roles:
        assert role.name in rendered
        assert role.responsibilities in rendered
    assert "feature-lock" in rendered
    assert "producer" in rendered and "reviewer" in rendered
    assert "max_review_iterations" in rendered
    assert "subagents" in rendered


def test_render_team_detail_agent_teams_mode_is_advisory() -> None:
    pattern = _producer_reviewer_pattern()

    rendered = render_team_detail(pattern, "agent-teams")

    assert "agent-teams" in rendered
    assert "ADVISORY" in rendered or "advisory" in rendered.lower()


def test_render_team_detail_supervisor_pattern_cites_harness_supervise() -> None:
    pattern = load_pattern("supervisor", DEFAULT_PATTERNS_DIR)

    rendered = render_team_detail(pattern, "subagents")

    assert "harness supervise" in rendered


def test_install_team_docs_idempotent_preserves_other_managed_blocks(
    tmp_path: Path,
) -> None:
    pattern = _producer_reviewer_pattern()

    agents_path = tmp_path / "AGENTS.md"
    compiler_block = "<!-- harness:begin -->\n## Compiler stuff\n<!-- harness:end -->"
    lifecycle_block = (
        "<!-- harness:lifecycle:begin -->\n## Lifecycle stuff\n"
        "<!-- harness:lifecycle:end -->"
    )
    agents_path.write_text(
        "# AGENTS.md\n\n"
        + compiler_block
        + "\n\n"
        + lifecycle_block
        + "\n\n## Notas do usuário\nNão apagar.\n",
        encoding="utf-8",
    )

    agents_md, team_detail = install_team_docs(tmp_path, pattern, "subagents")
    assert agents_md == agents_path
    assert team_detail == tmp_path / ".harness" / "TEAM.md"
    assert team_detail.is_file()

    first_text = agents_path.read_text(encoding="utf-8")
    assert compiler_block in first_text
    assert lifecycle_block in first_text
    assert "## Notas do usuário" in first_text
    assert first_text.count(TEAM_BEGIN) == 1
    assert first_text.count(TEAM_END) == 1

    # Segunda chamada: idempotente, não duplica o bloco nem apaga os demais.
    install_team_docs(tmp_path, pattern, "subagents")
    second_text = agents_path.read_text(encoding="utf-8")

    assert second_text.count(TEAM_BEGIN) == 1
    assert second_text.count(TEAM_END) == 1
    assert compiler_block in second_text
    assert lifecycle_block in second_text
    assert "## Notas do usuário" in second_text
    assert "Não apagar." in second_text


def test_install_team_manifest_writes_exact_schema(tmp_path: Path) -> None:
    pattern = _producer_reviewer_pattern()

    manifest_path = install_team_manifest(
        tmp_path, pattern, "subagents", max_review_iterations=5
    )

    assert manifest_path == tmp_path / ".harness" / "team" / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert data["pattern"] == "producer-reviewer"
    assert data["mode"] == "subagents"
    assert data["roles"] == [role.name for role in pattern.roles]
    assert data["max_review_iterations"] == 5
    assert "generated_at" in data and data["generated_at"]


def test_install_team_manifest_always_overwrites(tmp_path: Path) -> None:
    pattern = _producer_reviewer_pattern()

    install_team_manifest(tmp_path, pattern, "subagents", max_review_iterations=3)
    manifest_path = install_team_manifest(
        tmp_path, pattern, "agent-teams", max_review_iterations=7
    )

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert data["mode"] == "agent-teams"
    assert data["max_review_iterations"] == 7


def test_generate_team_producer_reviewer_writes_everything(tmp_path: Path) -> None:
    result = generate_team(tmp_path, "producer-reviewer", mode="subagents")

    assert isinstance(result, TeamGenerationResult)
    assert result.pattern == "producer-reviewer"
    assert result.mode == "subagents"
    assert set(result.roles) == {"producer", "reviewer"}

    assert len(result.agents_written) == 2
    assert len(result.skills_written) == 2
    for path in result.agents_written + result.skills_written:
        assert path.is_file()

    assert result.agents_md == tmp_path / "AGENTS.md"
    assert result.agents_md.is_file()
    assert result.team_detail == tmp_path / ".harness" / "TEAM.md"
    assert result.team_detail.is_file()
    assert result.manifest == tmp_path / ".harness" / "team" / "manifest.json"
    manifest_data = json.loads(result.manifest.read_text(encoding="utf-8"))
    assert manifest_data["pattern"] == "producer-reviewer"
    assert manifest_data["roles"] == ["producer", "reviewer"]


def test_generate_team_invalid_pattern_raises_team_error(tmp_path: Path) -> None:
    with pytest.raises(TeamError):
        generate_team(tmp_path, "inexistente")
