"""Auditoria de TIME: papel órfão, drift do bloco gerenciado dos agentes e
ferramentas além do papel declarado no catálogo (Fase 4 do ROADMAP).

Mecanismo DISTINTO de `harness.audit` (diff byte-exato dos artefatos
COMPILADOS a partir de `harness.yaml`) e de `harness.runtime_audit`
(invariantes de feature/evidence da Fase 3, artefatos que mudam durante a
execução autônoma). Este módulo audita especificamente os artefatos de TIME
gerados pela Fase 4 (`.claude/agents/<papel>.md`, `.harness/team/manifest.json`)
contra o catálogo de padrões (`harness.teams.load_pattern`) e contra o que
`harness.teams.render_agent_md` geraria hoje para cada papel.

Invariantes verificados por `audit_team`:
  (1) `.harness/team/manifest.json` existe e é JSON válido — ausência é
      `info` (projeto sem Fase 4 ativa é estado válido, score 100 sem
      penalidade); JSON inválido é `critical`.
  (2) o padrão citado em `manifest['pattern']` ainda existe no catálogo
      (`harness.teams.load_pattern`) — senão, `critical`, audit para aqui.
  (3) todo arquivo `.claude/agents/*.md` corresponde a um papel do padrão
      atual — papel órfão é `warning`.
  (4) todo papel do padrão com `tools` não-vazia tem um agente gerado
      (`critical` se faltar) cujo frontmatter `tools:` não excede o mínimo
      declarado no catálogo (`critical` se exceder — o invariante mais
      importante: um `reviewer`/`supervisor` nunca deveria ganhar
      `Edit`/`Write` por edição manual do arquivo gerado).
  (5) o bloco gerenciado (`<!-- harness:team:agent:begin/end -->`) de cada
      agente presente ainda bate com o que `render_agent_md` geraria hoje a
      partir do catálogo — divergência é `warning`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from harness.teams import (
    TEAM_AGENT_BEGIN,
    TEAM_AGENT_END,
    TeamError,
    TeamPattern,
    load_pattern,
    render_agent_md,
)

MANIFEST_PATH = ".harness/team/manifest.json"
AGENTS_DIR = ".claude/agents"

_FRONTMATTER_DELIM = "---"


@dataclass
class TeamFinding:
    severity: str          # "critical" | "warning" | "info"
    code: str              # slug estável p/ máquina
    message: str           # frase p/ humano
    fix: str               # como corrigir

    def to_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "code": self.code,
                "message": self.message, "fix": self.fix}


@dataclass
class TeamAuditReport:
    score: int
    findings: list[TeamFinding] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"score": self.score, "findings": [f.to_dict() for f in self.findings]}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


_PENALTY = {"critical": 40, "warning": 15, "info": 5}


def _finish(findings: list[TeamFinding]) -> TeamAuditReport:
    score = 100
    for f in findings:
        score -= _PENALTY.get(f.severity, 0)
    return TeamAuditReport(score=max(0, score), findings=findings)


def _read_frontmatter(path: Path) -> dict[str, Any] | None:
    """Extrai o frontmatter YAML de `path` como dict (mesma técnica de
    `contract.py::parse_spec`: delimitadores `---`/`---` nas primeiras
    linhas). Devolve `None` (em vez de levantar) se o arquivo não tiver
    frontmatter delimitado corretamente ou o YAML for inválido/não-dict —
    quem chama decide o que fazer com um arquivo malformado."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FRONTMATTER_DELIM:
        return None
    try:
        closing_offset = lines[1:].index(_FRONTMATTER_DELIM)
    except ValueError:
        return None

    frontmatter_text = "\n".join(lines[1:closing_offset + 1])
    try:
        data = yaml.safe_load(frontmatter_text)
    except yaml.YAMLError:
        return None

    if not isinstance(data, dict):
        return None
    return data


def _extract_block(text: str, begin: str, end: str) -> str | None:
    """Extrai a substring `begin...end` (inclusive) de `text`, ou `None` se
    algum dos dois delimitadores estiver ausente."""
    match = re.search(re.escape(begin) + ".*?" + re.escape(end), text, re.DOTALL)
    return match.group(0) if match else None


def _parse_tools(raw: Any) -> list[str]:
    """`tools:` do frontmatter como lista — o valor é sempre uma string
    separada por vírgula (mesmo formato produzido por
    `teams.py::_format_tools`), nunca uma lista YAML nativa. `None`/vazio
    vira lista vazia (papel sem `tools` fixadas)."""
    if not raw:
        return []
    return [t.strip() for t in str(raw).split(",") if t.strip()]


def audit_team(target_dir: Path, patterns_dir: Path | None = None) -> TeamAuditReport:
    target_dir = target_dir.resolve()
    findings: list[TeamFinding] = []

    # --- 1. manifest.json existe e é JSON válido ---
    manifest_path = target_dir / MANIFEST_PATH
    if not manifest_path.is_file():
        return TeamAuditReport(
            score=100,
            findings=[TeamFinding(
                "info", "no_team_manifest",
                "nenhum time compilado ainda — rode harness team generate",
                "Rode `harness team generate` para compilar um time (Fase 4).",
            )],
        )

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        findings.append(TeamFinding(
            "critical", "invalid_team_manifest_json",
            f"{MANIFEST_PATH} não é JSON válido: {exc}",
            "Rode `harness team generate` novamente para regravar o manifesto.",
        ))
        return _finish(findings)

    if not isinstance(manifest, dict):
        findings.append(TeamFinding(
            "critical", "invalid_team_manifest_schema",
            f"{MANIFEST_PATH} não é um objeto JSON válido.",
            "Rode `harness team generate` novamente para regravar o manifesto.",
        ))
        return _finish(findings)

    # --- 2. o padrão citado no manifesto ainda existe no catálogo ---
    pattern_name = manifest.get("pattern")
    try:
        pattern: TeamPattern = load_pattern(pattern_name, patterns_dir)
    except TeamError as exc:
        findings.append(TeamFinding(
            "critical", "unknown_team_pattern",
            f"padrão do manifesto ('{pattern_name}') não existe mais no catálogo: {exc}",
            "Escolha um padrão válido (`harness team design`) e rode "
            "`harness team generate` novamente.",
        ))
        return _finish(findings)

    role_by_name = {role.name: role for role in pattern.roles}
    agents_dir = target_dir / AGENTS_DIR

    # --- 3. papel órfão: agente sem papel correspondente no padrão atual ---
    if agents_dir.is_dir():
        for agent_path in sorted(agents_dir.glob("*.md")):
            frontmatter = _read_frontmatter(agent_path)
            if frontmatter is None:
                continue
            agent_name = frontmatter.get("name")
            if agent_name not in role_by_name:
                findings.append(TeamFinding(
                    "warning", "orphan_team_agent",
                    f"papel órfão: {agent_path} não corresponde a nenhum papel "
                    f"do padrão atual ('{pattern.name}').",
                    "Remova o arquivo ou rode `harness team generate` para "
                    "ressincronizar os agentes com o padrão atual.",
                ))

    # --- 4/5. por papel: agente ausente / ferramentas além do papel / drift ---
    for role in pattern.roles:
        agent_path = agents_dir / f"{role.name}.md"

        if not agent_path.is_file():
            if role.tools:
                findings.append(TeamFinding(
                    "critical", "missing_team_agent",
                    f"papel '{role.name}' do padrão '{pattern.name}' sem "
                    "agente gerado.",
                    "Rode `harness team generate` novamente.",
                ))
            continue

        frontmatter = _read_frontmatter(agent_path)
        if frontmatter is not None and role.tools:
            agent_tools = _parse_tools(frontmatter.get("tools"))
            extra_tools = sorted(set(agent_tools) - set(role.tools))
            if extra_tools:
                findings.append(TeamFinding(
                    "critical", "team_agent_extra_tools",
                    f"papel '{role.name}' tem ferramenta(s) além do mínimo "
                    f"declarado no catálogo: {', '.join(extra_tools)}.",
                    f"Remova {', '.join(extra_tools)} do frontmatter `tools:` "
                    f"de {agent_path}, ou rode `harness team generate` "
                    "novamente para regravar o arquivo a partir do catálogo.",
                ))

        existing_text = agent_path.read_text(encoding="utf-8")
        existing_block = _extract_block(existing_text, TEAM_AGENT_BEGIN, TEAM_AGENT_END)
        rendered_block = _extract_block(
            render_agent_md(role, pattern), TEAM_AGENT_BEGIN, TEAM_AGENT_END
        )
        if existing_block is not None and existing_block != rendered_block:
            findings.append(TeamFinding(
                "warning", "team_agent_drift",
                f"bloco gerenciado de {agent_path} diverge do catálogo atual "
                "— rode harness team generate para ressincronizar.",
                "Rode `harness team generate` para regravar o bloco gerenciado.",
            ))

    return _finish(findings)
