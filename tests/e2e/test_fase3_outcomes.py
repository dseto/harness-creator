"""E2E: verificação independente dos 5 outcomes prometidos pela Fase 3 do
ROADMAP.md ("Auto-verificação e Correção em Loop"), provados contra o código
REAL — subprocess da CLI (`python -m harness.cli ...`) e dos hooks standalone
gerados, MAIS chamada direta às funções públicas de módulo que a Fase 3
expõe de propósito (`compute_files_hash`, `get_stop_conditions`,
`is_feature_in_progress`, `needs_verification`, `evaluate_feature_list_edit`,
`audit_runtime`) — nunca por confiança em relatório de implementação.

Camada de verificação INDEPENDENTE dos E2E já existentes: não duplica
`test_boundary_flow.py` (que cobre runtime floor, superfície de arquivos/
comandos e proteção de teste — mas NÃO o feature-lock de `passes:true`).

Outcomes verificados (extraídos da seção "Fase 3" do ROADMAP.md, linhas
~208-247, refinados pela leitura do código real):

    1. `harness verify <id>` roda o `verify_cmd` REAL da feature (efeito
       observável em disco) e só grava `.harness/evidence/<id>.json` quando o
       exit code é 0 — com o schema EXATO fixado em `verify.py` (`feature_id`/
       `verify_cmd`/`recorded_at`/`exit_code`/`files_hash`, e `files_hash`
       recomputável de fora via `compute_files_hash`). Falha do verify_cmd NÃO
       grava evidência e o exit code REAL (ex.: 7) propaga pela CLI — nunca um
       1 hardcoded. Feature/contrato ausentes -> exit 1 com erro legível.
       `compute_files_hash` é determinística, insensível à ordem de `files[]`,
       muda quando o conteúdo muda e não levanta para arquivo ausente.
    2. `get_stop_conditions` expõe as `stop_conditions:` do frontmatter do
       `spec.md` normalizadas para `list[str]`, consistentes com o que
       `parse_spec` já retornava (nunca uma segunda fonte); chave ausente ou
       nula -> lista vazia sem levantar. O passo 10 do lifecycle compilado
       (`.harness/LIFECYCLE.md` via `install_lifecycle`) cita explicitamente
       o campo `stop_conditions:` do `spec.md` ativo e o acessor
       `harness.contract.get_stop_conditions` como o disjuntor do loop de
       autocorreção.
    3. Feature-lock no boundary_guard (hook standalone REAL via subprocess E
       versão importável `evaluate_feature_list_edit` — as duas cópias que o
       módulo exige manter sincronizadas): edição de `feature_list.json` que
       transiciona feature para `passes:true` -> deny sem evidência, deny com
       evidência mais antiga que o último commit, allow com evidência fresca;
       edição que NÃO transiciona nada delega ao comportamento genérico de
       superfície (deny, arquivo fora de files[]).
    4. Hook `Stop`: `is_feature_in_progress` (passes false + diff não
       commitado tocando files[]) e `needs_verification` (evidência ausente OU
       files_hash desatualizado) detectam corretamente — e ficam em silêncio
       quando tudo verificado, sem trabalho pendente, `passes:true` ou feature
       sem files[]. O script standalone gerado (`render_stop_hook`) devolve
       `additionalContext` citando só os ids pendentes, e imprime NADA quando
       não há pendência. `compile-session` instala o hook (chave `stop_hook`
       no JSON de saída, entrada em hooks.Stop SEM `matcher`, idempotente,
       conteúdo do arquivo == `render_stop_hook()`).
    5. `audit-runtime` pega os 2 invariantes prometidos com severidade
       `critical`: (a) no máximo 1 feature em progresso; (b) todo `passes:true`
       tem evidência válida com `exit_code == 0`. E usa a MESMA função
       `is_feature_in_progress` importada de `stop_hook` (identidade de objeto,
       não cópia) — provado também em comportamento: os ids que a função de
       stop_hook flagra num cenário real são exatamente os ids que o finding
       `multiple_features_in_progress` cita. CLI `audit-runtime`: exit 0 com
       artefatos sadios, exit 1 com score < 60, findings em JSON parseável.

Evidência: ao final da execução do módulo, grava
`tests/e2e/evidence/fase3-outcomes-verification.md` com uma seção por outcome
(veredito ATINGIDO / NÃO ATINGIDO / NÃO EXECUTADO + prova concreta), fazendo
MERGE com o arquivo existente (mesmo padrão de `test_fase2_outcomes.py`): cada
outcome executado nesta rodada é regravado com o veredito novo; outcome não
executado preserva byte a byte o veredito real de uma rodada anterior; só cai
para o placeholder quando nunca houve veredito.

Nenhuma env var é necessária: todos os testes são baratos (subprocess local,
git local, sem tokens, sem Docker, sem cobaia externa).
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
EVIDENCE_PATH = EVIDENCE_DIR / "fase3-outcomes-verification.md"

# Funções públicas de módulo da Fase 3 — chamadas DIRETAS onde faz sentido
# (o próprio ROADMAP as expõe como API de módulo, não só scripts standalone).
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from harness import runtime_audit as runtime_audit_module  # noqa: E402
from harness import stop_hook as stop_hook_module  # noqa: E402
from harness.boundary_guard import (  # noqa: E402
    evaluate_feature_list_edit,
    render_boundary_guard,
)
from harness.contract import ContractError, get_stop_conditions, parse_spec  # noqa: E402
from harness.lifecycle import install_lifecycle  # noqa: E402
from harness.runtime_audit import audit_runtime  # noqa: E402
from harness.stop_hook import (  # noqa: E402
    is_feature_in_progress,
    needs_verification,
    render_stop_hook,
)
from harness.verify import compute_files_hash  # noqa: E402

SLUG = "fase3-outcomes"

APP_PY = 'def health() -> dict:\n    return {"status": "ok"}\n'
UTIL_PY = "def soma(a: int, b: int) -> int:\n    return a + b\n"
TEST_APP_PY = (
    "from app import health\n\n\n"
    'def test_health():\n    assert health() == {"status": "ok"}\n'
)

# Datas de commit FIXAS no passado (2026-01-01) para que "evidência fresca"
# (recorded_at = agora) e "evidência velha" (recorded_at = 2020) fiquem
# inequivocamente dos dois lados do timestamp do último commit — sem depender
# da resolução de segundos do %cI num teste que roda em milissegundos.
_COMMIT_DATE = "2026-01-01T00:00:00+00:00"
_STALE_RECORDED_AT = "2020-01-01T00:00:00+00:00"


# ---------------------------------------------------------------------------
# Registro de evidência (uma seção por outcome, escrita ao final do módulo,
# com merge entre rodadas — mesmo padrão de test_fase1/test_fase2_outcomes.py)
# ---------------------------------------------------------------------------

_OUTCOME_TITLES = {
    1: "harness verify roda o verify_cmd REAL; evidência (schema exato) só com exit 0; falha propaga o exit code real sem gravar nada",
    2: "get_stop_conditions expõe as stop conditions do spec.md (consistente com parse_spec) e o passo 10 do lifecycle cita essa fonte como disjuntor",
    3: "feature-lock: passes:true só com evidência fresca (mais nova que o último commit); sem/velha evidência -> deny; edição sem transição mantém o deny de superfície",
    4: "hook Stop detecta feature em progresso sem verificação atualizada, silencia quando tudo verificado; compile-session instala idempotente sem matcher",
    5: "audit-runtime pega os 2 invariantes como critical e usa is_feature_in_progress IMPORTADA de stop_hook (os dois módulos concordam no mesmo cenário)",
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
        "# Evidência — Fase 3: verificação dos 6 outcomes",
        "",
        f"Gerado em {now} por `tests/e2e/test_fase3_outcomes.py` "
        "(repos sintéticos em tmp_path via subprocess da CLI real + hooks "
        "standalone gerados + funções públicas de módulo).",
        "",
    ]
    for num in range(1, 6):
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
# Helpers
# ---------------------------------------------------------------------------

def _run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ | {"PYTHONPATH": str(SRC_DIR)}
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *args],
        capture_output=True, text=True, timeout=120, env=env, cwd=str(cwd),
    )


def _run_boundary_hook(script: Path, payload: dict) -> dict:
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload), capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["hookSpecificOutput"]


def _run_stop_hook(script: Path, payload: dict) -> dict | None:
    """Roda o hook Stop standalone. Retorna `hookSpecificOutput` ou `None`
    quando o hook (corretamente) não imprime nada."""
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload), capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout.strip()
    if not out:
        return None
    return json.loads(out)["hookSpecificOutput"]


def _git(root: Path, *args: str, backdated: bool = False) -> str:
    env = os.environ.copy()
    if backdated:
        env["GIT_AUTHOR_DATE"] = _COMMIT_DATE
        env["GIT_COMMITTER_DATE"] = _COMMIT_DATE
    proc = subprocess.run(
        ["git", "-c", "user.name=e2e", "-c", "user.email=e2e@example.com", *args],
        cwd=str(root), capture_output=True, text=True, timeout=30, env=env,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def _feature(fid: str, files: list[str], verify_cmd: str,
             passes: bool = False) -> dict:
    return {
        "id": fid,
        "desc": f"Feature {fid}",
        "files": files,
        "verify_cmd": verify_cmd,
        "depends": [],
        "passes": passes,
    }


def _write_feature_list(root: Path, features: list[dict]) -> Path:
    path = root / ".harness" / "feature_list.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "contract": SLUG,
        "compiled_at": datetime.now(timezone.utc).isoformat(),
        "features": features,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return path


def _write_evidence(root: Path, fid: str, *, files: list[str] | None = None,
                    recorded_at: str | None = None, exit_code: int = 0,
                    files_hash: str | None = None,
                    verify_cmd: str = "echo ok") -> Path:
    evidence = {
        "feature_id": fid,
        "verify_cmd": verify_cmd,
        "recorded_at": recorded_at or datetime.now(timezone.utc).isoformat(),
        "exit_code": exit_code,
        "files_hash": files_hash if files_hash is not None
        else compute_files_hash(files or [], root),
    }
    path = root / ".harness" / "evidence" / f"{fid}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Outcome 1 — harness verify: evidência real só com exit 0, exit code propaga
# ---------------------------------------------------------------------------

def test_outcome1_verify_records_evidence_only_on_success(tmp_path: Path) -> None:
    proof: list[str] = []
    achieved = False
    try:
        project = tmp_path / "verify"
        (project / "src").mkdir(parents=True)
        (project / "src" / "app.py").write_text(APP_PY, encoding="utf-8")
        _write_feature_list(project, [
            # verify_cmd com EFEITO OBSERVÁVEL em disco: prova que o comando
            # rodou de verdade, não que a CLI "disse que rodou".
            _feature("T-OK", ["src/app.py"], "echo verify-ok > verify_ran.txt"),
            # exit code arbitrário (7): prova propagação do código REAL,
            # nunca um 1 hardcoded.
            _feature("T-FAIL", ["src/app.py"], "exit 7"),
        ])

        # (a) sucesso: exit 0, evidência gravada com o schema EXATO
        proc = _run_cli(["verify", "T-OK", "--dir", str(project)], cwd=project)
        assert proc.returncode == 0, proc.stderr
        assert (project / "verify_ran.txt").is_file(), (
            "verify_cmd não rodou de verdade — nenhum efeito observável em disco"
        )
        assert "verify-ok" in (project / "verify_ran.txt").read_text(encoding="utf-8")

        evidence_path = project / ".harness" / "evidence" / "T-OK.json"
        assert evidence_path.is_file(), "sucesso não gravou .harness/evidence/T-OK.json"
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        assert set(evidence.keys()) == {
            "feature_id", "verify_cmd", "recorded_at", "exit_code", "files_hash",
        }, f"schema da evidência divergiu do fixado em verify.py: {sorted(evidence)}"
        assert evidence["feature_id"] == "T-OK"
        assert evidence["verify_cmd"] == "echo verify-ok > verify_ran.txt"
        assert evidence["exit_code"] == 0
        # recorded_at ISO8601 parseável
        datetime.fromisoformat(evidence["recorded_at"])
        # files_hash recomputável de FORA (a promessa do módulo: consumidores
        # detectam evidência desatualizada sem reimplementar o hash)
        recomputed = compute_files_hash(["src/app.py"], project)
        assert evidence["files_hash"] == recomputed, (
            f"files_hash gravado ({evidence['files_hash']}) != recomputado ({recomputed})"
        )
        # stdout da CLI ecoa a evidência gravada (mesmo JSON)
        assert json.loads(proc.stdout) == evidence
        proof.append(
            "`harness verify T-OK`: exit 0, o verify_cmd REAL rodou (efeito "
            "observável `verify_ran.txt` criado em disco), evidência gravada em "
            "`.harness/evidence/T-OK.json` com o schema EXATO de verify.py "
            "(feature_id/verify_cmd/recorded_at/exit_code/files_hash), "
            "`exit_code: 0`, `recorded_at` ISO8601 e `files_hash` idêntico ao "
            "recomputado de fora via `compute_files_hash`.\n\n"
            f"```json\n{json.dumps(evidence, indent=2)}\n```"
        )

        # (b) falha: exit code REAL (7) propaga, NADA gravado
        proc = _run_cli(["verify", "T-FAIL", "--dir", str(project)], cwd=project)
        assert proc.returncode == 7, (
            f"exit code do verify_cmd (7) não propagou: obtido {proc.returncode}"
        )
        assert not (project / ".harness" / "evidence" / "T-FAIL.json").exists(), (
            "verify_cmd falhou e MESMO ASSIM gravou evidência"
        )
        proof.append(
            "`harness verify T-FAIL` (verify_cmd `exit 7`): CLI saiu com exit "
            "code 7 — o código REAL do comando, não um 1 genérico — e NENHUM "
            "`.harness/evidence/T-FAIL.json` foi gravado."
        )

        # (c) feature inexistente / contrato ausente: exit 1 com erro legível
        proc = _run_cli(["verify", "T-NOPE", "--dir", str(project)], cwd=project)
        assert proc.returncode == 1, proc.returncode
        assert "encontrada" in proc.stderr, proc.stderr
        bare = tmp_path / "bare"
        bare.mkdir()
        proc = _run_cli(["verify", "T-01", "--dir", str(bare)], cwd=bare)
        assert proc.returncode == 1, proc.returncode
        assert "encontrado" in proc.stderr, proc.stderr
        proof.append(
            "Feature inexistente e diretório sem feature_list.json: exit 1 com "
            "erro legível no stderr (nunca evidência, nunca traceback)."
        )

        # (d) propriedades de compute_files_hash (chamada direta — função
        # pública de módulo, outras tarefas dependem dela)
        (project / "a.txt").write_text("aaa\n", encoding="utf-8")
        (project / "b.txt").write_text("bbb\n", encoding="utf-8")
        h_ab = compute_files_hash(["a.txt", "b.txt"], project)
        h_ba = compute_files_hash(["b.txt", "a.txt"], project)
        assert h_ab == h_ba, "hash sensível à ordem de files[] — não é determinístico"
        assert h_ab.startswith("sha256:")
        (project / "b.txt").write_text("MUDOU\n", encoding="utf-8")
        h_changed = compute_files_hash(["a.txt", "b.txt"], project)
        assert h_changed != h_ab, "conteúdo mudou e o hash não acompanhou"
        h_missing = compute_files_hash(["nao_existe.txt"], project)
        assert h_missing.startswith("sha256:"), "arquivo ausente deveria usar sentinela, não levantar"
        proof.append(
            "`compute_files_hash` (chamada direta): insensível à ordem de "
            "files[] (sorted), prefixo `sha256:`, muda quando o conteúdo muda, "
            "e arquivo ausente usa a sentinela `<missing>` sem levantar exceção."
        )
        achieved = True
    finally:
        _record(1, achieved, proof)


# ---------------------------------------------------------------------------
# Outcome 2 — get_stop_conditions + passo 10 do lifecycle cita a fonte
# ---------------------------------------------------------------------------

def test_outcome2_stop_conditions_accessor_and_lifecycle_step10(tmp_path: Path) -> None:
    proof: list[str] = []
    achieved = False
    try:
        # (a) spec com stop_conditions (incluindo item não-string, para provar
        # a normalização para list[str]) — consistência com parse_spec
        spec_with = tmp_path / "spec_with.md"
        spec_with.write_text(
            "---\n"
            f"slug: {SLUG}\n"
            "approved_by: qa\n"
            "approved_at: 2026-07-16T10:00:00Z\n"
            "stop_conditions:\n"
            '  - "3 falhas consecutivas da mesma suíte de teste"\n'
            '  - "verify_cmd referenciado não existe no repo-profile"\n'
            "  - 42\n"
            "---\n\n# Spec\n",
            encoding="utf-8",
        )
        conditions = get_stop_conditions(spec_with)
        assert conditions == [
            "3 falhas consecutivas da mesma suíte de teste",
            "verify_cmd referenciado não existe no repo-profile",
            "42",
        ], conditions
        # consistência com o parser existente: mesma fonte, só normalizada
        raw = parse_spec(spec_with)["stop_conditions"]
        assert conditions == [str(item) for item in raw], (
            "get_stop_conditions divergiu do que parse_spec retorna para a mesma chave"
        )
        proof.append(
            "`get_stop_conditions` sobre spec com 3 condições (uma não-string, "
            "`42`): retorna `list[str]` normalizada e IDÊNTICA a "
            "`[str(x) for x in parse_spec(...)['stop_conditions']]` — mesma "
            "fonte do parser existente, nunca um segundo parse de frontmatter."
        )

        # (b) chave ausente e chave nula: lista vazia, sem levantar
        spec_absent = tmp_path / "spec_absent.md"
        spec_absent.write_text(
            f"---\nslug: {SLUG}\napproved_by: qa\napproved_at: 2026-07-16T10:00:00Z\n---\n\n# Spec\n",
            encoding="utf-8",
        )
        assert get_stop_conditions(spec_absent) == []
        spec_null = tmp_path / "spec_null.md"
        spec_null.write_text(
            f"---\nslug: {SLUG}\nstop_conditions:\n---\n\n# Spec\n",
            encoding="utf-8",
        )
        assert get_stop_conditions(spec_null) == []
        with pytest.raises(ContractError):
            get_stop_conditions(tmp_path / "nao_existe.md")
        proof.append(
            "Chave `stop_conditions` ausente -> `[]`; chave nula -> `[]` "
            "(opcional no contrato, nunca levanta por ausência); spec.md "
            "inexistente -> `ContractError` (do próprio parse_spec)."
        )

        # (c) o passo 10 do lifecycle compilado cita a fonte como disjuntor
        project = tmp_path / "lifecycle"
        project.mkdir()
        agents_path, detail_path = install_lifecycle(project)
        assert detail_path.is_file() and agents_path.is_file()
        detail = detail_path.read_text(encoding="utf-8")
        step10 = re.search(r"^10\. \*\*.*?(?=^11\. \*\*)", detail,
                           re.MULTILINE | re.DOTALL)
        assert step10, "LIFECYCLE.md sem o passo 10"
        step10_text = step10.group(0)
        assert "stop_conditions" in step10_text, (
            "passo 10 não cita o campo stop_conditions do spec.md"
        )
        assert "spec.md" in step10_text
        assert "harness.contract.get_stop_conditions" in step10_text, (
            "passo 10 não aponta o acessor programático get_stop_conditions"
        )
        assert "disjuntor" in step10_text, (
            "passo 10 não declara as stop conditions como o disjuntor do loop"
        )
        proof.append(
            "`.harness/LIFECYCLE.md` instalado por `install_lifecycle` (o mesmo "
            "caminho de `compile-session`): o parágrafo do passo 10 cita "
            "explicitamente o campo `stop_conditions:` do frontmatter do "
            "`spec.md` ativo, o acessor `harness.contract.get_stop_conditions` "
            "e a palavra 'disjuntor' — a fonte do circuito de parada do loop "
            "de autocorreção é a mesma que o outcome (a) provou funcionar."
        )
        achieved = True
    finally:
        _record(2, achieved, proof)


# ---------------------------------------------------------------------------
# Outcome 3 — feature-lock: passes:true só com evidência fresca
# ---------------------------------------------------------------------------

def test_outcome3_feature_lock_requires_fresh_evidence(tmp_path: Path) -> None:
    proof: list[str] = []
    achieved = False
    try:
        project = tmp_path / "lock"
        (project / "src").mkdir(parents=True)
        (project / "src" / "app.py").write_text(APP_PY, encoding="utf-8")
        _write_feature_list(project, [
            _feature("T-01", ["src/app.py"], "echo ok"),
        ])
        # repo git REAL com commit BACKDATED (2026-01-01): evidência "agora" é
        # inequivocamente mais nova; evidência de 2020 é inequivocamente velha.
        _git(project, "init", "-q")
        _git(project, "add", "-A")
        _git(project, "commit", "-qm", "estado inicial", backdated=True)

        guard = project / ".harness" / "hooks" / "boundary_guard.py"
        guard.parent.mkdir(parents=True, exist_ok=True)
        guard.write_text(render_boundary_guard(), encoding="utf-8")

        transition_input = {
            "file_path": ".harness/feature_list.json",
            "old_string": '"passes": false',
            "new_string": '"passes": true',
        }
        payload = {"tool_name": "Edit", "cwd": str(project),
                   "tool_input": transition_input}

        # (a) SEM evidência: deny nas DUAS cópias (standalone + importável)
        out = _run_boundary_hook(guard, payload)
        assert out["permissionDecision"] == "deny", out
        assert "feature-lock" in out["permissionDecisionReason"]
        assert "harness verify" in out["permissionDecisionReason"]
        assert "T-01" in out["permissionDecisionReason"]
        importable = evaluate_feature_list_edit("Edit", transition_input, project)
        assert importable is not None and importable[0] == "deny", importable
        assert "harness verify" in importable[1]
        proof.append(
            "Transição `passes: false -> true` via Edit SEM evidência em disco: "
            "deny citando T-01 e mandando rodar `harness verify` primeiro — nas "
            "DUAS cópias da lógica (hook standalone via subprocess E "
            "`evaluate_feature_list_edit` importável). Razão do hook: "
            f"`{out['permissionDecisionReason']}`"
        )

        # (b) evidência VELHA (recorded_at 2020 < commit 2026-01-01): deny
        _write_evidence(project, "T-01", files=["src/app.py"],
                        recorded_at=_STALE_RECORDED_AT)
        out = _run_boundary_hook(guard, payload)
        assert out["permissionDecision"] == "deny", out
        assert "mais antiga que o" in out["permissionDecisionReason"], out
        importable = evaluate_feature_list_edit("Edit", transition_input, project)
        assert importable is not None and importable[0] == "deny", importable
        assert "mais antiga que o" in importable[1]
        proof.append(
            "Evidência com `recorded_at` de 2020 (mais velha que o último commit, "
            "backdated para 2026-01-01): deny nas duas cópias, razão citando "
            "'evidencia mais antiga que o ultimo commit'."
        )

        # (c) evidência FRESCA (recorded_at agora > commit): allow
        _write_evidence(project, "T-01", files=["src/app.py"])
        out = _run_boundary_hook(guard, payload)
        assert out["permissionDecision"] == "allow", out
        assert "T-01" in out["permissionDecisionReason"]
        importable = evaluate_feature_list_edit("Edit", transition_input, project)
        assert importable is not None and importable[0] == "allow", importable
        proof.append(
            "Mesma edição com evidência fresca (recorded_at = agora, mais nova "
            "que o último commit): ALLOW nas duas cópias, razão confirmando a "
            "evidência fresca de T-01 — o agente só marca done depois do "
            "`harness verify` real. Razão do hook: "
            f"`{out['permissionDecisionReason']}`"
        )

        # (d) edição que NÃO transiciona passes:true delega à superfície
        # genérica -> deny (feature_list.json fora de files[] de qualquer tarefa)
        no_transition_input = {
            "file_path": ".harness/feature_list.json",
            "old_string": '"desc": "Feature T-01"',
            "new_string": '"desc": "Feature T-01 renomeada"',
        }
        out = _run_boundary_hook(guard, {
            "tool_name": "Edit", "cwd": str(project),
            "tool_input": no_transition_input,
        })
        assert out["permissionDecision"] == "deny", out
        assert "fora da superficie do contrato ativo" in out["permissionDecisionReason"], out
        assert evaluate_feature_list_edit("Edit", no_transition_input, project) is None, (
            "versão importável deveria delegar (None) quando não há transição"
        )
        proof.append(
            "Edição do feature_list.json que NÃO transiciona nenhuma feature "
            "(só muda desc): a versão importável delega (`None`) e o hook "
            "standalone cai no comportamento genérico de superfície -> deny "
            "('fora da superficie do contrato ativo') — o feature-lock não abriu "
            "uma porta nova para edições arbitrárias do arquivo."
        )
        achieved = True
    finally:
        _record(3, achieved, proof)


# ---------------------------------------------------------------------------
# Outcome 4 — hook Stop: detecção correta + instalação via compile-session
# ---------------------------------------------------------------------------

def test_outcome4_stop_hook_detects_unverified_in_progress(tmp_path: Path) -> None:
    proof: list[str] = []
    achieved = False
    try:
        project = tmp_path / "stop"
        (project / "src").mkdir(parents=True)
        (project / "src" / "app.py").write_text(APP_PY, encoding="utf-8")
        (project / "src" / "util.py").write_text(UTIL_PY, encoding="utf-8")
        feat_t01 = _feature("T-01", ["src/app.py"], "echo ok")
        feat_t02 = _feature("T-02", ["src/util.py"], "echo ok")
        _write_feature_list(project, [feat_t01, feat_t02])
        _git(project, "init", "-q")
        _git(project, "add", "-A")
        _git(project, "commit", "-qm", "estado inicial")

        hook = project / ".harness" / "hooks" / "stop_hook.py"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text(render_stop_hook(), encoding="utf-8")

        # (a) working tree limpa: nada em progresso, hook SILENCIOSO
        assert is_feature_in_progress(feat_t01, project) is False
        assert _run_stop_hook(hook, {"cwd": str(project)}) is None, (
            "hook Stop sinalizou com working tree limpa"
        )
        proof.append(
            "Working tree limpa: `is_feature_in_progress` False e o hook Stop "
            "standalone não imprime NADA (encerramento sem fricção quando não "
            "há trabalho pendente)."
        )

        # (b) trabalho não commitado em src/app.py, SEM evidência: T-01
        # em progresso e precisando de verificação; hook cita SÓ T-01
        (project / "src" / "app.py").write_text(
            APP_PY + "\n# trabalho em andamento\n", encoding="utf-8"
        )
        assert is_feature_in_progress(feat_t01, project) is True
        assert needs_verification(feat_t01, project) is True
        assert is_feature_in_progress(feat_t02, project) is False
        out = _run_stop_hook(hook, {"cwd": str(project)})
        assert out is not None, "hook Stop silenciou com feature em progresso sem evidência"
        assert out["hookEventName"] == "Stop"
        context = out["additionalContext"]
        assert "T-01" in context and "harness verify" in context, context
        assert "T-02" not in context, f"hook citou feature sem trabalho pendente: {context}"
        proof.append(
            "Diff não commitado tocando `src/app.py` (files[] de T-01), sem "
            "evidência: `is_feature_in_progress`/`needs_verification` True para "
            "T-01 (e False para T-02, intocada); o hook standalone devolve "
            "`additionalContext` citando SÓ T-01 e mandando rodar "
            f"`harness verify`. Contexto: `{context}`"
        )

        # (c) evidência com files_hash ATUAL: verificado, hook silencia
        _write_evidence(project, "T-01", files=["src/app.py"])
        assert needs_verification(feat_t01, project) is False
        assert _run_stop_hook(hook, {"cwd": str(project)}) is None, (
            "hook Stop sinalizou mesmo com evidência atualizada (hash batendo)"
        )
        proof.append(
            "Evidência gravada com o files_hash ATUAL: `needs_verification` "
            "False e o hook volta a silenciar — evidência atualizada encerra "
            "a cobrança."
        )

        # (d) arquivo muda DEPOIS da evidência (hash não bate): flagra de novo
        (project / "src" / "app.py").write_text(
            APP_PY + "\n# mudou depois da verificacao\n", encoding="utf-8"
        )
        assert needs_verification(feat_t01, project) is True
        out = _run_stop_hook(hook, {"cwd": str(project)})
        assert out is not None and "T-01" in out["additionalContext"]
        proof.append(
            "Arquivo modificado DEPOIS da evidência (files_hash gravado != "
            "hash atual): `needs_verification` volta a True e o hook flagra "
            "T-01 de novo — evidência desatualizada não vale como prova."
        )

        # (e) casos que NUNCA são "em progresso": passes true; sem files[]
        passed = dict(feat_t01, passes=True)
        assert is_feature_in_progress(passed, project) is False
        no_files = _feature("T-03", [], "echo ok")
        assert is_feature_in_progress(no_files, project) is False
        assert needs_verification(no_files, project) is False
        proof.append(
            "`passes: true` nunca é 'em progresso' (mesmo com diff pendente); "
            "feature sem files[] nunca é 'em progresso' (sem pathspec não há "
            "como detectar trabalho — evita diff do repo inteiro)."
        )

        # (f) instalação REAL via compile-session (CLI): chave stop_hook no
        # output, entrada em hooks.Stop SEM matcher, idempotente, conteúdo
        # do arquivo == render_stop_hook()
        cs = tmp_path / "cs"
        (cs / "src").mkdir(parents=True)
        (cs / "src" / "app.py").write_text(APP_PY, encoding="utf-8")
        (cs / "tests").mkdir()
        (cs / "tests" / "test_app.py").write_text(TEST_APP_PY, encoding="utf-8")
        profile = {
            "languages": [{"value": "python", "evidence": "pyproject.toml", "confidence": 0.9}],
            "package_manager": {"value": "npm", "evidence": "package-lock.json", "confidence": 0.9},
            "test_command": {"value": "pytest tests -q", "evidence": "pyproject.toml", "confidence": 0.9},
            "test_glob": {"value": "tests/**/*.py", "evidence": "tests/test_app.py", "confidence": 0.9},
            "extras": {},
            "unknowns": [],
            "analyzed_at": "2026-07-16T00:00:00+00:00",
            "manifest_snapshot": {},
        }
        (cs / ".harness").mkdir()
        (cs / ".harness" / "repo-profile.json").write_text(
            json.dumps(profile, indent=2), encoding="utf-8"
        )
        contract_dir = cs / ".harness" / "work" / SLUG
        contract_dir.mkdir(parents=True)
        (contract_dir / "spec.md").write_text(
            f"---\nslug: {SLUG}\napproved_by: qa\napproved_at: 2026-07-16T10:00:00Z\n---\n\n# Spec\n",
            encoding="utf-8",
        )
        (contract_dir / "Plans.md").write_text(
            "## [T-01] Health check\n- files: `src/app.py`\n- verify: `pytest tests -q`\n",
            encoding="utf-8",
        )
        proc = _run_cli(["compile-contract", "--dir", str(cs), "--slug", SLUG], cwd=cs)
        assert proc.returncode == 0, proc.stderr
        proc = _run_cli(["compile-session", "--dir", str(cs)], cwd=cs)
        assert proc.returncode == 0, proc.stderr
        output = json.loads(proc.stdout)
        assert "stop_hook" in output, f"compile-session não reportou stop_hook: {output}"
        installed = Path(output["stop_hook"])
        assert installed.is_file()
        assert installed.read_text(encoding="utf-8") == render_stop_hook(), (
            "arquivo instalado difere de render_stop_hook()"
        )
        settings = json.loads((cs / ".claude" / "settings.json").read_text(encoding="utf-8"))
        stop_entries = settings["hooks"]["Stop"]
        assert len(stop_entries) == 1, stop_entries
        assert "matcher" not in stop_entries[0], (
            "entrada de hooks.Stop tem matcher — Stop não suporta matcher"
        )
        assert "stop_hook.py" in stop_entries[0]["hooks"][0]["command"]
        proc = _run_cli(["compile-session", "--dir", str(cs)], cwd=cs)
        assert proc.returncode == 0, proc.stderr
        settings2 = json.loads((cs / ".claude" / "settings.json").read_text(encoding="utf-8"))
        assert len(settings2["hooks"]["Stop"]) == 1, settings2["hooks"]["Stop"]
        proof.append(
            "`compile-session` (CLI real) instala o hook: chave `stop_hook` no "
            "JSON de saída, arquivo instalado idêntico a `render_stop_hook()`, "
            "UMA entrada em hooks.Stop SEM chave `matcher` (Stop não suporta "
            "matcher), e a segunda rodada não duplica (idempotente)."
        )
        achieved = True
    finally:
        _record(4, achieved, proof)


# ---------------------------------------------------------------------------
# Outcome 5 — audit-runtime: 2 invariantes critical + concordância com stop_hook
# ---------------------------------------------------------------------------

def test_outcome5_runtime_audit_invariants_agree_with_stop_hook(tmp_path: Path) -> None:
    proof: list[str] = []
    achieved = False
    try:
        # A função é a MESMA (identidade de objeto): runtime_audit não
        # reimplementa a decisão de "em progresso".
        assert runtime_audit_module.is_feature_in_progress is stop_hook_module.is_feature_in_progress, (
            "runtime_audit NÃO importa is_feature_in_progress de stop_hook — lógica duplicada"
        )
        proof.append(
            "`harness.runtime_audit.is_feature_in_progress` É o mesmo objeto de "
            "`harness.stop_hook.is_feature_in_progress` (assert de identidade "
            "`is`) — a decisão de 'em progresso' tem UMA implementação, não duas."
        )

        project = tmp_path / "audit"
        (project / "src").mkdir(parents=True)
        (project / "src" / "a.py").write_text("A = 1\n", encoding="utf-8")
        (project / "src" / "b.py").write_text("B = 2\n", encoding="utf-8")
        (project / "claude-progress.md").write_text("# progresso\n", encoding="utf-8")
        feat_a = _feature("T-01", ["src/a.py"], "echo ok")
        feat_b = _feature("T-02", ["src/b.py"], "echo ok")
        _write_feature_list(project, [feat_a, feat_b])
        _git(project, "init", "-q")
        _git(project, "add", "-A")
        _git(project, "commit", "-qm", "estado inicial")

        # (a) invariante 1: DUAS features em progresso -> critical citando
        # exatamente os ids que a função de stop_hook flagra (concordância
        # comportamental, não só de import)
        (project / "src" / "a.py").write_text("A = 111\n", encoding="utf-8")
        (project / "src" / "b.py").write_text("B = 222\n", encoding="utf-8")
        flagged = [f["id"] for f in (feat_a, feat_b)
                   if is_feature_in_progress(f, project)]
        assert flagged == ["T-01", "T-02"], flagged
        report = audit_runtime(project)
        multi = [f for f in report.findings if f.code == "multiple_features_in_progress"]
        assert len(multi) == 1, [f.to_dict() for f in report.findings]
        assert multi[0].severity == "critical"
        for fid in flagged:
            assert fid in multi[0].message, multi[0].message
        proof.append(
            "Duas features com diff não commitado: `is_feature_in_progress` "
            f"(stop_hook, chamada direta) flagra {flagged}; `audit_runtime` "
            "emite UM finding `multiple_features_in_progress` critical citando "
            "exatamente esses ids — os dois lugares que decidem 'em progresso' "
            f"concordam. Mensagem: `{multi[0].message}`"
        )

        # (b) restaurando uma: os dois lados voltam a concordar (1 em progresso
        # é permitido — nenhum finding)
        _git(project, "checkout", "--", "src/b.py")
        assert is_feature_in_progress(feat_b, project) is False
        report = audit_runtime(project)
        assert not any(f.code == "multiple_features_in_progress" for f in report.findings), (
            [f.to_dict() for f in report.findings]
        )
        proof.append(
            "`git checkout -- src/b.py`: stop_hook deixa de flagrar T-02 e o "
            "finding `multiple_features_in_progress` some do audit — exatamente "
            "1 feature em progresso é estado legal."
        )

        # (c) invariante 2: passes:true sem evidência -> critical
        _write_feature_list(project, [feat_a, dict(feat_b, passes=True)])
        report = audit_runtime(project)
        missing = [f for f in report.findings if f.code == "missing_evidence"]
        assert len(missing) == 1 and missing[0].severity == "critical", (
            [f.to_dict() for f in report.findings]
        )
        assert "T-02" in missing[0].message
        # evidência com exit_code != 0 -> critical
        _write_evidence(project, "T-02", files=["src/b.py"], exit_code=1)
        report = audit_runtime(project)
        nonzero = [f for f in report.findings if f.code == "evidence_exit_code_nonzero"]
        assert len(nonzero) == 1 and nonzero[0].severity == "critical", (
            [f.to_dict() for f in report.findings]
        )
        assert "T-02" in nonzero[0].message
        # evidência válida com exit_code 0 -> nenhum critical, score 100
        _write_evidence(project, "T-02", files=["src/b.py"], exit_code=0)
        report = audit_runtime(project)
        assert report.score == 100, report.to_json()
        assert not report.findings, report.to_json()
        proof.append(
            "`passes: true` sem evidência -> critical `missing_evidence` citando "
            "T-02; evidência com `exit_code: 1` -> critical "
            "`evidence_exit_code_nonzero`; evidência válida com `exit_code: 0` "
            "-> zero findings, score 100."
        )

        # (d) CLI audit-runtime: exit 0 sadio; exit 1 quando score < 60,
        # findings em JSON parseável
        proc = _run_cli(["audit-runtime", "--dir", str(project)], cwd=project)
        assert proc.returncode == 0, proc.stderr
        assert json.loads(proc.stdout)["score"] == 100
        (project / ".harness" / "evidence" / "T-02.json").unlink()
        (project / "claude-progress.md").unlink()
        proc = _run_cli(["audit-runtime", "--dir", str(project)], cwd=project)
        assert proc.returncode == 1, (proc.returncode, proc.stdout)
        broken = json.loads(proc.stdout)
        assert broken["score"] < 60, broken
        codes = {f["code"] for f in broken["findings"]}
        assert "missing_evidence" in codes and "missing_progress_file" in codes, codes
        proof.append(
            "CLI `harness audit-runtime`: exit 0 com score 100 no estado sadio; "
            "apagando a evidência de T-02 e o claude-progress.md -> exit 1 com "
            f"score {broken['score']} (<60) e findings JSON parseáveis "
            f"({sorted(codes)})."
        )
        achieved = True
    finally:
        _record(5, achieved, proof)
