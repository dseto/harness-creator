"""Fixtures E2E: cópia real da MinimumAPI (.NET) como projeto-cobaia.

A fonte vem de HARNESS_E2E_API_SRC (default C:/Projetos/MinimumAPI). A cópia
é reorganizada para o layout multi-projeto que um repo .NET real teria:

    <cobaia>/
    ├── MinimumAPI/          # fonte da API (sem bin/obj/db/logs)
    └── MinimumAPI.Tests/    # projeto xUnit gerado (testes dos validators)

Os testes E2E NÃO rodam `dotnet` — validam o harness (compile/audit/hooks),
que opera sobre arquivos e payloads stdin. O playground manual (script
scripts/make_playground.py) é onde `dotnet test` roda de verdade.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

API_SRC = Path(os.environ.get("HARNESS_E2E_API_SRC", "C:/Projetos/MinimumAPI"))

# Diretórios/arquivos de build e estado local que não pertencem à cobaia.
_EXCLUDE_DIRS = {"bin", "obj", ".git", ".vs"}
_EXCLUDE_SUFFIXES = {".db", ".db-shm", ".db-wal", ".log"}

TESTS_CSPROJ = """<Project Sdk="Microsoft.NET.Sdk">

  <PropertyGroup>
    <TargetFramework>net10.0</TargetFramework>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
    <IsPackable>false</IsPackable>
  </PropertyGroup>

  <ItemGroup>
    <PackageReference Include="Microsoft.NET.Test.Sdk" Version="17.11.1" />
    <PackageReference Include="xunit" Version="2.9.2" />
    <PackageReference Include="xunit.runner.visualstudio" Version="2.8.2" />
  </ItemGroup>

  <ItemGroup>
    <ProjectReference Include="..\\MinimumAPI\\MinimumAPI.csproj" />
  </ItemGroup>

</Project>
"""

VALIDATOR_TESTS_CS = """using FluentValidation.TestHelper;
using MinimumAPI.DTOs;
using MinimumAPI.Validators;
using Xunit;

namespace MinimumAPI.Tests;

public class CreateCustomerRequestValidatorTests
{
    private readonly CreateCustomerRequestValidator _validator = new();

    [Fact]
    public void Valid_request_passes()
    {
        var request = new CreateCustomerRequest("Ana", "ana@example.com", "12345678901");
        _validator.TestValidate(request).ShouldNotHaveAnyValidationErrors();
    }

    [Fact]
    public void Empty_name_fails()
    {
        var request = new CreateCustomerRequest("", "ana@example.com", "12345678901");
        _validator.TestValidate(request).ShouldHaveValidationErrorFor(x => x.Name);
    }

    [Fact]
    public void Short_document_fails()
    {
        var request = new CreateCustomerRequest("Ana", "ana@example.com", "123");
        _validator.TestValidate(request).ShouldHaveValidationErrorFor(x => x.Document);
    }
}
"""


def copy_api_source(dest_root: Path) -> Path:
    """Copia a MinimumAPI para dest_root no layout multi-projeto. Retorna a
    raiz da cobaia (dest_root)."""
    api_dest = dest_root / "MinimumAPI"

    def ignore(directory: str, names: list[str]) -> set[str]:
        skip = {n for n in names if n in _EXCLUDE_DIRS}
        skip |= {n for n in names if Path(n).suffix in _EXCLUDE_SUFFIXES}
        return skip

    shutil.copytree(API_SRC, api_dest, ignore=ignore)

    tests_dir = dest_root / "MinimumAPI.Tests"
    tests_dir.mkdir()
    (tests_dir / "MinimumAPI.Tests.csproj").write_text(TESTS_CSPROJ, encoding="utf-8")
    (tests_dir / "CustomerValidatorTests.cs").write_text(VALIDATOR_TESTS_CS, encoding="utf-8")
    return dest_root


@pytest.fixture()
def api_project(tmp_path: Path) -> Path:
    """Cobaia fresca por teste: cópia da MinimumAPI + projeto de testes xUnit."""
    if not API_SRC.is_dir():
        pytest.skip(f"MinimumAPI não encontrada em {API_SRC} (defina HARNESS_E2E_API_SRC)")
    return copy_api_source(tmp_path / "cobaia")
