"""E2E: verificação independente dos 8 outcomes prometidos pela Fase 2 do
ROADMAP.md ("Execução Autônoma no Raio de Impacto"), provados contra o código
REAL via subprocess da CLI (`python -m harness.cli ...`) em repos sintéticos
`tmp_path` — nunca por import in-process, nunca por confiança em relatório de
implementação.

Camada de verificação INDEPENDENTE de `test_boundary_flow.py` (o E2E sintético
escrito junto com a implementação): os cenários aqui são deliberadamente
diferentes — profile com extras (lint/typecheck/build) e package_manager,
contrato de duas tarefas com arquivos sobrepostos, contrato HOSTIL tentando
cobrir o runtime floor, mecanismo legado com `enforce_tdd: true` (guard_tests
E guard_test_runner), abandono de contrato após instalação.

Outcomes verificados (extraídos da seção "Fase 2" do ROADMAP.md, linhas
~130-206):

    1. `compile-session` produz `.claude/settings.json` com `permissions.allow`
       cobrindo EXATAMENTE a superfície enumerada do contrato ativo (Edit/Write
       dos `files[]`, `Bash(verify_cmd)`, lint/typecheck/build do profile,
       comando de instalação do package_manager, git local do ritual) — nunca
       um wildcard genérico; merge não-destrutivo preserva regras manuais,
       recompilar não duplica, e encolher o contrato REMOVE as regras órfãs.
    2. O runtime floor NUNCA vira allow efetivo: (a) contrato normal não gera
       nenhuma regra de push/rede/segredo; (b) contrato HOSTIL que declara
       `.env` em files[] e `git push` como verify_cmd continua tendo push e
       .env negados pelo boundary_guard (floor avaliado ANTES da superfície do
       contrato); (c) sem contrato ativo, `compile-session` falha (exit 1) e
       NÃO compila política nenhuma; (d) contrato abandonado (feature_list.json
       removido após instalação) mantém o floor: push/.env seguem deny enquanto
       arquivo comum volta a allow.
    3. `boundary_guard.py` nega ação fora da superfície (arquivo fora de
       files[], comando fora de verify/lint/typecheck/build/install/git-local)
       com razão legível que orienta o replanejamento, e permite a mesma classe
       de ação quando dentro do raio (incl. lint do profile e git local).
    4. Proteção contra enfraquecimento de teste: arquivo que casa `test_glob`
       só é editável se declarado em `files[]` de alguma tarefa do contrato.
    5. `compile-session` remove o hook legado `guard_tests.py` (mecanismo
       `harness compile` antigo) sem tocar outros hooks legados
       (`guard_test_runner.py` permanece) — evita duplo-gate/`ask` residual.
    6. Lifecycle de 16 passos compilado como bloco gerenciado idempotente no
       `AGENTS.md` (delimitadores próprios), coexistindo com o bloco do
       `compiler.py` e com texto humano, com progressive disclosure para
       `.harness/LIFECYCLE.md`.
    7. Templates gerados do contrato/profile: `claude-progress.md` (uma linha
       por feature, NUNCA sobrescrito se já existir) e `init.sh`/`init.ps1`
       (determinísticos, regenerados quando o profile muda).
    8. Hook `SessionStart` injeta contexto real (feature pendente, progresso,
       git log) e não quebra em diretório sem git nem sem contrato; instalação
       idempotente.

Evidência: ao final da execução do módulo, grava
`tests/e2e/evidence/fase2-outcomes-verification.md` com uma seção por outcome
(veredito ATINGIDO / NÃO ATINGIDO / NÃO EXECUTADO + prova concreta), fazendo
MERGE com o arquivo existente: cada outcome executado nesta rodada é
regravado com o veredito novo; outcome não executado nesta rodada preserva
byte a byte o veredito real de uma rodada anterior; só cai para o placeholder
quando nunca houve veredito real.

Nenhuma env var é necessária: todos os testes são baratos (subprocess local,
sem tokens, sem Docker, sem cobaia externa).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PLUGIN_ROOT / "src"
EVIDENCE_DIR = Path(__file__).resolve().parent / "evidence"
EVIDENCE_PATH = EVIDENCE_DIR / "fase2-outcomes-verification.md"

SLUG = "fase2-outcomes"

PYPROJECT_TOML = '[project]\nname = "demo-fase2"\nversion = "0.1.0"\n'
APP_PY = 'def health() -> dict:\n    return {"status": "ok"}\n'
UTIL_PY = "def soma(a: int, b: int) -> int:\n    return a + b\n"
TEST_APP_PY = (
    "from app import health\n\n\n"
    'def test_health():\n    assert health() == {"status": "ok"}\n'
)
TEST_OTHER_PY = (
    "from util import soma\n\n\ndef test_soma():\n    assert soma(1, 2) == 3\n"
)

APPROVED_SPEC = f"""---
slug: {SLUG}
approved_by: humano-e2e-fase2
approved_at: 2026-07-16T10:00:00Z
---

# Spec: Demo Fase 2

## Escopo
Health check + util, dentro do raio de impacto declarado.

## Critérios de aceitação
- `pytest tests/test_app.py -q` passa.
"""

PLANS_TWO_TASKS = """## [T-01] Implementar health check
- files: `src/app.py`, `tests/test_app.py`
- verify: `pytest tests/test_app.py -q`

## [T-02] Implementar util de soma
- files: `src/app.py`, `src/util.py`
- verify: `pytest tests -q`
- depends: T-01
"""

PLANS_ONE_TASK = """## [T-01] Implementar health check
- files: `src/app.py`, `tests/test_app.py`
- verify: `pytest tests/test_app.py -q`
"""

# Contrato HOSTIL: tenta colocar o runtime floor DENTRO da superfície aprovada
# (.env em files[], git push como verify_cmd). O floor tem que prevalecer.
PLANS_HOSTILE = """## [T-01] Tarefa que tenta cobrir o runtime floor
- files: `.env`, `src/app.py`
- verify: `git push origin main`
"""

# Profile sintético no formato EXATO de analyzer.py (Finding = value/evidence/
# confidence), com extras completos para exercitar a superfície enumerada.
def _profile_dict(package_manager: str = "npm") -> dict:
    def finding(value, evidence):
        return {"value": value, "evidence": evidence, "confidence": 0.9}

    return {
        "languages": [finding("python", "pyproject.toml")],
        "package_manager": finding(package_manager, "package-lock.json"),
        "test_command": finding("pytest tests -q", "pyproject.toml"),
        "test_glob": finding("tests/**/*.py", "tests/test_app.py"),
        "extras": {
            "lint_command": finding("ruff check .", "pyproject.toml"),
            "typecheck_command": finding("mypy src", "mypy.ini"),
            "build_command": finding("npm run build", "package.json"),
        },
        "unknowns": [],
        "analyzed_at": "2026-07-16T00:00:00+00:00",
        "manifest_snapshot": {},
    }


# Subcomandos do proprio harness liberados desde o SUBAGENTE 01 do backlog
# de correcao de friccao (2026-07-18) — espelha _HARNESS_SUBCOMMANDS de
# session_permissions.py/boundary_guard.py (NAO inclui "run").
_HARNESS_SUBCOMMANDS = [
    "compile", "audit", "audit-runtime", "analyze", "preflight",
    "compile-contract", "compile-session", "verify", "team", "review",
    "supervise", "audit-team",
]
_HARNESS_CLI_ALLOW = (
    [f"Bash(harness {sub}*)" for sub in _HARNESS_SUBCOMMANDS]
    + [f"Bash(python -m harness.cli {sub}*)" for sub in _HARNESS_SUBCOMMANDS]
)

# Superfície EXATA esperada em permissions.allow para PLANS_TWO_TASKS +
# _profile_dict("npm"), na ordem determinística de render_session_permissions:
# Edit/Write por arquivo (união na ordem de aparição), Bash(verify_cmd)
# distintos, extras (lint, typecheck, build), instalação, git local fixo,
# subcomandos do harness (SUBAGENTE 01, ver acima).
EXPECTED_ALLOW = [
    "Edit(src/app.py)",
    "Write(src/app.py)",
    "Edit(tests/test_app.py)",
    "Write(tests/test_app.py)",
    "Edit(src/util.py)",
    "Write(src/util.py)",
    "Bash(pytest tests/test_app.py -q)",
    "Bash(pytest tests -q)",
    "Bash(ruff check .)",
    "Bash(mypy src)",
    "Bash(npm run build)",
    "Bash(npm ci)",
    "Bash(git status)",
    "Bash(git log*)",
    "Bash(git diff*)",
    "Bash(git add*)",
    "Bash(git commit*)",
    *_HARNESS_CLI_ALLOW,
]

# Mecanismo legado (compiler.py) com enforce_tdd LIGADO: instala guard_tests.py
# (Write|Edit) E guard_test_runner.py (Bash) — cenário mais forte que o de
# test_boundary_flow.py (que usa enforce_tdd: false): compile-session tem que
# remover só o guard_tests.py e PRESERVAR o guard_test_runner.py.
LEGACY_HARNESS_YAML_TDD = """
governance:
  approval_policy: balanced
verification:
  enforce_tdd: true
  test_command: "pytest tests -q"
  test_glob: "tests/**/*.py"
"""

# ---------------------------------------------------------------------------
# Registro de evidência (uma seção por outcome, escrita ao final do módulo,
# com merge entre rodadas — mesmo padrão de test_fase1_outcomes.py)
# ---------------------------------------------------------------------------

_OUTCOME_TITLES = {
    1: "compile-session compila permissions.allow EXATAMENTE da superfície enumerada do contrato",
    2: "runtime floor (git push/rede/segredos) NUNCA vira allow — com contrato hostil, sem contrato, ou contrato abandonado",
    3: "boundary_guard nega fora da superfície com razão legível e permite dentro do raio",
    4: "arquivo que casa test_glob só é editável se declarado em files[] do contrato",
    5: "compile-session remove o hook legado guard_tests.py sem tocar outros hooks",
    6: "lifecycle de 16 passos como bloco gerenciado idempotente no AGENTS.md + .harness/LIFECYCLE.md",
    7: "templates do contrato/profile: claude-progress.md nunca sobrescrito; init.* regenerados",
    8: "hook SessionStart injeta contexto real e não quebra sem git/sem contrato",
}

_SECTIONS: dict[int, tuple[bool, str]] = {}

_EXISTING_SECTION_HEADER_RE = re.compile(r"^## Outcome (\d) — .*$", re.MULTILINE)

_NOT_EXECUTED_PREFIX = "Veredito: **NÃO EXECUTADO**"


def _record(outcome: int, achieved: bool, proof: list[str]) -> None:
    _SECTIONS[outcome] = (achieved, "\n".join(proof) if proof else "(sem prova registrada)")


def _parse_existing_sections(text: str) -> dict[int, str]:
    matches = list(_EXISTING_SECTION_HEADER_RE.finditer(text))
    sections: dict[int, str] = {}
    for i, match in enumerate(matches):
        num = int(match.group(1))
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[num] = text[start:end].strip("\n")
    return sections


@pytest.fixture(scope="module", autouse=True)
def _evidence_writer():
    yield
    if not _SECTIONS:
        return  # nenhum teste executou — não clobbar evidência real
    now = datetime.now(timezone.utc).isoformat()
    existing_sections: dict[int, str] = {}
    if EVIDENCE_PATH.is_file():
        existing_sections = _parse_existing_sections(
            EVIDENCE_PATH.read_text(encoding="utf-8")
        )
    body = [
        "# Evidência — Fase 2: verificação dos 9 outcomes",
        "",
        f"Gerado em {now} por `tests/e2e/test_fase2_outcomes.py` "
        "(repos sintéticos em tmp_path via subprocess da CLI real).",
        "",
    ]
    for num in range(1, 9):
        title = _OUTCOME_TITLES[num]
        body.append(f"## Outcome {num} — {title}")
        body.append("")
        if num in _SECTIONS:
            achieved, proof = _SECTIONS[num]
            body.append(f"Veredito: **{'ATINGIDO' if achieved else 'NÃO ATINGIDO'}**")
            body.append("")
            body.append(proof)
            body.append("")
            body.append(f"_Atualizado em {now} por esta rodada._")
        else:
            old_body = existing_sections.get(num, "")
            if old_body and not old_body.lstrip().startswith(_NOT_EXECUTED_PREFIX):
                body.append(old_body)
            else:
                body.append("Veredito: **NÃO EXECUTADO** (teste pulado ou não alcançado)")
        body.append("")
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    EVIDENCE_PATH.write_text("\n".join(body) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Helpers — sempre subprocess real (CLI e hooks standalone), nunca in-process
# ---------------------------------------------------------------------------

def _run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ | {"PYTHONPATH": str(SRC_DIR)}
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *args],
        capture_output=True, text=True, timeout=60, env=env, cwd=str(cwd),
    )


def _run_hook(script: Path, payload: dict) -> dict:
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload), capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["hookSpecificOutput"]


def _bootstrap_repo(root: Path) -> None:
    (root / "pyproject.toml").write_text(PYPROJECT_TOML, encoding="utf-8")
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "app.py").write_text(APP_PY, encoding="utf-8")
    (root / "src" / "util.py").write_text(UTIL_PY, encoding="utf-8")
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / "tests" / "test_app.py").write_text(TEST_APP_PY, encoding="utf-8")
    (root / "tests" / "test_other.py").write_text(TEST_OTHER_PY, encoding="utf-8")


def _write_profile(root: Path, package_manager: str = "npm") -> None:
    profile_path = root / ".harness" / "repo-profile.json"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        json.dumps(_profile_dict(package_manager), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _write_contract(root: Path, plans_text: str, spec_text: str = APPROVED_SPEC) -> None:
    contract_dir = root / ".harness" / "work" / SLUG
    contract_dir.mkdir(parents=True, exist_ok=True)
    (contract_dir / "spec.md").write_text(spec_text, encoding="utf-8")
    (contract_dir / "Plans.md").write_text(plans_text, encoding="utf-8")


def _setup_project(root: Path, plans_text: str = PLANS_TWO_TASKS,
                   with_profile: bool = True) -> Path:
    """Repo sintético + profile + contrato aprovado + `compile-contract` (CLI
    real). NÃO roda `compile-session` — cada teste roda quando quiser."""
    root.mkdir(parents=True, exist_ok=True)
    _bootstrap_repo(root)
    if with_profile:
        _write_profile(root)
    _write_contract(root, plans_text)
    proc = _run_cli(["compile-contract", "--dir", str(root), "--slug", SLUG], cwd=root)
    assert proc.returncode == 0, proc.stderr
    return root


def _load_settings(root: Path) -> dict:
    return json.loads((root / ".claude" / "settings.json").read_text(encoding="utf-8"))


def _boundary_script(root: Path) -> Path:
    return root / ".harness" / "hooks" / "boundary_guard.py"


# ---------------------------------------------------------------------------
# Outcome 1 — superfície EXATA de permissions compilada do contrato
# ---------------------------------------------------------------------------

def test_outcome1_permissions_exactly_enumerated_surface(tmp_path: Path) -> None:
    proof: list[str] = []
    achieved = False
    try:
        project = _setup_project(tmp_path / "demo")

        # (a) primeira compilação, sem settings pré-existente: allow tem que
        # ser EXATAMENTE a lista enumerada — nem uma regra a mais, nem a menos.
        proc = _run_cli(["compile-session", "--dir", str(project)], cwd=project)
        assert proc.returncode == 0, proc.stderr
        allow = _load_settings(project)["permissions"]["allow"]
        assert allow == EXPECTED_ALLOW, (
            f"allow compilado difere da superfície enumerada esperada:\n"
            f"obtido:   {allow}\nesperado: {EXPECTED_ALLOW}"
        )
        # nunca uma política genérica
        for generic in ("Bash", "Edit", "Write", "Bash(*)", "Edit(*)", "Write(*)"):
            assert generic not in allow, f"política genérica {generic!r} no allow"
        proof.append(
            "`compile-session` num settings virgem compilou `permissions.allow` "
            f"EXATAMENTE igual à superfície enumerada ({len(EXPECTED_ALLOW)} regras: "
            "Edit/Write dos files[] das 2 tarefas sem duplicar `src/app.py`, os 2 "
            "verify_cmd distintos, lint/typecheck/build do profile, `npm ci` do "
            "package_manager, git local do ritual). Nenhum wildcard genérico.\n\n"
            f"```json\n{json.dumps(allow, indent=2)}\n```"
        )

        # (b) regra manual sobrevive ao merge e recompilar não duplica.
        settings = _load_settings(project)
        settings["permissions"]["allow"].insert(0, "Bash(echo regra-manual)")
        (project / ".claude" / "settings.json").write_text(
            json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        proc = _run_cli(["compile-session", "--dir", str(project)], cwd=project)
        assert proc.returncode == 0, proc.stderr
        allow = _load_settings(project)["permissions"]["allow"]
        assert "Bash(echo regra-manual)" in allow, "regra manual foi apagada pelo merge"
        assert len(allow) == len(EXPECTED_ALLOW) + 1, f"recompilar duplicou regras: {allow}"
        assert len(set(allow)) == len(allow), f"regras duplicadas: {allow}"
        proof.append(
            "Merge não-destrutivo: regra manual `Bash(echo regra-manual)` sobreviveu "
            "à recompilação; nenhuma regra duplicada (idempotência)."
        )

        # (c) encolher o contrato REMOVE as regras órfãs (T-02 sai do plano).
        _write_contract(project, PLANS_ONE_TASK)
        proc = _run_cli(["compile-contract", "--dir", str(project), "--slug", SLUG], cwd=project)
        assert proc.returncode == 0, proc.stderr
        proc = _run_cli(["compile-session", "--dir", str(project)], cwd=project)
        assert proc.returncode == 0, proc.stderr
        allow = _load_settings(project)["permissions"]["allow"]
        assert "Edit(src/util.py)" not in allow, "regra órfã de T-02 sobreviveu ao shrink"
        assert "Write(src/util.py)" not in allow
        assert "Bash(pytest tests -q)" not in allow, "verify_cmd órfão de T-02 sobreviveu"
        assert "Edit(src/app.py)" in allow and "Bash(pytest tests/test_app.py -q)" in allow
        assert "Bash(echo regra-manual)" in allow, "shrink apagou a regra manual"
        proof.append(
            "Contrato encolhido (T-02 removida do Plans.md) e recompilado: "
            "`Edit/Write(src/util.py)` e `Bash(pytest tests -q)` SUMIRAM do allow "
            "(a autonomia é do tamanho do contrato ATUAL), regra manual preservada."
        )
        achieved = True
    finally:
        _record(1, achieved, proof)


# ---------------------------------------------------------------------------
# Outcome 2 — runtime floor nunca vira allow (o achado crítico da revisão)
# ---------------------------------------------------------------------------

def test_outcome2_runtime_floor_never_becomes_allow(tmp_path: Path) -> None:
    proof: list[str] = []
    achieved = False
    try:
        # (a) contrato normal: NENHUMA regra do floor aparece no allow compilado.
        project = _setup_project(tmp_path / "demo")
        proc = _run_cli(["compile-session", "--dir", str(project)], cwd=project)
        assert proc.returncode == 0, proc.stderr
        allow = _load_settings(project)["permissions"]["allow"]
        for floor_marker in ("git push", "curl", "wget", "publish", "twine",
                             "gh release", ".env", ".pem", "id_rsa", "credentials"):
            hits = [r for r in allow if floor_marker in r]
            assert not hits, f"floor {floor_marker!r} vazou para o allow: {hits}"
        proof.append(
            "Contrato normal: nenhuma regra de `git push`/rede (curl, wget, "
            "publish, twine, gh release)/segredos (.env, .pem, id_rsa, credentials) "
            "no `permissions.allow` compilado."
        )

        # (b) contrato HOSTIL: .env em files[], `git push` como verify_cmd —
        # aprovado e compilado, e MESMO ASSIM o boundary_guard nega os dois
        # (floor avaliado ANTES da superfície do contrato).
        hostile = _setup_project(tmp_path / "hostile", plans_text=PLANS_HOSTILE)
        proc = _run_cli(["compile-session", "--dir", str(hostile)], cwd=hostile)
        assert proc.returncode == 0, proc.stderr
        guard = _boundary_script(hostile)
        assert guard.is_file()

        push = _run_hook(guard, {
            "tool_name": "Bash", "cwd": str(hostile),
            "tool_input": {"command": "git push origin main"},
        })
        assert push["permissionDecision"] == "deny", push
        assert "runtime floor" in push["permissionDecisionReason"]

        env_edit = _run_hook(guard, {
            "tool_name": "Edit", "cwd": str(hostile),
            "tool_input": {"file_path": ".env"},
        })
        assert env_edit["permissionDecision"] == "deny", env_edit
        assert "runtime floor" in env_edit["permissionDecisionReason"]
        proof.append(
            "Contrato HOSTIL (files[] declara `.env`; verify_cmd é `git push "
            "origin main`), aprovado e compilado com sucesso — e o boundary_guard "
            "instalado NEGA os dois mesmo assim, citando 'runtime floor' na razão: "
            "o floor é avaliado antes da superfície do contrato, então nem contrato "
            "aprovado cobrindo tudo transforma push/segredo em allow efetivo."
        )
        # Observação honesta (não-falha): no nível do settings.json, o render
        # ecoa o verify_cmd hostil verbatim; a garantia efetiva vem do hook
        # PreToolUse, que o Claude Code avalia antes das permissions e cujo
        # deny prevalece sobre qualquer allow.
        hostile_allow = _load_settings(hostile)["permissions"]["allow"]
        echoed = [r for r in hostile_allow if "git push" in r or ".env" in r]
        proof.append(
            "Observação (registrada, não é falha do outcome): com o contrato "
            f"hostil o settings ecoa {echoed} em `permissions.allow` — a camada "
            "que faz o floor valer é o hook `boundary_guard` (deny incondicional, "
            "avaliado antes das permissions), não a lista compilada."
        )

        # (c) SEM contrato ativo: compile-session recusa e NÃO compila nada.
        bare = tmp_path / "bare"
        bare.mkdir()
        _bootstrap_repo(bare)
        proc = _run_cli(["compile-session", "--dir", str(bare)], cwd=bare)
        assert proc.returncode == 1, (
            f"compile-session sem contrato deveria falhar: exit={proc.returncode}"
        )
        assert "compile-contract" in proc.stderr, proc.stderr
        assert not (bare / ".claude" / "settings.json").exists(), (
            "compile-session sem contrato escreveu settings.json — política sem contrato"
        )
        proof.append(
            "Sem contrato ativo: `compile-session` -> exit 1 (stderr manda rodar "
            "`compile-contract` primeiro) e NENHUM `.claude/settings.json` é "
            "escrito — não existe política compilada sem contrato aprovado."
        )

        # (d) contrato ABANDONADO depois da instalação: floor continua deny,
        # arquivo comum volta a allow (guard não gateia fora de sessão de
        # contrato, mas o floor é incondicional).
        (hostile / ".harness" / "feature_list.json").unlink()
        push2 = _run_hook(guard, {
            "tool_name": "Bash", "cwd": str(hostile),
            "tool_input": {"command": "git push origin main"},
        })
        assert push2["permissionDecision"] == "deny", push2
        env2 = _run_hook(guard, {
            "tool_name": "Write", "cwd": str(hostile),
            "tool_input": {"file_path": ".env"},
        })
        assert env2["permissionDecision"] == "deny", env2
        common = _run_hook(guard, {
            "tool_name": "Edit", "cwd": str(hostile),
            "tool_input": {"file_path": "src/app.py"},
        })
        assert common["permissionDecision"] == "allow", common
        assert "sem contrato ativo" in common["permissionDecisionReason"]
        proof.append(
            "Contrato abandonado (feature_list.json removido após a instalação): "
            "`git push` e Write em `.env` continuam DENY (floor incondicional, "
            "avaliado ANTES da checagem de contrato), enquanto Edit em arquivo "
            "comum volta a allow ('sem contrato ativo')."
        )
        achieved = True
    finally:
        _record(2, achieved, proof)


# ---------------------------------------------------------------------------
# Outcome 3 — deny com razão legível fora do raio; allow dentro
# ---------------------------------------------------------------------------

def test_outcome3_boundary_guard_denies_outside_allows_inside(tmp_path: Path) -> None:
    proof: list[str] = []
    achieved = False
    try:
        project = _setup_project(tmp_path / "demo")
        proc = _run_cli(["compile-session", "--dir", str(project)], cwd=project)
        assert proc.returncode == 0, proc.stderr
        guard = _boundary_script(project)

        # deny: arquivo fora de files[] de qualquer tarefa
        deny_file = _run_hook(guard, {
            "tool_name": "Edit", "cwd": str(project),
            "tool_input": {"file_path": "src/nao_declarado.py"},
        })
        assert deny_file["permissionDecision"] == "deny", deny_file
        reason = deny_file["permissionDecisionReason"]
        assert "fora da superficie do contrato ativo" in reason, reason
        assert "replaneje" in reason, reason
        proof.append(
            "Edit em `src/nao_declarado.py` (fora de files[]) -> deny com razão "
            f"legível que orienta o replanejamento: `{reason}`"
        )

        # deny: comando fora da superfície compilada
        deny_cmd = _run_hook(guard, {
            "tool_name": "Bash", "cwd": str(project),
            "tool_input": {"command": "python scripts/deploy.py --prod"},
        })
        assert deny_cmd["permissionDecision"] == "deny", deny_cmd
        reason_cmd = deny_cmd["permissionDecisionReason"]
        assert "fora da superficie compilada do contrato" in reason_cmd, reason_cmd
        assert "replaneje" in reason_cmd, reason_cmd
        proof.append(
            "Bash `python scripts/deploy.py --prod` (fora de verify/lint/typecheck/"
            f"build/install/git-local) -> deny com razão: `{reason_cmd}`"
        )

        # allow: as mesmas classes de ação DENTRO do raio
        checks = [
            ("Edit", {"file_path": "src/app.py"}, "arquivo declarado em files[]"),
            ("Bash", {"command": "pytest tests/test_app.py -q"}, "verify_cmd"),
            ("Bash", {"command": "ruff check ."}, "lint do profile"),
            ("Bash", {"command": "mypy src"}, "typecheck do profile"),
            ("Bash", {"command": "npm run build"}, "build do profile"),
            ("Bash", {"command": "git status"}, "git local do ritual"),
            ("Bash", {"command": "git commit -m 'estado retomavel'"}, "git local do ritual"),
        ]
        for tool, tool_input, label in checks:
            result = _run_hook(guard, {
                "tool_name": tool, "cwd": str(project), "tool_input": tool_input,
            })
            assert result["permissionDecision"] == "allow", (label, result)
        proof.append(
            "Dentro do raio, tudo allow sem prompt: Edit em files[], verify_cmd, "
            "lint/typecheck/build do profile, `git status`/`git commit` do ritual."
        )
        achieved = True
    finally:
        _record(3, achieved, proof)


# ---------------------------------------------------------------------------
# Outcome 4 — proteção contra enfraquecimento de teste (por tarefa)
# ---------------------------------------------------------------------------

def test_outcome4_test_weakening_protection_is_per_task(tmp_path: Path) -> None:
    proof: list[str] = []
    achieved = False
    try:
        project = _setup_project(tmp_path / "demo")
        proc = _run_cli(["compile-session", "--dir", str(project)], cwd=project)
        assert proc.returncode == 0, proc.stderr
        guard = _boundary_script(project)

        # tests/test_app.py casa test_glob E está em files[] da T-01 -> allow
        # (o lado allow que test_boundary_flow.py não cobre).
        allowed = _run_hook(guard, {
            "tool_name": "Edit", "cwd": str(project),
            "tool_input": {"file_path": "tests/test_app.py"},
        })
        assert allowed["permissionDecision"] == "allow", allowed
        assert "teste declarado em files[]" in allowed["permissionDecisionReason"]
        proof.append(
            "`tests/test_app.py` casa o test_glob E está em files[] da T-01 -> "
            f"allow (razão: `{allowed['permissionDecisionReason']}`) — tarefa TDD "
            "declarada pode tocar o próprio teste."
        )

        # tests/test_other.py casa test_glob mas NENHUMA tarefa o declara -> deny
        denied = _run_hook(guard, {
            "tool_name": "Edit", "cwd": str(project),
            "tool_input": {"file_path": "tests/test_other.py"},
        })
        assert denied["permissionDecision"] == "deny", denied
        reason = denied["permissionDecisionReason"]
        assert "enfraquecimento de teste" in reason, reason
        proof.append(
            "`tests/test_other.py` casa o test_glob e NÃO está em files[] de "
            f"nenhuma tarefa -> deny (razão: `{reason}`) — o allow do raio não "
            "deixa o agente afrouxar teste fora do escopo aprovado."
        )
        achieved = True
    finally:
        _record(4, achieved, proof)


# ---------------------------------------------------------------------------
# Outcome 5 — remoção do hook legado guard_tests.py (sem tocar os demais)
# ---------------------------------------------------------------------------

def test_outcome5_legacy_guard_tests_removed_others_preserved(tmp_path: Path) -> None:
    proof: list[str] = []
    achieved = False
    try:
        project = _setup_project(tmp_path / "demo")

        # Mecanismo antigo com enforce_tdd LIGADO: instala guard_tests.py
        # (Write|Edit) E guard_test_runner.py (Bash).
        (project / ".harness" / "harness.yaml").write_text(
            LEGACY_HARNESS_YAML_TDD, encoding="utf-8"
        )
        proc = _run_cli(["compile", "--dir", str(project)], cwd=project)
        assert proc.returncode == 0, proc.stderr
        pre = json.dumps(_load_settings(project)["hooks"]["PreToolUse"])
        assert "guard_tests.py" in pre, "cenário legado não instalou guard_tests.py"
        assert "guard_test_runner.py" in pre, "cenário legado não instalou guard_test_runner.py"
        proof.append(
            "Mecanismo antigo (`harness compile`, enforce_tdd: true) instalou "
            "`guard_tests.py` (Write|Edit) E `guard_test_runner.py` (Bash) em "
            "hooks.PreToolUse."
        )

        proc = _run_cli(["compile-session", "--dir", str(project)], cwd=project)
        assert proc.returncode == 0, proc.stderr
        entries = _load_settings(project)["hooks"]["PreToolUse"]
        dump = json.dumps(entries)
        assert "guard_tests.py" not in dump, (
            "guard_tests.py legado sobreviveu — duplo-gate/`ask` residual sobre Edit de teste"
        )
        assert "guard_test_runner.py" in dump, (
            "compile-session removeu um hook que NÃO era o guard_tests.py legado"
        )
        assert "boundary_guard.py" in dump
        matchers = sorted(e["matcher"] for e in entries)
        # boundary_guard.py agora registra com matcher "*" (casa toda tool
        # call — roteamento explícito por tool acontece dentro de main() do
        # script gerado; ver docstring de harness.boundary_guard), não mais
        # "Edit|Write|Bash".
        assert matchers == ["*", "Bash"], matchers
        proof.append(
            "Após `compile-session`: `guard_tests.py` REMOVIDO de hooks.PreToolUse "
            "(a proteção de teste agora é por-tarefa no boundary_guard), "
            "`guard_test_runner.py` PRESERVADO intacto, `boundary_guard.py` "
            f"registrado. Matchers finais: {matchers}."
        )

        # idempotência: segunda rodada não duplica a entrada do boundary_guard
        proc = _run_cli(["compile-session", "--dir", str(project)], cwd=project)
        assert proc.returncode == 0, proc.stderr
        entries2 = _load_settings(project)["hooks"]["PreToolUse"]
        boundary_entries = [e for e in entries2 if "boundary_guard.py" in json.dumps(e)]
        assert len(boundary_entries) == 1, entries2
        proof.append("Segunda rodada de `compile-session`: uma única entrada do "
                     "boundary_guard (idempotente).")
        achieved = True
    finally:
        _record(5, achieved, proof)


# ---------------------------------------------------------------------------
# Outcome 6 — lifecycle de 16 passos: bloco gerenciado idempotente no AGENTS.md
# ---------------------------------------------------------------------------

def test_outcome6_lifecycle_block_idempotent_and_coexistent(tmp_path: Path) -> None:
    proof: list[str] = []
    achieved = False
    try:
        project = _setup_project(tmp_path / "demo")

        # AGENTS.md pré-existente com texto HUMANO + bloco do compiler.py
        # (mecanismo antigo) já presente — os três têm que coexistir.
        (project / "AGENTS.md").write_text(
            "# Projeto Demo\n\nTexto escrito pelo humano — não pode sumir.\n",
            encoding="utf-8",
        )
        (project / ".harness" / "harness.yaml").write_text(
            LEGACY_HARNESS_YAML_TDD, encoding="utf-8"
        )
        proc = _run_cli(["compile", "--dir", str(project)], cwd=project)
        assert proc.returncode == 0, proc.stderr
        text_before = (project / "AGENTS.md").read_text(encoding="utf-8")
        assert "<!-- harness:begin -->" in text_before
        compiler_block = re.search(
            r"<!-- harness:begin -->.*?<!-- harness:end -->", text_before, re.DOTALL
        ).group(0)

        proc = _run_cli(["compile-session", "--dir", str(project)], cwd=project)
        assert proc.returncode == 0, proc.stderr
        text = (project / "AGENTS.md").read_text(encoding="utf-8")

        assert "Texto escrito pelo humano — não pode sumir." in text
        assert compiler_block in text, "bloco do compiler.py foi alterado/apagado"
        assert text.count("<!-- harness:lifecycle:begin -->") == 1
        proof.append(
            "AGENTS.md após `compile` (mecanismo antigo) + `compile-session`: texto "
            "humano preservado, bloco `<!-- harness:begin -->` do compiler.py "
            "byte a byte intacto, bloco `<!-- harness:lifecycle:begin -->` adicionado."
        )

        # 16 passos numerados no bloco fino + progressive disclosure
        block = re.search(
            r"<!-- harness:lifecycle:begin -->.*?<!-- harness:lifecycle:end -->",
            text, re.DOTALL,
        ).group(0)
        steps = re.findall(r"^\d+\. ", block, re.MULTILINE)
        assert len(steps) == 16, f"bloco do lifecycle tem {len(steps)} passos, esperado 16"
        assert ".harness/LIFECYCLE.md" in block, "bloco fino não aponta para o detalhe"
        for marker in ("exatamente UMA feature pendente", "claude-progress.md",
                       "feature_list.json", "git log"):
            assert marker in block, f"passo esperado ausente do bloco: {marker!r}"
        proof.append(
            "Bloco do lifecycle: 16 passos numerados (1 linha por passo), citando "
            "init/claude-progress.md/feature_list.json/git log/'exatamente UMA "
            "feature pendente', com ponteiro de progressive disclosure para "
            "`.harness/LIFECYCLE.md`."
        )

        detail = (project / ".harness" / "LIFECYCLE.md").read_text(encoding="utf-8")
        detail_steps = re.findall(r"^\d+\. \*\*", detail, re.MULTILINE)
        assert len(detail_steps) == 16, f"LIFECYCLE.md tem {len(detail_steps)} passos detalhados"
        proof.append("`.harness/LIFECYCLE.md` existe com os 16 passos detalhados "
                     "(um parágrafo por passo).")

        # idempotência: recompilar não duplica o bloco nem mexe no resto
        proc = _run_cli(["compile-session", "--dir", str(project)], cwd=project)
        assert proc.returncode == 0, proc.stderr
        text2 = (project / "AGENTS.md").read_text(encoding="utf-8")
        assert text2.count("<!-- harness:lifecycle:begin -->") == 1
        assert compiler_block in text2
        assert "Texto escrito pelo humano — não pode sumir." in text2
        proof.append("Segunda rodada: um único bloco lifecycle (substituído in-place), "
                     "bloco do compiler e texto humano seguem intactos.")
        achieved = True
    finally:
        _record(6, achieved, proof)


# ---------------------------------------------------------------------------
# Outcome 7 — templates: progresso nunca sobrescrito; init.* regenerados
# ---------------------------------------------------------------------------

def test_outcome7_templates_progress_preserved_init_regenerated(tmp_path: Path) -> None:
    proof: list[str] = []
    achieved = False
    try:
        project = _setup_project(tmp_path / "demo")
        proc = _run_cli(["compile-session", "--dir", str(project)], cwd=project)
        assert proc.returncode == 0, proc.stderr

        # claude-progress.md gerado DO CONTRATO (uma linha por feature, pending)
        progress = (project / "claude-progress.md").read_text(encoding="utf-8")
        assert f"Contrato: `{SLUG}`" in progress
        assert "| T-01 | Implementar health check | pending |" in progress
        assert "| T-02 | Implementar util de soma | pending |" in progress
        proof.append(
            "`claude-progress.md` gerado do contrato compilado: cabeçalho com o "
            "slug e uma linha por feature (T-01/T-02, status pending)."
        )

        # init.sh / init.ps1 gerados DO PROFILE (npm ci + test_command)
        init_sh = (project / "init.sh").read_text(encoding="utf-8")
        init_ps1 = (project / "init.ps1").read_text(encoding="utf-8")
        assert "npm ci" in init_sh and "pytest tests -q" in init_sh
        assert init_sh.startswith("#!/usr/bin/env bash")
        assert "npm ci" in init_ps1 and "pytest tests -q" in init_ps1
        assert "$ErrorActionPreference = 'Stop'" in init_ps1
        proof.append(
            "`init.sh`/`init.ps1` gerados do profile: instalação (`npm ci` do "
            "package_manager) + health check (`pytest tests -q` do test_command), "
            "mesmo conteúdo semântico nas duas linguagens."
        )

        # progresso REAL nunca é sobrescrito por recompilação
        sentinel = "# PROGRESSO REAL DA SESSÃO — sobrescrever isto é perder trabalho\n"
        (project / "claude-progress.md").write_text(sentinel, encoding="utf-8")
        proc = _run_cli(["compile-session", "--dir", str(project)], cwd=project)
        assert proc.returncode == 0, proc.stderr
        assert (project / "claude-progress.md").read_text(encoding="utf-8") == sentinel, (
            "recompilar SOBRESCREVEU claude-progress.md — progresso real perdido"
        )
        proof.append(
            "`claude-progress.md` substituído por progresso real e `compile-session` "
            "re-rodado: o arquivo permaneceu byte a byte igual (nunca sobrescrito)."
        )

        # init.* são determinísticos: profile mudou -> regenerados
        _write_profile(project, package_manager="pnpm")
        proc = _run_cli(["compile-session", "--dir", str(project)], cwd=project)
        assert proc.returncode == 0, proc.stderr
        init_sh2 = (project / "init.sh").read_text(encoding="utf-8")
        assert "pnpm install --frozen-lockfile" in init_sh2
        assert "npm ci" not in init_sh2
        allow = _load_settings(project)["permissions"]["allow"]
        assert "Bash(pnpm install --frozen-lockfile)" in allow
        assert "Bash(npm ci)" not in allow, "regra de instalação órfã sobreviveu à troca de profile"
        proof.append(
            "Profile mudado (npm -> pnpm) e recompilado: `init.sh` regenerado com "
            "`pnpm install --frozen-lockfile` (sem resto de `npm ci`), e a regra de "
            "instalação no allow acompanhou a troca."
        )
        achieved = True
    finally:
        _record(7, achieved, proof)


# ---------------------------------------------------------------------------
# Outcome 8 — SessionStart injeta contexto real; robusto sem git/sem contrato
# ---------------------------------------------------------------------------

def test_outcome8_session_start_injects_state_and_survives_no_git(tmp_path: Path) -> None:
    proof: list[str] = []
    achieved = False
    try:
        project = _setup_project(tmp_path / "demo")

        # repo git REAL com um commit, para o hook ter git log de verdade
        def _git(*args: str) -> None:
            proc = subprocess.run(
                ["git", *args], cwd=str(project), capture_output=True, text=True, timeout=30,
            )
            assert proc.returncode == 0, proc.stderr

        _git("init", "-q")
        _git("add", "-A")
        _git("-c", "user.name=e2e", "-c", "user.email=e2e@example.com",
             "commit", "-qm", "estado inicial da cobaia fase2")

        proc = _run_cli(["compile-session", "--dir", str(project)], cwd=project)
        assert proc.returncode == 0, proc.stderr

        hook_path = project / ".harness" / "hooks" / "session_start.py"
        assert hook_path.is_file()
        settings = _load_settings(project)
        entries = settings["hooks"]["SessionStart"]
        assert len(entries) == 1 and entries[0]["matcher"] == "*", entries
        proof.append(
            "`compile-session` instalou `.harness/hooks/session_start.py` e "
            "registrou UMA entrada em hooks.SessionStart (matcher `*`)."
        )

        out = _run_hook(hook_path, {"cwd": str(project)})
        assert out["hookEventName"] == "SessionStart", out
        context = out["additionalContext"]
        assert "Feature ativa/pendente: T-01" in context, context
        assert "Progresso recente (claude-progress.md)" in context, context
        assert "git log -n 5 --oneline" in context, context
        assert "estado inicial da cobaia fase2" in context, context
        proof.append(
            "Hook invocado com payload real: `additionalContext` contém a feature "
            "pendente (`Feature ativa/pendente: T-01`), o tail do "
            "claude-progress.md e o `git log` real (commit 'estado inicial da "
            "cobaia fase2') — a sessão nasce sabendo onde parou."
        )

        # idempotência do registro
        proc = _run_cli(["compile-session", "--dir", str(project)], cwd=project)
        assert proc.returncode == 0, proc.stderr
        entries2 = _load_settings(project)["hooks"]["SessionStart"]
        assert len(entries2) == 1, entries2
        proof.append("Segunda rodada de `compile-session`: continua UMA entrada em "
                     "hooks.SessionStart (idempotente).")

        # diretório SEM git e SEM contrato: hook não quebra a sessão
        bare = tmp_path / "sem-git"
        bare.mkdir()
        out_bare = _run_hook(hook_path, {"cwd": str(bare)})
        assert out_bare["hookEventName"] == "SessionStart", out_bare
        assert "Nenhum contrato ativo" in out_bare["additionalContext"]
        proof.append(
            "Hook apontado (via payload cwd) para diretório sem git e sem "
            "`.harness/`: exit 0, JSON válido, contexto degrada com elegância "
            "('Nenhum contrato ativo') — não quebra a sessão."
        )
        achieved = True
    finally:
        _record(8, achieved, proof)
