"""Testes de `harness.blind` — a camada 3 do §6, com o isolamento de viés do §9.1.

As camadas 1 e 2 provam que o código faz o que o teste diz. Nenhuma das duas
pergunta se o que foi entregue é o que a demanda prometia — e quem responderia
isso, hoje, é a mesma cabeça que implementou.

O que estes testes travam é a AUSÊNCIA: o pacote que o verificador recebe é
derivado do contrato por código, e não pode conter o raciocínio de quem
implementou. Um pacote redigido à mão por quem acabou de escrever o código vaza
a justificativa por construção, sem má-fé nenhuma — e o §9.1 é explícito que
uma avaliação assim já nasce contaminada.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from harness.blind import (
    BLIND_PACKAGE_FILE,
    BLIND_REVIEW_DIR,
    BlindError,
    build_package,
    package_tasks,
    read_review,
    record_verdict,
    render_package,
    review_state,
)


def _feature(
    feature_id: str,
    *,
    desc: str = "",
    files: list[str] | None = None,
    verify_cmd: str = "pytest -q",
) -> dict[str, Any]:
    return {
        "id": feature_id,
        "desc": desc or f"tarefa {feature_id}",
        "files": files if files is not None else [f"src/{feature_id}.py"],
        "verify_cmd": verify_cmd,
        "depends": [],
        "cwd": None,
        "passes": True,
    }


def _write_contract(target_dir: Path, features: list[dict[str, Any]], slug: str = "demanda-x") -> None:
    (target_dir / ".harness").mkdir(parents=True, exist_ok=True)
    (target_dir / ".harness" / "feature_list.json").write_text(
        json.dumps({"contract": slug, "features": features}, ensure_ascii=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# REGRA: o pacote entrega, de cada tarefa, as três coisas que tornam um
# veredito possível — o que foi prometido, onde olhar, e qual era a prova.
# Faltando qualquer uma, o verificador julga no escuro e devolve palpite.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ContentCase:
    why: str
    #: trecho que TEM que aparecer no pacote renderizado.
    expected: str


CONTENT_CASES = [
    ContentCase(why="o criterio de aceitacao de cada tarefa", expected="o tema escuro persiste"),
    ContentCase(why="o id da tarefa, para o veredito poder citar", expected="T-01"),
    ContentCase(why="os arquivos onde o resultado ficou", expected="src/tema.py"),
    ContentCase(why="o teste que a tarefa declarou como prova", expected="pytest tests/test_tema.py -q"),
    ContentCase(why="o contrato a que a entrega pertence", expected="demanda-x"),
]


@pytest.mark.parametrize("case", CONTENT_CASES, ids=lambda c: c.why)
def test_package_carries_what_a_verdict_requires(case: ContentCase) -> None:
    tasks = package_tasks(
        {
            "contract": "demanda-x",
            "features": [
                _feature(
                    "T-01",
                    desc="o tema escuro persiste entre recarregamentos",
                    files=["src/tema.py", "tests/test_tema.py"],
                    verify_cmd="pytest tests/test_tema.py -q",
                )
            ],
        }
    )
    rendered = render_package("demanda-x", tasks)
    assert case.expected in rendered


def test_package_names_the_role_and_forbids_fixing() -> None:
    """§9.1: quem verificou não conserta — devolve o veredito ao loop, que
    decide. Um verificador que corrige o que achou vira o gerador do próximo
    artefato, e o ponto de independência some no mesmo movimento."""
    rendered = render_package("demanda-x", package_tasks({"features": [_feature("T-01")]}))
    lowered = rendered.lower()
    assert "não conserte" in lowered or "nao conserte" in lowered
    assert "veredito" in lowered


def test_package_tells_how_to_return_the_verdict() -> None:
    """Veredito que não tem como voltar é veredito perdido: o verificador roda
    em contexto próprio e some quando termina."""
    rendered = render_package("demanda-x", package_tasks({"features": [_feature("T-01")]}))
    assert "harness blind verdict" in rendered


# ---------------------------------------------------------------------------
# REGRA: o pacote nomeia o que o verificador não deve abrir. É a única defesa
# possível contra a contaminação por leitura — ele é um agente com acesso ao
# repositório, e os arquivos do racional continuam lá no disco.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ForbiddenCase:
    why: str
    path: str


FORBIDDEN_CASES = [
    ForbiddenCase(why="spec.md carrega as decisoes de desenho do gerador", path=".harness/work/demanda-x/spec.md"),
    ForbiddenCase(why="progress.md carrega o historico de tentativas", path=".harness/progress.md"),
    ForbiddenCase(why="decisions.md carrega o porque das escolhas", path=".harness/decisions.md"),
    ForbiddenCase(why="lessons.md carrega as friccoes anotadas", path=".harness/lessons.md"),
]


@pytest.mark.parametrize("case", FORBIDDEN_CASES, ids=lambda c: c.why)
def test_package_names_what_must_not_be_opened(case: ForbiddenCase) -> None:
    rendered = render_package("demanda-x", package_tasks({"features": [_feature("T-01")]}))
    assert case.path in rendered


def test_package_warns_against_the_commit_messages_too() -> None:
    """A mensagem de commit deste projeto é onde o racional mais completo mora
    — e `git log` é a primeira coisa que um agente roda para se situar."""
    rendered = render_package("demanda-x", package_tasks({"features": [_feature("T-01")]}))
    assert "git log" in rendered


# ---------------------------------------------------------------------------
# REGRA: o texto do gerador nunca entra no pacote. Esta é a entrega inteira do
# contrato: um pacote montado por código não tem por onde vazar a justificativa,
# e é por isso que ele não é escrito à mão.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LeakCase:
    why: str
    relative_path: str


LEAK_CASES = [
    LeakCase(why="racional do spec nao vaza", relative_path=".harness/work/demanda-x/spec.md"),
    LeakCase(why="historico de tentativas nao vaza", relative_path=".harness/progress.md"),
    LeakCase(why="decisoes registradas nao vazam", relative_path=".harness/decisions.md"),
    LeakCase(why="licoes anotadas nao vazam", relative_path=".harness/lessons.md"),
]

#: string improvável o bastante para que sua presença só possa vir do arquivo.
CANARY = "CANARIO-DO-RACIONAL-DE-QUEM-IMPLEMENTOU"


@pytest.mark.parametrize("case", LEAK_CASES, ids=lambda c: c.why)
def test_the_generator_reasoning_never_reaches_the_package(tmp_path: Path, case: LeakCase) -> None:
    _write_contract(tmp_path, [_feature("T-01")])
    leaky = tmp_path / case.relative_path
    leaky.parent.mkdir(parents=True, exist_ok=True)
    leaky.write_text(f"# titulo\n\n{CANARY}\n", encoding="utf-8")

    path = build_package(tmp_path)

    assert CANARY not in path.read_text(encoding="utf-8")


def test_build_package_writes_where_the_dispatch_can_read_it(tmp_path: Path) -> None:
    """Arquivo em disco, e não string devolvida: o valor do pacote é poder ser
    despachado como está, sem passar pela redação de quem implementou."""
    _write_contract(tmp_path, [_feature("T-01")])

    path = build_package(tmp_path)

    assert path == tmp_path / BLIND_PACKAGE_FILE
    assert path.is_file()
    assert "T-01" in path.read_text(encoding="utf-8")


def test_a_contract_with_no_tasks_is_not_a_package_to_judge(tmp_path: Path) -> None:
    _write_contract(tmp_path, [])
    with pytest.raises(BlindError):
        build_package(tmp_path)


def test_without_a_compiled_contract_there_is_nothing_to_judge(tmp_path: Path) -> None:
    with pytest.raises(BlindError):
        build_package(tmp_path)


# ---------------------------------------------------------------------------
# REGRA: o veredito fica preso ao estado que julgou. Sem isso, um "aprovado" de
# vinte commits atrás fecha a demanda de hoje — que é exatamente o buraco que a
# evidência da camada 2 já fechou para as fatias.
# ---------------------------------------------------------------------------

def _contract_with_file(tmp_path: Path, content: str = "print(1)\n") -> None:
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "T-01.py").write_text(content, encoding="utf-8")
    _write_contract(tmp_path, [_feature("T-01")])


def test_the_verdict_records_the_hash_of_what_it_judged(tmp_path: Path) -> None:
    _contract_with_file(tmp_path)

    record_verdict(tmp_path, passed=True, evidence="conferi src/T-01.py:1")

    review = read_review(tmp_path)
    assert review is not None
    assert review["verdicts"][-1]["files_hash"].startswith("sha256:")
    assert review["verdicts"][-1]["evidence"] == "conferi src/T-01.py:1"


def test_a_new_verdict_never_erases_the_one_before(tmp_path: Path) -> None:
    """Reprovação que some é reprovação que se re-litiga: a próxima volta do
    loop não sabe que aquilo já foi julgado e recusado uma vez."""
    _contract_with_file(tmp_path)
    record_verdict(tmp_path, passed=False, evidence="faltou o caso vazio em src/T-01.py:1")
    record_verdict(tmp_path, passed=True, evidence="caso vazio coberto em src/T-01.py:3")

    review = read_review(tmp_path)
    assert review is not None
    assert [v["verdict"] for v in review["verdicts"]] == ["fail", "pass"]
    assert review["verdicts"][0]["evidence"] == "faltou o caso vazio em src/T-01.py:1"


def test_a_verdict_without_evidence_is_refused(tmp_path: Path) -> None:
    """§9.1: verificador que só diz 'reprovado' gera re-tentativa cega."""
    _contract_with_file(tmp_path)
    with pytest.raises(BlindError):
        record_verdict(tmp_path, passed=False, evidence="   ")


def test_no_verdict_can_be_recorded_without_a_contract(tmp_path: Path) -> None:
    with pytest.raises(BlindError):
        record_verdict(tmp_path, passed=True, evidence="qualquer coisa")


# ---------------------------------------------------------------------------
# REGRA: o estado do veredito é o que o `finish` consulta. Cada valor manda o
# humano fazer uma coisa diferente, então confundir dois deles é pior do que
# não ter o campo.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StateCase:
    why: str
    #: vereditos a registrar, em ordem: (passou, evidência).
    verdicts: list[tuple[bool, str]]
    #: se o arquivo julgado muda depois dos vereditos.
    touch_after: bool
    expected: str


STATE_CASES = [
    StateCase(why="sem nenhum veredito registrado", verdicts=[], touch_after=False, expected="missing"),
    StateCase(
        why="aprovado sobre o estado atual",
        verdicts=[(True, "conferi")],
        touch_after=False,
        expected="fresh",
    ),
    StateCase(
        why="reprovado sobre o estado atual",
        verdicts=[(False, "nao confere")],
        touch_after=False,
        expected="failed",
    ),
    StateCase(
        why="aprovado antes de o codigo mudar",
        verdicts=[(True, "conferi")],
        touch_after=True,
        expected="stale",
    ),
    StateCase(
        why="reprovado e o codigo mudou depois -- o veredito velho nao descreve mais o codigo",
        verdicts=[(False, "nao confere")],
        touch_after=True,
        expected="stale",
    ),
    StateCase(
        why="o ultimo veredito manda, nao o primeiro",
        verdicts=[(False, "nao confere"), (True, "agora confere")],
        touch_after=False,
        expected="fresh",
    ),
    StateCase(
        why="aprovar e depois reprovar tambem vale -- o ultimo manda nos dois sentidos",
        verdicts=[(True, "conferi"), (False, "achei outra coisa")],
        touch_after=False,
        expected="failed",
    ),
]


@pytest.mark.parametrize("case", STATE_CASES, ids=lambda c: c.why)
def test_review_state_reports_what_the_human_has_to_do(tmp_path: Path, case: StateCase) -> None:
    _contract_with_file(tmp_path)
    for passed, evidence in case.verdicts:
        record_verdict(tmp_path, passed=passed, evidence=evidence)
    if case.touch_after:
        (tmp_path / "src" / "T-01.py").write_text("print(2)\n", encoding="utf-8")

    assert review_state(tmp_path)["state"] == case.expected


def test_an_unreadable_review_is_not_a_valid_verdict(tmp_path: Path) -> None:
    """Arquivo corrompido não pode virar 'aprovado' por omissão — falha de
    leitura aqui é ausência de veredito, e o fecho volta a cobrar um."""
    _contract_with_file(tmp_path)
    path = tmp_path / BLIND_REVIEW_DIR / "demanda-x.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ isto nao e json", encoding="utf-8")

    assert review_state(tmp_path)["state"] == "missing"
