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

from harness.analyzer import (
    MANUAL_EVIDENCE,
    REPO_PROFILE_PATH,
    Finding,
    RepoProfile,
    analyze_project,
)

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


# ---------------------------------------------------------------------------
# Resolubilidade do comando inferido (Item 2 do backlog do dogfood
# `Savant.Backend.APP-15167`).
#
# As categorias 2-4 checavam DECLARAÇÃO: existe manifesto, existe runner
# declarado, existe config de lint. Nenhuma checava se o comando inferido de
# fato RESOLVE no shell. No dogfood, o analyzer inferiu `pytest` a partir do
# manifesto, gravou no `repo-profile.json`, e ninguém verificou que `pytest`
# nu não está no PATH sem ativar `.venv\\Scripts` — preflight devolveu READY,
# o contrato foi compilado com um `verify_cmd` que não executa, e descobrir a
# forma correta virou tentativa-e-erro sob guard ativo (~13 ciclos
# disable/compile-session/enable).
#
# **Resolução, não execução.** A tentação era rodar o comando a seco. Isso
# violaria a stop condition documentada de `run_preflight` ("Read-only
# absoluto: nenhum byte é escrito no alvo") — `pytest` cria `.pytest_cache/`
# e `__pycache__/`, `npm test` pode tocar `node_modules/.cache`. `shutil.which`
# responde exatamente a pergunta que interessa (o binário existe e é
# executável?) com zero efeito colateral, e no Windows respeita `PATHEXT`,
# então shims `.cmd`/`.exe` (`ng`, `npm`) são encontrados — o mesmo caso que
# no backlog do elegant-heisenberg exigiu `shell=True` na execução real.
#
# **Limite conhecido e assumido:** `shutil.which` usa o PATH do processo que
# roda o preflight, que pode não ser o PATH do shell da Bash tool do agente.
# Um PASS aqui não é prova de que o agente vai conseguir rodar o comando — é
# a checagem barata que pega o caso comum e observável (venv não ativado).
# Falso-PASS reintroduz a fricção; falso-WARNING só gera um aviso a mais.
# Nunca FAIL: runner declarado porém não resolvido não impede o repo de
# receber o harness, só exige escolher a forma de invocação certa.
# ---------------------------------------------------------------------------
_VENV_DIR_NAMES = (".venv", "venv")
_VENV_BIN_DIRS = ("Scripts", "bin")
_BIN_SUFFIXES = ("", ".exe", ".cmd", ".bat")

# Lançadores que resolvem o próprio ambiente: `uv run pytest`,
# `poetry run pytest`, `tox` etc. não dependem de venv ativado, então a regra
# de ancoragem abaixo não se aplica a eles.
_ENV_MANAGER_HEADS = frozenset({
    "uv", "poetry", "pipenv", "pdm", "rye", "hatch", "tox", "nox",
})


def _command_head(command: str | None) -> str | None:
    """Primeiro token de um comando (o binário invocado), sem aspas. `None`
    para comando vazio/ausente."""
    tokens = (command or "").split()
    if not tokens:
        return None
    head = tokens[0]
    if len(head) >= 2 and head[0] == head[-1] and head[0] in ('"', "'"):
        head = head[1:-1]
    return head or None


def _venv_binary_candidates(target_dir: Path, head: str) -> list[str]:
    """Caminhos relativos (POSIX) de um binário homônimo dentro de um venv do
    próprio repo. Vazio se não houver venv ou se o binário não estiver lá.

    Serve para dois propósitos: montar um Actionable Fix com caminhos REAIS
    (não um palpite genérico) e detectar o caso de sombra descrito em
    `_command_resolution_check`."""
    found: list[str] = []
    for venv_dir in _VENV_DIR_NAMES:
        for bin_dir in _VENV_BIN_DIRS:
            base = target_dir / venv_dir / bin_dir
            if not base.is_dir():
                continue
            for suffix in _BIN_SUFFIXES:
                candidate = base / f"{head}{suffix}"
                if candidate.is_file():
                    found.append(f"{venv_dir}/{bin_dir}/{head}{suffix}")
    return found


def _repo_has_venv(target_dir: Path) -> str | None:
    """Nome do diretório de venv presente no repo (`.venv`/`venv`), ou `None`.
    Exige o diretório de binários dentro (`Scripts`/`bin`) — uma pasta `venv/`
    vazia ou de outro propósito não conta."""
    for venv_dir in _VENV_DIR_NAMES:
        for bin_dir in _VENV_BIN_DIRS:
            if (target_dir / venv_dir / bin_dir).is_dir():
                return venv_dir
    return None


def _is_venv_anchored(head: str) -> bool:
    """True se o binário invocado aponta explicitamente para dentro de um venv
    (`.venv/Scripts/pytest`, `venv/bin/pytest`, com ou sem barra invertida)."""
    parts = (head or "").replace("\\", "/").split("/")
    return any(
        part in _VENV_DIR_NAMES and parts[index + 1] in _VENV_BIN_DIRS
        for index, part in enumerate(parts[:-1])
    )


def _resolve_head(head: str, target_dir: Path) -> str | None:
    """Caminho do binário invocado, ou `None` se não for encontrado.

    Dois modos, porque `shutil.which` responde bem a só um deles:

    - **head SEM separador** (`pytest`): busca no PATH via `shutil.which` —
      respeita `PATHEXT` no Windows, então shim `.cmd`/`.exe` é encontrado.
    - **head COM separador** (`.venv/Scripts/pytest.exe`): é um caminho, não
      um nome de PATH. `shutil.which` de um caminho relativo devolve `None`
      mesmo com o arquivo existindo, o que faria o check RECUSAR justamente a
      forma que a própria mensagem de fix manda declarar — um WARNING que o
      usuário não conseguiria silenciar fazendo o que foi pedido. Aqui a
      pergunta certa é existência em disco, relativa à raiz do repo.
    """
    normalized = (head or "").replace("\\", "/")
    if "/" not in normalized:
        return shutil.which(head)

    candidate = Path(head) if Path(head).is_absolute() else target_dir / normalized
    for suffix in _BIN_SUFFIXES:
        with_suffix = candidate.with_name(candidate.name + suffix)
        if with_suffix.is_file():
            return str(with_suffix)
    return None


def _command_resolution_check(
    code: str,
    label: str,
    command: str,
    target_dir: Path,
) -> PreflightCheck:
    """Um check de resolubilidade para um comando inferido. Três desfechos:

    - binário não resolve no PATH -> WARNING, com fix listando as formas
      concretas achadas em disco (`.venv/Scripts/<bin>`, `python -m <bin>`);
    - binário resolve, mas existe homônimo dentro de um venv do repo e o
      resolvido está FORA dele -> WARNING de sombra: o comando "funciona" e
      roda o ambiente errado, que é pior que falhar alto porque falha em
      silêncio (dependência do projeto ausente, versão divergente);
    - resolve sem ambiguidade -> PASS.
    """
    head = _command_head(command)
    if head is None:
        return PreflightCheck(
            code=code,
            status="WARNING",
            message=f"{label} está declarado mas vazio",
            fix=f"declarar um {label} não-vazio no manifesto do projeto",
            evidence=None,
        )

    resolved = _resolve_head(head, target_dir)
    venv_candidates = _venv_binary_candidates(target_dir, head)

    if resolved is None:
        options = list(venv_candidates) + [f"python -m {head}"]
        return PreflightCheck(
            code=code,
            status="WARNING",
            message=(
                f"o {label} inferido (`{command}`) começa por `{head}`, que não resolve "
                "no PATH — o comando compilado para o contrato pode não executar"
            ),
            fix=(
                f"usar uma forma de invocação que resolva, e declará-la no manifesto/"
                f"perfil: {', '.join(options)}"
            ),
            evidence=None,
        )

    if venv_candidates:
        resolved_path = Path(resolved).resolve()
        inside_venv = any(
            part in _VENV_DIR_NAMES for part in resolved_path.parts
        )
        if not inside_venv:
            return PreflightCheck(
                code=code,
                status="WARNING",
                message=(
                    f"o {label} inferido (`{command}`) resolve para `{resolved}`, FORA do "
                    f"venv do projeto, embora exista um `{head}` dentro dele — o comando "
                    "roda, mas no ambiente errado (dependências do projeto ausentes ou "
                    "em versão divergente)"
                ),
                fix=(
                    f"declarar a forma explícita do venv: {', '.join(venv_candidates)} "
                    f"(ou `python -m {head}` com o venv ativado)"
                ),
                evidence=venv_candidates[0],
            )

    # B3 — o desfecho que o `which` sozinho NÃO enxerga.
    #
    # `shutil.which` responde sobre o PATH do processo que roda o preflight —
    # tipicamente o terminal do usuário, COM o venv ativado. O comando aprovado
    # aqui vai ser executado depois pela Bash tool do agente, que abre um shell
    # limpo, SEM ativação. São dois PATHs diferentes, e o check estava
    # respondendo sobre o errado: com o venv ativo, `pytest` resolve dentro do
    # venv, cai no PASS acima, e o contrato nasce com um `verify_cmd` que não
    # executa no shell do agente — exatamente a falha do dogfood que originou
    # este item, e que o desenho anterior só pegava quando o usuário rodava o
    # preflight SEM ativar o venv (isto é, só quando ele era descuidado).
    #
    # A regra abaixo não depende de qual terminal rodou o preflight: num repo
    # COM venv, só é robusto o comando ancorado nele. Lançadores que gerenciam
    # o próprio ambiente (`uv run`, `poetry run`, `tox`) ficam de fora porque
    # não dependem de ativação.
    venv_dir = _repo_has_venv(target_dir)
    if venv_dir and not _is_venv_anchored(head) and head.lower() not in _ENV_MANAGER_HEADS:
        options = list(venv_candidates) or [f"{venv_dir}/{_VENV_BIN_DIRS[0]}/{head}"]
        return PreflightCheck(
            code=code,
            status="WARNING",
            message=(
                f"o {label} inferido (`{command}`) não está ancorado no venv do "
                f"projeto (`{venv_dir}/`). Ele resolve no terminal onde o venv está "
                "ativado, mas a Bash tool do agente abre um shell SEM ativação — o "
                "comando compilado para o contrato pode não executar lá"
            ),
            fix=(
                "declarar a forma ancorada no venv, que não depende de ativação: "
                + ", ".join(options)
            ),
            evidence=venv_candidates[0] if venv_candidates else None,
        )

    return PreflightCheck(
        code=code,
        status="PASS",
        message=f"o {label} inferido (`{command}`) resolve no PATH",
        fix="",
        evidence=None,
    )


def _check_tests(profile: RepoProfile, target_dir: Path) -> PreflightCategory:
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

    # test_command_resolvable — o comando inferido de fato resolve no shell?
    # Só faz sentido quando há comando declarado; sem ele, o FAIL de
    # `test_runner_detected` acima já é o achado, e um segundo check sobre o
    # mesmo vazio seria ruído.
    if profile.test_command is not None:
        checks.append(
            _command_resolution_check(
                code="test_command_resolvable",
                label="comando de teste",
                command=str(profile.test_command.value),
                target_dir=target_dir,
            )
        )

    return PreflightCategory(
        id="tests",
        title="Ferramentas de Verificação/TDD",
        checks=checks,
    )


def _check_lint(profile: RepoProfile, target_dir: Path) -> PreflightCategory:
    """Categoria 4: Qualidade Estática/Linting.

    Política de severidade sobre `profile.extras["lint_command"]` (derivado de
    `analyze_project()` — NÃO reimplementa detecção). Linter ausente é WARNING
    (decisão fixada do usuário: alerta, não bloqueio); presente → PASS com a
    evidência do Finding.
    """
    lint_command = profile.extras.get("lint_command")
    if lint_command is None:
        checks = [
            PreflightCheck(
                code="linter_configured",
                status="WARNING",
                message="nenhum linter configurado para a stack detectada",
                fix=(
                    "configurar linter da stack (ex.: [tool.ruff] no pyproject.toml, "
                    "config do eslint)"
                ),
                evidence=None,
            )
        ]
    else:
        checks = [
            PreflightCheck(
                code="linter_configured",
                status="PASS",
                message="linter configurado",
                fix="",
                evidence=lint_command.evidence,
            ),
            # Mesma checagem de resolubilidade do comando de teste — o linter
            # entra no `verify_cmd`/quality gate pelos mesmos caminhos e sofre
            # exatamente o mesmo problema de venv (no dogfood, `ruff` foi o
            # comando que mais oscilou de forma: `.venv/Scripts/ruff` ->
            # `python -m ruff` -> de volta).
            _command_resolution_check(
                code="lint_command_resolvable",
                label="comando de lint",
                command=str(lint_command.value),
                target_dir=target_dir,
            ),
        ]

    return PreflightCategory(
        id="lint",
        title="Qualidade Estática/Linting",
        checks=checks,
    )


def _with_manual_overrides(profile: RepoProfile, target_dir: Path) -> RepoProfile:
    """Aplica sobre `profile` (recém-inferido) as entradas que um humano
    corrigiu à mão com `harness profile set`.

    Achado F3 do dogfood no MiojoSimulator 3.0: o preflight re-inferia tudo e
    ignorava o `repo-profile.json` do disco. Depois de o usuário corrigir o
    `test_command`, o laudo repetia `test_runner_detected: FAIL` **com a mesma
    instrução de fix que ele acabara de aplicar** — dois comandos do mesmo
    produto discordando sobre o mesmo fato, e um laço para quem seguir a
    instrução ao pé da letra.

    A regra é estreita de propósito: só vence a re-inferência a entrada marcada
    com `MANUAL_EVIDENCE`, que é decisão humana sobre o AMBIENTE. Todo o resto
    do arquivo em disco é inferência velha e continua sendo descartado — se o
    repo mudou, quem manda é a análise de agora. Continua read-only: lê o
    arquivo, não escreve nada.
    """
    path = target_dir / REPO_PROFILE_PATH
    if not path.is_file():
        return profile
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return profile
    if not isinstance(data, dict):
        return profile

    for key in ("package_manager", "test_command"):
        entry = data.get(key)
        if isinstance(entry, dict) and entry.get("evidence") == MANUAL_EVIDENCE:
            setattr(profile, key, Finding.from_dict(entry))

    extras = data.get("extras")
    if isinstance(extras, dict):
        for key, entry in extras.items():
            if isinstance(entry, dict) and entry.get("evidence") == MANUAL_EVIDENCE:
                profile.extras[key] = Finding.from_dict(entry)

    profile.unknowns = [
        item for item in profile.unknowns
        if not (isinstance(item, str) and item.split(":", 1)[0] in _MANUALLY_SET_KEYS(data))
    ]
    return profile


def _MANUALLY_SET_KEYS(data: dict) -> set[str]:  # noqa: N802
    """Chaves do profile em disco marcadas como correção manual."""
    keys = {
        key for key in ("package_manager", "test_command")
        if isinstance(data.get(key), dict)
        and data[key].get("evidence") == MANUAL_EVIDENCE
    }
    extras = data.get("extras")
    if isinstance(extras, dict):
        keys |= {
            key for key, entry in extras.items()
            if isinstance(entry, dict) and entry.get("evidence") == MANUAL_EVIDENCE
        }
    return keys


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

    profile = _with_manual_overrides(analyze_project(target_dir), target_dir)

    categories = [
        _check_git(target_dir),
        _check_manifest(profile),
        _check_tests(profile, target_dir),
        _check_lint(profile, target_dir),
    ]

    return PreflightReport(
        verdict=compute_verdict(categories),
        target=str(target_dir.resolve()),
        categories=categories,
    )
