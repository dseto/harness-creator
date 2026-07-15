"""Cria/recria o playground manual: cópia da MinimumAPI com harness compilado.

Uso (da raiz do harness-creator):

    $env:PYTHONPATH = "src"
    python scripts/make_playground.py [--dest C:/Projetos/MinimumAPI-harness]

Reaproveita as fixtures da suíte E2E (tests/e2e/conftest.py) — mesma cópia,
mesmo projeto de testes xUnit, mesmo harness.yaml. O que a suíte automatizada
valida em tmp, o playground materializa em disco para o teste manual com
`claude --plugin-dir` (Fase 4 do plano — ver HARNESS-TEST-REPORT.md gerado).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests" / "e2e"))

from conftest import API_SRC, copy_api_source  # noqa: E402
from harness.audit import audit_project  # noqa: E402
from harness.compiler import compile_project  # noqa: E402

HARNESS_YAML = """\
governance:
  approval_policy: balanced
  budget:
    max_tokens_per_task: 500000
    max_tool_calls_per_task: 120
verification:
  enforce_tdd: true
  test_command: "dotnet test"
  test_glob: "MinimumAPI.Tests/**/*.cs"
"""

ROTEIRO = """# Roteiro de teste manual — harness na MinimumAPI

Playground gerado por `python scripts/make_playground.py`. Harness já
compilado (política `balanced`, TDD ligado). Score do audit na geração: {score}.

## Antes de começar

```powershell
cd {dest}
dotnet test          # suíte xUnit deve estar verde
```

## Sessão governada

```powershell
claude --plugin-dir C:\\Projetos\\Harness-creator
```

Casos a exercitar (marque o resultado):

| # | Peça ao Claude | Esperado | OK? |
|---|---|---|---|
| 1 | "lê o Program.cs e resume os endpoints" | roda sem prompt (read liberado) | |
| 2 | "adiciona endpoint DELETE /customers/{{id}}" | prompt de aprovação ao editar CustomerEndpoints.cs | |
| 3 | "ajusta o CustomerValidatorTests.cs" | prompt com razão TDD (hook guard_tests) | |
| 4 | "roda dotnet test" | prompt com razão TDD (hook guard_test_runner) | |
| 5 | "roda dotnet build" | SEM prompt do hook (só o ask genérico de Bash) | |
| 6 | "baixa a doc X com curl" | prompt de rede (sempre gateada) | |
| 7 | `/harness-creator:audit` | score 100 | |

Depois: edite `.harness/harness.yaml` (ex.: `approval_policy: auto`), rode
`/harness-creator:compile`, reabra a sessão e confira que editar fonte não
prompta mais — mas rede e testes continuam gateados.

Bugs encontrados → registrar como teste na suíte `tests/e2e/` do plugin.
"""


def _make_solution(dest: Path) -> None:
    """`dotnet test` da raiz precisa de .sln juntando API + Tests."""
    try:
        for cmd in (
            ["dotnet", "new", "sln", "-n", "MinimumAPI"],
            ["dotnet", "sln", "add", "MinimumAPI/MinimumAPI.csproj",
             "MinimumAPI.Tests/MinimumAPI.Tests.csproj"],
        ):
            subprocess.run(cmd, cwd=dest, check=True, capture_output=True, timeout=120)
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        print(f"aviso: .sln não criada ({exc}); rode `dotnet test MinimumAPI.Tests`")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dest", default="C:/Projetos/MinimumAPI-harness")
    args = parser.parse_args()
    dest = Path(args.dest)

    if not API_SRC.is_dir():
        sys.exit(f"erro: MinimumAPI não encontrada em {API_SRC}")
    if dest.exists():
        shutil.rmtree(dest)

    copy_api_source(dest)
    _make_solution(dest)
    yaml_path = dest / ".harness" / "harness.yaml"
    yaml_path.parent.mkdir(parents=True)
    yaml_path.write_text(HARNESS_YAML, encoding="utf-8")
    compile_project(dest)
    report = audit_project(dest)

    (dest / "HARNESS-TEST-REPORT.md").write_text(
        ROTEIRO.format(score=report.score, dest=dest), encoding="utf-8"
    )
    print(f"playground pronto em {dest} (audit score: {report.score})")
    print(f"roteiro manual: {dest / 'HARNESS-TEST-REPORT.md'}")


if __name__ == "__main__":
    main()
