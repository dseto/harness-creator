# Evidência — dogfood `dogfood-document-digits`

## Regressão (testes pré-existentes)

Execução ANTES da correção (deve estar vermelha):

```
Determinando os projetos a serem restaurados...
C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-99\test_contract_dogfood_document0\cobaia\MinimumAPI.Tests\MinimumAPI.Tests.csproj : warning NU1903: O pacote 'Microsoft.OpenApi' 2.0.0 tem uma alta vulnerabilidade de gravidade conhecida, https://github.com/advisories/GHSA-v5pm-xwqc-g5wc
C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-99\test_contract_dogfood_document0\cobaia\MinimumAPI\MinimumAPI.csproj : warning NU1903: O pacote 'Microsoft.OpenApi' 2.0.0 tem uma alta vulnerabilidade de gravidade conhecida, https://github.com/advisories/GHSA-v5pm-xwqc-g5wc [C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-99\test_contract_dogfood_document0\cobaia\MinimumAPI.Tests\MinimumAPI.Tests.csproj]
C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-99\test_contract_dogfood_document0\cobaia\MinimumAPI.Tests\MinimumAPI.Tests.csproj : warning NU1903: O pacote 'SQLitePCLRaw.lib.e_sqlite3' 2.1.11 tem uma alta vulnerabilidade de gravidade conhecida, https://github.com/advisories/GHSA-2m69-gcr7-jv3q
C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-99\test_contract_dogfood_document0\cobaia\MinimumAPI\MinimumAPI.csproj : warning NU1903: O pacote 'SQLitePCLRaw.lib.e_sqlite3' 2.1.11 tem uma alta vulnerabilidade de gravidade conhecida, https://github.com/advisories/GHSA-2m69-gcr7-jv3q [C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-99\test_contract_dogfood_document0\cobaia\MinimumAPI.Tests\MinimumAPI.Tests.csproj]
  C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-99\test_contract_dogfood_document0\cobaia\MinimumAPI\MinimumAPI.csproj restaurado (em 262 ms).
  C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-99\test_contract_dogfood_document0\cobaia\MinimumAPI.Tests\MinimumAPI.Tests.csproj restaurado (em 262 ms).
C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-99\test_contract_dogfood_document0\cobaia\MinimumAPI.Tests\MinimumAPI.Tests.csproj : warning NU1903: O pacote 'Microsoft.OpenApi' 2.0.0 tem uma alta vulnerabilidade de gravidade conhecida, https://github.com/advisories/GHSA-v5pm-xwqc-g5wc
C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-99\test_contract_dogfood_document0\cobaia\MinimumAPI.Tests\MinimumAPI.Tests.csproj : warning NU1903: O pacote 'SQLitePCLRaw.lib.e_sqlite3' 2.1.11 tem uma alta vulnerabilidade de gravidade conhecida, https://github.com/advisories/GHSA-2m69-gcr7-jv3q
C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-99\test_contract_dogfood_document0\cobaia\MinimumAPI\MinimumAPI.csproj : warning NU1903: O pacote 'Microsoft.OpenApi' 2.0.0 tem uma alta vulnerabilidade de gravidade conhecida, https://github.com/advisories/GHSA-v5pm-xwqc-g5wc
C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-99\test_contract_dogfood_document0\cobaia\MinimumAPI\MinimumAPI.csproj : warning NU1903: O pacote 'SQLitePCLRaw.lib.e_sqlite3' 2.1.11 tem uma alta vulnerabilidade de gravidade conhecida, https://github.com/advisories/GHSA-2m69-gcr7-jv3q
  MinimumAPI -> C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-99\test_contract_dogfood_document0\cobaia\MinimumAPI\bin\Debug\net10.0\MinimumAPI.dll
  MinimumAPI.Tests -> C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-99\test_contract_dogfood_document0\cobaia\MinimumAPI.Tests\bin\Debug\net10.0\MinimumAPI.Tests.dll
ExecuÃ§Ã£o de teste para C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-99\test_contract_dogfood_document0\cobaia\MinimumAPI.Tests\bin\Debug\net10.0\MinimumAPI.Tests.dll (.NETCoreApp,Version=v10.0)
VersÃ£o do VSTest 18.0.1 (x64)

Iniciando execuÃ§Ã£o de teste, espere...
1 arquivos de teste no total corresponderam ao padrÃ£o especificado.
  Com falha MinimumAPI.Tests.CreateCustomerRequestValidatorTests.Document_with_letters_fails [1 ms]
  Mensagem de erro:
   FluentValidation.TestHelper.ValidationTestException : Expected a validation error for property Document
  Rastreamento de pilha:
     at FluentValidation.TestHelper.TestValidationResult`1.ShouldHaveValidationError(String propertyName, Boolean shouldNormalizePropertyName) in /_/src/FluentValidation/TestHelper/TestValidationResult.cs:line 91
   at FluentValidation.TestHelper.TestValidationResult`1.ShouldHaveValidationErrorFor[TProperty](Expression`1 memberAccessor) in /_/src/FluentValidation/TestHelper/TestValidationResult.cs:line 38
   at MinimumAPI.Tests.CreateCustomerRequestValidatorTests.Document_with_letters_fails() in C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-99\test_contract_dogfood_document0\cobaia\MinimumAPI.Tests\CustomerValidatorTests.cs:line 37
   at System.Reflection.MethodBaseInvoker.InterpretedInvoke_Method(Object obj, IntPtr* args)
   at System.Reflection.RuntimeMethodInfo.Invoke(Object obj, BindingFlags invokeAttr, Binder binder, Object[] parameters, CultureInfo culture)
Arquivo de resultados: C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-99\test_contract_dogfood_document0\cobaia\TestResults\before\before.trx

Com falha! â€“ Com falha:     1, Aprovado:     3, Ignorado:     0, Total:     4, DuraÃ§Ã£o: 367 ms - MinimumAPI.Tests.dll (net10.0)

[xUnit.net 00:00:01.06]     MinimumAPI.Tests.CreateCustomerRequestValidatorTests.Document_with_letters_fails [FAIL]
```

Resultado individual (via .trx) depois da correção — zero regressão:

```
{
  "Valid_request_passes": "Passed",
  "Empty_name_fails": "Passed",
  "Short_document_fails": "Passed"
}
```


## Nova funcionalidade

Execução DEPOIS da correção (deve estar verde, incluindo Document_with_letters_fails):

```
Determinando os projetos a serem restaurados...
C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-99\test_contract_dogfood_document0\cobaia\MinimumAPI.Tests\MinimumAPI.Tests.csproj : warning NU1903: O pacote 'Microsoft.OpenApi' 2.0.0 tem uma alta vulnerabilidade de gravidade conhecida, https://github.com/advisories/GHSA-v5pm-xwqc-g5wc
C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-99\test_contract_dogfood_document0\cobaia\MinimumAPI\MinimumAPI.csproj : warning NU1903: O pacote 'Microsoft.OpenApi' 2.0.0 tem uma alta vulnerabilidade de gravidade conhecida, https://github.com/advisories/GHSA-v5pm-xwqc-g5wc [C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-99\test_contract_dogfood_document0\cobaia\MinimumAPI.Tests\MinimumAPI.Tests.csproj]
C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-99\test_contract_dogfood_document0\cobaia\MinimumAPI\MinimumAPI.csproj : warning NU1903: O pacote 'SQLitePCLRaw.lib.e_sqlite3' 2.1.11 tem uma alta vulnerabilidade de gravidade conhecida, https://github.com/advisories/GHSA-2m69-gcr7-jv3q [C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-99\test_contract_dogfood_document0\cobaia\MinimumAPI.Tests\MinimumAPI.Tests.csproj]
C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-99\test_contract_dogfood_document0\cobaia\MinimumAPI.Tests\MinimumAPI.Tests.csproj : warning NU1903: O pacote 'SQLitePCLRaw.lib.e_sqlite3' 2.1.11 tem uma alta vulnerabilidade de gravidade conhecida, https://github.com/advisories/GHSA-2m69-gcr7-jv3q
  Todos os projetos estÃ£o atualizados para restauraÃ§Ã£o.
C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-99\test_contract_dogfood_document0\cobaia\MinimumAPI.Tests\MinimumAPI.Tests.csproj : warning NU1903: O pacote 'Microsoft.OpenApi' 2.0.0 tem uma alta vulnerabilidade de gravidade conhecida, https://github.com/advisories/GHSA-v5pm-xwqc-g5wc
C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-99\test_contract_dogfood_document0\cobaia\MinimumAPI.Tests\MinimumAPI.Tests.csproj : warning NU1903: O pacote 'SQLitePCLRaw.lib.e_sqlite3' 2.1.11 tem uma alta vulnerabilidade de gravidade conhecida, https://github.com/advisories/GHSA-2m69-gcr7-jv3q
C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-99\test_contract_dogfood_document0\cobaia\MinimumAPI\MinimumAPI.csproj : warning NU1903: O pacote 'Microsoft.OpenApi' 2.0.0 tem uma alta vulnerabilidade de gravidade conhecida, https://github.com/advisories/GHSA-v5pm-xwqc-g5wc
C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-99\test_contract_dogfood_document0\cobaia\MinimumAPI\MinimumAPI.csproj : warning NU1903: O pacote 'SQLitePCLRaw.lib.e_sqlite3' 2.1.11 tem uma alta vulnerabilidade de gravidade conhecida, https://github.com/advisories/GHSA-2m69-gcr7-jv3q
  MinimumAPI -> C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-99\test_contract_dogfood_document0\cobaia\MinimumAPI\bin\Debug\net10.0\MinimumAPI.dll
  MinimumAPI.Tests -> C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-99\test_contract_dogfood_document0\cobaia\MinimumAPI.Tests\bin\Debug\net10.0\MinimumAPI.Tests.dll
ExecuÃ§Ã£o de teste para C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-99\test_contract_dogfood_document0\cobaia\MinimumAPI.Tests\bin\Debug\net10.0\MinimumAPI.Tests.dll (.NETCoreApp,Version=v10.0)
VersÃ£o do VSTest 18.0.1 (x64)

Iniciando execuÃ§Ã£o de teste, espere...
1 arquivos de teste no total corresponderam ao padrÃ£o especificado.
Arquivo de resultados: C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-99\test_contract_dogfood_document0\cobaia\TestResults\after\after.trx

Aprovado!  â€“ Com falha:     0, Aprovado:     4, Ignorado:     0, Total:     4, DuraÃ§Ã£o: 40 ms - MinimumAPI.Tests.dll (net10.0)
```


## Diff aplicado

```diff
--- a/MinimumAPI/Validators/CustomerValidators.cs
+++ b/MinimumAPI/Validators/CustomerValidators.cs
@@ -19,7 +19,8 @@
         RuleFor(x => x.Document)
             .NotEmpty().WithMessage("O documento é obrigatório.")
             .MinimumLength(11).WithMessage("O documento deve ter pelo menos 11 caracteres.")
-            .MaximumLength(20).WithMessage("O documento deve ter no máximo 20 caracteres.");
+            .MaximumLength(20).WithMessage("O documento deve ter no máximo 20 caracteres.")
+            .Matches(@"^\d+$").WithMessage("O documento deve conter apenas dígitos.");
     }
 }
 
```


## Execução do agente

- `is_error`: False
- `permission_denials`: []
- `num_turns`: 6

Últimos ~500 caracteres da resposta:

```
4 pass, 0 fail. Task done.
```


