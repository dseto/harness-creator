"""Comando de instalação de dependências derivado do `package_manager`.

Fonte ÚNICA do mapeamento que estava triplicado em `boundary_guard.py`,
`session_permissions.py` e `templates.py` — cada cópia com o mesmo defeito, o
que é a razão de existir este módulo e não só uma correção pontual.

**O defeito (achado F2 do dogfood venv-Windows).** O mapa dizia
`pip -> "pip install -e ."`, que exige um pacote instalável (`pyproject.toml`
ou `setup.py` com metadados). A maioria dos serviços Python **não** é um
pacote: declara dependências em `requirements.txt` e roda direto. Nesses
repos o comando correto é `pip install -r requirements.txt`, e ele caía no
default-deny do `boundary_guard` — enquanto o comando emitido, `pip install
-e .`, falharia se alguém o rodasse.

**Por que a decisão é por EVIDÊNCIA e não por um valor novo de
`package_manager`.** O `analyzer` já grava, em `package_manager.evidence`, o
arquivo que provou o achado (`uv.lock`, `package-lock.json`,
`requirements.txt`, `pyproject.toml`). Essa é exatamente a informação que
falta, e ela já viaja no profile. Criar um `package_manager: "pip-requirements"`
vazaria um detalhe de layout para dentro de uma enumeração que descreve
FERRAMENTA, e quebraria todo consumidor que compara com `"pip"`.

O módulo é stdlib-only e sem imports do pacote: `render_boundary_guard()`
embute `install_command_for` no hook standalone via `inspect.getsource()`.
"""

from __future__ import annotations

#: `package_manager.value` -> comando de instalação. O valor bruto do profile
#: (ex.: `npm`) NUNCA vira um comando permitido por si só: isso liberaria
#: qualquer subcomando (`npm run x`, `npm exec`), não só a instalação.
INSTALL_COMMAND_BY_PACKAGE_MANAGER: dict[str, str] = {
    "npm": "npm ci",
    "pnpm": "pnpm install --frozen-lockfile",
    "yarn": "yarn install --frozen-lockfile",
    "uv": "uv sync",
    "poetry": "poetry install",
    "pip": "pip install -e .",
}


def install_command_for(package_manager, evidence=None):
    """Comando de instalação para `package_manager`, ou `None` se desconhecido.

    `evidence` é o `package_manager.evidence` do `repo-profile.json` — o
    arquivo que provou o achado. Quando o gerenciador é `pip` e a prova é um
    `requirements*.txt`, o comando passa a ser `pip install -r <arquivo>`:
    um repo que declara dependências assim tipicamente não é um pacote
    instalável, e `pip install -e .` falharia nele.

    Sem evidência, ou com evidência de manifesto de pacote
    (`pyproject.toml`/`setup.py`), o comando segue `pip install -e .`.
    """
    if not package_manager:
        return None
    command = INSTALL_COMMAND_BY_PACKAGE_MANAGER.get(package_manager)
    if command is None:
        return None
    if package_manager != "pip" or not evidence:
        return command
    basename = str(evidence).replace("\\", "/").rsplit("/", 1)[-1].lower()
    if basename.startswith("requirements") and basename.endswith(".txt"):
        return "pip install -r " + str(evidence).replace("\\", "/")
    return command
