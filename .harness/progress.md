# Claude Progress

Contrato: `setup-fail-closed-sem-init`

_Demanda ENCERRADA por `harness finish`._

## Features

| id | desc | status |
| --- | --- | --- |
| T-01 | Compilar um contrato num repo que nunca rodou `harness init` para com erro que ensina o caminho de volta, em vez de compilar com governança pela metade | done |
| T-02 | Compilar a sessão sem `.harness/harness.yaml` deixa de ser um aviso ignorável em stderr e vira recusa explícita apontando `/harness-creator:init` | done |
| T-03 | Verificar tarefas ou supervisionar o ciclo com contrato ativo mas enforcement desligado nesta máquina (hooks ausentes ou kill-switch) para na hora, nomeando o que falta e o comando que religa | done |
| T-04 | A skill plan recusa começar num repo sem init: passo 0 checa `.harness/harness.yaml` e redireciona para `/harness-creator:init` antes de qualquer entrevista | done |
| T-05 | O cenário real do incidente vira teste de integração: repo .NET sem `harness.yaml` é recusado com a mensagem didática, e o repo governado continua saindo limpo | done |
| T-06 | A documentação para de prometer "avisa, não bloqueia" no cenário sem init, e a reversão da decisão v0.30.0 fica registrada com o racional setup-time vs runtime | done |
| T-07 | Ao encerrar a demanda, o desenvolvedor é perguntado — antes do commit — se quer incluir a atualização de docs/CHANGELOG/versão: o finish reporta o que está pendente, e a escolha é dele | done |

## Última atualização

_(vazio — demanda encerrada; o próximo `compile-session` regenera este arquivo a partir do contrato novo. A prova do que foi entregue está em `.harness/evidence/`.)_
