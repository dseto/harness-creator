"""Budget: o disjuntor mecânico do loop de autocorreção.

Incremento 1 do design de loop engineering, §4.2: "critério semântico mal
escrito + ausência de teto = loop infinito. O budget é o seguro contra o
próprio erro de design." E §8.2: "se a tentativa N produz o MESMO erro da
tentativa N-1, a abordagem está errada, não a execução".

Contrato `falha-transiente-e-escalada` (T-03) soma §8.1: falha transiente
esgotada (`attempts.classify_failure` via `verify.run_verify`) vira o
veredito `stop_transient_exhausted`, que vence os outros dois — não é o
loop de correção normal do §8.2 pegando um teto, é o §8.3 batendo por outra
porta ("mesmo erro transiente 3× → reclassificar como infra").

Contrato `convergencia-opt-in` (T-03) soma §4.3: tarefa com `metric_cmd` E
`metric_target` no `feature_list.json` (T-01) ganha DOIS vereditos de
trajetória, lidos de `convergence.summarize_trajectory` — `stop_worsening`
(as últimas 2 medições pioraram frente ao melhor já registrado) e
`stop_plateau` (as últimas 3 não bateram um novo recorde, oscilação
inclusa). Os dois ficam DEPOIS dos vereditos estruturais na ordem de
precedência: falha repetida/teto de iterações/transiente esgotado são sinais
sobre a EXECUÇÃO do loop e vencem um sinal sobre a TRAJETÓRIA do artefato.
Tarefa com `metric_cmd` mas sem `metric_target` (sem direção de "melhor")
nunca dispara os dois — mesmo silêncio de uma tarefa sem métrica nenhuma.

O que estava furado: `max_green_iterations` existia no `harness.yaml` e no
schema (`config.BudgetConfig`) sem UM consumidor — o `compiler.py` o
imprimia no `AGENTS.md` numa seção chamada, literalmente, "Orçamento
(orientação)". E as `stop_conditions` do `spec.md` eram frases livres que o
passo 10 do lifecycle chamava de "disjuntor do loop". Um disjuntor que
depende de o agente lembrar de contar não é disjuntor: é sugestão. Este
módulo conta.

Fronteira (mesma de `supervisor.py`, e pelo mesmo motivo): SÓ LEITURA. Nunca
escreve, nunca executa `verify_cmd`/git/subprocess. `check_budget` responde
uma pergunta; OBEDECER é papel de quem chama — hoje o passo 10 do lifecycle,
amanhã o hook Stop bloqueante da Fase 6 do `docs/roadmap-autonomous.md`. A
separação existe para que ligar o enforcement depois não exija reescrever a
decisão.

Fontes lidas, nesta ordem de precedência para os tetos:

1. `stop_conditions.typed` do `.harness/feature_list.json` — o CONTRATO. Se
   declarou, manda: é a demanda dizendo o quanto ela tolera.
2. `governance.budget.max_green_iterations` do `.harness/harness.yaml` — o
   default do projeto para o teto de iterações.
3. Default do schema (`config.BudgetConfig`) — quando não há yaml legível.
   Nunca "sem teto": a ausência de configuração não pode virar autorização
   para iterar para sempre.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from harness.attempts import CLASSIFICATION_TRANSIENT, read_attempts, summarize
from harness.config import HarnessConfig
from harness.contract import FEATURE_LIST_FILE
from harness.convergence import read_measurements, summarize_trajectory

HARNESS_YAML_RELATIVE_PATH = ".harness/harness.yaml"

#: Teto padrão da regra do padrão repetido (§8.2) quando o contrato não
#: declara `same_failure_signature`. Três é o número do próprio design
#: ("tentativas consecutivas na MESMA falha: 3"): duas repetições ainda podem
#: ser coincidência de um ajuste que não chegou a tocar a causa; a terceira já
#: é evidência de que o caminho é outro.
DEFAULT_SAME_SIGNATURE_LIMIT = 3

CONTINUE = "continue"
STOP_SAME_FAILURE = "stop_same_failure"
STOP_ITERATIONS = "stop_iterations"
#: §8.1: "mesmo erro transiente 3× → reclassificar como infra (§8.3)". O
#: único jeito de um registro `classification == "transient"` chegar a
#: existir no rastro é `verify.run_verify` já ter esgotado os retries
#: (T-02) — então este veredito nunca espera acumular contagem nenhuma: a
#: PRIMEIRA vez que a última falha registrada é transiente já é a resposta
#: do §8.3 (nunca healing automático, sempre parada + escalada), não um
#: caso do loop de correção normal do §8.2.
STOP_TRANSIENT_EXHAUSTED = "stop_transient_exhausted"
#: §4.3: "duas medições seguidas piores que o melhor valor já registrado".
#: Constante do design (contrato `convergencia-opt-in`) — não configurável
#: no primeiro corte (ver Não-objetivos: "configurar antes da primeira
#: demanda real usar é ajuste sem dado").
STOP_WORSENING = "stop_worsening"
WORSENING_STREAK_LIMIT = 2
#: §4.3: "três medições sem superar o melhor valor" — inclui oscilação por
#: construção (ver `convergence.summarize_trajectory`).
STOP_PLATEAU = "stop_plateau"
PLATEAU_STREAK_LIMIT = 3


class BudgetError(Exception):
    """Alvo inexistente: contrato não compilado ou feature fora do contrato."""


#: Tradução de cada veredito para uma frase de RESULTADO — o que aconteceu,
#: em palavras de quem não escreveu o harness. O nome cru (`stop_plateau` e
#: companhia) continua no JSON, que é da máquina; ele nunca chega ao canal
#: humano, onde só significa "o programa sabe de algo que você não".
_HUMAN_VERDICT = {
    CONTINUE: "ainda dá para seguir tentando dentro do orçamento desta tarefa",
    STOP_SAME_FAILURE: (
        "o mesmo erro se repetiu {streak} vezes: o que está errado é a abordagem, "
        "não a execução"
    ),
    STOP_ITERATIONS: (
        "{consecutive} tentativas seguidas terminaram em vermelho sem nenhum verde "
        "no meio"
    ),
    STOP_TRANSIENT_EXHAUSTED: (
        "o ambiente não respondeu (rede ou timeout) nem depois das tentativas "
        "automáticas — isso não é bug no código para consertar tentando de novo"
    ),
    STOP_WORSENING: "o resultado está piorando a cada medição, não melhorando",
    STOP_PLATEAU: "as últimas medições ficaram sem melhora: o loop está girando em falso",
}

_HUMAN_VERDICT_FALLBACK = "o loop parou por uma condição do orçamento desta tarefa"


def human_verdict(report: dict[str, Any]) -> str:
    """A frase de resultado correspondente ao veredito de `report`.

    Veredito desconhecido cai numa frase genérica em vez de imprimir o nome
    cru: o objetivo é que NENHUM identificador interno vaze para o humano, e
    um veredito novo que alguém adicione sem passar por aqui não pode furar
    essa regra por esquecimento.
    """
    template = _HUMAN_VERDICT.get(str(report.get("verdict") or ""), _HUMAN_VERDICT_FALLBACK)
    return template.format(
        streak=report.get("same_signature_streak", "várias"),
        consecutive=report.get("consecutive_failures", "várias"),
    )


def _load_feature_list(target_dir: Path) -> dict[str, Any]:
    path = target_dir / FEATURE_LIST_FILE
    if not path.is_file():
        raise BudgetError(
            f"`{FEATURE_LIST_FILE}` ausente — não há contrato compilado de onde ler "
            "tetos. Rode `harness compile-contract` antes."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise BudgetError(f"`{FEATURE_LIST_FILE}` ilegível — {exc}") from exc
    if not isinstance(data, dict):
        raise BudgetError(f"`{FEATURE_LIST_FILE}` ilegível — conteúdo não é um objeto")
    return data


def _max_green_iterations(target_dir: Path) -> int:
    """`governance.budget.max_green_iterations`, com degradação graciosa.

    Mesma postura de `branching.load_branch_per_contract`: yaml ausente,
    inválido ou com schema divergente cai no default do modelo. Aqui isso
    importa mais que lá — o default é um TETO, e cair em "sem teto" por causa
    de um yaml quebrado seria transformar erro de configuração em autonomia
    ilimitada.
    """
    default = HarnessConfig().governance.budget.max_green_iterations
    yaml_path = target_dir / HARNESS_YAML_RELATIVE_PATH
    if not yaml_path.is_file():
        return default
    try:
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return default
    if not isinstance(raw, dict):
        return default
    try:
        config = HarnessConfig.model_validate(raw)
    except ValidationError:
        return default
    return config.governance.budget.max_green_iterations


def _typed_limits(feature_list: dict[str, Any]) -> dict[str, int]:
    """Tetos declarados pelo contrato, por tipo. Formato já validado em
    `contract.parse_stop_conditions` na compilação — aqui só é lido, e um
    conteúdo inesperado (contrato compilado à mão) é ignorado em vez de
    levantar: o disjuntor cai nos defaults, nunca em 'sem teto'."""
    stop_conditions = feature_list.get("stop_conditions")
    if not isinstance(stop_conditions, dict):
        return {}

    limits: dict[str, int] = {}
    for item in stop_conditions.get("typed") or []:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        n = item.get("n")
        if isinstance(kind, str) and isinstance(n, int) and not isinstance(n, bool) and n > 0:
            limits[kind] = n
    return limits


def check_budget(target_dir: Path | str, feature_id: str) -> dict[str, Any]:
    """Veredito do disjuntor para UMA feature. SÓ LEITURA.

    Devolve:

        {"feature_id", "contract", "attempts_total", "consecutive_failures",
         "same_signature_streak", "last_failure_line", "last_failure_signature",
         "limits": {"consecutive_verify_failures": int,
                    "same_failure_signature": int},
         "verdict": "continue" | "stop_same_failure" | "stop_iterations" |
                    "stop_transient_exhausted" | "stop_worsening" | "stop_plateau",
         "reason": "<frase para humano>",
         "target_met": bool}

    Precedência: `stop_transient_exhausted` vence QUALQUER outro veredito —
    checado antes de streak/consecutivas, do mesmo jeito que `health.py`
    checa proteção antes de governança antes de ferramenta ("quem lê para no
    primeiro item, e o primeiro item tem que ser o que mais muda a decisão").
    Falha transiente esgotada é, por definição do §8.1, o §8.3 batendo —
    ambiente instável não é abordagem errada nem teto de tentativas estourado,
    e misturar as três faria o loop tentar "corrigir" o que não é bug.

    Sem isso, `stop_same_failure` vence quando os dois tetos estruturais
    estouram juntos. Os dois param o loop, mas só um diz o que fazer a seguir
    — "a mesma falha três vezes" é um diagnóstico acionável (troque de
    abordagem, registre a decisão), enquanto "acabaram as iterações" informa
    apenas que o tempo passou. §8 exige que a escalada entregue diagnóstico,
    não sintoma.

    Levanta `BudgetError` para contrato não compilado ou `feature_id` fora do
    contrato — devolver `continue` nesses casos faria um id digitado errado
    parecer autorização para seguir tentando.
    """
    target_dir = Path(target_dir).resolve()
    feature_list = _load_feature_list(target_dir)

    contract = feature_list.get("contract")
    features = feature_list.get("features") or []
    feature = next(
        (f for f in features if isinstance(f, dict) and f.get("id") == feature_id), None
    )
    if feature is None:
        known = ", ".join(
            str(f.get("id")) for f in features if isinstance(f, dict) and f.get("id")
        )
        raise BudgetError(
            f"feature '{feature_id}' não existe no contrato "
            f"'{contract or '?'}' — ids disponíveis: {known or '(nenhum)'}"
        )

    typed = _typed_limits(feature_list)
    limits = {
        "consecutive_verify_failures": typed.get(
            "consecutive_verify_failures", _max_green_iterations(target_dir)
        ),
        "same_failure_signature": typed.get(
            "same_failure_signature", DEFAULT_SAME_SIGNATURE_LIMIT
        ),
    }

    summary = summarize(read_attempts(target_dir, contract, feature_id))
    consecutive = summary["consecutive_failures"]
    streak = summary["same_signature_streak"]

    # §4.3: só existe trajetória para comparar com `metric_cmd` E
    # `metric_target` — sem a direção que o target dá, não há "melhor" para
    # `summarize_trajectory` comparar (ver docstring de `convergence.py`).
    metric_cmd = feature.get("metric_cmd")
    metric_target = feature.get("metric_target")
    trajectory = None
    target_met = False
    if metric_cmd and metric_target:
        measurements = read_measurements(target_dir, contract, feature_id)
        trajectory = summarize_trajectory(measurements, metric_target)
        target_met = trajectory["target_met"]

    if summary["last_classification"] == CLASSIFICATION_TRANSIENT:
        verdict = STOP_TRANSIENT_EXHAUSTED
        reason = (
            f"o retry transiente do §8.1 esgotou (`{summary['last_failure_line']}` "
            "persistiu por todas as tentativas) — não é falha de lógica para "
            "consertar por dentro do loop, é ambiente instável (rede, timeout de "
            "aplicação). Pare e escale com o erro cru; insistir aqui é a mesma "
            "aposta que o §8.3 proíbe explicitamente."
        )
    elif streak >= limits["same_failure_signature"]:
        verdict = STOP_SAME_FAILURE
        reason = (
            f"{streak} tentativas seguidas quebraram com a mesma falha "
            f"(`{summary['last_failure_line']}`) — o teto é "
            f"{limits['same_failure_signature']}. O que está errado é a abordagem, "
            "não a execução: mude de estratégia e registre a decisão, ou escale ao "
            "humano com o último erro cru."
        )
    elif consecutive >= limits["consecutive_verify_failures"]:
        verdict = STOP_ITERATIONS
        reason = (
            f"{consecutive} falhas consecutivas desde o último verde — o teto é "
            f"{limits['consecutive_verify_failures']}. Pare, registre o estado no "
            "progress.md e devolva o controle ao humano com o diagnóstico "
            "(o que foi tentado, último erro, classificação)."
        )
    elif trajectory is not None and trajectory["worsening_streak"] >= WORSENING_STREAK_LIMIT:
        verdict = STOP_WORSENING
        best = trajectory["best"]
        reason = (
            f"as últimas {trajectory['worsening_streak']} medições da métrica pioraram "
            f"frente ao melhor valor já registrado ({best['value']}, "
            f"{best.get('recorded_at') or '?'}, commit {best.get('commit') or '?'}) — "
            "isso não é bug de lógica para consertar por dentro do loop (§4.3): "
            "retome do melhor estado nomeado acima, não continue empilhando por "
            "cima do que já piorou."
        )
    elif trajectory is not None and trajectory["plateau_streak"] >= PLATEAU_STREAK_LIMIT:
        verdict = STOP_PLATEAU
        reason = (
            f"as últimas {trajectory['plateau_streak']} medições da métrica não "
            "bateram um novo recorde contra o que veio antes delas — platô, "
            "oscilação inclusa (§4.3). Troque de abordagem ou escale com a curva "
            "registrada; insistir na mesma direção não está aproximando do alvo."
        )
    else:
        verdict = CONTINUE
        reason = (
            f"{consecutive} falha(s) consecutiva(s) de "
            f"{limits['consecutive_verify_failures']}, {streak} com a mesma "
            f"assinatura de {limits['same_failure_signature']} — dá para continuar "
            "corrigindo."
        )

    return {
        "feature_id": feature_id,
        "contract": contract,
        "attempts_total": summary["attempts_total"],
        "consecutive_failures": consecutive,
        "same_signature_streak": streak,
        "last_failure_line": summary["last_failure_line"],
        "last_failure_signature": summary["last_failure_signature"],
        "limits": limits,
        "verdict": verdict,
        "reason": reason,
        # §4.3: informativo, NUNCA decide veredito nem `passes` — anti-Goodhart
        # do design como invariante (ver stop_conditions do contrato
        # `convergencia-opt-in`). `False` para tarefa sem métrica/target.
        "target_met": target_met,
    }
