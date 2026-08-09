"""Testes da atualização transparente (`harness.autoupdate`).

T-01 cobre só a DECISÃO (pura, sem efeito colateral): comparar a versão que
gravou os artefatos do projeto (`.harness/compiled-state.json`) com a do
pacote instalado, e dizer o que precisa ser regravado. A execução da
recompilação é T-03.

A comparação é por ordem semver, não por igualdade como faz o `doctor`
(`doctor.py:305`): o `doctor` só reporta, então `!=` basta; uma ação
automática precisa distinguir "atrás" (recompila) de "à frente" (só avisa,
jamais regride)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from harness.autoupdate import (
    AHEAD,
    OUTDATED,
    UNKNOWN,
    UP_TO_DATE,
    parse_version,
    plan_update,
)
from harness.compiler import HARNESS_YAML, STATE_FILE
from harness.session_permissions import FEATURE_LIST_FILE


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def harness_version() -> str:
    import harness

    return harness.__version__


def _write_compiled_state(target: Path, version: str | None) -> None:
    payload: dict = {} if version is None else {"plugin_version": version}
    _write(target / STATE_FILE, json.dumps(payload))


# --------------------------------------------------------------------------
# REGRA 1 — leitura de versão: só `X`, `X.Y` ou `X.Y.Z` de dígitos vira tupla
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ParseCase:
    raw: object
    expect: tuple[int, int, int] | None
    why: str


PARSE_CASES = [
    ParseCase("0.30.0", (0, 30, 0), "forma canônica do projeto"),
    ParseCase("1.2", (1, 2, 0), "faltando patch: completa com zero"),
    ParseCase("7", (7, 0, 0), "só major"),
    ParseCase(" 0.30.0 ", (0, 30, 0), "espaço em volta não invalida"),
    ParseCase("0.30.0.1", None, "componente extra não é semver deste projeto"),
    ParseCase("0.30.0.dev1", None, "instalação de desenvolvimento: ilegível de propósito"),
    ParseCase("0.30.0rc1", None, "pré-release: ilegível de propósito"),
    ParseCase("", None, "string vazia"),
    ParseCase("abc", None, "texto"),
    ParseCase(None, None, "ausente"),
    ParseCase(30, None, "não-string nunca é aceito sem conversão explícita"),
]


@pytest.mark.parametrize("case", PARSE_CASES, ids=lambda c: c.why)
def test_parse_version_only_accepts_plain_numeric_semver(case: ParseCase) -> None:
    assert parse_version(case.raw) == case.expect


def test_parse_version_orders_by_number_not_by_string() -> None:
    """`"0.9.0" > "0.10.0"` em ordem alfabética e `<` em ordem semver — é o
    caso exato que a comparação por string erraria em silêncio."""
    assert parse_version("0.9.0") < parse_version("0.10.0")
    assert parse_version("0.30.0") < parse_version("1.0.0")


# --------------------------------------------------------------------------
# REGRA 2 — veredito: compilado vs instalado
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class VerdictCase:
    compiled: str | None
    installed: str
    expect: str
    why: str


VERDICT_CASES = [
    VerdictCase("0.30.0", "0.30.0", UP_TO_DATE, "mesma versão"),
    VerdictCase("0.29.0", "0.30.0", OUTDATED, "projeto atrás do pacote instalado"),
    VerdictCase("0.9.0", "0.10.0", OUTDATED, "atrás na ordem semver, à frente na alfabética"),
    VerdictCase("0.31.0", "0.30.0", AHEAD, "projeto à frente: nunca regredir"),
    VerdictCase("0.30", "0.30.0", UP_TO_DATE, "componente omitido equivale a zero"),
    VerdictCase(None, "0.30.0", UNKNOWN, "nunca compilado nesta máquina"),
    VerdictCase("nao-e-versao", "0.30.0", UNKNOWN, "estado ilegível: não agir"),
]


@pytest.mark.parametrize("case", VERDICT_CASES, ids=lambda c: c.why)
def test_verdict_compares_compiled_state_against_installed_package(
    tmp_path: Path, case: VerdictCase
) -> None:
    _write(tmp_path / HARNESS_YAML, "version: 1\n")
    _write_compiled_state(tmp_path, case.compiled)

    plan = plan_update(tmp_path, installed_version=case.installed)

    assert plan.verdict == case.expect
    assert plan.compiled_version == case.compiled
    assert plan.installed_version == case.installed


def test_unreadable_compiled_state_is_unknown_not_a_crash(tmp_path: Path) -> None:
    """JSON quebrado nunca derruba a decisão — mesma degradação graciosa dos
    leitores do `doctor`."""
    _write(tmp_path / HARNESS_YAML, "version: 1\n")
    _write(tmp_path / STATE_FILE, "{ isto nao e json")

    plan = plan_update(tmp_path, installed_version="0.30.0")

    assert plan.verdict == UNKNOWN
    assert not plan.should_recompile


# --------------------------------------------------------------------------
# REGRA 3 — quais artefatos regravar: derivado do que existe no projeto
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class StepsCase:
    has_yaml: bool
    has_feature_list: bool
    expect: tuple[str, ...]
    why: str


STEPS_CASES = [
    StepsCase(True, False, ("compile",), "governado sem contrato ativo"),
    StepsCase(True, True, ("compile", "compile-session"), "governado com contrato: compile primeiro"),
    StepsCase(False, True, ("compile-session",), "contrato sem harness.yaml (governança parcial)"),
    StepsCase(False, False, (), "não é projeto governado: nada a regravar"),
]


@pytest.mark.parametrize("case", STEPS_CASES, ids=lambda c: c.why)
def test_steps_follow_the_artifacts_the_project_actually_has(
    tmp_path: Path, case: StepsCase
) -> None:
    if case.has_yaml:
        _write(tmp_path / HARNESS_YAML, "version: 1\n")
    if case.has_feature_list:
        _write(tmp_path / FEATURE_LIST_FILE, json.dumps({"features": []}))
    _write_compiled_state(tmp_path, "0.29.0")

    plan = plan_update(tmp_path, installed_version="0.30.0")

    assert plan.verdict == OUTDATED
    assert plan.steps == case.expect
    assert plan.should_recompile is bool(case.expect)


@dataclass(frozen=True)
class NoRecompileCase:
    compiled: str
    why: str


NO_RECOMPILE_CASES = [
    NoRecompileCase("0.30.0", "em dia não recompila"),
    NoRecompileCase("0.31.0", "à frente não recompila"),
]


@pytest.mark.parametrize("case", NO_RECOMPILE_CASES, ids=lambda c: c.why)
def test_only_an_outdated_project_is_ever_recompiled(
    tmp_path: Path, case: NoRecompileCase
) -> None:
    _write(tmp_path / HARNESS_YAML, "version: 1\n")
    _write(tmp_path / FEATURE_LIST_FILE, json.dumps({"features": []}))
    _write_compiled_state(tmp_path, case.compiled)

    plan = plan_update(tmp_path, installed_version="0.30.0")

    assert not plan.should_recompile
    assert plan.steps == ()


def test_installed_version_defaults_to_the_running_package(tmp_path: Path) -> None:
    """Sem argumento explícito, a referência é o pacote instalado — é assim
    que os dois gatilhos (CLI e SessionStart) vão chamar."""
    import harness

    _write(tmp_path / HARNESS_YAML, "version: 1\n")
    _write_compiled_state(tmp_path, harness.__version__)

    plan = plan_update(tmp_path)

    assert plan.installed_version == harness.__version__
    assert plan.verdict == UP_TO_DATE


# ==========================================================================
# T-03 — execução
# ==========================================================================

class FakeRunner:
    """Substitui o subprocess de recompilação. Registra os argv recebidos e
    devolve os exit codes que o teste programou (default: sucesso)."""

    def __init__(self, exit_codes: list[int] | None = None, raises: Exception | None = None):
        self.calls: list[list[str]] = []
        self._exit_codes = list(exit_codes or [])
        self._raises = raises

    def __call__(self, argv: list[str]) -> int:
        self.calls.append(list(argv))
        if self._raises is not None:
            raise self._raises
        return self._exit_codes.pop(0) if self._exit_codes else 0

    @property
    def steps(self) -> list[str]:
        """O subcomando de cada chamada — `argv` é
        `[<python>, "-m", "harness.cli", <step>, ...]`."""
        return [call[3] for call in self.calls]


def _governed_outdated(tmp_path: Path, *, with_contract: bool = True) -> None:
    _write(tmp_path / HARNESS_YAML, "version: 1\n")
    if with_contract:
        _write(tmp_path / FEATURE_LIST_FILE, json.dumps({"features": []}))
    _write_compiled_state(tmp_path, "0.29.0")


# --------------------------------------------------------------------------
# REGRA 4 — quando NÃO agir: cada motivo é nomeado, nenhum dispara subprocess
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class SkipCase:
    env: dict[str, str]
    kill_switch: bool
    compiled: str
    reason_contains: str
    why: str


SKIP_CASES = [
    SkipCase({"HARNESS_AUTO_UPDATE": "0"}, False, "0.29.0", "HARNESS_AUTO_UPDATE", "opt-out por 0"),
    SkipCase({"HARNESS_AUTO_UPDATE": "false"}, False, "0.29.0", "HARNESS_AUTO_UPDATE", "opt-out por false"),
    SkipCase({"HARNESS_AUTO_UPDATE": "NO"}, False, "0.29.0", "HARNESS_AUTO_UPDATE", "opt-out ignora caixa"),
    SkipCase({"HARNESS_AUTO_UPDATE_RUNNING": "1"}, False, "0.29.0", "recursão", "já rodando: não recursar"),
    SkipCase({}, True, "0.29.0", "kill-switch", "harness desativado"),
    SkipCase({}, False, "0.30.0", "em dia", "nada a fazer"),
    SkipCase({}, False, "0.31.0", "à frente", "projeto adiantado: nunca regride"),
]


@pytest.mark.parametrize("case", SKIP_CASES, ids=lambda c: c.why)
def test_recompilation_is_skipped_and_the_reason_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: SkipCase
) -> None:
    from harness.autoupdate import sync_if_outdated

    _governed_outdated(tmp_path)
    _write_compiled_state(tmp_path, case.compiled)
    if case.kill_switch:
        _write(tmp_path / ".harness" / "harness.disabled", "{}")
    for key in ("HARNESS_AUTO_UPDATE", "HARNESS_AUTO_UPDATE_RUNNING"):
        monkeypatch.delenv(key, raising=False)
    for key, value in case.env.items():
        monkeypatch.setenv(key, value)

    runner = FakeRunner()
    result = sync_if_outdated(tmp_path, installed_version="0.30.0", runner=runner)

    assert runner.calls == []
    assert not result.recompiled
    assert case.reason_contains in result.skipped_reason


def test_a_project_that_is_not_governed_is_left_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`compiled-state.json` órfão, sem `harness.yaml` nem contrato: não há
    artefato a produzir, e escrever ali seria intrusão."""
    from harness.autoupdate import sync_if_outdated

    monkeypatch.delenv("HARNESS_AUTO_UPDATE", raising=False)
    _write_compiled_state(tmp_path, "0.29.0")

    runner = FakeRunner()
    result = sync_if_outdated(tmp_path, installed_version="0.30.0", runner=runner)

    assert runner.calls == []
    assert not result.recompiled


# --------------------------------------------------------------------------
# REGRA 5 — quando agir: quais comandos, em que ordem, com quais flags
# --------------------------------------------------------------------------

def test_outdated_project_is_recompiled_in_order_and_never_touches_the_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys as _sys

    from harness.autoupdate import sync_if_outdated

    monkeypatch.delenv("HARNESS_AUTO_UPDATE", raising=False)
    monkeypatch.delenv("HARNESS_AUTO_UPDATE_RUNNING", raising=False)
    _governed_outdated(tmp_path)

    runner = FakeRunner()
    result = sync_if_outdated(tmp_path, installed_version="0.30.0", runner=runner)

    assert result.recompiled
    assert runner.steps == ["compile", "compile-session"]
    assert all(call[0] == _sys.executable for call in runner.calls)
    assert all(call[1:3] == ["-m", "harness.cli"] for call in runner.calls)
    assert all(str(tmp_path) in call for call in runner.calls)
    # A garantia central de T-02: a recompilação automática nunca cria nem
    # troca branch.
    assert "--no-branch" in runner.calls[1]
    assert "--no-branch" not in runner.calls[0]


def test_recompilation_reports_what_it_did_on_stderr_never_on_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """O stdout dos comandos do harness é JSON que outros processos parseiam
    — uma linha de aviso ali quebraria o parse do chamador."""
    from harness.autoupdate import sync_if_outdated

    monkeypatch.delenv("HARNESS_AUTO_UPDATE", raising=False)
    monkeypatch.delenv("HARNESS_AUTO_UPDATE_RUNNING", raising=False)
    _governed_outdated(tmp_path)

    sync_if_outdated(tmp_path, installed_version="0.30.0", runner=FakeRunner())

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "0.29.0" in captured.err
    assert "0.30.0" in captured.err


def test_a_project_ahead_of_the_installed_package_is_warned_not_downgraded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Máquina B com pip antigo abrindo um repositório compilado na máquina
    A. Regredir aqui faria as duas máquinas brigarem a cada sessão."""
    from harness.autoupdate import sync_if_outdated

    monkeypatch.delenv("HARNESS_AUTO_UPDATE", raising=False)
    _governed_outdated(tmp_path)
    _write_compiled_state(tmp_path, "0.31.0")

    runner = FakeRunner()
    sync_if_outdated(tmp_path, installed_version="0.30.0", runner=runner)

    assert runner.calls == []
    assert "0.31.0" in capsys.readouterr().err


# --------------------------------------------------------------------------
# REGRA 6 — fail-open: falhar a atualização nunca quebra quem a disparou
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class FailureCase:
    runner: object
    why: str


FAILURE_CASES = [
    FailureCase(FakeRunner(exit_codes=[1, 0]), "primeiro passo sai diferente de zero"),
    FailureCase(FakeRunner(raises=OSError("interpretador sumiu")), "interpretador irresolúvel"),
    FailureCase(FakeRunner(raises=RuntimeError("qualquer coisa inesperada")), "erro inesperado"),
]


@pytest.mark.parametrize("case", FAILURE_CASES, ids=lambda c: c.why)
def test_a_failed_recompilation_warns_and_lets_the_original_command_proceed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    case: FailureCase,
) -> None:
    from harness.autoupdate import sync_if_outdated

    monkeypatch.delenv("HARNESS_AUTO_UPDATE", raising=False)
    monkeypatch.delenv("HARNESS_AUTO_UPDATE_RUNNING", raising=False)
    _governed_outdated(tmp_path)

    result = sync_if_outdated(tmp_path, installed_version="0.30.0", runner=case.runner)

    assert not result.recompiled
    assert "aviso" in capsys.readouterr().err.lower()


def test_a_failed_first_step_does_not_run_the_second(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`compile-session` depende do que `compile` grava; encadear em cima de
    um `compile` que falhou só produz um segundo erro menos legível."""
    from harness.autoupdate import sync_if_outdated

    monkeypatch.delenv("HARNESS_AUTO_UPDATE", raising=False)
    monkeypatch.delenv("HARNESS_AUTO_UPDATE_RUNNING", raising=False)
    _governed_outdated(tmp_path)

    runner = FakeRunner(exit_codes=[1, 0])
    sync_if_outdated(tmp_path, installed_version="0.30.0", runner=runner)

    assert runner.steps == ["compile"]


def test_an_error_while_inspecting_the_version_is_a_warning_not_an_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A inspeção roda antes de TODO comando do harness. Se ela levantar,
    quem quebra é o comando do usuário — daí a promessa de que
    `sync_if_outdated` nunca levanta valer também para a metade pura."""
    import harness.autoupdate as autoupdate

    monkeypatch.delenv("HARNESS_AUTO_UPDATE", raising=False)
    _governed_outdated(tmp_path)

    def explode(*_args: object, **_kwargs: object) -> None:
        raise OSError("disco em erro")

    monkeypatch.setattr(autoupdate, "plan_update", explode)

    result = autoupdate.sync_if_outdated(tmp_path, installed_version="0.30.0")

    assert not result.recompiled
    assert result.plan.verdict == UNKNOWN
    assert "aviso" in capsys.readouterr().err.lower()


def _run_module_main(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, plugins: dict) -> dict:
    """Roda `python -m harness.autoupdate` in-process e devolve o JSON impresso."""
    import harness.autoupdate as autoupdate

    plugins_file = tmp_path / "installed_plugins.json"
    plugins_file.write_text(json.dumps(plugins), encoding="utf-8")
    monkeypatch.setattr(
        autoupdate, "DEFAULT_INSTALLED_PLUGINS_FILE", plugins_file, raising=False
    )
    import harness.doctor as doctor_module
    monkeypatch.setattr(doctor_module, "DEFAULT_INSTALLED_PLUGINS_FILE", plugins_file)

    import io
    import contextlib

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        autoupdate._main(["--dir", str(tmp_path)])
    return json.loads(buffer.getvalue())


def _plugins_payload(version: str) -> dict:
    return {"plugins": {"harness-creator@local": [{"version": version, "installPath": "x"}]}}


def test_the_payload_carries_the_stale_plugin_so_the_hook_can_warn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O hook `SessionStart` não importa `harness` (roda com -S). Este payload
    é o único canal por onde a informação de versão chega até ele."""
    monkeypatch.delenv("HARNESS_AUTO_UPDATE", raising=False)
    monkeypatch.delenv("HARNESS_AUTO_UPDATE_RUNNING", raising=False)
    _write(tmp_path / HARNESS_YAML, "version: 1\n")
    _write_compiled_state(tmp_path, harness_version())

    data = _run_module_main(tmp_path, monkeypatch, _plugins_payload("0.0.1"))

    assert len(data["stale_plugins"]) == 1
    entry = data["stale_plugins"][0]
    assert entry["id"] == "harness-creator@local"
    assert entry["version"] == "0.0.1"
    assert entry["command"] == "claude plugin update harness-creator@local"


def test_the_payload_reports_the_plugin_even_when_nothing_was_recompiled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Projeto em dia não dispara recompilação nenhuma — e mesmo assim o aviso
    de plugin precisa sair, porque são defasagens independentes."""
    monkeypatch.delenv("HARNESS_AUTO_UPDATE", raising=False)
    _write(tmp_path / HARNESS_YAML, "version: 1\n")
    _write_compiled_state(tmp_path, harness_version())

    data = _run_module_main(tmp_path, monkeypatch, _plugins_payload("0.0.1"))

    assert data["recompiled"] is False
    assert data["stale_plugins"]


def test_opting_out_of_the_update_does_not_opt_out_of_being_informed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`HARNESS_AUTO_UPDATE=0` desliga o AGIR, não o INFORMAR. Calar os dois
    com uma chave só devolveria a invisibilidade que este canal remove."""
    monkeypatch.setenv("HARNESS_AUTO_UPDATE", "0")
    _write(tmp_path / HARNESS_YAML, "version: 1\n")
    _write_compiled_state(tmp_path, "0.0.1")

    data = _run_module_main(tmp_path, monkeypatch, _plugins_payload("0.0.1"))

    assert data["recompiled"] is False
    assert "HARNESS_AUTO_UPDATE" in data["skipped_reason"]
    assert data["stale_plugins"]


@dataclass(frozen=True)
class QuietPayloadCase:
    plugins: dict
    why: str


QUIET_PAYLOAD_CASES = [
    QuietPayloadCase({"plugins": {}}, "nenhum plugin registrado"),
    QuietPayloadCase({"plugins": {"outro@x": [{"version": "0.0.1"}]}}, "plugin de terceiro"),
]


@pytest.mark.parametrize("case", QUIET_PAYLOAD_CASES, ids=lambda c: c.why)
def test_the_payload_says_nothing_when_there_is_nothing_to_warn_about(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: QuietPayloadCase
) -> None:
    monkeypatch.delenv("HARNESS_AUTO_UPDATE", raising=False)
    _write(tmp_path / HARNESS_YAML, "version: 1\n")
    _write_compiled_state(tmp_path, harness_version())

    data = _run_module_main(tmp_path, monkeypatch, case.plugins)

    assert data["stale_plugins"] == []


def test_a_failure_reading_the_plugin_cache_never_breaks_the_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O payload é consumido pelo hook de sessão. Uma exceção aqui custaria o
    contexto inteiro da sessão por causa de um aviso acessório."""
    import harness.autoupdate as autoupdate
    import harness.doctor as doctor_module

    monkeypatch.delenv("HARNESS_AUTO_UPDATE", raising=False)
    _write(tmp_path / HARNESS_YAML, "version: 1\n")
    _write_compiled_state(tmp_path, harness_version())

    def explode(*_args: object, **_kwargs: object) -> None:
        raise OSError("cache ilegivel")

    monkeypatch.setattr(doctor_module, "stale_plugin_installs", explode)

    import io
    import contextlib

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        exit_code = autoupdate._main(["--dir", str(tmp_path)])

    assert exit_code == 0
    assert json.loads(buffer.getvalue())["stale_plugins"] == []


def test_the_recompilation_subprocess_is_marked_so_it_cannot_recurse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O subprocess é a própria CLI, que roda o mesmo gatilho. A isenção por
    nome de subcomando mora no chamador; esta marca fecha o caso de dentro,
    para qualquer chamador futuro."""
    import harness.autoupdate as autoupdate

    monkeypatch.delenv("HARNESS_AUTO_UPDATE", raising=False)
    monkeypatch.delenv("HARNESS_AUTO_UPDATE_RUNNING", raising=False)
    _governed_outdated(tmp_path)

    seen: list[dict[str, str]] = []

    def fake_subprocess_run(argv, **kwargs):  # noqa: ANN001, ANN003
        seen.append(dict(kwargs.get("env") or {}))

        class _Completed:
            returncode = 0

        return _Completed()

    monkeypatch.setattr(autoupdate.subprocess, "run", fake_subprocess_run)
    autoupdate.sync_if_outdated(tmp_path, installed_version="0.30.0")

    assert seen
    assert all(env.get(autoupdate.RECURSION_ENV) == "1" for env in seen)
