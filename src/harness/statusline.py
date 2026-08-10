"""Statusline do Claude Code — o placar reduzido a UMA linha sempre visível.

Terceiro render do contrato `placar-de-andamento`, e o único que não precisa
ser pedido: o `--brief` o agente cola, o painel o dev abre num segundo
terminal, e esta linha simplesmente está lá na barra do CLI enquanto a sessão
corre. Mostra demanda, progresso, tarefa atual, tentativa, o veredito da
última prova — e o custo da sessão quando o próprio CLI o entrega no stdin.

**Por que o hook é standalone (stdlib-only, sem `import harness`)**: ele é
executado pelo Claude Code, fora do venv do projeto — a mesma razão de
`session_start`, `stop_hook` e `boundary_guard` serem gerados assim. O preço é
que a leitura do estado aparece duas vezes no repositório (aqui e em
`panel.py`); o teto desse preço é a linha ser deliberadamente magra: ela lê
`feature_list.json` e a última linha do rastro de tentativas, nada mais. Toda
regra de decisão (disjuntor, veredito, próximo passo) fica em `panel.py` e
NÃO é replicada aqui.

Contrato do Claude Code (confirmado na documentação oficial,
https://code.claude.com/docs/en/statusline): a entrada em settings é
`statusLine: {"type": "command", "command": "..."}` e o stdin traz, entre
outros campos, `cost.total_cost_usd`. Campo ausente ou stdin ilegível não é
erro — a linha sai sem custo. Uma barra que some quando um campo opcional
falta é pior que uma barra sem o campo.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from harness.hook_launcher import hook_command
from harness.killswitch import DISABLED_CHECK_SRC
from harness.settings_paths import prepare_managed_settings, write_managed_settings

HOOKS_DIR = ".harness/hooks"
HOOK_FILENAME = "statusline.py"
SESSION_STATE_FILE = ".harness/compiled-state-session.json"
STATE_KEY = "statusline_command"
SETTINGS_KEY = "statusLine"


# ---------------------------------------------------------------------------
# render (puro) — conteúdo do script standalone
# ---------------------------------------------------------------------------

def render_statusline_hook() -> str:
    """Código-fonte do comando de statusline (stdlib only, sem `harness`)."""
    return '''#!/usr/bin/env python
"""Statusline do harness -- UMA linha com o andamento da demanda.

GERADO por `harness compile-session` (harness.statusline). Nao edite: a
proxima compilacao sobrescreve. Stdlib-only de proposito -- roda fora do venv
do projeto, igual aos outros hooks gerados.

Fail-safe em tudo: qualquer erro de leitura vira uma linha mais curta, nunca
uma barra vazia nem um traceback na interface.
"""

import json
import sys
from pathlib import Path


''' + DISABLED_CHECK_SRC + '''


def _repo_root():
    # O hook mora em <repo>/.harness/hooks/statusline.py -- ancorar por
    # __file__ e nao pelo cwd do payload (que deriva com /add-dir).
    return Path(__file__).resolve().parent.parent.parent


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None


def _last_attempt(root, contract, feature_id):
    path = root / ".harness" / "attempts" / (contract or "_sem-contrato") / (feature_id + ".jsonl")
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return None, 0
    failures = 0
    last = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict) or not record.get("result"):
            continue
        last = record
        if record.get("result") == "pass":
            failures = 0
        elif record.get("classification") != "transient":
            failures += 1
    return last, failures


def _cost(payload):
    cost = payload.get("cost") if isinstance(payload, dict) else None
    value = cost.get("total_cost_usd") if isinstance(cost, dict) else None
    if not isinstance(value, (int, float)):
        return None
    return "$" + ("%.2f" % value)


def build_line(root, payload):
    parts = []
    if _harness_disabled():
        parts.append("harness DESATIVADO")

    data = _read_json(root / ".harness" / "feature_list.json")
    features = []
    contract = None
    if isinstance(data, dict):
        contract = data.get("contract")
        features = [f for f in (data.get("features") or []) if isinstance(f, dict)]

    if not features:
        parts.append("sem contrato compilado")
    else:
        done = sum(1 for f in features if f.get("passes") is True)
        by_id = dict((str(f.get("id")), f) for f in features)
        current = None
        for feature in features:
            if feature.get("passes") is True:
                continue
            depends = feature.get("depends") or []
            if all(
                (by_id.get(d) or {}).get("passes") is True for d in depends
            ):
                current = feature
                break

        parts.append(str(contract or "?"))
        parts.append("%d/%d" % (done, len(features)))

        if current is None:
            parts.append("tudo verde -- rode harness finish")
        else:
            feature_id = str(current.get("id"))
            parts.append(feature_id)
            last, failures = _last_attempt(root, contract, feature_id)
            parts.append("tentativa %d" % (failures + 1))
            if last is None:
                parts.append("prova ainda nao rodou")
            elif last.get("result") == "pass":
                parts.append("prova passou")
            else:
                line = (last.get("failure_line") or "").strip()
                parts.append("prova falhou: " + line[:60] if line else "prova falhou")

    cost = _cost(payload)
    if cost:
        parts.append(cost)

    return " | ".join(parts)


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    try:
        line = build_line(_repo_root(), payload)
    except Exception:
        line = "harness: placar indisponivel"
    sys.stdout.write(line + "\\n")


if __name__ == "__main__":
    main()
'''


# ---------------------------------------------------------------------------
# install — grava o hook e registra a entrada no settings machine-local
# ---------------------------------------------------------------------------

def install_statusline(target_dir: Path | str, *, replace_foreign: bool = True) -> Path:
    """Grava o hook de statusline e registra `statusLine` no settings
    machine-local. Devolve o caminho do hook.

    Idempotente pelo mesmo mecanismo de `install_session_start`: o comando
    registrado fica em `.harness/compiled-state-session.json`, então recompilar
    substitui a entrada anterior em vez de empilhar uma nova — e uma entrada
    antiga, escrita por uma versão que formatava o `command` de outro jeito,
    ainda é reconhecida pelo NOME do arquivo.

    `replace_foreign=False` protege uma statusline que o USUÁRIO configurou:
    entrada que o harness não instalou (não bate com o estado compilado nem
    aponta para o hook) é decisão da pessoa, e sobrescrevê-la seria o
    compilador escolhendo o que aparece na barra dela. O hook é gravado assim
    mesmo — fica pronto para quando ela quiser apontar para ele.
    """
    target_dir = Path(target_dir).resolve()

    hooks_dir = target_dir / HOOKS_DIR
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_path = hooks_dir / HOOK_FILENAME
    hook_path.write_text(render_statusline_hook(), encoding="utf-8")

    command = hook_command(hook_path)

    state_path = target_dir / SESSION_STATE_FILE
    state = _load_json(state_path)
    prev_command = state.get(STATE_KEY)

    settings_path, settings = prepare_managed_settings(target_dir)
    existing = settings.get(SETTINGS_KEY)

    if not replace_foreign and isinstance(existing, dict):
        foreign = (
            existing.get("command") not in (prev_command, command)
            and HOOK_FILENAME not in str(existing.get("command") or "")
        )
        if foreign:
            return hook_path

    settings[SETTINGS_KEY] = {"type": "command", "command": command}
    write_managed_settings(settings_path, settings)

    state[STATE_KEY] = command
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    return hook_path


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}
