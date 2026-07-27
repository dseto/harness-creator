# Dogfood das ondas 2–4 contra `C:\Projetos\miojo-simulator-3.0`

**Data:** 2026-07-27. **Alvo:** MiojoSimulator 3.0 — FastAPI + Python 3.14 com
`.venv` no Windows, frontend estático. É o primeiro alvo que reúne as condições
do relato original (`Savant.Backend.APP-15167`): Python **com venv**, Windows, e
um contrato real já autorado (`.harness/work/frontend-progress-bar/`).

**Versões comparadas:** `origin/main` **v0.18.0** (`45ea0ca`) contra a branch
`feat/savant-ondas-2-5` **v0.19.0**, instaladas lado a lado em duas cópias do
alvo, com os hooks gerados por cada uma recebendo **payloads `PreToolUse` reais
via stdin**.

O trabalho não-commitado do usuário não foi tocado: tudo o que exigia árvore
limpa rodou em clone.

---

## 1. O A/B — 6 decisões mudaram, todas na direção pretendida

`verify_cmd` do contrato: `python -m pytest tests/test_progress_bar.py -v`.

| | v0.18.0 | v0.19.0 | comando |
|---|---|---|---|
| | allow | allow | `python -m pytest tests/test_progress_bar.py -v` |
| **→** | **deny** | **allow** | `pytest tests/test_progress_bar.py -v` |
| **→** | **deny** | **allow** | `.venv/Scripts/pytest.exe tests/test_progress_bar.py -v` |
| **→** | **deny** | **allow** | `.venv/Scripts/python.exe -m pytest tests/test_progress_bar.py -v` |
| **→** | **deny** | **allow** | `uv run pytest tests/test_progress_bar.py -v` |
| **→** | **deny** | **allow** | `python -m pytest … -v \| Select-Object -First 20` (PowerShell) |
| **→** | **deny** | **allow** | `.venv/Scripts/pytest.exe … \| Select-Object -First 20` (PowerShell) |
| | deny | deny | `source .venv/Scripts/activate && pytest …` |
| | deny | deny | `python backend/main.py` |
| | deny | deny | `$env:PATH = '.venv\Scripts'; pytest` |
| | deny | deny | `python -m pytest \| ForEach-Object { rm -rf backend }` |
| | deny | deny | `git push origin main` · `.venv/Scripts/git.exe push origin main` |
| | deny | deny | `curl http://localhost:8000/runs` · `.venv/Scripts/curl.exe …` |
| | allow | allow | `uvicorn backend.main:app --reload` (extra_allowed_commands) |
| | deny | deny | `Write backend/main.py` · `Write .harness/harness.yaml` · `Write .env` |

Nenhuma decisão de floor mudou, e nenhum deny virou allow fora da classe de
equivalência de forma. As quatro formas que o venv Windows obriga a usar
deixaram de custar um ciclo de tentativa-e-erro cada.

**Cross-check de gramática do Item 3 validado em arquivo real:** o
`harness.yaml` deste alvo declara `uvicorn backend.main:app` — dois-pontos
colado, o caso que o parser mínimo precisa aceitar. `compile-session` devolveu
`extra_allowed_commands_grammar_problem: null` e o guard liberou o comando.

**Escopação de evidência validada por acidente feliz:** o alvo tinha uma
evidência órfã do layout antigo (`.harness/evidence/T-01.json`, `exit_code: 0`,
de 16/07, sem campo `contract`). O `verify` de hoje **falhou** — o
`frontend/app.js` foi reescrito por um commit posterior e não tem mais
`data.progress`. A evidência velha ficou inerte, exatamente como a escopação por
contrato promete. Nada, porém, **detecta ou limpa** a órfã (já registrado como
P2 no backlog dos testes isentos; agora com instância real).

---

## 2. Achados novos — **os oito corrigidos**

> **Estado (2026-07-27, fim do dia):** os oito achados foram corrigidos. F4 e F8
> saíram na mesma sessão do dogfood; F1, F2, F3, F5, F6 e F7 saíram logo em
> seguida, a pedido do usuário. Cada seção abaixo mantém o diagnóstico original
> e traz o bloco **Corrigido** com o que mudou e como está coberto.

### F1 — `requirements.txt` não era manifest reconhecido (ALTO, causa-raiz — CORRIGIDO)

`harness analyze` num repo com `requirements.txt`, `backend/*.py`,
`tests/conftest.py` e `tests/test_*.py` devolve:

```json
{ "languages": [], "package_manager": null, "test_command": null, "test_glob": null }
```

O analyzer é dirigido a manifesto e só reconhece Python por `pyproject.toml`/
`setup.py`. O próprio `spec.md` do alvo já documentava isso como limitação
conhecida, em 16/07 — o que significa que o autor do contrato gastou tempo
descobrindo e escrevendo a explicação.

**A cascata é o que faz disso um achado alto**, não a detecção em si:

- `harness preflight` devolve **NOT_READY** com `manifest_present: FAIL` e
  `test_runner_detected: FAIL` num repo Python perfeitamente governável;
- **o check de sombra de venv (B3) nunca dispara.** Ele existe para avisar
  "repo COM venv + comando não ancorado nele"; mas depende de haver um
  `test_command` inferido, e não há. F1 mascara F5 abaixo;
- `test_glob` fica `null`, e é dele que `_is_test_diff` depende — o gate de
  "diff de teste exige justificativa" do padrão produtor-revisor fica **inerte**
  sem sinal nenhum.

**Corrigido.** `requirements.txt` entrou em `_PYTHON_MANIFESTS`, e o runner
ganhou dois detectores novos, nesta ordem: `conftest.py` — que é **prova**, o
arquivo só existe para o pytest — e `pytest` declarado em `requirements*.txt`
(casando o NOME do pacote, não substring: `pytest-asyncio` sozinho não conta).
O `conftest.py` é o que resolve o caso do alvo, cujo `requirements.txt` lista só
dependências de runtime. Repo com `pyproject.toml` **e** `requirements.txt`
continua provando pelo manifesto mais forte, o que é o que mantém o
`pip install -e .` de quem realmente é um pacote (F2).

O alvo real, depois: `languages: [python]`, `test_command: pytest` (evidência
`tests/conftest.py`), `test_glob: tests/**/*.py`, `unknowns: []`, e o preflight
saiu de **NOT_READY** para **READY_WITH_WARNINGS**.

### F2 — `package_manager: pip` mapeava para o comando errado (MÉDIO — CORRIGIDO)

`INSTALL_COMMAND_BY_PACKAGE_MANAGER["pip"] = "pip install -e ."`, o que exige um
pacote instalável. Neste alvo o comando correto é
`pip install -r requirements.txt`, e ele era **deny**. Confirmado no A/B. O
mapeamento assumia que todo projeto pip é um pacote; a maioria dos serviços
Python não é.

**Corrigido**, e a correção começou por unificar: o mapa estava **triplicado**
em `boundary_guard`, `session_permissions` e `templates`, cada cópia com o mesmo
defeito. Agora vive em `harness/install_command.py`, e os três importam de lá —
o hook standalone inclusive, via `inspect.getsource()`.

A decisão é por **evidência**, não por um valor novo de `package_manager`: o
analyzer já grava em `package_manager.evidence` o arquivo que provou o achado, e
`pip` + `requirements*.txt` passa a render `pip install -r <arquivo>`. Criar um
`package_manager: "pip-requirements"` vazaria detalhe de layout para dentro de
uma enumeração que descreve FERRAMENTA, e quebraria todo consumidor que compara
com `"pip"`.

Verificado no alvo real: `Bash(pip install -r requirements.txt)` no
`settings.local.json`, a mesma linha no `init.sh` gerado, e **allow** no guard.

### F3 — `preflight` não lia o `repo-profile.json` (MÉDIO — CORRIGIDO)

Depois de `harness profile set test_command "python -m pytest"` — que gravou
corretamente e limpou o `unknowns` correspondente —, o `preflight` continuava
reportando `test_runner_detected: FAIL` com **a mesma instrução de fix que já
foi aplicada**. Dois comandos do mesmo produto discordando sobre o mesmo fato.
Um usuário seguindo a instrução literalmente entra em laço.

**Corrigido** com uma regra estreita de propósito: só vence a re-inferência a
entrada marcada com `MANUAL_EVIDENCE` (`"harness profile set"`), que é decisão
humana sobre o ambiente. Todo o resto do arquivo em disco continua sendo
descartado — se o repo mudou, quem manda é a análise de agora. O preflight
segue read-only: lê o arquivo, não escreve nada (coberto por teste de snapshot
da árvore).

### F4 — a nota do `profile set` prometia efeito que não existe (CORRIGIDO nesta sessão)

A nota dizia, para toda chave, *"rode `harness compile-session` para a mudança
chegar ao settings.json e ao boundary_guard"*. Falso para `test_command`:
`_collect_allowed_bash_commands` lê `verify_cmd` + extras + instalação, nunca o
`test_command` do profile. O usuário compilaria, veria o comando continuar
negado e caçaria a causa errada — a fricção que este backlog existe para matar.

Manter `test_command` fora da superfície é a decisão **certa** (quem manda lá é
o `verify_cmd` do contrato aprovado); o que estava errado era a frase. A nota
passou a ser por chave (`next_step_note`), com trava estrutural em teste para o
conjunto não divergir dos leitores da superfície.

### F5 — `harness verify` roda no Python global mesmo com `.venv` presente (MÉDIO — AVISO RESTAURADO)

```
platform win32 -- Python 3.14.2, pytest-9.1.1 -- C:\Python314\python.exe
```

O `.venv` do alvo tem pytest **9.0.2**; a execução usou o **9.1.1** global. Só
funcionou porque o `site-packages` global desta máquina por acaso tem `fastapi`
e `pydantic` — num ambiente limpo, o `verify` falharia com `ImportError` e o
agente iria depurar o código em vez do ambiente. É o cenário exato que o B3
existe para avisar, e o aviso não veio (ver F1).

**O aviso voltou**, que é o remédio desenhado — e ele voltou *pelo F1*: com o
`test_command` inferido, o check de sombra tem o que checar. No alvo real,
agora:

```
test_command_resolvable = WARNING :: o comando de teste inferido (`pytest`)
resolve para C:\Users\...\Python314\Scripts\pytest.EXE, FORA do venv do
projeto, embora exista um `pytest` dentro dele
        fix: declarar a forma explícita do venv: .venv/Scripts/pytest.exe
```

**O que foi deliberadamente NÃO feito:** ancorar o `test_command` inferido no
venv (gravar `.venv/Scripts/pytest` no profile). O `repo-profile.json` é
**versionado**, e `.venv/Scripts` x `.venv/bin` é diferença de sistema
operacional — a inferência ancorada quebraria o repo do colega de outra
plataforma. Fazer `harness verify` injetar o venv por conta própria também está
fora: ele executa o comando que o contrato aprovou, literalmente, e mudar isso
em silêncio é pior que o problema. O aviso com o fix nominal é o desenho certo,
e a regressão está fixada por teste que liga F1 e F5.

### F6 — não havia caminho para adotar o harness no meio de uma feature (BAIXO, design — CORRIGIDO)

`compile-session` recusa árvore suja para criar `contract/<slug>`. Aqui os dois
arquivos modificados **são** os `files[]` do contrato: o trabalho já estava em
andamento quando o harness foi instalado. O fluxo pressupõe instalar antes de
começar, e a mensagem de erro não oferecia saída para quem já começou — dizia
"commit ou stash" e parava aí.

**Corrigido na mensagem, não na regra** — a regra está certa: criar a branch de
contrato com sujeira de outro contexto misturaria trabalho. O que faltava era
dizer QUAIS arquivos e QUAIS são as saídas, e sobretudo dizer que **stash é o
conselho errado quando o trabalho pendente é do próprio contrato** (o stash
esconde exatamente o que o contrato existe para governar). A mensagem agora no
alvo real:

> working tree suja (…). **Sujo: frontend/app.js, frontend/styles.css.** Três
> saídas, e a escolha depende de o trabalho pendente PERTENCER ou não a este
> contrato: (1) se pertence — caso comum de quem instala o harness no meio de
> uma feature —, commite AGORA, na branch atual, e rode de novo: o
> `git switch -c contract/frontend-progress-bar` leva o commit junto, sem perder
> nada; (2) se é de outro contexto, `git stash` e retome depois; (3) se este
> repo não quer branch por contrato, desligue em
> `governance.branch_per_contract`. **NÃO stashe trabalho que é deste
> contrato** — é justamente o que ele vai governar.

### F8 — os hooks do `harness compile` lançavam `python` nu (ALTO, segurança — CORRIGIDO nesta sessão)

O `settings.local.json` que `harness compile` escreveu neste alvo contém:

```json
{ "type": "command", "command": "python \"C:\\Projetos\\miojo-simulator-3.0\\.harness\\hooks\\guard_tests.py\"" }
```

Interpretador **nu**, resolvido pelo PATH no momento da tool call, e **sem** o
sufixo `|| exit 2`. É exatamente o fail-open que o Item 1 (`hook_command()` de
`harness.hook_launcher`) existe para fechar — mas a correção foi aplicada só aos
três instaladores do `compile-session` (`boundary_guard`, `session_start`,
`stop_hook`). Os dois hooks de `compiler.py:141` ficaram para trás.

Três razões para isso ser pior do que parece:

1. **É o caminho que toda instalação percorre primeiro.** `harness compile` roda
   antes de `compile-contract`/`compile-session`; um repo pode ficar dias neste
   estado — é o estado em que o alvo está agora.
2. **Pela semântica de exit code do Claude Code, só `exit 2` bloqueia.** Um
   interpretador irresolúvel (venv desativado, PATH divergente, stub da
   Microsoft Store, que sai 9009) faz a tool call **passar** com uma linha de
   `hook error` no transcript.
3. **O `doctor` não cobre.** `_managed_hook_scripts` filtra por
   `MANAGED_HOOK_FILENAMES`, que lista só os hooks de sessão — o laudo deste
   alvo devolveu `"hooks": []` com os dois hooks instalados e vulneráveis.

**Corrigido:** `_hook_entry` passou a usar `hook_command()`, o mesmo ponto único
dos outros três, e os dois nomes entraram em `MANAGED_HOOK_FILENAMES`. A suíte
inteira continuou verde **depois** da troca — prova de que nenhum teste cobria o
formato, que é a mesma lacuna que o B2 fechou para os hooks de sessão. Foram
acrescentados os três testes que faltavam: instalação (interpretador absoluto +
sufixo), **desfecho** (script corrompido por erro de sintaxe → o comando gravado
sai 2; script ausente não discriminaria, porque o próprio Python já sai 2) e
cobertura do `doctor`.

Um efeito colateral corrigido junto: as mensagens de `interpreter_problem`/
`fail_closed_problem` mandavam rodar `harness compile-session`, que **não**
regrava estes dois hooks. Passaram a nomear os dois comandos — mandar o usuário
rodar algo que não corrige o problema dele é a mesma classe de defeito do F3.

Verificado no alvo real depois do fix:

```
"C:\Python314\python.exe" "…\.harness\hooks\guard_tests.py" || exit 2
"C:\Python314\python.exe" "…\.harness\hooks\guard_test_runner.py" || exit 2
```

com `harness doctor` reportando os dois hooks, `ok: true`, e sem entrada órfã
(o casamento por NOME DE ARQUIVO em `_merge_settings` já cobria a troca de
formato — a lição do Item 1 que aqui estava aplicada).

### F7 — `test_glob` tinha duas fontes que podiam divergir (BAIXO — CORRIGIDO)

`verification.test_glob` do `harness.yaml` alimenta `guard_tests`; `test_glob`
do `repo-profile.json` alimenta `_is_test_diff`/review. Neste alvo o primeiro
valia `tests/**/*.py` e o segundo era `null` — o mesmo conceito, protegido numa
camada e inerte na outra, sem sinal nenhum.

**Corrigido com a governança vencendo, por ESCRITA e não por aviso.**
`compile-session` reconcilia: se o `harness.yaml` declara
`verification.test_glob` e o profile diverge, o profile passa a seguir a
governança (evidência `harness.yaml (verification.test_glob)`), e a
reconciliação é reportada no JSON e em stderr. Escrever, e não só avisar, é a
leitura correta de quem manda: o `test_glob` decide o que conta como arquivo de
teste protegido, o que é política aprovada — é exatamente por isso que
`harness profile set` **recusa** essa chave. Se governança manda, ela precisa
chegar aos dois consumidores.

No alvo real a reconciliação sai como **no-op** (`test_glob_reconciled: null`),
porque com o F1 corrigido as duas fontes já concordam — que é o desfecho
desejado: o mecanismo existe para o caso em que divergem.

---

## 3. O que este dogfood NÃO mediu

O gate da onda 5 pede o número de ciclos `disable`/`enable` de uma **sessão real
do Claude Code rodando dentro do alvo**, com o `boundary_guard` interceptando as
tool calls do agente. Isto aqui foi a instalação e a bateria de decisões do
guard, executadas de fora: `friction.disable_enable_cycles` = **0**, mas com
`compile-session` = 1 e nenhuma sessão de agente. O contador está instalado e
funcionando; falta rodá-lo.

Para fechar o gate, é preciso abrir o Claude Code **dentro** de
`C:\Projetos\miojo-simulator-3.0` e trabalhar o contrato até o fim. Só então
`harness status` responde a pergunta que decide entre as posturas B e C.
