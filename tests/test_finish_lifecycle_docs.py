"""`harness finish` deve rodar na branch do contrato, antes do commit final --
nao depois do merge. A fricao observada em ondas anteriores: rodar `finish`
so' depois do merge sempre deixa uma sobra (`progress.md` reescrito,
evidencia recarimbada) que precisa de commit direto na `main`, branch onde o
agente nunca pode commitar. Esses testes travam a instrucao (docs/skill), nao
o codigo de `finish.py`/`verify.py` (que ja nao toca git).
"""

from __future__ import annotations

from pathlib import Path

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
