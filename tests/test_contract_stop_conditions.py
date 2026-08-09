"""Testes das stop conditions TIPADAS do contrato.

T-03 do contrato `rastro-de-tentativas-e-budget`. Arquivo dedicado (não
anexado a `test_contract.py`) pelo motivo já declarado naquele arquivo: não
colidir com tarefas concorrentes que editam o mesmo módulo.

O problema fechado aqui: `stop_conditions:` sempre existiu no frontmatter do
`spec.md` e sempre foi **string livre** — "3 falhas consecutivas da mesma suíte
de teste" é uma frase que o agente lê e interpreta. O passo 10 do lifecycle a
chama de "disjuntor do loop", mas nada nem ninguém contava: um disjuntor que
depende de o agente lembrar de contar não é disjuntor, é sugestão. A forma
tipada existe para que `harness budget` (T-04) leia um número.

Compatibilidade é requisito, não gentileza: contratos já compilados usam a
forma string, e ela continua valendo como advisory — o que muda é que agora
existe uma forma que a máquina entende.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from harness.contract import (
    ContractError,
    compile_contract,
    get_stop_conditions,
    parse_stop_conditions,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_contract(tmp_path: Path, stop_conditions_block: str, slug: str = "exemplo") -> None:
    _write(
        tmp_path / ".harness" / "work" / slug / "spec.md",
        "---\n"
        f"slug: {slug}\n"
        "approved_by: alice\n"
        "approved_at: 2026-08-09T04:00:00Z\n"
        f"{stop_conditions_block}"
        "---\n\n# Spec\n",
    )
    _write(
        tmp_path / ".harness" / "work" / slug / "Plans.md",
        "## [T-01] Fazer alguma coisa\n"
        "- files: `src/x.py`\n"
        "- verify: `pytest -q`\n",
    )


# ---------------------------------------------------------------------------
# REGRA 1 — as duas formas convivem: dict vira teto contável, string vira aviso
#
# A separação é o ponto todo. O que a máquina conta precisa de `type` e `n`; o
# que só o agente interpreta continua sendo prosa, e prosa nunca vira número
# por inferência.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SplitCase:
    raw: object
    typed: list[dict]
    advisory: list[str]
    why: str


SPLIT_CASES = [
    SplitCase(None, [], [], "chave ausente"),
    SplitCase([], [], [], "lista vazia"),
    SplitCase(
        ["3 falhas consecutivas da mesma suíte"],
        [],
        ["3 falhas consecutivas da mesma suíte"],
        "só string: forma histórica intacta",
    ),
    SplitCase(
        [42],
        [],
        ["42"],
        "escalar não-string vira advisory por str(), como sempre foi",
    ),
    SplitCase(
        [{"type": "consecutive_verify_failures", "n": 3}],
        [{"type": "consecutive_verify_failures", "n": 3}],
        [],
        "só tipada",
    ),
    SplitCase(
        [{"type": "same_failure_signature", "n": 2}],
        [{"type": "same_failure_signature", "n": 2}],
        [],
        "a outra tipada suportada",
    ),
    SplitCase(
        [{"type": "consecutive_verify_failures", "n": 3}, "sinal de impossibilidade"],
        [{"type": "consecutive_verify_failures", "n": 3}],
        ["sinal de impossibilidade"],
        "mistura das duas formas no mesmo contrato",
    ),
    SplitCase(
        [
            {"type": "consecutive_verify_failures", "n": 5},
            {"type": "same_failure_signature", "n": 2},
        ],
        [
            {"type": "consecutive_verify_failures", "n": 5},
            {"type": "same_failure_signature", "n": 2},
        ],
        [],
        "as duas tipadas juntas",
    ),
]


@pytest.mark.parametrize("case", SPLIT_CASES, ids=lambda c: c.why)
def test_parse_stop_conditions_splits_typed_from_advisory(case: SplitCase) -> None:
    parsed = parse_stop_conditions(case.raw)
    assert parsed["typed"] == case.typed
    assert parsed["advisory"] == case.advisory


# ---------------------------------------------------------------------------
# REGRA 2 — typo em condição tipada é ERRO de compilação, nunca advisory mudo
#
# Fail-closed (§2.4 do design). O modo de falha que isto evita: alguém escreve
# `consecutive_verify_failure` (sem o "s"), o parser não reconhece, e a condição
# vira uma string de aviso que ninguém conta — o contrato PARECE ter disjuntor e
# não tem. Silêncio é o pior resultado possível para um mecanismo de segurança.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RejectCase:
    raw: object
    fragment: str
    why: str


REJECT_CASES = [
    RejectCase([{"type": "consecutive_verify_failure", "n": 3}], "consecutive_verify_failure", "typo no tipo"),
    RejectCase([{"type": "budget_usd", "max": 5}], "budget_usd", "tipo não suportado nesta versão"),
    RejectCase([{"n": 3}], "type", "dict sem type"),
    RejectCase([{"type": "consecutive_verify_failures"}], "n", "tipada sem n"),
    RejectCase([{"type": "consecutive_verify_failures", "n": 0}], "n", "n zero não é teto"),
    RejectCase([{"type": "consecutive_verify_failures", "n": -1}], "n", "n negativo"),
    RejectCase([{"type": "consecutive_verify_failures", "n": "3"}], "n", "n string não é inteiro"),
    RejectCase([{"type": "consecutive_verify_failures", "n": 1.5}], "n", "n fracionário"),
    RejectCase([{"type": "consecutive_verify_failures", "n": True}], "n", "booleano não é contagem"),
    RejectCase([["consecutive_verify_failures", 3]], "stop_conditions", "item que não é nem string nem dict"),
    RejectCase("3 falhas", "stop_conditions", "valor escalar no lugar da lista"),
]


@pytest.mark.parametrize("case", REJECT_CASES, ids=lambda c: c.why)
def test_parse_stop_conditions_rejects_malformed_typed_entries(case: RejectCase) -> None:
    with pytest.raises(ContractError) as excinfo:
        parse_stop_conditions(case.raw)
    assert case.fragment in str(excinfo.value)


# ---------------------------------------------------------------------------
# REGRA 3 — o acessor histórico continua devolvendo só as strings
#
# `get_stop_conditions` já tem consumidor (passo 10 do lifecycle, via prosa) e
# assinatura `list[str]`. Fazer ele passar a devolver dicts quebraria quem já
# chama; a forma tipada tem caminho próprio.
# ---------------------------------------------------------------------------

def test_get_stop_conditions_still_returns_only_the_advisory_strings(tmp_path: Path) -> None:
    _write_contract(
        tmp_path,
        "stop_conditions:\n"
        "  - \"sinal de impossibilidade\"\n"
        "  - {type: consecutive_verify_failures, n: 3}\n",
    )
    spec_path = tmp_path / ".harness" / "work" / "exemplo" / "spec.md"
    assert get_stop_conditions(spec_path) == ["sinal de impossibilidade"]


# ---------------------------------------------------------------------------
# REGRA 4 — a forma compilada viaja no feature_list.json, de forma aditiva
#
# `budget` (T-04) lê o `feature_list.json`, não o `spec.md`: o contrato
# compilado é a fonte que o runtime consome. A chave é nova e ninguém que já
# lê o arquivo depende dela — nada quebra.
# ---------------------------------------------------------------------------

def test_compile_contract_carries_the_stop_conditions(tmp_path: Path) -> None:
    _write_contract(
        tmp_path,
        "stop_conditions:\n"
        "  - {type: consecutive_verify_failures, n: 4}\n"
        "  - \"dependência inexistente\"\n",
    )

    path = compile_contract(tmp_path, "exemplo")
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["stop_conditions"] == {
        "typed": [{"type": "consecutive_verify_failures", "n": 4}],
        "advisory": ["dependência inexistente"],
    }
    assert [f["id"] for f in payload["features"]] == ["T-01"]


def test_compile_contract_without_stop_conditions_still_carries_the_key(tmp_path: Path) -> None:
    """Chave sempre presente, mesmo vazia: quem lê não precisa de `.get` com
    default em dois níveis para descobrir que não há teto declarado."""
    _write_contract(tmp_path, "")

    payload = json.loads(compile_contract(tmp_path, "exemplo").read_text(encoding="utf-8"))
    assert payload["stop_conditions"] == {"typed": [], "advisory": []}


def test_compile_contract_refuses_a_malformed_typed_condition(tmp_path: Path) -> None:
    """Fail-closed no ponto que importa: o contrato inteiro não compila, e
    NADA é escrito — mesma postura do gate de aprovação."""
    _write_contract(tmp_path, "stop_conditions:\n  - {type: nao_existe, n: 3}\n")

    with pytest.raises(ContractError):
        compile_contract(tmp_path, "exemplo")

    assert not (tmp_path / ".harness" / "feature_list.json").exists()
