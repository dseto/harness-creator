"""Guard test contra doc que promete um portão de proteção que não roda.

Issue #61: quatro documentos de `docs/plugin/` descreviam o `guard_tests.py`
como hook de enforcement ativo — `GUIDE.md` chegava a prometer que editar um
arquivo de teste dispara *aquele* hook. As afirmações já eram falsas antes da
correção do #61: quem entrega o gate de edição de teste é o `boundary_guard`,
por decisão por-tarefa. (Atualização T-04/onda-1: o `guard_tests.py` deixou
de ser gerado — antes disso já não era registrado.)

Por que um teste e não uma revisão de doc: essas frases nasceram corretas e
envelheceram sem sinal nenhum. A mesma classe de defeito da issue #11 e do
drift de marcador de versão (ver `test_version_sync.py`) — documentação que
descreve um mecanismo que mudou, com a suíte verde. Um teste transforma o
envelhecimento silencioso em falha.

Enumeração fechada, e não um grep por `guard_tests`: o nome aparece
legitimamente em `docs/plugin/` (a linha do inventário que explica por que o
mecanismo antigo não é mais gerado) e em `docs/project/` inteiro, que é
registro histórico datado — reescrever registro histórico é falsificá-lo.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

#: (arquivo, trecho proibido, por que era falso). O trecho é literal: se a
#: frase for reescrita legitimamente, o teste falha pedindo revisão desta
#: tabela — o que é o comportamento desejado, não um incômodo.
_FORBIDDEN_CLAIMS: tuple[tuple[str, str, str], ...] = (
    (
        "docs/plugin/GUIDE.md",
        "hook `guard_tests.py` — impede alterar o teste",
        "atribuía ao guard_tests o gate de edição de teste, que o boundary_guard entrega",
    ),
    (
        "docs/plugin/TUTORIAL.md",
        "| Guard PreToolUse: disciplina de teste |",
        "descrevia como guard PreToolUse ativo um hook que não é registrado",
    ),
    (
        "docs/plugin/ARCHITECTURE.md",
        "`boundary_guard`, `guard_tests`, `guard_test_runner`",
        "listava o guard_tests na camada de enforcement runtime",
    ),
    (
        "docs/plugin/arquitetura-visual.html",
        "boundary_guard.py · guard_tests.py · guard_test_runner.py",
        "mesma lista de enforcement, no diagrama de camadas",
    ),
    (
        "docs/plugin/arquitetura-visual.html",
        "t:'guard_tests'",
        "nó do grafo de dependências apresentado como hook de TDD ativo",
    ),
    # Achado por revisão fria: a primeira correção desta linha trocou uma
    # afirmação falsa por outra. Passou a atribuir ao `boundary_guard` um
    # "prompt de aprovação com motivo específico", e o `boundary_guard` NUNCA
    # emite `ask` — só `allow`/`deny`, e a decisão é por-tarefa (o arquivo está
    # ou não em `files[]`). A frase inventada era mais convincente que a
    # original justamente por citar o mecanismo certo.
    (
        "docs/plugin/GUIDE.md",
        "regra TDD do harness",
        "citava uma razão de prompt que não existe em src/ — o boundary_guard não emite ask",
    ),
    # Não é `docs/plugin/`, e é o caso mais perigoso: instrução VIVA que a skill
    # `plan` injeta em toda demanda, afirmando que o guard_tests põe o `desc` da
    # tarefa na frente do prompt de permissão. Ele não é registrado, então não
    # põe nada em prompt nenhum.
    (
        "skills/plan/references/contract-templates.md",
        "Os hooks de TDD gerados (`guard_tests.py`",
        "instruía o autor do contrato com base num hook que não roda",
    ),
    # Segundo achado de revisão fria no MESMO parágrafo: a primeira correção
    # dele atribuiu ao `boundary_guard` a leitura do `desc` da tarefa. Ele não
    # lê `desc` em lugar nenhum (`grep -c '\\bdesc\\b'` = 0) — as razões de deny
    # dele levam o ID da tarefa. Quem põe o `desc` na frente do prompt é só o
    # `guard_test_runner.py`, via `_contract_note` em `compiler.py`.
    (
        "skills/plan/references/contract-templates.md",
        "O\n`boundary_guard.py` e o `guard_test_runner.py` leem o `desc`",
        "atribuía ao boundary_guard a leitura do desc, que ele não faz",
    ),
    # Onda 2/T-01: AGENTS.md descrevia uma arquitetura de sandbox/container
    # e um ContextManager que nunca existiram no Claude Code — era prosa da
    # "era congelada" citada em docs/project/AUDIT-harness-engineering-
    # 2026-07-30.md, sobrevivendo como texto injetado toda sessão.
    (
        "AGENTS.md",
        "Este arquivo é lido pelo `ContextManager` do harness",
        "atribuía a leitura deste arquivo a um ContextManager que não existe no Claude Code",
    ),
    (
        "AGENTS.md",
        "Sandbox only",
        "prometia um contêiner isolado sem rede que não existe no host Windows",
    ),
    (
        "AGENTS.md",
        "Prefira `read_file`/`write_file` a `run_terminal`",
        "citava ferramentas read_file/write_file/run_terminal que não são nativas do Claude Code",
    ),
    (
        "AGENTS.md",
        "`tools/`, `verification/`, `context/`, `governance/`, `telemetry/`, `routing/`",
        "listava pacotes que não existem em src/harness/ (hoje módulos soltos + governance/ e teams/)",
    ),
    # Onda 3/T-01: guard_test_runner.py (matcher Bash, sempre-`allow`, nunca
    # lia o payload) foi aposentado — media ~125ms por chamada de Bash sem
    # mudar nenhuma decisão, já que o boundary_guard.py (matcher `*`) já
    # cobre todo Bash. Estas frases o descreviam como hook ATIVO/gerado.
    (
        "docs/plugin/GUIDE.md",
        "`.harness/hooks/guard_test_runner.py` — registrado como hook `PreToolUse`,",
        "descrevia guard_test_runner.py como hook ativo registrado por `harness init`",
    ),
    (
        "docs/plugin/TUTORIAL.md",
        "Registrado no matcher `Bash` (só com `enforce_tdd`), mas sempre `allow`",
        "linha de tabela descrevendo guard_test_runner.py como hook ativo",
    ),
    (
        "docs/plugin/ARCHITECTURE.md",
        "`boundary_guard`, `guard_test_runner`, `session_start`, `stop_hook`",
        "listava guard_test_runner na camada 3 de enforcement runtime",
    ),
    (
        "docs/plugin/arquitetura-visual.html",
        "boundary_guard.py · guard_test_runner.py · session_start.py · stop_hook.py",
        "mesma lista de enforcement, no texto da camada 3 do diagrama",
    ),
)


@pytest.mark.parametrize(
    ("relative_path", "claim", "why"),
    _FORBIDDEN_CLAIMS,
    ids=[f"{p.split('/')[-1]}:{c[:34]}" for p, c, _ in _FORBIDDEN_CLAIMS],
)
def test_plugin_docs_do_not_claim_guard_tests_is_active(
    relative_path: str, claim: str, why: str
) -> None:
    text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
    assert claim not in text, (
        f"{relative_path}: a afirmação {claim!r} voltou. Ela {why} — o "
        "guard_tests.py nem é mais gerado (T-04/onda-1; já não era registrado "
        "desde a issue #61), e quem entrega o gate de edição de teste é o "
        "boundary_guard. Se a "
        "frase foi reescrita de propósito, atualize _FORBIDDEN_CLAIMS em "
        f"{Path(__file__).name}"
    )
