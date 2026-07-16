"""Contrato: `spec.md` + `Plans.md` -> `.harness/feature_list.json`.

Fase 1 do ROADMAP ("Delegação Baseada em Contratos"): TODA a autoridade
humana se concentra num único artefato aprovável — o par `spec.md` (o
*quê*: escopo, critérios de aceitação, stop conditions) + `Plans.md` (o
*como*: tarefas, arquivos afetados, comando de verificação). Só depois do
gate de aprovação (frontmatter `approved_by`/`approved_at` preenchido) o
contrato compila para `.harness/feature_list.json` — formato consumido
pelo lifecycle da Fase 2/3. Sem aprovação, nada compila (regra do
ROADMAP): `compile_contract` não escreve UM byte em disco se o gate falhar.

Este módulo espelha o padrão de `compiler.py` (mesmo projeto, mesmo eixo
`render()`/`compile_*`), mas com um cuidado a mais na recompilação:
`passes: true` de uma tarefa só é preservado entre compilações se a
IDENTIDADE da tarefa não mudou — (`id`, `verify_cmd`, `files`). Mudar
só a descrição não invalida evidência já registrada; mudar arquivos ou
comando de verificação invalida (a evidência antiga não prova mais nada
sobre o novo escopo). Tarefa removida do `Plans.md` simplesmente some do
`feature_list.json` recompilado.

Formato do diretório de contrato — `.harness/work/<slug>/`:

    .harness/work/<slug>/
        spec.md      # frontmatter YAML + corpo em markdown
        Plans.md     # blocos de tarefa em markdown

Exemplo LITERAL e COMPLETO de `spec.md` válido (referência exata para
quem for gerar este arquivo, ex.: skill `plan`):

    ---
    slug: exemplo-feature
    approved_by: alice
    approved_at: 2026-07-15T10:00:00Z
    stop_conditions:
      - "3 falhas consecutivas da mesma suíte de teste"
      - "verify_cmd referenciado não existe no repo-profile"
    ---

    # Spec: Exemplo de Feature

    ## Escopo
    Descrição em linguagem natural do que deve ser feito e por quê.

    ## Critérios de aceitação
    - Critério executável 1.
    - Critério executável 2.

    ## Unknowns
    - O que não foi observado no repo-profile (se houver).

Exemplo LITERAL e COMPLETO de `Plans.md` válido — cada tarefa é um bloco
`## [T-XX] <descrição>` seguido de bullets `files`/`verify` (obrigatórios)
e `depends` (opcional, lista de ids desta tarefa depende; vazio por
padrão). A sintaxe de `depends` já nasce aqui porque o ROADMAP define
`Plans.md` como tendo "sequência de tarefas, **dependências**, arquivos
afetados" e a Fase 4 promete um Supervisor que despacha "respeitando
dependências do Plans.md" — mas este módulo APENAS parseia e preserva o
campo; nenhuma lógica de ordenação/dispatch é implementada aqui:

    ## [T-01] Criar módulo de configuração
    - files: `src/harness/config.py`, `tests/test_config.py`
    - verify: `pytest tests/test_config.py -q`

    ## [T-02] Integrar configuração no compilador
    - files: `src/harness/compiler.py`
    - verify: `pytest tests/test_compiler.py -q`
    - depends: T-01

Saída de `compile_contract` — `.harness/feature_list.json`:

    {
      "contract": "exemplo-feature",
      "compiled_at": "2026-07-15T12:00:00+00:00",
      "features": [
        {
          "id": "T-01",
          "desc": "Criar módulo de configuração",
          "files": ["src/harness/config.py", "tests/test_config.py"],
          "verify_cmd": "pytest tests/test_config.py -q",
          "depends": [],
          "passes": false
        },
        {
          "id": "T-02",
          "desc": "Integrar configuração no compilador",
          "files": ["src/harness/compiler.py"],
          "verify_cmd": "pytest tests/test_compiler.py -q",
          "depends": ["T-01"],
          "passes": false
        }
      ]
    }
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

WORK_DIR = ".harness/work"
FEATURE_LIST_FILE = ".harness/feature_list.json"

_FRONTMATTER_DELIM = "---"
_TASK_HEADER_RE = re.compile(r"^##\s*\[(?P<id>[^\]]+)\]\s*(?P<desc>.*)$")
_FIELD_RE = re.compile(r"^-\s*(?P<key>files|verify|depends)\s*:\s*(?P<value>.*)$", re.IGNORECASE)
_BACKTICK_RE = re.compile(r"`([^`]+)`")


class ContractError(Exception):
    """Base para erros de parsing/compilação do contrato."""


class ContractNotApprovedError(ContractError):
    """Gate de aprovação não satisfeito — `compile_contract` não escreve nada."""


@dataclass
class Task:
    """Uma tarefa `## [T-XX]` do `Plans.md`."""

    id: str
    desc: str
    files: list[str]
    verify_cmd: str
    depends: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# parse_spec
# ---------------------------------------------------------------------------

def parse_spec(spec_path: Path) -> dict[str, Any]:
    """Extrai o frontmatter YAML de `spec.md` como dict.

    Levanta `ContractError` com mensagem clara se o arquivo não existir, não
    tiver frontmatter delimitado por `---`/`---`, ou se o YAML for inválido.
    """
    if not spec_path.is_file():
        raise ContractError(f"{spec_path}: spec.md não encontrado")

    text = spec_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FRONTMATTER_DELIM:
        raise ContractError(
            f"{spec_path}: spec.md malformado — precisa começar com frontmatter "
            f"YAML delimitado por '{_FRONTMATTER_DELIM}'"
        )
    try:
        closing_offset = lines[1:].index(_FRONTMATTER_DELIM)
    except ValueError:
        raise ContractError(
            f"{spec_path}: spec.md malformado — frontmatter YAML sem delimitador "
            f"de fechamento '{_FRONTMATTER_DELIM}'"
        ) from None

    frontmatter_text = "\n".join(lines[1:closing_offset + 1])
    try:
        data = yaml.safe_load(frontmatter_text)
    except yaml.YAMLError as exc:
        raise ContractError(f"{spec_path}: frontmatter YAML inválido — {exc}") from exc

    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ContractError(f"{spec_path}: frontmatter YAML deve ser um mapeamento (dict)")
    return data


# ---------------------------------------------------------------------------
# parse_plans
# ---------------------------------------------------------------------------

def _split_list(raw: str) -> list[str]:
    backticked = _BACKTICK_RE.findall(raw)
    if backticked:
        return [item.strip() for item in backticked if item.strip()]
    return [item.strip() for item in raw.split(",") if item.strip()]


def parse_plans(plans_path: Path) -> list[Task]:
    """Extrai as tarefas `## [T-XX]` de `Plans.md`.

    Levanta `ContractError` nomeando a tarefa se faltar `files` ou `verify`.
    """
    if not plans_path.is_file():
        raise ContractError(f"{plans_path}: Plans.md não encontrado")

    lines = plans_path.read_text(encoding="utf-8").splitlines()
    tasks: list[Task] = []
    i = 0
    n = len(lines)
    while i < n:
        header = _TASK_HEADER_RE.match(lines[i].strip())
        if not header:
            i += 1
            continue

        task_id = header.group("id").strip()
        desc = header.group("desc").strip()
        i += 1

        raw_fields: dict[str, str] = {}
        while i < n and not _TASK_HEADER_RE.match(lines[i].strip()):
            field_match = _FIELD_RE.match(lines[i].strip())
            if field_match:
                raw_fields[field_match.group("key").lower()] = field_match.group("value").strip()
            i += 1

        if not raw_fields.get("files"):
            raise ContractError(
                f"{plans_path}: tarefa {task_id} sem campo 'files' obrigatório"
            )
        if not raw_fields.get("verify"):
            raise ContractError(
                f"{plans_path}: tarefa {task_id} sem campo 'verify' obrigatório"
            )

        files = _split_list(raw_fields["files"])
        verify_values = _split_list(raw_fields["verify"])
        verify_cmd = verify_values[0] if verify_values else raw_fields["verify"].strip()
        depends = _split_list(raw_fields["depends"]) if raw_fields.get("depends") else []

        tasks.append(Task(id=task_id, desc=desc, files=files, verify_cmd=verify_cmd, depends=depends))

    return tasks


# ---------------------------------------------------------------------------
# compile_contract
# ---------------------------------------------------------------------------

def _load_existing_features(feature_list_path: Path) -> dict[str, dict[str, Any]]:
    if not feature_list_path.is_file():
        return {}
    try:
        data = json.loads(feature_list_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return {f["id"]: f for f in data.get("features", []) if "id" in f}


def compile_contract(target_dir: Path, slug: str) -> Path:
    """Compila `.harness/work/<slug>/{spec.md,Plans.md}` -> `.harness/feature_list.json`.

    GATE OBRIGATÓRIO: se `approved_by` ou `approved_at` estiverem ausentes ou
    vazios no frontmatter de `spec.md`, levanta `ContractNotApprovedError` e
    NÃO escreve nada em disco — sem aprovação, nada compila.

    Recompilação: tarefas cujo (`id`, `verify_cmd`, `files`) não mudaram em
    relação ao `feature_list.json` existente preservam `passes: true`; ids
    novos entram com `passes: false`; ids removidos do Plans.md somem da
    saída.
    """
    target_dir = target_dir.resolve()
    contract_dir = target_dir / WORK_DIR / slug
    spec_path = contract_dir / "spec.md"
    plans_path = contract_dir / "Plans.md"

    spec = parse_spec(spec_path)
    approved_by = spec.get("approved_by")
    approved_at = spec.get("approved_at")
    if not approved_by or not approved_at:
        raise ContractNotApprovedError(
            "contrato não aprovado — preencha approved_by/approved_at no spec.md"
        )

    tasks = parse_plans(plans_path)

    feature_list_path = target_dir / FEATURE_LIST_FILE
    existing = _load_existing_features(feature_list_path)

    features: list[dict[str, Any]] = []
    for task in tasks:
        old = existing.get(task.id)
        passes = bool(
            old is not None
            and old.get("verify_cmd") == task.verify_cmd
            and old.get("files") == task.files
            and old.get("passes")
        )
        features.append({
            "id": task.id,
            "desc": task.desc,
            "files": task.files,
            "verify_cmd": task.verify_cmd,
            "depends": task.depends,
            "passes": passes,
        })

    payload = {
        "contract": slug,
        "compiled_at": datetime.now(timezone.utc).isoformat(),
        "features": features,
    }

    feature_list_path.parent.mkdir(parents=True, exist_ok=True)
    feature_list_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return feature_list_path
