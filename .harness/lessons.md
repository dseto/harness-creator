# Lições — fricções observadas

Append-only. Escrito por `harness lesson`. Quem fecha um item é o HUMANO,
revisando em cadência própria — o agente anota, não aplica.
- [ ] re-prova incremental verde nao recarimba a evidencia da tarefa antiga: ela continua stale e o harness finish cobra um harness verify manual → avaliar se a re-prova verde deve regravar files_hash da evidencia da tarefa re-provada
- [ ] guard nega git switch/pull isolados mas deixou passar em chamada composta, e nao ha caminho sancionado de volta para a branch de contrato → tornar o deny de git switch deterministico e abrir retorno para contract/<slug> ativo
- [ ] session_permissions.FIXED_HARNESS_SEQUENCES esta desatualizado: nao tem blind, finish, budget, reconcile, decide, lesson, task nem pr-draft, e o comentario ainda diz espelhar o guard → derivar a lista do mesmo lugar que o guard, ou um teste que compare as duas listas -- o mesmo mecanismo que ja pega verbo esquecido no guard
- [ ] veredito da camada 3 e invalidado pelas proprias observacoes nao-bloqueantes do verificador: agir sobre elas muda arquivo do contrato e o veredito vira stale, exigindo nova passada → avaliar veredito escopado por tarefa, ou um modo de re-julgamento so do delta desde o veredito anterior
- [ ] contagem de casos no README nao tem teste que a trave: errei o numero duas vezes seguidas na mesma demanda, e so o verificador cego pegou → teste que compara o numero do README com pytest --collect-only, como test_version_sync ja faz com a versao
