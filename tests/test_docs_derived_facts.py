"""Números do README conferidos contra a fonte real.

Terceira lição compilada do ciclo do contrato `verificador-cego-do-gate`: a
contagem de casos foi escrita errada DUAS VEZES na mesma demanda, e o único que
pegou foi o verificador cego da camada 3. Nada além de leitura pegava — e
leitura é justamente o que não escala.

É a mesma classe de defeito que o teste derivado do parser (em
`test_boundary_guard.py`) já fecha para a lista de verbos do guard, e que a
importação de `HARNESS_CLI_VERBS` fechou para a superfície de permissions:
**fato escrito à mão que já é derivável do código**. A cura conhecida é
derivar; quando o texto não pode ser gerado, o mínimo é travá-lo contra a
fonte.

O preço, declarado: toda tarefa que acrescenta um caso de teste passa a mexer
no README. É o preço certo — o número existe para quem avalia o projeto, e um
número desatualizado informa pior do que número nenhum. A alternativa honesta,
se o incômodo passar do valor, é TIRAR o número do texto — nunca afrouxar a
conferência.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

#: TODA a documentação de usuário, não só o README. A primeira versão deste
#: arquivo ancorava só no `README.md` e passava verde enquanto o `TUTORIAL.md`
#: mandava conferir "20 subcomandos" (eram 25) e a arquitetura visual anunciava
#: "32 módulos" (eram 38) — o verificador cego reprovou a entrega por isso, e
#: com razão: a promessa era sobre a documentação, não sobre um arquivo.
DOC_FILES = (
    "README.md",
    "docs/plugin/TUTORIAL.md",
    "docs/plugin/GUIDE.md",
    "docs/plugin/ARCHITECTURE.md",
    "docs/plugin/arquitetura-visual.html",
)


def _docs() -> list[tuple[str, str]]:
    found = [
        (name, (REPO_ROOT / name).read_text(encoding="utf-8"))
        for name in DOC_FILES
        if (REPO_ROOT / name).is_file()
    ]
    assert found, "nenhum arquivo de documentação foi encontrado — a leitura quebrou"
    return found


def _declared(pattern: str) -> dict[str, set[int]]:
    """`{arquivo: {números declarados}}`, com TODAS as ocorrências de cada um.

    Por arquivo, e não num conjunto só, porque a mensagem de falha precisa
    dizer ONDE corrigir: "README fala em 25 e o tutorial em 20" é acionável;
    "a documentação fala em {20, 25}" manda procurar."""
    out: dict[str, set[int]] = {}
    for name, text in _docs():
        numbers = {int(m) for m in re.findall(pattern, text)}
        if numbers:
            out[name] = numbers
    return out


def _wrong(pattern: str, real: int) -> dict[str, list[int]]:
    return {
        name: sorted(numbers - {real})
        for name, numbers in _declared(pattern).items()
        if numbers - {real}
    }


def _real_subcommand_count() -> int:
    """Verbos que o parser do argparse aceita, lidos do bloco `{...}` do
    `--help` — a mesma leitura que o teste derivado do guard faz, pela mesma
    razão: lista copiada à mão é exatamente o que estes testes existem para
    não ser."""
    proc = subprocess.run(
        [sys.executable, "-m", "harness.cli", "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    usage = proc.stdout
    if "{" not in usage or "}" not in usage:
        pytest.skip(f"o `--help` não expôs o bloco de subcomandos: {usage[:400]}")
    block = usage[usage.index("{") + 1 : usage.index("}")]
    return len({verb.strip() for verb in block.split(",") if verb.strip()})


def _real_module_count() -> int:
    """Módulos de `src/harness/`, sem recursão e sem o `__init__.py`: é o que a
    árvore do README descreve."""
    return len([p for p in (REPO_ROOT / "src" / "harness").glob("*.py") if p.name != "__init__.py"])


def _real_test_count() -> int:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    match = re.search(r"(\d+) tests? collected", proc.stdout)
    if match is None:
        pytest.skip(f"coleta do pytest não pôde ser lida: {proc.stdout[-400:]}")
    return int(match.group(1))


def test_no_document_declares_a_subcommand_count_the_parser_does_not_have() -> None:
    real = _real_subcommand_count()
    wrong = _wrong(r"(\d+) subcomandos", real)

    assert not wrong, (
        f"o parser aceita {real} subcomandos; a documentação diz outra coisa: {wrong}"
    )


def test_no_document_declares_a_module_count_the_package_does_not_have() -> None:
    real = _real_module_count()
    wrong = _wrong(r"(\d+) módulos", real)

    assert not wrong, (
        f"`src/harness/` tem {real} módulos (sem `__init__.py`); a documentação "
        f"diz outra coisa: {wrong}"
    )


def test_no_document_declares_a_test_count_pytest_does_not_collect() -> None:
    """O caso que motivou o arquivo. Erra fácil porque o número muda a cada
    tarefa, e a tarefa que o muda quase nunca é a que olha a documentação."""
    real = _real_test_count()

    # Três dígitos ou mais: "casos" é palavra comum em prosa, e o TUTORIAL fala
    # em "os 4 casos dos critérios" num exemplo — número de narrativa, não
    # afirmação sobre o tamanho da suíte. As duas classes se separam pela ordem
    # de grandeza, e não por marcador manual, que seria mais uma lista à mão.
    # A âncora abaixo existe para o dia em que essa separação deixar de valer:
    # suíte abaixo de 100 faria o teste parar de cobrir EM SILÊNCIO.
    assert real >= 100, (
        f"a suíte caiu para {real} casos e o corte de três dígitos deste teste "
        "deixou de separar afirmação de narrativa — reveja o padrão antes que "
        "ele passe a não cobrir nada"
    )

    wrong = _wrong(r"(\d{3,}) casos", real)

    assert not wrong, (
        f"`pytest --collect-only` coleta {real} casos; a documentação diz outra "
        f"coisa: {wrong}"
    )


def test_the_guard_actually_reads_more_than_the_readme() -> None:
    """Âncora contra a regressão exata pela qual esta tarefa foi reprovada uma
    vez: com a conferência ancorada só no `README.md`, número errado em
    `TUTORIAL.md` ou na arquitetura visual passava com a suíte 100% verde."""
    read = {name for name, _ in _docs()}

    assert {"README.md", "docs/plugin/TUTORIAL.md"} <= read
    assert len(read) >= 3
