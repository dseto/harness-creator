"""Achado F2 do dogfood no MiojoSimulator 3.0 — o comando de instalação.

O mapa dizia `pip -> "pip install -e ."`, que exige um pacote instalável. A
maioria dos serviços Python não é um pacote: declara dependências em
`requirements.txt` e roda direto. Nesses repos o comando correto é
`pip install -r requirements.txt`, e ele caía no default-deny do
`boundary_guard` — enquanto o comando emitido falharia se alguém o rodasse.
"""

from __future__ import annotations

from harness.install_command import (
    INSTALL_COMMAND_BY_PACKAGE_MANAGER,
    install_command_for,
)


def test_pip_with_requirements_evidence_installs_from_requirements() -> None:
    assert install_command_for("pip", "requirements.txt") == "pip install -r requirements.txt"
    assert install_command_for("pip", "requirements-dev.txt") == (
        "pip install -r requirements-dev.txt"
    )
    assert install_command_for("pip", "deploy/requirements.txt") == (
        "pip install -r deploy/requirements.txt"
    )
    assert install_command_for("pip", r"deploy\requirements.txt") == (
        "pip install -r deploy/requirements.txt"
    )


def test_pip_with_package_manifest_evidence_stays_editable_install() -> None:
    """Repo que É um pacote continua com `pip install -e .` — a mudança é
    condicionada à prova, não uma troca cega do default."""
    assert install_command_for("pip", "pyproject.toml") == "pip install -e ."
    assert install_command_for("pip", "setup.py") == "pip install -e ."
    assert install_command_for("pip", None) == "pip install -e ."


def test_other_managers_ignore_evidence() -> None:
    for manager, expected in INSTALL_COMMAND_BY_PACKAGE_MANAGER.items():
        if manager == "pip":
            continue
        assert install_command_for(manager, "requirements.txt") == expected, manager
        assert install_command_for(manager, None) == expected, manager


def test_unknown_or_absent_manager_returns_none() -> None:
    assert install_command_for(None, "requirements.txt") is None
    assert install_command_for("", None) is None
    assert install_command_for("conda", None) is None


def test_the_three_consumers_read_the_same_source() -> None:
    """A razão de o módulo existir: o mapa estava DUPLICADO em três lugares, e
    o F2 era o mesmo defeito nas três cópias. Se alguém reintroduzir uma cópia
    local, este teste continua verde — mas a importação some, e é isso que ele
    fixa: os três importam daqui."""
    import harness.boundary_guard as bg
    import harness.session_permissions as sp
    import harness.templates as tp

    for module in (bg, sp, tp):
        assert module.install_command_for is install_command_for, module.__name__


def test_generated_hook_carries_the_same_function() -> None:
    """O hook standalone é stdlib-only e não importa `harness.*`: a função é
    embutida por `inspect.getsource()`. Se o embutimento sumir, o guard volta a
    negar `pip install -r requirements.txt` enquanto o settings.json o libera."""
    from harness.boundary_guard import render_boundary_guard

    namespace: dict = {}
    exec(compile(render_boundary_guard(), "gen", "exec"), namespace)

    assert namespace["install_command_for"]("pip", "requirements.txt") == (
        "pip install -r requirements.txt"
    )
    assert namespace["install_command_for"]("pip", "pyproject.toml") == "pip install -e ."
