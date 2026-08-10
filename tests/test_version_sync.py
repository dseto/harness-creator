"""Guard test contra drift de versão (issue #11): marketplace.json e
plugin.json são fontes manuais que não podem divergir de
harness.__version__ — commit ddc37f6 atualizou só 2 de 4 fontes.

A cobertura foi estendida na v0.27.0 pelo MESMO defeito, um nível acima: o
bump tocou as três fontes que o `AGENTS.md` lista, os dois testes abaixo
passaram, e **cinco marcadores de versão em documentação continuaram na versão
anterior** — README, ARCHITECTURE, o HTML de arquitetura (duas vezes) e o
exemplo de marketplace do GUIDE. O README é a primeira coisa que alguém lê no
GitHub, então o produto se apresentava uma versão atrás com a suíte verde.

Por que um teste e não um item de checklist: o `AGENTS.md` já dizia "bump nas
três fontes", e a instrução foi seguida à risca. O que falhou foi a lista estar
incompleta — e lista incompleta em documento de processo é exatamente o que um
guard test existe para substituir.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import harness

REPO_ROOT = Path(__file__).resolve().parent.parent


def _read_json_version(relative_path: str) -> str:
    path = REPO_ROOT / relative_path
    data = json.loads(path.read_text(encoding="utf-8"))
    if relative_path.endswith("marketplace.json"):
        return data["plugins"][0]["version"]
    return data["version"]


def test_marketplace_json_matches_harness_version() -> None:
    assert _read_json_version(".claude-plugin/marketplace.json") == harness.__version__


def test_plugin_json_matches_harness_version() -> None:
    assert _read_json_version(".claude-plugin/plugin.json") == harness.__version__


#: Marcadores de versão CORRENTE em documentação, um por linha que precisa
#: acompanhar o bump. Cada entrada é (arquivo, template com o literal `<V>` no
#: lugar da versão).
#:
#: O placeholder é `<V>` e não `{v}` de propósito: um dos templates contém `}`
#: literal (o exemplo de `marketplace.json` do GUIDE), e `str.format` levanta
#: `ValueError` em chave desbalanceada. Substituição simples não tem esse
#: problema e não exige escapar nada.
#:
#: Enumeração fechada de propósito, e não um grep por `\d+\.\d+\.\d+`: o
#: repositório cita versões ANTIGAS legitimamente — o CHANGELOG inteiro, a nota
#: "Convenção da suíte (v0.26.0)" no README (que datou uma mudança e deve
#: continuar apontando para a versão em que ela aconteceu), e o
#: "padrão desde a v0.23.0" das tabelas de CLI. Um grep genérico
#: transformaria histórico correto em falha de teste, e o teste seria desligado.
_DOC_VERSION_MARKERS: tuple[tuple[str, str], ...] = (
    ("README.md", "**v<V>** · [CHANGELOG]"),
    ("docs/plugin/ARCHITECTURE.md", "**v<V>** · versão navegável"),
    ("docs/plugin/arquitetura-visual.html", '<span class="pill v">v<V></span>'),
    ("docs/plugin/arquitetura-visual.html", "<strong>harness-creator v<V></strong>"),
    ("docs/plugin/GUIDE.md", '"source": "./", "version": "<V>" }'),
)


def test_changelog_has_a_section_for_the_current_version() -> None:
    """O CHANGELOG ganha a seção da versão corrente no MESMO bump que sobe as
    três fontes.

    Terceira extensão deste arquivo pelo mesmo defeito de sempre: a lista do
    que um bump toca estava incompleta. Os testes acima cobriam as fontes
    manuais e os marcadores de doc, mas nada cobria o documento que responde
    "o que mudou nesta versão" — dava para subir a versão em sete arquivos,
    com a suíte verde, e deixar o CHANGELOG uma versão atrás. Apontado pelo
    verificador cego no contrato `placar-de-andamento`.
    """
    changelog = (REPO_ROOT / "docs/reference/CHANGELOG.md").read_text(encoding="utf-8")
    expected = f"## v{harness.__version__} —"

    assert expected in changelog, (
        f"docs/reference/CHANGELOG.md não tem seção para a versão corrente — "
        f"esperava uma linha começando com {expected!r}. Bump de versão toca as "
        f"3 fontes manuais, os marcadores de doc E a entrada de CHANGELOG."
    )


@pytest.mark.parametrize(
    ("relative_path", "template"),
    _DOC_VERSION_MARKERS,
    ids=[f"{p}:{t[:28]}" for p, t in _DOC_VERSION_MARKERS],
)
def test_doc_version_marker_matches_harness_version(relative_path: str, template: str) -> None:
    """Cada marcador de versão corrente na doc acompanha `harness.__version__`.

    Falha com as duas informações que o autor do bump precisa: qual arquivo
    ficou atrás e qual string procurar — sem isso o teste vira um booleano
    inútil num release apressado.
    """
    text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
    expected = template.replace("<V>", harness.__version__)

    if expected in text:
        return

    stale = re.findall(
        re.escape(template).replace(re.escape("<V>"), r"(\d+\.\d+\.\d+)"), text
    )
    assert stale, (
        f"{relative_path}: marcador de versão não encontrado — o texto "
        f"esperado era {expected!r}. Se a frase mudou legitimamente, atualize "
        f"_DOC_VERSION_MARKERS em {Path(__file__).name}"
    )
    pytest.fail(
        f"{relative_path}: marcador de versão em {stale[0]}, mas "
        f"harness.__version__ é {harness.__version__}. Atualize para "
        f"{expected!r} — bump de versão toca as 3 fontes manuais E os "
        f"marcadores de doc."
    )
