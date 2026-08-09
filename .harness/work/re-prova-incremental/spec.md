---
slug: re-prova-incremental
approved_by: Daniel Seto
approved_at: 2026-08-09T10:01:13Z
stop_conditions:
  - type: consecutive_verify_failures
    n: 3
  - type: same_failure_signature
    n: 2
  - "Se a re-prova de uma tarefa antiga ficar vermelha por causa do ambiente (timeout, lock de arquivo, ferramenta ausente) e não por regressão de código: parar e tratar como falha de infraestrutura — rebaixar `passes` nesse caso destrói registro válido."
  - "Se a interseção de arquivos devolver, na prática, quase todas as tarefas do contrato a cada verificação: parar e replanejar o critério de seleção — re-prova que roda a suíte inteira é a camada 3 disfarçada, exatamente o que o design proíbe dentro do loop."
---

# Spec: Re-prova incremental — a fatia nova não quebra a fatia antiga em silêncio

## Resumo executivo

Hoje, quando uma tarefa fica pronta, o harness roda só o teste daquela
tarefa. Se ela quebrou uma tarefa que já estava dada como pronta, ninguém
descobre — o registro segue dizendo "pronto" e o problema só aparece no
fim, horas e muitas mudanças depois, quando achar a causa já custa caro.

Passa a ser assim: ao fechar uma tarefa, o harness também re-executa a prova
das tarefas já concluídas que **mexem nos mesmos arquivos**. Se alguma ficar
vermelha, ela volta para a fila de trabalho automaticamente e a verificação
avisa. Não é a suíte inteira: só o que tem parentesco real com o que acabou
de mudar.

## Escopo

Incremento 3 do [design de loop engineering](docs/reference/loop-engineering-design.md),
§6 — "re-prova incremental (proteção contra regressão de código entre
fatias)". A camada 1 (sinal rápido) e a camada 2 (`verify_cmd` da fatia) já
existem; falta a parte da camada 2 que olha para trás.

Todo o dado necessário já está em `.harness/feature_list.json`: cada feature
declara `files[]`, `verify_cmd` e `passes`. A seleção é a interseção de
`files[]` — custo proporcional ao acoplamento real, não ao tamanho do
contrato.

Três decisões de desenho que o escopo carrega:

1. **A re-prova é automática, não um comando que alguém lembra de rodar.**
   `harness verify <T-ID>` passa a fazê-la sozinho depois do verde. Depender
   da memória do agente é o mesmo defeito que as stop conditions em prosa
   tinham antes do incremento 1 e que o passo "cheque o `git log`" tinha
   antes do incremento 2.
2. **Vermelho rebaixa.** A feature regredida volta a `passes: false` e ganha
   registro de tentativa — ou seja, reentra na fila do `harness supervise`,
   conta no disjuntor do `harness budget` e bloqueia o `harness finish`.
   Avisar sem rebaixar deixaria o `feature_list.json` alegando pronto aquilo
   que acabou de falhar, que é precisamente a mentira que o incremento 2
   existe para detectar.
3. **A evidência antiga não é apagada.** Ela vira prova obsoleta (o
   `files_hash` deixa de bater e o `harness reconcile` já sabe chamar isso de
   `evidence_stale`). Apagar destruiria o registro do que um dia foi provado.

## Critérios de aceitação

- A seleção devolve só tarefas já concluídas que compartilham pelo menos um
  arquivo com a tarefa recém-fechada, nunca a própria, e nunca repete o mesmo
  comando de prova duas vezes: `pytest tests/test_regression.py -q`
- Uma tarefa antiga cuja prova ficou vermelha volta a `passes: false` com
  tentativa registrada, e o relatório distingue o que foi re-provado do que
  regrediu: `pytest tests/test_regression.py -q`
- `harness verify <T-ID>` executa a re-prova sozinho depois do verde e sai
  com exit code 2 quando encontra regressão (0 quando não encontra), com
  `--no-reproof` para desligar: `pytest tests/test_cli.py -q`
- O ciclo documentado manda ler o exit code 2 como trabalho a fazer, não como
  ruído, e a documentação do projeto descreve a re-prova:
  `pytest tests/test_lifecycle.py -q`

## Não-objetivos

- **Não roda a suíte completa.** Isso é a camada 3, e o design proíbe
  explicitamente rodá-la dentro do loop de iteração.
- **Não infere acoplamento** por import, chamada de função ou histórico do
  git. A interseção declarada em `files[]` é o critério; um acoplamento não
  declarado é problema do contrato, e `harness task add-file` já existe para
  corrigi-lo.
- **Não conserta a regressão.** Rebaixa e avisa; consertar é o ciclo normal,
  com a tarefa de volta na fila.
- **Não muda `harness finish` nem `harness reconcile`.** Uma feature
  rebaixada já aparece nos dois pelas regras que eles têm hoje
  (`feature_not_passed`, `evidence_stale`).
- **Não bloqueia a sessão.** Exit code 2 é veredito, não trava — mesma
  postura de `budget` e `reconcile`.
- **Não paraleliza** a execução das re-provas.

## Unknowns

- Nenhum. O `harness analyze` deste repositório devolveu `unknowns: []`
  (`test_command: pytest`, evidência `pyproject.toml`).
