"""Verificação: `verify_cmd` de uma feature -> evidência executável.

Fecha o passo 11 do lifecycle (Fase 2/3): uma feature só é considerada
"provada" se o `verify_cmd` declarado em `.harness/feature_list.json` rodou
de verdade e saiu com exit code 0. Este módulo NÃO decide bloqueio de
edição sobre `feature_list.json` (outro escopo) nem ordena por `depends[]`
(idem) — apenas executa o comando de UMA feature e, em caso de sucesso,
grava a prova em `.harness/evidence/<feature_id>.json`.

`mark_feature_passed` é a exceção opt-in a essa regra: só roda quando o
`cli.py` chama com `--mark-passed` (e só depois de `run_verify` já ter tido
sucesso) — grava `passes: true` na feature em `feature_list.json`. Sem lock
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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

from harness.boundary_guard import is_floor_bash_command
from harness.contract import FEATURE_LIST_FILE

EVIDENCE_DIR = ".harness/evidence"
_VERIFY_TIMEOUT_SECONDS = 600

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
    correção do issue 4 do dogfood aegis (no Windows, o kill do
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


def _load_feature(target_dir: Path, feature_id: str) -> dict[str, Any]:
    feature_list_path = target_dir / FEATURE_LIST_FILE
    if not feature_list_path.is_file():
        raise VerifyError(f"{feature_list_path}: feature_list.json não encontrado")

    try:
        data = json.loads(feature_list_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise VerifyError(f"{feature_list_path}: JSON inválido — {exc}") from exc

    for feature in data.get("features", []):
        if feature.get("id") == feature_id:
            return feature

    raise VerifyError(f"feature '{feature_id}' não encontrada em {feature_list_path}")


def run_verify(
    target_dir: Path,
    feature_id: str,
    *,
    timeout_seconds: int = _VERIFY_TIMEOUT_SECONDS,
    stream: bool = False,
) -> Path:
    """Roda o `verify_cmd` da feature `feature_id` e, se exit code == 0, grava evidência.

    Levanta `VerifyError` se a feature ou o `feature_list.json` não existirem.
    Levanta `VerifyFailedError` (carregando stdout/stderr/exit_code) se o
    `verify_cmd` sair com código != 0 — NADA é gravado em disco nesse caso.
    Retorna o Path do arquivo de evidência gravado em caso de sucesso.

    `timeout_seconds` (CLI `--timeout`): o default de 600s matava
    verify_cmds legítimos encadeados (~1100s no dogfood do issue 4) — agora
    configurável por chamada, sem mudar o default. `stream` (CLI
    `--stream`): tee do stdout/stderr em tempo real, opt-in — ver
    `_run_verify_cmd` para o porquê de NÃO ser default.
    """
    target_dir = target_dir.resolve()
    feature = _load_feature(target_dir, feature_id)
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

    try:
        returncode, stdout, stderr = _run_verify_cmd(
            verify_cmd, verify_cwd, timeout_seconds, stream
        )
    except subprocess.TimeoutExpired as exc:
        raise VerifyError(
            f"feature '{feature_id}': verify_cmd '{verify_cmd}' excedeu o "
            f"timeout de {timeout_seconds}s — árvore de processos encerrada "
            "(taskkill /T no Windows, killpg no POSIX; best-effort). Suíte "
            "legitimamente mais lenta que isso? use --timeout <segundos>"
        ) from exc

    if returncode != 0:
        raise VerifyFailedError(feature_id, returncode, stdout, stderr)

    evidence = {
        "feature_id": feature_id,
        "verify_cmd": verify_cmd,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "exit_code": returncode,
        "files_hash": compute_files_hash(files, target_dir),
    }

    evidence_path = target_dir / EVIDENCE_DIR / f"{feature_id}.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return evidence_path


def mark_feature_passed(target_dir: Path, feature_id: str) -> Path:
    """Grava `passes: true` na feature `feature_id` em `feature_list.json`.

    Opt-in via `harness verify <id> --mark-passed` (chamado pelo `cli.py`
    SÓ depois de `run_verify` ter sucesso) — poupa a sessão orquestradora
    sequencial única de editar `feature_list.json` na mão a cada tarefa.

    SEM lock entre processos: não usar com múltiplos agentes escrevendo o
    mesmo `feature_list.json` em paralelo (mesma ressalva de
    `contract.compile_contract`, que usa este mesmo padrão de escrita).

    Reescreve o arquivo inteiro (leitura completa -> mutação da feature em
    memória -> `write_text` do payload inteiro), preservando todos os outros
    campos de topo e todas as outras features intactas. Levanta
    `VerifyError` se `feature_list.json` não existir, tiver JSON inválido,
    ou não tiver a feature `feature_id`.
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
            feature["passes"] = True
            break
    else:
        raise VerifyError(f"feature '{feature_id}' não encontrada em {feature_list_path}")

    feature_list_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return feature_list_path
