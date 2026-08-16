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

## D-009 — Placar e opt-in: harness status sem flag continua JSON (2026-08-10)
Decisão: O painel entra por --brief/--panel; a saida default de harness status permanece o mesmo JSON estruturado
Porquê: session_start.py aponta harness status como fonte de verdade estruturada do kill-switch e a issue #52 estabeleceu esse comando como o unico lugar que conta a verdade sobre o harness desligado. Trocar a saida default por um painel quebraria todo consumidor dessa leitura para ganhar estetica. Descartado tambem inverter (painel default + --json): sinalizaria que o JSON e o caso especial, quando ele e o contrato.

## D-010 — Statusline standalone repete leitura magra em vez de importar panel (2026-08-10)
Decisão: O hook gerado le feature_list.json e a ultima linha do rastro por conta propria; nenhuma regra de decisao (disjuntor, veredito, proximo passo) e replicada nele
Porquê: O hook roda pelo Claude Code fora do venv do projeto, igual a session_start/stop_hook/boundary_guard -- import harness ali quebra na maquina de quem instalou o plugin sem o pacote no PATH do CLI. O preco e leitura duplicada; o teto do preco e a linha ser magra de proposito, e o teste executar o ARQUIVO GERADO por subprocess em vez de uma copia da logica, para a duplicacao nao virar divergencia silenciosa. Descartado embutir o panel.py inteiro por render (o DISABLED_CHECK_SRC embute 10 linhas; embutir 300 seria um segundo modulo mantido a mao).

## D-011 — compile-session nunca sobrescreve statusline do usuario (2026-08-10)
Decisão: install_statusline usa replace_foreign=False no compile-session: entrada statusLine que nao veio do harness e preservada, e o hook e gravado assim mesmo
Porquê: A barra do CLI e o unico artefato deste contrato que fica visivel o tempo todo na interface da pessoa. Entrada que o harness nao instalou (nao bate com o compiled-state nem aponta para o hook) e configuracao dela; sobrescrever seria o compilador decidindo o que aparece na tela do usuario sem pedir. O hook continua sendo gravado para ela poder apontar quando quiser.

## D-012 — Texto de escalada muda dentro do JSON do budget, e isso e o esperado (2026-08-10)
Decisão: O campo escalation do stdout de harness budget passa a comecar com PAROU:; a promessa de stdout byte-identico do T-05 vale para os campos de maquina (verdict, consecutive_failures, limits, reason)
Porquê: O campo escalation E o canal humano -- ele so esta dentro do JSON porque o comando emite os dois de uma vez (stdout para script, stderr para quem le). Congelar esse texto para manter o stdout literalmente identico exigiria DUAS versoes do mesmo bloco de escalada, uma velha para o JSON e uma nova para o stderr, e duas versoes do mesmo texto e a origem de divergencia silenciosa. Levantado pelo verificador cego; registrado para nao ser re-litigado como bug.

## D-013 — Bloqueio declarado e do agente, e o harness nunca o infere (2026-08-12)
Decisão: Quem declara que uma fatia parou por dependencia humana e o agente, via harness block <id> --needs; o harness nao adivinha a partir da saida de nenhum comando
Porquê: Na sessao que originou a demanda o agente JA sabia que dependia de uma edicao humana e escreveu isso na tela antes de repetir a tentativa 16 vezes -- faltava onde registrar, nao como descobrir. Inferencia automatica erraria nos dois sentidos: travaria trabalho por bug de implementacao e deixaria passar dependencia humana silenciosa. Descartado tambem destrave por tempo: bloqueio que caduca sozinho volta a empurrar trabalho contra a mesma parede, com atraso.

## D-014 — Liquidacao do bloqueio mora na CLI, nao nos leitores (2026-08-12)
Decisão: settle_blocks e chamado por harness.cli antes de despachar qualquer subcomando nao-diagnostico; dispatch_next e collect_state continuam sem nenhum caminho de escrita
Porquê: read_block decide a espera na leitura, o que e barato para quem le mas deixa o progress.md -- coluna ESCRITA, e o primeiro arquivo que a proxima sessao le -- dizendo AGUARDANDO VOCE sobre fatia ja liberada. Colocar a escrita dentro dos leitores quebraria o SO LEITURA que os dois prometem no docstring, e essa promessa vale mais que a conveniencia. Verbos de diagnostico (doctor, health, audit*) ficam de fora porque a allowlist do boundary_guard os justifica por escrito como read-only.

## D-015 — Setup do ciclo vira fail-closed; runtime e diagnostico continuam intocados (2026-08-16)
Decisão: compile-contract, compile-session, harness verify, harness supervise e task add-file recusam (exit 1) em vez de avisar quando falta harness.yaml (setup) ou falta enforcement nesta maquina com contrato ativo (trabalho); runtime (escapes do boundary_guard: task add-file, .harness/scratch/, YAML colavel do deny) e diagnostico (status/doctor/health) continuam intocados, so reportando
Porquê: Reverte deliberadamente o nao-objetivo do contrato governanca-parcial-invisivel-sem-init (nao tornar harness.yaml obrigatorio para compile-session, spec.md:73-74 daquele contrato, v0.30.0). O aviso em stderr de missing_harness_yaml_warning provou-se invisivel: numa sessao real o preflight rodou, o plan rodou sem harness.yaml, o aviso passou despercebido, o plano executou inteiro com alteracoes fora do contrato passando, e o harness so confessou a governanca ausente no fim -- tarde demais para importar. Racional da distincao: o harness barra o minimo e criterio de RUNTIME (agente sozinho por horas; deny duro sem escape empurra para o kill-switch, que e desprotecao total, pior que o deny que se queria evitar). Setup e outro tempo: humano presente na tela, uma vez por projeto, custo de destravar e rodar /harness-creator:init. Escopo decidido na implementacao do T-03: enforcement_gate_problem (health.py) so dispara em repo GOVERNADO (harness.yaml presente) com contrato ativo -- repo sem harness.yaml e caso do gate de setup (T-01/T-02), nao deste; misturar os dois faria verify/supervise competir por mensagem alheia e quebraria a suite de run_verify/dispatch_next, que roda de proposito com contrato ativo e sem hooks instalados.
