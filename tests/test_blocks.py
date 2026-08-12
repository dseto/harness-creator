"""Testes de `harness.blocks` — o estado "parei, é sua vez".

T-01 do contrato `parei-e-sua-vez`. Até aqui uma feature só existia em dois
estados (`passes: true|false`), e por isso "estou esperando o humano" era
indistinguível de "ainda não implementei": o supervisor devolvia a tarefa como
próxima, o hook Stop cobrava verificação, e o agente repetia o que ele mesmo
já tinha explicado que não tinha como funcionar.

Este módulo é só o registro do bloqueio. Quem para de oferecer a tarefa é
`supervisor` (T-02); quem para de cobrar é o hook Stop (T-03); quem mostra é
`panel`/`templates` (T-04); quem impede o fecho é `finish` (T-06). Um teste
por REGRA, com tabela de casos — não um `def` por caso.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from harness.blocks import (
    BLOCKS_DIR,
    UNSCOPED_BLOCKS_DIR,
    BlockError,
    block_path,
    clear_block,
    is_blocked,
    list_blocks,
    read_block,
    record_block,
)

RECORDED_AT = "2026-08-12T01:00:00+00:00"


# ---------------------------------------------------------------------------
# REGRA 1 — o bloqueio é escopado por contrato, espelhando `attempts_path`
#
# Todo contrato começa em `T-01`. Bloqueio não escopado faria o contrato novo
# nascer com uma tarefa parada que outro contrato declarou — e o supervisor
# pularia uma fatia que ninguém pediu para pular.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PathCase:
    contract: object
    expected_dir: str
    why: str


PATH_CASES = [
    PathCase("meu-contrato", "meu-contrato", "slug normal vira subdiretório"),
    PathCase("", UNSCOPED_BLOCKS_DIR, "contrato vazio cai no diretório sem-contrato"),
    PathCase(None, UNSCOPED_BLOCKS_DIR, "contrato ausente cai no diretório sem-contrato"),
    PathCase("  ", UNSCOPED_BLOCKS_DIR, "só espaço conta como ausente"),
    PathCase("  outro  ", "outro", "espaço em volta não vira parte do nome"),
]


@pytest.mark.parametrize("case", PATH_CASES, ids=lambda c: c.why)
def test_block_path_is_scoped_by_contract(tmp_path: Path, case: PathCase) -> None:
    path = block_path(tmp_path, case.contract, "T-01")
    assert path == tmp_path / BLOCKS_DIR / case.expected_dir / "T-01.json"


def test_block_path_never_collides_between_contracts(tmp_path: Path) -> None:
    assert block_path(tmp_path, "contrato-a", "T-01") != block_path(
        tmp_path, "contrato-b", "T-01"
    )


# ---------------------------------------------------------------------------
# REGRA 2 — motivo é obrigatório, e recusa não deixa arquivo para trás
#
# O freio contra o bloqueio virar fuga de trabalho difícil é o motivo ser
# acionável e visível. Bloqueio sem motivo é exatamente o estado que já
# existia (`passes: false` mudo) com um nome novo — então não pode nascer.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReasonCase:
    needs: object
    why: str


REJECTED_REASONS = [
    ReasonCase("", "motivo vazio"),
    ReasonCase("   ", "só espaço"),
    ReasonCase("\n\t  \n", "só quebra de linha e tab"),
    ReasonCase(None, "motivo ausente"),
]


@pytest.mark.parametrize("case", REJECTED_REASONS, ids=lambda c: c.why)
def test_record_block_requires_a_reason(tmp_path: Path, case: ReasonCase) -> None:
    with pytest.raises(BlockError):
        record_block(
            tmp_path,
            "meu-contrato",
            "T-01",
            needs=case.needs,
            recorded_at=RECORDED_AT,
        )
    assert not block_path(tmp_path, "meu-contrato", "T-01").exists()
    assert not is_blocked(tmp_path, "meu-contrato", "T-01")


# ---------------------------------------------------------------------------
# REGRA 3 — id fora do contrato ativo é recusado
#
# `known_ids` vem de quem já leu o `feature_list.json` (a CLI). Este módulo
# nunca lê aquele arquivo — mesma divisão de `attempts.py`, que grava e conta
# sem nunca abrir o contrato.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class KnownIdsCase:
    feature_id: str
    known_ids: object
    accepted: bool
    why: str


KNOWN_IDS_CASES = [
    KnownIdsCase("T-01", ["T-01", "T-02"], True, "id do contrato é aceito"),
    KnownIdsCase("T-09", ["T-01", "T-02"], False, "id fora do contrato é recusado"),
    KnownIdsCase("T-01", [], False, "contrato sem features recusa qualquer id"),
    KnownIdsCase("T-09", None, True, "sem lista declarada, não há o que conferir"),
]


@pytest.mark.parametrize("case", KNOWN_IDS_CASES, ids=lambda c: c.why)
def test_record_block_rejects_unknown_feature(tmp_path: Path, case: KnownIdsCase) -> None:
    def _call() -> Path:
        return record_block(
            tmp_path,
            "meu-contrato",
            case.feature_id,
            needs="editar test_glob em .harness/harness.yaml e rodar compile-session",
            recorded_at=RECORDED_AT,
            known_ids=case.known_ids,
        )

    if case.accepted:
        assert _call().is_file()
    else:
        with pytest.raises(BlockError):
            _call()
        assert not block_path(tmp_path, "meu-contrato", case.feature_id).exists()


# ---------------------------------------------------------------------------
# REGRA 4 — o registro guarda o motivo íntegro e o que a leitura precisa
#
# O motivo é a frase que o humano vai ler no placar, no progresso e no fecho.
# Reescrever, truncar ou resumir aqui é jogar fora exatamente o que faz o
# bloqueio ser acionável em vez de mais um "pendente".
# ---------------------------------------------------------------------------

NEEDS = "editar test_glob na linha 27 de .harness/harness.yaml e rodar harness compile-session"


def test_record_block_keeps_the_reason_intact(tmp_path: Path) -> None:
    path = record_block(
        tmp_path, "meu-contrato", "T-04", needs=NEEDS, recorded_at=RECORDED_AT
    )

    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["needs"] == NEEDS
    assert record["feature_id"] == "T-04"
    assert record["contract"] == "meu-contrato"
    assert record["recorded_at"] == RECORDED_AT
    assert record["watch"] is None


def test_record_block_trims_only_the_edges_of_the_reason(tmp_path: Path) -> None:
    path = record_block(
        tmp_path, "meu-contrato", "T-04", needs="  " + NEEDS + "  ", recorded_at=RECORDED_AT
    )
    assert json.loads(path.read_text(encoding="utf-8"))["needs"] == NEEDS


def test_record_block_records_the_watched_file_when_given(tmp_path: Path) -> None:
    path = record_block(
        tmp_path,
        "meu-contrato",
        "T-04",
        needs=NEEDS,
        recorded_at=RECORDED_AT,
        watch=".harness/harness.yaml",
    )
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["watch"] == ".harness/harness.yaml"


def test_record_block_replaces_the_previous_block_of_the_same_feature(tmp_path: Path) -> None:
    record_block(tmp_path, "meu-contrato", "T-04", needs="motivo velho", recorded_at=RECORDED_AT)
    record_block(tmp_path, "meu-contrato", "T-04", needs=NEEDS, recorded_at=RECORDED_AT)

    block = read_block(tmp_path, "meu-contrato", "T-04")
    assert block is not None
    assert block["needs"] == NEEDS


# ---------------------------------------------------------------------------
# REGRA 5 — leitura degrada graciosamente: ausente ou corrompido não é bloqueio
#
# Mesma postura de `read_attempts` e `supervisor.dispatch_next`: o bloqueio é
# estado de sessão, e um arquivo escrito pela metade não pode derrubar a
# leitura nem — pior — travar uma tarefa que ninguém declarou parada.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReadCase:
    content: object
    why: str


UNREADABLE_CASES = [
    ReadCase(None, "arquivo ausente"),
    ReadCase("", "arquivo vazio"),
    ReadCase("{ nao e json", "json inválido"),
    ReadCase('"uma string"', "json válido que não é objeto"),
    ReadCase("[]", "json válido que é lista"),
    ReadCase('{"feature_id": "T-04"}', "objeto sem motivo não é bloqueio"),
    ReadCase('{"needs": "   ", "feature_id": "T-04"}', "motivo em branco não é bloqueio"),
]


@pytest.mark.parametrize("case", UNREADABLE_CASES, ids=lambda c: c.why)
def test_read_block_degrades_to_none(tmp_path: Path, case: ReadCase) -> None:
    path = block_path(tmp_path, "meu-contrato", "T-04")
    if case.content is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(case.content), encoding="utf-8")

    assert read_block(tmp_path, "meu-contrato", "T-04") is None
    assert not is_blocked(tmp_path, "meu-contrato", "T-04")


def test_is_blocked_is_true_only_for_the_blocked_feature(tmp_path: Path) -> None:
    record_block(tmp_path, "meu-contrato", "T-04", needs=NEEDS, recorded_at=RECORDED_AT)

    assert is_blocked(tmp_path, "meu-contrato", "T-04")
    assert not is_blocked(tmp_path, "meu-contrato", "T-01")
    assert not is_blocked(tmp_path, "outro-contrato", "T-04")


# ---------------------------------------------------------------------------
# REGRA 6 — a lista devolve todos os bloqueios do contrato, em ordem estável
#
# `finish` (T-06) e o placar (T-04) precisam nomear TODAS as tarefas paradas,
# não a primeira. Ordem por id para o relatório não mudar entre execuções.
# ---------------------------------------------------------------------------

def test_list_blocks_returns_every_block_sorted_by_id(tmp_path: Path) -> None:
    for feature_id in ("T-07", "T-02", "T-04"):
        record_block(
            tmp_path, "meu-contrato", feature_id, needs=NEEDS, recorded_at=RECORDED_AT
        )

    blocks = list_blocks(tmp_path, "meu-contrato")
    assert [b["feature_id"] for b in blocks] == ["T-02", "T-04", "T-07"]


def test_list_blocks_skips_corrupted_entries(tmp_path: Path) -> None:
    record_block(tmp_path, "meu-contrato", "T-02", needs=NEEDS, recorded_at=RECORDED_AT)
    corrupted = block_path(tmp_path, "meu-contrato", "T-05")
    corrupted.parent.mkdir(parents=True, exist_ok=True)
    corrupted.write_text("{ nao e json", encoding="utf-8")

    assert [b["feature_id"] for b in list_blocks(tmp_path, "meu-contrato")] == ["T-02"]


def test_list_blocks_of_a_contract_without_blocks_is_empty(tmp_path: Path) -> None:
    assert list_blocks(tmp_path, "meu-contrato") == []


# ---------------------------------------------------------------------------
# REGRA 7 — o verbo da CLI é o que o agente tem à mão
#
# O módulo pode estar perfeito e o defeito continuar de pé se o agente não
# tiver como chamá-lo no meio do trabalho. Aqui o contrato ativo é lido de
# `feature_list.json` (o módulo nunca o abre) e o id é conferido contra ele.
# ---------------------------------------------------------------------------

def _contract(tmp_path: Path, *, contract: str = "meu-contrato") -> None:
    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir(parents=True, exist_ok=True)
    (harness_dir / "feature_list.json").write_text(
        json.dumps(
            {
                "contract": contract,
                "features": [
                    {
                        "id": "T-01",
                        "desc": "primeira",
                        "passes": False,
                        "files": [],
                        "verify_cmd": 'python -c "pass"',
                    },
                    {
                        "id": "T-02",
                        "desc": "segunda",
                        "passes": False,
                        "files": [],
                        "verify_cmd": 'python -c "pass"',
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


def _run_cli(argv: list[str], monkeypatch: pytest.MonkeyPatch) -> int:
    from harness.cli import main

    monkeypatch.setattr(sys, "argv", ["harness", *argv])
    with pytest.raises(SystemExit) as exc:
        main()
    return int(exc.value.code or 0)


def test_cli_block_records_the_block_under_the_active_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _contract(tmp_path)

    code = _run_cli(["block", "T-01", "--needs", NEEDS, "--dir", str(tmp_path)], monkeypatch)

    assert code == 0
    block = read_block(tmp_path, "meu-contrato", "T-01")
    assert block is not None
    assert block["needs"] == NEEDS


def test_cli_block_records_the_watched_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _contract(tmp_path)

    code = _run_cli(
        [
            "block",
            "T-01",
            "--needs",
            NEEDS,
            "--watch",
            ".harness/harness.yaml",
            "--dir",
            str(tmp_path),
        ],
        monkeypatch,
    )

    assert code == 0
    block = read_block(tmp_path, "meu-contrato", "T-01")
    assert block is not None
    assert block["watch"] == ".harness/harness.yaml"


@dataclass(frozen=True)
class CliRefusalCase:
    argv_tail: list[str]
    with_contract: bool
    why: str


CLI_REFUSALS = [
    CliRefusalCase(["T-09", "--needs", NEEDS], True, "id fora do contrato ativo"),
    CliRefusalCase(["T-01", "--needs", "   "], True, "motivo em branco"),
    CliRefusalCase(["T-01", "--needs", NEEDS], False, "sem contrato compilado"),
]


@pytest.mark.parametrize("case", CLI_REFUSALS, ids=lambda c: c.why)
def test_cli_block_refuses_and_writes_nothing(
    tmp_path: Path, case: CliRefusalCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    if case.with_contract:
        _contract(tmp_path)

    code = _run_cli(["block", *case.argv_tail, "--dir", str(tmp_path)], monkeypatch)

    assert code == 1
    assert not (tmp_path / BLOCKS_DIR).exists()


# ---------------------------------------------------------------------------
# REGRA 8 — a fatia volta a andar por três caminhos, e só por eles
#
# Sem expiração por tempo (não-objetivo do spec): bloqueio que caduca sozinho
# volta a empurrar trabalho contra a mesma parede, com atraso. Os três são: a
# pessoa libera; o arquivo declarado como esperado mudou; a verificação passou.
# ---------------------------------------------------------------------------

def test_clearing_a_block_removes_it(tmp_path: Path) -> None:
    record_block(tmp_path, "meu-contrato", "T-04", needs=NEEDS, recorded_at=RECORDED_AT)

    assert clear_block(tmp_path, "meu-contrato", "T-04") is True
    assert not is_blocked(tmp_path, "meu-contrato", "T-04")


def test_clearing_a_feature_that_was_not_blocked_is_a_silent_noop(tmp_path: Path) -> None:
    assert clear_block(tmp_path, "meu-contrato", "T-04") is False


@dataclass(frozen=True)
class WatchCase:
    watch: str | None
    change_file: bool
    still_blocked: bool
    why: str


WATCH_CASES = [
    WatchCase("cfg.yaml", True, False, "o arquivo esperado mudou: destrava"),
    WatchCase("cfg.yaml", False, True, "arquivo intacto: continua parada"),
    WatchCase(None, True, True, "sem arquivo declarado, só a pessoa destrava"),
    WatchCase("nao-existe.yaml", False, True, "arquivo esperado que nem existe não destrava"),
]


def test_creating_the_awaited_file_is_a_change(tmp_path: Path) -> None:
    """"Crie este arquivo" é espera legítima e comum. Com o carimbo de ausente
    valendo `None`, a comparação ficava desligada e essa espera nunca terminava
    — a documentação prometia um destrave que o código não entregava."""
    record_block(
        tmp_path,
        "meu-contrato",
        "T-04",
        needs=NEEDS,
        recorded_at=RECORDED_AT,
        watch="vitest.config.ts",
    )
    assert is_blocked(tmp_path, "meu-contrato", "T-04")

    (tmp_path / "vitest.config.ts").write_text("export default {}\n", encoding="utf-8")

    assert not is_blocked(tmp_path, "meu-contrato", "T-04")


def test_the_progress_column_stops_lying_after_the_watch_unblocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Depois que o arquivo esperado muda, quatro superfícies já veem a fatia
    liberada — mas o `progress.md` guarda o texto da espera numa coluna
    ESCRITA, e é ele que a próxima sessão lê primeiro. Sem liquidar, a sessão
    nova abre acreditando numa espera que acabou."""
    from harness.templates import PROGRESS_FILE, render_progress_template

    _contract(tmp_path)
    feature_list = json.loads(
        (tmp_path / ".harness" / "feature_list.json").read_text(encoding="utf-8")
    )
    (tmp_path / PROGRESS_FILE).write_text(
        render_progress_template(feature_list), encoding="utf-8"
    )
    watched = tmp_path / "cfg.yaml"
    watched.write_text("antes\n", encoding="utf-8")

    assert _run_cli(
        ["block", "T-01", "--needs", NEEDS, "--watch", "cfg.yaml", "--dir", str(tmp_path)],
        monkeypatch,
    ) == 0
    assert "AGUARDANDO" in (tmp_path / PROGRESS_FILE).read_text(encoding="utf-8")

    watched.write_text("depois\n", encoding="utf-8")
    _run_cli(["supervise", "--dir", str(tmp_path)], monkeypatch)

    table = (tmp_path / PROGRESS_FILE).read_text(encoding="utf-8")
    row = next(line for line in table.splitlines() if line.startswith("| T-01 "))
    assert "AGUARDANDO" not in row
    assert not block_path(tmp_path, "meu-contrato", "T-01").exists()


def test_settling_leaves_a_live_block_alone(tmp_path: Path) -> None:
    from harness.blocks import settle_blocks

    record_block(tmp_path, "meu-contrato", "T-01", needs=NEEDS, recorded_at=RECORDED_AT)

    assert settle_blocks(tmp_path, "meu-contrato") == []
    assert is_blocked(tmp_path, "meu-contrato", "T-01")


def test_settling_never_destroys_a_corrupted_block(tmp_path: Path) -> None:
    """Registro corrompido já não bloqueia (`read_block`), mas apagá-lo seria
    jogar fora o artefato de perícia justamente no caso em que alguém vai
    querer olhar o que aconteceu."""
    from harness.blocks import settle_blocks

    corrupted = block_path(tmp_path, "meu-contrato", "T-02")
    corrupted.parent.mkdir(parents=True, exist_ok=True)
    corrupted.write_text("{ nao e json", encoding="utf-8")

    assert settle_blocks(tmp_path, "meu-contrato") == []
    assert corrupted.is_file()


def test_a_diagnostic_command_never_settles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`harness doctor` e `harness health` são justificados por escrito como
    read-only na allowlist do guard. Perguntar pelo estado não pode mudá-lo."""
    _contract(tmp_path)
    watched = tmp_path / "cfg.yaml"
    watched.write_text("antes\n", encoding="utf-8")
    record_block(
        tmp_path,
        "meu-contrato",
        "T-01",
        needs=NEEDS,
        recorded_at=RECORDED_AT,
        watch="cfg.yaml",
    )
    watched.write_text("depois\n", encoding="utf-8")

    _run_cli(["doctor", "--dir", str(tmp_path)], monkeypatch)

    assert block_path(tmp_path, "meu-contrato", "T-01").is_file()


def test_an_unreadable_watched_file_keeps_the_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Erro de I/O é NÃO SEI, não "mudou". No Windows um arquivo travado no
    meio de um save de editor levanta PermissionError — tratar isso como
    mudança destravaria trabalho sozinho, em silêncio."""
    from harness import blocks as blocks_module

    watched = tmp_path / "cfg.yaml"
    watched.write_text("antes\n", encoding="utf-8")
    record_block(
        tmp_path, "meu-contrato", "T-04", needs=NEEDS, recorded_at=RECORDED_AT, watch="cfg.yaml"
    )

    def _boom(self: Path) -> bytes:
        raise PermissionError("arquivo travado por outro processo")

    monkeypatch.setattr(blocks_module.Path, "read_bytes", _boom)

    assert is_blocked(tmp_path, "meu-contrato", "T-04")


@pytest.mark.parametrize("case", WATCH_CASES, ids=lambda c: c.why)
def test_a_block_clears_when_the_watched_file_changes(tmp_path: Path, case: WatchCase) -> None:
    watched = tmp_path / "cfg.yaml"
    watched.write_text("test_glob: '**/*.test.ts'\n", encoding="utf-8")

    record_block(
        tmp_path,
        "meu-contrato",
        "T-04",
        needs=NEEDS,
        recorded_at=RECORDED_AT,
        watch=case.watch,
    )

    if case.change_file:
        watched.write_text("test_glob: 'src/**/*.test.ts'\n", encoding="utf-8")

    assert is_blocked(tmp_path, "meu-contrato", "T-04") is case.still_blocked


def test_the_watched_hash_is_taken_when_the_block_is_declared(tmp_path: Path) -> None:
    """Sem carimbar o conteúdo no momento da declaração não há com o que
    comparar depois — e o bloqueio ou nunca destrava, ou destrava na primeira
    leitura."""
    watched = tmp_path / "cfg.yaml"
    watched.write_text("antes\n", encoding="utf-8")
    path = record_block(
        tmp_path, "meu-contrato", "T-04", needs=NEEDS, recorded_at=RECORDED_AT, watch="cfg.yaml"
    )

    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["watch_hash"], "o carimbo do arquivo esperado precisa estar no registro"


def test_a_green_verify_clears_the_block(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Se passou, o que travava deixou de travar. Manter o registro seria outra
    mentira de estado — e a fatia sumiria da fila estando pronta."""
    from harness import verify as verify_module

    _contract(tmp_path)
    record_block(tmp_path, "meu-contrato", "T-01", needs=NEEDS, recorded_at=RECORDED_AT)

    monkeypatch.chdir(tmp_path)
    verify_module.run_verify(tmp_path, "T-01")

    assert not is_blocked(tmp_path, "meu-contrato", "T-01")


def test_the_guard_lets_the_agent_declare_a_block(tmp_path: Path) -> None:
    """Sem o verbo na superfície do guard, o agente que esbarra numa dependência
    humana não consegue REGISTRAR isso — e volta a repetir a tentativa contra a
    mesma parede, que é o defeito exato que este contrato corrige."""
    from harness.boundary_guard import HARNESS_CLI_VERBS

    assert "block" in HARNESS_CLI_VERBS
