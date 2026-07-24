# Evidência dogfood — `governance.extra_allowed_commands` (gate final da demanda)

**Data:** 2026-07-22
**Teste:** `tests/e2e/test_extra_allowed_commands_e2e.py::test_extra_allowed_commands_e2e_dogfood`

Prova REAL exigida pelo ROADMAP: mock em disco de um repo cujo produto é um
CLI (`python -m mar_committee` — mesmo comando do cenário real do repo
`entebate` que motivou esta demanda), contrato ATIVO com a feature
`passes:false` (propositalmente não concluído — contrato 100% verde
aposenta a superfície de comando inteira, ver achado de assimetria
`_evaluate_bash`/`_evaluate_powershell` corrigido depois desta evidência)
SEM `verify_cmd` cobrindo o CLI, e `.harness/harness.yaml` declarando
`governance.extra_allowed_commands: ["python -m mar_committee"]`.
`install_boundary_guard` (função REAL do pacote, mesmo caminho de
`harness compile-session`) instala o hook em disco; os dois blocos JSON
abaixo são a **saída literal** do script instalado, invocado via
`subprocess.run` (interpretador `C:\Python314\python.exe`).

Script instalado em `.harness/hooks/boundary_guard.py` (relativo à raiz
do mock efêmero em `tmp_path` — o path absoluto varia por rodada e não entra
na evidência versionada).

---

## Comando declarado em `extra_allowed_commands` — `python -m mar_committee config-show`

Sem esta feature, o guard negaria: nenhum `verify_cmd` do contrato cobre o
CLI do produto (só `pytest -q`), e não há sequência fixa (`git`/`harness`)
nem utilitário read-only que case.

```json
{
  "hookEventName": "PreToolUse",
  "permissionDecision": "allow",
  "permissionDecisionReason": "comando na superficie compilada do contrato (verify_cmd/lint/typecheck/build/install/git local), utilitario read-only ou cd intra-repo"
}
```

## Comando NÃO declarado — `algum-cli-nao-declarado --flag`

Continua fora da superfície (`verify_cmd`/lint/build/install/git local) —
`extra_allowed_commands` libera só o que foi explicitamente declarado, não
qualquer comando.

```json
{
  "hookEventName": "PreToolUse",
  "permissionDecision": "deny",
  "permissionDecisionReason": "segmento 'algum-cli-nao-declarado --flag' fora da superficie compilada do contrato (verify_cmd/lint/typecheck/build/install/git local) e nao aceito como utilitario read-only (cat/head/tail/wc/grep/rg/ls/echo/find sem redirecionamento de escrita) nem cd intra-repo; replaneje via /harness-creator:plan se precisar de outro comando"
}
```

---

## Interpretação

O comando declarado (`python -m mar_committee config-show`, prefixado por
`python -m mar_committee`) recebe **allow** — o cenário real que motivou a
demanda (CLI do próprio produto bloqueado durante um contrato ativo cujo
`verify_cmd` não cobre o CLI) está resolvido sem precisar de um contrato
ad-hoc cujos `verify_cmd` SEJAM os subcomandos do CLI. Um comando fora da
superfície declarada continua **deny** — `extra_allowed_commands` amplia a
superfície de forma explícita e auditável, não abre um allow genérico.
(Com contrato 100% `passes:true` o boundary_guard se aposenta da
superfície de comando inteira — cenário coberto separadamente em
`tests/test_boundary_guard.py`.)
