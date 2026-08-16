"""Testes de `harness.verify`: `run_verify` e `compute_files_hash`.

Arquivo dedicado (não anexado a test_contract.py/test_cli.py) para não
colidir com tarefas concorrentes que editam contract.py/cli.py."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from harness.attempts import CLASSIFICATION_STRUCTURAL, CLASSIFICATION_TRANSIENT, read_attempts
from harness.convergence import read_measurements
from harness.verify import (
    UNSCOPED_EVIDENCE_DIR,
    VerifyError,
    VerifyFailedError,
    compute_files_hash,
    detect_file_lock_hint,
    evidence_path,
    mark_feature_passed,
    mark_feature_regressed,
    normalize_command_head,
    run_verify,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_feature_list(
    tmp_path: Path, features: list[dict], contract: str = "exemplo-feature"
) -> None:
    payload = {
        "contract": contract,
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

    assert evidence_path == (
        tmp_path / ".harness" / "evidence" / "exemplo-feature" / "T-01.json"
    )
    assert evidence_path.is_file()

    data = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert data["feature_id"] == "T-01"
    assert data["desc"] == "Criar x"
    assert data["files"] == ["src/x.py"]
    assert data["verify_cmd"] == _true_cmd()
    assert data["exit_code"] == 0
    assert "recorded_at" in data
    assert data["files_hash"] == compute_files_hash(["src/x.py"], tmp_path)
    # `contract` é a identidade da prova: sem ele, a evidência de um contrato
    # anterior (todo contrato tem um T-01) destravaria passes:true aqui.
    assert data["contract"] == "exemplo-feature"
    assert set(data.keys()) == {
        "feature_id", "contract", "desc", "files", "verify_cmd", "recorded_at",
        "exit_code", "files_hash",
    }


def test_run_verify_success_syncs_claude_progress_row_to_done(tmp_path: Path) -> None:
    """US-2: run_verify verde reescreve a linha da feature no .harness/progress.md
    para 'done' — sem passo manual."""
    _write(tmp_path / "src" / "x.py", "print('hi')\n")
    _write_feature_list(
        tmp_path,
        [{"id": "T-01", "desc": "Criar x", "files": ["src/x.py"],
          "verify_cmd": _true_cmd(), "depends": [], "passes": False}],
    )
    _write(
        tmp_path / ".harness/progress.md",
        "# Claude Progress\n\n## Features\n\n"
        "| id | desc | status |\n| --- | --- | --- |\n"
        "| T-01 | Criar x | pending |\n\n## Última atualização\n\n_(vazio)_\n",
    )

    run_verify(tmp_path, "T-01")

    progress = (tmp_path / ".harness/progress.md").read_text(encoding="utf-8")
    row = next(ln for ln in progress.splitlines() if ln.startswith("| T-01 "))
    assert row.split("|")[3].strip() == "done", progress


def test_run_verify_success_without_progress_file_does_not_raise(tmp_path: Path) -> None:
    """US-2: ausência do .harness/progress.md nunca faz run_verify falhar —
    evidência continua gravada."""
    _write(tmp_path / "src" / "x.py", "print('hi')\n")
    _write_feature_list(
        tmp_path,
        [{"id": "T-01", "desc": "Criar x", "files": ["src/x.py"],
          "verify_cmd": _true_cmd(), "depends": [], "passes": False}],
    )

    evidence_path = run_verify(tmp_path, "T-01")

    assert evidence_path.is_file()
    assert not (tmp_path / ".harness/progress.md").exists()


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


# ---------------------------------------------------------------------------
# REGRA — falha transiente (§8.1) tenta de novo sozinha, sem contar como
# tentativa de correção; falha estrutural nunca entra nesse caminho
#
# `_flaky_cmd` é um script real (mesmo padrão de `_cwd_check_cmd`): cada
# chamada lê e incrementa um contador em disco e devolve o `(exit_code,
# stderr)` da posição correspondente em `codes` — comportamento determinístico
# ao longo de várias execuções reais do subprocess, sem golpear internals.
# ---------------------------------------------------------------------------

def _flaky_cmd(tmp_path: Path, codes: list[tuple[int, str]]) -> tuple[str, Path]:
    script = tmp_path / "flaky.py"
    counter = tmp_path / "flaky_counter.txt"
    _write(
        script,
        "import pathlib, sys\n"
        f"codes = {codes!r}\n"
        "counter = pathlib.Path(sys.argv[1])\n"
        "n = int(counter.read_text()) if counter.is_file() else 0\n"
        "counter.write_text(str(n + 1))\n"
        "code, message = codes[min(n, len(codes) - 1)]\n"
        "if message:\n"
        "    sys.stderr.write(message)\n"
        "sys.exit(code)\n",
    )
    return f'"{sys.executable}" "{script}" "{counter}"', counter


def test_run_verify_retries_transient_failure_and_succeeds_without_recording_retries(
    tmp_path: Path,
) -> None:
    verify_cmd, counter = _flaky_cmd(
        tmp_path,
        [(1, "Connection refused"), (1, "Connection refused"), (0, "")],
    )
    _write_feature_list(
        tmp_path,
        [{"id": "T-01", "desc": "x", "files": [], "verify_cmd": verify_cmd, "depends": [], "passes": False}],
    )
    sleeps: list[float] = []

    evidence = run_verify(tmp_path, "T-01", sleep=sleeps.append)

    assert evidence.is_file()
    assert int(counter.read_text()) == 3
    assert sleeps == [1, 2]
    records = read_attempts(tmp_path, "exemplo-feature", "T-01")
    assert [r["result"] for r in records] == ["pass"]


def test_run_verify_transient_failure_exhausted_retries_records_once_as_transient(
    tmp_path: Path,
) -> None:
    verify_cmd, counter = _flaky_cmd(tmp_path, [(1, "Read timed out")] * 3)
    _write_feature_list(
        tmp_path,
        [{"id": "T-01", "desc": "x", "files": [], "verify_cmd": verify_cmd, "depends": [], "passes": False}],
    )

    with pytest.raises(VerifyFailedError):
        run_verify(tmp_path, "T-01", sleep=lambda seconds: None)

    assert int(counter.read_text()) == 3
    records = read_attempts(tmp_path, "exemplo-feature", "T-01")
    assert [r["result"] for r in records] == ["fail"]
    assert records[0]["classification"] == CLASSIFICATION_TRANSIENT
    assert records[0]["failure_line"] == "Read timed out"


def test_run_verify_structural_failure_never_retries(tmp_path: Path) -> None:
    verify_cmd, counter = _flaky_cmd(tmp_path, [(1, "AssertionError: x != y")])
    _write_feature_list(
        tmp_path,
        [{"id": "T-01", "desc": "x", "files": [], "verify_cmd": verify_cmd, "depends": [], "passes": False}],
    )

    def _never_sleep(seconds: float) -> None:
        raise AssertionError("falha estrutural não deveria disparar retry/backoff")

    with pytest.raises(VerifyFailedError):
        run_verify(tmp_path, "T-01", sleep=_never_sleep)

    assert int(counter.read_text()) == 1
    records = read_attempts(tmp_path, "exemplo-feature", "T-01")
    assert [r["result"] for r in records] == ["fail"]
    assert records[0]["classification"] == CLASSIFICATION_STRUCTURAL


# ---------------------------------------------------------------------------
# REGRA — métrica de convergência (§4.3, contrato `convergencia-opt-in`):
# `metric_cmd` roda uma vez, depois do resultado TERMINAL do verify_cmd,
# passe ou falhe — nunca a cada retry transiente, nunca inventa valor.
# ---------------------------------------------------------------------------

def _metric_cmd_printing(value: str) -> str:
    return f'"{sys.executable}" -c "print({value!r})"'


def _counting_metric_cmd(tmp_path: Path, value: str) -> tuple[str, Path]:
    """Script real que incrementa um contador em disco a cada chamada e
    imprime `value` — usado para provar QUANTAS vezes o metric_cmd rodou."""
    script = tmp_path / "metric.py"
    counter = tmp_path / "metric_counter.txt"
    _write(
        script,
        "import pathlib, sys\n"
        f"counter = pathlib.Path({str(counter)!r})\n"
        "n = int(counter.read_text()) if counter.is_file() else 0\n"
        "counter.write_text(str(n + 1))\n"
        f"print({value!r})\n",
    )
    return f'"{sys.executable}" "{script}"', counter


def test_run_verify_records_metric_after_success(tmp_path: Path) -> None:
    _write_feature_list(
        tmp_path,
        [{"id": "T-01", "desc": "x", "files": [], "verify_cmd": _true_cmd(),
          "metric_cmd": _metric_cmd_printing("0.85"), "depends": [], "passes": False}],
    )

    run_verify(tmp_path, "T-01")

    records = read_measurements(tmp_path, "exemplo-feature", "T-01")
    assert [r["value"] for r in records] == [0.85]


def test_run_verify_records_metric_after_failure_too(tmp_path: Path) -> None:
    """A trajetória interessa PRINCIPALMENTE nos vermelhos (spec) — o
    veredito de falha ainda levanta VerifyFailedError normalmente."""
    _write_feature_list(
        tmp_path,
        [{"id": "T-01", "desc": "x", "files": [], "verify_cmd": _false_cmd(),
          "metric_cmd": _metric_cmd_printing("0.40"), "depends": [], "passes": False}],
    )

    with pytest.raises(VerifyFailedError):
        run_verify(tmp_path, "T-01")

    records = read_measurements(tmp_path, "exemplo-feature", "T-01")
    assert [r["value"] for r in records] == [0.40]


def test_run_verify_without_metric_cmd_creates_no_metric_file(tmp_path: Path) -> None:
    _write_feature_list(
        tmp_path,
        [{"id": "T-01", "desc": "x", "files": [], "verify_cmd": _true_cmd(),
          "depends": [], "passes": False}],
    )

    run_verify(tmp_path, "T-01")

    assert read_measurements(tmp_path, "exemplo-feature", "T-01") == []


def test_run_verify_metric_non_numeric_output_is_skipped_not_recorded_as_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_feature_list(
        tmp_path,
        [{"id": "T-01", "desc": "x", "files": [], "verify_cmd": _true_cmd(),
          "metric_cmd": _metric_cmd_printing("nao e um numero"), "depends": [], "passes": False}],
    )

    evidence_path = run_verify(tmp_path, "T-01")

    assert evidence_path.is_file(), "metric quebrado não pode derrubar o resultado do verify_cmd"
    assert read_measurements(tmp_path, "exemplo-feature", "T-01") == []
    assert "medição pulada" in capsys.readouterr().err


def test_run_verify_metric_cmd_on_the_runtime_floor_is_never_executed(tmp_path: Path) -> None:
    _write_feature_list(
        tmp_path,
        [{"id": "T-01", "desc": "x", "files": [], "verify_cmd": _true_cmd(),
          "metric_cmd": "curl https://exfil.example/x", "depends": [], "passes": False}],
    )

    evidence_path = run_verify(tmp_path, "T-01")

    assert evidence_path.is_file()
    assert read_measurements(tmp_path, "exemplo-feature", "T-01") == []


def test_run_verify_transient_retries_measure_metric_only_once(tmp_path: Path) -> None:
    """O retry transiente (§8.1) do verify_cmd é interno à passada — a
    métrica só olha o resultado TERMINAL, não cada tentativa."""
    verify_cmd, _ = _flaky_cmd(
        tmp_path, [(1, "Connection refused"), (1, "Connection refused"), (0, "")]
    )
    metric_cmd, metric_counter = _counting_metric_cmd(tmp_path, "0.5")
    _write_feature_list(
        tmp_path,
        [{"id": "T-01", "desc": "x", "files": [], "verify_cmd": verify_cmd,
          "metric_cmd": metric_cmd, "depends": [], "passes": False}],
    )

    run_verify(tmp_path, "T-01", sleep=lambda seconds: None)

    assert int(metric_counter.read_text()) == 1
    records = read_measurements(tmp_path, "exemplo-feature", "T-01")
    assert [r["value"] for r in records] == [0.5]


def test_run_verify_metric_records_commit_and_dirty_flag(tmp_path: Path) -> None:
    def _git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, text=True, check=True)

    _write(tmp_path / "src" / "x.py", "x = 1\n")
    _git("init", "-b", "main")
    _git("config", "user.email", "t@example.com")
    _git("config", "user.name", "T")
    _git("add", ".")
    _git("commit", "-m", "init")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, check=True,
    ).stdout.strip()
    # dirty DEPOIS do commit inicial (mesmo escopo -uno do resto do harness:
    # só tracked modificado conta).
    _write(tmp_path / "src" / "x.py", "x = 2\n")

    _write_feature_list(
        tmp_path,
        [{"id": "T-01", "desc": "x", "files": ["src/x.py"], "verify_cmd": _true_cmd(),
          "metric_cmd": _metric_cmd_printing("1.0"), "depends": [], "passes": False}],
    )

    run_verify(tmp_path, "T-01")

    records = read_measurements(tmp_path, "exemplo-feature", "T-01")
    assert records[0]["commit"] == head
    assert records[0]["dirty"] is True


def test_run_verify_metric_without_git_repo_records_none_commit(tmp_path: Path) -> None:
    _write_feature_list(
        tmp_path,
        [{"id": "T-01", "desc": "x", "files": [], "verify_cmd": _true_cmd(),
          "metric_cmd": _metric_cmd_printing("1.0"), "depends": [], "passes": False}],
    )

    run_verify(tmp_path, "T-01")

    records = read_measurements(tmp_path, "exemplo-feature", "T-01")
    assert records[0]["commit"] is None
    assert records[0]["dirty"] is False


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


def test_run_verify_stamps_the_last_update_section_of_progress(tmp_path: Path) -> None:
    """Item 4 do backlog do dogfood miojo: a coluna de status já era
    sincronizada, mas a seção de texto livre ficava vazia até alguém lembrar
    do passo 12 — e o arquivo existe justamente para a próxima sessão retomar
    sem perder contexto."""
    from harness.templates import PROGRESS_FILE, render_progress_template

    _write_feature_list(
        tmp_path,
        [{"id": "T-01", "desc": "Alvo", "files": [], "verify_cmd": _true_cmd(),
          "depends": [], "passes": False}],
    )
    feature_list = json.loads(
        (tmp_path / ".harness" / "feature_list.json").read_text(encoding="utf-8")
    )
    _write(tmp_path / PROGRESS_FILE, render_progress_template(feature_list))

    path = run_verify(tmp_path, "T-01")

    evidence = json.loads(path.read_text(encoding="utf-8"))
    progress = (tmp_path / PROGRESS_FILE).read_text(encoding="utf-8")
    assert "| T-01 | Alvo | done |" in progress
    # mesmo timestamp da evidência: dois carimbos divergentes para o mesmo
    # evento seriam piores que a seção vazia
    assert evidence["recorded_at"] in progress
    assert ".harness/evidence/exemplo-feature/T-01.json" in progress


def test_run_verify_succeeds_when_progress_file_is_absent(tmp_path: Path) -> None:
    """Sincronizar o rastro legível nunca pode ser motivo de a verificação
    falhar — no-op silencioso, mesma regra de `update_progress_status`."""
    _write_feature_list(
        tmp_path,
        [{"id": "T-01", "desc": "x", "files": [], "verify_cmd": _true_cmd(),
          "depends": [], "passes": False}],
    )

    path = run_verify(tmp_path, "T-01")

    assert json.loads(path.read_text(encoding="utf-8"))["exit_code"] == 0


# ---------------- normalize_command_head (item 1 do backlog do dogfood miojo) ----------------


@pytest.mark.skipif(not _is_windows(), reason="normalização só se aplica ao cmd.exe")
def test_normalize_command_head_rewrites_only_the_head_on_windows() -> None:
    # o head é o único ponto onde o `/` quebra: o cmd.exe corta o token do
    # COMANDO no primeiro `/`, tratando o resto como switch
    assert normalize_command_head(
        ".venv/Scripts/pytest.exe -q tests/test_x.py"
    ) == ".venv\\Scripts\\pytest.exe -q tests/test_x.py"


@pytest.mark.skipif(not _is_windows(), reason="normalização só se aplica ao cmd.exe")
def test_normalize_command_head_preserves_slashes_in_arguments() -> None:
    # regex, URL e --cov=src/... continuam intactos: reescrevê-los mudaria o
    # SIGNIFICADO do comando, não só a forma de invocação
    assert normalize_command_head(
        ".venv/Scripts/pytest.exe --cov=src/harness -k 'a/b'"
    ) == ".venv\\Scripts\\pytest.exe --cov=src/harness -k 'a/b'"


@pytest.mark.skipif(not _is_windows(), reason="normalização só se aplica ao cmd.exe")
def test_normalize_command_head_noop_for_plain_and_quoted_heads() -> None:
    assert normalize_command_head("python -m pytest -q") == "python -m pytest -q"
    assert normalize_command_head("pytest -q") == "pytest -q"
    # head entre aspas: o cmd.exe já trata o caminho inteiro como um token só
    assert normalize_command_head('".venv/Scripts/pytest.exe" -q') == '".venv/Scripts/pytest.exe" -q'


@pytest.mark.skipif(_is_windows(), reason="POSIX resolve a barra normal nativamente")
def test_normalize_command_head_is_noop_outside_windows() -> None:
    command = ".venv/bin/pytest -q"
    assert normalize_command_head(command) == command


@pytest.mark.skipif(not _is_windows(), reason="reproduz a falha do cmd.exe")
def test_run_verify_executes_venv_anchored_command_and_records_original_text(
    tmp_path: Path,
) -> None:
    """A regressão que originou o item: `.venv/Scripts/<bin>` passava no
    boundary_guard (que só CASA o texto) e falhava na execução com
    `'.venv' não é reconhecido...`, porque quem executa é o cmd.exe.

    Usa um .cmd de verdade dentro de `.venv/Scripts` — o ponto do teste é o
    caminho com barra normal chegar ao shell, não o binário em si."""
    scripts = tmp_path / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "faketest.cmd").write_text("@echo ok\n@exit 0\n", encoding="ascii")

    _write_feature_list(
        tmp_path,
        [{"id": "T-01", "desc": "x", "files": [], "depends": [], "passes": False,
          "verify_cmd": ".venv/Scripts/faketest.cmd -q"}],
    )

    path = run_verify(tmp_path, "T-01")

    evidence = json.loads(path.read_text(encoding="utf-8"))
    assert evidence["exit_code"] == 0
    # a evidência guarda o TEXTO DO CONTRATO, não a forma executável — é o
    # contrato que ela prova
    assert evidence["verify_cmd"] == ".venv/Scripts/faketest.cmd -q"


# ---------------- mark_feature_passed (default desde v0.23.0; --no-mark-passed volta ao antigo) ----------------


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


def test_mark_feature_regressed_takes_the_proof_back_without_touching_the_rest(
    tmp_path: Path,
) -> None:
    """Rebaixamento da re-prova incremental: `passes` volta a false e mais nada
    muda — a evidência antiga fica no lugar (vira `evidence_stale`, que é
    informação), e a feature irmã não é afetada."""
    _write_feature_list(
        tmp_path,
        [
            {"id": "T-01", "desc": "Alvo", "files": ["a.py"], "verify_cmd": _true_cmd(),
             "depends": [], "passes": True},
            {"id": "T-02", "desc": "Outra", "files": ["b.py"], "verify_cmd": _true_cmd(),
             "depends": ["T-01"], "passes": True},
        ],
    )

    result_path = mark_feature_regressed(tmp_path, "T-01")

    data = json.loads(result_path.read_text(encoding="utf-8"))
    features_by_id = {f["id"]: f for f in data["features"]}
    assert features_by_id["T-01"]["passes"] is False
    assert features_by_id["T-02"]["passes"] is True
    assert data["contract"] == "exemplo-feature"


def test_mark_feature_regressed_nonexistent_feature_raises_verify_error(tmp_path: Path) -> None:
    _write_feature_list(
        tmp_path,
        [{"id": "T-01", "desc": "x", "files": [], "verify_cmd": _true_cmd(), "depends": [], "passes": True}],
    )

    with pytest.raises(VerifyError, match="T-99"):
        mark_feature_regressed(tmp_path, "T-99")


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


# ---------------- Item 4 do dogfood venv-Windows: gestao de arvore de processos + streaming ----------------


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


# ---------------------------------------------------------------------------
# Evidência escopada por contrato (achado de teste isento)
# ---------------------------------------------------------------------------

def test_verify_of_a_new_contract_does_not_destroy_the_previous_proof(
    tmp_path: Path,
) -> None:
    """A evidência morava em `.harness/evidence/<id>.json`, sem o contrato em
    lugar nenhum. Como TODO contrato começa em `T-01`, compilar um contrato
    novo e rodar `harness verify T-01` sobrescrevia em silêncio a prova do
    contrato anterior — sem aviso e sem backup."""
    _write_feature_list(
        tmp_path,
        [{"id": "T-01", "desc": "Feature do contrato A", "files": ["src/x.py"],
          "verify_cmd": _true_cmd(), "depends": [], "passes": False}],
        contract="contrato-a",
    )
    first = run_verify(tmp_path, "T-01")

    # Contrato novo, mesmo id de tarefa — o cenário exato da colisão.
    _write_feature_list(
        tmp_path,
        [{"id": "T-01", "desc": "Feature do contrato B", "files": ["src/x.py"],
          "verify_cmd": _true_cmd(), "depends": [], "passes": False}],
        contract="contrato-b",
    )
    second = run_verify(tmp_path, "T-01")

    assert first != second
    assert first.is_file(), "a prova do contrato anterior foi destruída"
    assert json.loads(first.read_text(encoding="utf-8"))["desc"] == "Feature do contrato A"
    assert json.loads(second.read_text(encoding="utf-8"))["desc"] == "Feature do contrato B"
    assert first.parent.name == "contrato-a"
    assert second.parent.name == "contrato-b"


def test_evidence_path_falls_back_when_the_contract_is_absent(tmp_path: Path) -> None:
    """`feature_list.json` sem `contract` (compilado por versão antiga, ou
    fixture) não pode explodir nem gravar na raiz de `evidence/` — vai para um
    subdiretório de nome inválido como slug, que nunca colide com contrato
    real."""
    assert evidence_path(tmp_path, "", "T-01").parent.name == UNSCOPED_EVIDENCE_DIR
    assert evidence_path(tmp_path, None, "T-01").parent.name == UNSCOPED_EVIDENCE_DIR
    assert evidence_path(tmp_path, "   ", "T-01").parent.name == UNSCOPED_EVIDENCE_DIR
    assert evidence_path(tmp_path, "meu-contrato", "T-01").parent.name == "meu-contrato"


# ---------------------------------------------------------------------------
# enforcement_gate (T-03, contrato setup-fail-closed-sem-init): `harness
# verify <id>` para com exit 1 quando há contrato ativo mas o enforcement
# não está de pé NESTA máquina (hooks ausentes do settings gerenciado, ou
# kill-switch ligado) — o cenário do clone novo/segunda máquina: o contrato
# (.harness/feature_list.json) viaja pelo git, o enforcement machine-local
# não. `run_verify` (testado acima, à exaustão) continua roda com contrato
# ativo e SEM hooks/settings instalados — de propósito, são testes de
# unidade da lógica de verificação, não da governança. O gate mora só em
# `cli.py` (via harness.health.require_enforcement_installed), então essas
# funções não precisam saber que ele existe. Ver harness.health para a
# detecção reusada (`_protection_problem`/`_hooks_missing`).
# ---------------------------------------------------------------------------

def _write_hooks_installed(tmp_path: Path) -> None:
    """Registra um hook do harness em `.claude/settings.local.json` — o
    suficiente para `health._hooks_missing` ver enforcement instalado.
    `require_enforcement_installed` só checa PRESENÇA (a mesma leitura de
    `doctor._read_managed_hooks`), não se o interpretador resolve de
    verdade — isso é outra família (`governance_stale`), já coberta por
    `doctor`/`repo_issues`."""
    settings = {
        "hooks": {
            "PreToolUse": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": '"python" ".harness/hooks/boundary_guard.py" || exit 2',
                        }
                    ]
                }
            ]
        }
    }
    _write(
        tmp_path / ".claude" / "settings.local.json",
        json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
    )


def _write_harness_yaml(tmp_path: Path) -> None:
    # O gate (T-03) pressupõe um repositório GOVERNADO (já rodou
    # /harness-creator:init) clonado sem o output machine-local -- sem
    # harness.yaml é outro furo (T-01/T-02), fora do escopo deste gate.
    _write(tmp_path / ".harness" / "harness.yaml", "governance:\n  approval_policy: default\n")


def _enforcement_gate_case_hooks_missing(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "x.py", "print('hi')\n")
    _write_harness_yaml(tmp_path)
    _write_feature_list(
        tmp_path,
        [{"id": "T-01", "desc": "Criar x", "files": ["src/x.py"],
          "verify_cmd": _true_cmd(), "depends": [], "passes": False}],
    )
    # Sem .claude/settings.local.json nenhum -- hooks ausentes por definição.


def _enforcement_gate_case_killswitch_on(tmp_path: Path) -> None:
    from harness.killswitch import disable

    _write(tmp_path / "src" / "x.py", "print('hi')\n")
    _write_harness_yaml(tmp_path)
    _write_feature_list(
        tmp_path,
        [{"id": "T-01", "desc": "Criar x", "files": ["src/x.py"],
          "verify_cmd": _true_cmd(), "depends": [], "passes": False}],
    )
    _write_hooks_installed(tmp_path)
    disable(tmp_path, note="teste enforcement_gate")


def _enforcement_gate_case_installed(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "x.py", "print('hi')\n")
    _write_harness_yaml(tmp_path)
    _write_feature_list(
        tmp_path,
        [{"id": "T-01", "desc": "Criar x", "files": ["src/x.py"],
          "verify_cmd": _true_cmd(), "depends": [], "passes": False}],
    )
    _write_hooks_installed(tmp_path)


def _enforcement_gate_case_no_active_contract(tmp_path: Path) -> None:
    # Nenhum .harness/feature_list.json -- sem contrato ativo, o gate não é
    # da conta deste comando (outro erro, "feature_list.json não
    # encontrado", cuida disso).
    pass


@pytest.mark.parametrize(
    "setup, expect_exit, expect_in_stderr, forbid_in_stderr",
    [
        pytest.param(
            _enforcement_gate_case_hooks_missing, 1,
            "harness compile-session",
            ("harness enable",),
            id="hooks_missing",
        ),
        pytest.param(
            _enforcement_gate_case_killswitch_on, 1,
            "harness enable",
            ("harness compile-session",),
            id="killswitch_on",
        ),
        pytest.param(
            _enforcement_gate_case_installed, 0, None, (), id="enforcement_installed",
        ),
        pytest.param(
            _enforcement_gate_case_no_active_contract, 1,
            "feature_list.json",
            ("harness compile-session", "harness enable"),
            id="no_active_contract",
        ),
    ],
)
def test_verify_enforcement_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    setup,
    expect_exit: int,
    expect_in_stderr: str | None,
    forbid_in_stderr: tuple[str, ...],
) -> None:
    from harness.cli import main

    setup(tmp_path)

    monkeypatch.setattr(sys, "argv", ["harness", "verify", "T-01", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == expect_exit
    err = capsys.readouterr().err
    if expect_in_stderr is not None:
        assert expect_in_stderr in err, err
    for forbidden in forbid_in_stderr:
        assert forbidden not in err, err


def test_verify_enforcement_gate_installed_runs_verify_cmd_and_writes_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """Regra (3) do gate: com enforcement instalado, `harness verify`
    preserva o comportamento de hoje -- roda o verify_cmd de verdade e grava
    a evidência, sem nenhuma menção ao gate em stderr."""
    from harness.cli import main

    _enforcement_gate_case_installed(tmp_path)

    monkeypatch.setattr(sys, "argv", ["harness", "verify", "T-01", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    evidence = tmp_path / ".harness" / "evidence" / "exemplo-feature" / "T-01.json"
    assert evidence.is_file()
    data = json.loads(evidence.read_text(encoding="utf-8"))
    assert data["exit_code"] == 0
