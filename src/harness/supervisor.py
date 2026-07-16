"""Supervisor: leitor de estado que decide a PRÓXIMA feature a trabalhar.

Fase 4 do ROADMAP ("despacho dinâmico"): `contract.py` já parseia `depends[]`
desde a Fase 1, mas até este módulo nenhum consumidor real ordenava as
features por essa dependência. Este módulo é o primeiro: uma leitura de
`.harness/feature_list.json` que devolve a feature "pronta" seguinte,
respeitando `depends[]`.

Não é um daemon/loop (decisão do planejador #7 do backlog) — `dispatch_next`
é uma chamada síncrona que lê o estado atual, decide e devolve; quem chama
decide o que fazer com o resultado (ex.: delegar a um subagente). Este
módulo NUNCA executa `verify_cmd`/git/subprocess por conta própria — isso é
escopo de `verify.py`. A única escrita em disco feita aqui é indireta, via
`harness.review.submit_for_review` (IMPORTADA, nunca reimplementada) quando
`on_feature_verified` decide que o time compilado tem os papéis
`producer`+`reviewer`.

Schema do manifesto de time consumido aqui —
`.harness/team/manifest.json` (fixado pelo SUBAGENTE 06 de `teams.py`; este
módulo só LÊ o JSON, nunca importa nada de `teams.py`):

    {
      "pattern": "producer-reviewer",
      "mode": "subagents",
      "roles": ["producer", "reviewer"],
      "max_review_iterations": 3,
      "generated_at": "2026-07-16T12:00:00+00:00"
    }
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from harness.contract import FEATURE_LIST_FILE
from harness.review import submit_for_review

TEAM_MANIFEST_FILE = ".harness/team/manifest.json"


def ready_features(feature_list: dict[str, Any]) -> list[dict[str, Any]]:
    """Devolve, na MESMA ordem de `feature_list['features']`, as features com
    `passes != True` cujos `depends` (lista de ids) estão TODOS com
    `passes == True` no mesmo `feature_list`.

    Dependência para um id inexistente é tratada como NÃO satisfeita — a
    feature nunca fica pronta; nenhuma exceção é levantada, ela apenas não
    entra na lista devolvida.
    """
    features = feature_list.get("features") or []
    by_id = {f["id"]: f for f in features if "id" in f}

    ready: list[dict[str, Any]] = []
    for feature in features:
        if feature.get("passes") is True:
            continue

        depends = feature.get("depends") or []
        satisfied = True
        for dep_id in depends:
            dep = by_id.get(dep_id)
            if dep is None or dep.get("passes") is not True:
                satisfied = False
                break

        if satisfied:
            ready.append(feature)

    return ready


def dispatch_next(target_dir: Path) -> dict[str, Any] | None:
    """Lê `.harness/feature_list.json` (via `harness.contract.FEATURE_LIST_FILE`)
    e devolve a PRIMEIRA feature pronta (ver `ready_features`), ou `None` se
    não houver nenhuma. Ausência do arquivo (ou JSON inválido) -> `None`, sem
    levantar exceção. SÓ LEITURA — nunca escreve nada, nunca executa
    `verify_cmd`/git/subprocess de qualquer tipo.
    """
    target_dir = Path(target_dir).resolve()
    feature_list_path = target_dir / FEATURE_LIST_FILE
    if not feature_list_path.is_file():
        return None

    try:
        data = json.loads(feature_list_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None

    candidates = ready_features(data)
    return candidates[0] if candidates else None


def on_feature_verified(
    target_dir: Path, feature_id: str, max_review_iterations: int = 3
) -> dict[str, Any] | None:
    """Chamada depois que `harness verify <feature_id>` já rodou com sucesso
    (evidência gravada). Lê `.harness/team/manifest.json`: ausência ou JSON
    inválido -> devolve `None` (time não compilado, nada a fazer).

    Se o manifesto declarar os papéis `producer`+`reviewer`, aciona
    `harness.review.submit_for_review` (IMPORTADA — a transição de estado
    não é reimplementada aqui) e devolve o dict completo já gravado por ela.
    Sem os dois papéis no manifesto, devolve `None` sem chamar
    `submit_for_review` (zero-op quando o time não tem produtor+revisor).
    """
    target_dir = Path(target_dir).resolve()
    manifest_path = target_dir / TEAM_MANIFEST_FILE
    if not manifest_path.is_file():
        return None

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None

    roles = set(manifest.get("roles") or [])
    if not {"producer", "reviewer"} <= roles:
        return None

    effective_max_iterations = manifest.get("max_review_iterations", max_review_iterations)
    return submit_for_review(target_dir, feature_id, max_iterations=effective_max_iterations)
