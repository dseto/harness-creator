"""O placar existe na documentação onde o humano procura o que a ferramenta faz.

T-06 do contrato `placar-de-andamento`. Mesma postura de
`test_docs_derived_facts.py`: a documentação é produto, e afirmação de produto
que ninguém verifica envelhece calada. O `README.md` já ganhou a seção no T-04;
aqui a pergunta é sobre os TRÊS documentos do plugin, que são onde a pessoa
cai quando quer aprender (tutorial), operar (guia) ou entender o desenho
(arquitetura).

Um teste por REGRA, tabela de casos. Cada caso é uma pergunta que o leitor
daquele documento faz e que precisa ter resposta lá dentro — não a mesma
palavra repetida em três arquivos.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

TUTORIAL = "docs/plugin/TUTORIAL.md"
GUIDE = "docs/plugin/GUIDE.md"
ARCHITECTURE = "docs/plugin/ARCHITECTURE.md"


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# REGRA 1 — os três renders do placar aparecem nos três documentos do plugin
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RenderCase:
    doc: str
    needle: str
    why: str


RENDER_CASES = [
    RenderCase(TUTORIAL, "status --brief", "quem aprende precisa do comando que se cola no chat"),
    RenderCase(TUTORIAL, "--panel", "e do painel de terminal"),
    RenderCase(TUTORIAL, "--watch", "e de saber que ele se re-renderiza sozinho"),
    RenderCase(GUIDE, "status --brief", "quem opera precisa distinguir o placar do JSON"),
    RenderCase(GUIDE, "--panel", "o guia é onde se procura a forma de operação"),
    RenderCase(ARCHITECTURE, "panel.py", "quem lê o desenho precisa achar o módulo"),
    RenderCase(ARCHITECTURE, "statusline.py", "e o módulo que instala a barra"),
]


@pytest.mark.parametrize("case", RENDER_CASES, ids=lambda c: f"{c.doc.split('/')[-1]}:{c.needle}")
def test_the_plugin_docs_show_the_scoreboard(case: RenderCase) -> None:
    assert case.needle in _read(case.doc), (
        f"{case.doc} não menciona `{case.needle}` — {case.why}"
    )


# ---------------------------------------------------------------------------
# REGRA 2 — a statusline aparece como ARTEFATO GERADO, não só como conceito
# ---------------------------------------------------------------------------

def test_the_tutorial_lists_the_statusline_among_the_generated_files() -> None:
    """O tutorial tem a tabela do que o `compile-session` escreve no disco.
    Hook que não está lá é arquivo que aparece no repositório de quem seguiu o
    tutorial sem nada explicando de onde veio."""
    tutorial = _read(TUTORIAL)

    assert "statusline.py" in tutorial
    assert "statusLine" in tutorial, (
        "o tutorial precisa nomear a entrada `statusLine` do settings: é ela que "
        "o usuário procura quando quer trocar ou desligar a barra"
    )


def test_the_architecture_puts_the_statusline_in_the_hook_map() -> None:
    """O mapa de hooks da arquitetura lista o que o Claude Code dispara. A
    statusline é o quarto artefato executado pelo CLI, ao lado de
    `session_start.py` e `stop_hook.py` — ausente ali, o desenho conta uma
    história com um hook a menos do que a realidade.

    A janela é FECHADA dos dois lados de propósito: a primeira versão deste
    teste fatiava do diagrama até o fim do arquivo, e nesse formato ele não
    dizia nada além do que a REGRA 1 já diz (a string existe em algum lugar do
    documento). Guarda que não morde a propriedade que nomeia é guarda que vai
    deixar passar a próxima.
    """
    architecture = _read(ARCHITECTURE)
    anchor = architecture.index("stop_hook.py")
    hook_map = architecture[anchor - 600 : anchor + 600]

    assert "statusline.py" in hook_map, (
        "o diagrama de hooks da ARCHITECTURE.md não cita statusline.py na "
        "vizinhança de session_start.py/stop_hook.py"
    )


def test_the_architecture_layer_table_lists_the_two_new_modules() -> None:
    """A promessa literal do T-06 é a tabela de CAMADAS, não a prosa em volta.
    Sem ancorar na linha da tabela, apagar `panel` da camada 4 e `statusline`
    da camada 3 deixaria a suíte verde — e a tabela é o índice que alguém lê
    para saber o que existe no pacote."""
    architecture = _read(ARCHITECTURE)
    rows = [line for line in architecture.splitlines() if line.startswith("| **")]

    def _modules_column(row: str) -> str:
        # A COLUNA de módulos, não a linha inteira: a primeira versão desta
        # guarda casava a linha toda, e a prosa das colunas "Responsabilidade"
        # e "o que ela NÃO faz" já cita os dois módulos pelo nome — apagá-los
        # da lista deixava a suíte verde, que é exatamente a regressão que este
        # teste promete pegar. Pego pelo verificador cego.
        return row.split("|")[2]

    enforcement = _modules_column(next(row for row in rows if "Enforcement" in row))
    proof = _modules_column(next(row for row in rows if "Prova e controle" in row))

    assert "statusline" in enforcement, (
        "a camada 3 (Enforcement) da tabela não lista `statusline` — o hook da "
        "barra do CLI é executado fora do pacote, como os outros três"
    )
    assert "panel" in proof, (
        "a camada 4 (Prova e controle) da tabela não lista `panel` — é ele que "
        "lê a evidência e devolve o estado do loop"
    )


# ---------------------------------------------------------------------------
# REGRA 3 — o guia mantém a distinção que o contrato preservou: `status` sem
# flag é o JSON estruturado, o placar é opt-in
# ---------------------------------------------------------------------------

def test_the_guide_keeps_the_json_and_the_panel_distinguishable() -> None:
    """A seção de kill-switch do guia diz que `harness status` é a única fonte
    de verdade. Se ela passasse a mostrar o placar sem dizer que a saída padrão
    continua sendo o JSON, o leitor concluiria que a fonte de verdade virou um
    painel colorido — que é exatamente o que este contrato NÃO fez."""
    guide = _read(GUIDE)

    assert "JSON" in guide
    marker = "status --brief"
    around = guide[guide.index(marker) - 1200 : guide.index(marker) + 1200]
    assert "JSON" in around, (
        "o guia menciona o placar longe de qualquer explicação de que a saída "
        "padrão de `harness status` continua sendo o JSON estruturado"
    )
