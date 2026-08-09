"""Templates: `feature_list.json`/`repo-profile.json` -> `progress.md` + `init.*`.

Fase 2 do docs/project/ROADMAP ("Delegação Baseada em Contratos"): o lifecycle de 16
passos (ver docs/project/ROADMAP.md, Fase 2) manda o agente 1) ler AGENTS.md, 2) rodar
`.harness/init.sh`/`.harness/init.ps1` (deps + health check gerados a partir
do `repo-profile.json`), 3) ler `.harness/progress.md`, 4) ler
`feature_list.json`. Este módulo gera os artefatos dos passos 2 e 3.

**Os três moram em `.harness/`, não na raiz do projeto-alvo** (item 6 do
backlog de `docs/project/AUDIT-footprint-raiz-e-versionamento-2026-07-26.md`).
Nenhum deles é lido por ferramenta externa — só o próprio harness os
consome —, então ocupar a raiz do repositório do usuário nunca teve
justificativa; `init.sh` em particular é nome de altíssima colisão com
script de bootstrap pré-existente do projeto. Não existe leitura
retrocompatível do caminho antigo: o produto é pré-produção e a instalação
é sempre feita do zero (ver `settings_paths` para a mesma premissa).

Duas naturezas de arquivo bem distintas:

- `.harness/progress.md` é estado RUNTIME-MUTÁVEL — o agente escreve nele a
  cada sessão (o que foi feito, o que quebrou, onde parou). Este módulo
  gera só o ESQUELETO inicial (uma vez); recompilar o contrato NUNCA pode
  sobrescrever progresso já registrado, então `install_templates` só grava
  este arquivo se ele ainda não existir.
- `.harness/init.sh`/`.harness/init.ps1` são determinísticos — função pura
  do `repo-profile.json` (mesmo profile => mesmo script). Recompilar
  regenera os dois, sem risco: não guardam estado, só refletem o profile
  mais recente (ex.: package manager mudou de npm para pnpm). A única
  exceção é o arquivo EDITADO À MÃO: todo script gerado carrega
  `MANAGED_MARKER` na segunda linha, e um `init.*` sem esse marcador é
  preservado intacto em vez de sobrescrito (item 5 do mesmo backlog —
  regenerar por cima apagava trabalho do usuário sem aviso).

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

import re
from pathlib import Path
from typing import Any

from harness.install_command import install_command_for
from harness.spine import (
    DECISIONS_FILE,
    DECISIONS_HEADER,
    LESSONS_FILE,
    LESSONS_HEADER,
)

HARNESS_DIR = ".harness"

PROGRESS_FILE = f"{HARNESS_DIR}/progress.md"
INIT_SH_FILE = f"{HARNESS_DIR}/init.sh"
INIT_PS1_FILE = f"{HARNESS_DIR}/init.ps1"

#: Segunda linha de todo `init.*` gerado — é o que distingue script nosso de
#: script que o usuário editou. Comentário `#` nas duas linguagens; ASCII puro
#: porque o `.ps1` é lido pelo PowerShell 5.1, que erra com UTF-8 multi-byte.
MANAGED_MARKER = (
    "# gerado por harness-creator a partir de .harness/repo-profile.json"
    " - nao editar a mao"
)

# O mapa `package_manager.value` -> comando de instalação vive em
# `harness.install_command` (fonte única — ver o docstring de lá para o achado
# F2 que motivou a unificação).

# ASCII puro, como `MANAGED_MARKER` e pelo mesmo motivo: estes comentários saem
# dentro do `init.ps1`, lido pelo PowerShell 5.1 — o travessão que estava aqui
# chegava corrompido no terminal do usuário.
_NO_PACKAGE_MANAGER_COMMENT = "nenhum package manager detectado - pule esta etapa"
_NO_TEST_COMMAND_COMMENT = "nenhum test_command detectado"

_CONTRACT_LINE_PREFIX = "Contrato: `"
_LAST_UPDATE_HEADING = "## Última atualização"

#: Delimitadores do trecho AUTOMÁTICO dentro de `## Última atualização`
#: (item 4 do backlog do dogfood miojo). Existem para o carimbo do
#: `run_verify` e a prosa do agente coexistirem no mesmo arquivo: sem
#: fronteira explícita, ou o automático sobrescreve a nota humana, ou o
#: humano precisa desviar do automático. Comentário HTML porque não aparece
#: no markdown renderizado.
_AUTO_NOTE_BEGIN = "<!-- harness:auto -->"
_AUTO_NOTE_END = "<!-- /harness:auto -->"

#: Quantas entradas automáticas o bloco guarda. O propósito do arquivo é a
#: próxima sessão retomar o contexto, não manter um log completo — a
#: evidência em `.harness/evidence/` é que é o registro permanente.
_AUTO_NOTE_MAX_ENTRIES = 10

#: Casa o caminho de evidência citado numa entrada automática (formato fixo
#: de `verify.py`: "... — <feature_id> verificado (exit_code 0) — <path>").
#: Usado só para VALIDAR se a evidência ainda existe (Onda 2/T-05) — uma
#: linha sem esse formato (nota manual, prosa livre) nunca é filtrada por
#: falta de correspondência.
_EVIDENCE_PATH_RE = re.compile(r"(\.harness/evidence/\S+\.json)")


def _auto_entry_evidence_exists(line: str, target_dir: Path) -> bool:
    match = _EVIDENCE_PATH_RE.search(line)
    if match is None:
        return True
    return (target_dir / match.group(1)).is_file()


# ---------------------------------------------------------------------------
# .harness/progress.md
# ---------------------------------------------------------------------------

def render_progress_template(feature_list: dict[str, Any]) -> str:
    """Gera o conteúdo INICIAL de `.harness/progress.md` a partir do contrato
    compilado (`feature_list.json`). Cada feature aparece com status inicial
    'pending' (todo `passes` recém-compilado é `false`). Este é apenas o
    esqueleto de primeira geração — nunca deve ser usado para sobrescrever um
    `.harness/progress.md` já existente (isso é responsabilidade de
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

#: Delimitadores da região gerenciada de tentativas dentro do `progress.md`.
#: Mesma técnica dos blocos do `AGENTS.md` (`compiler.py`, `lifecycle.py`) e
#: pelo mesmo motivo: o `progress.md` é arquivo do AGENTE — ele escreve texto
#: livre ali —, então o harness só pode mandar dentro de uma faixa que ele
#: mesmo abriu e fecha.
ATTEMPTS_BEGIN = "<!-- harness:attempts:begin -->"
ATTEMPTS_END = "<!-- harness:attempts:end -->"

_ATTEMPTS_REGION_RE = re.compile(
    re.escape(ATTEMPTS_BEGIN) + r".*?" + re.escape(ATTEMPTS_END), re.DOTALL
)


def _attempts_heading(feature_id: str) -> str:
    return f"### Tentativas — {feature_id}"


def render_attempts_section(feature_id: str, failures: list[dict[str, Any]]) -> str:
    """Subseção legível das tentativas AINDA EM ABERTO de uma feature.

    Uma linha por tentativa, na ordem em que aconteceram:

        ### Tentativas — T-01

        1. exit 1 — E   assert 1 == 2 (sig 9f2b1c4d5e6f)
        2. exit 1 — E   assert 1 == 2 (sig 9f2b1c4d5e6f)

    A assinatura vai na linha de propósito: duas linhas com o mesmo `sig` são
    o padrão repetido de §8.2 visível a olho nu, antes mesmo de alguém rodar
    `harness budget`. O que entra aqui é a linha de erro CRUA registrada no
    rastro — resumir na renderização jogaria fora o mesmo sinal que o §3 do
    design manda preservar.
    """
    lines = [_attempts_heading(feature_id), ""]
    for number, failure in enumerate(failures, start=1):
        line = failure.get("failure_line") or "(sem mensagem)"
        lines.append(
            f"{number}. exit {failure.get('exit_code')} — {line} "
            f"(sig {failure.get('failure_signature')})"
        )
    return "\n".join(lines)


def _split_sections(region_body: str) -> dict[str, str]:
    """Corpo da região -> `{feature_id: texto da subseção}`, preservando ordem
    de inserção (dict do Python 3.7+). Texto fora de qualquer `### Tentativas
    — <id>` é descartado: a região inteira é gerada, nunca editada à mão."""
    sections: dict[str, str] = {}
    current: str | None = None
    buffer: list[str] = []
    for line in region_body.splitlines():
        stripped = line.strip()
        if stripped.startswith("### Tentativas — "):
            if current is not None:
                sections[current] = "\n".join(buffer).strip("\n")
            current = stripped[len("### Tentativas — "):].strip()
            buffer = [line]
        elif current is not None:
            buffer.append(line)
    if current is not None:
        sections[current] = "\n".join(buffer).strip("\n")
    return sections


def update_progress_attempts(
    target_dir: Path, feature_id: str, failures: list[dict[str, Any]]
) -> bool:
    """Sincroniza a subseção de `feature_id` na região gerenciada do
    `.harness/progress.md`. Retorna `True` se o arquivo foi reescrito.

    `failures` são as tentativas em aberto (ver `attempts.open_failures`):
    lista com itens -> a subseção é criada ou substituída; lista vazia -> a
    subseção é REMOVIDA, e a região some junto se ficar sem nenhuma. A remoção
    no verde é o ponto: a fatia deixou de estar "em andamento", o histórico
    permanente é o jsonl, e deixar o bloco faria a próxima sessão ler pendência
    onde existe prova.

    NO-OP silencioso (retorna `False`, nunca levanta) quando o arquivo não
    existe — mesma regra de `update_progress_status`/`append_progress_note`,
    e pelo mesmo motivo: quem chama é o `run_verify`, no meio de uma
    verificação, e sincronizar o rastro legível jamais pode ser o que faz uma
    verificação mudar de resultado.
    """
    progress_path = Path(target_dir) / PROGRESS_FILE
    if not progress_path.is_file():
        return False

    text = progress_path.read_text(encoding="utf-8")

    match = _ATTEMPTS_REGION_RE.search(text)
    if match:
        body = match.group(0)[len(ATTEMPTS_BEGIN):-len(ATTEMPTS_END)]
        sections = _split_sections(body)
    else:
        sections = {}

    if failures:
        sections[feature_id] = render_attempts_section(feature_id, failures)
    else:
        sections.pop(feature_id, None)

    if sections:
        region = "\n\n".join([ATTEMPTS_BEGIN, *sections.values(), ATTEMPTS_END])
    else:
        region = ""

    if match:
        updated = text[: match.start()] + region + text[match.end():]
        # Região removida: sobra o par de quebras que a cercava. Colapsa para
        # não acumular linha em branco a cada ciclo vermelho-verde.
        if not region:
            updated = updated.replace("\n\n\n\n", "\n\n").rstrip("\n") + "\n"
    else:
        if not region:
            return False
        updated = text.rstrip("\n") + "\n\n" + region + "\n"

    if updated == text:
        return False
    progress_path.write_text(updated, encoding="utf-8")
    return True


def render_init_scripts(profile: dict[str, Any]) -> tuple[str, str]:
    """Gera `(init_sh, init_ps1)` a partir do `repo-profile.json`: instalação
    de dependências (por `package_manager.value`) seguida do health check
    (`test_command.value`, se detectado). Mesmo conteúdo semântico nas duas
    linguagens.

    Os dois carregam `MANAGED_MARKER` logo no topo (linha 2 no `.sh`, depois
    do shebang; linha 1 no `.ps1`) — é o que `install_templates` usa para
    saber que pode regenerar o arquivo sem apagar edição do usuário."""
    package_manager_entry = profile.get("package_manager") or {}
    test_command = (profile.get("test_command") or {}).get("value")

    install_cmd = install_command_for(
        package_manager_entry.get("value"), package_manager_entry.get("evidence")
    )

    sh_lines = ["#!/usr/bin/env bash", MANAGED_MARKER, "set -e", ""]
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

    ps1_lines = [MANAGED_MARKER, "$ErrorActionPreference = 'Stop'", ""]
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
    `.harness/progress.md` já gravado. `None` se a linha não existir — cobre
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


def _drop_stale_auto_entries(section: str, target_dir: Path) -> str:
    """Filtra, dentro do bloco `harness:auto` de `section`, as entradas cujo
    caminho de evidência citado não existe mais em disco (Onda 2/T-05).

    Chamado só na troca de contrato (`install_templates`): a seção inteira
    de `## Última atualização` é copiada para o `progress.md` novo, e sem
    esse filtro uma nota automática de um contrato que não é mais o ativo
    sobrevive como se fosse atual — o que o achado #6 do laudo de
    simplificação observou como "paths de evidência inexistentes e features
    fantasma injetados". Prosa humana fora do bloco `harness:auto` nunca é
    tocada aqui."""
    begin = section.find(_AUTO_NOTE_BEGIN)
    end = section.find(_AUTO_NOTE_END)
    if begin == -1 or end == -1 or end <= begin:
        return section

    kept = [
        line for line in section[begin + len(_AUTO_NOTE_BEGIN):end].splitlines()
        if line.strip().startswith("- ") and _auto_entry_evidence_exists(line, target_dir)
    ]
    block = _AUTO_NOTE_BEGIN + "\n" + ("\n".join(kept) + "\n" if kept else "")
    return section[:begin] + block + section[end:]


def is_managed_init_script(path: Path) -> bool:
    """True se `path` é um `init.*` GERADO por este módulo (carrega
    `MANAGED_MARKER`). Arquivo ausente conta como gerenciado — não há nada do
    usuário para preservar, e o caminho normal é criá-lo. Arquivo ilegível
    conta como NÃO gerenciado: na dúvida, preservar."""
    if not path.is_file():
        return True
    try:
        return MANAGED_MARKER in path.read_text(encoding="utf-8")
    except OSError:
        return False


def manual_init_scripts(target_dir: Path) -> list[Path]:
    """Os `init.*` de `target_dir` que existem SEM `MANAGED_MARKER` — foram
    editados à mão e `install_templates` não os sobrescreve. Existe para o
    CLI conseguir dizer ao usuário quais scripts ficaram fora da
    regeneração; preservar em silêncio deixaria um `init.*` desatualizado em
    relação ao profile sem sinal nenhum."""
    target_dir = target_dir.resolve()
    return [
        path
        for path in (target_dir / INIT_SH_FILE, target_dir / INIT_PS1_FILE)
        if path.is_file() and not is_managed_init_script(path)
    ]


def install_templates(
    target_dir: Path, feature_list: dict[str, Any], profile: dict[str, Any]
) -> list[Path]:
    """Grava `.harness/progress.md`, `.harness/init.sh` e `.harness/init.ps1`.

    `.harness/progress.md` é RUNTIME-MUTÁVEL: por padrão só é gravado se ainda
    não existir (recompilar nunca apaga progresso já registrado pelo
    agente). Exceção (achado A do dogfood 2026-07-22): se o arquivo já
    existente tem um header `Contrato: \\`slug\\`` reconhecível e esse slug
    diverge do `contract` do `feature_list` recém-compilado, o arquivo é
    RESTAURADO para o novo contrato — senão o agente lê passos/features de
    um contrato que não é mais o ativo. A seção `## Última atualização`
    (notas livres do agente) é sempre preservada nesse caso. Conteúdo sem
    header reconhecível (customizado manualmente, sem `Contrato: \\`...\\``)
    nunca é tocado — comportamento pré-existente mantido.

    `init.sh`/`init.ps1` são determinísticos e regenerados com o profile mais
    recente, EXCETO quando o arquivo em disco não tem `MANAGED_MARKER`: aí ele
    é do usuário e fica intacto (item 5 do backlog do laudo de footprint).
    Quem quiser voltar ao script gerado apaga o arquivo e recompila.

    Retorna a lista de paths escritos NESTA chamada — o que foi preservado
    (progresso já existente, `init.*` editado à mão) não entra na lista.
    `manual_init_scripts` é o complemento: diz o que ficou de fora e por quê.
    """
    target_dir = target_dir.resolve()
    (target_dir / HARNESS_DIR).mkdir(parents=True, exist_ok=True)

    written: list[Path] = []

    progress_path = target_dir / PROGRESS_FILE
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
                last_update = _drop_stale_auto_entries(last_update, target_dir)
                heading_idx = new_content.find(_LAST_UPDATE_HEADING)
                new_content = new_content[:heading_idx] + last_update
            progress_path.write_text(new_content, encoding="utf-8")
            written.append(progress_path)

    init_sh, init_ps1 = render_init_scripts(profile)

    for relative, content in ((INIT_SH_FILE, init_sh), (INIT_PS1_FILE, init_ps1)):
        path = target_dir / relative
        if not is_managed_init_script(path):
            continue
        path.write_text(content, encoding="utf-8")
        written.append(path)

    # Os outros dois registros da spine (§5.2/§5.3). Criados só se ausentes, e
    # NUNCA regenerados: a vida deles é o projeto, não a demanda — regenerar a
    # cada contrato novo apagaria a razão de escolhas tomadas em demandas
    # anteriores, que é justamente o que eles existem para guardar. Nascem aqui
    # porque o `boundary_guard` proíbe escrita direta em `.harness/**`: sem o
    # esqueleto, o primeiro `harness decide` criaria um arquivo sem cabeçalho e
    # nada diria ao leitor que ele é append-only.
    for relative, header in (
        (DECISIONS_FILE, DECISIONS_HEADER),
        (LESSONS_FILE, LESSONS_HEADER),
    ):
        path = target_dir / relative
        if path.is_file():
            continue
        path.write_text(header, encoding="utf-8")
        written.append(path)

    return written


# ---------------------------------------------------------------------------
# update_progress_status (US-2 — sincronização automática)
# ---------------------------------------------------------------------------

def update_progress_status(target_dir: Path, feature_id: str, status: str) -> bool:
    """Reescreve a coluna de status da linha de `feature_id` na tabela do
    `.harness/progress.md` de `target_dir` para `status`.

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
    progress_path = target_dir / PROGRESS_FILE
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


def render_last_update_note(
    text: str, note: str, feature_id: str | None = None
) -> str | None:
    """`text` do `progress.md` com `note` acrescentada ao bloco automático da
    seção `## Última atualização`. `None` se o heading não existir.

    Puro (não toca disco) para o comportamento ser testável sem fixture de
    arquivo — mesma divisão de `render_progress_template`.

    - Bloco já presente: acrescenta a entrada e trunca em
      `_AUTO_NOTE_MAX_ENTRIES`, mantendo as mais recentes.
    - `feature_id` (Onda 2/T-05): se passado, qualquer entrada anterior que
      cite esse mesmo id é removida antes de acrescentar a nova — reverificar
      a MESMA feature substitui a nota antiga em vez de somar outra
      (44% do teto de 10 entradas era repetição da mesma feature, achado #6
      do laudo de simplificação 2026-07-30). `None` (default) preserva o
      comportamento antigo de puro acúmulo.
    - Bloco ausente: insere logo abaixo do heading, ANTES do texto que já
      estiver lá. O placeholder `_(vazio — ...)_` e qualquer prosa do agente
      seguem intactos embaixo — este bloco nunca reescreve o que não é dele.
    - Heading ausente (agente reescreveu o arquivo à mão): `None`, e o
      chamador não escreve nada. Fabricar a estrutura de volta seria impor um
      formato a um arquivo declaradamente runtime-mutável.
    """
    if _LAST_UPDATE_HEADING not in text:
        return None

    entry = f"- {note}"
    begin = text.find(_AUTO_NOTE_BEGIN)
    end = text.find(_AUTO_NOTE_END)

    if begin != -1 and end > begin:
        previous = [
            line for line in text[begin + len(_AUTO_NOTE_BEGIN):end].splitlines()
            if line.strip().startswith("- ")
            and not (feature_id and f" {feature_id} " in line)
        ]
        entries = (previous + [entry])[-_AUTO_NOTE_MAX_ENTRIES:]
        block = _AUTO_NOTE_BEGIN + "\n" + "\n".join(entries) + "\n"
        return text[:begin] + block + text[end:]

    insert_at = text.find(_LAST_UPDATE_HEADING) + len(_LAST_UPDATE_HEADING)
    block = f"\n\n{_AUTO_NOTE_BEGIN}\n{entry}\n{_AUTO_NOTE_END}\n"
    return text[:insert_at] + block + text[insert_at:]


def append_progress_note(
    target_dir: Path, note: str, feature_id: str | None = None
) -> bool:
    """Acrescenta `note` ao bloco automático de `## Última atualização` do
    `.harness/progress.md` de `target_dir`. `True` se o arquivo foi reescrito.

    Chamada por `harness.verify.run_verify` a cada prova gravada, passando
    `feature_id` para dedupe (ver `render_last_update_note`). NO-OP silencioso
    (retorna `False`, nunca levanta) quando o arquivo não existe ou não tem o
    heading — mesma regra de `update_progress_status`: sincronizar o rastro
    legível jamais pode ser motivo de uma verificação falhar.
    """
    progress_path = Path(target_dir) / PROGRESS_FILE
    if not progress_path.is_file():
        return False

    text = progress_path.read_text(encoding="utf-8")
    updated = render_last_update_note(text, note, feature_id)
    if updated is None or updated == text:
        return False

    progress_path.write_text(updated, encoding="utf-8")
    return True
