"""Testes do branching (finding C do dogfood 2026-07-22): fluxo branch-first
gerenciado pela CLI — `ensure_contract_branch` cria/muda para
`contract/<slug>` antes de o compile-session instalar o guard, e os loaders
de `governance.branch_per_contract`/`governance.protected_branches` leem o
`.harness/harness.yaml` com degradação graciosa."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from harness.boundary_guard import load_protected_branches
from harness.branching import (
    BranchingError,
    ensure_contract_branch,
    load_branch_per_contract,
)


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True,
    )
    return proc.stdout.strip()


def _init_repo(target: Path) -> None:
    _git(target, "init", "-b", "main")
    _git(target, "config", "user.email", "test@example.com")
    _git(target, "config", "user.name", "Test")
    (target / "README.md").write_text("x", encoding="utf-8")
    _git(target, "add", "README.md")
    _git(target, "commit", "-m", "init")


def _current_branch(target: Path) -> str:
    return _git(target, "rev-parse", "--abbrev-ref", "HEAD")


# ---------------------------------------------------------------------------
# ensure_contract_branch
# ---------------------------------------------------------------------------

def test_ensure_contract_branch_creates_and_switches(tmp_path: Path) -> None:
    _init_repo(tmp_path)

    result = ensure_contract_branch(tmp_path, "exemplo-feature")

    assert result == "contract/exemplo-feature"
    assert _current_branch(tmp_path) == "contract/exemplo-feature"


def test_ensure_contract_branch_is_idempotent(tmp_path: Path) -> None:
    _init_repo(tmp_path)

    ensure_contract_branch(tmp_path, "exemplo-feature")
    result = ensure_contract_branch(tmp_path, "exemplo-feature")

    assert result == "contract/exemplo-feature"
    assert _current_branch(tmp_path) == "contract/exemplo-feature"


def test_ensure_contract_branch_switches_to_existing_branch(tmp_path: Path) -> None:
    """Recompile do mesmo contrato = continuação: a branch já existe, só muda
    pra ela (switch sem -c)."""
    _init_repo(tmp_path)
    ensure_contract_branch(tmp_path, "exemplo-feature")
    _git(tmp_path, "switch", "main")

    result = ensure_contract_branch(tmp_path, "exemplo-feature")

    assert result == "contract/exemplo-feature"
    assert _current_branch(tmp_path) == "contract/exemplo-feature"


def test_ensure_contract_branch_is_noop_when_already_correct_branch_and_dirty(
    tmp_path: Path,
) -> None:
    """Regressão: já em contract/<slug> + tracked dirty não deve levantar
    BranchingError — recompilar mid-task com mudanças não commitadas é o
    caso comum (compile-contract → compile-session deixa .harness/** e
    outros arquivos tracked modificados antes do commit do contrato)."""
    _init_repo(tmp_path)
    ensure_contract_branch(tmp_path, "exemplo-feature")
    (tmp_path / "README.md").write_text("modificado", encoding="utf-8")

    result = ensure_contract_branch(tmp_path, "exemplo-feature")

    assert result == "contract/exemplo-feature"
    assert _current_branch(tmp_path) == "contract/exemplo-feature"


def test_ensure_contract_branch_aborts_on_dirty_tracked_file(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "README.md").write_text("modificado", encoding="utf-8")

    with pytest.raises(BranchingError, match="suja"):
        ensure_contract_branch(tmp_path, "exemplo-feature")
    assert _current_branch(tmp_path) == "main"


def test_ensure_contract_branch_aborts_on_staged_file(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "novo.py").write_text("x = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "novo.py")

    with pytest.raises(BranchingError, match="suja"):
        ensure_contract_branch(tmp_path, "exemplo-feature")


def test_ensure_contract_branch_ignores_untracked_files(tmp_path: Path) -> None:
    """Untracked NÃO conta como sujeira: o fluxo real compile-contract →
    compile-session deixa .harness/** untracked, e é na branch de contrato
    que esses artefatos devem ser commitados (git switch preserva untracked)."""
    _init_repo(tmp_path)
    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    (harness_dir / "feature_list.json").write_text("{}", encoding="utf-8")

    result = ensure_contract_branch(tmp_path, "exemplo-feature")

    assert result == "contract/exemplo-feature"
    assert (harness_dir / "feature_list.json").is_file()


def _commit_harness_managed_artifacts(target: Path) -> None:
    """Deixa os artefatos gerenciados pelo harness TRACKED, como num repo que
    versiona `.harness/` — é o estado em que o deadlock aparece."""
    harness_dir = target / ".harness"
    harness_dir.mkdir(exist_ok=True)
    (harness_dir / "feature_list.json").write_text("{}", encoding="utf-8")
    (harness_dir / "repo-profile.json").write_text("{}", encoding="utf-8")
    _git(target, "add", ".harness")
    _git(target, "commit", "-m", "versiona .harness")


def test_ensure_contract_branch_ignores_dirty_harness_managed_artifacts(
    tmp_path: Path,
) -> None:
    """Deadlock achado ao vivo compilando o contrato `harness-finish`. Num repo
    que versiona `.harness/`, do SEGUNDO contrato em diante o agente ficava sem
    saída: `compile-contract` reescreve o `feature_list.json` tracked -> tree
    suja -> `compile-session` recusa e manda commitar na branch atual -> a
    branch atual é protegida e o guard nega o commit, sugerindo `git checkout
    -b` -> que o guard também nega. O arquivo que o PRÓPRIO harness acabou de
    gerar não é "trabalho de outro contexto"; ele viaja para a branch nova de
    qualquer forma, porque `git switch -c` preserva a working tree."""
    _init_repo(tmp_path)
    _commit_harness_managed_artifacts(tmp_path)
    harness_dir = tmp_path / ".harness"
    harness_dir.joinpath("feature_list.json").write_text(
        '{"contract": "exemplo-feature"}', encoding="utf-8"
    )
    harness_dir.joinpath("repo-profile.json").write_text(
        '{"languages": ["python"]}', encoding="utf-8"
    )

    result = ensure_contract_branch(tmp_path, "exemplo-feature")

    assert result == "contract/exemplo-feature"
    assert _current_branch(tmp_path) == "contract/exemplo-feature"
    # O switch levou o conteúdo junto — nada foi perdido nem revertido.
    assert "exemplo-feature" in harness_dir.joinpath("feature_list.json").read_text(
        encoding="utf-8"
    )


def test_ensure_contract_branch_ignores_managed_progress_and_evidence(
    tmp_path: Path,
) -> None:
    """O conjunto gerenciado não é só o que `compile-contract` grava: o
    `progress.md` e a evidência saem de `harness verify` a cada tarefa, e num
    repo que versiona `.harness/` eles ficam tracked-sujos o tempo todo. Achado
    rodando o próprio `harness finish` sobre este contrato — ele acusou o
    `progress.md` como "trabalho de outro contexto", que é exatamente o que ele
    não é."""
    _init_repo(tmp_path)
    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir(exist_ok=True)
    (harness_dir / "progress.md").write_text("# Claude Progress\n", encoding="utf-8")
    evidence_dir = harness_dir / "evidence" / "exemplo-feature"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "T-01.json").write_text("{}", encoding="utf-8")
    _git(tmp_path, "add", ".harness")
    _git(tmp_path, "commit", "-m", "versiona .harness")
    (harness_dir / "progress.md").write_text("# Claude Progress\n\nT-01 done\n", encoding="utf-8")
    (evidence_dir / "T-01.json").write_text('{"exit_code": 0}', encoding="utf-8")

    result = ensure_contract_branch(tmp_path, "exemplo-feature")

    assert result == "contract/exemplo-feature"


def test_the_two_spine_records_are_managed_like_the_rest(tmp_path: Path) -> None:
    """Achado rodando o `harness finish` do contrato `verificador-cego-do-gate`:
    ele acusou `.harness/decisions.md` e `.harness/lessons.md` como "trabalho de
    outro contexto". São o oposto disso — o `boundary_guard` PROÍBE editá-los à
    mão, então a única coisa que os escreve é `harness decide`/`harness lesson`.

    Não era teórico: enquanto estavam fora do conjunto gerenciado, registrar uma
    decisão durante a demanda travava o fecho dela, e o único jeito de fechar
    seria não registrar — que é o contrário do que os dois verbos existem para
    fazer."""
    _init_repo(tmp_path)
    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir(exist_ok=True)
    (harness_dir / "decisions.md").write_text("# Decisões\n", encoding="utf-8")
    (harness_dir / "lessons.md").write_text("# Lições\n", encoding="utf-8")
    _git(tmp_path, "add", ".harness")
    _git(tmp_path, "commit", "-m", "versiona .harness")
    (harness_dir / "decisions.md").write_text("# Decisões\n\n## D-001\n", encoding="utf-8")
    (harness_dir / "lessons.md").write_text("# Lições\n\n- [ ] x\n", encoding="utf-8")

    assert ensure_contract_branch(tmp_path, "exemplo-feature") == "contract/exemplo-feature"


def test_the_blind_verdict_is_managed_like_the_evidence(tmp_path: Path) -> None:
    """Mesmo deadlock dos dois acima, uma pasta ao lado. Enquanto o veredito de
    uma demanda for arquivo novo ele é untracked e o `-uno` do `finish` o ignora
    — o problema aparece na demanda em que um veredito já foi commitado e outro
    é registrado depois: o arquivo vira tracked-sujo, cai em `tree_residue`, e
    não há escape, porque `harness task add-file` recusa caminho de plano de
    controle. É prova de camada 3, exatamente como `.harness/evidence/` é prova
    de camada 2."""
    _init_repo(tmp_path)
    review_dir = tmp_path / ".harness" / "blind-review"
    review_dir.mkdir(parents=True)
    (review_dir / "exemplo-feature.json").write_text("{}", encoding="utf-8")
    _git(tmp_path, "add", ".harness")
    _git(tmp_path, "commit", "-m", "versiona .harness")
    (review_dir / "exemplo-feature.json").write_text('{"verdicts": []}', encoding="utf-8")

    assert ensure_contract_branch(tmp_path, "exemplo-feature") == "contract/exemplo-feature"


def test_the_attempt_trail_is_managed_like_the_evidence(tmp_path: Path) -> None:
    """Terceira ocorrência do MESMO deadlock, achada fechando o contrato
    `placar-de-andamento`: `.harness/attempts/` ficou de fora dos prefixos
    gerenciados enquanto `evidence/` e `blind-review/` entraram.

    O rastro de tentativas é escrito exclusivamente por `harness verify` — o
    `boundary_guard` proíbe editá-lo à mão, e `harness task add-file` recusa
    caminho de plano de controle. Enquanto ele contasse como "trabalho de outro
    contexto", toda demanda longa travava no fecho: basta um `verify` depois do
    primeiro commit para o arquivo virar tracked-sujo, e não existe escape
    nenhum — nem declarar, nem deixar de registrar (o registro é o que o
    disjuntor lê).
    """
    _init_repo(tmp_path)
    attempts_dir = tmp_path / ".harness" / "attempts" / "exemplo-feature"
    attempts_dir.mkdir(parents=True)
    (attempts_dir / "T-01.jsonl").write_text('{"result": "fail"}\n', encoding="utf-8")
    _git(tmp_path, "add", ".harness")
    _git(tmp_path, "commit", "-m", "versiona .harness")
    (attempts_dir / "T-01.jsonl").write_text(
        '{"result": "fail"}\n{"result": "pass"}\n', encoding="utf-8"
    )

    assert ensure_contract_branch(tmp_path, "exemplo-feature") == "contract/exemplo-feature"


def test_finish_does_not_call_the_attempt_trail_residue(tmp_path: Path) -> None:
    """A outra ponta do mesmo julgamento: `harness finish` consome
    `unmanaged_dirty_paths` para decidir `tree_residue`. Sem esta asserção, a
    isenção poderia valer só na criação da branch e continuar travando o fecho —
    que é onde o deadlock aparece de verdade."""
    from harness.branching import unmanaged_dirty_paths

    porcelain = (
        " M .harness/attempts/demo/T-04.jsonl\n"
        " M .harness/evidence/demo/T-04.json\n"
        " M src/app.py\n"
    )

    assert unmanaged_dirty_paths(porcelain) == ["src/app.py"]


def test_the_exemption_is_per_tree_never_the_whole_control_plane() -> None:
    """O caso NEGATIVO que fixa o limite da isenção.

    Os testes acima dizem quais árvores do `.harness/` são artefato do harness;
    nenhum dizia que o RESTO continua sendo resíduo. Sem esta asserção, trocar
    a tupla por `(".harness/",)` isentaria o plano de controle inteiro — o
    `feature_list.json` alterado à mão, um hook trocado, o `harness.yaml`
    reescrito — e a suíte seguiria verde. Apontado pelo verificador cego no
    contrato `placar-de-andamento`, como cobertura ausente, não defeito
    presente.
    """
    from harness.branching import unmanaged_dirty_paths

    porcelain = (
        " M .harness/hooks/boundary_guard.py\n"
        " M .harness/harness.yaml\n"
        " M .harness/work/demo/spec.md\n"
        " M .harness/attempts/demo/T-01.jsonl\n"
    )

    assert unmanaged_dirty_paths(porcelain) == [
        ".harness/hooks/boundary_guard.py",
        ".harness/harness.yaml",
        ".harness/work/demo/spec.md",
    ]


def test_ensure_contract_branch_aborts_when_unmanaged_file_is_dirty_beside_managed(
    tmp_path: Path,
) -> None:
    """A isenção é escopada: sujeira de qualquer arquivo fora do conjunto
    gerenciado continua abortando, e a mensagem nomeia só o que de fato é
    trabalho de outro contexto — citar o `feature_list.json` que o próprio
    comando anterior gerou mandaria o humano investigar um falso positivo."""
    _init_repo(tmp_path)
    _commit_harness_managed_artifacts(tmp_path)
    (tmp_path / ".harness" / "feature_list.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("modificado", encoding="utf-8")

    with pytest.raises(BranchingError) as exc_info:
        ensure_contract_branch(tmp_path, "exemplo-feature")

    message = str(exc_info.value)
    assert "README.md" in message
    assert "feature_list.json" not in message
    assert _current_branch(tmp_path) == "main"


def test_ensure_contract_branch_rejects_non_git_dir(tmp_path: Path) -> None:
    with pytest.raises(BranchingError, match="git"):
        ensure_contract_branch(tmp_path, "exemplo-feature")


def test_ensure_contract_branch_rejects_repo_without_initial_commit(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-b", "main")

    with pytest.raises(BranchingError, match="commit inicial"):
        ensure_contract_branch(tmp_path, "exemplo-feature")


def test_ensure_contract_branch_rejects_empty_slug(tmp_path: Path) -> None:
    _init_repo(tmp_path)

    with pytest.raises(BranchingError, match="slug"):
        ensure_contract_branch(tmp_path, "")


# ---------------------------------------------------------------------------
# loaders (.harness/harness.yaml, degradação graciosa)
# ---------------------------------------------------------------------------

def test_load_branch_per_contract_defaults_true_without_yaml(tmp_path: Path) -> None:
    assert load_branch_per_contract(tmp_path) is True


def test_load_branch_per_contract_reads_override(tmp_path: Path) -> None:
    yaml_path = tmp_path / ".harness" / "harness.yaml"
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    yaml_path.write_text(
        "governance:\n  branch_per_contract: false\n", encoding="utf-8"
    )

    assert load_branch_per_contract(tmp_path) is False


def test_load_branch_per_contract_defaults_true_on_invalid_yaml(tmp_path: Path) -> None:
    yaml_path = tmp_path / ".harness" / "harness.yaml"
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    yaml_path.write_text(":: nao e yaml valido ::[", encoding="utf-8")

    assert load_branch_per_contract(tmp_path) is True


def test_load_protected_branches_defaults_without_yaml(tmp_path: Path) -> None:
    assert load_protected_branches(tmp_path) == ["main", "homolog", "develop"]


def test_dirty_tree_message_names_the_files_and_the_three_ways_out(
    tmp_path: Path,
) -> None:
    """Achado F6 do dogfood venv-Windows. A mensagem antiga dizia
    "commit ou stash antes de compilar a sessão" e parava aí. No alvo real os
    arquivos sujos ERAM os `files[]` do próprio contrato — o trabalho já estava
    em andamento quando o harness foi instalado, que é o caso de quem adota a
    ferramenta num projeto vivo. Mandar "stashear" ali é conselho ruim: o stash
    esconde exatamente o que o contrato existe para governar."""
    _init_repo(tmp_path)
    (tmp_path / "README.md").write_text("modificado", encoding="utf-8")

    with pytest.raises(BranchingError) as exc_info:
        ensure_contract_branch(tmp_path, "exemplo-feature")

    message = str(exc_info.value)
    assert "README.md" in message                      # nomeia o que está sujo
    assert "commite AGORA" in message                  # saída 1: pertence ao contrato
    assert "git stash" in message                      # saída 2: é de outro contexto
    assert "branch_per_contract" in message            # saída 3: desligar a regra
    assert "contract/exemplo-feature" in message       # o switch leva o commit junto
    assert "NÃO stashe" in message


def test_dirty_tree_message_truncates_a_long_file_list(tmp_path: Path) -> None:
    """Listar tudo num repo com dezenas de modificações vira parede de texto e
    some com a saída — o resumo mantém a mensagem legível."""
    _init_repo(tmp_path)
    for i in range(9):
        path = tmp_path / f"arquivo{i}.txt"
        path.write_text("original", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "base")
    for i in range(9):
        (tmp_path / f"arquivo{i}.txt").write_text("modificado", encoding="utf-8")

    with pytest.raises(BranchingError) as exc_info:
        ensure_contract_branch(tmp_path, "exemplo-feature")

    assert "(+4)" in str(exc_info.value)


def test_load_protected_branches_reads_override(tmp_path: Path) -> None:
    yaml_path = tmp_path / ".harness" / "harness.yaml"
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    yaml_path.write_text(
        "governance:\n  protected_branches:\n    - trunk\n", encoding="utf-8"
    )

    assert load_protected_branches(tmp_path) == ["trunk"]
