"""Placar de andamento — o loop legível para quem só quer o resultado.

Responde, de um bloco só, as quatro perguntas que a enxurrada de tool calls
não responde: **onde estou** (tarefa quantas de quantas), **o que está sendo
feito agora**, **está indo bem** (tentativa n de quantas, a última prova
passou?) e **o que vem a seguir**.

Render PURO, e isso é a razão de o placar ser confiável: tudo aqui sai dos
arquivos que outros módulos já gravam — `.harness/feature_list.json`
(contrato), `.harness/attempts/` (rastro de tentativas), `.harness/metrics/`
(trajetória de convergência) e o sentinel do kill-switch. Este módulo nunca
escreve, nunca roda `verify_cmd`, nunca chama git ou subprocess. O agente
COLA a saída, nunca a redige: placar redigido de cabeça é self-report, e o
repositório já estabeleceu que self-report não vale como prova de andamento.

`collect_state` é a fonte única dos três renders (`--brief` para o chat,
terminal ANSI, statusline de uma linha): se cada render lesse o disco à sua
maneira, três leituras divergentes contariam três verdades diferentes sobre
a mesma sessão.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from harness.attempts import read_attempts
from harness.budget import BudgetError, check_budget
from harness.contract import FEATURE_LIST_FILE
from harness.convergence import best_so_far, read_measurements
from harness.killswitch import is_disabled
from harness.supervisor import dispatch_next

#: Células da barra de progresso. Vinte cabe na largura de qualquer terminal
#: e na linha de um chat sem quebrar.
_BAR_CELLS = 20

#: Quantas medições recentes entram na série do placar. O rastro inteiro é
#: relatório de escalada (`escalation.py`); aqui a pergunta é "está melhorando
#: agora?", que oito pontos já respondem.
_SERIES_WINDOW = 8

_SPARK_CHARS = "▁▂▃▄▅▆▇█"

STATE_DONE = "done"
STATE_CURRENT = "current"
STATE_BLOCKED = "blocked"
STATE_PENDING = "pending"


def _load_feature_list(target_dir: Path) -> dict[str, Any] | None:
    path = target_dir / FEATURE_LIST_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _feature_state(
    feature: dict[str, Any], current_id: str | None, by_id: dict[str, dict[str, Any]]
) -> str:
    if feature.get("passes") is True:
        return STATE_DONE
    if feature.get("id") == current_id:
        return STATE_CURRENT
    for dep_id in feature.get("depends") or []:
        dep = by_id.get(dep_id)
        if dep is None or dep.get("passes") is not True:
            return STATE_BLOCKED
    return STATE_PENDING


def _last_proof(target_dir: Path, contract: Any, feature_id: str) -> dict[str, Any]:
    """Resultado da ÚLTIMA tentativa registrada da fatia, com o erro CRU.

    A linha de erro é a que o runner imprimiu — o painel nunca resume falha:
    resumir erro é jogar fora o sinal que o próximo passo precisa.
    """
    records = [r for r in read_attempts(target_dir, contract, feature_id) if r.get("result")]
    if not records:
        return {"result": None, "failure_line": None, "recorded_at": None}
    last = records[-1]
    passed = last.get("result") == "pass"
    return {
        "result": "pass" if passed else "fail",
        "failure_line": None if passed else (last.get("failure_line") or ""),
        "recorded_at": last.get("recorded_at"),
        "classification": None if passed else last.get("classification"),
    }


def _metric(target_dir: Path, contract: Any, feature: dict[str, Any]) -> dict[str, Any] | None:
    """Trajetória da métrica, ou `None` quando não há o que mostrar.

    Exige `metric_cmd` E `metric_target` E rastro em disco — as três coisas,
    pela mesma razão de `budget.check_budget`: sem o target não existe direção,
    e sem direção não existe "melhor" para comparar. Tarefa sem métrica não
    ganha uma linha vazia no placar; ela simplesmente não tem essa linha.
    """
    if not (feature.get("metric_cmd") and feature.get("metric_target")):
        return None
    measurements = read_measurements(target_dir, contract, str(feature.get("id")))
    if not measurements:
        return None
    target = str(feature["metric_target"])
    return {
        "series": measurements[-_SERIES_WINDOW:],
        "best": best_so_far(measurements, target),
        "latest": measurements[-1],
        "target": target,
    }


def _next_step(
    *,
    disabled: bool,
    contract: Any,
    total: int,
    current: dict[str, Any] | None,
    last_proof: dict[str, Any],
    verdict: str,
    reason: str,
) -> str:
    """O próximo passo é DERIVADO do estado, nunca narrado.

    A ordem é a de quem lê e para no primeiro item: um harness desativado
    torna todo o resto irrelevante (os hooks estão em no-op), e um veredito de
    parada do disjuntor vence a vontade de tentar mais uma vez.
    """
    if disabled:
        return "o harness está desativado — reative com harness enable --dir . antes de seguir"
    if contract is None or total == 0:
        return "nenhum contrato compilado — aprove um plano e rode harness compile-contract"
    if current is None:
        return "todas as tarefas passaram — encerre a demanda com harness finish --dir ."
    if verdict and verdict != "continue":
        return f"pare e escale: {reason}"
    # Texto CRU, sem crase: a mesma frase é lida no chat (markdown), no
    # terminal (texto puro) e na statusline (uma linha). Marcação de um render
    # vazando nos outros é o defeito que separar os renders existe para evitar.
    command = current.get("verify_cmd") or f"harness verify {current.get('id')}"
    if last_proof.get("result") == "fail":
        return f"corrigir o que a prova apontou e rodar de novo: {command}"
    return f"implementar a fatia e provar com {command}"


def collect_state(target_dir: Path | str) -> dict[str, Any]:
    """Lê o estado real do harness e devolve o placar em dados. SÓ LEITURA.

    Nunca levanta por estado ausente: repositório sem contrato compilado é uma
    situação normal (antes do primeiro `compile-contract`), e um painel que
    explode em vez de dizer "não há contrato" seria pior que nenhum painel.
    """
    target_dir = Path(target_dir).resolve()
    disabled = is_disabled(target_dir)

    feature_list = _load_feature_list(target_dir)
    contract = (feature_list or {}).get("contract")
    raw_features = [f for f in ((feature_list or {}).get("features") or []) if isinstance(f, dict)]
    by_id = {str(f.get("id")): f for f in raw_features}

    current_feature = dispatch_next(target_dir) if feature_list else None
    current_id = str(current_feature["id"]) if current_feature else None

    features = [
        {
            "id": str(f.get("id")),
            "desc": str(f.get("desc") or ""),
            "passes": f.get("passes") is True,
            "state": _feature_state(f, current_id, by_id),
        }
        for f in raw_features
    ]

    current: dict[str, Any] | None = None
    last_proof: dict[str, Any] = {"result": None, "failure_line": None, "recorded_at": None}
    metric: dict[str, Any] | None = None
    verdict = ""
    reason = ""

    if current_feature is not None:
        last_proof = _last_proof(target_dir, contract, current_id)
        metric = _metric(target_dir, contract, current_feature)
        attempt = 1
        limit = 0
        try:
            budget = check_budget(target_dir, current_id)
        except BudgetError:
            # Contrato ilegível para o disjuntor não pode apagar o placar: o
            # resto do estado continua verdadeiro, e a tentativa cai no piso.
            budget = None
        if budget is not None:
            attempt = int(budget["consecutive_failures"]) + 1
            limit = int(budget["limits"]["consecutive_verify_failures"])
            verdict = str(budget.get("verdict") or "")
            reason = str(budget.get("reason") or "")
        current = {
            "id": current_id,
            "desc": str(current_feature.get("desc") or ""),
            "verify_cmd": current_feature.get("verify_cmd"),
            "attempt": attempt,
            "limit": limit,
            "verdict": verdict,
            "reason": reason,
        }

    return {
        "contract": contract,
        "disabled": disabled,
        "total": len(features),
        "done": sum(1 for f in features if f["passes"]),
        "features": features,
        "current": current,
        "last_proof": last_proof,
        "metric": metric,
        "next_step": _next_step(
            disabled=disabled,
            contract=contract,
            total=len(features),
            current=current,
            last_proof=last_proof,
            verdict=verdict,
            reason=reason,
        ),
    }


def _progress_bar(done: int, total: int) -> str:
    if total <= 0:
        return "░" * _BAR_CELLS
    filled = round(_BAR_CELLS * done / total)
    return "█" * filled + "░" * (_BAR_CELLS - filled)


def _sparkline(values: list[float]) -> str:
    if not values:
        return ""
    low, high = min(values), max(values)
    if high == low:
        return _SPARK_CHARS[len(_SPARK_CHARS) // 2] * len(values)
    span = high - low
    return "".join(
        _SPARK_CHARS[min(len(_SPARK_CHARS) - 1, int((v - low) / span * (len(_SPARK_CHARS) - 1)))]
        for v in values
    )


def _format_number(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _metric_line(metric: dict[str, Any]) -> str:
    series = [m["value"] for m in metric["series"]]
    best = metric["best"] or {}
    return (
        f"{_sparkline(series)} atual {_format_number(series[-1])} · "
        f"melhor {_format_number(best.get('value'))} · alvo {metric['target']}"
    )


_TASK_MARK = {
    STATE_DONE: "[x]",
    STATE_CURRENT: "[ ]",
    STATE_BLOCKED: "[ ]",
    STATE_PENDING: "[ ]",
}

_TASK_SUFFIX = {
    STATE_CURRENT: " ← agora",
    STATE_BLOCKED: " (esperando dependência)",
    STATE_DONE: "",
    STATE_PENDING: "",
}


def render_brief(state: dict[str, Any]) -> str:
    """Bloco markdown+unicode para o agente COLAR no chat. Nunca ANSI.

    O chat do Claude Code renderiza markdown e mostra escape code ANSI como
    lixo literal — por isso este render e o do terminal são separados em vez
    de um só com a cor "desligada".
    """
    contract = state.get("contract") or "sem contrato compilado"
    done, total = state["done"], state["total"]

    lines = [f"# Placar — {contract}", ""]
    lines.append(f"`{_progress_bar(done, total)}` **{done}/{total}** tarefas prontas")
    lines.append("")

    for feature in state["features"]:
        desc = feature["desc"] or feature["id"]
        text = f"{_TASK_MARK[feature['state']]} {feature['id']} — {desc}"
        if feature["state"] == STATE_CURRENT:
            text = f"{_TASK_MARK[feature['state']]} **{feature['id']} — {desc}**"
        lines.append(f"- {text}{_TASK_SUFFIX[feature['state']]}")

    if not state["features"]:
        lines.append("- _(nenhuma tarefa compilada)_")

    lines.append("")

    current = state.get("current")
    if current:
        limit = current["limit"]
        ceiling = f"/{limit}" if limit else ""
        lines.append(f"**Tentativa:** {current['attempt']}{ceiling}")

    proof = state["last_proof"]
    if proof["result"] == "fail":
        lines.append(f"**Última prova:** ❌ falhou — `{proof['failure_line']}`")
    elif proof["result"] == "pass":
        lines.append("**Última prova:** ✅ passou")
    else:
        lines.append("**Última prova:** — ainda não rodou nesta fatia")

    if state.get("metric"):
        lines.append(f"**Métrica:** {_metric_line(state['metric'])}")

    if state["disabled"]:
        lines.append("**Kill-switch:** ⚠️ harness DESATIVADO — os hooks estão em no-op")

    lines.append(f"**Próximo passo:** {state['next_step']}")

    return "\n".join(lines) + "\n"


#: Cores SGR. Só as quatro que carregam significado no placar: verde = passou,
#: vermelho = falhou/desativado, âmbar = é aqui que estamos, ciano = o que
#: fazer. Cor é decoração — o mesmo texto tem que sobrar quando ela sai.
_GREEN = "32"
_RED = "31"
_AMBER = "33"
_CYAN = "36"
_DIM = "2"


def _paint(text: str, code: str | None, *, color: bool) -> str:
    if not color or not code:
        return text
    return f"\x1b[{code}m{text}\x1b[0m"


_TASK_GLYPH = {
    STATE_DONE: "✔",
    STATE_CURRENT: "▶",
    STATE_BLOCKED: "·",
    STATE_PENDING: "·",
}

_TASK_COLOR = {
    STATE_DONE: _GREEN,
    STATE_CURRENT: _AMBER,
    STATE_BLOCKED: _DIM,
    STATE_PENDING: _DIM,
}


def render_terminal(state: dict[str, Any], *, color: bool = False) -> str:
    """Placar para o terminal do DEV.

    Mesmo conteúdo do `--brief`, sem a sintaxe de markdown que só faz sentido
    dentro do chat, e com cor ANSI quando `color=True`. A cor é estritamente
    decoração: `strip_ansi(render_terminal(s, color=True))` é igual a
    `render_terminal(s, color=False)` — um placar que dissesse coisas
    diferentes conforme o destino da saída seria duas verdades, não uma.
    """
    contract = state.get("contract") or "sem contrato compilado"
    done, total = state["done"], state["total"]

    out: list[str] = [f"Placar — {contract}", ""]

    bar = _progress_bar(done, total)
    bar_color = _GREEN if total and done == total else _AMBER
    out.append(f"{_paint(bar, bar_color, color=color)} {done}/{total} tarefas prontas")
    out.append("")

    for feature in state["features"]:
        desc = feature["desc"] or feature["id"]
        text = (
            f"{_TASK_GLYPH[feature['state']]} {feature['id']} — {desc}"
            f"{_TASK_SUFFIX[feature['state']]}"
        )
        out.append(_paint(text, _TASK_COLOR[feature["state"]], color=color))

    if not state["features"]:
        out.append(_paint("(nenhuma tarefa compilada)", _DIM, color=color))

    out.append("")

    current = state.get("current")
    if current:
        ceiling = f"/{current['limit']}" if current["limit"] else ""
        out.append(f"Tentativa: {current['attempt']}{ceiling}")

    proof = state["last_proof"]
    if proof["result"] == "fail":
        out.append(
            "Última prova: "
            + _paint(f"falhou — {proof['failure_line']}", _RED, color=color)
        )
    elif proof["result"] == "pass":
        out.append("Última prova: " + _paint("passou", _GREEN, color=color))
    else:
        out.append("Última prova: ainda não rodou nesta fatia")

    if state.get("metric"):
        out.append(f"Métrica: {_metric_line(state['metric'])}")

    if state["disabled"]:
        out.append(
            _paint("Kill-switch: harness DESATIVADO — os hooks estão em no-op", _RED, color=color)
        )

    out.append("Próximo passo: " + _paint(state["next_step"], _CYAN, color=color))

    return "\n".join(out) + "\n"


#: Limpa a tela e leva o cursor ao topo antes de cada re-render. Só vale em
#: TTY: num pipe isso viraria lixo no meio do arquivo.
_CLEAR_SCREEN = "\x1b[2J\x1b[H"


def watch(
    target_dir: Path | str,
    interval: int,
    *,
    stream: Any = None,
    color: bool | None = None,
    iterations: int | None = None,
    sleep: Any = None,
) -> None:
    """Re-renderiza o placar a cada `interval` segundos no terminal do DEV.

    Um LOOP DE RENDER, não um daemon: roda no terminal de quem chamou, morre
    com ele, não escreve nada e não abre porta nenhuma. `iterations=None`
    (default) é o uso real — repete até o `Ctrl+C`; o parâmetro existe para o
    teste poder pedir um número finito de voltas sem depender de relógio.

    Dorme ENTRE renders, nunca depois do último: com `iterations` esgotado o
    comando termina na hora, sem um intervalo morto no fim.
    """
    import sys as _sys
    import time as _time

    stream = stream if stream is not None else _sys.stdout
    sleep = sleep if sleep is not None else _time.sleep
    is_tty = bool(getattr(stream, "isatty", lambda: False)())
    use_color = is_tty if color is None else color

    count = 0
    while True:
        text = render_terminal(collect_state(target_dir), color=use_color)
        stream.write((_CLEAR_SCREEN if is_tty else "") + text)
        stream.flush()
        count += 1
        if iterations is not None and count >= iterations:
            return
        sleep(interval)
