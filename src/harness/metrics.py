"""Contagem de ciclos de fricção — instrumentação da onda 3 do plano v2.

O gate da onda 5 (decidir entre as posturas **B** e **C** do Item 9) depende de
UM número que ninguém tem: quantos ciclos `disable` -> editar ->
`compile-session` -> `enable` uma sessão real ainda gasta depois das ondas 2 e 3.
A sessão do `Savant.Backend.APP-15167` gastou ~13, contados à mão relendo
transcrição. Sem instrumentação, a próxima medição seria igualmente manual — e a
§7 do plano v2 registra que a contagem que ordenou as ondas já está
possivelmente contaminada, porque não há registro de quantas tool calls
passaram sem guard quando o fail-open do Item 1 podia estar ativo.

**Onde a contagem vive, e por quê.** Em `disable`/`enable`/`compile-session`, na
CLI — não em hook. Os ciclos ocorrem justamente com o harness DESLIGADO: um
contador em hook mediria a janela errada, contando zero exatamente durante o
fenômeno que interessa.

O arquivo (`.harness/metrics.json`) é machine-local: conta operações desta
máquina, não fato do repositório.

Invariante: instrumentação **nunca** quebra o comando que instrumenta.
`record_event` engole qualquer erro — um disco cheio ou um JSON corrompido não
pode impedir o usuário de desligar o harness.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

METRICS_RELATIVE_PATH = ".harness/metrics.json"

#: Eventos contados. Fechado de propósito: um contador que aceita nome livre
#: vira lixo acumulado e ninguém confia no número depois.
COUNTED_EVENTS: tuple[str, ...] = ("disable", "enable", "compile-session")


def metrics_path(target_dir: Path | str) -> Path:
    return Path(target_dir) / METRICS_RELATIVE_PATH


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_metrics(target_dir: Path | str) -> dict[str, Any]:
    """Estado atual dos contadores. Arquivo ausente/ilegível devolve o estado
    zerado — nunca lança."""
    empty: dict[str, Any] = {
        "counters": {event: 0 for event in COUNTED_EVENTS},
        "first_recorded_at": None,
        "last_recorded_at": None,
    }
    path = metrics_path(target_dir)
    if not path.is_file():
        return empty
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return empty
    if not isinstance(data, dict):
        return empty
    counters = data.get("counters")
    if not isinstance(counters, dict):
        counters = {}
    merged = dict(empty)
    merged["counters"] = {
        event: int(counters.get(event, 0)) if isinstance(counters.get(event, 0), int) else 0
        for event in COUNTED_EVENTS
    }
    merged["first_recorded_at"] = data.get("first_recorded_at")
    merged["last_recorded_at"] = data.get("last_recorded_at")
    return merged


def record_event(target_dir: Path | str, event: str) -> None:
    """Incrementa o contador de `event`. Silencioso e fail-safe por contrato:
    qualquer erro (evento desconhecido, disco cheio, JSON corrompido) é
    engolido — a instrumentação não pode derrubar o comando instrumentado, e
    menos ainda o `disable`, que é a válvula de escape do usuário."""
    if event not in COUNTED_EVENTS:
        return
    try:
        state = read_metrics(target_dir)
        state["counters"][event] = state["counters"].get(event, 0) + 1
        now = _now_iso()
        if not state.get("first_recorded_at"):
            state["first_recorded_at"] = now
        state["last_recorded_at"] = now
        path = metrics_path(target_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    except Exception:
        return


def friction_summary(target_dir: Path | str) -> dict[str, Any]:
    """Resumo pronto para o gate da onda 5.

    `disable_enable_cycles` é `min(disable, enable)`: um `disable` sem `enable`
    correspondente ainda está aberto e não fechou um ciclo. É a leitura
    conservadora — subestima em vez de inflar o número que decide se a postura
    B se justifica."""
    state = read_metrics(target_dir)
    counters = state["counters"]
    return {
        "counters": counters,
        "disable_enable_cycles": min(counters["disable"], counters["enable"]),
        "first_recorded_at": state["first_recorded_at"],
        "last_recorded_at": state["last_recorded_at"],
    }
