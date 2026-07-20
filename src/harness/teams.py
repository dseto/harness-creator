"""Team-Architecture Factory (Fase 4 do ROADMAP): catálogo de padrões de
time + motor de análise/seleção.

Este módulo cobre só as duas primeiras fases do workflow de 6 fases descrito
no ROADMAP.md ("Fase 4 — Team-Architecture Factory"): (1) análise de domínio
e (2) design/seleção do padrão. A geração dos artefatos `.claude/agents/`/
`.claude/skills/` (fase 3-4 do workflow) e o state machine de revisão do
padrão Produtor-Revisor ficam em módulos próprios (`review.py` e uma
extensão futura deste arquivo) — não são reimplementados aqui.

O catálogo em si vive em `src/harness/teams/patterns/*.yaml` (empacotado no
wheel do plugin — é conteúdo do PLUGIN, não do projeto-alvo). Os dois
padrões priorizados pelo roadmap — `producer-reviewer` e `supervisor` — têm
schema completo, com `tools` mínimas por papel (o invariante que o audit de
time da Fase 4 vai checar depois: papéis de revisão/orquestração nunca têm
`Edit`/`Write`). Os outros 4 padrões (`pipeline`, `expert-pool`,
`fan-out-fan-in`, `hierarchical-delegation`) são templates declarativos
simplificados, sem `tools` detalhado.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

# Padrões de time empacotados no wheel (src/harness/teams/patterns/)
DEFAULT_PATTERNS_DIR = Path(__file__).resolve().parent / "teams" / "patterns"

REPO_PROFILE_PATH = ".harness/repo-profile.json"

# Sinais (case-insensitive) que a descrição da demanda pode conter — ordem de
# precedência importa, ver `recommend_pattern`.
_SUPERVISOR_SIGNALS = ("supervisor", "distribuir", "paralelo", "multiplas features",
                       "múltiplas features")
_REVIEW_SIGNALS = ("revisão", "revisao", "review", "qualidade")


class TeamError(Exception):
    """Erro de catálogo: arquivo ausente ou schema de padrão inválido."""


@dataclass
class TeamRole:
    """Um papel dentro de um `TeamPattern` (ex.: producer, reviewer)."""

    name: str
    responsibilities: str
    tools: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "responsibilities": self.responsibilities,
            "tools": list(self.tools),
        }


@dataclass
class TeamPattern:
    """Um padrão de time do catálogo (`src/harness/teams/patterns/<name>.yaml`)."""

    name: str
    description: str
    when_to_use: str
    roles: list[TeamRole]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "when_to_use": self.when_to_use,
            "roles": [r.to_dict() for r in self.roles],
        }


# ---------------------------------------------------------------------------
# Catálogo (leitura de src/harness/teams/patterns/*.yaml)
# ---------------------------------------------------------------------------

def list_patterns(patterns_dir: Path | None = None) -> list[str]:
    """Nomes (sem extensão) dos arquivos `.yaml` em `patterns_dir`."""
    directory = patterns_dir if patterns_dir is not None else DEFAULT_PATTERNS_DIR
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.yaml"))


def load_pattern(name: str, patterns_dir: Path | None = None) -> TeamPattern:
    """Carrega `<patterns_dir>/<name>.yaml` como `TeamPattern`.

    Levanta `TeamError` citando o arquivo se ele não existir ou o schema
    estiver quebrado (faltando `name`/`description`/`roles`).
    """
    directory = patterns_dir if patterns_dir is not None else DEFAULT_PATTERNS_DIR
    path = directory / f"{name}.yaml"
    if not path.is_file():
        raise TeamError(f"{path}: padrão de time não encontrado")

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise TeamError(f"{path}: YAML inválido — {exc}") from exc

    if not isinstance(data, dict):
        raise TeamError(f"{path}: schema inválido — esperado um mapeamento (dict)")

    missing = [key for key in ("name", "description", "roles") if not data.get(key)]
    if missing:
        raise TeamError(f"{path}: schema inválido — faltando {', '.join(missing)}")

    roles_raw = data["roles"]
    if not isinstance(roles_raw, list) or not roles_raw:
        raise TeamError(f"{path}: schema inválido — 'roles' precisa ser uma lista não-vazia")

    roles: list[TeamRole] = []
    for role_data in roles_raw:
        if not isinstance(role_data, dict) or not role_data.get("name"):
            raise TeamError(f"{path}: schema inválido — papel sem 'name'")
        roles.append(
            TeamRole(
                name=role_data["name"],
                responsibilities=role_data.get("responsibilities", ""),
                tools=list(role_data.get("tools") or []),
            )
        )

    return TeamPattern(
        name=data["name"],
        description=data["description"],
        when_to_use=data.get("when_to_use", ""),
        roles=roles,
    )


# ---------------------------------------------------------------------------
# Análise de domínio e seleção de padrão
# ---------------------------------------------------------------------------

def analyze_domain(target_dir: Path) -> dict[str, Any]:
    """Lê `.harness/repo-profile.json` (se existir) e devolve um resumo
    simples do domínio do projeto-alvo — sem nenhuma lógica nova de
    varredura de disco, é só leitura do profile já produzido pela Fase 1.

    Ausência do repo-profile.json não é erro: devolve `profile: None`.
    """
    path = target_dir.resolve() / REPO_PROFILE_PATH
    if not path.is_file():
        return {"profile": None, "languages": [], "has_tests": False}

    try:
        profile = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return {"profile": None, "languages": [], "has_tests": False}

    languages = [f.get("value") for f in profile.get("languages", []) if f.get("value")]
    has_tests = profile.get("test_glob") is not None

    return {"profile": profile, "languages": languages, "has_tests": has_tests}


def recommend_pattern(domain: dict[str, Any], description: str) -> tuple[str, str]:
    """Heurística SIMPLES e determinística para recomendar um padrão de
    time — documentada aqui como tal (não é NLP, é matching de sinais
    literais na descrição + o campo `has_tests` do domínio).

    ORDEM DE PRECEDÊNCIA (importa, cheque nesta ordem exata — achado de
    reflect+judge: sinal explícito da descrição tem que vencer `has_tests`,
    senão o padrão supervisor nunca é recomendado automaticamente em repo
    real, que quase sempre tem testes):

    1º) `description` (case-insensitive) contém qualquer um dos sinais de
        supervisor ('supervisor', 'distribuir', 'paralelo',
        'multiplas features', 'múltiplas features') -> recomenda
        'supervisor'. Este sinal vence QUALQUER outro, inclusive
        `has_tests=True`.
    2º) senão, se `description` contém qualquer um dos sinais de revisão
        ('revisão', 'revisao', 'review', 'qualidade') OU
        `domain['has_tests']` é `True` -> recomenda 'producer-reviewer'.
    3º) caso nenhum sinal bata -> default 'producer-reviewer' (padrão mais
        seguro/testado desta fase).
    """
    lowered = description.lower()

    if any(signal in lowered for signal in _SUPERVISOR_SIGNALS):
        return (
            "supervisor",
            "descrição contém sinal explícito de distribuição/supervisão "
            "('supervisor'/'distribuir'/'paralelo'/'multiplas features') — "
            "este sinal vence qualquer outro, inclusive has_tests.",
        )

    matched_review_signal = next(
        (signal for signal in _REVIEW_SIGNALS if signal in lowered), None
    )
    if matched_review_signal is not None:
        return (
            "producer-reviewer",
            f"descrição contém sinal de revisão/qualidade ('{matched_review_signal}').",
        )
    if domain.get("has_tests"):
        return (
            "producer-reviewer",
            "domínio tem has_tests=True — revisão de qualidade automatizada "
            "é aplicável.",
        )

    return (
        "producer-reviewer",
        "nenhum sinal explícito na descrição nem has_tests=True — default "
        "para o padrão mais seguro/testado desta fase.",
    )


# ---------------------------------------------------------------------------
# Geração de artefatos do time: `.claude/agents/<papel>.md` e
# `.claude/skills/<papel>/SKILL.md` no PROJETO-ALVO (SUBAGENTE 03)
# ---------------------------------------------------------------------------

# Delimitadores PRÓPRIOS deste bloco (mesma técnica de
# `lifecycle.py::LIFECYCLE_BEGIN`/`END`) — diferentes dos usados por
# `compiler.py`/`lifecycle.py` para que os blocos gerenciados convivam no
# mesmo arquivo sem colisão.
TEAM_AGENT_BEGIN = "<!-- harness:team:agent:begin -->"
TEAM_AGENT_END = "<!-- harness:team:agent:end -->"

TEAM_SKILL_BEGIN = "<!-- harness:team:skill:begin -->"
TEAM_SKILL_END = "<!-- harness:team:skill:end -->"


def _format_tools(tools: list[str]) -> str:
    """`role.tools` como string separada por vírgula (ex. "Read, Grep,
    Glob, Bash"). Lista vazia vira string vazia — ver nota em
    `render_agent_md` sobre o efeito disso no frontmatter `tools:`."""
    return ", ".join(tools)


def render_agent_md(role: TeamRole, pattern: TeamPattern) -> str:
    """Renderiza o conteúdo completo de `.claude/agents/<role.name>.md`
    (arquivo do PROJETO-ALVO, não do plugin): frontmatter YAML
    (`name`/`description`/`tools`) + bloco gerenciado delimitado por
    `TEAM_AGENT_BEGIN`/`TEAM_AGENT_END` (mesma técnica de substituição por
    delimitadores de `lifecycle.py::LIFECYCLE_BEGIN`/`END` — nunca reescreve
    o arquivo inteiro se ele já tiver conteúdo do usuário fora do bloco;
    ver `install_team_agents`).

    Papel sem `tools` declaradas (os 4 padrões template do SUBAGENTE 01,
    que não têm `tools` detalhado por papel) produz `tools: ""` no
    frontmatter. Claude Code trata ausência/string vazia de `tools` como
    "todas as ferramentas liberadas" para aquele agente — esse efeito é
    intencional e não é restringido aqui; é o comportamento correto para
    papéis sem `tools` fixadas no catálogo.
    """
    tools_str = _format_tools(role.tools)
    return f"""---
name: {role.name}
description: {role.responsibilities}
tools: {tools_str}
---

{TEAM_AGENT_BEGIN}
# Papel: {role.name} (time {pattern.name}, gerado pelo harness-creator)

{role.responsibilities}

Ferramentas mínimas deste papel: {tools_str}. NÃO peça nem use
ferramentas fora desta lista — o audit de time (`harness audit-team`)
detecta e reporta qualquer drift.
{TEAM_AGENT_END}
"""


def _extract_block(rendered: str, begin: str, end: str) -> str:
    """Extrai a substring `begin...end` (inclusive) de `rendered`."""
    start_idx = rendered.index(begin)
    end_idx = rendered.index(end) + len(end)
    return rendered[start_idx:end_idx]


def _write_managed_block(path: Path, full_content: str, begin: str, end: str) -> None:
    """Grava `full_content` em `path`, respeitando o padrão de bloco
    gerenciado (mesma técnica de `lifecycle.py::install_lifecycle`):

    - arquivo ainda não existe -> grava `full_content` (frontmatter+bloco
      completo).
    - arquivo existe e já tem `begin`/`end` -> substitui SÓ o conteúdo entre
      eles (regex `re.DOTALL`), preservando frontmatter/texto do usuário
      fora do bloco. Rodar de novo com o mesmo conteúdo é idempotente (não
      duplica o bloco).
    - arquivo existe mas ainda não tem `begin`/`end` -> anexa o bloco no fim
      do arquivo, sem apagar o conteúdo já existente.
    """
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(full_content, encoding="utf-8")
        return

    new_block = _extract_block(full_content, begin, end)
    text = path.read_text(encoding="utf-8")
    if begin in text and end in text:
        pattern = re.compile(re.escape(begin) + ".*?" + re.escape(end), re.DOTALL)
        text = pattern.sub(lambda _: new_block, text, count=1)
    else:
        text = text.rstrip() + "\n\n" + new_block + "\n"
    path.write_text(text, encoding="utf-8")


def install_team_agents(target_dir: Path, pattern: TeamPattern) -> list[Path]:
    """Grava/atualiza `target_dir/.claude/agents/<role.name>.md` para cada
    `role in pattern.roles`, usando `render_agent_md` + `_write_managed_block`
    (substitui só o bloco `TEAM_AGENT_BEGIN`/`END` se o arquivo já existir
    com os delimitadores; cria o arquivo com frontmatter+bloco completo caso
    contrário). Idempotente: rodar duas vezes não duplica conteúdo.

    Devolve a lista de paths gravados, na mesma ordem de `pattern.roles`.
    """
    agents_dir = target_dir / ".claude" / "agents"
    written: list[Path] = []
    for role in pattern.roles:
        path = agents_dir / f"{role.name}.md"
        full_content = render_agent_md(role, pattern)
        _write_managed_block(path, full_content, TEAM_AGENT_BEGIN, TEAM_AGENT_END)
        written.append(path)
    return written


def render_skill_md(role: TeamRole, pattern: TeamPattern) -> str:
    """Renderiza o conteúdo completo de
    `.claude/skills/<role.name>/SKILL.md` (arquivo do PROJETO-ALVO) — mesmo
    shape de frontmatter de `skills/plan/SKILL.md`
    (`name`/`description`/`when_to_use`/`disable-model-invocation`) + bloco
    gerenciado delimitado por `TEAM_SKILL_BEGIN`/`TEAM_SKILL_END`.
    """
    return f"""---
name: {role.name}
description: {role.responsibilities}
when_to_use: Papel {role.name} do time {pattern.name} (gerado pelo harness-creator; ver .claude/agents/{role.name}.md para o agente correspondente).
disable-model-invocation: false
---

{TEAM_SKILL_BEGIN}
# {role.name} — time {pattern.name}

{role.responsibilities}
{TEAM_SKILL_END}
"""


def install_team_skills(target_dir: Path, pattern: TeamPattern) -> list[Path]:
    """Grava/atualiza `target_dir/.claude/skills/<role.name>/SKILL.md` para
    cada `role in pattern.roles`, usando `render_skill_md` +
    `_write_managed_block` (mesma técnica de substituição por delimitadores
    de `install_team_agents`). Cria os diretórios necessários
    (`.claude/skills/<role.name>/`). Idempotente: rodar duas vezes não
    duplica conteúdo.

    Devolve a lista de paths gravados, na mesma ordem de `pattern.roles`.
    """
    skills_dir = target_dir / ".claude" / "skills"
    written: list[Path] = []
    for role in pattern.roles:
        path = skills_dir / role.name / "SKILL.md"
        full_content = render_skill_md(role, pattern)
        _write_managed_block(path, full_content, TEAM_SKILL_BEGIN, TEAM_SKILL_END)
        written.append(path)
    return written


# ---------------------------------------------------------------------------
# Integração e orquestração (SUBAGENTE 06): documentação do time em
# AGENTS.md/.harness/TEAM.md + manifesto `.harness/team/manifest.json` +
# `generate_team()`, o entrypoint de topo que compõe as fases 2-5 do
# workflow do ROADMAP.
# ---------------------------------------------------------------------------

# Delimitadores PRÓPRIOS deste bloco (mesma técnica de
# `lifecycle.py::LIFECYCLE_BEGIN`/`END`) — distintos de
# `LIFECYCLE_BEGIN`/`END` (`lifecycle.py`), `AGENTS_BEGIN`/`END`
# (`compiler.py`) e `TEAM_AGENT_BEGIN`/`END` /
# `TEAM_SKILL_BEGIN`/`END` (acima, neste mesmo módulo), para que todos os
# blocos gerenciados convivam no mesmo `AGENTS.md` sem colisão.
TEAM_BEGIN = "<!-- harness:team:begin -->"
TEAM_END = "<!-- harness:team:end -->"

TEAM_DETAIL_PATH = ".harness/TEAM.md"
TEAM_MANIFEST_PATH = ".harness/team/manifest.json"


def render_team_block(pattern: TeamPattern, mode: str) -> str:
    """Bloco curto (progressive disclosure, mesmo estilo de
    `lifecycle.py::render_lifecycle_block`) para o `AGENTS.md`: cita o
    padrão de time escolhido, os papéis e seus arquivos de agente
    (`.claude/agents/<role>.md`), e aponta para o detalhe completo em
    `.harness/TEAM.md`.

    Se `pattern.name == 'supervisor'`, inclui uma linha citando `harness
    supervise` como o comando que decide a próxima feature a trabalhar.
    """
    roles_lines = "\n".join(
        f"- `{role.name}` — `.claude/agents/{role.name}.md`" for role in pattern.roles
    )
    supervisor_line = ""
    if pattern.name == "supervisor":
        supervisor_line = (
            "\n\n`harness supervise` decide a próxima feature a trabalhar, "
            "respeitando `depends[]` de `feature_list.json`."
        )
    return f"""{TEAM_BEGIN}
## Time de Agentes (gerado — padrão `{pattern.name}`, modo `{mode}`)

Padrão de time compilado: `{pattern.name}`.

{roles_lines}{supervisor_line}

Detalhe de cada papel: ver `.harness/TEAM.md`.
{TEAM_END}"""


def render_team_detail(pattern: TeamPattern, mode: str) -> str:
    """Conteúdo completo de `.harness/TEAM.md`: um parágrafo por papel
    (responsabilidades + ferramentas mínimas), a regra do feature-lock
    estendido, o limite de iterações, a regra de escalação e o `mode`
    corrente."""
    role_paragraphs = "\n\n".join(
        f"### `{role.name}`\n\n{role.responsibilities}\n\n"
        f"Ferramentas mínimas deste papel: {_format_tools(role.tools) or '(nenhuma restrição declarada)'}."
        for role in pattern.roles
    )

    role_names = {role.name for role in pattern.roles}
    if {"producer", "reviewer"} <= role_names:
        feature_lock_note = (
            "Este time declara os papéis `producer`+`reviewer`: o feature-lock "
            "estendido de `boundary_guard.py` (SUBAGENTE 04) exige, além da "
            "evidência fresca de `verify_cmd`, a aprovação do revisor para "
            "que uma feature possa transicionar para `passes: true` — "
            "'revisão do time (produtor-revisor) pendente/obsoleta' bloqueia "
            "a transição até o revisor aprovar."
        )
    else:
        feature_lock_note = (
            "Este time não declara os dois papéis `producer`+`reviewer`; o "
            "feature-lock estendido de `boundary_guard.py` (SUBAGENTE 04) não "
            "se aplica — a transição de uma feature para `passes: true` "
            "segue só a regra genérica de evidência fresca."
        )

    supervisor_note = ""
    if pattern.name == "supervisor":
        supervisor_note = (
            "\n\nComando `harness supervise`: lê `.harness/feature_list.json` "
            "e devolve a próxima feature pronta (todas as `depends[]` já com "
            "`passes: true`), sem executar nada por conta própria — quem chama "
            "decide o que fazer com o resultado."
        )

    mode_note = (
        "'subagents': as instâncias de cada papel são despachadas via `Task`/"
        "subagente do próprio Claude Code, seguindo os arquivos gerados em "
        "`.claude/agents/`."
        if mode == "subagents"
        else
        "'agent-teams': rótulo ADVISORY nesta versão do plugin — Claude Code "
        "não tem hoje um recurso nativo dedicado de 'agent teams' com caminho "
        "de código próprio; escolher este modo não muda nenhum comportamento "
        "de execução, é só documentação da intenção."
    )

    return f"""# TEAM.md — Time de Agentes (padrão `{pattern.name}`)

Este arquivo é o detalhe de progressive disclosure do bloco "Time de
Agentes" em `AGENTS.md`. Descreve o time gerado pelo harness-creator a
partir do padrão `{pattern.name}` (Fase 4 do ROADMAP — Team-Architecture
Factory).

## Papéis

{role_paragraphs}

## Feature-lock estendido

{feature_lock_note}

## Limite de iterações de revisão

O número máximo de rodadas de revisão está fixado em
`.harness/team/manifest.json` (`max_review_iterations`). Esgotado o
limite sem aprovação, a regra de escalação vale: o time NUNCA força
aprovação — o estado é escalado ao humano para decisão.{supervisor_note}

## Modo (`mode`)

{mode_note}
"""


def install_team_docs(
    target_dir: Path, pattern: TeamPattern, mode: str
) -> tuple[Path, Path]:
    """Grava/atualiza os dois artefatos de documentação do time no
    projeto-alvo (mesma técnica de `lifecycle.py::install_lifecycle`):

    (a) `target_dir/AGENTS.md` — substitui o conteúdo entre `TEAM_BEGIN`/
        `TEAM_END` se já existir (regex `re.DOTALL`), ou anexa o bloco no
        fim do arquivo (criando o `AGENTS.md` com um cabeçalho mínimo se
        ele não existir) caso as marcações ainda não estejam presentes.
        Nunca apaga texto fora dos delimitadores, nem os blocos de
        `compiler.py` (`AGENTS_BEGIN`/`AGENTS_END`) ou `lifecycle.py`
        (`LIFECYCLE_BEGIN`/`LIFECYCLE_END`) que possam coexistir no mesmo
        arquivo.
    (b) `target_dir/.harness/TEAM.md` — grava `render_team_detail(...)`,
        criando `.harness/` se preciso.

    Retorna `(agents_path, detail_path)`.
    """
    agents_path = target_dir / "AGENTS.md"
    block = render_team_block(pattern, mode)

    if agents_path.is_file():
        text = agents_path.read_text(encoding="utf-8")
        if TEAM_BEGIN in text and TEAM_END in text:
            block_pattern = re.compile(
                re.escape(TEAM_BEGIN) + ".*?" + re.escape(TEAM_END), re.DOTALL
            )
            text = block_pattern.sub(lambda _: block, text, count=1)
        else:
            text = text.rstrip() + "\n\n" + block + "\n"
    else:
        text = "# AGENTS.md — Diretrizes para Agentes\n\n" + block + "\n"
    agents_path.write_text(text, encoding="utf-8")

    detail_path = target_dir / TEAM_DETAIL_PATH
    detail_path.parent.mkdir(parents=True, exist_ok=True)
    detail_path.write_text(render_team_detail(pattern, mode), encoding="utf-8")

    return agents_path, detail_path


def install_team_manifest(
    target_dir: Path,
    pattern: TeamPattern,
    mode: str,
    max_review_iterations: int = 3,
) -> Path:
    """Grava `target_dir/.harness/team/manifest.json` com o schema FIXADO
    (`pattern`, `mode`, `roles: list[str]`, `max_review_iterations: int`,
    `generated_at`). Cria os diretórios necessários. SEMPRE sobrescreve —
    este arquivo é determinístico a partir do padrão escolhido (mesma
    natureza de `init.sh`/`init.ps1` em `templates.py`), nunca é editado
    manualmente pelo agente.
    """
    manifest_path = target_dir / TEAM_MANIFEST_PATH
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "pattern": pattern.name,
        "mode": mode,
        "roles": [role.name for role in pattern.roles],
        "max_review_iterations": max_review_iterations,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest_path


@dataclass
class TeamGenerationResult:
    """Resultado consolidado de `generate_team()`."""

    pattern: str
    mode: str
    roles: list[str]
    agents_written: list[Path]
    skills_written: list[Path]
    agents_md: Path
    team_detail: Path
    manifest: Path


def generate_team(
    target_dir: Path,
    pattern_name: str,
    mode: str = "subagents",
    max_review_iterations: int = 3,
    patterns_dir: Path | None = None,
) -> TeamGenerationResult:
    """Entrypoint de topo (SUBAGENTE 06) que compõe as fases 2-5 do
    workflow de 6 fases descrito no ROADMAP.md ("Fase 4 — Team-Architecture
    Factory"): carrega o padrão já escolhido (`pattern_name` — este
    entrypoint NÃO recomenda o padrão; quem chama já decidiu, seja via
    `recommend_pattern` seja por escolha explícita do humano), gera os
    agentes e skills do time, grava a documentação (`AGENTS.md`/
    `.harness/TEAM.md`) e o manifesto (`.harness/team/manifest.json`),
    nessa ordem, e devolve um `TeamGenerationResult` consolidado.

    Propaga `TeamError` (via `load_pattern`) se `pattern_name` não existir
    no catálogo ou tiver schema inválido.
    """
    pattern = load_pattern(pattern_name, patterns_dir)

    agents_written = install_team_agents(target_dir, pattern)
    skills_written = install_team_skills(target_dir, pattern)
    agents_md, team_detail = install_team_docs(target_dir, pattern, mode)
    manifest = install_team_manifest(
        target_dir, pattern, mode, max_review_iterations=max_review_iterations
    )

    return TeamGenerationResult(
        pattern=pattern.name,
        mode=mode,
        roles=[role.name for role in pattern.roles],
        agents_written=agents_written,
        skills_written=skills_written,
        agents_md=agents_md,
        team_detail=team_detail,
        manifest=manifest,
    )
