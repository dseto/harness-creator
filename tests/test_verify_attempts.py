"""Testes da gravação do rastro de tentativas dentro de `harness.verify`.

T-02 do contrato `rastro-de-tentativas-e-budget`. Arquivo dedicado (não
anexado a `test_verify.py`) pelo mesmo motivo declarado lá: não colidir com
tarefas concorrentes que editam o módulo.

A invariante histórica de `run_verify` — "exit code != 0 -> NADA é gravado em
disco" — muda aqui, e a mudança é deliberada: o que não podia ser gravado no
vermelho era **evidência** (prova de que a fatia está pronta). Rastro de
tentativa é o oposto disso — é o registro de que ela NÃO está — e é justamente
o dado que faltava para o disjuntor de §4.2/§8.2 existir. Estes testes fixam as
duas metades: a evidência continua proibida no vermelho, e o rastro passa a ser
obrigatório.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from harness.attempts import attempts_path, failure_signature, read_attempts
from harness.verify import VerifyError, VerifyFailedError, evidence_path, run_verify


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _is_windows() -> bool:
    return sys.platform.startswith("win")


def _true_cmd() -> str:
    return "exit 0" if _is_windows() else "true"


def _false_cmd() -> str:
    return "exit 1" if _is_windows() else "false"


def _fail_with(message: str) -> str:
    """Comando que falha imprimindo `message` no stdout (onde pytest põe o
    resumo da falha) — é o formato que `extract_failure_line` prioriza depois
    do stderr vazio."""
    if _is_windows():
        return f"echo {message}& exit 1"
    return f"echo '{message}'; exit 1"


def _setup(
    tmp_path: Path,
    verify_cmd: str,
    contract: str = "exemplo-feature",
    files: list[str] | None = None,
) -> None:
    files = files if files is not None else ["src/x.py"]
    for relative in files:
        _write(tmp_path / relative, "print('hi')\n")
    payload = {
        "contract": contract,
        "compiled_at": "2026-07-16T12:00:00+00:00",
        "features": [
            {
                "id": "T-01",
                "desc": "Criar x",
                "files": files,
                "verify_cmd": verify_cmd,
                "depends": [],
                "passes": False,
            }
        ],
    }
    _write(
        tmp_path / ".harness" / "feature_list.json",
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
    )


# ---------------------------------------------------------------------------
# REGRA 1 — o vermelho passa a deixar rastro, e continua sem deixar evidência
#
# As duas metades andam juntas: gravar a tentativa não pode virar, por
# descuido, uma forma de a fatia parecer provada.
# ---------------------------------------------------------------------------

def test_failed_verify_records_the_attempt(tmp_path: Path) -> None:
    _setup(tmp_path, _fail_with("E assert 1 == 2"))

    with pytest.raises(VerifyFailedError):
        run_verify(tmp_path, "T-01")

    records = read_attempts(tmp_path, "exemplo-feature", "T-01")
    assert len(records) == 1
    record = records[0]
    assert record["result"] == "fail"
    assert record["feature_id"] == "T-01"
    assert record["contract"] == "exemplo-feature"
    assert record["exit_code"] == 1
    assert "assert 1 == 2" in record["failure_line"]
    assert record["failure_signature"] == failure_signature(record["failure_line"])
    assert record["files_hash"].startswith("sha256:")
    assert record["verify_cmd"] == _fail_with("E assert 1 == 2")
    assert record["recorded_at"]


def test_failed_verify_still_writes_no_evidence(tmp_path: Path) -> None:
    _setup(tmp_path, _false_cmd())

    with pytest.raises(VerifyFailedError):
        run_verify(tmp_path, "T-01")

    assert not evidence_path(tmp_path, "exemplo-feature", "T-01").exists()


def test_failed_verify_still_raises_with_the_raw_output(tmp_path: Path) -> None:
    """Gravar o rastro não pode engolir a exceção: o erro CRU continua sendo o
    que entra no próximo Adjustment (§3 do design)."""
    _setup(tmp_path, _fail_with("boom especifico"))

    with pytest.raises(VerifyFailedError) as excinfo:
        run_verify(tmp_path, "T-01")

    assert excinfo.value.exit_code == 1
    assert "boom especifico" in (excinfo.value.stdout + excinfo.value.stderr)


# ---------------------------------------------------------------------------
# REGRA 2 — o verde fecha a sequência com o MESMO carimbo da evidência
#
# Dois relógios para o mesmo evento é o defeito que o `append_progress_note` já
# tinha evitado reusando o `recorded_at` da evidência; a mesma regra vale aqui.
# ---------------------------------------------------------------------------

def test_successful_verify_records_the_pass(tmp_path: Path) -> None:
    _setup(tmp_path, _true_cmd())

    path = run_verify(tmp_path, "T-01")

    records = read_attempts(tmp_path, "exemplo-feature", "T-01")
    assert [r["result"] for r in records] == ["pass"]
    evidence = json.loads(path.read_text(encoding="utf-8"))
    assert records[0]["recorded_at"] == evidence["recorded_at"]
    assert records[0]["files_hash"] == evidence["files_hash"]


def test_the_trail_keeps_the_whole_history_across_the_green(tmp_path: Path) -> None:
    """O rastro é o produto: o verde encerra a sequência de falhas, não apaga
    o que aconteceu antes dele."""
    _setup(tmp_path, _fail_with("primeira"))
    with pytest.raises(VerifyFailedError):
        run_verify(tmp_path, "T-01")

    _setup(tmp_path, _fail_with("segunda"))
    with pytest.raises(VerifyFailedError):
        run_verify(tmp_path, "T-01")

    _setup(tmp_path, _true_cmd())
    run_verify(tmp_path, "T-01")

    records = read_attempts(tmp_path, "exemplo-feature", "T-01")
    assert [r["result"] for r in records] == ["fail", "fail", "pass"]
    assert "primeira" in records[0]["failure_line"]
    assert "segunda" in records[1]["failure_line"]


def test_the_trail_is_scoped_by_contract(tmp_path: Path) -> None:
    """Contrato novo começa a contagem do zero, mesmo reusando o id `T-01`."""
    _setup(tmp_path, _false_cmd(), contract="contrato-a")
    with pytest.raises(VerifyFailedError):
        run_verify(tmp_path, "T-01")

    _setup(tmp_path, _false_cmd(), contract="contrato-b")
    with pytest.raises(VerifyFailedError):
        run_verify(tmp_path, "T-01")

    assert len(read_attempts(tmp_path, "contrato-a", "T-01")) == 1
    assert len(read_attempts(tmp_path, "contrato-b", "T-01")) == 1


# ---------------------------------------------------------------------------
# REGRA 3 — timeout não é tentativa
#
# §8 do design separa falha ESTRUTURAL (teste vermelho: o loop de autocorreção
# se aplica) de transiente/infra (timeout: "não conta como tentativa de
# correção — nada foi corrigido, só repetido"). Contar timeout no disjuntor
# gastaria o teto de iterações sem nenhum ajuste ter sido tentado.
# ---------------------------------------------------------------------------

def test_timeout_leaves_no_attempt_in_the_trail(tmp_path: Path) -> None:
    _setup(tmp_path, _true_cmd())

    with patch(
        "harness.verify._run_verify_cmd",
        side_effect=subprocess.TimeoutExpired(cmd="x", timeout=1),
    ):
        with pytest.raises(VerifyError):
            run_verify(tmp_path, "T-01")

    assert read_attempts(tmp_path, "exemplo-feature", "T-01") == []
    assert not attempts_path(tmp_path, "exemplo-feature", "T-01").exists()


def test_floor_rejection_leaves_no_attempt_in_the_trail(tmp_path: Path) -> None:
    """`verify_cmd` barrado pelo runtime floor nunca chegou a rodar — não há
    tentativa a registrar."""
    _setup(tmp_path, "git push origin main")

    with pytest.raises(VerifyError):
        run_verify(tmp_path, "T-01")

    assert read_attempts(tmp_path, "exemplo-feature", "T-01") == []


# ---------------------------------------------------------------------------
# REGRA 4 — o rastro é subproduto: falhar ao gravá-lo nunca muda o resultado
#
# Mesma regra já valia para o sync do `progress.md` ("sincronizar o rastro
# legível jamais pode ser motivo de uma verificação falhar"). Um disco cheio
# não pode transformar verde em vermelho, nem vermelho em exceção diferente da
# que o loop de autocorreção espera tratar.
# ---------------------------------------------------------------------------

def test_trail_write_failure_does_not_change_a_red(tmp_path: Path) -> None:
    _setup(tmp_path, _false_cmd())

    with patch("harness.verify.record_failure", side_effect=OSError("disco cheio")):
        with pytest.raises(VerifyFailedError):
            run_verify(tmp_path, "T-01")


def test_trail_write_failure_does_not_change_a_green(tmp_path: Path) -> None:
    _setup(tmp_path, _true_cmd())

    with patch("harness.verify.record_pass", side_effect=OSError("disco cheio")):
        path = run_verify(tmp_path, "T-01")

    assert path.is_file()
    assert json.loads(path.read_text(encoding="utf-8"))["exit_code"] == 0
