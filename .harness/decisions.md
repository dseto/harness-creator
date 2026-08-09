# Decisões do projeto

Append-only. Escrito por `harness decide` — não edite entradas antigas;
mudou de ideia, registre uma decisão nova que supersede a anterior.

## D-001 — Lições nunca entram no contexto do agente (2026-08-09)
Decisão: SessionStart injeta decisões; lessons.md só aparece no harness finish, para o humano
Porquê: Uma lista de fricções no contexto vira backlog que o agente tentaria resolver — auto-modificação do harness pelo próprio agente, a camada que o design manda não construir. Descartado injetar 'as N mais recentes' pelo mesmo motivo: o problema não é volume.

## D-002 — Decisões e lições ficam fora de templates.py (2026-08-09)
Decisão: Módulo próprio harness/spine.py; progress.md continua em templates.py
Porquê: Ciclos de vida opostos: progress.md é regenerado a cada contrato novo, decisions/lessons são append-only e vivem o projeto inteiro. Juntar num módulo só faria um herdar a política de regeneração do outro, e regenerar decisions.md apagaria exatamente o que ele guarda.
