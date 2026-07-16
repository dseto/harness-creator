# Evidência — dogfood Fase 4 `dogfood-producer-reviewer` (padrão Produtor-Revisor, revisão independente real)

## TDD vermelho inicial (antes de qualquer correção)

Execução ANTES de qualquer correção (deve estar vermelha para os três facts novos):

```
Determinando os projetos a serem restaurados...
C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-227\test_contract_dogfood_producer0\cobaia\MinimumAPI\MinimumAPI.csproj : warning NU1903: O pacote 'Microsoft.OpenApi' 2.0.0 tem uma alta vulnerabilidade de gravidade conhecida, https://github.com/advisories/GHSA-v5pm-xwqc-g5wc [C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-227\test_contract_dogfood_producer0\cobaia\MinimumAPI.Tests\MinimumAPI.Tests.csproj]
C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-227\test_contract_dogfood_producer0\cobaia\MinimumAPI.Tests\MinimumAPI.Tests.csproj : warning NU1903: O pacote 'Microsoft.OpenApi' 2.0.0 tem uma alta vulnerabilidade de gravidade conhecida, https://github.com/advisories/GHSA-v5pm-xwqc-g5wc
C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-227\test_contract_dogfood_producer0\cobaia\MinimumAPI\MinimumAPI.csproj : warning NU1903: O pacote 'SQLitePCLRaw.lib.e_sqlite3' 2.1.11 tem uma alta vulnerabilidade de gravidade conhecida, https://github.com/advisories/GHSA-2m69-gcr7-jv3q [C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-227\test_contract_dogfood_producer0\cobaia\MinimumAPI.Tests\MinimumAPI.Tests.csproj]
C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-227\test_contract_dogfood_producer0\cobaia\MinimumAPI.Tests\MinimumAPI.Tests.csproj : warning NU1903: O pacote 'SQLitePCLRaw.lib.e_sqlite3' 2.1.11 tem uma alta vulnerabilidade de gravidade conhecida, https://github.com/advisories/GHSA-2m69-gcr7-jv3q
  C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-227\test_contract_dogfood_producer0\cobaia\MinimumAPI.Tests\MinimumAPI.Tests.csproj restaurado (em 254 ms).
  C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-227\test_contract_dogfood_producer0\cobaia\MinimumAPI\MinimumAPI.csproj restaurado (em 254 ms).
C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-227\test_contract_dogfood_producer0\cobaia\MinimumAPI.Tests\MinimumAPI.Tests.csproj : warning NU1903: O pacote 'Microsoft.OpenApi' 2.0.0 tem uma alta vulnerabilidade de gravidade conhecida, https://github.com/advisories/GHSA-v5pm-xwqc-g5wc
C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-227\test_contract_dogfood_producer0\cobaia\MinimumAPI.Tests\MinimumAPI.Tests.csproj : warning NU1903: O pacote 'SQLitePCLRaw.lib.e_sqlite3' 2.1.11 tem uma alta vulnerabilidade de gravidade conhecida, https://github.com/advisories/GHSA-2m69-gcr7-jv3q
C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-227\test_contract_dogfood_producer0\cobaia\MinimumAPI\MinimumAPI.csproj : warning NU1903: O pacote 'Microsoft.OpenApi' 2.0.0 tem uma alta vulnerabilidade de gravidade conhecida, https://github.com/advisories/GHSA-v5pm-xwqc-g5wc
C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-227\test_contract_dogfood_producer0\cobaia\MinimumAPI\MinimumAPI.csproj : warning NU1903: O pacote 'SQLitePCLRaw.lib.e_sqlite3' 2.1.11 tem uma alta vulnerabilidade de gravidade conhecida, https://github.com/advisories/GHSA-2m69-gcr7-jv3q
  MinimumAPI -> C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-227\test_contract_dogfood_producer0\cobaia\MinimumAPI\bin\Debug\net10.0\MinimumAPI.dll
  MinimumAPI.Tests -> C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-227\test_contract_dogfood_producer0\cobaia\MinimumAPI.Tests\bin\Debug\net10.0\MinimumAPI.Tests.dll
ExecuÃ§Ã£o de teste para C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-227\test_contract_dogfood_producer0\cobaia\MinimumAPI.Tests\bin\Debug\net10.0\MinimumAPI.Tests.dll (.NETCoreApp,Version=v10.0)
VersÃ£o do VSTest 18.0.1 (x64)

Iniciando execuÃ§Ã£o de teste, espere...
1 arquivos de teste no total corresponderam ao padrÃ£o especificado.
  Com falha MinimumAPI.Tests.CreateCustomerRequestValidatorTests.Create_email_with_plus_alias_fails [189 ms]
  Mensagem de erro:
   FluentValidation.TestHelper.ValidationTestException : Expected a validation error for property Email
  Rastreamento de pilha:
     at FluentValidation.TestHelper.TestValidationResult`1.ShouldHaveValidationError(String propertyName, Boolean shouldNormalizePropertyName) in /_/src/FluentValidation/TestHelper/TestValidationResult.cs:line 91
   at FluentValidation.TestHelper.TestValidationResult`1.ShouldHaveValidationErrorFor[TProperty](Expression`1 memberAccessor) in /_/src/FluentValidation/TestHelper/TestValidationResult.cs:line 38
   at MinimumAPI.Tests.CreateCustomerRequestValidatorTests.Create_email_with_plus_alias_fails() in C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-227\test_contract_dogfood_producer0\cobaia\MinimumAPI.Tests\CustomerValidatorTests.cs:line 44
   at System.Reflection.MethodBaseInvoker.InterpretedInvoke_Method(Object obj, IntPtr* args)
   at System.Reflection.MethodBaseInvoker.InvokeWithNoArgs(Object obj, BindingFlags invokeAttr)
  Com falha MinimumAPI.Tests.CreateCustomerRequestValidatorTests.Document_with_letters_fails [< 1 ms]
  Mensagem de erro:
   FluentValidation.TestHelper.ValidationTestException : Expected a validation error for property Document
  Rastreamento de pilha:
     at FluentValidation.TestHelper.TestValidationResult`1.ShouldHaveValidationError(String propertyName, Boolean shouldNormalizePropertyName) in /_/src/FluentValidation/TestHelper/TestValidationResult.cs:line 91
   at FluentValidation.TestHelper.TestValidationResult`1.ShouldHaveValidationErrorFor[TProperty](Expression`1 memberAccessor) in /_/src/FluentValidation/TestHelper/TestValidationResult.cs:line 38
   at MinimumAPI.Tests.CreateCustomerRequestValidatorTests.Document_with_letters_fails() in C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-227\test_contract_dogfood_producer0\cobaia\MinimumAPI.Tests\CustomerValidatorTests.cs:line 37
   at System.Reflection.MethodBaseInvoker.InterpretedInvoke_Method(Object obj, IntPtr* args)
   at System.Reflection.MethodBaseInvoker.InvokeWithNoArgs(Object obj, BindingFlags invokeAttr)
  Com falha MinimumAPI.Tests.CreateCustomerRequestValidatorTests.Update_email_with_plus_alias_fails [1 ms]
  Mensagem de erro:
   FluentValidation.TestHelper.ValidationTestException : Expected a validation error for property Email
  Rastreamento de pilha:
     at FluentValidation.TestHelper.TestValidationResult`1.ShouldHaveValidationError(String propertyName, Boolean shouldNormalizePropertyName) in /_/src/FluentValidation/TestHelper/TestValidationResult.cs:line 91
   at FluentValidation.TestHelper.TestValidationResult`1.ShouldHaveValidationErrorFor[TProperty](Expression`1 memberAccessor) in /_/src/FluentValidation/TestHelper/TestValidationResult.cs:line 38
   at MinimumAPI.Tests.CreateCustomerRequestValidatorTests.Update_email_with_plus_alias_fails() in C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-227\test_contract_dogfood_producer0\cobaia\MinimumAPI.Tests\CustomerValidatorTests.cs:line 52
   at System.Reflection.MethodBaseInvoker.InterpretedInvoke_Method(Object obj, IntPtr* args)
   at System.Reflection.MethodBaseInvoker.InvokeWithNoArgs(Object obj, BindingFlags invokeAttr)
Arquivo de resultados: C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-227\test_contract_dogfood_producer0\cobaia\TestResults\before-producer-reviewer\before-producer-reviewer.trx

Com falha! â€“ Com falha:     3, Aprovado:     3, Ignorado:     0, Total:     6, DuraÃ§Ã£o: 195 ms - MinimumAPI.Tests.dll (net10.0)

[xUnit.net 00:00:00.69]     MinimumAPI.Tests.CreateCustomerRequestValidatorTests.Create_email_with_plus_alias_fails [FAIL]
[xUnit.net 00:00:00.69]     MinimumAPI.Tests.CreateCustomerRequestValidatorTests.Document_with_letters_fails [FAIL]
[xUnit.net 00:00:00.70]     MinimumAPI.Tests.CreateCustomerRequestValidatorTests.Update_email_with_plus_alias_fails [FAIL]
```

Resultado individual (via .trx):

```
{
  "Document_with_letters_fails": "Failed",
  "Create_email_with_plus_alias_fails": "Failed",
  "Update_email_with_plus_alias_fails": "Failed"
}
```


## Mecanismo de Skip do round 1 (escolha documentada)

Escolha documentada (o bloco pedia para decidir entre marcar/comentar/skip o teste do update-path na primeira rodada, OU ainda não escrevê-lo nesta sessão): optamos por escrever os DOIS `[Fact]` desde o início (TDD vermelho real provado acima para os dois, sem Skip) e, só DEPOIS dessa prova, marcar `Update_email_with_plus_alias_fails` com `[Fact(Skip = "...")]` — mecanismo 100% controlado pelo harness Python de teste (NUNCA por uma sessão do Claude), removido de novo (`_remove_round1_skip_t02`) só entre a sessão REVISOR #1 (rejeição) e a sessão PRODUTOR #2, para que o round 2 rode o `[Fact]` de verdade e prove a correção real do UpdateCustomerRequestValidator.

Atributo aplicado:

```csharp
    [Fact(Skip = "T-02 round 1: UpdateCustomerRequestValidator ainda nao corrigido de proposito (mecanismo Skip controlado 100% pelo harness Python de teste, nunca por uma sessao do Claude - ver tests/e2e/evidence/fase4-dogfood-producer-reviewer.md)")]
    public void Update_email_with_plus_alias_fails()
```


## Time gerado (team generate)

`.harness/team/manifest.json`:

```json
{
  "pattern": "producer-reviewer",
  "mode": "subagents",
  "roles": [
    "producer",
    "reviewer"
  ],
  "max_review_iterations": 3,
  "generated_at": "2026-07-16T16:23:11.390282+00:00"
}
```

`.claude/agents/reviewer.md` — linha `tools:` (sem Edit/Write, confirmado por leitura de arquivo, não roteirizado):

```
tools: Read, Grep, Glob, Bash
```


## Sessões `claude -p` (5 no total)

### Sessão PRODUTOR #1

- `is_error`: False
- `permission_denials`: [{"tool_name": "Bash", "tool_use_id": "toolu_01Kgr6ydBmJRJCXoYEVxbXUV", "tool_input": {"command": "cd \"C:\\Users\\danie\\AppData\\Local\\Temp\\pytest-of-danie\\pytest-227\\test_contract_dogfood_producer0\\cobaia\" && echo \"EXIT:$?\" && ls .harness/evidence/T-02.json", "description": "Check last exit code and evidence file existence"}}, {"tool_name": "Edit", "tool_use_id": "toolu_01BEEhyTp6LHL9QsegycbDwA", "tool_input": {"file_path": "C:\\Users\\danie\\AppData\\Local\\Temp\\pytest-of-danie\\pytest-227\\test_contract_dogfood_producer0\\cobaia\\.harness\\feature_list.json", "old_string": "      \"passes\": false", "new_string": "      \"passes\": true", "replace_all": false}}]
- `num_turns`: 8

Últimos ~600 caracteres da resposta:

```
Denied as expected. Not retrying.

**Resultado:**

1. `dotnet test`: passou â€” 5 aprovados, 1 skip, 0 falhas.
2. `harness verify T-02`: exit_code 0, `.harness/evidence/T-02.json` criado.
3. Tentativa de marcar `passes: true`: **negada** (esperado) â€” `feature-lock: revisÃ£o do time pendente (status='in_review')`. NÃ£o insisti nem usei via alternativa.

Document rule (`Matches(@"^\d+$")`) e Email rule (`.Must(!Contains('+'))`) aplicados sÃ³ em `CreateCustomerRequestValidator`. `UpdateCustomerRequestValidator` intocado, conforme pedido. Nenhum arquivo em `MinimumAPI.Tests` alterado.
```

### Sessão REVISOR #1

- `is_error`: False
- `permission_denials`: []
- `num_turns`: 5

Últimos ~600 caracteres da resposta:

```
Rejeitado T-02. `UpdateCustomerRequestValidator` falta `.Must(email => !email.Contains('+'))` â€” sÃ³ tem `NotEmpty`/`EmailAddress`/`MaximumLength(150)`. `CreateCustomerRequestValidator` tem a regra certa (linha 18). Nota gravada, `dotnet test` rodou depois (5 passou, 1 skip).
```

### Sessão PRODUTOR #2

- `is_error`: False
- `permission_denials`: []
- `num_turns`: 5

Últimos ~600 caracteres da resposta:

```
Both green, exit 0. Verify recorded exit_code 0, evidence rewritten (T-02.json shown above). dotnet test: 6 passed, 0 failed. Gap fixed, no test files touched.
```

### Sessão REVISOR #2

- `is_error`: False
- `permission_denials`: []
- `num_turns`: 5

Últimos ~600 caracteres da resposta:

```
T-02 approved. Both validators (Create, Update) have `.Must(email => !email.Contains('+'))` â€” confirmed by direct read, lines 18/40. Iter1 rejected (Update missing), iter2 fixed, now both pass. `dotnet test` 6/6 green.
```

### Sessão PRODUTOR #3

- `is_error`: False
- `permission_denials`: []
- `num_turns`: 5

Últimos ~600 caracteres da resposta:

```
T-02 done. Evidence fresh (16:24:45), review approved iter 2, both both validators got `.Must` block on '+'. `passes` flipped falseâ†’true in feature_list.json. Legit, edit stands.
```


## Ciclo de revisão (.harness/review/T-02.json)

Histórico completo (`history`) do state machine de revisão ao final:

```json
{
  "feature_id": "T-02",
  "status": "approved",
  "iteration": 2,
  "max_iterations": 3,
  "history": [
    {
      "iteration": 1,
      "decision": "rejected",
      "note": "UpdateCustomerRequestValidator (MinimumAPI/Validators/CustomerValidators.cs) falta regra: só tem NotEmpty/EmailAddress/MaximumLength(150), sem .Must bloqueando '+'. CreateCustomerRequestValidator ok (tem o Must).",
      "at": "2026-07-16T16:24:14.634179+00:00"
    },
    {
      "iteration": 2,
      "decision": "approved",
      "note": "Confirmado por leitura direta de MinimumAPI/Validators/CustomerValidators.cs: CreateCustomerRequestValidator (linha 18) e UpdateCustomerRequestValidator (linha 40) ambos tem .Must(email => !email.Contains('+')) bloqueando alias '+'. Critério do spec.md satisfeito nos dois validators.",
      "at": "2026-07-16T16:25:09.745878+00:00"
    }
  ],
  "justification": null,
  "updated_at": "2026-07-16T16:25:09.745894+00:00"
}
```


## Feature-lock (negação com revisão pendente + aprovação final aceita)

PRODUTOR #1 — tentativa de marcar passes:true com revisão in_review, negada (`permission_denials`):

```json
[
  {
    "tool_name": "Bash",
    "tool_use_id": "toolu_01Kgr6ydBmJRJCXoYEVxbXUV",
    "tool_input": {
      "command": "cd \"C:\\Users\\danie\\AppData\\Local\\Temp\\pytest-of-danie\\pytest-227\\test_contract_dogfood_producer0\\cobaia\" && echo \"EXIT:$?\" && ls .harness/evidence/T-02.json",
      "description": "Check last exit code and evidence file existence"
    }
  },
  {
    "tool_name": "Edit",
    "tool_use_id": "toolu_01BEEhyTp6LHL9QsegycbDwA",
    "tool_input": {
      "file_path": "C:\\Users\\danie\\AppData\\Local\\Temp\\pytest-of-danie\\pytest-227\\test_contract_dogfood_producer0\\cobaia\\.harness\\feature_list.json",
      "old_string": "      \"passes\": false",
      "new_string": "      \"passes\": true",
      "replace_all": false
    }
  }
]
```

PRODUTOR #3 — estado final de `.harness/feature_list.json` (leitura direta, fora do Claude) — `passes: true` só depois de evidência + revisão aprovada:

```json
{
  "id": "T-02",
  "desc": "E-mail não pode conter alias '+'",
  "files": [
    "MinimumAPI/Validators/CustomerValidators.cs"
  ],
  "verify_cmd": "dotnet test MinimumAPI.Tests",
  "depends": [],
  "passes": true
}
```

mtime evidência (1784219085.5907025) <= mtime review (1784219109.7454593) <= mtime feature_list.json (1784219130.5709965): confirmado.


## Diff aplicado (CustomerValidators.cs)

```diff
--- a/MinimumAPI/Validators/CustomerValidators.cs
+++ b/MinimumAPI/Validators/CustomerValidators.cs
@@ -14,12 +14,14 @@
         RuleFor(x => x.Email)
             .NotEmpty().WithMessage("O e-mail é obrigatório.")
             .EmailAddress().WithMessage("O e-mail informado é inválido.")
-            .MaximumLength(150).WithMessage("O e-mail deve ter no máximo 150 caracteres.");
+            .MaximumLength(150).WithMessage("O e-mail deve ter no máximo 150 caracteres.")
+            .Must(email => !email.Contains('+')).WithMessage("O e-mail não pode conter o caractere '+'.");
 
         RuleFor(x => x.Document)
             .NotEmpty().WithMessage("O documento é obrigatório.")
             .MinimumLength(11).WithMessage("O documento deve ter pelo menos 11 caracteres.")
-            .MaximumLength(20).WithMessage("O documento deve ter no máximo 20 caracteres.");
+            .MaximumLength(20).WithMessage("O documento deve ter no máximo 20 caracteres.")
+            .Matches(@"^\d+$").WithMessage("O documento deve conter apenas dígitos.");
     }
 }
 
@@ -34,7 +36,8 @@
         RuleFor(x => x.Email)
             .NotEmpty().WithMessage("O e-mail é obrigatório.")
             .EmailAddress().WithMessage("O e-mail informado é inválido.")
-            .MaximumLength(150).WithMessage("O e-mail deve ter no máximo 150 caracteres.");
+            .MaximumLength(150).WithMessage("O e-mail deve ter no máximo 150 caracteres.")
+            .Must(email => !email.Contains('+')).WithMessage("O e-mail não pode conter o caractere '+'.");
 
         RuleFor(x => x.Document)
             .NotEmpty().WithMessage("O documento é obrigatório.")
```


## Regressão (Fases 1-3 na mesma cobaia + suíte final completa)

Execução DEPOIS de tudo (produtor-revisor completo) — zero regressão das Fases 1-3 + T-02 novo, todos Passed:

```
Determinando os projetos a serem restaurados...
C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-227\test_contract_dogfood_producer0\cobaia\MinimumAPI.Tests\MinimumAPI.Tests.csproj : warning NU1903: O pacote 'Microsoft.OpenApi' 2.0.0 tem uma alta vulnerabilidade de gravidade conhecida, https://github.com/advisories/GHSA-v5pm-xwqc-g5wc
C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-227\test_contract_dogfood_producer0\cobaia\MinimumAPI\MinimumAPI.csproj : warning NU1903: O pacote 'Microsoft.OpenApi' 2.0.0 tem uma alta vulnerabilidade de gravidade conhecida, https://github.com/advisories/GHSA-v5pm-xwqc-g5wc [C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-227\test_contract_dogfood_producer0\cobaia\MinimumAPI.Tests\MinimumAPI.Tests.csproj]
C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-227\test_contract_dogfood_producer0\cobaia\MinimumAPI.Tests\MinimumAPI.Tests.csproj : warning NU1903: O pacote 'SQLitePCLRaw.lib.e_sqlite3' 2.1.11 tem uma alta vulnerabilidade de gravidade conhecida, https://github.com/advisories/GHSA-2m69-gcr7-jv3q
C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-227\test_contract_dogfood_producer0\cobaia\MinimumAPI\MinimumAPI.csproj : warning NU1903: O pacote 'SQLitePCLRaw.lib.e_sqlite3' 2.1.11 tem uma alta vulnerabilidade de gravidade conhecida, https://github.com/advisories/GHSA-2m69-gcr7-jv3q [C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-227\test_contract_dogfood_producer0\cobaia\MinimumAPI.Tests\MinimumAPI.Tests.csproj]
  Todos os projetos estÃ£o atualizados para restauraÃ§Ã£o.
C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-227\test_contract_dogfood_producer0\cobaia\MinimumAPI.Tests\MinimumAPI.Tests.csproj : warning NU1903: O pacote 'Microsoft.OpenApi' 2.0.0 tem uma alta vulnerabilidade de gravidade conhecida, https://github.com/advisories/GHSA-v5pm-xwqc-g5wc
C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-227\test_contract_dogfood_producer0\cobaia\MinimumAPI.Tests\MinimumAPI.Tests.csproj : warning NU1903: O pacote 'SQLitePCLRaw.lib.e_sqlite3' 2.1.11 tem uma alta vulnerabilidade de gravidade conhecida, https://github.com/advisories/GHSA-2m69-gcr7-jv3q
C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-227\test_contract_dogfood_producer0\cobaia\MinimumAPI\MinimumAPI.csproj : warning NU1903: O pacote 'Microsoft.OpenApi' 2.0.0 tem uma alta vulnerabilidade de gravidade conhecida, https://github.com/advisories/GHSA-v5pm-xwqc-g5wc
C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-227\test_contract_dogfood_producer0\cobaia\MinimumAPI\MinimumAPI.csproj : warning NU1903: O pacote 'SQLitePCLRaw.lib.e_sqlite3' 2.1.11 tem uma alta vulnerabilidade de gravidade conhecida, https://github.com/advisories/GHSA-2m69-gcr7-jv3q
  MinimumAPI -> C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-227\test_contract_dogfood_producer0\cobaia\MinimumAPI\bin\Debug\net10.0\MinimumAPI.dll
  MinimumAPI.Tests -> C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-227\test_contract_dogfood_producer0\cobaia\MinimumAPI.Tests\bin\Debug\net10.0\MinimumAPI.Tests.dll
ExecuÃ§Ã£o de teste para C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-227\test_contract_dogfood_producer0\cobaia\MinimumAPI.Tests\bin\Debug\net10.0\MinimumAPI.Tests.dll (.NETCoreApp,Version=v10.0)
VersÃ£o do VSTest 18.0.1 (x64)

Iniciando execuÃ§Ã£o de teste, espere...
1 arquivos de teste no total corresponderam ao padrÃ£o especificado.
Arquivo de resultados: C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-227\test_contract_dogfood_producer0\cobaia\TestResults\after-producer-reviewer\after-producer-reviewer.trx

Aprovado!  â€“ Com falha:     0, Aprovado:     6, Ignorado:     0, Total:     6, DuraÃ§Ã£o: 25 ms - MinimumAPI.Tests.dll (net10.0)
```

Resultado individual (via .trx):

```
{
  "Valid_request_passes": "Passed",
  "Empty_name_fails": "Passed",
  "Short_document_fails": "Passed",
  "Document_with_letters_fails": "Passed",
  "Create_email_with_plus_alias_fails": "Passed",
  "Update_email_with_plus_alias_fails": "Passed"
}
```


