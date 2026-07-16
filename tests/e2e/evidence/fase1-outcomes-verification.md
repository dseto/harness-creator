# Evidência — Fase 1: verificação dos 6 outcomes

Gerado em 2026-07-16T03:07:52.465519+00:00 por `tests/e2e/test_fase1_outcomes.py` (cobaia: cópia real da MinimumAPI via fixture `api_project`).

## Outcome 1 — analyze --dir produz repo-profile.json com evidência real e unknowns honestos

Veredito: **ATINGIDO**

Comando: `python -m harness.cli analyze --dir C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-120\test_outcome1_analyze_produces0\cobaia` -> exit 0
Profile gravado em: `C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-120\test_outcome1_analyze_produces0\cobaia\.harness\repo-profile.json`
Finding csharp com evidence real: `MinimumAPI.Tests/MinimumAPI.Tests.csproj` (existe em disco: `C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-120\test_outcome1_analyze_produces0\cobaia\MinimumAPI.Tests\MinimumAPI.Tests.csproj`)
test_command: `{"value": "dotnet test", "evidence": "MinimumAPI.Tests/MinimumAPI.Tests.csproj", "confidence": 1.0}`
test_glob: `{"value": "**/*Tests.cs", "evidence": "MinimumAPI.Tests/CustomerValidatorTests.cs", "confidence": 1.0}`
unknowns[] (não-observado NÃO virou fato): `["package_manager: nenhum lockfile detectado"]`

_Atualizado em 2026-07-16T03:07:52.465519+00:00 por esta rodada._

## Outcome 2 — skill plan usa o profile como fonte de fatos (não reentrevista do zero)

Veredito: **ATINGIDO**

Baseline de permissões compilado ANTES do headless: `harness compile --dir C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-112\test_outcomes2_3_plan_skill_us0\cobaia` (policy=auto) -> exit 0, settings gravado em `C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-112\test_outcomes2_3_plan_skill_us0\cobaia\.claude\settings.json`.
Execução real: `claude -p ... --plugin-dir C:\Projetos\Harness-creator` — is_error=False, num_turns=10, permission_denials=[]
Contrato gerado pela skill: `C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-112\test_outcomes2_3_plan_skill_us0\cobaia\.harness\work\document-digits-only\spec.md` + `C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-112\test_outcomes2_3_plan_skill_us0\cobaia\.harness\work\document-digits-only\Plans.md`
verify do Plans.md rastreável ao profile (test_command=`dotnet test`).
Arquivos reais da cobaia referenciados no Plans.md: ['MinimumAPI/Validators/CustomerValidators.cs', 'MinimumAPI.Tests/CustomerValidatorTests.cs', 'MinimumAPI/Validators/CustomerValidators.cs', 'MinimumAPI.Tests/CustomerValidatorTests.cs']
Seção `## Unknowns` presente no spec.md; conteúdo:

```
- package_manager: nenhum lockfile detectado (não bloqueia esta demanda — projeto é .NET/dotnet, não usa gerenciador de pacote JS/Python).
```

_Atualizado em 2026-07-16T01:57:46.814841+00:00 por esta rodada._

## Outcome 3 — skill plan nunca se auto-aprova (approved_by/approved_at vazios)

Veredito: **ATINGIDO**

Frontmatter de `C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-112\test_outcomes2_3_plan_skill_us0\cobaia\.harness\work\document-digits-only\spec.md`: approved_by=None, approved_at=None
`compile-contract --slug document-digits-only` sobre o contrato gerado -> exit 1, stderr: `erro: contrato não aprovado — preencha approved_by/approved_at no spec.md`; feature_list.json ausente em disco.
Confirmação humana explícita SIMULADA: approved_by/approved_at reescritos no spec.md gerado pela skill -> `compile-contract --slug document-digits-only` agora -> exit 0, `C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-112\test_outcomes2_3_plan_skill_us0\cobaia\.harness\feature_list.json` existe. Prova a formulação completa do outcome 3: os campos ficam vazios ATÉ a confirmação humana, e a aprovação humana era o ÚNICO ingrediente faltando.

_Atualizado em 2026-07-16T01:57:46.814841+00:00 por esta rodada._

## Outcome 4 — compile-contract sem aprovação -> exit 1 e nada escrito em disco

Veredito: **ATINGIDO**

Sem aprovação: `compile-contract --slug fase1-outcomes` -> exit 1, stderr `erro: contrato não aprovado — preencha approved_by/approved_at no spec.md`, e NENHUM feature_list.json em disco.
Com approved_by/approved_at preenchidos: mesmo comando -> exit 0 e `C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-120\test_outcome4_approval_gate_bl0\cobaia\.harness\feature_list.json` existe.

_Atualizado em 2026-07-16T03:07:52.465519+00:00 por esta rodada._

## Outcome 5 — feature_list.json reflete fielmente o Plans.md aprovado

Veredito: **ATINGIDO**

Caminhos do Plans.md existem na cobaia: ['MinimumAPI/Validators/CustomerValidators.cs', 'MinimumAPI.Tests/CustomerValidatorTests.cs', 'MinimumAPI/Program.cs']
feature_list.json compilado (byte a byte igual ao contratado):

```json
[
  {
    "id": "T-01",
    "desc": "Documento deve conter apenas dígitos",
    "files": [
      "MinimumAPI/Validators/CustomerValidators.cs",
      "MinimumAPI.Tests/CustomerValidatorTests.cs"
    ],
    "verify_cmd": "dotnet test MinimumAPI.Tests",
    "depends": [],
    "passes": false
  },
  {
    "id": "T-02",
    "desc": "Registrar regra nova no endpoint de criação",
    "files": [
      "MinimumAPI/Program.cs"
    ],
    "verify_cmd": "dotnet build MinimumAPI",
    "depends": [
      "T-01"
    ],
    "passes": false
  }
]
```

_Atualizado em 2026-07-16T03:07:52.465519+00:00 por esta rodada._

## Outcome 6 — recompilar preserva passes:true de tarefa cuja identidade não mudou

Veredito: **ATINGIDO**

T-01 marcada `passes: true` (simulando verificação do lifecycle).
Recompilação (só desc da T-02 mudou): T-01 manteve `passes: true`.
Contraprova: mudar o verify_cmd de T-01 zerou `passes` para false (evidência antiga não vale para o novo comando).

_Atualizado em 2026-07-16T03:07:52.465519+00:00 por esta rodada._

