"""Testes do bloco de tentativas no `.harness/progress.md`.

T-05 do contrato `rastro-de-tentativas-e-budget`, fechando a metade legível de
§5.1: "histórico de tentativas é obrigatório para a fatia em andamento — sem
ele, a regra do padrão repetido só funciona dentro de uma sessão; a sessão
seguinte retoma sabendo ONDE parou, mas não O QUE já falhou, e repete a
tentativa 1 de boa fé".

O `progress.md` é o arquivo que o hook `SessionStart` injeta no começo de toda
sessão. O jsonl de `harness.attempts` é a fonte da verdade e é ótimo para
máquina; ninguém lê jsonl no meio de um handoff. Este bloco é a mesma
informação em formato de leitura — e, como todo o resto do progress.md, é
GERADO, nunca digitado: rastro escrito à mão é rastro que diverge.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from harness.attempts import failure_signature, open_failures
from harness.templates import (
    ATTEMPTS_BEGIN,
    ATTEMPTS_END,
    render_attempts_section,
    update_progress_attempts,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _progress(tmp_path: Path) -> Path:
    return tmp_path / ".harness" / "progress.md"


def _write_progress(tmp_path: Path) -> Path:
    path = _progress(tmp_path)
    _write(
        path,
        "# Claude Progress\n\n"
        "Contrato: `exemplo`\n\n"
        "## Features\n\n"
        "| id | desc | status |\n"
        "| --- | --- | --- |\n"
        "| T-01 | Fazer alguma coisa | pending |\n\n"
        "## Última atualização\n\n"
        "_(vazio — preenchido pelo agente durante a sessão)_\n",
    )
    return path


def _fail(line: str, exit_code: int = 1) -> dict:
    return {
        "result": "fail",
        "contract": "exemplo",
        "feature_id": "T-01",
        "recorded_at": "2026-08-09T04:00:00+00:00",
        "verify_cmd": "pytest -q",
        "exit_code": exit_code,
        "failure_line": line,
        "failure_signature": failure_signature(line),
        "files_hash": "h",
    }


def _pass() -> dict:
    return {"result": "pass", "recorded_at": "t", "files_hash": "h"}


# ---------------------------------------------------------------------------
# REGRA 1 — só a sequência ABERTA entra: o que o verde encerrou não é pendência
#
# `open_failures` é a mesma leitura de trilha que `summarize` usa para contar.
# Vive em `attempts.py` de propósito: se o markdown decidisse por conta própria
# o que é "tentativa em aberto", o bloco legível e o disjuntor poderiam
# discordar — e a pessoa leria uma coisa enquanto a máquina contava outra.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OpenCase:
    records: list[dict]
    expect_lines: list[str]
    why: str


OPEN_CASES = [
    OpenCase([], [], "rastro vazio"),
    OpenCase([_fail("a")], ["a"], "uma falha aberta"),
    OpenCase([_fail("a"), _fail("b")], ["a", "b"], "duas falhas em ordem cronológica"),
    OpenCase([_fail("a"), _pass()], [], "o verde encerrou a sequência"),
    OpenCase([_fail("a"), _pass(), _fail("b")], ["b"], "só o que veio depois do verde"),
    OpenCase([_pass()], [], "só verde"),
]


@pytest.mark.parametrize("case", OPEN_CASES, ids=lambda c: c.why)
def test_open_failures_returns_only_the_unresolved_run(case: OpenCase) -> None:
    assert [r["failure_line"] for r in open_failures(case.records)] == case.expect_lines


# ---------------------------------------------------------------------------
# REGRA 2 — a linha diz o que foi tentado, com que erro e com que assinatura
#
# A assinatura aparece porque é ela que torna "de novo a mesma coisa" visível a
# olho nu: duas linhas com o mesmo `sig` são o padrão repetido de §8.2 antes
# mesmo de o disjuntor falar.
# ---------------------------------------------------------------------------

def test_rendered_lines_carry_number_exit_code_error_and_signature() -> None:
    section = render_attempts_section("T-01", [_fail("E assert 1 == 2", exit_code=2)])

    assert "### Tentativas — T-01" in section
    assert "1." in section
    assert "exit 2" in section
    assert "E assert 1 == 2" in section
    assert failure_signature("E assert 1 == 2") in section


def test_rendered_lines_are_numbered_in_order() -> None:
    section = render_attempts_section("T-01", [_fail("primeira"), _fail("segunda")])
    assert section.index("1.") < section.index("2.")
    assert section.index("primeira") < section.index("segunda")


def test_repeated_signature_is_visible_as_such() -> None:
    section = render_attempts_section("T-01", [_fail("igual"), _fail("igual")])
    assert section.count(failure_signature("igual")) == 2


# ---------------------------------------------------------------------------
# REGRA 3 — o bloco é uma região GERENCIADA: entra, atualiza e some sozinho
#
# Mesma técnica dos blocos do AGENTS.md (delimitadores em comentário): o
# arquivo continua sendo do agente, e o harness só manda dentro da região que
# ele mesmo criou.
# ---------------------------------------------------------------------------

def test_first_failure_creates_the_managed_region(tmp_path: Path) -> None:
    path = _write_progress(tmp_path)

    assert update_progress_attempts(tmp_path, "T-01", [_fail("boom")]) is True

    text = path.read_text(encoding="utf-8")
    assert ATTEMPTS_BEGIN in text and ATTEMPTS_END in text
    assert "boom" in text


def test_next_failure_replaces_instead_of_duplicating(tmp_path: Path) -> None:
    path = _write_progress(tmp_path)

    update_progress_attempts(tmp_path, "T-01", [_fail("primeira")])
    update_progress_attempts(tmp_path, "T-01", [_fail("primeira"), _fail("segunda")])

    text = path.read_text(encoding="utf-8")
    assert text.count(ATTEMPTS_BEGIN) == 1
    assert text.count("### Tentativas — T-01") == 1
    assert text.count("primeira") == 1
    assert "segunda" in text


def test_the_green_removes_the_block_and_the_empty_region(tmp_path: Path) -> None:
    """A fatia saiu de 'em andamento': o histórico permanente é o jsonl, e
    deixar o bloco no progress.md faria a próxima sessão ler pendência onde há
    prova."""
    path = _write_progress(tmp_path)
    update_progress_attempts(tmp_path, "T-01", [_fail("boom")])

    update_progress_attempts(tmp_path, "T-01", [])

    text = path.read_text(encoding="utf-8")
    assert "boom" not in text
    assert ATTEMPTS_BEGIN not in text
    assert "## Features" in text


def test_two_features_coexist_and_are_removed_independently(tmp_path: Path) -> None:
    path = _write_progress(tmp_path)

    update_progress_attempts(tmp_path, "T-01", [_fail("erro um")])
    update_progress_attempts(tmp_path, "T-02", [_fail("erro dois")])
    update_progress_attempts(tmp_path, "T-01", [])

    text = path.read_text(encoding="utf-8")
    assert "erro um" not in text
    assert "erro dois" in text
    assert text.count(ATTEMPTS_BEGIN) == 1


def test_the_rest_of_the_file_is_never_touched(tmp_path: Path) -> None:
    path = _write_progress(tmp_path)
    before = path.read_text(encoding="utf-8")

    update_progress_attempts(tmp_path, "T-01", [_fail("boom")])
    update_progress_attempts(tmp_path, "T-01", [])

    assert path.read_text(encoding="utf-8").rstrip("\n") == before.rstrip("\n")


# ---------------------------------------------------------------------------
# REGRA 4 — no-op silencioso: sincronizar o legível nunca derruba nada
#
# Mesma regra de `update_progress_status`/`append_progress_note`, e o motivo é
# o mesmo: quem chama é o `run_verify`, no meio de uma verificação.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NoOpCase:
    create_file: bool
    records: list[dict]
    why: str


NOOP_CASES = [
    NoOpCase(False, [_fail("boom")], "progress.md ausente: não cria o arquivo"),
    NoOpCase(False, [], "ausente e sem falhas: nada a fazer"),
]


@pytest.mark.parametrize("case", NOOP_CASES, ids=lambda c: c.why)
def test_update_progress_attempts_is_a_silent_noop(tmp_path: Path, case: NoOpCase) -> None:
    assert update_progress_attempts(tmp_path, "T-01", case.records) is False
    assert not _progress(tmp_path).exists()


def test_removing_a_block_that_never_existed_changes_nothing(tmp_path: Path) -> None:
    path = _write_progress(tmp_path)
    before = path.read_text(encoding="utf-8")

    assert update_progress_attempts(tmp_path, "T-99", []) is False
    assert path.read_text(encoding="utf-8") == before


# ---------------------------------------------------------------------------
# REGRA 5 — o caminho real: falhar e passar pelo `run_verify` mantém o bloco
# em dia sem ninguém escrever markdown à mão
# ---------------------------------------------------------------------------

def test_run_verify_keeps_the_block_in_sync(tmp_path: Path) -> None:
    import sys

    from harness.verify import VerifyFailedError, run_verify

    is_windows = sys.platform.startswith("win")
    _write(tmp_path / "src" / "x.py", "print('hi')\n")
    _write_progress(tmp_path)

    def _setup(verify_cmd: str) -> None:
        _write(
            tmp_path / ".harness" / "feature_list.json",
            json.dumps({
                "contract": "exemplo",
                "compiled_at": "2026-08-09T04:00:00+00:00",
                "features": [{
                    "id": "T-01",
                    "desc": "Fazer alguma coisa",
                    "files": ["src/x.py"],
                    "verify_cmd": verify_cmd,
                    "depends": [],
                    "passes": False,
                }],
            }, indent=2, ensure_ascii=False) + "\n",
        )

    _setup("echo quebrou& exit 1" if is_windows else "echo 'quebrou'; exit 1")
    with pytest.raises(VerifyFailedError):
        run_verify(tmp_path, "T-01")

    text = _progress(tmp_path).read_text(encoding="utf-8")
    assert "quebrou" in text
    assert "### Tentativas — T-01" in text

    _setup("exit 0" if is_windows else "true")
    run_verify(tmp_path, "T-01")

    text = _progress(tmp_path).read_text(encoding="utf-8")
    assert "quebrou" not in text
    assert ATTEMPTS_BEGIN not in text
