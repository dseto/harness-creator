"""Analyzer: leitura determinística do repo-alvo -> `.harness/repo-profile.json`.

Fase 1 do roadmap (Delegação Baseada em Contratos — ver docs/project/ROADMAP.md): antes de
qualquer contrato (`spec.md`/`Plans.md`) ser redigido, o harness precisa de
fatos sobre o projeto-alvo — linguagem, package manager, comando de teste,
convenção de arquivo de teste — cada um com **evidência** (o arquivo que
provou o achado). Regra do roadmap: dado não observado permanece incógnita,
nunca vira fato — por isso `RepoProfile.unknowns` existe ao lado dos
`Finding`, e um `test_glob` só vira Finding se casar com algo em disco de
verdade (reusa `_glob_to_regex` de `verification.tdd_loop` para não divergir
semanticamente do matching usado pelo compiler/audit).

100% determinístico: zero LLM, zero rede, apenas leitura de arquivos do
próprio repo-alvo, stdlib apenas (sem dependência nova). Este módulo cobre
somente os detectores "core": linguagem/manifest, package manager,
test_command e test_glob — lint/CI/convenções adicionais entram em tarefas
futuras, populando `RepoProfile.extras`.
"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from harness.patterns import _glob_to_regex

REPO_PROFILE_PATH = ".harness/repo-profile.json"

# Diretórios de build/vendor ignorados na varredura (mesmo conjunto de
# audit.py — não reimplementar, só espelhar o padrão já usado no repo).
_SKIP_DIRS = {".harness", ".git", "__pycache__", ".venv", "node_modules",
              "bin", "obj", "target", "dist", "build"}

# Manifest -> linguagem. package.json/pyproject.toml tratados à parte porque
# geram mais de um Finding (javascript+typescript; python via dois nomes).
_PYTHON_MANIFESTS = {"pyproject.toml", "setup.py"}
_NODE_MANIFEST = "package.json"
_TS_MANIFEST = "tsconfig.json"
_GO_MANIFEST = "go.mod"
_RUST_MANIFEST = "Cargo.toml"
_CSHARP_SUFFIXES = {".csproj", ".sln"}

_LOCKFILE_MANAGERS: dict[str, str] = {
    "package-lock.json": "npm",
    "pnpm-lock.yaml": "pnpm",
    "yarn.lock": "yarn",
    "uv.lock": "uv",
    "poetry.lock": "poetry",
}

# Candidatos de test_glob por linguagem, em ordem de prioridade — cada um
# proposto e depois VALIDADO contra o disco (candidato sem nenhum arquivo
# casando é descartado; nenhum casando -> vira unknown, nunca fato). Mais de
# um candidato por linguagem cobre convenções de teste concorrentes na mesma
# stack (ex.: TypeScript com Jest/Vitest usa "*.test.ts", Angular/Jasmine/
# Karma usa "*.spec.ts" — um repo real pode seguir qualquer uma das duas).
_TEST_GLOB_CANDIDATES_BY_LANGUAGE: dict[str, list[str]] = {
    "python": ["tests/**/*.py"],
    "javascript": ["**/*.test.ts", "**/*.spec.ts"],
    "typescript": ["**/*.test.ts", "**/*.spec.ts"],
    "csharp": ["**/*Tests.cs"],
    "go": ["**/*_test.go"],
}

# Detectores "estendidos" (populam `RepoProfile.extras`) — lint/typecheck/build,
# CI, monorepo, docker-compose e docs. Mesma regra: achado com prova vira
# Finding; ausência de sinal não é unknown (unknown é só para sinal ambíguo).
_RUFF_CONFIG_NAMES = {"ruff.toml", ".ruff.toml"}
_ESLINT_CONFIG_NAMES = {
    ".eslintrc", ".eslintrc.js", ".eslintrc.cjs", ".eslintrc.mjs",
    ".eslintrc.json", ".eslintrc.yml", ".eslintrc.yaml",
    "eslint.config.js", "eslint.config.cjs", "eslint.config.mjs", "eslint.config.ts",
}
_MYPY_CONFIG_NAMES = {"mypy.ini"}
_DOC_FILENAMES = ["README.md", "CLAUDE.md", "AGENTS.md", "CONTRIBUTING.md"]
_COMPOSE_FILENAMES = {"docker-compose.yml", "compose.yaml"}


@dataclass
class Finding:
    """Um fato observado no repo, com a prova que o sustenta."""

    value: Any
    evidence: str   # caminho relativo (POSIX) do arquivo que provou o achado
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {"value": self.value, "evidence": self.evidence, "confidence": self.confidence}

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "Finding":
        return Finding(
            value=data["value"], evidence=data["evidence"], confidence=data["confidence"]
        )


@dataclass
class RepoProfile:
    """Snapshot determinístico do repo-alvo. Serializado em
    `.harness/repo-profile.json` — fonte de fatos para o contrato da Fase 1."""

    languages: list[Finding] = field(default_factory=list)
    package_manager: Finding | None = None
    test_command: Finding | None = None
    test_glob: Finding | None = None
    extras: dict[str, Finding] = field(default_factory=dict)
    unknowns: list[str] = field(default_factory=list)
    analyzed_at: str = ""
    manifest_snapshot: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "languages": [f.to_dict() for f in self.languages],
            "package_manager": self.package_manager.to_dict() if self.package_manager else None,
            "test_command": self.test_command.to_dict() if self.test_command else None,
            "test_glob": self.test_glob.to_dict() if self.test_glob else None,
            "extras": {k: v.to_dict() for k, v in self.extras.items()},
            "unknowns": list(self.unknowns),
            "analyzed_at": self.analyzed_at,
            "manifest_snapshot": dict(self.manifest_snapshot),
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "RepoProfile":
        return RepoProfile(
            languages=[Finding.from_dict(d) for d in data.get("languages", [])],
            package_manager=(
                Finding.from_dict(data["package_manager"])
                if data.get("package_manager") else None
            ),
            test_command=(
                Finding.from_dict(data["test_command"]) if data.get("test_command") else None
            ),
            test_glob=(
                Finding.from_dict(data["test_glob"]) if data.get("test_glob") else None
            ),
            extras={k: Finding.from_dict(v) for k, v in data.get("extras", {}).items()},
            unknowns=list(data.get("unknowns", [])),
            analyzed_at=data.get("analyzed_at", ""),
            manifest_snapshot=dict(data.get("manifest_snapshot", {})),
        )


# ---------------------------------------------------------------------------
# Análise (pura — recebe Path, não escreve nada)
# ---------------------------------------------------------------------------

def analyze_project(target_dir: Path) -> RepoProfile:
    target_dir = target_dir.resolve()
    files = _list_files(target_dir)

    language_findings, manifests = _detect_languages(files)
    package_manager = _detect_package_manager(files)

    primary_language = language_findings[0].value if language_findings else None
    test_command = _detect_test_command(target_dir, primary_language, manifests, files)
    test_glob = _detect_test_glob(primary_language, files)

    unknowns: list[str] = []
    if not language_findings:
        unknowns.append("languages: nenhum manifest reconhecido")
    if package_manager is None:
        unknowns.append("package_manager: nenhum lockfile detectado")
    if test_command is None:
        unknowns.append("test_command: nenhum runner detectado")
    if test_glob is None:
        if primary_language is None:
            unknowns.append("test_glob: linguagem não detectada")
        else:
            unknowns.append(
                f"test_glob: nenhum arquivo casa a convenção de '{primary_language}'"
            )

    manifest_snapshot = _snapshot_manifests(target_dir, manifests, package_manager)

    extras: dict[str, Finding] = {}
    lint_command = _detect_lint_command(target_dir, files)
    if lint_command is not None:
        extras["lint_command"] = lint_command
    typecheck_command = _detect_typecheck_command(target_dir, files)
    if typecheck_command is not None:
        extras["typecheck_command"] = typecheck_command
    build_command = _detect_build_command(target_dir, files)
    if build_command is not None:
        extras["build_command"] = build_command
    ci = _detect_ci(files)
    if ci is not None:
        extras["ci"] = ci
    monorepo = _detect_monorepo(target_dir, files)
    if monorepo is not None:
        extras["monorepo"] = monorepo
    services = _detect_services(target_dir, files)
    if services is not None:
        extras["services"] = services
    docs = _detect_docs(files)
    if docs is not None:
        extras["docs"] = docs

    return RepoProfile(
        languages=language_findings,
        package_manager=package_manager,
        test_command=test_command,
        test_glob=test_glob,
        extras=extras,
        unknowns=unknowns,
        analyzed_at=datetime.now(timezone.utc).isoformat(),
        manifest_snapshot=manifest_snapshot,
    )


def _list_files(target_dir: Path) -> list[Path]:
    """Todos os arquivos do repo-alvo (relativos), fora de `_SKIP_DIRS`,
    ordenados por profundidade e depois alfabeticamente — garante que um
    manifest na raiz vença um homônimo dentro de um subdiretório."""
    files = []
    for p in target_dir.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(target_dir)
        if _SKIP_DIRS.intersection(rel.parts):
            continue
        files.append(rel)
    return sorted(files, key=lambda rel: (len(rel.parts), rel.as_posix()))


def _first(files: list[Path], names: set[str]) -> Path | None:
    return next((rel for rel in files if rel.name in names), None)


def _detect_languages(files: list[Path]) -> tuple[list[Finding], dict[str, Path]]:
    findings: list[Finding] = []
    manifests: dict[str, Path] = {}

    python_manifest = _first(files, _PYTHON_MANIFESTS)
    if python_manifest is not None:
        findings.append(Finding("python", python_manifest.as_posix(), 1.0))
        manifests["python"] = python_manifest

    node_manifest = _first(files, {_NODE_MANIFEST})
    if node_manifest is not None:
        findings.append(Finding("javascript", node_manifest.as_posix(), 1.0))
        manifests["javascript"] = node_manifest
        ts_manifest = _first(files, {_TS_MANIFEST})
        if ts_manifest is not None:
            findings.append(Finding("typescript", ts_manifest.as_posix(), 1.0))
            manifests["typescript"] = ts_manifest

    csharp_manifest = next((rel for rel in files if rel.suffix in _CSHARP_SUFFIXES), None)
    if csharp_manifest is not None:
        findings.append(Finding("csharp", csharp_manifest.as_posix(), 1.0))
        manifests["csharp"] = csharp_manifest

    go_manifest = _first(files, {_GO_MANIFEST})
    if go_manifest is not None:
        findings.append(Finding("go", go_manifest.as_posix(), 1.0))
        manifests["go"] = go_manifest

    rust_manifest = _first(files, {_RUST_MANIFEST})
    if rust_manifest is not None:
        findings.append(Finding("rust", rust_manifest.as_posix(), 1.0))
        manifests["rust"] = rust_manifest

    return findings, manifests


def _detect_package_manager(files: list[Path]) -> Finding | None:
    for rel in files:
        manager = _LOCKFILE_MANAGERS.get(rel.name)
        if manager is not None:
            return Finding(manager, rel.as_posix(), 1.0)
    # Nenhum lockfile: projeto Python sem lockfile usa pip por definição
    # (não existe "linguagem Python sem package manager") — inferência com
    # confidence menor que 1.0 porque não veio de um lockfile explícito.
    python_manifest = _first(files, _PYTHON_MANIFESTS)
    if python_manifest is not None:
        return Finding("pip", python_manifest.as_posix(), 0.6)
    return None


def _detect_test_command(
    target_dir: Path,
    primary_language: str | None,
    manifests: dict[str, Path],
    files: list[Path],
) -> Finding | None:
    if primary_language == "python":
        return _detect_python_test_command(target_dir, manifests.get("python"), files)
    if primary_language in ("javascript", "typescript"):
        return _detect_node_test_command(target_dir, manifests.get("javascript"))
    if primary_language == "csharp":
        manifest = manifests.get("csharp")
        return Finding("dotnet test", manifest.as_posix(), 1.0) if manifest else None
    if primary_language == "go":
        manifest = manifests.get("go")
        return Finding("go test ./...", manifest.as_posix(), 1.0) if manifest else None
    return None


def _detect_python_test_command(
    target_dir: Path, pyproject_rel: Path | None, files: list[Path]
) -> Finding | None:
    if pyproject_rel is not None and pyproject_rel.name == "pyproject.toml":
        try:
            data = tomllib.loads((target_dir / pyproject_rel).read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError):
            data = {}
        if _pyproject_mentions_pytest(data):
            return Finding("pytest", pyproject_rel.as_posix(), 1.0)

    pytest_ini = _first(files, {"pytest.ini"})
    if pytest_ini is not None:
        return Finding("pytest", pytest_ini.as_posix(), 1.0)
    return None


def _dep_name(dependency: str) -> str:
    """Nome do pacote sem especificador de versão/extras: "pytest>=8.0" -> "pytest"."""
    return re.split(r"[<>=!\[\s;]", dependency, maxsplit=1)[0].strip().lower()


def _pyproject_mentions_pytest(data: dict[str, Any]) -> bool:
    project = data.get("project", {})
    deps: list[str] = list(project.get("dependencies", []))
    for group in project.get("optional-dependencies", {}).values():
        deps.extend(group)

    tool = data.get("tool", {})
    if "ini_options" in tool.get("pytest", {}):
        return True

    poetry = tool.get("poetry", {})
    deps.extend(poetry.get("dependencies", {}).keys())
    deps.extend(poetry.get("dev-dependencies", {}).keys())
    for group in poetry.get("group", {}).values():
        deps.extend(group.get("dependencies", {}).keys())

    return any(_dep_name(dep) == "pytest" for dep in deps)


def _detect_node_test_command(target_dir: Path, package_rel: Path | None) -> Finding | None:
    if package_rel is None:
        return None
    try:
        data = json.loads((target_dir / package_rel).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    script = (data.get("scripts") or {}).get("test")
    if not script or not script.strip():
        return None
    if "no test specified" in script.lower():
        return None  # placeholder gerado por `npm init` — não é um runner real
    return Finding(script, package_rel.as_posix(), 1.0)


def _detect_test_glob(primary_language: str | None, files: list[Path]) -> Finding | None:
    if primary_language is None:
        return None
    candidates = _TEST_GLOB_CANDIDATES_BY_LANGUAGE.get(primary_language)
    if candidates is None:
        return None
    for glob in candidates:
        pattern = _glob_to_regex(glob)
        matches = sorted(rel for rel in files if pattern.match(rel.as_posix()))
        if matches:
            return Finding(glob, matches[0].as_posix(), 1.0)
    return None  # nenhum candidato casou em disco -> não vira fato


def _snapshot_manifests(
    target_dir: Path, manifests: dict[str, Path], package_manager: Finding | None
) -> dict[str, str]:
    paths: set[Path] = set(manifests.values())
    if package_manager is not None:
        paths.add(Path(package_manager.evidence))

    snapshot: dict[str, str] = {}
    for rel in sorted(paths, key=lambda p: p.as_posix()):
        content = (target_dir / rel).read_bytes()
        snapshot[rel.as_posix()] = hashlib.sha256(content).hexdigest()
    return snapshot


# ---------------------------------------------------------------------------
# Detectores estendidos (extras) — lint/typecheck/build, CI, monorepo,
# docker-compose e docs. Cada um segue a mesma regra dos detectores core:
# achado com prova -> Finding com evidence; sem sinal -> nada (não é unknown).
# ---------------------------------------------------------------------------

def _detect_lint_command(target_dir: Path, files: list[Path]) -> Finding | None:
    pyproject_rel = _first(files, {"pyproject.toml"})
    if pyproject_rel is not None:
        try:
            data = tomllib.loads((target_dir / pyproject_rel).read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError):
            data = {}
        if "ruff" in data.get("tool", {}):
            return Finding("ruff check .", pyproject_rel.as_posix(), 1.0)

    ruff_toml = _first(files, _RUFF_CONFIG_NAMES)
    if ruff_toml is not None:
        return Finding("ruff check .", ruff_toml.as_posix(), 1.0)

    eslint_config = _first(files, _ESLINT_CONFIG_NAMES)
    if eslint_config is not None:
        package_rel = _first(files, {_NODE_MANIFEST})
        if package_rel is not None:
            try:
                data = json.loads((target_dir / package_rel).read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                data = {}
            script = (data.get("scripts") or {}).get("lint")
            if script and script.strip():
                return Finding(script, package_rel.as_posix(), 1.0)
        return Finding("npx eslint .", eslint_config.as_posix(), 1.0)

    return None


def _detect_typecheck_command(target_dir: Path, files: list[Path]) -> Finding | None:
    tsconfig = _first(files, {_TS_MANIFEST})
    if tsconfig is not None:
        return Finding("npx tsc --noEmit", tsconfig.as_posix(), 1.0)

    pyproject_rel = _first(files, {"pyproject.toml"})
    if pyproject_rel is not None:
        try:
            data = tomllib.loads((target_dir / pyproject_rel).read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError):
            data = {}
        if "mypy" in data.get("tool", {}):
            return Finding("mypy", pyproject_rel.as_posix(), 1.0)

    mypy_ini = _first(files, _MYPY_CONFIG_NAMES)
    if mypy_ini is not None:
        return Finding("mypy", mypy_ini.as_posix(), 1.0)

    return None


def _detect_build_command(target_dir: Path, files: list[Path]) -> Finding | None:
    package_rel = _first(files, {_NODE_MANIFEST})
    if package_rel is not None:
        try:
            data = json.loads((target_dir / package_rel).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            data = {}
        script = (data.get("scripts") or {}).get("build")
        if script and script.strip():
            return Finding(script, package_rel.as_posix(), 1.0)

    csproj = next((rel for rel in files if rel.suffix == ".csproj"), None)
    if csproj is not None:
        return Finding("dotnet build", csproj.as_posix(), 1.0)

    go_mod = _first(files, {_GO_MANIFEST})
    if go_mod is not None:
        return Finding("go build ./...", go_mod.as_posix(), 1.0)

    return None


def _detect_ci(files: list[Path]) -> Finding | None:
    workflows = sorted(
        rel for rel in files
        if len(rel.parts) >= 3
        and rel.parts[0] == ".github"
        and rel.parts[1] == "workflows"
        and rel.suffix in (".yml", ".yaml")
    )
    if not workflows:
        return None
    return Finding([rel.name for rel in workflows], workflows[0].as_posix(), 1.0)


def _detect_monorepo(target_dir: Path, files: list[Path]) -> Finding | None:
    package_rel = _first(files, {_NODE_MANIFEST})
    if package_rel is not None:
        try:
            data = json.loads((target_dir / package_rel).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            data = {}
        if data.get("workspaces"):
            return Finding(True, package_rel.as_posix(), 1.0)

    pnpm_workspace = _first(files, {"pnpm-workspace.yaml"})
    if pnpm_workspace is not None:
        return Finding(True, pnpm_workspace.as_posix(), 1.0)

    sln = next((rel for rel in files if rel.suffix == ".sln"), None)
    if sln is not None:
        try:
            content = (target_dir / sln).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            content = ""
        csproj_refs = set(re.findall(r'[^"]+\.csproj', content))
        if len(csproj_refs) >= 2:
            return Finding(True, sln.as_posix(), 1.0)

    return None


def _detect_services(target_dir: Path, files: list[Path]) -> Finding | None:
    compose_rel = _first(files, _COMPOSE_FILENAMES)
    if compose_rel is None:
        return None
    try:
        data = yaml.safe_load((target_dir / compose_rel).read_text(encoding="utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    services = data.get("services")
    if not isinstance(services, dict) or not services:
        return None
    return Finding(sorted(services.keys()), compose_rel.as_posix(), 1.0)


def _detect_docs(files: list[Path]) -> Finding | None:
    present: list[Path] = []
    for name in _DOC_FILENAMES:
        rel = _first(files, {name})
        if rel is not None:
            present.append(rel)
    if not present:
        return None
    return Finding([rel.name for rel in present], present[0].as_posix(), 1.0)


# ---------------------------------------------------------------------------
# I/O (escreve no projeto-alvo)
# ---------------------------------------------------------------------------

def write_profile(profile: RepoProfile, target_dir: Path) -> Path:
    """Grava `.harness/repo-profile.json`, regenerado do zero a cada chamada."""
    path = target_dir.resolve() / REPO_PROFILE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(profile.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return path
