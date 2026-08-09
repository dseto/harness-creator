"""Testes de `harness.reconcile` — a reconciliação de ABERTURA (§7.4 do
design de loop engineering).

O julgamento não nasce aqui: `finish.audit_closure` já compara estado declarado
com estado real (hash da evidência × código, `passes` × prova, working tree ×
`files[]`). O que este módulo faz é traduzir aquele relatório para a pergunta do
INÍCIO da sessão, que não é a mesma do fecho — e é a tradução que estes testes
travam.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pytest

from harness.killswitch import SENTINEL_RELATIVE_PATH
from harness.reconcile import reconcile, render_session_section
from harness.verify import compute_files_hash


# ---------------------------------------------------------------------------
# helpers de cenário
# ---------------------------------------------------------------------------

def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def _make_repo(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    (target / "src").mkdir(exist_ok=True)
    (target / "src" / "modulo.py").write_text("x = 1\n", encoding="utf-8")
    _git(target, "init", "-b", "main")
    _git(target, "config", "user.email", "test@example.com")
    _git(target, "config", "user.name", "Test")
    _git(target, "add", ".")
    _git(target, "commit", "-m", "init")


def _write_contract(target: Path, *, contract: str = "demo", passes: bool = True) -> None:
    harness_dir = target / ".harness"
    harness_dir.mkdir(exist_ok=True)
    (harness_dir / "feature_list.json").write_text(
        json.dumps(
            {
                "contract": contract,
                "features": [
                    {
                        "id": "T-01",
                        "desc": "faz a coisa",
                        "files": ["src/modulo.py"],
                        "verify_cmd": "pytest -q",
                        "depends": [],
                        "cwd": None,
                        "passes": passes,
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _write_evidence(target: Path, *, contract: str = "demo", files_hash: str | None = None) -> None:
    evidence_dir = target / ".harness" / "evidence" / contract
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "T-01.json").write_text(
        json.dumps(
            {
                "feature_id": "T-01",
                "contract": contract,
                "files": ["src/modulo.py"],
                "files_hash": files_hash or compute_files_hash(["src/modulo.py"], target),
                "passes": True,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _write_progress(target: Path, contract: str) -> None:
    harness_dir = target / ".harness"
    harness_dir.mkdir(exist_ok=True)
    (harness_dir / "progress.md").write_text(
        f"# Claude Progress\n\nContrato: `{contract}`\n\n## Features\n",
        encoding="utf-8",
    )


# --- cenários (cada um deixa o repo num estado; devolve os kinds esperados) ---

def _scenario_clean(target: Path) -> None:
    _make_repo(target)
    _write_contract(target)
    _write_evidence(target)
    _write_progress(target, "demo")


def _scenario_pending_feature(target: Path) -> None:
    _make_repo(target)
    _write_contract(target, passes=False)
    _write_progress(target, "demo")


def _scenario_no_contract(target: Path) -> None:
    _make_repo(target)


def _scenario_evidence_stale(target: Path) -> None:
    _scenario_clean(target)
    (target / "src" / "modulo.py").write_text("x = 999\n", encoding="utf-8")
    _git(target, "add", ".")
    _git(target, "commit", "-m", "muda o codigo depois da prova")


def _scenario_evidence_missing(target: Path) -> None:
    _make_repo(target)
    _write_contract(target)
    _write_progress(target, "demo")


def _scenario_killswitch(target: Path) -> None:
    _scenario_clean(target)
    (target / SENTINEL_RELATIVE_PATH).write_text("{}", encoding="utf-8")


def _scenario_tree_residue(target: Path) -> None:
    _scenario_clean(target)
    (target / "outro.py").write_text("y = 2\n", encoding="utf-8")
    _git(target, "add", "outro.py")
    _git(target, "commit", "-m", "add outro")
    (target / "outro.py").write_text("y = 3\n", encoding="utf-8")


def _scenario_progress_of_another_contract(target: Path) -> None:
    _scenario_clean(target)
    _write_progress(target, "contrato-antigo")


def _scenario_progress_without_feature_list(target: Path) -> None:
    _make_repo(target)
    _write_progress(target, "contrato-antigo")


def _scenario_dir_without_git(target: Path) -> None:
    """Diretório que NÃO é raiz de repo — sandbox, suite e2e, alvo recém-criado.
    Deliberadamente sem `git init`."""
    target.mkdir(parents=True, exist_ok=True)
    (target / "src").mkdir(exist_ok=True)
    (target / "src" / "modulo.py").write_text("x = 1\n", encoding="utf-8")
    _write_contract(target)
    _write_evidence(target)
    _write_progress(target, "demo")


@dataclass(frozen=True)
class ReconcileCase:
    why: str
    setup: Callable[[Path], None]
    expected_kinds: frozenset[str]


CASES = [
    ReconcileCase(
        why="repo integro nao acusa nada",
        setup=_scenario_clean,
        expected_kinds=frozenset(),
    ),
    ReconcileCase(
        # A tradução central: `feature_not_passed` é BLOQUEADOR no fecho e
        # estado NORMAL na abertura. Se entrasse, toda sessão de trabalho
        # abriria com "divergência" e o sinal morreria de ruído.
        why="tarefa pendente e estado normal de quem esta comecando, nao divergencia",
        setup=_scenario_pending_feature,
        expected_kinds=frozenset(),
    ),
    ReconcileCase(
        # Mesma razão: repo antes do primeiro `compile-contract` é bootstrap,
        # não repositório mentindo. A mentira desse caso é coberta por
        # `progress_contract_mismatch`, logo abaixo.
        why="repo sem contrato ainda e bootstrap, nao divergencia",
        setup=_scenario_no_contract,
        expected_kinds=frozenset(),
    ),
    ReconcileCase(
        why="prova anterior ao codigo atual e divergencia",
        setup=_scenario_evidence_stale,
        expected_kinds=frozenset({"evidence_stale"}),
    ),
    ReconcileCase(
        why="tarefa marcada como passando sem prova nenhuma e divergencia",
        setup=_scenario_evidence_missing,
        expected_kinds=frozenset({"evidence_missing"}),
    ),
    ReconcileCase(
        why="harness desligado significa que nada foi governado",
        setup=_scenario_killswitch,
        expected_kinds=frozenset({"killswitch_active"}),
    ),
    ReconcileCase(
        why="sobra tracked fora do contrato e trabalho de outro contexto",
        setup=_scenario_tree_residue,
        expected_kinds=frozenset({"tree_residue"}),
    ),
    ReconcileCase(
        # Bug real da v0.25.0: o `SessionStart` injetou "nenhuma feature
        # pendente" numa sessão com seis tarefas a fazer, porque o progress.md
        # era da demanda anterior. `audit_closure` não vê isso — ele reescreve
        # o arquivo logo depois. Na abertura é a mentira mais cara que existe.
        why="progress.md de outro contrato envenena a sessao inteira",
        setup=_scenario_progress_of_another_contract,
        expected_kinds=frozenset({"progress_contract_mismatch"}),
    ),
    ReconcileCase(
        why="progress.md nomeia contrato que o feature_list nao tem",
        setup=_scenario_progress_without_feature_list,
        expected_kinds=frozenset({"progress_contract_mismatch"}),
    ),
    ReconcileCase(
        # `git status` sobe diretórios até achar um repo. Rodado num alvo que
        # não é raiz de repo — sandbox, e2e, ou um tmp aninhado num home
        # versionado —, ele devolvia a sujeira do repo DE CIMA, e o relatório
        # acusava arquivos que o projeto nem tem. É a mesma armadilha que
        # `branching._has_git_root` já documenta, e que aqui custaria caro: a
        # reconciliação roda em TODA abertura de sessão, e um aviso que aparece
        # sempre, sobre arquivo alheio, é um aviso que ensina a ignorar avisos.
        why="alvo sem git nao herda a sujeira do repo de cima",
        setup=_scenario_dir_without_git,
        expected_kinds=frozenset(),
    ),
]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.why)
def test_reconcile_reports_real_divergence_and_stays_quiet_on_normal_state(
    case: ReconcileCase, tmp_path: Path
) -> None:
    """REGRA: `reconcile` acusa estado declarado que não bate com o real, e só
    isso. O que é estado normal de quem está abrindo a sessão (tarefa pendente,
    repo ainda sem contrato) não vira divergência — um aviso que aparece sempre
    é um aviso que ninguém lê."""
    target = tmp_path / "repo"
    case.setup(target)

    report = reconcile(target)

    assert {d["kind"] for d in report["divergences"]} == set(case.expected_kinds)


def test_every_divergence_carries_a_problem_a_human_can_act_on(tmp_path: Path) -> None:
    """REGRA: `kind` é para máquina, `problem` é para gente. Divergência sem
    frase acionável obriga quem recebe o aviso a ir ler o código do harness
    para descobrir o que fazer."""
    target = tmp_path / "repo"
    _scenario_evidence_stale(target)

    report = reconcile(target)

    assert report["contract"] == "demo"
    assert report["features"] and report["features"][0]["id"] == "T-01"
    for divergence in report["divergences"]:
        assert divergence["kind"]
        assert len(divergence["problem"]) > 20


def test_reconcile_never_writes_anything(tmp_path: Path) -> None:
    """REGRA: reconciliação é SÓ LEITURA, como `audit_closure`. Consertar
    sozinha apagaria o rastro necessário para entender o que divergiu — e um
    comando que roda em toda abertura de sessão não pode ter efeito colateral."""
    target = tmp_path / "repo"
    _scenario_evidence_stale(target)
    before = {p: p.read_bytes() for p in sorted(target.rglob("*")) if p.is_file()}

    reconcile(target)

    after = {p: p.read_bytes() for p in sorted(target.rglob("*")) if p.is_file()}
    assert after == before


# ---------------------------------------------------------------------------
# REGRA (contrato `verificador-cego-do-gate`, T-04): o veredito da camada 3 é
# assunto do FECHO. Na abertura, "ninguém verificou ainda" é o estado normal de
# quem está começando — exatamente como tarefa pendente.
#
# Sem este filtro, TODA sessão nova abriria com divergência, e o aviso morreria
# de ser ruído: o modo de falha que faz humano desligar alerta.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "kind",
    ["blind_review_missing", "blind_review_stale", "blind_review_failed"],
    ids=["ninguem julgou ainda", "julgou antes do codigo mudar", "julgou e reprovou"],
)
def test_the_blind_review_never_becomes_an_opening_divergence(
    tmp_path: Path, kind: str
) -> None:
    from harness.reconcile import OPENING_IGNORED_KINDS

    assert kind in OPENING_IGNORED_KINDS


def test_a_session_that_never_ran_a_blind_review_opens_quiet(tmp_path: Path) -> None:
    """O caso concreto: repo íntegro, sem veredito nenhum — que é como toda
    demanda começa. Tem que abrir com `divergences: []`."""
    target = tmp_path / "repo"
    _scenario_clean(target)

    assert reconcile(target)["divergences"] == []


# ---------------------------------------------------------------------------
# render_session_section — o que o hook SessionStart injeta
# ---------------------------------------------------------------------------

def test_the_session_section_appears_only_when_there_is_something_to_say(
    tmp_path: Path,
) -> None:
    """REGRA: sem divergência, seção nenhuma. O contexto injetado na abertura é
    caro (entra em toda sessão); uma seção dizendo "está tudo bem" gasta o
    orçamento de atenção que o aviso de verdade vai precisar."""
    clean = tmp_path / "limpo"
    _scenario_clean(clean)
    assert render_session_section(reconcile(clean)) is None

    dirty = tmp_path / "sujo"
    _scenario_evidence_stale(dirty)
    section = render_session_section(reconcile(dirty))
    assert section is not None
    assert "evidence_stale" in section
    assert "harness reconcile" in section
