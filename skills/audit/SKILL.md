---
name: audit
description: Avalia a estrutura de harness de um projeto — score 0-100 e findings (yaml inválido, hooks ausentes, drift entre harness.yaml e settings.json, política arriscada) com oferta de correção.
when_to_use: Quando o usuário quer avaliar/verificar/auditar a governança de harness do projeto, suspeita que settings.json divergiu do harness.yaml, ou depois de um /harness-creator:init.
argument-hint: "[diretório-alvo, default: raiz do projeto atual]"
disable-model-invocation: false
---

# Auditar estrutura de harness

Avalie a governança de harness do projeto-alvo (argumento `$0` ou raiz atual).

## Passo 1 — Rodar a auditoria

```
python -m harness.cli audit --dir <alvo>
```

Saída: JSON com `score` (0-100) e `findings` (severity/code/message/fix).
Exit code 1 = estrutura comprometida (algum finding crítico). Se der
`ModuleNotFoundError`, falta `PYTHONPATH`: rode
`$env:PYTHONPATH = "${CLAUDE_PLUGIN_ROOT}\src"` e repita — só faça essa
checagem quando o comando falhar, não antes (evita um `Bash` extra pedindo
aprovação sem necessidade).

## Passo 2 — Apresentar

- Score em destaque com leitura: ≥85 saudável · 60-84 precisa atenção ·
  <60 comprometida.
- Tabela dos findings: severidade, problema, correção — traduza `message`/`fix`
  para o contexto do projeto, não despeje JSON cru.
- Sem findings: diga que está saudável e pare. Não invente melhoria.

## Passo 3 — Oferecer correção

A maioria dos findings se resolve com `python -m harness.cli compile --dir <alvo>`
(regenera hooks/settings/AGENTS.md preservando conteúdo manual). Ofereça rodar.
Exceções:
- `invalid_harness_yaml` — mostre o erro de validação e corrija o YAML com o
  usuário antes de recompilar.
- `auto_policy` — explique o risco (auto NÃO é read-only) e pergunte se troca
  para `balanced`.
- `no_test_files` — confirme o `test_glob` ou ajude a criar a suíte.

Depois de corrigir, rode o audit de novo e mostre o score novo.
