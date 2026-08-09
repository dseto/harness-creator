# Decisões do projeto

Append-only. Escrito por `harness decide` — não edite entradas antigas;
mudou de ideia, registre uma decisão nova que supersede a anterior.

## D-001 — Lições nunca entram no contexto do agente (2026-08-09)
Decisão: SessionStart injeta decisões; lessons.md só aparece no harness finish, para o humano
Porquê: Uma lista de fricções no contexto vira backlog que o agente tentaria resolver — auto-modificação do harness pelo próprio agente, a camada que o design manda não construir. Descartado injetar 'as N mais recentes' pelo mesmo motivo: o problema não é volume.

## D-002 — Decisões e lições ficam fora de templates.py (2026-08-09)
Decisão: Módulo próprio harness/spine.py; progress.md continua em templates.py
Porquê: Ciclos de vida opostos: progress.md é regenerado a cada contrato novo, decisions/lessons são append-only e vivem o projeto inteiro. Juntar num módulo só faria um herdar a política de regeneração do outro, e regenerar decisions.md apagaria exatamente o que ele guarda.

## D-003 — Camada 3 e por demanda, fora do review.py (2026-08-09)
Decisão: Modulo proprio harness/blind.py; review.py continua sendo o state machine por feature do padrao Produtor-Revisor
Porquê: Granularidades e ciclos de vida diferentes: review.py e por FEATURE, com iteracao e teto de re-submissao, e so existe quando ha time compilado (Fase 4, opt-in); a camada 3 e por DEMANDA, uma passada, no gate de entrega, e vale sem time nenhum. Juntar faria um herdar as regras do outro -- o mesmo erro que separar spine.py de templates.py evitou.

## D-004 — O que se mecaniza na camada 3 e a ausencia (2026-08-09)
Decisão: O pacote do verificador e montado por codigo a partir do feature_list.json; o agente que implementou nunca redige esse prompt
Porquê: O julgamento nao da para mecanizar, mas a contaminacao da entrada da. Prompt escrito por quem acabou de implementar vaza a justificativa por construcao, sem ma-fe -- e o paragrafo 9.1 do design diz que avaliacao assim ja nasce contaminada. Descartado embutir o diff no pacote: o verificador le os arquivos sozinho, e o diff traria as mensagens de commit junto. Limite declarado: nao da para provar que o subagente recebeu SO o pacote; garante-se que o pacote existe, saiu de codigo, e que o veredito esta preso ao hash do estado julgado.

## D-005 — Recarimbo atualiza prova existente, nunca cria (2026-08-09)
Decisão: restamp_evidence devolve None quando nao ha arquivo de evidencia; a re-prova verde so regrava o que ja existia
Porquê: Fatia com passes:true e sem arquivo de prova e marcacao a mao, e e o que o bloqueador evidence_missing do harness finish existe para pegar. Emitir a prova no recarimbo apagaria a deteccao -- o mecanismo passaria a fabricar exatamente o tipo de registro que o harness existe para desconfiar. Descartado criar a evidencia por conveniencia.

## D-006 — Importar a lista, nao comparar duas listas (2026-08-09)
Decisão: HARNESS_CLI_VERBS vira constante de modulo em boundary_guard.py; o hook gerado recebe bakeada por json.dumps e session_permissions e o e2e importam a mesma
Porquê: A lista estava em TRES copias a mao (guard, session_permissions, tests/e2e/test_fase2_outcomes) e duas estavam desatualizadas -- a do e2e assertava a superficie EXATA, entao a copia velha exigia que o produto ficasse errado junto. Descartado o teste que compara as listas: comparar DETECTA a divergencia depois de ela existir; importar IMPEDE que exista. Bakear com json.dumps e nao repr porque aspas duplas mantem o estilo do hook gerado e ha teste que procura o verbo entre aspas duplas nesse texto.

## D-007 — O health check pergunta, nunca executa o verify_cmd (2026-08-09)
Decisão: Resolver o executavel no PATH e, so na forma <python> -m <modulo>, rodar um import; nunca executar o comando do contrato
Porquê: Executar a suite na abertura foi o que fez ninguem rodar o .harness/init.ps1 que o passo 2 ja mandava rodar; um check caro vira opcional na pratica, e um check opcional nao cobre o modo de falha do 8.3, que e o silencio

## D-008 — Conteudo da working tree nao decide o que o health check lanca (2026-08-09)
Decisão: Executavel so e procurado dentro da arvore quando o token tem separador de caminho, e so vira import o que casa nome de modulo pontilhado
Porquê: Sem as duas fronteiras, um arquivo de texto homonimo fazia o laudo dizer VERDE para ferramenta ausente, e um arquivo chamado python escolhia o interpretador que o hook da abertura lanca sozinho; a fronteira do separador ainda bate com o que o cmd.exe faz de verdade
