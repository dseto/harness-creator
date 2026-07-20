"""Agent Session Lifecycle: compila o ciclo de 16 passos (docs/project/ROADMAP.md, Fase 2)
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
    """Bloco curto (progressive disclosure) para o AGENTS.md: os 16 passos
    do Agent Session Lifecycle (docs/project/ROADMAP.md, Fase 2) como lista numerada
    compacta — uma linha por passo, sem repetir o detalhe completo."""
    return f"""{LIFECYCLE_BEGIN}
## Agent Session Lifecycle (gerado — 16 passos, docs/project/ROADMAP.md Fase 2)

1. Ler `AGENTS.md`.
2. Rodar `init.sh`/`init.ps1` (deps + health check do profile).
3. Ler `claude-progress.md`.
4. Ler `feature_list.json`.
5. Checar `git log`.
6. Escolher exatamente UMA feature pendente.
7. Planejar a implementação da feature escolhida.
8. Implementar a mudança dentro do raio de impacto declarado.
9. Rodar `verify_cmd` da tarefa.
10. Se falhar: autocorrigir e re-rodar `verify_cmd` até passar.
11. Registrar a prova (evidência da verificação bem-sucedida).
12. Atualizar `claude-progress.md` com o estado atual.
13. Marcar a feature concluída em `feature_list.json`.
14. Documentar o que ficou quebrado, se houver.
15. Commit apenas em estado retomável.
16. Deixar a working tree limpa.

Detalhe de cada passo: ver `.harness/LIFECYCLE.md`.
{LIFECYCLE_END}"""


def render_lifecycle_detail() -> str:
    """Conteúdo completo de `.harness/LIFECYCLE.md`: um parágrafo por passo,
    explicando o objetivo de cada um (prosa baseada no docs/project/ROADMAP.md Fase 2)."""
    return """# Agent Session Lifecycle — Detalhe dos 16 Passos

Este arquivo é o detalhe de progressive disclosure do bloco "Agent Session
Lifecycle" em `AGENTS.md`. Cada passo abaixo corresponde ao ciclo de 16
passos descrito no `docs/project/ROADMAP.md` (Fase 2 — "Execução Autônoma no Raio de
Impacto"): a sessão nasce sabendo onde parou, trabalha dentro do contrato
aprovado e só devolve o controle ao humano em estado retomável.

1. **Ler `AGENTS.md`.** Primeiro passo de toda sessão: carregar a
   governança compilada (permissions, hooks, este próprio lifecycle) antes
   de tocar em qualquer arquivo do projeto.

2. **Rodar `init.sh`/`init.ps1` (deps + health check do profile).** Script
   gerado a partir do profile do projeto: instala dependências e roda um
   health check para confirmar que o ambiente está utilizável antes de
   começar a trabalhar.

3. **Ler `claude-progress.md`.** Resumo do estado da sessão anterior — o
   que já foi feito, o que ficou pendente, o que quebrou. Evita retrabalho
   e recontagem de contexto pelo humano.

4. **Ler `feature_list.json`.** Lista de features do plano aprovado, cada
   uma com seu status (`pending`/`done`) e critério de verificação
   (`verify_cmd`).

5. **Checar `git log`.** Confirma o que já foi commitado de fato, cruzando
   com o que `claude-progress.md`/`feature_list.json` alegam — detecta
   divergência entre estado declarado e estado real do repositório.

6. **Escolher exatamente UMA feature pendente.** Disciplina de escopo: a
   sessão trabalha em uma única feature por vez, nunca em paralelo dentro
   da mesma sessão — isso mantém o raio de impacto pequeno e revisável.

7. **Planejar a implementação da feature escolhida.** Antes de editar
   código, esboçar a abordagem: quais arquivos mudam, que testes cobrem a
   mudança, qual é o critério de pronto.

8. **Implementar a mudança dentro do raio de impacto declarado.** Editar
   apenas os arquivos ligados à feature escolhida — o `boundary_guard`
   (Fase 2) nega qualquer edição fora dessa superfície.

9. **Rodar `verify_cmd` da tarefa.** Comando de verificação vindo do
   contrato (build, lint, suíte de teste) — a prova executável de que a
   implementação funciona.

10. **Se falhar: autocorrigir e re-rodar `verify_cmd` até passar.** Loop de
    autocorreção (Fase 3): o agente conserta a própria falha e testa de
    novo, sem envolver o humano, respeitando as stop conditions (N falhas
    consecutivas ou sinal de impossibilidade interrompe o loop). A fonte
    dessas stop conditions é explícita: o campo `stop_conditions:` do
    frontmatter do `spec.md` ativo (`.harness/work/<slug>/spec.md`),
    acessível via `harness.contract.get_stop_conditions` — esse campo é o
    disjuntor do loop. Satisfazer QUALQUER uma das condições listadas ali
    interrompe a autocorreção, registra o estado em `claude-progress.md` e
    devolve o controle ao humano junto com o diagnóstico da falha.

11. **Registrar a prova (evidência da verificação bem-sucedida).** Grava a
    evidência de que `verify_cmd` passou (timestamp, comando, hash) — é o
    que autoriza marcar a feature como concluída no passo 13.

12. **Atualizar `claude-progress.md` com o estado atual.** Documenta o que
    foi feito nesta sessão, para que a próxima sessão (passo 3) retome sem
    perder contexto.

13. **Marcar a feature concluída em `feature_list.json`.** Só acontece com
    evidência fresca do passo 11 — marcar sem evidência é enfraquecer a
    garantia que todo o lifecycle existe para proteger.

14. **Documentar o que ficou quebrado, se houver.** Transparência: se algo
    ficou incompleto ou quebrado, isso é registrado explicitamente — nunca
    escondido atrás de um commit "limpo".

15. **Commit apenas em estado retomável.** O commit local (`git add`/
    `git commit`) só acontece quando o repositório está em um estado que a
    próxima sessão (ou o humano) consegue retomar sem arqueologia.

16. **Deixar a working tree limpa.** Fim de sessão: nenhuma mudança solta
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
