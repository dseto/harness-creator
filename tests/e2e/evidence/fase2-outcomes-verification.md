# Evidência — Fase 2: verificação dos 9 outcomes

Gerado por `tests/e2e/test_fase2_outcomes.py` (repos sintéticos em tmp_path via subprocess da CLI real).

## Outcome 1 — compile-session compila permissions.allow EXATAMENTE da superfície enumerada do contrato

Veredito: **ATINGIDO**

`compile-session` num settings virgem compilou `permissions.allow` EXATAMENTE igual à superfície enumerada (47 regras: Edit/Write dos files[] das 2 tarefas sem duplicar `src/app.py`, os 2 verify_cmd distintos, lint/typecheck/build do profile, `npm ci` do package_manager, git local do ritual). Nenhum wildcard genérico.

```json
[
  "Edit(src/app.py)",
  "Write(src/app.py)",
  "Edit(tests/test_app.py)",
  "Write(tests/test_app.py)",
  "Edit(src/util.py)",
  "Write(src/util.py)",
  "Bash(pytest tests/test_app.py -q)",
  "Bash(pytest tests/test_app.py -q:*)",
  "Bash(pytest tests -q)",
  "Bash(pytest tests -q:*)",
  "Bash(ruff check .)",
  "Bash(ruff check .:*)",
  "Bash(mypy src)",
  "Bash(mypy src:*)",
  "Bash(npm run build)",
  "Bash(npm run build:*)",
  "Bash(npm ci)",
  "Bash(npm ci:*)",
  "Bash(git status)",
  "Bash(git log*)",
  "Bash(git diff*)",
  "Bash(git add*)",
  "Bash(git commit*)",
  "Bash(harness compile*)",
  "Bash(harness audit*)",
  "Bash(harness audit-runtime*)",
  "Bash(harness analyze*)",
  "Bash(harness preflight*)",
  "Bash(harness compile-contract*)",
  "Bash(harness compile-session*)",
  "Bash(harness verify*)",
  "Bash(harness team*)",
  "Bash(harness review*)",
  "Bash(harness supervise*)",
  "Bash(harness audit-team*)",
  "Bash(python -m harness.cli compile*)",
  "Bash(python -m harness.cli audit*)",
  "Bash(python -m harness.cli audit-runtime*)",
  "Bash(python -m harness.cli analyze*)",
  "Bash(python -m harness.cli preflight*)",
  "Bash(python -m harness.cli compile-contract*)",
  "Bash(python -m harness.cli compile-session*)",
  "Bash(python -m harness.cli verify*)",
  "Bash(python -m harness.cli team*)",
  "Bash(python -m harness.cli review*)",
  "Bash(python -m harness.cli supervise*)",
  "Bash(python -m harness.cli audit-team*)"
]
```
Merge não-destrutivo: regra manual `Bash(echo regra-manual)` sobreviveu à recompilação; nenhuma regra duplicada (idempotência).
Contrato encolhido (T-02 removida do Plans.md) e recompilado: `Edit/Write(src/util.py)` e `Bash(pytest tests -q)` SUMIRAM do allow (a autonomia é do tamanho do contrato ATUAL), regra manual preservada.

## Outcome 2 — runtime floor (git push/rede/segredos) NUNCA vira allow — com contrato hostil, sem contrato, ou contrato abandonado

Veredito: **ATINGIDO**

Contrato normal: nenhuma regra de `git push`/rede (curl, wget, publish, twine, gh release)/segredos (.env, .pem, id_rsa, credentials) no `permissions.allow` compilado.
Contrato HOSTIL (files[] declara `.env`; verify_cmd é `git push origin main`), aprovado e compilado com sucesso — e o boundary_guard instalado NEGA os dois mesmo assim, citando 'runtime floor' na razão: o floor é avaliado antes da superfície do contrato, então nem contrato aprovado cobrindo tudo transforma push/segredo em allow efetivo.
Observação (registrada, não é falha do outcome): com o contrato hostil o settings ecoa [] em `permissions.allow` — a camada que faz o floor valer é o hook `boundary_guard` (deny incondicional, avaliado antes das permissions), não a lista compilada.
Sem contrato ativo: `compile-session` -> exit 1 (stderr manda rodar `compile-contract` primeiro) e NENHUM `.claude/settings.local.json` é escrito — não existe política compilada sem contrato aprovado.
Contrato abandonado (feature_list.json removido após a instalação): `git push` e Write em `.env` continuam DENY (floor incondicional, avaliado ANTES da checagem de contrato); Edit em arquivo comum TAMBÉM é DENY ('nenhum contrato ativo') — default-deny sem contrato. `git status` permanece allow: a superfície de bootstrap (git local + subcomandos do harness + utilitários read-only) é o caminho de volta para recompilar o contrato sem intervenção humana.

## Outcome 3 — boundary_guard nega fora da superfície com razão legível e permite dentro do raio

Veredito: **ATINGIDO**

Edit em `src/nao_declarado.py` (fora de files[]) -> deny com razão legível que orienta o replanejamento: `arquivo fora da superficie do contrato ativo (nenhuma tarefa declara este path em files[]); artefato temporario de verificacao (screenshot, dump, HTML de debug)? salve em .harness/scratch/ ; se este arquivo PERTENCE ao escopo ja aprovado, o escape barato e `harness task add-file T-01 src/nao_declarado.py` (um comando, sem replanejar - ja liberado no guard); replaneje via /harness-creator:plan so se o ESCOPO mudou de verdade`
Bash `python scripts/deploy.py --prod` (fora de verify/lint/typecheck/build/install/git-local) -> deny com razão: `segmento 'python scripts/deploy.py --prod' fora da superficie compilada do contrato (verify_cmd/lint/typecheck/build/install/git local) e nao aceito como utilitario read-only (cat/head/tail/wc/grep/rg/ls/echo/find sem redirecionamento de escrita) nem cd intra-repo. Escapes, do mais barato ao mais caro. (1) O guard ja reconhece as formas EQUIVALENTES do que esta declarado: `python -m <bin>`, `.venv/Scripts/<bin>`, `.venv/bin/<bin>` e `uv run <bin>` valem tanto quanto o binario nu — NAO ha grafia a descobrir por tentativa e erro. (2) Este repositorio ainda nao tem `.harness/harness.yaml` com a chave `governance:` (rode /harness-creator:init para a governanca completa). Peca ao usuario para criar/editar o arquivo no terminal DELE (fora do Claude Code) com este bloco:

governance:
  extra_allowed_commands:
    - python scripts/deploy.py

Vale na tool call SEGUINTE — o guard le esse arquivo a cada chamada, sem recompilar nada. E casa por PREFIXO: essa entrada libera o comando com qualquer argumento depois dela. (3) Replaneje via /harness-creator:plan so se o ESCOPO da tarefa mudou.`
Dentro do raio, tudo allow sem prompt: Edit em files[], verify_cmd, lint/typecheck/build do profile, `git status`/`git commit` do ritual.

## Outcome 4 — arquivo que casa test_glob só é editável se declarado em files[] do contrato

Veredito: **ATINGIDO**

`tests/test_app.py` casa o test_glob E está em files[] da T-01 -> allow (razão: `arquivo de teste declarado em files[] de uma tarefa do contrato ativo`) — tarefa TDD declarada pode tocar o próprio teste.
`tests/test_other.py` casa o test_glob e NÃO está em files[] de nenhuma tarefa -> deny (razão: `arquivo de teste protegido: nenhuma tarefa do contrato ativo declara este arquivo em files[] - enfraquecimento de teste fora do escopo aprovado`) — o allow do raio não deixa o agente afrouxar teste fora do escopo aprovado.

## Outcome 5 — guard_tests.py não é gerado nem registrado; compile-session preserva outros hooks

Veredito: **ATINGIDO**

Mecanismo antigo (`harness compile`, enforce_tdd: true): nem `guard_tests.py` nem `guard_test_runner.py` são gerados/registrados em hooks.PreToolUse — o `boundary_guard.py` instalado pelo próprio `compile` cobre a mesma proteção por-tarefa e todo `Bash`, num único processo.
Após `compile-session`: nem `guard_tests.py` nem `guard_test_runner.py` aparecem em hooks.PreToolUse (nenhum dos dois chega a ser gerado), só `boundary_guard.py` registrado. Matchers finais: ['*'].
Segunda rodada de `compile-session`: uma única entrada do boundary_guard (idempotente).

## Outcome 6 — lifecycle de 17 passos como bloco gerenciado idempotente no AGENTS.md + .harness/LIFECYCLE.md

Veredito: **ATINGIDO**

AGENTS.md após `compile` (mecanismo antigo) + `compile-session`: texto humano preservado, bloco `<!-- harness:begin -->` do compiler.py byte a byte intacto, bloco `<!-- harness:lifecycle:begin -->` adicionado.
Bloco do lifecycle: 17 passos numerados (1 linha por passo), citando init/.harness/progress.md/feature_list.json/`harness reconcile`/'exatamente UMA feature pendente'/commit condicionado a `harness finish` com blockers vazio, com ponteiro de progressive disclosure para `.harness/LIFECYCLE.md`.
`.harness/LIFECYCLE.md` existe com os 17 passos detalhados (um parágrafo por passo).
Segunda rodada: um único bloco lifecycle (substituído in-place), bloco do compiler e texto humano seguem intactos.

## Outcome 7 — templates do contrato/profile: .harness/progress.md nunca sobrescrito; init.* regenerados

Veredito: **ATINGIDO**

`.harness/progress.md` gerado do contrato compilado: cabeçalho com o slug e uma linha por feature (T-01/T-02, status pending).
`.harness/init.sh`/`.harness/init.ps1` gerados do profile: instalação (`npm ci` do package_manager) + health check (`pytest tests -q` do test_command), mesmo conteúdo semântico nas duas linguagens; a raiz do projeto-alvo ficou sem `init.*` e sem `claude-progress.md`.
`.harness/progress.md` substituído por progresso real e `compile-session` re-rodado: o arquivo permaneceu byte a byte igual (nunca sobrescrito).
Profile mudado (npm -> pnpm) e recompilado: `init.sh` regenerado com `pnpm install --frozen-lockfile` (sem resto de `npm ci`), e a regra de instalação no allow acompanhou a troca.

## Outcome 8 — hook SessionStart injeta contexto real e não quebra sem git/sem contrato

Veredito: **ATINGIDO**

`compile-session` instalou `.harness/hooks/session_start.py` e registrou UMA entrada em hooks.SessionStart (matcher `startup|resume|clear` — Onda 2/T-03: não reinjeta em `compact`).
Hook invocado com payload real: `additionalContext` contém a feature pendente (`Feature ativa/pendente: T-01`), o tail do .harness/progress.md e o `git log` real (commit 'estado inicial da cobaia fase2') — a sessão nasce sabendo onde parou.
Segunda rodada de `compile-session`: continua UMA entrada em hooks.SessionStart (idempotente).
Hook apontado (via payload cwd) para diretório sem git e sem `.harness/`: exit 0, JSON válido, contexto degrada com elegância ('Nenhum contrato ativo') — não quebra a sessão.

