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

    with patch("harness.verify.subprocess.run") as mock_run:
        with pytest.raises(VerifyError, match="floor"):
            run_verify(tmp_path, "T-01")
        mock_run.assert_not_called()

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

    with patch("harness.verify.subprocess.run") as mock_run:
        with pytest.raises(VerifyError, match="floor"):
            run_verify(tmp_path, "T-01")
        mock_run.assert_not_called()


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
