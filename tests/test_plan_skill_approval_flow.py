"""A aprovação do contrato é o ÚNICO pedido feito ao humano antes do PR.

O ciclo tinha três paradas — aprovar o contrato, pedir a implementação,
aprovar o commit. Duas eram redundantes: quem aprovou o contrato já
autorizou o trabalho, e quem verificou tarefa a tarefa já provou o commit.

Estes testes travam a INSTRUÇÃO (`skills/plan/SKILL.md`), não código — mesmo
padrão de `test_finish_lifecycle_docs.py`. A skill é um prompt: o que ela diz
É o comportamento, e uma frase que envelhece em silêncio aqui volta a
introduzir os pedidos que este contrato removeu.

As duas metades importam igualmente. Sem a primeira, o agente continua
esperando um "pode implementar". Sem a segunda, um teste verde acompanharia
uma skill que removeu o gate de aprovação junto — que é o oposto do
pretendido."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL = REPO_ROOT / "skills/plan/SKILL.md"


def _text() -> str:
    return SKILL.read_text(encoding="utf-8")


# ---------------- metade 1: a aprovação autoriza o ciclo ----------------

def test_the_skill_says_approval_authorizes_the_implementation() -> None:
    lower = _text().lower()

    assert "## passo 5" in lower
    passo5 = lower[lower.index("## passo 5"):lower.index("## passo 6")]

    assert "autoriza" in passo5, (
        "o Passo 5 precisa dizer, por escrito, que a aprovação autoriza a "
        "implementação — sem isso o agente para e espera um segundo pedido"
    )
    assert "não pare" in passo5 or "nao pare" in passo5 or "sem parar" in passo5


def test_the_skill_names_the_approval_as_the_single_human_gate() -> None:
    lower = _text().lower()

    assert "único gate" in lower or "unico gate" in lower


# ---------------- metade 2: o que continua parando ----------------

def test_the_contract_approval_itself_is_still_a_gate() -> None:
    """A mudança remove o pedido REDUNDANTE, não o gate. Auto-preencher
    `approved_by` continua proibido."""
    text = _text()
    lower = text.lower()

    assert "approved_by" in text and "approved_at" in text
    assert "nunca" in lower
    passo5 = lower[lower.index("## passo 5"):lower.index("## passo 6")]
    assert "aprovação explícita" in passo5 or "aprovacao explicita" in passo5


def test_the_agent_is_told_it_must_not_open_the_pull_request() -> None:
    """Fronteira dura: commit e push são automáticos, abrir PR nunca é."""
    lower = _text().lower()

    assert "pr-draft" in lower
    assert "gh pr create" in lower
    assert "nunca" in lower and "pull request" in lower


def test_the_final_step_commits_and_pushes_instead_of_asking() -> None:
    lower = _text().lower()

    assert "## passo 9" in lower
    passo9_e_diante = lower[lower.index("## passo 9"):]

    assert "git push" in passo9_e_diante or "push" in passo9_e_diante
    assert "blockers" in passo9_e_diante
    assert "aprovação do commit" not in passo9_e_diante, (
        "o pedido de aprovação do commit final foi removido do ciclo — a "
        "pré-condição agora é `harness finish` com blockers vazio"
    )


def test_the_branch_boundary_survives_the_automation() -> None:
    """Push automático não afrouxa o floor: só a branch do contrato."""
    lower = _text().lower()
    passo9_e_diante = lower[lower.index("## passo 9"):]

    assert "contract/" in passo9_e_diante
    assert "main" in passo9_e_diante
