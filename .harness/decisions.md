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
