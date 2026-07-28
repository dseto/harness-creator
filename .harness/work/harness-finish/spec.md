---
slug: harness-finish
approved_by: Daniel Seto
approved_at: 2026-07-28T21:02:07Z
stop_conditions:
  - "3 falhas consecutivas do mesmo verify_cmd sem hipótese nova — parar e devolver ao humano"
  - "A auditoria exigir executar git ou gh (commit/push/PR) para fechar — está fora do escopo, parar e reportar"
  - "A varredura precisar apagar algo fora de .harness/progress.md e .harness/scratch/ — parar e perguntar"
---

# Spec: harness finish — encerrar a demanda e deixar o repo pronto para a próxima

## Resumo executivo
Hoje, quando uma demanda termina, o repositório fica com sobras. O resumo de
progresso ainda descreve um contrato antigo — hoje ele afirma que existe
trabalho não commitado esperando aprovação, o que é falso há duas versões. A
pasta de rascunho guarda arquivos de semanas atrás. E ninguém confere se as
provas de teste registradas ainda valem para o código que foi realmente
entregue. Este contrato cria um comando único de encerramento que audita o
fecho da demanda e limpa o que é descartável, para que a próxima demanda comece
de um estado previsível: sem pendência, sem lixo e sem o harness em estado
inconsistente.

## Escopo

`harness finish --dir <alvo>` faz duas coisas, nesta ordem, e nada além disso.

**1. Audita o fecho (só leitura).** Reprova o encerramento e lista como
bloqueador cada uma destas situações:

- kill-switch ativo — encerrar uma demanda com o `boundary_guard` em no-op
  significa que a sessão inteira rodou sem governança (é o modo de falha da
  issue #52, e o `finish` é a superfície mais barata para pegá-lo);
- `.harness/feature_list.json` ausente ou ilegível — não há contrato a fechar;
- feature do contrato sem `passes: true`;
- feature com `passes: true` sem arquivo de evidência correspondente;
- evidência cujo `files_hash` divergiu do hash atual dos `files[]` da feature —
  a prova é anterior ao código que está em disco, logo não prova mais nada;
- arquivo tracked modificado/staged fora da união dos `files[]` do contrato —
  resíduo de outro contexto misturado no fecho.

Havendo qualquer bloqueador, o comando reporta e sai com código 1 **sem varrer
nada**.

**2. Varre os descartáveis do `.harness/`.** Só executa com a auditoria limpa:

- `.harness/progress.md` volta a um resumo curto declarando o contrato
  encerrado, sem narrativa herdada de contratos anteriores;
- `.harness/scratch/` é esvaziado, preservando o `.gitignore` da pasta.

O comando nunca executa `git` nem `gh`, e nunca apaga `.harness/work/`,
`.harness/evidence/` ou `.harness/feature_list.json` — esses são histórico.

Por fim, `finish` entra na allowlist de subcomandos do `boundary_guard`, junto
dos demais comandos de leitura/compilação do próprio harness, para que o agente
possa encerrar o ciclo sem prompt de permissão.

**3. Destrava o deadlock que impede começar o próximo contrato.** Achado ao vivo
ao compilar ESTE contrato. Num repo que versiona `.harness/`, do segundo
contrato em diante o agente fica sem saída sancionada:

1. `compile-contract` reescreve `.harness/feature_list.json`, que é tracked →
   working tree suja;
2. `compile-session` recusa a tree suja e manda commitar na branch atual;
3. a branch atual é protegida (`main`), e `git commit` ali é deny do guard, cuja
   mensagem manda `git checkout -b` ou `harness compile-session`;
4. `git checkout -b` é deny do guard, por estar fora da superfície compilada.

Volta ao passo 2. As três mensagens apontam umas para as outras e nenhuma abre
caminho. A causa é uma só: `ensure_contract_branch` conta como "trabalho de
outro contexto" um arquivo que o **próprio harness** acabou de gerar. A
correção é excluir do julgamento de sujeira um conjunto explícito e pequeno de
artefatos gerenciados pelo harness — `.harness/feature_list.json` à frente,
junto do `.harness/repo-profile.json` que o `analyze` grava no mesmo fluxo. Eles
seguem para a branch nova de qualquer forma, porque `git switch -c` preserva a
working tree. Sujeira de qualquer outro arquivo continua abortando como hoje.

## Critérios de aceitação

- Com kill-switch ativo, feature sem `passes`, evidência ausente, evidência com
  `files_hash` velho ou tracked sujo fora dos `files[]`, o comando devolve
  bloqueador e sai com código 1, e o `progress.md`/`scratch/` ficam intactos —
  prova: `python -m pytest tests/test_finish.py -k audit -q`
- Com o fecho íntegro, o comando reescreve o `progress.md` como contrato
  encerrado (sem o texto do contrato anterior) e esvazia o `.harness/scratch/`
  preservando o `.gitignore` — prova:
  `python -m pytest tests/test_finish.py -k sweep -q`
- O `boundary_guard` permite `harness finish --dir .` e
  `python -m harness.cli finish --dir .` sem contrato ativo, como já faz com os
  demais subcomandos — prova:
  `python -m pytest tests/test_boundary_guard.py -k finish -q`
- Com `.harness/feature_list.json` (ou `.harness/repo-profile.json`) como única
  mudança tracked, `ensure_contract_branch` cria e troca para a branch de
  contrato em vez de abortar; com qualquer outro arquivo tracked sujo continua
  abortando com a mesma mensagem — prova:
  `python -m pytest tests/test_branching.py -k managed -q`

## Não-objetivos

- Executar `git commit`, `git push` ou `gh pr create`. Colocar ação de rede
  irreversível dentro de um subcomando que está na allowlist do agente
  transformaria o próprio `finish` em bypass do runtime floor — é a razão de
  `enable`/`disable` estarem fora dessa lista.
- Gerar "sugestões de melhoria" a partir do comando. Isso é saída de modelo, não
  de CLI: `finish` entrega os fatos e quem redige a mensagem de fecho é o
  agente.
- Apagar histórico: `.harness/work/`, `.harness/evidence/` (inclusive a
  evidência legada sem contrato na raiz) e `feature_list.json` ficam como estão.
- Fechar a issue #52 inteira. `finish` cobre só o próprio momento do fecho;
  `audit-runtime`, `doctor` e `SessionStart` continuam cegos ao kill-switch.
- Liberar `git push` e `gh pr create` na superfície compilada de permissões
  (a parada extra que ainda sobra do item 5 do backlog) — adiado por decisão
  explícita do usuário nesta rodada.
- Bump de versão e CHANGELOG, que seguem como chore direto na `main` após o
  merge.

## Unknowns

- Nenhum. O alvo é o próprio repositório do harness-creator, cujo
  `repo-profile.json` já está gravado e confirmado.
