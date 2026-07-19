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

Item 5 do ROADMAP (correção da fricção issue #1): `add_task_file` edita
cirurgicamente o bullet `files:` de UMA tarefa em `Plans.md` (append,
idempotente), sem tocar no resto do arquivo — usado por
`harness task add-file` para não exigir edição manual de markdown toda vez
que um campo novo obrigatório quebra specs/testes pré-existentes que
precisam entrar na superfície de uma tarefa já compilada.

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
`## [T-XX] <descrição>` seguido de bullets `files`/`verify` (obrigatórios),
`depends` (opcional, lista de ids desta tarefa depende; vazio por padrão)
e `cwd` (opcional, diretório relativo à raiz do repo onde `verify_cmd`
roda — default a própria raiz). A sintaxe de `depends` já nasce aqui porque
o ROADMAP define `Plans.md` como tendo "sequência de tarefas,
**dependências**, arquivos afetados" e a Fase 4 promete um Supervisor que
despacha "respeitando dependências do Plans.md" — mas este módulo APENAS
parseia e preserva o campo; nenhuma lógica de ordenação/dispatch é
implementada aqui. `cwd` existe porque, em monorepo (`backend/`+`frontend/`
sob uma raiz comum), um `verify_cmd` como `ng test` só resolve o binário
rodando de dentro do workspace do frontend — mas `feature_list.json`
sempre é procurado na raiz (`target_dir`), então `cwd` afeta SÓ o diretório
do subprocess do `verify_cmd`, nunca onde o contrato é resolvido:

    ## [T-01] Criar módulo de configuração
    - files: `src/harness/config.py`, `tests/test_config.py`
    - verify: `pytest tests/test_config.py -q`

    ## [T-02] Integrar configuração no compilador
    - files: `src/harness/compiler.py`
    - verify: `pytest tests/test_compiler.py -q`
    - depends: T-01

    ## [T-03] Testar componente Angular do frontend
    - files: `frontend/src/app/x.component.ts`, `frontend/src/app/x.component.spec.ts`
    - verify: `ng test --include=**/x.component.spec.ts`
    - cwd: `frontend`

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
          "cwd": null,
          "passes": false
        },
        {
          "id": "T-02",
          "desc": "Integrar configuração no compilador",
          "files": ["src/harness/compiler.py"],
          "verify_cmd": "pytest tests/test_compiler.py -q",
          "depends": ["T-01"],
          "cwd": null,
          "passes": false
        },
        {
          "id": "T-03",
          "desc": "Testar componente Angular do frontend",
          "files": ["frontend/src/app/x.component.ts", "frontend/src/app/x.component.spec.ts"],
          "verify_cmd": "ng test --include=**/x.component.spec.ts",
          "depends": [],
          "cwd": "frontend",
          "passes": false
        }
      ]
    }
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from harness import __version__ as _HARNESS_VERSION
from harness.boundary_guard import is_floor_bash_command

WORK_DIR = ".harness/work"
FEATURE_LIST_FILE = ".harness/feature_list.json"

_FRONTMATTER_DELIM = "---"
_TASK_HEADER_RE = re.compile(r"^##\s*\[(?P<id>[^\]]+)\]\s*(?P<desc>.*)$")
_FIELD_RE = re.compile(r"^-\s*(?P<key>files|verify|depends|cwd)\s*:\s*(?P<value>.*)$", re.IGNORECASE)
_BACKTICK_RE = re.compile(r"`([^`]+)`")
# Variante de _FIELD_RE dedicada à reescrita cirúrgica do bullet `files:` —
# usada só por `add_task_file`. Difere de _FIELD_RE por preservar o prefixo
# EXATO (indentação, espaçamento ao redor de ':', caixa de "files") num
# grupo próprio, para que a reescrita toque somente o valor, nunca o resto
# da linha.
_FILES_LINE_RE = re.compile(r"^(?P<prefix>\s*-\s*files\s*:\s*)(?P<value>.*)$", re.IGNORECASE)
_NEWLINE_RE = re.compile(r"(\r\n|\r|\n)$")


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
    cwd: str | None = None


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

    text = spec_path.read_text(encoding="utf-8-sig")
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
# get_stop_conditions
# ---------------------------------------------------------------------------

def get_stop_conditions(spec_path: Path) -> list[str]:
    """Acessor dedicado às `stop_conditions:` do frontmatter de `spec.md`.

    Delega o parsing a `parse_spec` (nenhuma lógica de frontmatter nova
    aqui) e devolve a chave `stop_conditions` já normalizada para
    `list[str]`. Lista vazia se a chave não existir ou for `None` — nunca
    levanta por ausência da chave (ela é opcional no contrato).
    """
    data = parse_spec(spec_path)
    raw = data.get("stop_conditions") or []
    return [str(item) for item in raw]


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

    lines = plans_path.read_text(encoding="utf-8-sig").splitlines()
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
        cwd_values = _split_list(raw_fields["cwd"]) if raw_fields.get("cwd") else []
        cwd = cwd_values[0] if cwd_values else None

        tasks.append(Task(
            id=task_id, desc=desc, files=files, verify_cmd=verify_cmd, depends=depends, cwd=cwd,
        ))

    return tasks


# ---------------------------------------------------------------------------
# add_task_file
# ---------------------------------------------------------------------------

def add_task_file(target_dir: Path, slug: str, task_id: str, new_path: str) -> bool:
    """Adiciona `new_path` ao bullet `files:` da tarefa `task_id` em
    `.harness/work/<slug>/Plans.md`, editando SÓ aquela linha — o resto do
    arquivo (outras tarefas, `verify`/`depends`/`cwd`, formatação, BOM) é
    preservado byte-a-byte. Item 5 do ROADMAP: substitui o ciclo manual de
    editar Plans.md à mão + recompilar quando um novo arquivo passa a
    pertencer à superfície de uma tarefa já existente.

    Idempotente: se `new_path` já estiver no `files[]` da tarefa, não
    escreve nada e devolve `False` (chamador decide como avisar). Devolve
    `True` se o arquivo foi efetivamente modificado.

    Levanta `ContractError` — e NÃO escreve nada em disco — se:
    - `new_path` contém backtick (`` ` ``) ou vírgula (`,`) — esses são os
      caracteres delimitadores do próprio formato `files:` (crases
      envolvem cada item, vírgula separa itens); um path com qualquer um
      dos dois corromperia silenciosamente o próximo `parse_plans` (crase
      corta o item no meio, vírgula parte um path em dois). Rejeitado
      explicitamente em vez de escapado: paths assim não existem em
      projetos reais, e escapar complicaria o parser para um caso que não
      precisa existir;
    - `Plans.md` não existir;
    - `task_id` não existir no arquivo (mensagem lista as tarefas presentes);
    - a tarefa existir mas não tiver bullet `files:` (Plans.md malformado —
      mesma exigência de `parse_plans`, aqui detectada cirurgicamente porque
      esta função não depende de `parse_plans` ter sucesso no arquivo
      inteiro: uma tarefa QUALQUER OUTRA malformada no mesmo Plans.md não
      impede adicionar um arquivo a uma tarefa válida; só a recompilação
      completa (chamada separadamente pelo CLI) exige o arquivo inteiro
      parseável).

    Não recompila `feature_list.json` — só edita o markdown. O chamador
    (CLI `harness task add-file`) decide se e quando recompilar.
    """
    if "`" in new_path or "," in new_path:
        raise ContractError(
            f"path '{new_path}' contém caractere inválido (backtick/vírgula) "
            "que corromperia o formato de files[] no Plans.md"
        )

    target_dir = target_dir.resolve()
    plans_path = target_dir / WORK_DIR / slug / "Plans.md"
    if not plans_path.is_file():
        raise ContractError(f"{plans_path}: Plans.md não encontrado")

    raw_bytes = plans_path.read_bytes()
    had_bom = raw_bytes.startswith(b"\xef\xbb\xbf")
    raw_text = raw_bytes.decode("utf-8-sig")
    lines = raw_text.splitlines(keepends=True)
    n = len(lines)

    task_start: int | None = None
    task_end = n
    found_ids: list[str] = []
    i = 0
    while i < n:
        header = _TASK_HEADER_RE.match(lines[i].strip())
        if header:
            current_id = header.group("id").strip()
            found_ids.append(current_id)
            if current_id == task_id:
                task_start = i
                j = i + 1
                while j < n and not _TASK_HEADER_RE.match(lines[j].strip()):
                    j += 1
                task_end = j
                break
        i += 1

    if task_start is None:
        listed = ", ".join(found_ids) if found_ids else "(nenhuma)"
        raise ContractError(
            f"{plans_path}: tarefa '{task_id}' não encontrada — tarefas presentes: {listed}"
        )

    files_line_idx: int | None = None
    files_match = None
    files_nl = ""
    for idx in range(task_start + 1, task_end):
        raw_line = lines[idx]
        nl_match = _NEWLINE_RE.search(raw_line)
        nl = nl_match.group(0) if nl_match else ""
        body = raw_line[: len(raw_line) - len(nl)] if nl else raw_line
        match = _FILES_LINE_RE.match(body)
        if match:
            # Se houver mais de uma linha `files:` na tarefa (Plans.md
            # malformado), a última vence — mesma semântica de
            # `parse_plans` (dict sobrescrito por chave).
            files_line_idx = idx
            files_match = match
            files_nl = nl

    if files_line_idx is None or files_match is None:
        raise ContractError(
            f"{plans_path}: tarefa '{task_id}' sem campo 'files' (Plans.md malformado)"
        )

    existing_value = files_match.group("value")
    existing_files = _split_list(existing_value)
    if new_path in existing_files:
        return False

    value_stripped = existing_value.rstrip()
    uses_backticks = bool(_BACKTICK_RE.findall(existing_value))
    if not value_stripped:
        addition = f"`{new_path}`"
    elif uses_backticks:
        addition = f", `{new_path}`"
    else:
        addition = f", {new_path}"

    new_value = value_stripped + addition
    lines[files_line_idx] = files_match.group("prefix") + new_value + files_nl

    # newline="" desliga a tradução universal-newlines da escrita em modo
    # texto: sem isso, no Windows, um "\r\n" já presente na linha (lido cru
    # dos bytes) seria traduzido de novo para "\r\n" ao escrever, dobrando
    # para "\r\r\n" — corrompendo TODAS as linhas do arquivo, não só a
    # editada. Escrevemos exatamente os caracteres que já reconstruímos.
    plans_path.write_text(
        "".join(lines), encoding="utf-8-sig" if had_bom else "utf-8", newline=""
    )
    return True


# ---------------------------------------------------------------------------
# compile_contract
# ---------------------------------------------------------------------------

def _load_existing_features(feature_list_path: Path) -> dict[str, dict[str, Any]]:
    if not feature_list_path.is_file():
        return {}
    try:
        data = json.loads(feature_list_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return {}
    return {f["id"]: f for f in data.get("features", []) if "id" in f}


def _dry_check_verify_cmd(verify_cmd: str, cwd: Path, timeout: float = 8.0) -> str | None:
    """Roda `verify_cmd` com timeout curto e devolve um warning (string) se
    o comando falhar rápido — sinal de possível erro de flag/opção inválida
    (heurística fail-fast: `--dry-run-verify`, advisory, nunca bloqueia).

    Invariante de segurança NÃO-NEGOCIÁVEL (achado do llm-as-judge/Opus):
    nunca executa um `verify_cmd` que bata no runtime floor
    (push/rede/publicação) — sem essa checagem, este dry-check seria uma
    via de bypass do floor sob contrato ativo. Checada ANTES de qualquer
    subprocess.
    """
    if is_floor_bash_command(verify_cmd):
        return (
            f"verify_cmd '{verify_cmd}' bate no runtime floor "
            "(push/rede/publicacao) — dry-check NUNCA executa esse tipo de "
            "comando; se isso e inesperado, revise Plans.md"
        )

    try:
        proc = subprocess.run(
            verify_cmd,
            shell=True,
            cwd=cwd,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        # Comando ainda rodando no timeout = sinal de teste de verdade em
        # andamento (subprocess.run já mata o processo internamente ao
        # levantar TimeoutExpired) — trata como são, sem warning.
        return None
    except (FileNotFoundError, OSError) as exc:
        return f"verify_cmd '{verify_cmd}' — comando não encontrado: {exc}"

    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        last_line = stderr.splitlines()[-1] if stderr else "(sem stderr)"
        return (
            f"verify_cmd '{verify_cmd}' falhou rápido (exit {proc.returncode}) — "
            f"pode ser flag/opção inválida OU, se a tarefa ainda não foi "
            f"implementada, o resultado esperado de um teste que ainda falha "
            f"(fluxo TDD): {last_line}"
        )
    return None


def compile_contract(target_dir: Path, slug: str, *, dry_run_verify: bool = False) -> Path:
    """Compila `.harness/work/<slug>/{spec.md,Plans.md}` -> `.harness/feature_list.json`.

    GATE OBRIGATÓRIO: se `approved_by` ou `approved_at` estiverem ausentes ou
    vazios no frontmatter de `spec.md`, levanta `ContractNotApprovedError` e
    NÃO escreve nada em disco — sem aprovação, nada compila.

    Recompilação: tarefas cujo (`id`, `verify_cmd`, `files`) não mudaram em
    relação ao `feature_list.json` existente preservam `passes: true`; ids
    novos entram com `passes: false`; ids removidos do Plans.md somem da
    saída.

    `dry_run_verify=True` (opt-in, `--dry-run-verify` na CLI): antes de
    escrever `feature_list.json`, roda cada `verify_cmd` distinto (por
    `(verify_cmd, cwd)`) com timeout curto e escreve um warning em stderr se
    ele falhar rápido — nunca levanta exceção, nunca impede a escrita.
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
            and old.get("cwd") == task.cwd
            and old.get("passes")
        )
        features.append({
            "id": task.id,
            "desc": task.desc,
            "files": task.files,
            "verify_cmd": task.verify_cmd,
            "depends": task.depends,
            "cwd": task.cwd,
            "passes": passes,
        })

    if dry_run_verify:
        seen_pairs: set[tuple[str, str | None]] = set()
        for task in tasks:
            key = (task.verify_cmd, task.cwd)
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            check_cwd = (target_dir / task.cwd) if task.cwd else target_dir
            warning = _dry_check_verify_cmd(task.verify_cmd, cwd=check_cwd, timeout=8.0)
            if warning is not None:
                print(f"aviso: {warning}", file=sys.stderr)

    payload = {
        "contract": slug,
        "compiled_at": datetime.now(timezone.utc).isoformat(),
        "compiled_with_version": _HARNESS_VERSION,
        "features": features,
    }

    feature_list_path.parent.mkdir(parents=True, exist_ok=True)
    feature_list_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return feature_list_path
