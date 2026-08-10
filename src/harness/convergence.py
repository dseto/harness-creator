"""Trajetória de métrica: sinal de convergência opt-in (§4.3 do design de
loop engineering, contrato `convergencia-opt-in`).

Terceiro sinal do design, ortogonal aos dois que `attempts.py`/`budget.py` já
respondem ("chegou?" / "esgotou?"): "está se aproximando ou se afastando do
objetivo?" — só faz sentido quando o progresso é mensurável numa escala
contínua (similaridade visual, contagem de erros de lint, testes passando
numa migração grande). Tarefa sem `metric_cmd` no `feature_list.json`
(`contract.py`, T-01) nunca passa por este módulo: o slot é opt-in por
tarefa, e o resto do harness continua se comportando exatamente como antes.

Divisão de responsabilidade, espelhando `attempts.py`/`verify.py`/`budget.py`:

- `convergence.py` (aqui, T-02/T-03): grava a medição e deriva a trajetória
  (melhor valor, sequência de piora, sequência de platô) a partir do rastro
  — nunca executa `metric_cmd`, nunca chama git/subprocess, nunca gera
  timestamp. `record_measurement` recebe `commit`/`dirty`/`recorded_at`
  prontos, do mesmo jeito que `attempts.record_failure` recebe `files_hash`
  pronto.
- `verify.py` (T-02): roda `metric_cmd` depois do `verify_cmd` (passe ou
  falhe — a trajetória interessa principalmente nos vermelhos) e chama
  `record_measurement` com o resultado real.
- `budget.py` (T-03): lê `summarize_trajectory` daqui para decidir
  `stop_worsening`/`stop_plateau`.

Saída do `metric_cmd` que não parseia como número vira `ConvergenceError` —
falha de AMBIENTE (mesma família do §8.3: o script de métrica quebrou, isso
não é sinal sobre o artefato), nunca um valor inventado (zero seria mentira
sobre a trajetória, pior que não medir nada).

`target` (`metric_target` no `feature_list.json`) é uma expressão de
comparação — `>= 0.85`, `<= 5` — que faz DUAS coisas: diz quando a métrica
bate o alvo (`target_met`) e diz a DIREÇÃO de "melhor" (`>=`/`>` — maior é
melhor; `<=`/`<` — menor é melhor). `==` fica fora do formato aceito:
"melhor" para uma igualdade exata não tem sentido de trajetória. Tarefa com
`metric_cmd` mas sem `metric_target` continua registrando medições (T-02),
mas sem direção não há "melhor" para comparar — os vereditos de trajetória
(T-03) simplesmente não disparam para ela, o mesmo silêncio de uma tarefa
sem métrica nenhuma.

Formato — `.harness/attempts/<contrato>/<feature_id>-metric.jsonl` (mesmo
diretório e mesmo escopo por contrato do rastro de tentativas, sufixo
`-metric` distingue o arquivo), uma linha JSON por medição, em ordem
cronológica de append:

    {"value": 0.72, "recorded_at": "2026-08-09T04:00:00+00:00",
     "commit": "a1b2c3d4...", "dirty": false}
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from harness.attempts import ATTEMPTS_DIR, UNSCOPED_ATTEMPTS_DIR

#: `operador` seguido de um número — só os quatro que definem uma direção
#: clara de "melhor". `==` fica de fora de propósito (ver docstring do
#: módulo).
_TARGET_RE = re.compile(r"^(>=|<=|>|<)\s*(-?\d+(?:\.\d+)?)\s*$")

#: Operadores que significam "maior é melhor" — usados para escolher argmax
#: (`>=`/`>`) vs argmin (`<=`/`<`) ao derivar o melhor valor do rastro.
_HIGHER_IS_BETTER = (">=", ">")


class ConvergenceError(Exception):
    """Saída do `metric_cmd` não é um número, ou `target` malformado — falha
    de AMBIENTE (mesma família do §8.3), nunca um valor inventado."""


def metric_path(target_dir: Path, contract: Any, feature_id: str) -> Path:
    """`.harness/attempts/<contrato>/<feature_id>-metric.jsonl`.

    Mesmo diretório e mesmo escopo por contrato do rastro de tentativas
    (`attempts.attempts_path`) — sufixo `-metric` distingue o arquivo do
    rastro de falhas/passes da mesma tarefa, sem precisar de subdiretório
    próprio.
    """
    slug = str(contract or "").strip() or UNSCOPED_ATTEMPTS_DIR
    return Path(target_dir) / ATTEMPTS_DIR / slug / f"{feature_id}-metric.jsonl"


def parse_metric_value(stdout: str) -> float:
    """O `metric_cmd` "imprime um único número em stdout" — a saída inteira,
    stripada, precisa parsear como float. Levanta `ConvergenceError` (nunca
    devolve zero) quando não parseia: saída vazia, texto, ou múltiplas
    linhas são falha do script de métrica, não um valor sobre o artefato.
    """
    text = (stdout or "").strip()
    if not text:
        raise ConvergenceError("metric_cmd não produziu saída")
    try:
        return float(text)
    except ValueError:
        raise ConvergenceError(
            f"saída do metric_cmd não é um número: {text!r}"
        ) from None


def parse_target(target: str) -> tuple[str, float]:
    """`(operador, limiar)` a partir de uma expressão como `>= 0.85`.

    Levanta `ConvergenceError` para expressão malformada ou operador fora
    de `{>=, <=, >, <}`.
    """
    match = _TARGET_RE.match((target or "").strip())
    if not match:
        raise ConvergenceError(
            f"target '{target}' não é uma expressão reconhecida — use >=, <=, "
            "> ou < seguido de um número (ex.: '>= 0.85')"
        )
    return match.group(1), float(match.group(2))


def target_met(value: float, target: str) -> bool:
    """`True` se `value` já bate a expressão `target`."""
    operator, threshold = parse_target(target)
    if operator == ">=":
        return value >= threshold
    if operator == ">":
        return value > threshold
    if operator == "<=":
        return value <= threshold
    return value < threshold  # "<"


def _higher_is_better(target: str) -> bool:
    operator, _ = parse_target(target)
    return operator in _HIGHER_IS_BETTER


def _append(path: Path, record: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def record_measurement(
    target_dir: Path,
    contract: Any,
    feature_id: str,
    *,
    value: float,
    commit: str | None,
    dirty: bool,
    recorded_at: str,
) -> Path:
    """Acrescenta uma medição ao rastro de trajetória. Retorna o path do jsonl.

    `commit`/`dirty`/`recorded_at` vêm de fora, já computados por quem chama
    — mesma divisão de `attempts.record_failure` (recebe `files_hash`
    pronto): este módulo nunca chama git nem relógio.
    """
    return _append(
        metric_path(target_dir, contract, feature_id),
        {"value": value, "recorded_at": recorded_at, "commit": commit, "dirty": dirty},
    )


def read_measurements(target_dir: Path, contract: Any, feature_id: str) -> list[dict[str, Any]]:
    """Lê o rastro em ordem cronológica. Ausente/ilegível -> `[]`, nunca
    levanta — mesma degradação graciosa de `attempts.read_attempts`. Linha
    sem `value` numérico é pulada (mesma postura de linha corrompida)."""
    path = metric_path(target_dir, contract, feature_id)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return []

    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and isinstance(record.get("value"), (int, float)):
            records.append(record)
    return records


def best_so_far(measurements: list[dict[str, Any]], target: str) -> dict[str, Any] | None:
    """A medição com o MELHOR valor do rastro inteiro, direção decidida pelo
    operador de `target` (argmax para `>=`/`>`, argmin para `<=`/`<`).
    `None` para rastro vazio. Empate resolve pela medição MAIS ANTIGA — o
    checkpoint mais estável, não o mais recente."""
    if not measurements:
        return None
    higher_is_better = _higher_is_better(target)
    best = measurements[0]
    for record in measurements[1:]:
        value = record.get("value")
        best_value = best.get("value")
        if higher_is_better and value > best_value:
            best = record
        elif not higher_is_better and value < best_value:
            best = record
    return best


def summarize_trajectory(measurements: list[dict[str, Any]], target: str) -> dict[str, Any]:
    """Contadores que o disjuntor de trajetória (`budget.py`, T-03) consome.

    - `best`: a melhor medição do rastro inteiro (ver `best_so_far`), ou
      `None` para rastro vazio.
    - `worsening_streak`: quantas das ÚLTIMAS medições, contando do fim para
      trás, são ESTRITAMENTE piores que o melhor GLOBAL — para no primeiro
      empate (a própria melhor, se ela for recente, não é "pior que si
      mesma"). É o sinal de `stop_worsening`.
    - `plateau_streak`: quantas das últimas medições NÃO bateram um novo
      recorde contra tudo que veio ANTES delas (melhor CORRENTE, prefixo —
      não o global). Usar o corrente em vez do global evita o paradoxo de a
      própria medição-recorde, comparada a si mesma, "empatar" e contar como
      platô no exato momento em que o platô deveria zerar. Oscilação (sobe e
      desce sem nunca superar o pico) cai aqui por construção — a pergunta é
      "bateu recorde?", não "piorou em sequência" (essa é `worsening_streak`).
      É o sinal de `stop_plateau`.
    - `target_met`: `True` se a medição mais recente já bate `target`.

    Rastro vazio devolve tudo zerado/`None` — mesmo formato de
    `attempts.summarize` para rastro vazio.
    """
    if not measurements:
        return {"best": None, "worsening_streak": 0, "plateau_streak": 0, "target_met": False}

    higher_is_better = _higher_is_better(target)
    best = best_so_far(measurements, target)
    best_value = best["value"]

    def _is_worse_than_best(value: float) -> bool:
        return value < best_value if higher_is_better else value > best_value

    worsening_streak = 0
    for record in reversed(measurements):
        if _is_worse_than_best(record.get("value")):
            worsening_streak += 1
        else:
            break

    running_best: float | None = None
    set_new_record: list[bool] = []
    for record in measurements:
        value = record.get("value")
        if running_best is None:
            is_new = True
        else:
            is_new = value > running_best if higher_is_better else value < running_best
        set_new_record.append(is_new)
        if running_best is None or is_new:
            running_best = value

    plateau_streak = 0
    for is_new in reversed(set_new_record):
        if not is_new:
            plateau_streak += 1
        else:
            break

    return {
        "best": best,
        "worsening_streak": worsening_streak,
        "plateau_streak": plateau_streak,
        "target_met": target_met(measurements[-1]["value"], target),
    }
