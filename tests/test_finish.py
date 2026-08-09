"""Testes do `harness finish` — o comando único de encerramento da demanda.

Contrato `harness-finish`. Duas metades, separadas pelo `-k` dos verify_cmd:
`audit` (T-01, auditoria read-only do fecho) e `sweep` (T-02, varredura dos
descartáveis do `.harness/`). A auditoria é o gate: havendo bloqueador, nada é
varrido.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from harness.blind import record_verdict
from harness.finish import FinishError, audit_closure, sweep_disposables
from harness.killswitch import SENTINEL_RELATIVE_PATH
from harness.templates import install_templates
from harness.verify import compute_files_hash


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def _kinds(report: dict) -> set[str]:
    return {blocker["kind"] for blocker in report["blockers"]}


def _make_repo(target: Path, *, tracked_code: str = "x = 1\n") -> None:
    """Repo git com um arquivo de código tracked e o `.harness/` versionado —
    o formato real de quem adota o harness e commita a governança."""
    target.mkdir(parents=True, exist_ok=True)
    (target / "src").mkdir(exist_ok=True)
    (target / "src" / "modulo.py").write_text(tracked_code, encoding="utf-8")
    (target / "outro.py").write_text("y = 2\n", encoding="utf-8")
    _git(target, "init", "-b", "main")
    _git(target, "config", "user.email", "test@example.com")
    _git(target, "config", "user.name", "Test")
    _git(target, "add", ".")
    _git(target, "commit", "-m", "init")


def _write_contract(
    target: Path,
    *,
    contract: str = "demo",
    passes: bool = True,
    files: list[str] | None = None,
) -> list[str]:
    files = files if files is not None else ["src/modulo.py"]
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
                        "files": files,
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
    return files


def _write_evidence(
    target: Path, *, contract: str = "demo", files: list[str], files_hash: str | None = None
) -> Path:
    evidence_dir = target / ".harness" / "evidence" / contract
    evidence_dir.mkdir(parents=True, exist_ok=True)
    path = evidence_dir / "T-01.json"
    path.write_text(
        json.dumps(
            {
                "feature_id": "T-01",
                "contract": contract,
                "desc": "faz a coisa",
                "files": files,
                "verify_cmd": "pytest -q",
                "recorded_at": "2026-07-28T12:00:00+00:00",
                "exit_code": 0,
                "files_hash": files_hash or compute_files_hash(files, target),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def _clean_closure(target: Path) -> list[str]:
    """Fecho íntegro: contrato com tudo passando, evidência fresca, tree limpa
    e veredito independente sobre o estado atual.

    O veredito entrou aqui no contrato `verificador-cego-do-gate`: a partir
    dele, prova de camada 2 sem camada 3 deixou de ser fecho íntegro."""
    _make_repo(target)
    files = _write_contract(target)
    _write_evidence(target, files=files)
    record_verdict(target, passed=True, evidence="conferi src/modulo.py:1")
    return files


# ---------------------------------------------------------------------------
# T-01 — auditoria (read-only)
# ---------------------------------------------------------------------------

def test_audit_approves_a_clean_closure(tmp_path: Path) -> None:
    _clean_closure(tmp_path)

    report = audit_closure(tmp_path)

    assert report["blockers"] == []
    assert report["contract"] == "demo"


def test_audit_blocks_when_the_killswitch_is_active(tmp_path: Path) -> None:
    """Encerrar a demanda com o guard em no-op significa que a sessão inteira
    rodou sem governança — o modo de falha silenciosa da issue #52. O `finish`
    é a superfície mais barata para pegá-lo: acontece uma vez por demanda,
    exatamente quando as conclusões vão ser tiradas."""
    _clean_closure(tmp_path)
    (tmp_path / SENTINEL_RELATIVE_PATH).write_text("{}", encoding="utf-8")

    report = audit_closure(tmp_path)

    assert "killswitch_active" in _kinds(report)


def test_audit_blocks_without_a_contract(tmp_path: Path) -> None:
    _make_repo(tmp_path)

    report = audit_closure(tmp_path)

    assert "no_contract" in _kinds(report)
    assert report["contract"] is None


def test_audit_blocks_when_a_feature_did_not_pass(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    _write_contract(tmp_path, passes=False)

    report = audit_closure(tmp_path)

    assert "feature_not_passed" in _kinds(report)
    problem = next(b["problem"] for b in report["blockers"] if b["kind"] == "feature_not_passed")
    assert "T-01" in problem


def test_audit_blocks_when_evidence_is_missing(tmp_path: Path) -> None:
    """`passes: true` sem arquivo de evidência é uma feature marcada à mão —
    exatamente o que o lifecycle proíbe no passo 13."""
    _make_repo(tmp_path)
    _write_contract(tmp_path)

    report = audit_closure(tmp_path)

    assert "evidence_missing" in _kinds(report)


def test_audit_blocks_when_the_evidence_is_older_than_the_code(tmp_path: Path) -> None:
    """O `files_hash` gravado na evidência prova que o teste passou CONTRA
    aquele conteúdo. Se o código mudou depois, a prova não prova mais nada —
    e é o caso mais fácil de passar despercebido, porque a feature continua
    `passes: true` e o arquivo de evidência continua lá."""
    files = _clean_closure(tmp_path)
    (tmp_path / files[0]).write_text("x = 999  # mexido depois da prova\n", encoding="utf-8")

    report = audit_closure(tmp_path)

    assert "evidence_stale" in _kinds(report)


def test_audit_blocks_on_tracked_residue_outside_the_contract_files(tmp_path: Path) -> None:
    _clean_closure(tmp_path)
    (tmp_path / "outro.py").write_text("y = 3  # de outro contexto\n", encoding="utf-8")

    report = audit_closure(tmp_path)

    assert "tree_residue" in _kinds(report)
    problem = next(b["problem"] for b in report["blockers"] if b["kind"] == "tree_residue")
    assert "outro.py" in problem


def test_audit_ignores_dirty_files_declared_by_the_contract(tmp_path: Path) -> None:
    """Os `files[]` do contrato sujos são o trabalho da própria demanda, ainda
    não commitado — é o estado NORMAL no momento em que o `finish` roda, logo
    não pode ser bloqueador. Só a sujeira fora deles é resíduo."""
    files = _clean_closure(tmp_path)
    (tmp_path / files[0]).write_text("x = 1\n# comentário\n", encoding="utf-8")
    _write_evidence(tmp_path, files=files)  # re-carimba a prova para o novo conteúdo

    report = audit_closure(tmp_path)

    assert "tree_residue" not in _kinds(report)


def test_audit_ignores_the_harness_own_managed_artifacts(tmp_path: Path) -> None:
    """Mesma regra do `ensure_contract_branch` (importada, não reimplementada):
    o `feature_list.json` que o próprio harness reescreve não é resíduo."""
    _clean_closure(tmp_path)
    _git(tmp_path, "add", ".harness")
    _git(tmp_path, "commit", "-m", "versiona .harness")
    (tmp_path / ".harness" / "feature_list.json").write_text(
        json.dumps({"contract": "demo", "features": []}) + "\n", encoding="utf-8"
    )

    report = audit_closure(tmp_path)

    assert "tree_residue" not in _kinds(report)


def test_audit_writes_nothing_to_the_repository(tmp_path: Path) -> None:
    """Garantia comportamental, não declarativa: a auditoria roda sobre um
    fecho REPROVADO (feature sem passar) e nada em disco muda — nem o
    `progress.md`, nem o `scratch/`, nem a lista de arquivos."""
    _make_repo(tmp_path)
    _write_contract(tmp_path, passes=False)
    progress = tmp_path / ".harness" / "progress.md"
    progress.write_text("# original\n", encoding="utf-8")
    scratch = tmp_path / ".harness" / "scratch"
    scratch.mkdir()
    (scratch / "rascunho.txt").write_text("nao apague\n", encoding="utf-8")
    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))

    audit_closure(tmp_path)

    assert progress.read_text(encoding="utf-8") == "# original\n"
    assert (scratch / "rascunho.txt").read_text(encoding="utf-8") == "nao apague\n"
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*")) == before


def test_cli_finish_reports_the_audit_and_exits_1_with_blockers(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    _write_contract(tmp_path, passes=False)

    proc = subprocess.run(
        ["python", "-m", "harness.cli", "finish", "--dir", str(tmp_path)],
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 1, proc.stderr
    report = json.loads(proc.stdout)
    assert "feature_not_passed" in {b["kind"] for b in report["blockers"]}


# ---------------------------------------------------------------------------
# REGRA (contrato `verificador-cego-do-gate`, T-04): a demanda não fecha sem um
# veredito independente e fresco. Sem este dente, o veredito seria registro que
# ninguém lê — o sinal de over-engineering que o §11 do design lista.
#
# Cada estado manda o humano fazer uma coisa diferente, então cada um tem
# `kind` próprio: confundir "não julgou" com "julgou e reprovou" manda consertar
# o que ninguém olhou.
# ---------------------------------------------------------------------------

def test_audit_blocks_a_closure_that_no_independent_eye_ever_looked_at(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    files = _write_contract(tmp_path)
    _write_evidence(tmp_path, files=files)

    report = audit_closure(tmp_path)

    assert "blind_review_missing" in _kinds(report)


def test_audit_blocks_when_the_code_changed_after_the_verdict(tmp_path: Path) -> None:
    """Mesma mecânica da evidência de camada 2, e pelo mesmo motivo: um
    "aprovado" de vinte commits atrás não fala do código de hoje."""
    _clean_closure(tmp_path)
    (tmp_path / "src" / "modulo.py").write_text("x = 2  # depois do veredito\n", encoding="utf-8")

    report = audit_closure(tmp_path)

    assert "blind_review_stale" in _kinds(report)


def test_audit_blocks_when_the_independent_eye_rejected_the_delivery(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    files = _write_contract(tmp_path)
    _write_evidence(tmp_path, files=files)
    record_verdict(tmp_path, passed=False, evidence="T-01 nao cobre o caso vazio")

    report = audit_closure(tmp_path)

    assert "blind_review_failed" in _kinds(report)


def test_the_rejection_reason_reaches_the_human_in_the_blocker(tmp_path: Path) -> None:
    """§9.1: veredito sem o quê e onde gera re-tentativa cega. Enterrar a
    evidência num arquivo que o fecho não mostra tem o mesmo efeito."""
    _make_repo(tmp_path)
    files = _write_contract(tmp_path)
    _write_evidence(tmp_path, files=files)
    record_verdict(tmp_path, passed=False, evidence="faltou tratar lista vazia em src/modulo.py:1")

    report = audit_closure(tmp_path)

    problems = " ".join(b["problem"] for b in report["blockers"])
    assert "src/modulo.py:1" in problems


def test_an_approved_and_fresh_verdict_does_not_block(tmp_path: Path) -> None:
    _clean_closure(tmp_path)

    assert _kinds(audit_closure(tmp_path)) == set()


# ---------------------------------------------------------------------------
# T-02 — varredura dos descartáveis
# ---------------------------------------------------------------------------

_PROGRESS_HERDADO = """# Claude Progress

Contrato: `demo`

## Features

| id | desc | status |
| --- | --- | --- |
| T-01 | faz a coisa | done |

## Última atualização

<!-- harness:auto -->
- 2026-07-01T10:00:00+00:00 — T-09 verificado — .harness/evidence/outro/T-09.json
<!-- /harness:auto -->

Contrato `contrato-anterior` CONCLUÍDO. NADA COMMITADO — aguardando aprovação
humana explícita antes do commit.
"""


def test_sweep_rewrites_progress_declaring_the_contract_closed(tmp_path: Path) -> None:
    """O estado real que motivou o contrato: depois de duas demandas, o
    `progress.md` deste repo ainda afirmava que existia trabalho não commitado
    esperando aprovação — texto herdado de um contrato de duas versões atrás.
    O arquivo é resumo de estado, não diário: o que sobrevive à demanda é a
    evidência em `.harness/evidence/`."""
    _clean_closure(tmp_path)
    progress = tmp_path / ".harness" / "progress.md"
    progress.write_text(_PROGRESS_HERDADO, encoding="utf-8")

    sweep_disposables(tmp_path)

    text = progress.read_text(encoding="utf-8")
    assert "ENCERRADA" in text
    # Header canônico, não decorado — é o que deixa o próximo contrato
    # regenerar o arquivo em vez de herdar este resumo.
    assert "Contrato: `demo`" in text
    assert "| T-01 | faz a coisa | done |" in text
    assert "contrato-anterior" not in text
    assert "NADA COMMITADO" not in text
    assert "T-09" not in text


def test_sweep_empties_the_scratch_but_keeps_its_gitignore(tmp_path: Path) -> None:
    _clean_closure(tmp_path)
    scratch = tmp_path / ".harness" / "scratch"
    scratch.mkdir()
    (scratch / ".gitignore").write_text("*\n", encoding="utf-8")
    (scratch / "commit-msg.txt").write_text("rascunho antigo\n", encoding="utf-8")
    (scratch / "evidencia").mkdir()
    (scratch / "evidencia" / "tela.png").write_bytes(b"\x89PNG")

    result = sweep_disposables(tmp_path)

    assert (scratch / ".gitignore").is_file()
    assert not (scratch / "commit-msg.txt").exists()
    assert not (scratch / "evidencia").exists()
    assert sorted(result["scratch_removed"]) == ["commit-msg.txt", "evidencia"]


def test_sweep_refuses_a_closure_with_blockers_and_changes_nothing(tmp_path: Path) -> None:
    """A auditoria é o gate: reprovada, nada é varrido. Limpar por cima de um
    fecho quebrado apagaria justamente o rastro necessário para consertá-lo."""
    _make_repo(tmp_path)
    _write_contract(tmp_path, passes=False)
    progress = tmp_path / ".harness" / "progress.md"
    progress.write_text("# original\n", encoding="utf-8")
    scratch = tmp_path / ".harness" / "scratch"
    scratch.mkdir()
    (scratch / "rascunho.txt").write_text("nao apague\n", encoding="utf-8")

    with pytest.raises(FinishError, match="feature_not_passed"):
        sweep_disposables(tmp_path)

    assert progress.read_text(encoding="utf-8") == "# original\n"
    assert (scratch / "rascunho.txt").is_file()


def test_sweep_never_touches_the_history_of_the_demand(tmp_path: Path) -> None:
    """`work/`, `evidence/` e o `feature_list.json` são o registro do que foi
    feito — varrer histórico deixaria o repo limpo e a demanda inauditável."""
    files = _clean_closure(tmp_path)
    work = tmp_path / ".harness" / "work" / "demo"
    work.mkdir(parents=True)
    (work / "spec.md").write_text("# spec\n", encoding="utf-8")
    evidence = tmp_path / ".harness" / "evidence" / "demo" / "T-01.json"
    evidence_before = evidence.read_text(encoding="utf-8")
    feature_list = tmp_path / ".harness" / "feature_list.json"
    feature_list_before = feature_list.read_text(encoding="utf-8")

    sweep_disposables(tmp_path)

    assert (work / "spec.md").is_file()
    assert evidence.read_text(encoding="utf-8") == evidence_before
    assert feature_list.read_text(encoding="utf-8") == feature_list_before
    assert (tmp_path / files[0]).is_file()


def test_sweep_stub_deixa_o_proximo_contrato_regenerar_o_progresso(tmp_path: Path) -> None:
    """Defeito entregue na v0.25.0 pelo próprio `finish`, achado ao compilar o
    contrato seguinte. `install_templates` só restaura o `progress.md` quando
    consegue ler o slug antigo pelo header canônico ``Contrato: `slug` `` — com
    dois-pontos e terminando em crase. O stub de encerramento abria com
    ``Contrato `slug` ENCERRADO``, que não casa: o slug antigo vinha `None`, a
    regeneração era pulada e o arquivo ficava preservado.

    O efeito era a sessão seguinte herdar o resumo da demanda ANTERIOR — o hook
    `SessionStart` chegou a injetar "nenhuma feature pendente" numa sessão com
    seis tarefas a fazer. É exatamente o modo de falha que o `finish` existe
    para matar."""
    _clean_closure(tmp_path)
    sweep_disposables(tmp_path)
    progress = tmp_path / ".harness" / "progress.md"
    assert "demo" in progress.read_text(encoding="utf-8")

    install_templates(
        tmp_path,
        {"contract": "contrato-novo", "features": [
            {"id": "T-01", "desc": "primeira tarefa do contrato novo", "passes": False},
        ]},
        {},
    )

    text = progress.read_text(encoding="utf-8")
    assert "contrato-novo" in text
    assert "primeira tarefa do contrato novo" in text
    assert "ENCERRADO" not in text


def test_cli_finish_sweeps_and_exits_0_on_a_clean_closure(tmp_path: Path) -> None:
    _clean_closure(tmp_path)
    progress = tmp_path / ".harness" / "progress.md"
    progress.write_text(_PROGRESS_HERDADO, encoding="utf-8")

    proc = subprocess.run(
        ["python", "-m", "harness.cli", "finish", "--dir", str(tmp_path)],
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["blockers"] == []
    assert report["swept"]["progress"].endswith("progress.md")
    assert "ENCERRADA" in progress.read_text(encoding="utf-8")
