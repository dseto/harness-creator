# Relatório — Verificação dos Outcomes da Fase 1 (Delegação Baseada em Contratos)

**Data:** 2026-07-15
**Cobaia:** cópia real da cobaia .NET externa (nunca o repo original — ver confirmação na seção 6)
**Escopo:** confirmar, com prova executável e não com leitura de código, se a implementação da
Fase 1 (feita em sessão anterior) entrega os outcomes prometidos em `ROADMAP.md` para um
desenvolvedor que usa o harness para implementar uma alteração real.

---

## 1. Metodologia

Verificação em duas etapas, delegadas a subagentes com modelos diferentes para reduzir viés de
confirmação (quem analisa/escreve o teste não é quem o executa e relata):

1. **Análise + criação dos testes — Claude Fable 5.** Leu `ROADMAP.md` (seção Fase 1 + seção
   "Gate de Encerramento por Fase"), a implementação real (`src/harness/analyzer.py`,
   `src/harness/contract.py`, `src/harness/cli.py`, `skills/plan/SKILL.md`) e os precedentes de
   E2E real já existentes no repo (`tests/e2e/conftest.py`, `tests/e2e/test_headless.py`,
   `tests/e2e/test_contract_dogfood.py`). Extraiu 6 outcomes concretos e escreveu
   `tests/e2e/test_fase1_outcomes.py` — 5 testes, todos operando via subprocess da CLI real
   (`python -m harness.cli ...`), nunca import in-process, sobre uma cópia fresca da cobaia .NET
   real (fixture `api_project`). Não executou a suíte pesada — só `--collect-only` e `ruff check`.
2. **Execução real + relato — Claude Sonnet 5.** Rodou os testes de verdade (bateria barata sem
   tokens/dotnet, depois bateria cara com `claude -p` headless real), leu a evidência gerada em
   disco, investigou a causa-raiz de qualquer falha lendo o código relevante, e reportou sem
   tentar consertar nada.

Nenhum dos dois agentes editou a cobaia .NET externa (o original) — só a cópia isolada por
teste (`tmp_path`), criada pela fixture `api_project`.

## 2. Os 6 outcomes avaliados

Extraídos do `ROADMAP.md`, seção "Fase 1 — Delegação Baseada em Contratos":

1. `harness analyze --dir` produz `.harness/repo-profile.json` com achados baseados em evidência
   real do repo (não adivinhação) — cada achado aponta pro arquivo real que o provou; o que não
   foi observado vai para `unknowns[]`, nunca vira fato inventado.
2. A skill `/harness-creator:plan` usa esse profile para não reentrevistar do zero — só pergunta
   ao humano sobre os `unknowns`.
3. A skill nunca se auto-aprova: `spec.md` sai com `approved_by`/`approved_at` vazios até
   confirmação humana explícita.
4. `harness compile-contract` só gera `feature_list.json` com o contrato aprovado; sem aprovação,
   nada é escrito em disco.
5. O `feature_list.json` gerado reflete fielmente o `Plans.md` aprovado — uma entrada por tarefa,
   com `files[]`/`verify_cmd` reais.
6. Recompilar um contrato preserva `passes:true` de tarefas cuja identidade (`id`/`verify_cmd`/
   `files`) não mudou.

## 3. Resultado — tabela geral

| # | Outcome | Veredito | Custo/tempo |
|---|---|---|---|
| 1 | Profile com evidência real, unknowns honestos | ✅ **ATINGIDO** | determinístico, ~2s |
| 2 | Skill usa o profile, não reentrevista | ⚠️ **NÃO EXECUTADO** (falha de setup do teste) | ~131s, tokens reais |
| 3 | Skill nunca se auto-aprova | ⚠️ **NÃO EXECUTADO** (dependia do #2) | mesmo run do #2 |
| 4 | Gate de aprovação (compile-contract) | ✅ **ATINGIDO** | determinístico |
| 5 | `feature_list.json` fiel ao `Plans.md` | ✅ **ATINGIDO** | determinístico |
| 6 | Recompilação preserva `passes:true` por identidade | ✅ **ATINGIDO** | determinístico |

**4 de 6 outcomes confirmados com prova real. 2 continuam sem veredito** — não porque a
implementação falhou neles, mas porque o teste que deveria prová-los tem um defeito de setup
(seção 5).

## 4. Achados detalhados

### Outcome 1 — ATINGIDO

```
python -m harness.cli analyze --dir <cópia> -> exit 0
csharp: evidence = "Cobaia/Cobaia.csproj" (arquivo real confirmado em disco)
test_command: {"value": "dotnet test", ...} com evidence real
test_glob: validado contra arquivo *.Tests.cs real
package_manager: None (nenhum lockfile .NET) + entrada correspondente em unknowns[]
```

Prova de que "não-observado não virou fato": `package_manager` não foi inventado — ficou `None`
e o motivo está em `unknowns[]`, exatamente como o contrato do `analyzer.py` promete.

### Outcomes 2 e 3 — NÃO EXECUTADOS, causa-raiz identificada

O teste `test_outcomes2_3_plan_skill_uses_profile_and_never_self_approves` invoca
`claude -p ... --plugin-dir C:\Projetos\Harness-creator` numa cópia da cobaia .NET que **não tem
`.harness/harness.yaml` compilado nem `.claude/settings.json` gerado**. Sem esse baseline de
permissões, o Claude Code em modo headless (`-p`, sem TTY) nega automaticamente qualquer ação
`ask` — comportamento já documentado na docstring de `tests/e2e/test_headless.py`. Resultado:

```
is_error: False, num_turns: 27
permission_denials: 9x Bash (analyze via várias formas de invocação) + 2x Write
  (tentativas de escrever .harness/work/document-digits-only/spec.md)
-> nenhum spec.md/Plans.md chegou a existir em disco
-> AssertionError: "skill não escreveu nenhum .harness/work/<slug>/spec.md"
```

O conteúdo que a skill **tentou** escrever (visível no payload de `permission_denials`) estava
correto — frontmatter com `approved_by`/`approved_at` vazios, seção `## Unknowns` presente. Ou
seja: **o comportamento da skill parece correto**; o que faltou foi o teste dar à sessão headless
permissão suficiente para agir, algo que os dois testes headless irmãos já resolvem:

- `tests/e2e/test_headless.py` — chama `_init()` (escreve `harness.yaml`) + `compile_project()`
  antes de invocar `claude -p`.
- `tests/e2e/test_contract_dogfood.py` — vai além, usa `governance.approval_policy: auto`
  deliberadamente para permitir edição sem prompt.

`test_fase1_outcomes.py` pulou essa etapa. **Isto é um bug no teste novo, não na Fase 1** — mas
enquanto não for corrigido, os outcomes 2 e 3 permanecem sem prova real, positiva ou negativa.

### Outcomes 4, 5, 6 — ATINGIDOS

- **4:** contrato sem `approved_by`/`approved_at` → `compile-contract` exit 1, stderr contém
  "não aprovado", **zero bytes** escritos em `feature_list.json`. Preenchendo e recompilando →
  exit 0, arquivo existe.
- **5:** `feature_list.json` compilado bate **byte a byte** com o `Plans.md` de teste — 2
  features, `files`/`verify_cmd`/`depends` exatos, caminhos reais da cópia
  (`Cobaia/Validators/CustomerValidators.cs` etc.), nunca placeholder.
- **6:** marcar T-01 `passes:true` e recompilar mudando só a `desc` de T-02 preserva o
  `passes:true` de T-01 (identidade intacta). Contraprova: mudar o `verify_cmd` de T-01 zera
  `passes` — evidência antiga não vale para um comando de verificação novo.

## 5. Achado colateral — bug no writer de evidência do próprio teste novo

`test_fase1_outcomes.py` tem uma fixture `_evidence_writer` (module-scoped) que grava
`tests/e2e/evidence/fase1-outcomes-verification.md` ao fim da execução. Como os testes rodaram em
**dois processos pytest separados** (bateria barata, depois bateria cara — necessário porque só a
segunda precisa de `HARNESS_E2E_HEADLESS=1`), e o estado dos vereditos vive em memória de
processo (`_SECTIONS`, dict global no módulo), a segunda rodada sobrescreveu o arquivo inteiro —
hoje ele mostra outcomes 1/4/5/6 como "NÃO EXECUTADO", o que é falso (passaram na primeira
rodada). Os resultados reais desses quatro vêm do output de pytest capturado durante a execução,
não do arquivo em disco atualmente.

**Consequência prática:** o arquivo de evidência automático não é, hoje, confiável como fonte
única — este relatório supre essa lacuna manualmente. Fica registrado como item de correção junto
com o bug do outcome 2/3 (seção 6).

## 6. Integridade do original

```
git -C <caminho da cobaia .NET> status --short
(saída vazia)
```

Confirmado: nenhuma escrita atingiu o repo original em nenhuma das duas etapas.

## 7. Recomendação

Fase 1 está **parcialmente validada por prova real**: o núcleo mecânico do contrato (analyze →
gate de aprovação → compile → feature_list.json fiel → preservação de `passes` por identidade)
está confirmado outcome a outcome, sem ressalva. O comportamento da skill em sessão headless real
(outcomes 2 e 3 — "não reentrevista, nunca se auto-aprova") **ainda não tem prova**, positiva ou
negativa, por defeito no arnês de teste, não na implementação.

**Antes de considerar a Fase 1 fechada:**
1. Corrigir `test_outcomes2_3_...`: compilar um `harness.yaml` (`approval_policy: auto`, mesmo
   padrão de `test_contract_dogfood.py`) na cópia antes de invocar `claude -p` headless.
2. Corrigir `_evidence_writer` para acumular entre execuções (ler o `.md` existente e mesclar, em
   vez de sobrescrever seções não tocadas na rodada atual) — ou aceitar rodar tudo num único
   processo pytest (`HARNESS_E2E_HEADLESS=1` sempre setado, mesmo pra bateria barata).
3. Rerodar outcomes 2 e 3 com o setup corrigido antes de assinar a Fase 1 como pronta.
