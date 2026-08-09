"""Reconcile: estado declarado × estado real na ABERTURA da sessão (§7.4).

O harness sempre soube fazer essa conferência — `finish.audit_closure` compara,
só lendo, o `files_hash` da evidência contra o código atual, o `passes: true`
declarado contra a existência da prova, e a working tree contra os `files[]` do
contrato. O que faltava era o MOMENTO: aquilo roda no fecho, quando a sessão já
gastou seu tempo acreditando na anotação. Uma sessão que abre depois de outra
ter deixado o repo fora do lugar começa confiando no que está escrito, e
descobre a divergência tarde — ou não descobre.

Este módulo não reimplementa o julgamento: chama `audit_closure` e traduz. A
tradução existe porque abertura e fecho não fazem a mesma pergunta.

**O que sai** (`OPENING_IGNORED_KINDS`): `feature_not_passed`, `no_contract` e
os três da camada 3 (`blind_review_*`). Tarefa pendente é bloqueador no fecho e
é o estado NORMAL de quem está começando; repo sem `feature_list.json` é
bootstrap, não repositório mentindo; e a verificação independente acontece no
FIM da demanda, então na abertura ela nunca existe ainda. Se esses entrassem,
toda abertura de sessão sairia com "divergência" e o aviso morreria de ser
ruído — o modo de falha que faz humano desligar alerta.

**O que entra** (`progress_contract_mismatch`): `.harness/progress.md`
descrevendo um contrato diferente do `.harness/feature_list.json`. `finish` não
detecta isso porque reescreve o arquivo logo em seguida; na abertura é a mentira
mais cara que existe, e já aconteceu — v0.25.0, o `SessionStart` injetou
"nenhuma feature pendente" numa sessão com seis tarefas a fazer (ver o
comentário em `finish.render_closed_progress`). É também o que cobre o caso do
`feature_list.json` sumido no meio da demanda: o contrato vira `None`, o
progress continua nomeando o slug, e a divergência aparece por aqui em vez de
pelo `no_contract` que foi filtrado.

SÓ LEITURA, como `audit_closure`: nada de `git restore`, nada de re-verificar,
nada de reescrever o `progress.md`. Reconciliação que conserta sozinha apaga o
rastro necessário para entender o que divergiu.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from harness.finish import PROGRESS_FILE, audit_closure

# `_extract_progress_contract` é privado em `templates`, e é de propósito que
# ele seja importado em vez de recopiado: o header `Contrato: \`slug\`` é o
# mesmo contrato de formato dos dois lados, e uma segunda cópia do parser é
# exatamente como as duas leituras passam a discordar sobre o que é um slug.
from harness.templates import _extract_progress_contract

#: Bloqueadores de FECHO que não são divergência de ABERTURA. Ver o docstring
#: do módulo: são os dois estados em que o repositório está normal e apenas
#: incompleto, e listá-los aqui é o que mantém `divergences: []` significando
#: alguma coisa.
OPENING_IGNORED_KINDS = frozenset(
    {
        "feature_not_passed",
        "no_contract",
        # A camada 3 (§6/§9.1) é assunto do FECHO, e por isso os três saem aqui.
        # "Ninguém verificou ainda" é o estado normal de quem está começando —
        # a demanda inteira acontece antes do veredito existir. Se entrassem,
        # TODA abertura sairia com divergência, que é a mesma morte por ruído
        # que os dois acima evitam. E `blind_review_failed` também sai: uma
        # reprovação legítima paralisaria a abertura da sessão que veio
        # justamente para consertar o que ela apontou.
        "blind_review_missing",
        "blind_review_stale",
        "blind_review_failed",
    }
)

PROGRESS_MISMATCH = "progress_contract_mismatch"


def reconcile(target_dir: Path | str) -> dict[str, Any]:
    """Reconcilia estado declarado com estado real. SÓ LEITURA.

    Devolve `{"contract": <slug|None>, "divergences": [...], "features": [...]}`,
    com cada divergência no mesmo formato dos bloqueadores do `finish`
    (`{"kind": ..., "problem": <frase para o humano>}`). Estado íntegro ->
    `divergences == []`.
    """
    target_dir = Path(target_dir).resolve()
    report = audit_closure(target_dir)

    divergences = [
        blocker
        for blocker in report["blockers"]
        if blocker["kind"] not in OPENING_IGNORED_KINDS
    ]

    mismatch = _progress_contract_mismatch(target_dir, report["contract"])
    if mismatch is not None:
        divergences.append(mismatch)

    return {
        "contract": report["contract"],
        "divergences": divergences,
        "features": report["features"],
    }


def _progress_contract_mismatch(
    target_dir: Path, contract: str | None
) -> dict[str, str] | None:
    """Divergência entre o contrato que o `progress.md` descreve e o que o
    `feature_list.json` compilou — ou `None` se não há o que comparar.

    Ausência de `progress.md`, ou `progress.md` sem o header canônico (conteúdo
    que o agente customizou), devolve `None`: o arquivo não está AFIRMANDO nada
    sobre qual contrato está em curso, e inventar divergência a partir de
    silêncio é como um aviso perde credibilidade.
    """
    progress_path = target_dir / PROGRESS_FILE
    if not progress_path.is_file():
        return None
    try:
        text = progress_path.read_text(encoding="utf-8")
    except OSError:
        return None

    declared = _extract_progress_contract(text)
    if not declared or declared == (contract or ""):
        return None

    if contract:
        problem = (
            f"o `{PROGRESS_FILE}` descreve o contrato `{declared}`, mas o contrato "
            f"compilado é `{contract}` — o resumo que a sessão lê para saber onde "
            "parou é de outra demanda. Rode `harness compile-session` para "
            "regenerá-lo a partir do contrato atual antes de escolher uma fatia."
        )
    else:
        problem = (
            f"o `{PROGRESS_FILE}` descreve o contrato `{declared}`, mas não há "
            "`feature_list.json` compilado — o progresso afirma uma demanda que "
            "o repositório não tem. Rode `harness compile-contract` (e depois "
            "`compile-session`), ou confirme que a demanda anterior foi mesmo "
            "encerrada."
        )
    return {"kind": PROGRESS_MISMATCH, "problem": problem}


def render_session_section(report: dict[str, Any]) -> str | None:
    """Seção markdown para o contexto do `SessionStart`, ou `None` quando não
    há divergência.

    `None` é o caso comum e é deliberado: o contexto da abertura entra em TODA
    sessão, e uma seção dizendo "está tudo certo" gasta o orçamento de atenção
    de que o aviso de verdade vai precisar. Silêncio quando está tudo bem é o
    que torna a seção legível quando ela aparece.
    """
    divergences = report.get("divergences") or []
    if not divergences:
        return None

    lines = [
        "## AVISO: o estado declarado nao bate com o repositorio",
        "",
        "A reconciliacao de abertura (`harness reconcile`) encontrou "
        f"{len(divergences)} divergencia(s) entre o que esta anotado como feito "
        "e o que existe de fato no codigo. Resolva antes de escolher uma fatia: "
        "trabalhar em cima de anotacao errada e como o trabalho da sessao "
        "anterior se perde.",
        "",
    ]
    for divergence in divergences:
        lines.append(f"- **{divergence.get('kind')}** — {divergence.get('problem')}")
    lines += [
        "",
        "Rode `harness reconcile --dir .` para o relatorio completo em JSON.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# entrypoint `python -m harness.reconcile`
# ---------------------------------------------------------------------------
#
# Mesma razão do entrypoint de `harness.autoupdate`: quem consome isto na
# abertura é o hook `SessionStart`, que é stdlib-only por design e roda com `-S`
# (sem `site-packages`), logo não consegue importar `harness`. Ele delega a um
# interpretador novo e lê o JSON de volta. Sem este entrypoint a alternativa
# seria duplicar a lógica dentro do script gerado, onde ela ficaria fora do
# alcance da suíte e divergiria na primeira mudança.

def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m harness.reconcile",
        description="Reconcilia estado declarado com estado real (abertura de sessão)",
    )
    parser.add_argument("--dir", default=".", help="Raiz do projeto-alvo")
    args = parser.parse_args(argv)

    report = reconcile(Path(args.dir))
    # `section` só existe neste payload, não no do `harness reconcile`: quem
    # consome aqui é o script gerado do `SessionStart`, que é stdlib-only e não
    # importa `harness`. Se ele montasse o texto do aviso, a formatação ficaria
    # fora do alcance da suíte e divergiria na primeira mudança — o mesmo
    # motivo pelo qual a DECISÃO do `_auto_update` também mora em `harness/`.
    print(json.dumps({**report, "section": render_session_section(report)}, ensure_ascii=False))
    return 2 if report["divergences"] else 0


if __name__ == "__main__":
    sys.exit(_main())
