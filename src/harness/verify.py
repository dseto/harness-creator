"""Verificação: `verify_cmd` de uma feature -> evidência executável.

Fecha o passo 11 do lifecycle (Fase 2/3): uma feature só é considerada
"provada" se o `verify_cmd` declarado em `.harness/feature_list.json` rodou
de verdade e saiu com exit code 0. Este módulo NÃO decide bloqueio de
edição sobre `feature_list.json` (outro escopo) nem ordena por `depends[]`
(idem) — apenas executa o comando de UMA feature e, em caso de sucesso,
grava a prova em `.harness/evidence/<contrato>/<feature_id>.json`.

`mark_feature_passed` é a exceção a essa regra: roda depois de `run_verify`
ter tido sucesso e grava `passes: true` na feature em `feature_list.json`.
Desde a v0.23.0 é o comportamento PADRÃO do `harness verify` (antes era
opt-in via `--mark-passed`); `--no-mark-passed` volta ao antigo. Sem lock
entre processos; ver docstring da função para a ressalva de concorrência.

Campo opcional `cwd` da feature (ver `contract.py`): diretório relativo a
`target_dir` onde `verify_cmd` roda via subprocess — existe para monorepo
(`backend/`+`frontend/`), onde um comando como `ng test` só resolve o
binário de dentro do workspace do frontend. Afeta SÓ o `cwd` do
subprocess; `target_dir` (resolução de `feature_list.json` e
`compute_files_hash`) nunca muda.

Schema exato da evidência (outras tarefas do ROADMAP dependem deste
formato — não mudar sem atualizar consumidores):

    {
      "feature_id": "T-01",
      "contract": "meu-contrato",
      "verify_cmd": "pytest tests/test_x.py -q",
      "recorded_at": "2026-07-16T12:00:00+00:00",
      "exit_code": 0,
      "files_hash": "sha256:<hex>"
    }

`files_hash` é o SHA-256 do conteúdo atual dos `files[]` da feature,
concatenados em ordem determinística (`sorted(files)`). Serve para uma
tarefa futura detectar evidência desatualizada (arquivo mudou depois da
verificação) sem precisar reimplementar o hash — por isso
`compute_files_hash` é exposta como função pública de módulo.

Rastro de tentativas (`harness.attempts`, incremento 1 do design de loop
engineering): além da evidência, TODA passada — verde ou vermelha — deixa uma
linha em `.harness/attempts/<contrato>/<id>.jsonl`. A regra antiga "exit code
!= 0 -> NADA é gravado em disco" valia para EVIDÊNCIA e continua valendo: o
vermelho segue sem prova. O que passa a ser gravado no vermelho é o oposto de
uma prova — o registro de que a fatia falhou, com o erro cru — sem o qual o
disjuntor de `harness budget` não teria o que contar e a regra do padrão
repetido só existiria como prosa no passo 10 do lifecycle. Gravar o rastro
NUNCA muda o resultado da verificação (mesma regra do sync do `progress.md`).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TextIO

from harness.attempts import (
    CLASSIFICATION_STRUCTURAL,
    CLASSIFICATION_TRANSIENT,
    classify_failure,
    extract_failure_line,
    open_failures,
    read_attempts,
    record_failure,
    record_pass,
)
from harness.boundary_guard import is_floor_bash_command
from harness.branching import is_git_repository
from harness.contract import FEATURE_LIST_FILE
from harness.convergence import ConvergenceError, parse_metric_value, record_measurement
from harness.skips import (
    actionable_skip_violation,
    format_skip_summary,
    load_allowed_skips,
    parse_skips,
    read_baseline,
    skip_delta_violation,
    without_liberated_actionable_skips,
)
from harness.templates import (
    append_progress_note,
    update_progress_attempts,
    update_progress_status,
)

EVIDENCE_DIR = ".harness/evidence"
_VERIFY_TIMEOUT_SECONDS = 600

#: Teto de itens da lista de skips gravada em evidência (T-06) — não de
#: caracteres, como o console (`skips.format_skip_summary`): a evidência é
#: JSON estruturado, cada item já é curto por natureza (nodeid + reason).
#: Vinte cabe qualquer skip legítimo real (a suíte deste repositório tem 2);
#: acima disso o campo `truncated` avisa em vez de crescer sem teto.
_EVIDENCE_SKIPS_MAX_ITEMS = 20

#: §8.1: "retry direto, com limite próprio (2-3)". 3 tentativas NO TOTAL
#: (a primeira + 2 retries) — o mesmo número que a regra do padrão repetido
#: (§8.2) usa para "insistir não adianta mais", por consistência de leitura.
#: Cobre só o caminho de exit code != 0 (processo terminou, saiu com erro
#: transiente reconhecível) — o timeout do PRÓPRIO processo do `verify_cmd`
#: (`_VERIFY_TIMEOUT_SECONDS`) fica de fora por desenho: reexecutar
#: automaticamente um comando que já levou minutos para estourar, até 3×,
#: prenderia a sessão em silêncio por muito mais tempo do que o "backoff
#: simples" do §8.1 tem em mente (ver Não-objetivos do spec.md do contrato
#: `falha-transiente-e-escalada`).
_TRANSIENT_RETRY_LIMIT = 3

#: Backoff simples entre tentativas transientes — índice 0 é a pausa ANTES da
#: 2ª tentativa, índice 1 antes da 3ª. Curto de propósito: é retry de "a rede
#: caiu por um instante", não uma espera longa.
_TRANSIENT_BACKOFF_SECONDS = (1, 2)

#: Subdiretório usado quando o `feature_list.json` não declara `contract`
#: (contrato compilado por versão antiga, ou fixture de teste). Nome inválido
#: como slug de contrato de propósito: nunca colide com um contrato real.
UNSCOPED_EVIDENCE_DIR = "_sem-contrato"


def evidence_path(target_dir: Path, contract: Any, feature_id: str) -> Path:
    """`.harness/evidence/<contrato>/<feature_id>.json`.

    A evidência morava em `.harness/evidence/<feature_id>.json`, sem o
    contrato em lugar nenhum — nem no caminho, nem no schema. Como TODO
    contrato começa em `T-01`, a colisão era por construção: compilar um
    contrato novo e rodar `harness verify T-01` **sobrescrevia em silêncio a
    prova do contrato anterior**, sem aviso e sem backup. Prova executável é a
    garantia central do produto; ela não pode ser destruída por um contrato
    que nem sabe da existência do outro.

    O caminho escopado resolve a destruição. A identidade — impedir que a
    evidência de um contrato destrave `passes:true` em outro — é o campo
    `contract` gravado dentro do JSON e conferido por quem lê
    (`boundary_guard`, `runtime_audit`, `stop_hook`). Antes, o que segurava
    isso era só o frescor contra o último commit: defesa TEMPORAL, que depende
    de existir um commit entre os dois contratos.
    """
    slug = str(contract or "").strip() or UNSCOPED_EVIDENCE_DIR
    return Path(target_dir) / EVIDENCE_DIR / slug / f"{feature_id}.json"


# Item 7 do backlog issue #1 — detecção-only de "arquivo em uso" (sem
# auto-kill). Padrão casa as duas mensagens de erro do MSBuild (.NET) que
# apareceram ~6x na sessão real (MSB3027 = falha ao COPIAR o binário de
# saída; MSB3021 = falha ao GERAR/vincular o binário porque outro processo
# o mantém aberto) mais os equivalentes textuais Node/POSIX (`EBUSY`,
# `text file busy`) e a variante Win32 (`ERROR_SHARING_VIOLATION`, "being
# used by another process" — a frase literal que MSB3021/3027 imprimem).
# Case-insensitive: saída de build pode vir com capitalização variável
# dependendo do locale do MSBuild.
_FILE_LOCK_PATTERN = re.compile(
    r"MSB3027|MSB3021|\bEBUSY\b|text file busy|ERROR_SHARING_VIOLATION|"
    r"being used by another process",
    re.IGNORECASE,
)

# Extração de PID é best-effort: MSB3027/MSB3021 normalmente NÃO citam o
# PID do processo que segura o lock (a mensagem do Win32
# ERROR_SHARING_VIOLATION traduzida pelo MSBuild não inclui o processo
# ofensor). Estes padrões só capturam os formatos em que algum PID
# aparece explicitamente na saída (ex.: uma ferramenta upstream que
# anexa "pid: 1234" à mensagem). Sem match -> None, e a mensagem aponta
# só a causa provável, sem inventar PID.
_PID_PATTERNS = (
    re.compile(r"process\s+id\s*[:#]?\s*(\d+)", re.IGNORECASE),
    re.compile(r"\(pid\s*[:=]?\s*(\d+)\)", re.IGNORECASE),
    re.compile(r"\bpid\s*[:=]\s*(\d+)\b", re.IGNORECASE),
)


def detect_file_lock_hint(stdout: str, stderr: str) -> str | None:
    """Detecta, na saída (stdout+stderr) de um `verify_cmd` que falhou, o
    padrão de "arquivo/processo em uso" (lock) típico de build .NET
    (MSBuild) ou Node/POSIX — DETECÇÃO-ONLY, item 7 do backlog issue #1.

    Retorna `None` se nenhum padrão de `_FILE_LOCK_PATTERN` casar — em
    particular, uma falha de teste NORMAL (assert, "N testes falharam")
    não contém nenhum desses tokens e por isso não gera mensagem (sem
    falso-positivo). Se casar, retorna uma string com a causa provável
    (processo do próprio projeto-alvo, ex.: `dotnet run`/`npm start`,
    rodando em paralelo e segurando o binário) e, SE um PID aparecer na
    saída num formato reconhecível, o PID — nunca inventado.

    REGRA DURA (rejeitada explicitamente no backlog): esta função só
    monta uma mensagem. Ela NUNCA mata processo, nunca lista processos
    (tasklist/Get-Process), nunca sugere comando de kill. Auto-kill foi
    avaliado e descartado (risco de matar o processo errado > benefício).
    """
    combined = f"{stdout}\n{stderr}"
    if not _FILE_LOCK_PATTERN.search(combined):
        return None

    pid = None
    for pattern in _PID_PATTERNS:
        match = pattern.search(combined)
        if match:
            pid = match.group(1)
            break

    hint = (
        "verify_cmd falhou com um padrão de arquivo/processo em uso (lock) "
        "-- causa provável: um processo do próprio projeto-alvo (ex.: "
        "`dotnet run`, `npm start`) rodando em paralelo e segurando o "
        "executável/dll de saída. Este harness NÃO mata processos "
        "automaticamente -- fechar manualmente o processo de dev antes de "
        "rodar o verify_cmd de novo costuma resolver."
    )
    if pid:
        hint += f" PID aparente na saída do build: {pid}."
    return hint


class VerifyError(Exception):
    """Erro antes mesmo de rodar o `verify_cmd` (feature/contrato ausente)."""


class VerifyFailedError(Exception):
    """`verify_cmd` rodou mas saiu com exit code != 0 — evidência NÃO gravada.

    `file_lock_hint` (item 7 do backlog issue #1): populado automaticamente
    via `detect_file_lock_hint(stdout, stderr)` — `None` no caso comum
    (falha de teste normal), ou uma string acionável quando a saída casa
    um padrão de arquivo em uso (MSB3027/MSB3021/EBUSY/"text file busy").
    Campo puramente ADITIVO: `feature_id`/`exit_code`/`stdout`/`stderr`
    continuam com o mesmo contrato de sempre, então qualquer consumidor
    existente de `run_verify` que só lê esses quatro campos não quebra.
    Escolha deliberada: a detecção entra aqui (não só no print do
    `cli.py`) para que QUALQUER consumidor de `run_verify` — não só o
    dispatch do comando `verify` — enxergue o sinal.
    """

    def __init__(self, feature_id: str, exit_code: int, stdout: str, stderr: str) -> None:
        super().__init__(
            f"verify_cmd da feature {feature_id} falhou com exit code {exit_code}"
        )
        self.feature_id = feature_id
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.file_lock_hint = detect_file_lock_hint(stdout, stderr)


def _kill_process_tree(proc: subprocess.Popen) -> None:
    """Mata a árvore de processos de `proc` — BEST-EFFORT, não garantia.

    Windows: `taskkill /T /F /PID` caminha a árvore por parent-PID; se um
    intermediário (ex.: o `cmd.exe` do `shell=True`) já morreu, netos
    reparentados NÃO são encontrados — eliminar isso de verdade exigiria
    Job Object (ctypes/pywin32), custo descartado por ora. POSIX:
    `os.killpg` sobre o grupo criado por `start_new_session=True` (esse é
    airtight para o grupo). Em ambos, cai para `proc.kill()` como última
    linha. Nunca levanta — usada em caminhos de erro/interrupção."""
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                capture_output=True,
            )
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.kill()
    except OSError:
        pass


def _pump_pipe(pipe: TextIO, parts: list[str], mirror: TextIO | None) -> None:
    """Thread leitora: drena `pipe` linha a linha para `parts` (buffer) e,
    se `mirror` não for None, espelha em tempo real (tee). O buffer é
    OBRIGATÓRIO mesmo com mirror: `VerifyFailedError` carrega stdout/stderr
    e alimenta `detect_file_lock_hint`. Engole erros de I/O — se o pipe
    morrer junto com o processo, a thread só termina."""
    try:
        for line in iter(pipe.readline, ""):
            parts.append(line)
            if mirror is not None:
                mirror.write(line)
                mirror.flush()
    except (OSError, ValueError):
        pass
    finally:
        try:
            pipe.close()
        except OSError:
            pass


def _run_verify_cmd(
    verify_cmd: str, cwd: Path, timeout_seconds: int, stream: bool
) -> tuple[int, str, str]:
    """Executa `verify_cmd` via Popen com gestão de árvore de processos —
    correção do issue 4 do dogfood venv-Windows (no Windows, o kill do
    `subprocess.run(timeout=...)` atingia só o `cmd.exe` filho direto;
    `pytest.exe`→`python.exe` ficavam órfãos e o `communicate()` bloqueava
    até eles morrerem, fazendo run lento parecer travado).

    - Filho em grupo/sessão própria: `CREATE_NEW_PROCESS_GROUP` no Windows
      (também isola do Ctrl+C do console — quem mata a árvore de forma
      ordenada é o handler daqui, não o sinal do terminal),
      `start_new_session=True` no POSIX.
    - Timeout E interrupção (KeyboardInterrupt etc.) matam a ÁRVORE via
      `_kill_process_tree` — nunca só o filho direto. Best-effort no
      Windows (ver docstring de `_kill_process_tree`).
    - `stream=True` faz tee do stdout/stderr para o console em tempo real
      (humano distingue lento de travado). Default False: com streaming
      incondicional, toda a saída da suíte entraria no contexto do agente
      a cada verify verde — anti-objetivo (economia de contexto).
    - Threads leitoras são daemon com `join` COM timeout: se o taskkill
      perder um neto que segura o handle do pipe, o join não trava o
      verify de novo (seria reintroduzir o sintoma original).

    Devolve `(returncode, stdout, stderr)`; propaga `TimeoutExpired` após
    matar a árvore.
    """
    popen_kwargs: dict[str, Any] = {}
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True

    proc = subprocess.Popen(
        verify_cmd,
        shell=True,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
        **popen_kwargs,
    )
    out_parts: list[str] = []
    err_parts: list[str] = []
    threads = (
        threading.Thread(
            target=_pump_pipe,
            args=(proc.stdout, out_parts, sys.stdout if stream else None),
            daemon=True,
        ),
        threading.Thread(
            target=_pump_pipe,
            args=(proc.stderr, err_parts, sys.stderr if stream else None),
            daemon=True,
        ),
    )
    for t in threads:
        t.start()
    try:
        returncode = proc.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        raise
    except BaseException:
        # KeyboardInterrupt/SystemExit: com CREATE_NEW_PROCESS_GROUP o filho
        # não recebe o Ctrl+C do console — sem este handler, interromper o
        # verify manualmente criaria exatamente o órfão que o issue relata.
        _kill_process_tree(proc)
        raise
    finally:
        for t in threads:
            t.join(timeout=5)
    return returncode, "".join(out_parts), "".join(err_parts)


def normalize_command_head(command: str) -> str:
    """No Windows, troca `/` por `\\` SÓ no primeiro token de `command`.

    Item 1 do backlog do dogfood miojo. O `boundary_guard` reconhece
    `.venv/Scripts/pytest.exe` como forma equivalente ao binário nu — e o
    `preflight` recomenda exatamente essa forma. Mas o guard só precisa CASAR
    o texto; quem EXECUTA é este módulo, via `shell=True`, que no Windows
    passa pelo `cmd.exe` — e o `cmd.exe` corta o token no primeiro `/`
    (delimitador de switch), respondendo `'.venv' não é reconhecido como um
    comando interno ou externo`. A mesma string, portanto, passava no guard e
    falhava na execução: o preflight recomendava uma forma que só funcionava
    em metade dos caminhos.

    **Só o head, nunca a string inteira.** Um replace global mangelaria
    argumento legítimo com `/`: regex (`-k 'a/b'`), URL, `--cov=src/harness`,
    caminho de teste em forma POSIX que o próprio `cmd.exe` aceita quando é
    ARGUMENTO (o corte por `/` só vale para o token do comando). O head é o
    único ponto onde a barra quebra.

    No-op fora do Windows, no-op quando o head não tem `/`, e no-op quando o
    head vem entre aspas (aí o `cmd.exe` já trata o caminho inteiro como um
    token só, e reescrever poderia romper um quoting deliberado).
    """
    if sys.platform != "win32":
        return command
    stripped = command.lstrip()
    if not stripped or stripped[0] in ("\"", "'"):
        return command
    head = re.match(r"\S+", stripped).group(0)
    if "/" not in head:
        return command
    leading = command[: len(command) - len(stripped)]
    return leading + head.replace("/", "\\") + stripped[len(head):]


def compute_files_hash(files: list[str], target_dir: Path) -> str:
    """SHA-256 determinístico do conteúdo atual de `files` (relativos a `target_dir`).

    Concatena, em ordem `sorted(files)`, para cada caminho: o próprio
    caminho relativo + "\n" + os bytes do arquivo + "\n". Arquivo ausente em
    disco não levanta exceção — usa o literal `b"<missing>\n"` no lugar do
    conteúdo. Retorna a string prefixada `"sha256:<hex>"`.
    """
    digest = hashlib.sha256()
    for rel_path in sorted(files):
        digest.update(rel_path.encode("utf-8"))
        digest.update(b"\n")
        file_path = target_dir / rel_path
        if file_path.is_file():
            digest.update(file_path.read_bytes())
        else:
            digest.update(b"<missing>\n")
        digest.update(b"\n")
    return f"sha256:{digest.hexdigest()}"


def _current_git_state(target_dir: Path) -> tuple[str | None, bool]:
    """`(commit, dirty)` do HEAD atual — best-effort, nunca levanta. Mesma
    postura só-leitura de `escalation._spine_state`; `dirty` usa
    `git status --porcelain -uno` (tracked, mesmo escopo do resto do
    harness — ver `branching.py`)."""
    if not is_git_repository(target_dir):
        return None, False
    try:
        commit_proc = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=target_dir, capture_output=True, text=True,
        )
        status_proc = subprocess.run(
            ["git", "status", "--porcelain", "-uno"], cwd=target_dir, capture_output=True, text=True,
        )
    except OSError:
        return None, False
    commit = commit_proc.stdout.strip() if commit_proc.returncode == 0 else None
    dirty = bool(status_proc.stdout.strip()) if status_proc.returncode == 0 else False
    return commit, dirty


def _record_metric(
    target_dir: Path,
    feature: dict[str, Any],
    feature_cwd: Path,
    feature_id: str,
    contract: str,
    timeout_seconds: int,
) -> None:
    """Roda `metric_cmd` (se a tarefa declarou um) depois do `verify_cmd` —
    passe ou falhe — e grava a medição no rastro de trajetória (§4.3, T-02).

    Nunca levanta: falha de `metric_cmd` (comando quebrado, floor, saída não
    numérica) é visível em stderr, mas não pode derrubar o resultado do
    `verify_cmd`, que é o único que decide `passes`. Sem `metric_cmd`
    declarado, no-op silencioso — nenhum arquivo de métrica é criado.
    """
    metric_cmd = feature.get("metric_cmd")
    if not metric_cmd:
        return
    if is_floor_bash_command(metric_cmd):
        print(
            f"metric_cmd de '{feature_id}' bate no runtime floor "
            "(push/rede/publicacao) — nunca executado, medição pulada",
            file=sys.stderr,
        )
        return
    try:
        exec_metric_cmd = normalize_command_head(metric_cmd)
        returncode, stdout, stderr = _run_verify_cmd(
            exec_metric_cmd, feature_cwd, timeout_seconds, False
        )
        if returncode != 0:
            tail = (stderr or stdout).strip()[:200]
            print(
                f"metric_cmd de '{feature_id}' saiu com exit code {returncode} "
                f"— medição pulada ({tail or 'sem saída'})",
                file=sys.stderr,
            )
            return
        value = parse_metric_value(stdout)
        commit, dirty = _current_git_state(target_dir)
        record_measurement(
            target_dir,
            contract,
            feature_id,
            value=value,
            commit=commit,
            dirty=dirty,
            recorded_at=datetime.now(timezone.utc).isoformat(),
        )
    except ConvergenceError as exc:
        print(f"metric_cmd de '{feature_id}': {exc} — medição pulada", file=sys.stderr)
    except Exception:
        pass


def _load_feature(target_dir: Path, feature_id: str) -> tuple[dict[str, Any], str]:
    """`(feature, contrato)`. O contrato sai junto porque a evidência é
    escopada por ele — ver `evidence_path`."""
    feature_list_path = target_dir / FEATURE_LIST_FILE
    if not feature_list_path.is_file():
        raise VerifyError(f"{feature_list_path}: feature_list.json não encontrado")

    try:
        data = json.loads(feature_list_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise VerifyError(f"{feature_list_path}: JSON inválido — {exc}") from exc

    contract = str(data.get("contract") or "")
    for feature in data.get("features", []):
        if feature.get("id") == feature_id:
            return feature, contract

    raise VerifyError(f"feature '{feature_id}' não encontrada em {feature_list_path}")


def _report_skips(feature_id: str, stdout: str, stderr: str) -> None:
    """Imprime o resumo de skips desta passada em stderr — SEMPRE, verde ou
    vermelho, sem flag (T-02 do contrato `skips-nunca-silenciosos`). Motivo
    de existir: `run_verify` decidia o resultado só pelo exit code, e
    pytest/dotnet test/jest saem 0 mesmo com dezenas de testes pulados; a
    prova gravada sobre uma suíte assim ficava indistinguível de uma suíte
    inteira. `None` de `format_skip_summary` (nada a dizer) não imprime
    nada — silêncio é o resultado certo quando não há skip.
    """
    message = format_skip_summary(parse_skips(stdout, stderr))
    if message:
        print(f"verify_cmd de '{feature_id}': {message}", file=sys.stderr)


def run_verify(
    target_dir: Path,
    feature_id: str,
    *,
    timeout_seconds: int = _VERIFY_TIMEOUT_SECONDS,
    stream: bool = False,
    sleep: Callable[[float], None] = time.sleep,
) -> Path:
    """Roda o `verify_cmd` da feature `feature_id` e, se exit code == 0, grava evidência.

    Levanta `VerifyError` se a feature ou o `feature_list.json` não existirem.
    Levanta `VerifyFailedError` (carregando stdout/stderr/exit_code) se o
    `verify_cmd` sair com código != 0 — NADA é gravado em disco nesse caso.
    Retorna o Path do arquivo de evidência gravado em caso de sucesso.

    Efeito aditivo (US-2): em caso de sucesso, além de gravar a evidência,
    sincroniza a linha da feature no `.harness/progress.md` para `done` via
    `templates.update_progress_status` — no-op silencioso se o arquivo não
    existir, então nunca faz a verificação falhar por causa disso.

    `timeout_seconds` (CLI `--timeout`): o default de 600s matava
    verify_cmds legítimos encadeados (~1100s no dogfood do issue 4) — agora
    configurável por chamada, sem mudar o default. `stream` (CLI
    `--stream`): tee do stdout/stderr em tempo real, opt-in — ver
    `_run_verify_cmd` para o porquê de NÃO ser default.

    Retry transiente (§8.1, contrato `falha-transiente-e-escalada`): quando o
    `verify_cmd` roda até o fim e sai com código != 0 numa mensagem
    reconhecidamente transiente (`attempts.classify_failure`), a passada
    tenta de novo sozinha — até `_TRANSIENT_RETRY_LIMIT` tentativas no total,
    com `_TRANSIENT_BACKOFF_SECONDS` de pausa entre elas — SEM gravar nada no
    rastro enquanto ainda houver tentativa sobrando: "não conta como
    tentativa de correção, nada foi corrigido, só repetido". Só a última
    tentativa (a que sucede, ou a que esgota o limite ainda transiente) tem
    efeito observável. `sleep` é injetável para teste (nunca dorme de
    verdade fora de produção); falha ESTRUTURAL nunca entra nesse laço — vai
    direto para o registro de sempre, no primeiro exit code != 0.
    """
    target_dir = target_dir.resolve()
    feature, contract = _load_feature(target_dir, feature_id)
    verify_cmd = feature["verify_cmd"]
    files = feature.get("files", [])

    if is_floor_bash_command(verify_cmd):
        raise VerifyError(
            f"feature '{feature_id}': verify_cmd '{verify_cmd}' bate no "
            "runtime floor (push/rede/publicacao) — nunca executado, "
            "mesmo vindo de um contrato compilado"
        )

    verify_cwd = target_dir
    feature_cwd = feature.get("cwd")
    if feature_cwd:
        verify_cwd = target_dir / feature_cwd
        if not verify_cwd.is_dir():
            raise VerifyError(
                f"feature '{feature_id}': cwd '{feature_cwd}' não existe em {target_dir}"
            )

    # O texto do contrato é preservado intacto (é ele que vai para a
    # evidência e para as mensagens de erro); o que roda é a forma executável
    # — ver `normalize_command_head` para o porquê de só o head mudar.
    exec_cmd = normalize_command_head(verify_cmd)

    attempt = 0
    while True:
        attempt += 1
        try:
            returncode, stdout, stderr = _run_verify_cmd(
                exec_cmd, verify_cwd, timeout_seconds, stream
            )
        except subprocess.TimeoutExpired as exc:
            # Timeout do PRÓPRIO processo fica fora do retry (ver docstring):
            # comando que já estourou o teto não é reexecutado automaticamente.
            raise VerifyError(
                f"feature '{feature_id}': verify_cmd '{verify_cmd}' excedeu o "
                f"timeout de {timeout_seconds}s — árvore de processos encerrada "
                "(taskkill /T no Windows, killpg no POSIX; best-effort). Suíte "
                "legitimamente mais lenta que isso? use --timeout <segundos>"
            ) from exc

        if returncode == 0:
            _report_skips(feature_id, stdout, stderr)
            report = parse_skips(stdout, stderr)
            allowed_skips = load_allowed_skips(target_dir)

            infra_violation = actionable_skip_violation(report, allowed_skips)
            if infra_violation is not None:
                # INFRA (§8.3): falta algo do lado de fora do código, não
                # código quebrado. Nunca entra no rastro de tentativas — a
                # mesma razão pela qual `verify_cmd` no runtime floor (acima)
                # também levanta `VerifyError` sem tocar `record_failure`:
                # loop não conserta a própria jaula, e "tentar de novo" não
                # resolve env var ausente.
                raise VerifyError(f"feature '{feature_id}': {infra_violation}")

            skip_violation = skip_delta_violation(
                without_liberated_actionable_skips(report, allowed_skips),
                read_baseline(target_dir, contract, feature_id),
            )
            if skip_violation is None:
                break

            # Skip novo fora do baseline: o processo saiu 0, mas a política
            # trata como falha estrutural — mesmo caminho do vermelho de
            # hoje (nada em .harness/evidence/, tentativa registrada, exceção
            # levantada). `exit_code=1` na tentativa e na exceção porque o 0
            # real do processo mentiria sobre o veredito para quem lê depois.
            print(f"verify_cmd de '{feature_id}': BLOQUEADO — {skip_violation}", file=sys.stderr)
            try:
                record_failure(
                    target_dir,
                    contract,
                    feature_id,
                    verify_cmd=verify_cmd,
                    exit_code=1,
                    stdout=stdout,
                    stderr=stderr,
                    files_hash=compute_files_hash(files, target_dir),
                    recorded_at=datetime.now(timezone.utc).isoformat(),
                    classification=CLASSIFICATION_STRUCTURAL,
                )
                update_progress_attempts(
                    target_dir,
                    feature_id,
                    open_failures(read_attempts(target_dir, contract, feature_id)),
                )
            except Exception:
                pass
            _record_metric(target_dir, feature, verify_cwd, feature_id, contract, timeout_seconds)
            raise VerifyFailedError(feature_id, 1, stdout, stderr)

        failure_line = extract_failure_line(stdout, stderr)
        classification = classify_failure(failure_line)
        if classification == CLASSIFICATION_TRANSIENT and attempt < _TRANSIENT_RETRY_LIMIT:
            backoff = _TRANSIENT_BACKOFF_SECONDS[
                min(attempt - 1, len(_TRANSIENT_BACKOFF_SECONDS) - 1)
            ]
            print(
                f"verify_cmd de '{feature_id}' falhou com sinal transiente "
                f"(tentativa {attempt}/{_TRANSIENT_RETRY_LIMIT}): "
                f"{failure_line or '(sem mensagem)'} — retry em {backoff}s, "
                "não conta como tentativa de correção (§8.1)",
                file=sys.stderr,
            )
            sleep(backoff)
            continue

        # Falha TERMINAL desta passada — estrutural de primeira, ou
        # transiente que esgotou os retries. O rastro é gravado ANTES de
        # levantar — a exceção é o caminho normal do vermelho, e um `raise`
        # antes do registro deixaria justamente a tentativa que interessa
        # fora do disjuntor. `except Exception` largo e silencioso pelo
        # mesmo motivo de `metrics.record_event`: subproduto não derruba a
        # operação que o produziu.
        try:
            record_failure(
                target_dir,
                contract,
                feature_id,
                verify_cmd=verify_cmd,
                exit_code=returncode,
                stdout=stdout,
                stderr=stderr,
                files_hash=compute_files_hash(files, target_dir),
                recorded_at=datetime.now(timezone.utc).isoformat(),
                classification=classification,
            )
            update_progress_attempts(
                target_dir,
                feature_id,
                open_failures(read_attempts(target_dir, contract, feature_id)),
            )
        except Exception:
            pass
        _report_skips(feature_id, stdout, stderr)
        _record_metric(target_dir, feature, verify_cwd, feature_id, contract, timeout_seconds)
        raise VerifyFailedError(feature_id, returncode, stdout, stderr)

    _record_metric(target_dir, feature, verify_cwd, feature_id, contract, timeout_seconds)

    evidence = {
        "feature_id": feature_id,
        # Identidade do contrato dentro da própria prova: o caminho escopado
        # impede a destruição, este campo impede o empréstimo (evidência de um
        # contrato destravando passes:true em outro).
        "contract": contract,
        "desc": feature.get("desc", ""),
        "files": files,
        "verify_cmd": verify_cmd,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "exit_code": returncode,
        "files_hash": compute_files_hash(files, target_dir),
    }
    # T-06: quem abrir esta evidência semanas depois precisa ver o que quem
    # rodou viu. Silêncio-no-verde: sem skip e sem "zero coletados", a chave
    # nem aparece — não muda o schema de quem já lê evidência de uma passada
    # limpa hoje. `items` vazio quando o motivo não é visível na saída — mas
    # isso nunca chega aqui de qualquer forma: T-04/T-05 já bloqueiam skip
    # sem motivo visível antes deste ponto (delta não decidível, INFRA
    # aplicável). Teto de ITENS, não de caracteres — evidência é JSON
    # estruturado, não texto de console (`format_skip_summary` já cobre o
    # console com teto de caracteres).
    if report.skipped_count or report.zero_collected:
        items = [
            {"nodeid": s.nodeid, "reason": s.reason}
            for s in report.skipped[:_EVIDENCE_SKIPS_MAX_ITEMS]
        ]
        skips_evidence: dict[str, Any] = {
            "count": report.skipped_count,
            "zero_collected": report.zero_collected,
            "items": items,
        }
        if report.skipped_count > len(items):
            skips_evidence["truncated"] = True
        evidence["skips"] = skips_evidence

    path = evidence_path(target_dir, contract, feature_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # Marcador de verde no rastro de tentativas: fecha a sequência de falhas
    # consecutivas que o `harness budget` conta. Reusa o `recorded_at` e o
    # `files_hash` da evidência — nunca um relógio ou um hash novos, que
    # descreveriam um estado sutilmente diferente do que acabou de ser provado.
    try:
        record_pass(
            target_dir,
            contract,
            feature_id,
            files_hash=evidence["files_hash"],
            recorded_at=evidence["recorded_at"],
        )
        # Lista vazia: o verde encerrou a sequência, então a subseção de
        # tentativas da fatia sai do progress.md. O histórico permanente
        # continua no jsonl — o que sai é a PENDÊNCIA, não o registro.
        update_progress_attempts(target_dir, feature_id, [])
    except Exception:
        pass

    # US-2: sincroniza o rastro legível com a prova recém-gravada — elimina o
    # passo manual 12 do lifecycle. No-op silencioso se .harness/progress.md não
    # existir (nunca faz run_verify falhar por causa disso).
    update_progress_status(target_dir, feature_id, "done")

    # Item 4 do backlog do dogfood miojo: a coluna de status era sincronizada,
    # mas a seção de texto livre "Última atualização" continuava 100% manual e
    # ficava vazia até alguém lembrar do passo 12 — o arquivo existe para a
    # próxima sessão retomar sem perder contexto, e cumpria mal esse papel.
    # O MESMO timestamp da evidência, nunca um relógio novo: dois carimbos
    # divergentes para o mesmo evento seriam piores que o placeholder.
    append_progress_note(
        target_dir,
        f"{evidence['recorded_at']} — {feature_id} verificado (exit_code 0) — "
        f"{path.relative_to(target_dir).as_posix()}",
        feature_id=feature_id,
    )

    return path


def mark_feature_passed(target_dir: Path, feature_id: str) -> Path:
    """Grava `passes: true` na feature `feature_id` em `feature_list.json`.

    Chamada pelo `cli.py` SÓ depois de `run_verify` ter sucesso, e por padrão
    desde a v0.23.0 (item 3 do backlog do dogfood miojo). Antes era opt-in via
    `--mark-passed`, e o resultado prático era que `harness verify` gravava
    evidência com `exit_code: 0` enquanto `passes` continuava `false` — e como
    `supervisor.ready_features` decide só por `passes`, `harness supervise`
    devolvia a MESMA tarefa indefinidamente, com prova verde em disco. A saída
    do verify também não mencionava a flag em lugar nenhum, então não havia de
    onde deduzir o passo que faltava.

    `--no-mark-passed` mantém o comportamento antigo. Ele existe para o caso
    de concorrência: SEM lock entre processos, não usar com múltiplos agentes
    escrevendo o mesmo `feature_list.json` em paralelo (mesma ressalva de
    `contract.compile_contract`, que usa este mesmo padrão de escrita). O
    lifecycle passo 6 manda trabalhar UMA feature por vez, então sequencial é
    o default honesto — quem monta fleet paralelo sabe que está fora dele.

    Reescreve o arquivo inteiro (leitura completa -> mutação da feature em
    memória -> escrita do payload inteiro), preservando todos os outros
    campos de topo e todas as outras features intactas. A escrita é ATÔMICA
    (arquivo temporário no mesmo diretório + `os.replace`): a corrida de
    lost-update entre processos continua existindo, mas nenhuma delas pode
    deixar o `feature_list.json` truncado — o arquivo é o contrato ativo, e um
    truncamento nele derruba o boundary_guard inteiro para o caminho de
    bootstrap. Levanta `VerifyError` se `feature_list.json` não existir, tiver
    JSON inválido, ou não tiver a feature `feature_id`.
    """
    return _set_feature_passes(target_dir, feature_id, True)


def restamp_evidence(
    target_dir: Path,
    contract: str,
    feature: dict[str, Any],
    *,
    verify_cmd: str,
    now: str | None = None,
) -> Path | None:
    """Atualiza o carimbo de uma evidência EXISTENTE para o estado atual.

    Existe porque a re-prova incremental roda o `verify_cmd` exato da tarefa
    acoplada contra os arquivos de agora — é a mesma execução que `run_verify`
    faria. Sem regravar, aquela prova válida virava `evidence_stale` e o
    `harness finish` cobrava um `harness verify` manual que reexecutava o
    mesmo comando que acabara de passar.

    **Nunca cria arquivo.** Evidência ausente devolve `None` e nada acontece:
    fatia com `passes: true` sem prova é marcação à mão, e é o que o bloqueador
    `evidence_missing` existe para pegar. Emitir a prova aqui apagaria a
    detecção — recarimbo atualiza prova válida, não emite prova nova.

    Preserva os campos de identidade da evidência antiga (`feature_id`,
    `contract`) e atualiza o que a re-prova acabou de estabelecer: `files[]` e
    `desc` do contrato ATUAL (a tarefa pode ter sido alargada por
    `harness task add-file`), `verify_cmd`, `exit_code` 0, `recorded_at` e
    `files_hash`.
    """
    feature_id = str(feature.get("id") or "")
    path = evidence_path(target_dir, contract, feature_id)
    if not path.is_file():
        return None
    try:
        evidence = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    if not isinstance(evidence, dict):
        return None

    files = [str(f) for f in (feature.get("files") or evidence.get("files") or [])]
    evidence.update(
        {
            "desc": feature.get("desc", evidence.get("desc", "")),
            "files": files,
            "verify_cmd": verify_cmd,
            "recorded_at": now or datetime.now(timezone.utc).isoformat(),
            "exit_code": 0,
            "files_hash": compute_files_hash(files, target_dir),
        }
    )
    path.write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def mark_feature_regressed(target_dir: Path, feature_id: str) -> Path:
    """Grava `passes: false` na feature `feature_id` — o inverso exato do acima.

    Chamada pela re-prova incremental (`harness.regression`) quando a prova de
    uma tarefa já concluída volta a falhar. O rebaixamento é o que faz a
    regressão virar trabalho: a tarefa reentra na fila do `harness supervise`,
    conta no disjuntor do `harness budget` e bloqueia o `harness finish`.
    Avisar sem rebaixar deixaria o `feature_list.json` alegando `passes: true`
    para uma prova que acabou de sair vermelha — a mentira que o `harness
    reconcile` existe para caçar, gravada pelo próprio harness.

    A evidência antiga NÃO é apagada: ela vira prova obsoleta (o `files_hash`
    deixa de bater e `audit_closure` a reporta como `evidence_stale`). Apagar
    destruiria o registro do que um dia foi de fato provado.

    Mesma escrita atômica, mesmas exceções e a mesma ressalva de concorrência
    de `mark_feature_passed`.
    """
    return _set_feature_passes(target_dir, feature_id, False)


def _set_feature_passes(target_dir: Path, feature_id: str, value: bool) -> Path:
    """Escrita atômica de `passes` — o único ponto que muda esse campo.

    Promoção e rebaixamento partilham o corpo de propósito: duas cópias da
    leitura-mutação-escrita seriam duas chances de uma delas deixar o
    `feature_list.json` truncado.
    """
    target_dir = target_dir.resolve()
    feature_list_path = target_dir / FEATURE_LIST_FILE
    if not feature_list_path.is_file():
        raise VerifyError(f"{feature_list_path}: feature_list.json não encontrado")

    try:
        data = json.loads(feature_list_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise VerifyError(f"{feature_list_path}: JSON inválido — {exc}") from exc

    for feature in data.get("features", []):
        if feature.get("id") == feature_id:
            feature["passes"] = value
            break
    else:
        raise VerifyError(f"feature '{feature_id}' não encontrada em {feature_list_path}")

    payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    tmp_path = feature_list_path.with_name(feature_list_path.name + ".tmp")
    tmp_path.write_text(payload, encoding="utf-8")
    os.replace(tmp_path, feature_list_path)
    return feature_list_path
