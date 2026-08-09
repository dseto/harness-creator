"""Agent Session Lifecycle: compila o ciclo de 17 passos (docs/project/ROADMAP.md, Fase 2)
como bloco gerenciado ADICIONAL no `AGENTS.md`, com progressive disclosure
(bloco fino aponta para o detalhe em `.harness/LIFECYCLE.md`).

Divergência deliberada do texto do docs/project/ROADMAP.md: a linha ~198 lista a entrega
como seções `state`/`lifecycle` no `harness.yaml` (i.e., dentro de
`HarnessConfig`, em `config.py`); este módulo implementa a mesma entrega via
Python + bloco em `AGENTS.md` + arquivo `.harness/LIFECYCLE.md`, sem estender
o schema do yaml — mais simples para algo que é essencialmente texto/instrução
e não configuração.

Os delimitadores (`LIFECYCLE_BEGIN`/`LIFECYCLE_END`) são PRÓPRIOS desta
entrega — diferentes de `AGENTS_BEGIN`/`AGENTS_END` de `compiler.py` — para
que os dois blocos gerenciados convivam no mesmo `AGENTS.md` sem colisão.
"""

from __future__ import annotations

import re
from pathlib import Path

LIFECYCLE_BEGIN = "<!-- harness:lifecycle:begin -->"
LIFECYCLE_END = "<!-- harness:lifecycle:end -->"

LIFECYCLE_DETAIL_PATH = ".harness/LIFECYCLE.md"


def render_lifecycle_block() -> str:
    """Bloco curto (progressive disclosure) para o AGENTS.md: os 17 passos
    do Agent Session Lifecycle (docs/project/ROADMAP.md, Fase 2) como lista numerada
    compacta — uma linha por passo, sem repetir o detalhe completo."""
    return f"""{LIFECYCLE_BEGIN}
## Agent Session Lifecycle (gerado — 17 passos, docs/project/ROADMAP.md Fase 2)

1. Ler `AGENTS.md`.
2. Rodar `.harness/init.sh`/`.harness/init.ps1` (deps + health check do profile).
3. Ler `.harness/progress.md`.
4. Ler `feature_list.json`.
5. Rodar `harness reconcile` e resolver toda divergência antes de seguir —
   estado declarado que não bate com o repositório envenena a sessão inteira.
6. Escolher exatamente UMA feature pendente.
7. Planejar a implementação da feature escolhida — alternativa descartada por
   razão não óbvia vira `harness decide`.
8. Implementar a mudança dentro do raio de impacto declarado.
9. Rodar `verify_cmd` da tarefa — o `harness verify` ainda re-prova sozinho as
   tarefas concluídas que compartilham arquivo com esta; exit 2 = regressão a
   consertar antes de seguir.
10. Se falhar: consultar `harness budget --feature <id>` e obedecer o
    veredito — autocorrigir e re-rodar só enquanto ele disser `continue`.
11. Registrar a prova (evidência da verificação bem-sucedida).
12. Atualizar `.harness/progress.md` com o estado atual.
13. Marcar a feature concluída em `feature_list.json`.
14. Documentar o que ficou quebrado, e anotar a fricção da sessão com
    `harness lesson` — o agente anota, quem compila é o humano.
15. Apresentar o que será commitado — por feature: descrição funcional em
    linguagem natural do que mudou, e link `file:line` do teste que prova.
16. Commit e push na branch do contrato, condicionados a `harness finish`
    com `blockers: []`. O PR é do humano: entregue o `harness pr-draft`.
17. Deixar a working tree limpa.

Detalhe de cada passo: ver `.harness/LIFECYCLE.md`.
{LIFECYCLE_END}"""


def render_lifecycle_detail() -> str:
    """Conteúdo completo de `.harness/LIFECYCLE.md`: um parágrafo por passo,
    explicando o objetivo de cada um (prosa baseada no docs/project/ROADMAP.md Fase 2)."""
    return """# Agent Session Lifecycle — Detalhe dos 17 Passos

Este arquivo é o detalhe de progressive disclosure do bloco "Agent Session
Lifecycle" em `AGENTS.md`. Cada passo abaixo corresponde ao ciclo de 17
passos descrito no `docs/project/ROADMAP.md` (Fase 2 — "Execução Autônoma no Raio de
Impacto"): a sessão nasce sabendo onde parou, trabalha dentro do contrato
aprovado e só devolve o controle ao humano em estado retomável.

1. **Ler `AGENTS.md`.** Primeiro passo de toda sessão: carregar a
   governança compilada (permissions, hooks, este próprio lifecycle) antes
   de tocar em qualquer arquivo do projeto.

2. **Rodar `.harness/init.sh`/`.harness/init.ps1` (deps + health check do profile).** Script
   gerado a partir do profile do projeto: instala dependências e roda um
   health check para confirmar que o ambiente está utilizável antes de
   começar a trabalhar.

3. **Ler `.harness/progress.md`.** Resumo do estado da sessão anterior — o
   que já foi feito, o que ficou pendente, o que quebrou. Evita retrabalho
   e recontagem de contexto pelo humano.

4. **Ler `feature_list.json`.** Lista de features do plano aprovado, cada
   uma com seu status (`pending`/`done`) e critério de verificação
   (`verify_cmd`).

5. **Rodar `harness reconcile`.** Compara o que o repositório DECLARA com o
   que ele TEM, e devolve as divergências em JSON (exit 0 = íntegro, 2 = há
   divergência, 1 = não foi possível checar). São quatro tipos, e nenhum
   deles apareceria num `git log` — que era o que este passo pedia antes:

   - `evidence_stale` — o `files_hash` gravado na prova não bate com o
     conteúdo atual dos `files[]`: a tarefa está marcada como feita, mas o
     código mudou depois da prova. Rode `harness verify <id>` de novo.
   - `evidence_missing` — tarefa com `passes: true` e nenhum arquivo de
     evidência, ou seja, marcada à mão.
   - `progress_contract_mismatch` — o `.harness/progress.md` descreve um
     contrato diferente do `feature_list.json`. É o resumo que você acabou de
     ler no passo 3; se ele é de outra demanda, tudo que você concluiu dele
     está errado. Rode `harness compile-session` para regenerá-lo.
   - `tree_residue` / `killswitch_active` — sobra de outro contexto na
     working tree, ou o harness rodando em no-op.

   Na sessão iniciada pelo Claude Code o hook `SessionStart` já injeta este
   relatório sozinho, e o passo é a conferência de que ele foi lido. Rode o
   comando à mão quando o aviso não chegou — sessão retomada, execução fora
   do Claude Code, ou hook desinstalado. **Divergência não é ruído a
   registrar: é trabalho a fazer antes de escolher uma fatia.** Seguir em
   cima de anotação errada é como o trabalho da sessão anterior se perde.

6. **Escolher exatamente UMA feature pendente.** Disciplina de escopo: a
   sessão trabalha em uma única feature por vez, nunca em paralelo dentro
   da mesma sessão — isso mantém o raio de impacto pequeno e revisável.

7. **Planejar a implementação da feature escolhida.** Antes de editar
   código, esboçar a abordagem: quais arquivos mudam, que testes cobrem a
   mudança, qual é o critério de pronto.

   Descartou uma alternativa por razão NÃO ÓBVIA, ou tomou uma decisão que
   restringe as iterações seguintes? Registre:

       harness decide "<título curto>" --decision "<o que foi decidido>" --why "<a razão, incluindo a alternativa descartada>"

   O registro é append-only (`.harness/decisions.md`) e as decisões recentes
   chegam sozinhas no contexto da próxima sessão. Sem isso, a sessão de daqui
   a duas semanas "descobre" e tenta de novo o caminho que esta aqui descartou
   por bom motivo — o motivo não estava em lugar nenhum que ela lesse. Não é
   ADR: três linhas bastam, e decisão óbvia não precisa de registro nenhum.

8. **Implementar a mudança dentro do raio de impacto declarado.** Editar
   apenas os arquivos ligados à feature escolhida — o `boundary_guard`
   (Fase 2) nega qualquer edição fora dessa superfície.

9. **Rodar `verify_cmd` da tarefa.** Comando de verificação vindo do
   contrato (build, lint, suíte de teste) — a prova executável de que a
   implementação funciona.

   Verde nesta tarefa não significa verde no repositório: ela pode ter
   quebrado uma tarefa já concluída. Por isso o `harness verify` faz também a
   **re-prova incremental** (§6 do design) — re-roda o `verify_cmd` das
   tarefas já `passes: true` que compartilham ARQUIVO com esta, a interseção
   declarada em `files[]`, nunca a suíte inteira (suíte completa é o gate
   final; dentro do loop ela só encarece a volta).

   Leia o exit code:

   - exit code 0 — nada acoplado regrediu. Siga.
   - exit code 2 — **regressão**: alguma tarefa concluída voltou a falhar. Ela já foi
     rebaixada para `passes: false`, com a tentativa registrada, e o
     `harness supervise` volta a devolvê-la. Conserte antes de escolher outra
     fatia: o diff suspeito ainda tem o tamanho de uma iteração, e é aqui que
     o conserto é barato.
   - exit code 1 — erro de execução do próprio comando (o de sempre).

   Um item `SEM VEREDITO` na saída é falha de ambiente (timeout, prova no
   runtime floor), não regressão: ninguém é rebaixado, mas aquela prova
   **não** foi confirmada — trate como falha de infraestrutura (passo 10).
   `--no-reproof` desliga a checagem; desligar custa exatamente a detecção de
   regressão entre fatias.

10. **Se falhar: consultar o disjuntor e obedecer o veredito.** Loop de
    autocorreção (Fase 3): o agente conserta a própria falha e testa de
    novo, sem envolver o humano — mas não indefinidamente, e não por
    julgamento próprio sobre quando desistir.

    Toda falha de `harness verify` já grava a tentativa em
    `.harness/attempts/<contrato>/<id>.jsonl` (erro cru, exit code,
    assinatura da falha). A cada vermelho, rode:

        harness budget --feature <id>

    e siga o `verdict`:

    - `continue` — corrija e re-rode o `verify_cmd`.
    - `stop_same_failure` — a MESMA falha se repetiu até o teto. O que está
      errado é a abordagem, não a execução: **mude de estratégia** (e diga
      qual, e por quê, ao reportar) ou escale. Insistir aqui é queimar o
      budget repetindo o que já não funcionou.
    - `stop_iterations` — o teto de tentativas desde o último verde
      estourou. Pare, registre o estado em `.harness/progress.md` e devolva
      o controle ao humano.

    Os tetos vêm, nesta ordem, das `stop_conditions:` TIPADAS do frontmatter
    do `spec.md` ativo (`{type: consecutive_verify_failures, n: 3}`,
    `{type: same_failure_signature, n: 3}`) e, na ausência delas, de
    `governance.budget.max_green_iterations` do `.harness/harness.yaml`.

    As `stop_conditions:` escritas em PROSA continuam valendo como condição
    adicional — elas cobrem o que nenhuma contagem pega, como o sinal de
    impossibilidade ("a dependência não existe", "o requisito é
    contraditório"). Essas são lidas por
    `harness.contract.get_stop_conditions` e interpretadas por você; parar
    por uma delas é acerto, não desistência, e não precisa esperar teto
    nenhum.

    Em qualquer parada, o que vai para o humano é DIAGNÓSTICO, não sintoma:
    o que estava sendo tentado, as abordagens em ordem, o último erro cru
    (está no `reason` e no rastro), e a sugestão de próximo passo.

11. **Registrar a prova (evidência da verificação bem-sucedida).** Grava a
    evidência de que `verify_cmd` passou (timestamp, comando, hash) — é o
    que autoriza marcar a feature como concluída no passo 13.

12. **Atualizar `.harness/progress.md` com o estado atual.** Documenta o que
    foi feito nesta sessão, para que a próxima sessão (passo 3) retome sem
    perder contexto.

13. **Marcar a feature concluída em `feature_list.json`.** Só acontece com
    evidência fresca do passo 11 — marcar sem evidência é enfraquecer a
    garantia que todo o lifecycle existe para proteger.

14. **Documentar o que ficou quebrado, e anotar a fricção que apareceu.**
    Transparência: se algo ficou incompleto ou quebrado, isso é registrado
    explicitamente — nunca escondido atrás de um commit "limpo".

    Bateu numa fricção durante a sessão — regra que barrou demais, critério
    ambíguo, mensagem de erro que não ajudou, o mesmo erro pela terceira vez?
    Anote no momento em que aconteceu, uma linha, sem interromper o trabalho:

        harness lesson "<a fricção observada>" --fix "<melhoria candidata no harness/skill/critério>"

    **O agente anota; quem compila é o humano.** Não feche um item, não
    "aplique" a lição editando o harness, não abra issue por conta própria:
    auto-modificação do harness pelo próprio agente é a camada mais perigosa
    do design e não vale o risco. As lições em aberto aparecem no
    `harness finish` (campo `open_lessons`) — é ali que a pessoa as encontra.

15. **Apresentar o que será commitado.** Este passo deixou de ser um gate: o
    ciclo tem UM pedido humano, a aprovação do contrato, e ela já autoriza o
    trabalho até o push. O que o passo continua exigindo é VISIBILIDADE — a
    sessão reporta, em mensagem clara e direta (não sub-entendida em log), o
    que mudou. Mostrar só o identificador da feature (`T-01`) e o JSON cru do
    `verify_cmd` **não é suficiente** — ninguém acompanha o que foi feito só
    com isso. Por feature, a mensagem PRECISA conter: (a) descrição funcional
    em linguagem natural do comportamento que mudou (não o nome do arquivo,
    não o comando — o que o teste efetivamente cobre), e (b) link direto
    `file:line` do teste que prova o critério, para o humano abrir e ler sem
    caçar. Além disso: o que ficou quebrado, se houver (passo 14).

16. **Commit e push na branch do contrato.** O commit local (`git add`/`git
    commit`) e o `git push` da branch do contrato acontecem sem pedir
    autorização — mas NÃO incondicionalmente. As duas pré-condições abaixo
    são o que substitui o antigo gate humano, e sem elas o agente para e
    chama a pessoa:

    - `harness finish` sai com `blockers: []` — o que já implica toda tarefa
      com `passes: true` e evidência cujo `files_hash` bate com o arquivo
      atual, isto é, prova que descreve o código que está sendo commitado;
    - nenhum `verify_cmd` vermelho.

    O push é só da branch do contrato (`contract/<slug>`) para ela mesma: o
    runtime floor do `boundary_guard` já restringe exatamente a isso — sem
    `--force`, sem refspec explícito, nunca a partir de branch protegida.
    Commit em `main` continua barrado, e o `chore` de versão/CHANGELOG segue
    sendo do humano, no terminal dele.

    **O agente NUNCA abre, aprova ou mergeia Pull Request.** Expor o trabalho
    para revisão e merge é decisão humana deliberada. O que o agente entrega é
    o trabalho pronto para isso: rode `harness pr-draft`, que monta o corpo do
    PR a partir do contrato e imprime o comando `gh pr create` exato, e
    repasse os dois ao humano.

17. **Deixar a working tree limpa.** Fim de sessão: nenhuma mudança solta
    fora de commit, nenhum arquivo temporário esquecido — o handoff para a
    próxima sessão (ou para o humano) começa de um estado previsível.
"""


def install_lifecycle(target_dir: Path) -> tuple[Path, Path]:
    """Grava/atualiza os dois artefatos do lifecycle no projeto-alvo:

    (a) `target_dir/AGENTS.md` — substitui o conteúdo entre
        `LIFECYCLE_BEGIN`/`LIFECYCLE_END` se já existir (mesmo padrão de
        `_write_agents_block` em `compiler.py`: regex `re.DOTALL`), ou
        anexa o bloco no fim do arquivo (criando o AGENTS.md com um
        cabeçalho mínimo se ele não existir) caso as marcações ainda não
        estejam presentes. Nunca apaga texto fora dos delimitadores, nem o
        bloco de `compiler.py` (`AGENTS_BEGIN`/`AGENTS_END`), que pode
        coexistir no mesmo arquivo.
    (b) `target_dir/.harness/LIFECYCLE.md` — grava `render_lifecycle_detail()`,
        criando `.harness/` se preciso.

    Retorna `(agents_path, detail_path)`.
    """
    agents_path = target_dir / "AGENTS.md"
    block = render_lifecycle_block()

    if agents_path.is_file():
        text = agents_path.read_text(encoding="utf-8")
        if LIFECYCLE_BEGIN in text and LIFECYCLE_END in text:
            pattern = re.compile(
                re.escape(LIFECYCLE_BEGIN) + ".*?" + re.escape(LIFECYCLE_END), re.DOTALL
            )
            text = pattern.sub(lambda _: block, text, count=1)
        else:
            text = text.rstrip() + "\n\n" + block + "\n"
    else:
        text = "# AGENTS.md — Diretrizes para Agentes\n\n" + block + "\n"
    agents_path.write_text(text, encoding="utf-8")

    detail_path = target_dir / ".harness" / "LIFECYCLE.md"
    detail_path.parent.mkdir(parents=True, exist_ok=True)
    detail_path.write_text(render_lifecycle_detail(), encoding="utf-8")

    return agents_path, detail_path
