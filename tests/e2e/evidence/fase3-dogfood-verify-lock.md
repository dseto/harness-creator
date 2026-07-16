# Evidência — dogfood Fase 3 `dogfood-document-digits` (verify + feature-lock)

## Regressão (Fases 1/2 na mesma cobaia)

Execução DEPOIS da correção, na MESMA cobaia da Fase 3 — zero regressão dos mecanismos das Fases 1/2 (incluindo Document_with_letters_fails):

```
Determinando os projetos a serem restaurados...
C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-188\test_contract_dogfood_verify_a0\cobaia\MinimumAPI\MinimumAPI.csproj : warning NU1903: O pacote 'Microsoft.OpenApi' 2.0.0 tem uma alta vulnerabilidade de gravidade conhecida, https://github.com/advisories/GHSA-v5pm-xwqc-g5wc [C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-188\test_contract_dogfood_verify_a0\cobaia\MinimumAPI.Tests\MinimumAPI.Tests.csproj]
C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-188\test_contract_dogfood_verify_a0\cobaia\MinimumAPI.Tests\MinimumAPI.Tests.csproj : warning NU1903: O pacote 'Microsoft.OpenApi' 2.0.0 tem uma alta vulnerabilidade de gravidade conhecida, https://github.com/advisories/GHSA-v5pm-xwqc-g5wc
C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-188\test_contract_dogfood_verify_a0\cobaia\MinimumAPI\MinimumAPI.csproj : warning NU1903: O pacote 'SQLitePCLRaw.lib.e_sqlite3' 2.1.11 tem uma alta vulnerabilidade de gravidade conhecida, https://github.com/advisories/GHSA-2m69-gcr7-jv3q [C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-188\test_contract_dogfood_verify_a0\cobaia\MinimumAPI.Tests\MinimumAPI.Tests.csproj]
C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-188\test_contract_dogfood_verify_a0\cobaia\MinimumAPI.Tests\MinimumAPI.Tests.csproj : warning NU1903: O pacote 'SQLitePCLRaw.lib.e_sqlite3' 2.1.11 tem uma alta vulnerabilidade de gravidade conhecida, https://github.com/advisories/GHSA-2m69-gcr7-jv3q
  Todos os projetos estÃ£o atualizados para restauraÃ§Ã£o.
C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-188\test_contract_dogfood_verify_a0\cobaia\MinimumAPI.Tests\MinimumAPI.Tests.csproj : warning NU1903: O pacote 'Microsoft.OpenApi' 2.0.0 tem uma alta vulnerabilidade de gravidade conhecida, https://github.com/advisories/GHSA-v5pm-xwqc-g5wc
C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-188\test_contract_dogfood_verify_a0\cobaia\MinimumAPI.Tests\MinimumAPI.Tests.csproj : warning NU1903: O pacote 'SQLitePCLRaw.lib.e_sqlite3' 2.1.11 tem uma alta vulnerabilidade de gravidade conhecida, https://github.com/advisories/GHSA-2m69-gcr7-jv3q
C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-188\test_contract_dogfood_verify_a0\cobaia\MinimumAPI\MinimumAPI.csproj : warning NU1903: O pacote 'Microsoft.OpenApi' 2.0.0 tem uma alta vulnerabilidade de gravidade conhecida, https://github.com/advisories/GHSA-v5pm-xwqc-g5wc
C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-188\test_contract_dogfood_verify_a0\cobaia\MinimumAPI\MinimumAPI.csproj : warning NU1903: O pacote 'SQLitePCLRaw.lib.e_sqlite3' 2.1.11 tem uma alta vulnerabilidade de gravidade conhecida, https://github.com/advisories/GHSA-2m69-gcr7-jv3q
  MinimumAPI -> C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-188\test_contract_dogfood_verify_a0\cobaia\MinimumAPI\bin\Debug\net10.0\MinimumAPI.dll
  MinimumAPI.Tests -> C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-188\test_contract_dogfood_verify_a0\cobaia\MinimumAPI.Tests\bin\Debug\net10.0\MinimumAPI.Tests.dll
ExecuÃ§Ã£o de teste para C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-188\test_contract_dogfood_verify_a0\cobaia\MinimumAPI.Tests\bin\Debug\net10.0\MinimumAPI.Tests.dll (.NETCoreApp,Version=v10.0)
VersÃ£o do VSTest 18.0.1 (x64)

Iniciando execuÃ§Ã£o de teste, espere...
1 arquivos de teste no total corresponderam ao padrÃ£o especificado.
Arquivo de resultados: C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-188\test_contract_dogfood_verify_a0\cobaia\TestResults\after-verify-lock\after-verify-lock.trx

Aprovado!  â€“ Com falha:     0, Aprovado:     4, Ignorado:     0, Total:     4, DuraÃ§Ã£o: 35 ms - MinimumAPI.Tests.dll (net10.0)
```

Resultado individual (via .trx):

```
{
  "Valid_request_passes": "Passed",
  "Empty_name_fails": "Passed",
  "Short_document_fails": "Passed"
}
```


## Verify real (harness verify T-01)

Evidência gravada pelo próprio Claude em `.harness/evidence/T-01.json`:

```json
{
  "feature_id": "T-01",
  "verify_cmd": "dotnet test MinimumAPI.Tests",
  "recorded_at": "2026-07-16T11:11:15.101841+00:00",
  "exit_code": 0,
  "files_hash": "sha256:a851197a484bb7985725a2159ce448c69e3007e776437ebf1eaaad960770bbe2"
}
```

`files_hash` recalculado de fora do Claude sobre ['MinimumAPI/Validators/CustomerValidators.cs'] bate com o gravado: True


## Feature-lock (negação prematura + permissão legítima)

Campo estruturado `permission_denials` do JSON de saída do `claude -p` (prova real da negação da tentativa prematura; o texto da resposta NÃO é usado como evidência):

```json
[
  {
    "tool_name": "Edit",
    "tool_use_id": "toolu_01EM3Cke6vR9EEnbicrjepqk",
    "tool_input": {
      "file_path": "C:\\Users\\danie\\AppData\\Local\\Temp\\pytest-of-danie\\pytest-188\\test_contract_dogfood_verify_a0\\cobaia\\.harness\\feature_list.json",
      "old_string": "      \"passes\": false",
      "new_string": "      \"passes\": true",
      "replace_all": false
    }
  }
]
```

Estado final de `.harness/feature_list.json` (leitura direta, fora do Claude) — `passes: true` só depois da evidência real:

```json
{
  "id": "T-01",
  "desc": "Documento deve conter apenas dígitos",
  "files": [
    "MinimumAPI/Validators/CustomerValidators.cs"
  ],
  "verify_cmd": "dotnet test MinimumAPI.Tests",
  "depends": [],
  "passes": true
}
```

mtime feature_list.json (1784200282.776518) >= mtime evidência (1784200275.101763): confirmado.


## Diff aplicado (T-01)

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
- `permission_denials`: [{"tool_name": "Edit", "tool_use_id": "toolu_01EM3Cke6vR9EEnbicrjepqk", "tool_input": {"file_path": "C:\\Users\\danie\\AppData\\Local\\Temp\\pytest-of-danie\\pytest-188\\test_contract_dogfood_verify_a0\\cobaia\\.harness\\feature_list.json", "old_string": "      \"passes\": false", "new_string": "      \"passes\": true", "replace_all": false}}]
- `num_turns`: 8

Últimos ~800 caracteres da resposta:

```
Aceito segunda vez. Resumo:

1. **EdiÃ§Ã£o cÃ³digo** â€” `.Matches(@"^\d+$")` add no `RuleFor(x => x.Document)` de `CreateCustomerRequestValidator`. `dotnet test` 4/4 verde, incl `Document_with_letters_fails`.
2. **1Âª tentativa feature_list.json** (prematura) â€” negada, como esperado: `feature-lock: transicao para passes:true sem evidencia fresca`. NÃ£o insisti.
3. **verify + dotnet test** â€” exit 0. EvidÃªncia gravada em `.harness/evidence/T-01.json` (hash `sha256:a851197a...`). Teste 4/4 verde de novo.
4. **2Âª tentativa feature_list.json** (legÃ­tima, pÃ³s-evidÃªncia) â€” aceita, `passes: true`.
```


