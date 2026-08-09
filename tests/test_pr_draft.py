"""Testes de `harness pr-draft` — o PR entregue pronto ao humano.

Abrir o PR continua sendo ação humana (não-objetivo explícito do contrato
`aviso-plugin-e-ciclo-automatico`). O que o harness faz é eliminar o trabalho
braçal: montar o corpo a partir do que o contrato já tem estruturado e
imprimir o comando exato.

A divisão é deliberada e está testada aqui: o comando gera o **fato**
derivável do contrato (tarefas, provas, evidência) e deixa marcado o
**racional** — que não é derivável e é a parte que vale a leitura do PR."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from harness.pr_draft import PrDraftError, build_pr_draft

FEATURE_LIST = {
    "contract": "exemplo-feature",
    "compiled_at": "2026-08-09T00:00:00+00:00",
    "features": [
        {
            "id": "T-01",
            "desc": "Usuario consegue exportar o relatorio em CSV",
            "files": ["src/app.py"],
            "verify_cmd": "pytest tests/test_app.py -q",
            "depends": [],
            "passes": True,
        },
        {
            "id": "T-02",
            "desc": "Exportacao vazia devolve arquivo com cabecalho",
            "files": ["src/app.py"],
            "verify_cmd": "pytest tests/test_empty.py -q",
            "depends": ["T-01"],
            "passes": True,
        },
    ],
}

SPEC_MD = """---
slug: exemplo-feature
approved_by: alice
approved_at: 2026-08-09T00:00:00Z
---

# Spec: exportacao de relatorio em CSV
"""


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _bootstrap(tmp_path: Path, *, with_spec: bool = True, branch: str | None = None) -> Path:
    _write(tmp_path / ".harness" / "feature_list.json", json.dumps(FEATURE_LIST))
    _write(tmp_path / "src" / "app.py", "def run():\n    return 1\n")
    if with_spec:
        _write(tmp_path / ".harness" / "work" / "exemplo-feature" / "spec.md", SPEC_MD)
    if branch:
        def _git(*args: str) -> None:
            subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, text=True, check=True)

        _git("init", "-b", branch)
        _git("config", "user.email", "t@e.com")
        _git("config", "user.name", "T")
        _git("commit", "--allow-empty", "-m", "init")
    return tmp_path


# --------------------------------------------------------------------------
# REGRA 1 — o corpo carrega o fato derivável do contrato
# --------------------------------------------------------------------------

def test_every_task_shows_up_with_its_description_and_its_proof(tmp_path: Path) -> None:
    """Quem revisa o PR precisa ver o que foi entregue e como cada parte foi
    provada, sem abrir o contrato."""
    _bootstrap(tmp_path)

    draft = build_pr_draft(tmp_path)
    body = draft.body_path.read_text(encoding="utf-8")

    for feature in FEATURE_LIST["features"]:
        assert feature["id"] in body
        assert feature["desc"] in body
        assert feature["verify_cmd"] in body


def test_the_title_comes_from_the_spec_heading_not_from_the_slug(tmp_path: Path) -> None:
    """O slug é kebab-case para virar nome de branch; título de PR feito dele
    fica ilegível. O `spec.md` já tem a frase escrita para humano."""
    _bootstrap(tmp_path)

    draft = build_pr_draft(tmp_path)

    assert draft.title == "exportacao de relatorio em CSV"


def test_without_a_spec_the_title_falls_back_to_the_slug(tmp_path: Path) -> None:
    _bootstrap(tmp_path, with_spec=False)

    draft = build_pr_draft(tmp_path)

    assert "exemplo-feature" in draft.title


# --------------------------------------------------------------------------
# REGRA 2 — o racional fica marcado para o agente escrever
# --------------------------------------------------------------------------

def test_the_body_leaves_the_reasoning_explicitly_unwritten(tmp_path: Path) -> None:
    """`pr-draft` não inventa o porquê: ele não tem como saber. Deixar a seção
    marcada é o que impede um PR sair só com a tabela de tarefas."""
    _bootstrap(tmp_path)

    body = build_pr_draft(tmp_path).body_path.read_text(encoding="utf-8")

    assert "PREENCHER" in body
    assert body.count("PREENCHER") >= 2


# --------------------------------------------------------------------------
# REGRA 3 — o comando sai pronto para colar
# --------------------------------------------------------------------------

def test_the_command_is_ready_to_paste_with_the_body_in_a_file(tmp_path: Path) -> None:
    """Corpo em `--body-file`, nunca em `--body` inline: acentuação em linha de
    comando no PowerShell 5.1 corrompe multi-byte, defeito já vivido neste
    repositório."""
    _bootstrap(tmp_path, branch="contract/exemplo-feature")

    draft = build_pr_draft(tmp_path)

    assert draft.command.startswith("gh pr create ")
    assert "--body-file" in draft.command
    assert "--body " not in draft.command
    assert str(draft.body_path) in draft.command
    assert "--head contract/exemplo-feature" in draft.command
    assert "--base main" in draft.command


def test_the_command_omits_the_head_when_the_branch_is_unknown(tmp_path: Path) -> None:
    """Fora de repositório git o `gh` infere a branch corrente; inventar um
    `--head` errado seria pior que omitir."""
    _bootstrap(tmp_path)

    draft = build_pr_draft(tmp_path)

    assert "--head" not in draft.command


def test_the_body_lands_in_scratch_which_git_ignores(tmp_path: Path) -> None:
    """`.harness/scratch/` tem escrita liberada pelo boundary_guard e é
    auto-ignorado — o rascunho não pode sujar o `git status` do PR que ele
    mesmo descreve."""
    _bootstrap(tmp_path)

    draft = build_pr_draft(tmp_path)

    assert draft.body_path.is_file()
    assert draft.body_path.parent == tmp_path / ".harness" / "scratch"


# --------------------------------------------------------------------------
# REGRA 4 — recusa em vez de entregar um rascunho vazio
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class RefusalCase:
    content: str | None
    why: str


REFUSAL_CASES = [
    RefusalCase(None, "sem contrato compilado"),
    RefusalCase("{ nao e json", "feature_list ilegivel"),
]


@pytest.mark.parametrize("case", REFUSAL_CASES, ids=lambda c: c.why)
def test_it_refuses_instead_of_producing_an_empty_draft(
    tmp_path: Path, case: RefusalCase
) -> None:
    if case.content is not None:
        _write(tmp_path / ".harness" / "feature_list.json", case.content)

    with pytest.raises(PrDraftError) as exc_info:
        build_pr_draft(tmp_path)

    assert "compile-contract" in str(exc_info.value)


# --------------------------------------------------------------------------
# REGRA 5 — a CLI expõe tudo em JSON
# --------------------------------------------------------------------------

def test_the_cli_prints_the_command_and_the_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from harness.cli import main

    _bootstrap(tmp_path, branch="contract/exemplo-feature")
    monkeypatch.setattr(sys, "argv", ["harness", "pr-draft", "--dir", str(tmp_path)])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["body"].endswith("pr-body.md")
    assert data["command"].startswith("gh pr create ")
    assert data["title"] == "exportacao de relatorio em CSV"
    assert data["branch"] == "contract/exemplo-feature"


def test_the_cli_fails_loudly_without_a_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from harness.cli import main

    monkeypatch.setattr(sys, "argv", ["harness", "pr-draft", "--dir", str(tmp_path)])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    assert capsys.readouterr().err.startswith("erro: ")
