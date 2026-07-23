# Claude Progress

Contrato: `lifecycle-gate-aprovacao-commit`

## Features

| id | desc | status |
| --- | --- | --- |
| T-01 | Inserir passo 15 (gate de aprovação humana) em lifecycle.py e renumerar 16/17 | done |
| T-02 | Atualizar teste e2e do outcome 6 para 17 passos + gate de aprovação | done |
| T-03 | Atualizar documentação corrente que cita "16 passos" para "17 passos" | done |
| T-04 | Instruir skill plan (Passo 5) a sempre mostrar caminho relativo do contrato antes da aprovação | done |
| T-05 | Regressão completa (critério de aceitação top-level do spec.md) | done |

## Última atualização

Contrato `lifecycle-gate-aprovacao-commit` concluído — T-01..T-05
verificados (`harness verify <id> --mark-passed`, `exit_code: 0` cada,
evidência em `.harness/feature_list.json`), regressão total verde
(`pytest tests -q`, 610 passed). T-03 exigiu correção de `verify_cmd`
(aspas simples em `bash -c '...'` quebram sob `cmd.exe`/`shell=True` no
Windows — trocado para aspas duplas) e recompilação do contrato, que
preservou `passes:true` de T-01/T-02 (identidade inalterada) e resetou só
T-03 (verify_cmd mudou), confirmando o comportamento documentado em
`contract.py`. Nenhuma quebra pendente. Aguardando aprovação humana
explícita (passo 15 do lifecycle, novo) antes do commit.
