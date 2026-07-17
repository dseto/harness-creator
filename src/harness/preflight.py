"""Preflight: laudo de prontidão de um repositório CRU, antes do harness.

Roda ANTES de `analyze`/`plan` — é o portão de entrada que diz se o repo tem
o mínimo para o ciclo Plan→Work→Review funcionar (git para baseline/diff/
rollback, manifest para o analyzer ter fatos, testes para o `verify_cmd`, lint
para o quality gate). Avalia 4 categorias de pré-requisitos e emite um veredito
`READY`/`READY_WITH_WARNINGS`/`NOT_READY`, cada check não-PASS carregando um
Actionable Fix concreto.

T-01 (este arquivo, primeira fatia) cobre só o NÚCLEO DE DADOS: as dataclasses
do laudo, a invariante do `fix`, a agregação de status por categoria e o
cálculo do veredito global. Os detectores (Git/manifest/tests/lint) e a
orquestração `run_preflight()` entram em T-02..T-05. O núcleo espelha
deliberadamente o padrão de `audit.py` (`Finding`/`AuditReport`): `to_dict()`/
`to_json()` com `ensure_ascii=False`, chaves JSON em inglês, mensagens/fixes
em pt-BR.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from harness.analyzer import RepoProfile, analyze_project

# Timeout (s) para cada subprocess git. Generoso: um `git status` num repo
# gigante raramente passa disso; se estourar, vira um check FAIL com a mensagem
# do timeout, nunca uma exceção não-tratada subindo do preflight.
_GIT_TIMEOUT = 10

# Ordem de severidade: quanto maior o peso, "pior" o status. Usado tanto para
# agregar o status de uma categoria (pior check vence) quanto para decidir o
# veredito global. FAIL > WARNING > PASS.
_SEVERITY = {"PASS": 0, "WARNING": 1, "FAIL": 2}
_SEVERITY_STATUS = {v: k for k, v in _SEVERITY.items()}


class PreflightError(Exception):
    """Erro de USO do preflight: alvo inexistente ou não-diretório.

    Distingue-se de um achado do laudo (repo cru é resultado normal, não erro)
    — o alvo simplesmente não pode ser avaliado. Consumido em T-04/T-05 para
    o exit code 2 do CLI.
    """


@dataclass
class PreflightCheck:
    """Um pré-requisito avaliado, com o veredito e como consertar.

    Invariante: um check não-PASS SEM `fix` seria um laudo inútil (aponta
    problema mas não a saída) — isso é bug de CONSTRUÇÃO do laudo, não do
    repo-alvo, então falha alto (`ValueError`) já na criação, não silenciosa.
    """

    code: str                 # slug estável p/ máquina (ex.: "git_repo")
    status: str               # "PASS" | "WARNING" | "FAIL"
    message: str              # frase p/ humano, pt-BR
    fix: str                  # Actionable Fix (comando/passo); vazio só se PASS
    evidence: str | None      # caminho relativo (POSIX) que provou o achado, ou None

    def __post_init__(self) -> None:
        if self.status != "PASS" and not self.fix:
            raise ValueError(
                f"check '{self.code}' com status {self.status} exige 'fix' não-vazio "
                "(todo check não-PASS deve ser acionável)"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "status": self.status,
            "message": self.message,
            "fix": self.fix,
            "evidence": self.evidence,
        }


@dataclass
class PreflightCategory:
    """Um grupo de checks de um mesmo eixo (git, manifest, tests, lint).

    O status da categoria é sempre derivado — nunca armazenado — como o PIOR
    status entre seus checks (FAIL > WARNING > PASS). Categoria sem checks é
    PASS: não há nada a reprovar (ocorre quando o curto-circuito omite checks,
    ex.: subprocess de git sem repo).
    """

    id: str
    title: str
    checks: list[PreflightCheck] = field(default_factory=list)

    @property
    def status(self) -> str:
        if not self.checks:
            return "PASS"
        worst = max(_SEVERITY[c.status] for c in self.checks)
        return _SEVERITY_STATUS[worst]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "checks": [c.to_dict() for c in self.checks],
        }


@dataclass
class PreflightReport:
    """O laudo completo: veredito global + alvo absoluto + categorias.

    Espelha `AuditReport`: `to_dict()`/`to_json()` com `ensure_ascii=False`
    (mensagens em pt-BR não devem virar `\\uXXXX`). O `verdict` é passado pronto
    (calculado por `compute_verdict`) para o report ser um valor imutável de
    apresentação, sem recomputar em cada serialização.
    """

    verdict: str              # "READY" | "READY_WITH_WARNINGS" | "NOT_READY"
    target: str               # caminho absoluto avaliado
    categories: list[PreflightCategory] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "target": self.target,
            "categories": [c.to_dict() for c in self.categories],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


def compute_verdict(categories: list[PreflightCategory]) -> str:
    """Veredito global a partir do pior status observado nas categorias.

    NOT_READY se ≥1 categoria FAIL; READY_WITH_WARNINGS se 0 FAIL e ≥1 WARNING;
    READY caso contrário (inclusive lista vazia).
    """
    statuses = {cat.status for cat in categories}
    if "FAIL" in statuses:
        return "NOT_READY"
    if "WARNING" in statuses:
        return "READY_WITH_WARNINGS"
    return "READY"


def _run_git(target_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Roda um `git <args>` read-only no alvo, capturando stdout/stderr.

    O escopo ao alvo é garantido pela PRÓPRIA função (injeta `-C <target_dir>`);
    o chamador NÃO deve passar `-C` nos `*args`.

    Nunca deixa exceção subir: qualquer falha inesperada (timeout, git some do
    PATH entre o `which` e a chamada, etc.) é traduzida em um CompletedProcess
    com returncode != 0 e a mensagem do erro em `stderr`, para o chamador
    decidir a severidade do check sem try/except espalhado.
    """
    try:
        return subprocess.run(
            ["git", "-C", str(target_dir), *args],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
            check=False,
        )
    except Exception as exc:  # noqa: BLE001 — qualquer erro vira achado, não crash
        return subprocess.CompletedProcess(
            args=["git", "-C", str(target_dir), *args], returncode=1, stdout="", stderr=str(exc)
        )


def _check_git(target_dir: Path) -> PreflightCategory:
    """Categoria 1: Controle de Versão (Git).

    Detector NOVO (o analyzer ignora `.git` de propósito). Read-only absoluto:
    só `shutil.which` + subprocess de leitura (`rev-parse`, `status --porcelain`
    com `--no-optional-locks` para o git não reescrever `.git/index`).

    Curto-circuito (regras de agregação do spec):
    - `git_binary` FAIL (git ausente do PATH): `git_repo` e `gitignore_present`
      AINDA são avaliados (não dependem do binário); só os 2 checks de
      subprocess (`git_baseline_commit`, `git_worktree_clean`) são omitidos.
    - `git_repo` FAIL (sem `.git` na raiz): `git_baseline_commit`/
      `git_worktree_clean` são omitidos (não há repo para medir);
      `gitignore_present` continua avaliado.

    Presença de repo é `(target_dir / ".git").exists()` (dir OU gitfile) —
    NUNCA `rev-parse --is-inside-work-tree`, para um mock criado dentro de
    outro repositório não passar de carona no repo-pai.
    """
    checks: list[PreflightCheck] = []

    # 1. git_binary — binário no PATH?
    git_present = shutil.which("git") is not None
    if git_present:
        checks.append(
            PreflightCheck(
                code="git_binary",
                status="PASS",
                message="binário git encontrado no PATH",
                fix="",
                evidence=None,
            )
        )
    else:
        checks.append(
            PreflightCheck(
                code="git_binary",
                status="FAIL",
                message="binário git não encontrado no PATH",
                fix="instalar o git (gerenciador de pacotes da plataforma ou https://git-scm.com/downloads)",
                evidence=None,
            )
        )

    # 2. git_repo — `.git` na raiz do alvo (dir ou gitfile).
    has_git_dir = (target_dir / ".git").exists()
    if has_git_dir:
        checks.append(
            PreflightCheck(
                code="git_repo",
                status="PASS",
                message="diretório é um repositório git",
                fix="",
                evidence=".git",
            )
        )
    else:
        checks.append(
            PreflightCheck(
                code="git_repo",
                status="FAIL",
                message="diretório não é um repositório git",
                fix="git init",
                evidence=None,
            )
        )

    # 3 e 4 — só rodam com binário E repo presentes (senão não há o que medir).
    if git_present and has_git_dir:
        # 3. git_baseline_commit — HEAD resolve? (0 commits → WARNING)
        head = _run_git(target_dir, "rev-parse", "--verify", "HEAD")
        if head.returncode == 0:
            checks.append(
                PreflightCheck(
                    code="git_baseline_commit",
                    status="PASS",
                    message="há ao menos um commit (baseline para diff/rollback)",
                    fix="",
                    evidence=None,
                )
            )
        else:
            checks.append(
                PreflightCheck(
                    code="git_baseline_commit",
                    status="WARNING",
                    message="repositório sem commits — não há baseline para diff/rollback",
                    fix='git add -A && git commit -m "baseline pré-harness"',
                    evidence=None,
                )
            )

        # 4. git_worktree_clean — `status --porcelain` vazio?
        # `--no-optional-locks` é OBRIGATÓRIA: sem ela o git reescreve
        # `.git/index` (refresh de stat-cache) como efeito colateral, violando
        # a garantia read-only do preflight.
        status = _run_git(
            target_dir,
            "--no-optional-locks",
            "status",
            "--porcelain",
        )
        if status.returncode == 0 and status.stdout.strip() == "":
            checks.append(
                PreflightCheck(
                    code="git_worktree_clean",
                    status="PASS",
                    message="árvore de trabalho limpa",
                    fix="",
                    evidence=None,
                )
            )
        elif status.returncode != 0:
            # Falha inesperada do subprocess (não o caso normal de árvore suja).
            checks.append(
                PreflightCheck(
                    code="git_worktree_clean",
                    status="FAIL",
                    message=f"falha ao consultar o estado da árvore: {status.stderr.strip() or 'erro desconhecido'}",
                    fix="verificar o repositório git manualmente (git status)",
                    evidence=None,
                )
            )
        else:
            checks.append(
                PreflightCheck(
                    code="git_worktree_clean",
                    status="WARNING",
                    message="há mudanças não-commitadas na árvore de trabalho",
                    fix="commitar ou stashear as mudanças antes de instalar o harness",
                    evidence=None,
                )
            )

    # 5. gitignore_present — `.gitignore` na raiz (independe de binário/repo).
    if (target_dir / ".gitignore").exists():
        checks.append(
            PreflightCheck(
                code="gitignore_present",
                status="PASS",
                message=".gitignore presente na raiz",
                fix="",
                evidence=".gitignore",
            )
        )
    else:
        checks.append(
            PreflightCheck(
                code="gitignore_present",
                status="WARNING",
                message=".gitignore ausente na raiz",
                fix="criar um .gitignore para a stack detectada",
                evidence=None,
            )
        )

    return PreflightCategory(
        id="git",
        title="Controle de Versão (Git)",
        checks=checks,
    )


def _language_values(profile: RepoProfile) -> set[str]:
    """Conjunto dos valores de linguagem detectados (ex.: {"python", "javascript"})."""
    return {str(finding.value) for finding in profile.languages}


def _check_manifest(profile: RepoProfile) -> PreflightCategory:
    """Categoria 2: Manifestos de Projeto Estruturados.

    Política de severidade sobre `profile.languages` (derivada de
    `analyze_project()` — NÃO reimplementa detecção de manifest). Sem nenhuma
    linguagem reconhecida → FAIL (o analyzer não tem fatos para redigir o
    contrato); caso contrário PASS com a evidência do primeiro Finding.
    """
    if not profile.languages:
        check = PreflightCheck(
            code="manifest_present",
            status="FAIL",
            message="nenhum manifest de projeto reconhecido na raiz",
            fix=(
                "criar manifest da stack (ex.: pyproject.toml, package.json, "
                "go.mod, Cargo.toml, .csproj)"
            ),
            evidence=None,
        )
    else:
        check = PreflightCheck(
            code="manifest_present",
            status="PASS",
            message="manifest de projeto reconhecido",
            fix="",
            evidence=profile.languages[0].evidence,
        )

    return PreflightCategory(
        id="manifest",
        title="Manifestos de Projeto Estruturados",
        checks=[check],
    )


def _test_runner_fix(profile: RepoProfile) -> str:
    """Actionable Fix contextual à linguagem detectada para o runner de teste."""
    languages = _language_values(profile)
    if "python" in languages:
        return (
            "declarar um runner de testes (ex.: pytest em "
            "[project.optional-dependencies] no pyproject.toml)"
        )
    if languages & {"javascript", "typescript"}:
        return 'declarar um script "test" no package.json (ex.: apontando para o runner usado)'
    return (
        "declarar um runner de testes para a stack detectada "
        "(ex.: pytest, jest/vitest, go test, dotnet test)"
    )


def _check_tests(profile: RepoProfile) -> PreflightCategory:
    """Categoria 3: Ferramentas de Verificação/TDD.

    Política de severidade sobre `profile.test_command` e `profile.test_glob`
    (ambos derivados de `analyze_project()` — NÃO reimplementa detecção).

    `test_files_present` é deliberadamente WARNING e sua message NÃO afirma
    ausência absoluta de testes: `test_glob is None` significa apenas que a
    CONVENÇÃO de testes reconhecida pelo analyzer não foi observada em disco —
    pode haver testes legítimos fora dela (ex.: `test_*.py` na raiz, que o
    pytest descobre mas o analyzer, com sua convenção fixa, não reconhece).
    """
    checks: list[PreflightCheck] = []

    # test_runner_detected — há um comando de teste declarado?
    if profile.test_command is None:
        checks.append(
            PreflightCheck(
                code="test_runner_detected",
                status="FAIL",
                message="nenhum runner de testes detectado no projeto",
                fix=_test_runner_fix(profile),
                evidence=None,
            )
        )
    else:
        checks.append(
            PreflightCheck(
                code="test_runner_detected",
                status="PASS",
                message="runner de testes detectado",
                fix="",
                evidence=profile.test_command.evidence,
            )
        )

    # test_files_present — a convenção de testes do analyzer casa algo em disco?
    if profile.test_glob is None:
        checks.append(
            PreflightCheck(
                code="test_files_present",
                status="WARNING",
                message=(
                    "convenção de testes reconhecida pelo analyzer não observada "
                    "em disco (ex.: tests/**/*.py para Python) — podem existir "
                    "testes fora dela (ex.: test_*.py na raiz) não reconhecidos "
                    "por esta convenção fixa"
                ),
                fix=(
                    "criar o primeiro teste na convenção detectável pelo analyzer "
                    "(ex.: tests/**/*.py para Python) ou mover os testes existentes "
                    "para ela"
                ),
                evidence=None,
            )
        )
    else:
        checks.append(
            PreflightCheck(
                code="test_files_present",
                status="PASS",
                message="arquivos de teste observados na convenção reconhecida",
                fix="",
                evidence=profile.test_glob.evidence,
            )
        )

    return PreflightCategory(
        id="tests",
        title="Ferramentas de Verificação/TDD",
        checks=checks,
    )


def _check_lint(profile: RepoProfile) -> PreflightCategory:
    """Categoria 4: Qualidade Estática/Linting.

    Política de severidade sobre `profile.extras["lint_command"]` (derivado de
    `analyze_project()` — NÃO reimplementa detecção). Linter ausente é WARNING
    (decisão fixada do usuário: alerta, não bloqueio); presente → PASS com a
    evidência do Finding.
    """
    lint_command = profile.extras.get("lint_command")
    if lint_command is None:
        check = PreflightCheck(
            code="linter_configured",
            status="WARNING",
            message="nenhum linter configurado para a stack detectada",
            fix=(
                "configurar linter da stack (ex.: [tool.ruff] no pyproject.toml, "
                "config do eslint)"
            ),
            evidence=None,
        )
    else:
        check = PreflightCheck(
            code="linter_configured",
            status="PASS",
            message="linter configurado",
            fix="",
            evidence=lint_command.evidence,
        )

    return PreflightCategory(
        id="lint",
        title="Qualidade Estática/Linting",
        checks=[check],
    )


def run_preflight(target_dir: Path) -> PreflightReport:
    """Função pública única: avalia o alvo e monta o laudo de prontidão.

    Valida o alvo (`PreflightError` se inexistente ou não-diretório), roda as 4
    categorias NA ORDEM contratada — git, manifest, tests, lint — e devolve um
    `PreflightReport` com `target` absoluto e veredito calculado.

    Read-only absoluto (stop condition do contrato): nenhum byte é escrito no
    alvo. `analyze_project()` é chamado UMA vez, puro (sem `write_profile`), e
    seu `RepoProfile` alimenta as categorias 2-4; a categoria 1 (`_check_git`)
    opera direto sobre `target_dir` via `shutil.which` + subprocess de leitura.
    """
    if not target_dir.exists():
        raise PreflightError(f"alvo não existe: {target_dir}")
    if not target_dir.is_dir():
        raise PreflightError(f"alvo não é um diretório: {target_dir}")

    profile = analyze_project(target_dir)

    categories = [
        _check_git(target_dir),
        _check_manifest(profile),
        _check_tests(profile),
        _check_lint(profile),
    ]

    return PreflightReport(
        verdict=compute_verdict(categories),
        target=str(target_dir.resolve()),
        categories=categories,
    )
