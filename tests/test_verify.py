"""Testes de `harness.verify`: `run_verify` e `compute_files_hash`.

Arquivo dedicado (não anexado a test_contract.py/test_cli.py) para não
colidir com tarefas concorrentes que editam contract.py/cli.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from harness.verify import (
    VerifyError,
    VerifyFailedError,
    compute_files_hash,
    detect_file_lock_hint,
    mark_feature_passed,
    run_verify,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_feature_list(tmp_path: Path, features: list[dict]) -> None:
    payload = {
        "contract": "exemplo-feature",
        "compiled_at": "2026-07-16T12:00:00+00:00",
        "features": features,
    }
    _write(
        tmp_path / ".harness" / "feature_list.json",
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
    )


def _is_windows() -> bool:
    return sys.platform.startswith("win")


def _true_cmd() -> str:
    return "exit 0" if _is_windows() else "true"


def _false_cmd() -> str:
    return "exit 1" if _is_windows() else "false"


def test_run_verify_success_writes_evidence_with_correct_schema(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "x.py", "print('hi')\n")
    _write_feature_list(
        tmp_path,
        [
            {
                "id": "T-01",
                "desc": "Criar x",
                "files": ["src/x.py"],
                "verify_cmd": _true_cmd(),
                "depends": [],
                "passes": False,
            }
        ],
    )

    evidence_path = run_verify(tmp_path, "T-01")

    assert evidence_path == tmp_path / ".harness" / "evidence" / "T-01.json"
    assert evidence_path.is_file()

    data = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert data["feature_id"] == "T-01"
    assert data["verify_cmd"] == _true_cmd()
    assert data["exit_code"] == 0
    assert "recorded_at" in data
    assert data["files_hash"] == compute_files_hash(["src/x.py"], tmp_path)
    assert set(data.keys()) == {"feature_id", "verify_cmd", "recorded_at", "exit_code", "files_hash"}


def test_run_verify_failure_does_not_write_evidence_and_propagates_exit_code(tmp_path: Path) -> None:
    _write_feature_list(
        tmp_path,
        [
            {
                "id": "T-01",
                "desc": "Falha",
                "files": [],
                "verify_cmd": _false_cmd(),
                "depends": [],
                "passes": False,
            }
        ],
    )

    with pytest.raises(VerifyFailedError) as exc_info:
        run_verify(tmp_path, "T-01")

    assert exc_info.value.exit_code == 1
    assert exc_info.value.feature_id == "T-01"
    evidence_path = tmp_path / ".harness" / "evidence" / "T-01.json"
    assert not evidence_path.is_file()


def test_run_verify_nonexistent_feature_raises_verify_error_naming_id(tmp_path: Path) -> None:
    _write_feature_list(
        tmp_path,
        [
            {
                "id": "T-01",
                "desc": "Existe",
                "files": [],
                "verify_cmd": _true_cmd(),
                "depends": [],
                "passes": False,
            }
        ],
    )

    with pytest.raises(VerifyError, match="T-99"):
        run_verify(tmp_path, "T-99")


def test_run_verify_missing_feature_list_raises_verify_error(tmp_path: Path) -> None:
    with pytest.raises(VerifyError):
        run_verify(tmp_path, "T-01")


def test_compute_files_hash_changes_when_file_content_changes(tmp_path: Path) -> None:
    _write(tmp_path / "a.txt", "conteudo 1")
    hash_before = compute_files_hash(["a.txt"], tmp_path)

    _write(tmp_path / "a.txt", "conteudo 2")
    hash_after = compute_files_hash(["a.txt"], tmp_path)

    assert hash_before != hash_after
    assert hash_before.startswith("sha256:")
    assert hash_after.startswith("sha256:")


def test_compute_files_hash_is_deterministic_for_same_input(tmp_path: Path) -> None:
    _write(tmp_path / "a.txt", "conteudo")
    _write(tmp_path / "b.txt", "outro conteudo")

    hash1 = compute_files_hash(["b.txt", "a.txt"], tmp_path)
    hash2 = compute_files_hash(["a.txt", "b.txt"], tmp_path)

    assert hash1 == hash2


def test_compute_files_hash_does_not_raise_for_missing_file(tmp_path: Path) -> None:
    result = compute_files_hash(["nao-existe.txt"], tmp_path)
    assert result.startswith("sha256:")


def _cwd_check_cmd(tmp_path: Path) -> str:
    """verify_cmd que só sai 0 se `marker.txt` existir no cwd do subprocess —
    prova que `run_verify` de fato mudou o cwd, não só passou no teste por
    coincidência (o comando falha rodando da raiz)."""
    script = tmp_path / "check_cwd.py"
    _write(script, "import pathlib, sys\nsys.exit(0 if pathlib.Path('marker.txt').is_file() else 1)\n")
    return f'"{sys.executable}" "{script}"'


def test_run_verify_runs_in_feature_cwd_when_declared(tmp_path: Path) -> None:
    _write(tmp_path / "frontend" / "marker.txt", "ok")
    verify_cmd = _cwd_check_cmd(tmp_path)
    _write_feature_list(
        tmp_path,
        [
            {"id": "T-01", "desc": "x", "files": [], "verify_cmd": verify_cmd,
             "depends": [], "cwd": "frontend", "passes": False}
        ],
    )
    evidence_path = run_verify(tmp_path, "T-01")
    assert evidence_path.is_file()


def test_run_verify_without_cwd_field_runs_at_target_dir_root(tmp_path: Path) -> None:
    """Sem `cwd`, o mesmo check falha porque marker.txt só existe em
    frontend/ — confirma que o comportamento sem `cwd` não mudou (raiz)."""
    _write(tmp_path / "frontend" / "marker.txt", "ok")
    verify_cmd = _cwd_check_cmd(tmp_path)
    _write_feature_list(
        tmp_path,
        [
            {"id": "T-01", "desc": "x", "files": [], "verify_cmd": verify_cmd,
             "depends": [], "passes": False}
        ],
    )
    with pytest.raises(VerifyFailedError):
        run_verify(tmp_path, "T-01")


def test_run_verify_nonexistent_cwd_raises_verify_error(tmp_path: Path) -> None:
    _write_feature_list(
        tmp_path,
        [
            {"id": "T-01", "desc": "x", "files": [], "verify_cmd": _true_cmd(),
             "depends": [], "cwd": "nao-existe", "passes": False}
        ],
    )
    with pytest.raises(VerifyError, match="nao-existe"):
        run_verify(tmp_path, "T-01")


# ---------------- achado do llm-as-judge/Opus: floor-check em run_verify ----------------


def test_run_verify_floor_verify_cmd_raises_verify_error_and_never_spawns_subprocess(
    tmp_path: Path,
) -> None:
    """verify_cmd que bate no runtime floor (curl) nunca deve rodar de
    verdade, mesmo vindo de um contrato compilado — bypass do floor seria
    uma falha de segurança (achado BLOQUEANTE do llm-as-judge/Opus)."""
    _write_feature_list(
        tmp_path,
        [
            {"id": "T-01", "desc": "x", "files": [], "verify_cmd": "curl https://example.com",
             "depends": [], "passes": False}
        ],
    )

    with patch("harness.verify.subprocess.Popen") as mock_popen:
        with pytest.raises(VerifyError, match="floor"):
            run_verify(tmp_path, "T-01")
        mock_popen.assert_not_called()

    evidence_path = tmp_path / ".harness" / "evidence" / "T-01.json"
    assert not evidence_path.is_file()


def test_run_verify_floor_git_push_verify_cmd_raises_and_never_spawns_subprocess(
    tmp_path: Path,
) -> None:
    _write_feature_list(
        tmp_path,
        [
            {"id": "T-01", "desc": "x", "files": [], "verify_cmd": "git push origin main",
             "depends": [], "passes": False}
        ],
    )

    with patch("harness.verify.subprocess.Popen") as mock_popen:
        with pytest.raises(VerifyError, match="floor"):
            run_verify(tmp_path, "T-01")
        mock_popen.assert_not_called()


# ---------------- regressão: UnicodeDecodeError sem `encoding=` explícito ----------------


def test_run_verify_non_ascii_utf8_output_does_not_crash_reader_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`subprocess.run(..., text=True)` sem `encoding=` cai no codec do
    console do SO (cp1252 no Windows) para decodificar stdout/stderr. Bytes
    UTF-8 fora desse charset (ex.: 0x81, indefinido em cp1252) derrubam a
    thread leitora com `UnicodeDecodeError` — mesmo sem relação com o exit
    code do `verify_cmd`. `run_verify` precisa declarar
    `encoding="utf-8", errors="replace"` explicitamente para não depender
    do locale do SO nem de `PYTHONUTF8=1` no ambiente do subprocess.

    O `verify_cmd` escreve bytes UTF-8 crus diretamente em `stdout.buffer`
    (contornando o encoding de escrita do processo filho) para isolar
    exatamente o lado da DECODIFICAÇÃO no processo pai, que é o que este
    teste protege. Sai com exit code 1 de propósito para que `run_verify`
    levante `VerifyFailedError` carregando `stdout` — só assim dá pra
    inspecionar o texto decodificado (em sucesso, a evidência não guarda
    stdout)."""
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)

    child_script = tmp_path / "print_utf8.py"
    _write(
        child_script,
        "import sys\n"
        "sys.stdout.buffer.write("
        "bytes([0xc3, 0x81]) + ' caf'.encode('utf-8') + bytes([0xc3, 0xa9])"
        " + ' '.encode('ascii') + bytes([0xe2, 0x98, 0x95])"
        ")\n"
        "sys.exit(1)\n",
    )
    verify_cmd = f'"{sys.executable}" "{child_script}"'
    _write_feature_list(
        tmp_path,
        [
            {
                "id": "T-01",
                "desc": "saida utf-8 nao-ascii",
                "files": [],
                "verify_cmd": verify_cmd,
                "depends": [],
                "passes": False,
            }
        ],
    )

    # Não pode levantar UnicodeDecodeError (era o crash original) — só
    # VerifyFailedError (esperado, exit code 1 de propósito).
    with pytest.raises(VerifyFailedError) as exc_info:
        run_verify(tmp_path, "T-01")

    assert exc_info.value.exit_code == 1
    # Bytes são UTF-8 válido -> decodificação exata, sem `�` de errors="replace".
    assert exc_info.value.stdout == "Á café ☕"


# ---------------- mark_feature_passed (opt-in, chamada só por cli.py --mark-passed) ----------------


def test_mark_feature_passed_sets_passes_true_and_preserves_other_features(tmp_path: Path) -> None:
    _write_feature_list(
        tmp_path,
        [
            {"id": "T-01", "desc": "Alvo", "files": ["a.py"], "verify_cmd": _true_cmd(),
             "depends": [], "passes": False},
            {"id": "T-02", "desc": "Outra", "files": ["b.py"], "verify_cmd": _true_cmd(),
             "depends": ["T-01"], "passes": False},
        ],
    )

    result_path = mark_feature_passed(tmp_path, "T-01")

    assert result_path == tmp_path / ".harness" / "feature_list.json"
    data = json.loads(result_path.read_text(encoding="utf-8"))
    features_by_id = {f["id"]: f for f in data["features"]}
    assert features_by_id["T-01"]["passes"] is True
    # feature irmã intacta -- escrita não corrompe o resto do arquivo
    assert features_by_id["T-02"]["passes"] is False
    assert features_by_id["T-02"]["depends"] == ["T-01"]
    # campos de topo preservados
    assert data["contract"] == "exemplo-feature"


def test_mark_feature_passed_nonexistent_feature_raises_verify_error(tmp_path: Path) -> None:
    _write_feature_list(
        tmp_path,
        [{"id": "T-01", "desc": "x", "files": [], "verify_cmd": _true_cmd(), "depends": [], "passes": False}],
    )

    with pytest.raises(VerifyError, match="T-99"):
        mark_feature_passed(tmp_path, "T-99")


def test_mark_feature_passed_missing_feature_list_raises_verify_error(tmp_path: Path) -> None:
    with pytest.raises(VerifyError):
        mark_feature_passed(tmp_path, "T-01")


# ---------------- Item 7 do backlog issue #1: detect_file_lock_hint (detecção-only) ----------------


def test_detect_file_lock_hint_msb3027_returns_actionable_message() -> None:
    stderr = (
        r'error MSB3027: Could not copy "obj\Debug\net6.0\App.dll" to '
        r'"bin\Debug\net6.0\App.dll". Exceeded retry count of 10. Failed.'
    )
    hint = detect_file_lock_hint(stdout="", stderr=stderr)
    assert hint is not None
    assert "processo do próprio projeto-alvo" in hint
    assert "dotnet run" in hint


def test_detect_file_lock_hint_msb3021_returns_actionable_message() -> None:
    stderr = (
        r'error MSB3021: Unable to copy file "obj\Debug\App.dll" to '
        r'"bin\Debug\App.dll". The process cannot access the file '
        r"'bin\Debug\App.dll' because it is being used by another process."
    )
    hint = detect_file_lock_hint(stdout="", stderr=stderr)
    assert hint is not None


@pytest.mark.parametrize(
    "needle",
    [
        "EBUSY",
        "ebusy",
        "Text file busy",
        "TEXT FILE BUSY",
        "ERROR_SHARING_VIOLATION",
        "being used by another process",
        "BEING USED BY ANOTHER PROCESS",
        "msb3027",
        "Msb3021",
    ],
)
def test_detect_file_lock_hint_matches_case_insensitively(needle: str) -> None:
    assert detect_file_lock_hint(stdout="", stderr=f"algo antes {needle} algo depois") is not None


def test_detect_file_lock_hint_ebusy_as_substring_of_other_word_is_no_false_positive() -> None:
    """Achado do validador Opus: sem word-boundary, `EBUSY` casava como
    SUBSTRING dentro de qualquer palavra que a contivesse (ex.:
    `DEBUSYX`), gerando falso-positivo. `\\bEBUSY\\b` exige que `EBUSY`
    apareça como token isolado (delimitado por não-alfanumérico/início-fim
    de string), como o libuv/Node de fato emite (`EBUSY: resource busy or
    locked`)."""
    assert detect_file_lock_hint(stdout="", stderr="algo DEBUSYX outro texto qualquer") is None
    assert detect_file_lock_hint(stdout="", stderr="prefixEBUSYsuffix sem separador") is None


def test_detect_file_lock_hint_ebusy_real_libuv_token_still_matches() -> None:
    """Token real como o Node/libuv de fato emite: `EBUSY:` seguido de
    dois-pontos — dois-pontos não é alfanumérico, então `\\bEBUSY\\b`
    ainda casa (o \\b entre 'Y' e ':' é uma fronteira de palavra válida)."""
    hint = detect_file_lock_hint(
        stdout="", stderr="Error: EBUSY: resource busy or locked, unlink 'app.exe'"
    )
    assert hint is not None


def test_detect_file_lock_hint_normal_test_failure_returns_none_no_false_positive() -> None:
    """Saída de falha de teste NORMAL (assert, N testes falharam) não deve
    disparar a mensagem — este é o caso mais comum de `verify_cmd` falhando
    e não pode gerar falso-positivo."""
    stdout = (
        "collected 12 items\n\n"
        "test_foo.py::test_bar FAILED\n\n"
        "    def test_bar():\n"
        ">       assert 1 == 2\n"
        "E       assert 1 == 2\n\n"
        "1 failed, 11 passed in 0.42s\n"
    )
    assert detect_file_lock_hint(stdout=stdout, stderr="") is None


def test_detect_file_lock_hint_empty_output_returns_none() -> None:
    assert detect_file_lock_hint(stdout="", stderr="") is None


def test_detect_file_lock_hint_extracts_pid_when_present_in_recognizable_format() -> None:
    stderr = "error MSB3027: file locked. Held by process id 4242."
    hint = detect_file_lock_hint(stdout="", stderr=stderr)
    assert hint is not None
    assert "4242" in hint


def test_detect_file_lock_hint_does_not_invent_pid_when_absent() -> None:
    """Mensagem real de MSB3027/MSB3021 tipicamente NÃO cita PID — a
    função não deve inventar um número que não está na saída."""
    stderr = (
        r'error MSB3027: Could not copy "bin\Debug\App.dll". '
        "The process cannot access the file because it is being used by another process."
    )
    hint = detect_file_lock_hint(stdout="", stderr=stderr)
    assert hint is not None
    assert "PID aparente" not in hint


def _msb3027_cmd(tmp_path: Path) -> str:
    """verify_cmd cross-plataforma que escreve uma mensagem estilo MSB3027
    em stderr e sai com exit code != 0 — simula `dotnet build` falhando por
    lock de arquivo sem depender de MSBuild instalado."""
    script = tmp_path / "fake_msbuild.py"
    _write(
        script,
        "import sys\n"
        "sys.stderr.write('error MSB3027: Could not copy bin/App.dll. "
        "The process cannot access the file because it is being used by "
        "another process.\\n')\n"
        "sys.exit(1)\n",
    )
    return f'"{sys.executable}" "{script}"'


def test_run_verify_msb3027_failure_populates_file_lock_hint_on_exception(tmp_path: Path) -> None:
    verify_cmd = _msb3027_cmd(tmp_path)
    _write_feature_list(
        tmp_path,
        [
            {"id": "T-01", "desc": "x", "files": [], "verify_cmd": verify_cmd,
             "depends": [], "passes": False}
        ],
    )

    with pytest.raises(VerifyFailedError) as exc_info:
        run_verify(tmp_path, "T-01")

    assert exc_info.value.file_lock_hint is not None
    assert "processo do próprio projeto-alvo" in exc_info.value.file_lock_hint
    # campos preexistentes continuam intactos (contrato aditivo, não quebrou nada)
    assert exc_info.value.exit_code == 1
    assert exc_info.value.feature_id == "T-01"
    assert "MSB3027" in exc_info.value.stderr


def test_run_verify_normal_failure_leaves_file_lock_hint_none(tmp_path: Path) -> None:
    """Falha comum (`exit 1` puro, sem menção a lock de arquivo) não deve
    popular `file_lock_hint` — sem falso-positivo end-to-end."""
    _write_feature_list(
        tmp_path,
        [
            {"id": "T-01", "desc": "x", "files": [], "verify_cmd": _false_cmd(),
             "depends": [], "passes": False}
        ],
    )

    with pytest.raises(VerifyFailedError) as exc_info:
        run_verify(tmp_path, "T-01")

    assert exc_info.value.file_lock_hint is None


# ---------------- Item 4 do dogfood aegis: gestao de arvore de processos + streaming ----------------


def test_run_verify_custom_timeout_kills_and_mentions_tree(tmp_path: Path) -> None:
    """Timeout configuravel por chamada (era fixo em 600s — matava suites
    legitimas do dogfood) e mensagem explicita de arvore encerrada, com o
    caminho de escape (--timeout) ensinado."""
    sleep_cmd = f'"{sys.executable}" -c "import time; time.sleep(60)"'
    _write_feature_list(
        tmp_path,
        [
            {"id": "T-01", "desc": "x", "files": [], "verify_cmd": sleep_cmd,
             "depends": [], "passes": False}
        ],
    )

    with pytest.raises(VerifyError, match="timeout de 2s") as exc_info:
        run_verify(tmp_path, "T-01", timeout_seconds=2)
    assert "árvore de processos encerrada" in str(exc_info.value)
    assert "--timeout" in str(exc_info.value)
    assert not (tmp_path / ".harness" / "evidence" / "T-01.json").is_file()


def test_run_verify_timeout_kills_grandchild_process(tmp_path: Path) -> None:
    """Regressao do issue 4: o kill do subprocess.run(timeout=...) atingia
    so o filho direto (cmd.exe/sh) e deixava os NETOS orfaos vivos. Agora o
    timeout mata a arvore (taskkill /T no Windows, killpg no POSIX). O
    verify_cmd spawna um neto que grava o proprio PID e dorme; apos o
    timeout, o PID nao pode mais existir. Scripts em arquivo .py (nao -c
    aninhado) para nao depender de quoting de shell."""
    import os
    import subprocess as sp
    import time

    pid_file = tmp_path / "grandchild.pid"
    grandchild_py = tmp_path / "grandchild.py"
    _write(
        grandchild_py,
        "import os, pathlib, time\n"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()))\n"
        "time.sleep(120)\n",
    )
    parent_py = tmp_path / "parent.py"
    _write(
        parent_py,
        "import subprocess, sys\n"
        f"p = subprocess.Popen([sys.executable, {str(grandchild_py)!r}])\n"
        "p.wait()\n",
    )
    verify_cmd = f'"{sys.executable}" "{parent_py}"'
    _write_feature_list(
        tmp_path,
        [
            {"id": "T-01", "desc": "x", "files": [], "verify_cmd": verify_cmd,
             "depends": [], "passes": False}
        ],
    )

    with pytest.raises(VerifyError, match="timeout"):
        run_verify(tmp_path, "T-01", timeout_seconds=5)

    assert pid_file.is_file(), "neto nunca chegou a rodar — teste invalido"
    grandchild_pid = int(pid_file.read_text().strip())

    def _alive(pid: int) -> bool:
        if _is_windows():
            out = sp.run(
                ["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True
            )
            return str(pid) in out.stdout
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    # taskkill /T e assincrono na pratica — polling curto antes de afirmar
    for _ in range(20):
        if not _alive(grandchild_pid):
            break
        time.sleep(0.5)
    assert not _alive(grandchild_pid), (
        f"neto (PID {grandchild_pid}) sobreviveu ao kill de arvore"
    )


def test_run_verify_stream_false_is_silent_on_console(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """Default stream=False: comportamento atual preservado — saida do
    verify_cmd NAO vaza para o console (economia de contexto do agente)."""
    echo_cmd = f'"{sys.executable}" -c "print(\'saida-da-suite\')"'
    _write_feature_list(
        tmp_path,
        [
            {"id": "T-01", "desc": "x", "files": [], "verify_cmd": echo_cmd,
             "depends": [], "passes": False}
        ],
    )

    run_verify(tmp_path, "T-01")
    captured = capsys.readouterr()
    assert "saida-da-suite" not in captured.out
    assert "saida-da-suite" not in captured.err


def test_run_verify_stream_true_mirrors_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """stream=True (CLI --stream): tee em tempo real para o console E
    buffer preservado (a evidencia continua sendo gravada normalmente)."""
    echo_cmd = f'"{sys.executable}" -c "print(\'saida-da-suite\')"'
    _write_feature_list(
        tmp_path,
        [
            {"id": "T-01", "desc": "x", "files": [], "verify_cmd": echo_cmd,
             "depends": [], "passes": False}
        ],
    )

    evidence_path = run_verify(tmp_path, "T-01", stream=True)
    captured = capsys.readouterr()
    assert "saida-da-suite" in captured.out
    assert evidence_path.is_file()


def test_run_verify_failure_still_carries_buffered_output_with_stream(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """Buffer obrigatorio mesmo com tee: VerifyFailedError.stdout alimenta
    detect_file_lock_hint — streaming nao pode drenar o buffer."""
    fail_cmd = (
        f'"{sys.executable}" -c "print(\'error MSB3027: locked\'); '
        'import sys; sys.exit(1)"'
    )
    _write_feature_list(
        tmp_path,
        [
            {"id": "T-01", "desc": "x", "files": [], "verify_cmd": fail_cmd,
             "depends": [], "passes": False}
        ],
    )

    with pytest.raises(VerifyFailedError) as exc_info:
        run_verify(tmp_path, "T-01", stream=True)

    assert "MSB3027" in exc_info.value.stdout
    assert exc_info.value.file_lock_hint is not None
