"""Templates: `feature_list.json`/`repo-profile.json` -> `claude-progress.md` + `init.*`.

Fase 2 do docs/project/ROADMAP ("Delegação Baseada em Contratos"): o lifecycle de 16
passos (ver docs/project/ROADMAP.md, Fase 2) manda o agente 1) ler AGENTS.md, 2) rodar
`init.sh`/`init.ps1` (deps + health check gerados a partir do
`repo-profile.json`), 3) ler `claude-progress.md`, 4) ler
`feature_list.json`. Este módulo gera os artefatos dos passos 2 e 3.

Duas naturezas de arquivo bem distintas:

- `claude-progress.md` é estado RUNTIME-MUTÁVEL — o agente escreve nele a
  cada sessão (o que foi feito, o que quebrou, onde parou). Este módulo
  gera só o ESQUELETO inicial (uma vez); recompilar o contrato NUNCA pode
  sobrescrever progresso já registrado, então `install_templates` só grava
  este arquivo se ele ainda não existir.
- `init.sh`/`init.ps1` são determinísticos — função pura do
  `repo-profile.json` (mesmo profile => mesmo script). Recompilar sempre
  regenera os dois, sem risco: não guardam estado, só refletem o profile
  mais recente (ex.: package manager mudou de npm para pnpm).

`profile.get('package_manager')` e `profile.get('test_command')` no
`repo-profile.json` real (ver `analyzer.py`) SEMPRE existem como chave,
mas o valor é `None` explícito quando o detector não achou nada — nunca
a chave ausente com fallback `{}` do `.get`. Por isso este módulo usa
`(profile.get('package_manager') or {}).get('value')` e não
`profile.get('package_manager', {}).get('value')`: a segunda forma
quebra com `AttributeError` assim que o valor for `None` de verdade,
porque o `.get(..., {})` só entra em jogo quando a CHAVE está ausente,
nunca quando ela existe com valor `None`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

CLAUDE_PROGRESS_FILE = "claude-progress.md"
INIT_SH_FILE = "init.sh"
INIT_PS1_FILE = "init.ps1"

# package_manager.value -> comando de instalação de dependências.
_INSTALL_COMMANDS: dict[str, str] = {
    "npm": "npm ci",
    "pnpm": "pnpm install --frozen-lockfile",
    "yarn": "yarn install --frozen-lockfile",
    "uv": "uv sync",
    "poetry": "poetry install",
}

_NO_PACKAGE_MANAGER_COMMENT = "nenhum package manager detectado — pule esta etapa"
_NO_TEST_COMMAND_COMMENT = "nenhum test_command detectado"

_CONTRACT_LINE_PREFIX = "Contrato: `"
_LAST_UPDATE_HEADING = "## Última atualização"


# ---------------------------------------------------------------------------
# claude-progress.md
# ---------------------------------------------------------------------------

def render_progress_template(feature_list: dict[str, Any]) -> str:
    """Gera o conteúdo INICIAL de `claude-progress.md` a partir do contrato
    compilado (`feature_list.json`). Cada feature aparece com status inicial
    'pending' (todo `passes` recém-compilado é `false`). Este é apenas o
    esqueleto de primeira geração — nunca deve ser usado para sobrescrever um
    `claude-progress.md` já existente (isso é responsabilidade de
    `install_templates`, não desta função)."""
    contract = feature_list.get("contract", "")
    features = feature_list.get("features", [])

    lines = ["# Claude Progress", ""]
    if contract:
        lines.append(f"Contrato: `{contract}`")
        lines.append("")

    lines.append("## Features")
    lines.append("")
    if features:
        lines.append("| id | desc | status |")
        lines.append("| --- | --- | --- |")
        for feature in features:
            feature_id = feature.get("id", "")
            desc = feature.get("desc", "")
            status = "pending" if not feature.get("passes") else "done"
            lines.append(f"| {feature_id} | {desc} | {status} |")
    else:
        lines.append("_Nenhuma feature no contrato._")
    lines.append("")

    lines.append("## Última atualização")
    lines.append("")
    lines.append("_(vazio — preenchido pelo agente durante a sessão)_")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# init.sh / init.ps1
# ---------------------------------------------------------------------------

def render_init_scripts(profile: dict[str, Any]) -> tuple[str, str]:
    """Gera `(init_sh, init_ps1)` a partir do `repo-profile.json`: instalação
    de dependências (por `package_manager.value`) seguida do health check
    (`test_command.value`, se detectado). Mesmo conteúdo semântico nas duas
    linguagens."""
    package_manager = (profile.get("package_manager") or {}).get("value")
    test_command = (profile.get("test_command") or {}).get("value")

    install_cmd = _INSTALL_COMMANDS.get(package_manager) if package_manager else None

    sh_lines = ["#!/usr/bin/env bash", "set -e", ""]
    if install_cmd:
        sh_lines.append(install_cmd)
    else:
        sh_lines.append(f"# {_NO_PACKAGE_MANAGER_COMMENT}")
    sh_lines.append("")
    if test_command:
        sh_lines.append(test_command)
    else:
        sh_lines.append(f"# {_NO_TEST_COMMAND_COMMENT}")
    sh_lines.append("")
    init_sh = "\n".join(sh_lines)

    ps1_lines = ["$ErrorActionPreference = 'Stop'", ""]
    if install_cmd:
        ps1_lines.append(install_cmd)
    else:
        ps1_lines.append(f"# {_NO_PACKAGE_MANAGER_COMMENT}")
    ps1_lines.append("")
    if test_command:
        ps1_lines.append(test_command)
    else:
        ps1_lines.append(f"# {_NO_TEST_COMMAND_COMMENT}")
    ps1_lines.append("")
    init_ps1 = "\n".join(ps1_lines)

    return init_sh, init_ps1


# ---------------------------------------------------------------------------
# I/O (escreve no projeto-alvo)
# ---------------------------------------------------------------------------

def _extract_progress_contract(text: str) -> str | None:
    """Lê o slug do contrato do header `Contrato: \\`slug\\`` de um
    `claude-progress.md` já gravado. `None` se a linha não existir — cobre
    tanto conteúdo customizado pelo agente (sem esse header) quanto o caso
    `contract` vazio no `feature_list.json` de origem."""
    for line in text.splitlines():
        if line.startswith(_CONTRACT_LINE_PREFIX) and line.endswith("`"):
            return line[len(_CONTRACT_LINE_PREFIX):-1]
    return None


def _extract_last_update_section(text: str) -> str | None:
    """Retorna o trecho de `text` a partir do heading `## Última
    atualização` (inclusive) até o fim do arquivo — a parte RUNTIME-MUTÁVEL
    que o agente edita durante a sessão. `None` se o heading não existir."""
    idx = text.find(_LAST_UPDATE_HEADING)
    if idx == -1:
        return None
    return text[idx:]


def install_templates(
    target_dir: Path, feature_list: dict[str, Any], profile: dict[str, Any]
) -> list[Path]:
    """Grava `claude-progress.md`, `init.sh` e `init.ps1` em `target_dir`.

    `claude-progress.md` é RUNTIME-MUTÁVEL: por padrão só é gravado se ainda
    não existir (recompilar nunca apaga progresso já registrado pelo
    agente). Exceção (achado A do dogfood 2026-07-22): se o arquivo já
    existente tem um header `Contrato: \\`slug\\`` reconhecível e esse slug
    diverge do `contract` do `feature_list` recém-compilado, o arquivo é
    RESTAURADO para o novo contrato — senão o agente lê passos/features de
    um contrato que não é mais o ativo. A seção `## Última atualização`
    (notas livres do agente) é sempre preservada nesse caso. Conteúdo sem
    header reconhecível (customizado manualmente, sem `Contrato: \\`...\\``)
    nunca é tocado — comportamento pré-existente mantido.
    `init.sh`/`init.ps1` são determinísticos: sempre (re)gravados com o
    profile mais recente.

    Retorna a lista de paths escritos NESTA chamada — se `claude-progress.md`
    já existia e não precisou ser restaurado, ele não entra na lista.
    """
    target_dir = target_dir.resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []

    progress_path = target_dir / CLAUDE_PROGRESS_FILE
    if not progress_path.is_file():
        progress_path.write_text(render_progress_template(feature_list), encoding="utf-8")
        written.append(progress_path)
    else:
        existing = progress_path.read_text(encoding="utf-8")
        new_contract = feature_list.get("contract", "")
        old_contract = _extract_progress_contract(existing)
        if old_contract is not None and new_contract and old_contract != new_contract:
            new_content = render_progress_template(feature_list)
            last_update = _extract_last_update_section(existing)
            if last_update is not None:
                heading_idx = new_content.find(_LAST_UPDATE_HEADING)
                new_content = new_content[:heading_idx] + last_update
            progress_path.write_text(new_content, encoding="utf-8")
            written.append(progress_path)

    init_sh, init_ps1 = render_init_scripts(profile)

    init_sh_path = target_dir / INIT_SH_FILE
    init_sh_path.write_text(init_sh, encoding="utf-8")
    written.append(init_sh_path)

    init_ps1_path = target_dir / INIT_PS1_FILE
    init_ps1_path.write_text(init_ps1, encoding="utf-8")
    written.append(init_ps1_path)

    return written


# ---------------------------------------------------------------------------
# update_progress_status (US-2 — sincronização automática)
# ---------------------------------------------------------------------------

def update_progress_status(target_dir: Path, feature_id: str, status: str) -> bool:
    """Reescreve a coluna de status da linha de `feature_id` na tabela do
    `claude-progress.md` de `target_dir` para `status`.

    Elimina o passo manual 12 do lifecycle: em vez de o agente lembrar de
    editar o markdown, o `run_verify` chama esta função ao provar a feature
    (ver `harness.verify.run_verify`). Casa a fonte de verdade real
    (`feature_list.json`/`passes`) com o rastro legível.

    Só toca a linha de tabela cujo 1º campo (entre os pipes) é exatamente
    `feature_id` — reescreve o 3º campo (status) preservando id e desc. Todo
    o resto do arquivo (cabeçalho, seção "Última atualização", texto livre do
    agente) fica intacto. Idempotente: reaplicar com o mesmo `status` não
    muda nada.

    NO-OP silencioso (retorna `False`, nunca levanta) quando o arquivo não
    existe OU nenhuma linha casa `feature_id` — nunca cria o arquivo nem o
    esqueleto (isso é responsabilidade de `install_templates`). Retorna
    `True` se uma linha foi reescrita.
    """
    progress_path = target_dir / CLAUDE_PROGRESS_FILE
    if not progress_path.is_file():
        return False

    lines = progress_path.read_text(encoding="utf-8").splitlines(keepends=True)
    changed = False
    for i, line in enumerate(lines):
        # Linha de tabela: "| id | desc | status |" — split por "|" gera
        # ['', ' id ', ' desc ', ' status ', ''] (5 campos). Só reescreve se
        # o campo de id casar exatamente e houver a coluna de status.
        parts = line.split("|")
        if len(parts) != 5:
            continue
        if parts[1].strip() != feature_id:
            continue
        newline = f"| {parts[1].strip()} | {parts[2].strip()} | {status} |"
        if line.endswith("\n"):
            newline += "\n"
        if newline != line:
            lines[i] = newline
            changed = True
        break

    if changed:
        progress_path.write_text("".join(lines), encoding="utf-8")
    return changed
