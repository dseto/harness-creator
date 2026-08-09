"""Testes de `harness.health` — o §7.2 do design (health check na abertura).

O passo 2 do protocolo de retomada é o único que ainda não tinha mecanismo. A
consequência não é um erro: é um erro DISFARÇADO. Ferramenta que não responde
chega ao loop como teste vermelho, e o agente gasta o budget consertando código
que está certo — a falha estrutural (§8.2) e a falha de infraestrutura (§8.3)
têm respostas opostas no design, e sem alguém para separá-las o loop aplica a
errada.

O que estes testes travam é o formato da PERGUNTA. Um health check que executa
o `verify_cmd` para descobrir se ele responde custa uma suíte inteira por
abertura — que é exatamente o preço que fez ninguém rodar o `.harness/init.ps1`
que o passo 2 já mandava rodar. Um check caro é um check opcional na prática, e
um check opcional não cobre o modo de falha que ele existe para pegar, porque
esse modo de falha é o silêncio.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from harness.doctor import repo_issues
from harness.health import (
    HEALTH_CLASSIFICATION,
    HEALTH_KIND_GOVERNANCE,
    HEALTH_KIND_MODULE,
    HEALTH_KIND_PROTECTION,
    HEALTH_KIND_TOOL,
    check_tools,
    contract_verify_cmds,
    probe_targets,
    render_session_section,
    run_health,
)


def _write_contract(
    target_dir: Path,
    verify_cmds: list[str],
    slug: str = "demanda-x",
    cwd: str | None = None,
) -> None:
    features = [
        {
            "id": f"T-{n:02d}",
            "desc": f"tarefa {n}",
            "files": [f"src/{n}.py"],
            "verify_cmd": cmd,
            "depends": [],
            "cwd": cwd,
            "passes": False,
        }
        for n, cmd in enumerate(verify_cmds, start=1)
    ]
    (target_dir / ".harness").mkdir(parents=True, exist_ok=True)
    (target_dir / ".harness" / "feature_list.json").write_text(
        json.dumps({"contract": slug, "features": features}, ensure_ascii=False),
        encoding="utf-8",
    )


class _Recorder:
    """Substituto de `subprocess.run` que grava o argv e nunca executa nada."""

    def __init__(self, returncode: int = 0) -> None:
        self.calls: list[list[str]] = []
        self.returncode = returncode

    def __call__(self, argv: list[str], **kwargs: Any) -> Any:
        self.calls.append(list(argv))

        class _Result:
            pass

        result = _Result()
        result.returncode = self.returncode
        result.stdout = ""
        result.stderr = ""
        return result


# ---------------------------------------------------------------------------
# REGRA: de um `verify_cmd`, o que se pergunta é o executável — e também o
# módulo, quando a forma é `<python> -m <módulo>`. É o que separa "instalado"
# de "responde": o interpretador existir não diz nada sobre o runner de teste
# estar no ambiente, e é o runner que falta no caso típico.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProbeCase:
    why: str
    verify_cmd: str
    executable: str
    module: str | None


PROBE_CASES = [
    ProbeCase(
        why="binario direto nao tem modulo a perguntar",
        verify_cmd="pytest tests/test_x.py -q",
        executable="pytest",
        module=None,
    ),
    ProbeCase(
        why="a forma -m expoe o modulo que precisa importar",
        verify_cmd="python -m pytest tests/test_x.py -q",
        executable="python",
        module="pytest",
    ),
    ProbeCase(
        why="modulo com ponto e um modulo so",
        verify_cmd="python -m harness.cli verify T-01",
        executable="python",
        module="harness.cli",
    ),
    ProbeCase(
        why="python versionado continua sendo python",
        verify_cmd="python3.12 -m pytest -q",
        executable="python3.12",
        module="pytest",
    ),
    ProbeCase(
        why="-m de quem nao e python nao e importacao: npm -m nao importa nada",
        verify_cmd="npm -m test",
        executable="npm",
        module=None,
    ),
    ProbeCase(
        why="-m sem argumento nenhum nao aponta modulo",
        verify_cmd="python -m",
        executable="python",
        module=None,
    ),
    ProbeCase(
        why="caminho com espaco vem entre aspas e chega inteiro",
        verify_cmd='"C:/Program Files/py/python.exe" -m pytest -q',
        executable="C:/Program Files/py/python.exe",
        module="pytest",
    ),
    ProbeCase(
        why="comando vazio nao tem o que perguntar",
        verify_cmd="   ",
        executable="",
        module=None,
    ),
    ProbeCase(
        why="o que nao e nome de modulo nao e perguntado como modulo",
        verify_cmd="python -m pathlib;print('oi')",
        executable="python",
        module=None,
    ),
]


@pytest.mark.parametrize("case", PROBE_CASES, ids=lambda c: c.why)
def test_what_gets_probed_from_a_verify_cmd(case: ProbeCase) -> None:
    assert probe_targets(case.verify_cmd) == (case.executable, case.module)


# ---------------------------------------------------------------------------
# REGRA: o check PERGUNTA, nunca EXECUTA. Nenhum argumento do `verify_cmd`
# pode aparecer num argv executado — se aparecesse, a abertura da sessão
# passaria a custar uma suíte de testes, e um check caro vira opcional.
# ---------------------------------------------------------------------------

def test_no_argument_of_the_verify_cmd_is_ever_executed(workspace: Path) -> None:
    canary = "--CANARIO-NAO-EXECUTE-O-VERIFY-CMD"
    _write_contract(workspace, [f"{sys_executable()} -m json.tool tests/alvo.py -q {canary}"])
    recorder = _Recorder()

    check_tools(workspace, run=recorder)

    executed = [arg for argv in recorder.calls for arg in argv]
    assert canary not in executed
    assert "tests/alvo.py" not in executed
    assert "-q" not in executed
    # O único subprocesso permitido é a pergunta de importação.
    for argv in recorder.calls:
        assert argv[1:2] == ["-c"], f"argv inesperado: {argv}"
        assert argv[2].startswith("import "), f"argv inesperado: {argv}"


def sys_executable() -> str:
    import sys

    return sys.executable


# ---------------------------------------------------------------------------
# REGRA: o que vem depois de `-m` só é perguntado se for NOME DE MÓDULO. O
# token entra interpolado num `-c "import ..."`, e o `shlex` só quebra em
# espaço — um payload sem espaços atravessava inteiro e virava código
# executado. Isso roda SOZINHO na abertura da sessão, pelo hook `SessionStart`,
# antes de qualquer humano olhar a branch: o pior lugar possível para confiar
# no conteúdo de um arquivo.
# ---------------------------------------------------------------------------

def test_a_module_name_that_is_not_a_module_name_is_never_executed(workspace: Path) -> None:
    sentinel = workspace / "SENTINELA.txt"
    payload = f"pathlib;pathlib.Path(r'{sentinel}').write_text('EXECUTADO')"
    _write_contract(workspace, [f"{sys_executable()} -m {payload}"])

    report = run_health(workspace)

    assert not sentinel.exists(), "o health check executou codigo vindo do contrato"
    # E o laudo não inventa problema: o executável responde; o que não há é
    # módulo a perguntar.
    assert report["ok"] is True
    assert report["tools"][0]["module"] is None


# ---------------------------------------------------------------------------
# REGRA: ferramenta que não resolve, e módulo que não importa, viram problema
# classificado — e o laudo nomeia o `verify_cmd` que exigia a ferramenta.
# Dizer "falta pytest" sem dizer quem pediu obriga a caçar.
# ---------------------------------------------------------------------------

def test_missing_executable_is_reported_with_the_command_that_needed_it(workspace: Path) -> None:
    _write_contract(workspace, ["ferramenta-que-nao-existe-xyz tests/ -q"])

    checks = check_tools(workspace)

    assert len(checks) == 1
    check = checks[0]
    assert check.ok is False
    assert check.kind == HEALTH_KIND_TOOL
    assert "ferramenta-que-nao-existe-xyz" in check.problem
    assert check.verify_cmd in check.problem


def test_unimportable_module_is_reported_even_with_the_executable_present(workspace: Path) -> None:
    _write_contract(workspace, [f"{sys_executable()} -m modulo_que_nao_existe_xyz -q"])

    checks = check_tools(workspace)

    assert len(checks) == 1
    check = checks[0]
    assert check.ok is False
    assert check.kind == HEALTH_KIND_MODULE
    assert "modulo_que_nao_existe_xyz" in check.problem


def test_a_tool_that_answers_is_not_a_problem(workspace: Path) -> None:
    _write_contract(workspace, [f"{sys_executable()} -m json.tool"])

    checks = check_tools(workspace)

    assert [c.ok for c in checks] == [True]
    assert [c.problem for c in checks] == [None]


# ---------------------------------------------------------------------------
# REGRA: a mesma ferramenta não é perguntada duas vezes. Contrato de 12 fatias
# com o mesmo `verify_cmd` não pode custar 12 subprocessos na abertura.
# ---------------------------------------------------------------------------

def test_the_same_command_is_asked_once(workspace: Path) -> None:
    cmd = f"{sys_executable()} -m json.tool tests/a.py"
    _write_contract(workspace, [cmd, cmd, cmd])

    assert contract_verify_cmds(workspace) == [(cmd, None)]

    recorder = _Recorder()
    check_tools(workspace, run=recorder)
    assert len(recorder.calls) == 1


# ---------------------------------------------------------------------------
# REGRA: sem contrato compilado não há ferramenta a exigir — e isso é silêncio,
# não problema. Um projeto entre demandas não pode abrir a sessão com alarme.
# ---------------------------------------------------------------------------

def test_no_contract_means_nothing_to_demand(workspace: Path) -> None:
    assert contract_verify_cmds(workspace) == []
    assert check_tools(workspace) == []


# ---------------------------------------------------------------------------
# REGRA: o executável é procurado de onde a prova VAI RODAR, e não só no PATH.
# `cwd` existe no contrato justamente para o binário que só resolve de dentro
# do workspace da tarefa (ver `harness.verify`), e um laudo que não olha ali
# devolve `tool_missing` para uma ferramenta que está presente — falso positivo
# é o jeito mais rápido de treinar quem lê a ignorar o aviso.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LocalToolCase:
    why: str
    #: subdiretório onde a ferramenta mora, ou None para a raiz do alvo
    cwd: str | None


LOCAL_TOOL_CASES = [
    LocalToolCase(why="ferramenta na raiz do alvo", cwd=None),
    LocalToolCase(why="ferramenta no cwd declarado pela tarefa", cwd="pacote"),
]


@pytest.mark.parametrize("case", LOCAL_TOOL_CASES, ids=lambda c: c.why)
def test_a_tool_inside_the_workspace_is_found_where_the_proof_will_run(
    workspace: Path, case: LocalToolCase
) -> None:
    base = workspace / case.cwd if case.cwd else workspace
    (base / "tools").mkdir(parents=True, exist_ok=True)
    (base / "tools" / "run.bat").write_text("@echo off\n", encoding="utf-8")
    _write_contract(workspace, ["tools/run.bat -q"], cwd=case.cwd)

    checks = check_tools(workspace)

    assert [c.ok for c in checks] == [True], checks[0].problem


# ---------------------------------------------------------------------------
# REGRA: só quem TEM separador de caminho é procurado dentro da árvore. Nome nu
# é do PATH, como no shell — e a fronteira não é purismo:
#
# - um arquivo qualquer chamado `pytest` na raiz faria o laudo dizer VERDE para
#   uma ferramenta que não existe em lugar nenhum. Silêncio verde é o modo de
#   falha do §8.3 que este módulo existe para pegar: ele inverteria a promessa.
# - um arquivo chamado `python` passaria a decidir QUAL binário o hook da
#   abertura lança sozinho, sem ninguém olhando. Conteúdo da working tree não
#   pode escolher interpretador.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ShadowCase:
    why: str
    #: nome do arquivo plantado na raiz do alvo, igual ao token do comando
    planted: str
    #: veredito esperado — o token nu segue valendo pelo PATH, e só por ele
    ok: bool


SHADOW_CASES = [
    ShadowCase(
        why="ferramenta ausente do PATH nao vira verde por causa de um arquivo homonimo",
        planted="ferramenta-que-nao-existe-xyz",
        ok=False,
    ),
    ShadowCase(
        why="arquivo chamado python nao substitui o interpretador do PATH",
        planted="python",
        ok=True,
    ),
]


@pytest.mark.parametrize("case", SHADOW_CASES, ids=lambda c: c.why)
def test_a_bare_name_is_never_looked_up_inside_the_working_tree(
    workspace: Path, case: ShadowCase
) -> None:
    (workspace / case.planted).write_text("nao sou executavel\n", encoding="utf-8")
    _write_contract(workspace, [f"{case.planted} -m json.tool alvo.json"])
    recorder = _Recorder()

    report = run_health(workspace, run=recorder)

    assert report["ok"] is case.ok
    if not case.ok:
        assert report["problems"][0]["kind"] == HEALTH_KIND_TOOL
    # E nada de dentro da árvore foi lançado: o arquivo plantado não vira argv.
    for argv in recorder.calls:
        assert str(workspace) not in argv[0], f"lancou algo de dentro do alvo: {argv}"


# ---------------------------------------------------------------------------
# REGRA: o laudo tem veredito próprio — `ok` falso quando alguma ferramenta não
# responde. É o que o passo de abertura lê antes de escolher fatia.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VerdictCase:
    why: str
    verify_cmd: str
    ok: bool


VERDICT_CASES = [
    VerdictCase(why="tudo responde", verify_cmd="{py} -m json.tool", ok=True),
    VerdictCase(why="executavel ausente", verify_cmd="binario-inexistente-xyz -q", ok=False),
    VerdictCase(why="modulo ausente", verify_cmd="{py} -m modulo_inexistente_xyz", ok=False),
]


@pytest.mark.parametrize("case", VERDICT_CASES, ids=lambda c: c.why)
def test_the_report_has_its_own_verdict(workspace: Path, case: VerdictCase) -> None:
    _write_contract(workspace, [case.verify_cmd.format(py=sys_executable())])

    report = run_health(workspace)

    assert report["ok"] is case.ok


# ===========================================================================
# T-02 — as três famílias do §8.3 num laudo só
# ===========================================================================

def _break_governance(workspace: Path) -> None:
    """Repositório que PARECE governado e não está: `harness.yaml` versionado,
    nenhum settings compilado. É o clone recém-feito, e nenhum hook roda."""
    (workspace / ".harness").mkdir(parents=True, exist_ok=True)
    (workspace / ".harness" / "harness.yaml").write_text("governance: {}\n", encoding="utf-8")


def _disable_protection(workspace: Path) -> None:
    (workspace / ".harness").mkdir(parents=True, exist_ok=True)
    (workspace / ".harness" / "harness.disabled").write_text(
        json.dumps({"disabled_at": "2026-08-09T00:00:00Z", "note": "teste"}), encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# REGRA: as TRÊS famílias do §8.3 chegam ao mesmo laudo. O design as nomeia
# junto — "hook morto, tool indisponível, guard em no-op" — porque a
# consequência é uma só: o agente continua trabalhando sem as garantias que
# acha que tem. Três diagnósticos em três comandos diferentes é o mesmo que
# nenhum: o modo de falha desta família é o silêncio, e ninguém pergunta três
# vezes o que não desconfia nem uma.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FamilyCase:
    why: str
    kind: str


FAMILY_CASES = [
    FamilyCase(why="ferramenta indisponivel", kind=HEALTH_KIND_TOOL),
    FamilyCase(why="governanca desalinhada (hook morto, settings ausente)", kind=HEALTH_KIND_GOVERNANCE),
    FamilyCase(why="protecao desligada (guard em no-op)", kind=HEALTH_KIND_PROTECTION),
]


@pytest.mark.parametrize("case", FAMILY_CASES, ids=lambda c: c.why)
def test_every_family_of_silent_failure_reaches_one_report(
    workspace: Path, case: FamilyCase
) -> None:
    _write_contract(workspace, ["binario-inexistente-xyz -q"])
    if case.kind != HEALTH_KIND_TOOL:
        # As outras duas famílias precisam de um contrato saudável, senão o
        # laudo ficaria vermelho pela razão errada e o teste não provaria nada.
        _write_contract(workspace, [f"{sys_executable()} -m json.tool"])
    if case.kind == HEALTH_KIND_GOVERNANCE:
        _break_governance(workspace)
    if case.kind == HEALTH_KIND_PROTECTION:
        _disable_protection(workspace)

    report = run_health(workspace)

    assert report["ok"] is False
    assert case.kind in {problem["kind"] for problem in report["problems"]}


def test_a_healthy_repo_reports_no_problem(workspace: Path) -> None:
    _write_contract(workspace, [f"{sys_executable()} -m json.tool"])

    report = run_health(workspace)

    assert report["ok"] is True
    assert report["problems"] == []


# ---------------------------------------------------------------------------
# REGRA: a classificação é `infra`, sempre. É a única informação que muda a
# reação de quem lê: §8.2 (estrutural) manda corrigir e re-verificar, §8.3
# (infra) manda parar. Sem a etiqueta, ferramenta ausente chega ao loop com
# cara de teste vermelho e o agente gasta o budget consertando código correto.
# ---------------------------------------------------------------------------

def test_the_report_classifies_as_infrastructure(workspace: Path) -> None:
    _write_contract(workspace, ["binario-inexistente-xyz -q"])

    report = run_health(workspace)

    assert report["classification"] == HEALTH_CLASSIFICATION == "infra"


# ---------------------------------------------------------------------------
# REGRA (canário): o check NUNCA conserta o que encontra. §8.3 é explícito —
# "loop não conserta a própria jaula". Um health check que instala dependência
# ou recompila hook por conta própria é exatamente o comportamento que o design
# proíbe, e ele apareceria aqui como um subprocesso que não é uma pergunta.
# ---------------------------------------------------------------------------

def test_the_check_never_repairs_what_it_finds(workspace: Path) -> None:
    _write_contract(workspace, [f"{sys_executable()} -m modulo_inexistente_xyz"])
    _break_governance(workspace)
    _disable_protection(workspace)
    before = {
        path: path.read_bytes()
        for path in sorted(workspace.rglob("*"))
        if path.is_file()
    }
    recorder = _Recorder(returncode=1)

    report = run_health(workspace, run=recorder)

    assert report["ok"] is False
    after = {
        path: path.read_bytes()
        for path in sorted(workspace.rglob("*"))
        if path.is_file()
    }
    assert after == before, "o health check escreveu no projeto — ele so pode perguntar"
    for argv in recorder.calls:
        assert argv[1:2] == ["-c"] and argv[2].startswith("import "), (
            f"subprocesso que nao e uma pergunta: {argv}"
        )


# ---------------------------------------------------------------------------
# REGRA: a seção de abertura cala quando está tudo bem, e quando fala diz o
# próximo passo. Silêncio no verde é o que faz o aviso ser lido quando aparece
# (mesma postura de `reconcile.render_session_section`); próximo passo é o que
# separa escalada de reclamação, pelo formato obrigatório do §8.
# ---------------------------------------------------------------------------

def test_the_opening_section_is_silent_when_everything_answers(workspace: Path) -> None:
    _write_contract(workspace, [f"{sys_executable()} -m json.tool"])

    report = run_health(workspace)

    assert render_session_section(report) is None


@dataclass(frozen=True)
class SectionCase:
    why: str
    expected: str


SECTION_CASES = [
    SectionCase(why="a classificacao, que decide a reacao", expected="INFRAESTRUTURA"),
    SectionCase(why="o problema encontrado, nomeado", expected="binario-inexistente-xyz"),
    SectionCase(why="que nao e para escolher fatia ainda", expected="fatia"),
    SectionCase(why="que nao e para consertar por conta propria", expected="Nao tente consertar"),
]


@pytest.mark.parametrize("case", SECTION_CASES, ids=lambda c: c.why)
def test_the_opening_section_says_what_to_do(workspace: Path, case: SectionCase) -> None:
    _write_contract(workspace, ["binario-inexistente-xyz -q"])

    section = render_session_section(run_health(workspace))

    assert case.expected in section


# ---------------------------------------------------------------------------
# REGRA: o laudo de abertura pergunta ao `doctor` sobre ESTE repositório, e o
# cache de plugin do Claude Code não é deste repositório — ele já tem aviso
# próprio na abertura, e ele NÃO bloqueia (o texto do aviso diz isso com todas
# as letras). Somá-lo aqui faria a sessão abrir mandando parar por uma coisa
# que não impede trabalhar.
# ---------------------------------------------------------------------------

def test_repo_issues_leave_the_plugin_cache_to_whoever_owns_it(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from harness import __version__
    from harness.doctor import run_doctor

    _break_governance(workspace)
    cache = workspace / "installed_plugins.json"
    cache.write_text(
        json.dumps({"plugins": {"harness-creator": [{"version": "0.0.1", "installPath": "x"}]}}),
        encoding="utf-8",
    )

    full = run_doctor(workspace, plugins_file=cache).issues
    scoped = repo_issues(workspace)

    assert any("0.0.1" in issue for issue in full), (
        "ancora: o doctor completo continua reportando o cache atrasado"
    )
    assert not any("0.0.1" in issue for issue in scoped)
    # E o que É deste repositório continua chegando aos dois.
    assert any("settings.local.json" in issue for issue in scoped)
    assert __version__
