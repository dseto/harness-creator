"""`harness finish` deve rodar na branch do contrato, antes do commit final --
nao depois do merge. A fricao observada em ondas anteriores: rodar `finish`
so' depois do merge sempre deixa uma sobra (`progress.md` reescrito,
evidencia recarimbada) que precisa de commit direto na `main`, branch onde o
agente nunca pode commitar. Esses testes travam a instrucao (docs/skill), nao
o codigo de `finish.py`/`verify.py` (que ja nao toca git).

Testes T-07 (contrato `setup-fail-closed-sem-init`) adicionados depois: o
passo de commit do lifecycle passa a perguntar ao desenvolvedor, ANTES do
commit, se ele quer incluir a atualização de docs/CHANGELOG/versão que
`harness finish` reportou (campo informativo `docs_version` — ver
`tests/test_finish.py`). Três garantias no texto: nunca fazer sozinho, nunca
pular a pergunta, "não" é resposta legítima que segue direto pro commit.
Cobre os dois artefatos que carregam essa instrução: o texto gerado por
`harness.lifecycle` (AGENTS.md / `.harness/LIFECYCLE.md`) e o `skills/plan/
SKILL.md` (Passo 9), que documenta a mesma pergunta no fluxo entre `harness
finish` e o commit.

O nome do arquivo já contém "lifecycle" — casa com o `-k` do verify_cmd
(`docs_version or lifecycle`) mesmo sem repetir a palavra em cada função,
mas ela também aparece nos nomes abaixo por clareza.
"""

from __future__ import annotations

from pathlib import Path

from harness.lifecycle import render_lifecycle_block, render_lifecycle_detail

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_plan_skill_tem_passo_apos_o_8_rodando_finish_antes_do_commit() -> None:
    text = (REPO_ROOT / "skills/plan/SKILL.md").read_text(encoding="utf-8")
    lower = text.lower()

    assert "## passo 8" in lower, "Passo 8 (teste manual de UI) sumiu do arquivo"
    passo8_idx = lower.index("## passo 8")
    passo9_idx = lower.index("## passo 9")
    assert passo9_idx > passo8_idx, "Passo 9 precisa vir depois do Passo 8"

    passo9_e_diante = lower[passo9_idx:]
    assert "harness finish" in passo9_e_diante, (
        "Passo 9 deveria instruir rodar `harness finish`"
    )
    assert "branch do contrato" in passo9_e_diante, (
        "Passo 9 deveria deixar explicito que o finish roda NA branch do "
        "contrato (nao depois do merge, na main)"
    )
    assert "antes" in passo9_e_diante, (
        "Passo 9 deveria dizer que o finish roda ANTES do commit/push/PR"
    )


def test_guide_secao_10_documenta_ordem_recomendada() -> None:
    text = (REPO_ROOT / "docs/plugin/GUIDE.md").read_text(encoding="utf-8")
    lower = text.lower()

    assert "## 10. encerrar a demanda" in lower, "secao 10 do GUIDE sumiu"
    secao10_idx = lower.index("## 10. encerrar a demanda")
    secao11_idx = lower.index("## 11.")
    secao10 = lower[secao10_idx:secao11_idx]

    assert "antes do" in secao10 and (
        "pr" in secao10 or "merge" in secao10
    ), (
        "secao 10 deveria recomendar rodar harness finish ANTES do PR/merge, "
        "nao so descrever o que o comando faz"
    )
    assert "branch do contrato" in secao10, (
        "secao 10 deveria dizer que a ordem recomendada roda na branch do "
        "contrato"
    )


# ---------------------------------------------------------------------------
# T-07 (contrato `setup-fail-closed-sem-init`) — pergunta sobre docs/versão
# antes do commit
# ---------------------------------------------------------------------------

def _commit_step_detail() -> str:
    """Recorta o passo 16 (commit) do detalhe completo do lifecycle."""
    text = render_lifecycle_detail()
    assert "16. **Commit" in text
    return text.split("16. **Commit", 1)[1]


def test_lifecycle_detail_asks_before_committing_a_docs_version_update() -> None:
    step = _commit_step_detail()

    assert "pergunt" in step.lower()
    assert "docs_version" in step
    assert "CHANGELOG" in step


def test_lifecycle_detail_never_updates_docs_or_version_on_its_own() -> None:
    step = _commit_step_detail()

    assert "nunca" in step.lower() and "sozinho" in step.lower()


def test_lifecycle_detail_a_negative_answer_is_legitimate_and_goes_straight_to_commit() -> None:
    step = _commit_step_detail()

    # a garantia precisa nomear explicitamente que recusar é uma resposta válida,
    # não apenas mencionar a palavra "não" em outro contexto do parágrafo.
    assert "resposta legítima" in step.lower() or "resposta legitima" in step.lower()


def test_lifecycle_detail_ties_the_question_to_the_docs_version_field_from_finish() -> None:
    """A pergunta não nasce solta: ela referencia o campo `docs_version` que
    `harness finish` já reporta (T-07, parte 1)."""
    step = _commit_step_detail()

    assert "harness" in step.lower() and "finish" in step.lower()
    assert "informativo" in step.lower() or "INFORMATIVO" in step


def test_lifecycle_short_block_also_mentions_the_docs_version_question() -> None:
    """O bloco curto (progressive disclosure) do AGENTS.md também recebe a
    menção — quem só lê o resumo não pode perder a pergunta."""
    block = render_lifecycle_block()
    step_16 = block.split("16.", 1)[1]

    assert "pergunt" in step_16.lower()
    assert "docs_version" in step_16


def test_skill_plan_step_9_documents_the_docs_version_question_between_finish_and_commit() -> None:
    skill = (REPO_ROOT / "skills" / "plan" / "SKILL.md").read_text(encoding="utf-8")
    assert "## Passo 9" in skill
    step_9 = skill.split("## Passo 9", 1)[1].split("## Regras", 1)[0]

    assert "harness finish" in step_9
    assert "docs_version" in step_9
    assert "pergunt" in step_9.lower()
    assert "CHANGELOG" in step_9
    # a pergunta precisa estar posicionada ENTRE o `harness finish` e o
    # commit, não antes do finish nem depois do push.
    finish_pos = step_9.index("harness finish")
    ask_pos = step_9.lower().index("pergunt")
    commit_pos = step_9.lower().index("commite e empurre")
    assert finish_pos < ask_pos < commit_pos


def test_skill_plan_step_9_a_no_answer_still_follows_the_convention_of_version_chores_on_main() -> (
    None
):
    """Coerência com a convenção vigente: recusar a atualização não trava
    nada, o `chore` de versão/CHANGELOG segue sendo do humano na `main`."""
    skill = (REPO_ROOT / "skills" / "plan" / "SKILL.md").read_text(encoding="utf-8")
    step_9 = skill.split("## Passo 9", 1)[1].split("## Regras", 1)[0]

    assert "chore" in step_9.lower()
    assert "main" in step_9
