"""Testes do boundary_guard (Fase 2): dispatcher único de fronteira
(Edit/Write/Bash) a partir da superfície do contrato ativo."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


from harness.boundary_guard import (
    BOUNDARY_CONTENT_HASH_STATE_KEY,
    BOUNDARY_HOOK_FILENAME,
    BOUNDARY_HOOK_MATCHER,
    BOUNDARY_STATE_KEY,
    REPO_ROOT_STATE_KEY,
    SESSION_STATE_FILE,
    _review_gate_problem,
    install_boundary_guard,
    is_floor_control_plane_path,
)


# ---------------------------------------------------------------------------
# Docstring de módulo — deve ser contrato de comportamento, não histórico
# ---------------------------------------------------------------------------

def test_module_docstring_is_concise() -> None:
    import harness.boundary_guard as bg

    lines = (bg.__doc__ or "").splitlines()
    assert len(lines) <= 40, (
        f"docstring de módulo com {len(lines)} linhas — o hook compilado "
        "nunca carrega esse texto (render_boundary_guard gera um cabeçalho "
        "próprio), então histórico de decisão aqui só custa leitura"
    )


def _run_hook(script: Path, payload: dict, cwd: Path | None = None) -> dict:
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload), capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["hookSpecificOutput"]


def _write_feature_list(target: Path, features: list[dict]) -> None:
    path = target / ".harness" / "feature_list.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"contract": "test", "compiled_at": "now", "features": features}),
        encoding="utf-8",
    )


def _write_profile(target: Path, **overrides) -> None:
    path = target / ".harness" / "repo-profile.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "languages": [{"value": "python", "evidence": "x", "confidence": 1.0}],
        "package_manager": None,
        "test_command": {"value": "pytest", "evidence": "x", "confidence": 1.0},
        "test_glob": {"value": "tests/**/*.py", "evidence": "x", "confidence": 1.0},
        "extras": {},
    }
    data.update(overrides)
    path.write_text(json.dumps(data), encoding="utf-8")


def _script(target: Path) -> Path:
    return install_boundary_guard(target)


def _init_git_repo_with_commit(target: Path, commit_iso_date: str) -> None:
    """Cria um repo git em `target` com UM commit cujo timestamp de
    committer é exatamente `commit_iso_date` (ex.: "2026-01-01T00:00:00+00:00"),
    para testar o comparativo de frescor de evidência contra
    `git log -1 --format=%cI`."""
    subprocess.run(["git", "init"], cwd=target, capture_output=True, text=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"],
                    cwd=target, capture_output=True, text=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"],
                    cwd=target, capture_output=True, text=True, check=True)
    (target / "README.md").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=target, capture_output=True, text=True, check=True)
    env = os.environ.copy()
    env["GIT_AUTHOR_DATE"] = commit_iso_date
    env["GIT_COMMITTER_DATE"] = commit_iso_date
    subprocess.run(["git", "commit", "-m", "init"], cwd=target, capture_output=True, text=True,
                    check=True, env=env)


def _write_evidence(
    target: Path,
    feature_id: str,
    recorded_at: str,
    contract: str = "test",
    dir_contract: str | None = None,
    **overrides,
) -> None:
    """Evidência escopada: `.harness/evidence/<contrato>/<id>.json`, com o campo
    `contract` DENTRO do JSON. `"test"` é o contrato dos fixtures deste arquivo
    (ver `_feature_list_json`).

    `dir_contract` desacopla o diretório do campo — é como se reproduz o
    arquivo copiado à mão para a pasta do contrato ativo, que é o caso em que
    o caminho sozinho não protege."""
    path = target / ".harness" / "evidence" / (dir_contract or contract) / f"{feature_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "feature_id": feature_id,
        "contract": contract,
        "verify_cmd": "pytest -q",
        "recorded_at": recorded_at,
        "exit_code": 0,
        "files_hash": "sha256:deadbeef",
    }
    data.update(overrides)
    path.write_text(json.dumps(data), encoding="utf-8")


def _feature_list_json(features: list[dict]) -> str:
    return json.dumps({"contract": "test", "compiled_at": "now", "features": features})


def _write_manifest(target: Path, roles: list[str] = ("producer", "reviewer")) -> None:
    path = target / ".harness" / "team" / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "pattern": "producer-reviewer",
        "mode": "subagents",
        "roles": list(roles),
        "max_review_iterations": 3,
        "generated_at": "2026-07-16T12:00:00+00:00",
    }), encoding="utf-8")


def _write_review(target: Path, feature_id: str, status: str, updated_at: str, **overrides) -> None:
    path = target / ".harness" / "review" / f"{feature_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "feature_id": feature_id,
        "status": status,
        "iteration": 1,
        "max_iterations": 3,
        "history": [],
        "justification": None,
        "updated_at": updated_at,
    }
    data.update(overrides)
    path.write_text(json.dumps(data), encoding="utf-8")


def _transition_payload(tmp_path: Path, files: list[str] | None = None) -> dict:
    return {
        "tool_name": "Write", "cwd": str(tmp_path),
        "tool_input": {
            "file_path": ".harness/feature_list.json",
            "content": _feature_list_json([
                {"id": "T-01", "desc": "x", "files": files or ["src/main.py"],
                 "verify_cmd": "pytest -q", "depends": [], "passes": True}
            ]),
        },
    }


# ---------------------------------------------------------------------------
# Tabela de decisão
#
# O guard é um dispatcher de política: cada regra tem MUITOS casos que só
# diferem no par (payload, desfecho). Escrever um `def test_` por caso fazia a
# suíte crescer com o número de casos em vez de com o número de REGRAS — e cada
# `def` pagava uma instalação de guard e um subprocesso Python só para variar
# uma string.
#
# Aqui um teste = uma regra, e a tabela carrega os casos. O `why` de cada caso é
# o que a mensagem de falha mostra, então a intenção não se perde ao colapsar.
# `_expect` roda a tabela INTEIRA antes de falhar: uma regressão que quebra
# cinco casos aparece de uma vez, não um por execução.
# ---------------------------------------------------------------------------

class Case:
    """Um caso de decisão: o que chega no hook e o desfecho exigido.

    `reason` é uma substring exigida em `permissionDecisionReason` (comparada em
    minúsculas); `denied_reason` é uma substring que NÃO pode aparecer."""

    __slots__ = ("tool", "inp", "decision", "reason", "absent", "why", "cwd", "before")

    def __init__(self, tool: str, inp: dict, decision: str, reason: str | None = None,
                 absent: str | None = None, why: str = "", cwd: str | None = None,
                 before=None) -> None:
        self.tool = tool
        self.inp = inp
        self.decision = decision
        self.reason = reason
        self.absent = absent
        self.why = why or f"{tool}: {inp}"
        # `cwd` do payload; por padrão a raiz do repo instalado. Sobrescrever
        # simula o shell "derivado" (agente que rodou `cd sub/` e não voltou).
        self.cwd = cwd
        # callable opcional rodado antes do caso — para o estado que o hook lê
        # do disco a cada chamada (ex.: trocar a branch em .git/HEAD).
        self.before = before


def bash(command: str, decision: str, reason: str | None = None,
         absent: str | None = None, why: str = "", **kw) -> Case:
    return Case("Bash", {"command": command}, decision, reason, absent,
                why or f"Bash: {command}", **kw)


def pwsh(command: str, decision: str, reason: str | None = None,
         absent: str | None = None, why: str = "", **kw) -> Case:
    return Case("PowerShell", {"command": command}, decision, reason, absent,
                why or f"PowerShell: {command}", **kw)


def write(file_path: str, decision: str, reason: str | None = None,
          absent: str | None = None, why: str = "", **kw) -> Case:
    return Case("Write", {"file_path": file_path, "content": "x"}, decision, reason,
                absent, why or f"Write: {file_path}", **kw)


def edit(file_path: str, decision: str, reason: str | None = None,
         absent: str | None = None, why: str = "", **kw) -> Case:
    return Case("Edit", {"file_path": file_path}, decision, reason, absent,
                why or f"Edit: {file_path}", **kw)


def _expect(script: Path, *cases: Case) -> None:
    """Roda cada caso contra o MESMO guard instalado e falha uma vez só,
    listando TODOS os casos que divergiram."""
    root = script.parent.parent.parent
    falhas: list[str] = []
    for case in cases:
        if case.before is not None:
            case.before()
        out = _run_hook(script, {"tool_name": case.tool,
                                 "cwd": str(root) if case.cwd is None else case.cwd,
                                 "tool_input": case.inp})
        got = out["permissionDecision"]
        reason = out.get("permissionDecisionReason", "") or ""
        if got != case.decision:
            falhas.append(f"{case.why}\n    esperado {case.decision}, veio {got}"
                          f"\n    razao: {reason[:220]}")
            continue
        if case.reason and case.reason.lower() not in reason.lower():
            falhas.append(f"{case.why}\n    decisao {got} ok, mas a razao nao cita "
                          f"{case.reason!r}\n    razao: {reason[:220]}")
        if case.absent and case.absent.lower() in reason.lower():
            falhas.append(f"{case.why}\n    decisao {got} ok, mas a razao NAO podia citar "
                          f"{case.absent!r}\n    razao: {reason[:220]}")
    assert not falhas, "\n\n".join(falhas)


# ---------------- sem contrato ativo ----------------

# ---------------- bootstrap: sem contrato, superfície mínima de COMANDO ----
#
# O default-deny do issue #35 vale para a superfície de ESCRITA. Para a
# superfície de COMANDO ele travava a própria sequência que CRIA o contrato
# (analyze -> compile -> commit -> compile-contract -> compile-session), e
# como `harness disable` é floor, o agente ficava sem saída. Os testes abaixo
# travam a superfície de bootstrap: git local, subcomandos do harness e
# utilitários read-only passam; o resto continua deny.

def test_bootstrap_surface_allows_the_contract_creation_path(tmp_path: Path) -> None:
    """Sem contrato compilado, a superfície de COMANDO precisa bastar para
    percorrer analyze -> compile-contract -> commit -> compile-session -> finish.

    `finish` entra pela mesma razão de `compile-session` — é passo do ciclo
    sancionado e escreve só dentro do `.harness/`. Não abre buraco no floor
    porque nunca executa git nem gh: um `finish` que commitasse/pushasse viraria
    bypass do floor por dentro de um subcomando permitido, que é justamente por
    que `enable`/`disable` ficam de fora."""
    _expect(
        _script(tmp_path),
        bash("git status", "allow"),
        bash('git commit -m "wip"', "allow"),
        bash("git diff", "allow"),
        bash("harness analyze --dir .", "allow"),
        bash("harness compile-contract --dir . --slug demo", "allow"),
        bash("python -m harness.cli compile-session --dir .", "allow"),
        bash("harness --help", "allow"),
        bash("harness doctor --dir .", "allow"),
        bash("harness finish --dir .", "allow"),
        bash("python -m harness.cli finish --dir .", "allow"),
        bash("echo hello", "allow"),
        bash("ls -la", "allow"),
        # Atrito 3 do ciclo `harness-finish`: `git status`/`log`/`diff` passavam e
        # `git branch --show-current` não, apesar de ser leitura pura. O agente
        # descobria a branch lendo a primeira linha do `git status` — rodeio sem
        # ganho de segurança nenhum.
        bash("git branch --show-current", "allow"),
        # Atrito 1 do ciclo `harness-finish`: a skill `plan` EXIGE carimbar
        # `approved_at` com o timestamp ISO do momento da aprovação humana, e o
        # guard negava toda rota de obtê-lo. O agente ficava sem como cumprir uma
        # regra do próprio processo — a saída foi rodar uma análise inteira do
        # repo só para ler o relógio.
        bash("date", "allow"),
        bash("date -u +%Y-%m-%dT%H:%M:%SZ", "allow"),
        bash("date --iso-8601=seconds", "allow"),
    )


def test_bootstrap_surface_denies_everything_outside_it(tmp_path: Path) -> None:
    """O simétrico: a superfície mínima é uma allowlist, não um portão aberto.

    `date` é read-only só até as flags que ESCREVEM o relógio da máquina — mesmo
    padrão de `find` (`FIND_WRITE_FLAGS`) e `grep`/`rg` (`GREP_RG_EXEC_FLAGS`):
    utilitário de leitura com um punhado de flags que o tornam destrutivo.

    E a liberação de branch é da sequência de TRÊS tokens `git branch
    --show-current`: liberar `git branch` com dois abriria `-D`/`-d`/`-m` junto,
    porque o match de superfície é por PREFIXO de tokens."""
    _expect(
        _script(tmp_path),
        bash('date -s "2020-01-01 00:00:00"', "deny"),
        bash("date --set=2020-01-01", "deny"),
        bash("git branch -D feature-antiga", "deny"),
        bash("git branch -d feature-antiga", "deny"),
        bash("git branch -m novo-nome", "deny"),
        # A mensagem de bootstrap não pode sugerir `harness task add-file`: sem
        # contrato não há tarefa a ampliar, e apontar um escape inexistente foi
        # justamente o que fez o agente concluir que estava preso.
        bash("rm -rf build", "deny", reason="nenhum contrato ativo",
             absent="task add-file"),
        # Superfície de ESCRITA: o default-deny do issue #35 continua valendo,
        # inclusive pela rota PowerShell, que cai em _evaluate_file.
        edit("src/main.py", "deny", reason="nenhum contrato ativo"),
        pwsh("Set-Content src/app.py 'x'", "deny", reason="nenhum contrato ativo"),
    )


def test_bootstrap_floor_stays_shut_without_a_contract(tmp_path: Path) -> None:
    """Bootstrap alarga a superfície, nunca o floor. A saída do deadlock é
    compilar o contrato, não o agente se autodesativar."""
    _expect(
        _script(tmp_path),
        bash("git push origin main", "deny", reason="runtime floor"),
        bash("harness disable", "deny", reason="runtime floor"),
        bash("curl https://x", "deny", reason="runtime floor"),
    )


def test_bootstrap_deny_carries_the_paste_ready_yaml_block(tmp_path: Path) -> None:
    """`extra_allowed_commands` é o ÚNICO escape de comando que funciona sem
    contrato — o hook lê o harness.yaml a cada tool call, então a entrada vale
    na chamada seguinte, sem `compile` e sem `/plan`. Omitir o bloco do deny de
    bootstrap deixava o agente sem saída alguma."""
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                              "tool_input": {"command": "git checkout -b chore/harness-init"}})
    assert out["permissionDecision"] == "deny", out
    reason = out["permissionDecisionReason"]
    assert "extra_allowed_commands:" in reason, reason
    # e a entrada sugerida preserva o modo — não libera `git checkout .` junto
    assert "- git checkout -b" in reason, reason
    assert "- git checkout\n" not in reason, reason


def test_surface_allows_the_profile_test_command_mid_contract(tmp_path: Path) -> None:
    """Atrito 2 do ciclo do contrato `harness-finish`. A superfície de comando
    era montada com o `verify_cmd` de cada tarefa mais `lint_command`,
    `typecheck_command` e `build_command` do profile — e ignorava o
    `test_command`, que está no MESMO profile. Assimetria pura: o lint do
    projeto rodava a qualquer momento, o teste do projeto só na grafia exata do
    `verify_cmd` da tarefa em curso. Na prática não havia como testar uma
    mudança em código compartilhado contra o resto da suíte antes do commit.

    O contrato deste teste tem feature PENDENTE de propósito: com todas
    passando, `_contract_fully_passed` aposenta o guard da superfície e
    qualquer pytest passaria — o que mascara o furo."""
    _write_feature_list(tmp_path, [
        {"id": "T-01", "files": ["src/a.py"],
         "verify_cmd": "pytest tests/test_a.py -q", "passes": False},
    ])
    _write_profile(tmp_path)  # test_command = "pytest"
    _expect(_script(tmp_path), bash("pytest tests -q", "allow"))

    # A liberação vem do profile, não de um allow embutido para `pytest`: sem
    # `test_command` declarado, a superfície continua a de antes.
    outro = tmp_path / "sem-test-command"
    outro.mkdir()
    _write_feature_list(outro, [
        {"id": "T-01", "files": ["src/a.py"],
         "verify_cmd": "pytest tests/test_a.py -q", "passes": False},
    ])
    _write_profile(outro, test_command=None)
    _expect(_script(outro), bash("pytest tests -q", "deny"))


def test_protected_branch_deny_names_the_chore_way_out(tmp_path: Path) -> None:
    """Atrito 5 do ciclo do contrato `harness-finish`. O floor de branch
    protegida está CERTO e continua intacto — o que estava errado era só a
    mensagem: ela oferecia `git checkout -b` e `harness compile-session`, e as
    duas são conselho ruim para um chore de release, que por política do repo
    vai direto para a `main`. Sem a terceira saída, o agente ficava tentando
    rotas fechadas ou reescrevendo a mensagem do commit, achando que o problema
    era o texto.

    A saída é incondicional, e não condicionada ao diff staged, porque
    classificar "chore" por caminho não pega o arquivo onde mora a versão
    (`src/harness/__init__.py` neste repo) sem virar regra específica de um
    repositório. O preço é a linha aparecer em todo deny de branch protegida —
    por isso ela precisa dizer que a decisão é do HUMANO."""
    _init_git_repo_with_commit(tmp_path, "2026-01-01T00:00:00+00:00")
    script = _script(tmp_path)

    out = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                              "tool_input": {"command": 'git commit -m "chore: bump"'}})

    assert out["permissionDecision"] == "deny", out
    reason = out["permissionDecisionReason"]
    assert "so via PR" in reason          # a rota normal continua sendo o PR
    assert "terminal" in reason.lower()   # a terceira saída é o terminal do humano
    assert "humano" in reason.lower()     # e é decisão dele, não do agente


# ---------------- superfície do contrato: Edit/Write ----------------

def test_contract_file_surface_is_what_files_declares(tmp_path: Path) -> None:
    """A superfície de escrita sai de `files[]` — e `files[]` aceita arquivo
    exato, prefixo de diretório e glob, sempre casando contra o PATH do
    candidato, não contra o disco (senão um arquivo genuinamente novo, que ainda
    não existe, nunca reconhece o próprio glob declarado).

    Duas exceções permanentes convivem com ela: a autoria do PRÓXIMO contrato
    (`.harness/work/<slug>/{spec,Plans}.md`), que nunca está no `files[]` do
    contrato ativo e ficaria bloqueada pela superfície da demanda atual; e o
    floor de segredo, que PRECEDE a exceção — um `.env` escondido lá dentro
    continua barrado."""
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x",
         "files": ["src/main.py", "backend/Migrations/", "frontend/*.ts"],
         "verify_cmd": "pytest -q", "depends": [], "passes": False}
    ])
    _expect(
        _script(tmp_path),
        edit("src/main.py", "allow", why="arquivo exato declarado"),
        edit("src/other.py", "deny", why="arquivo nao declarado"),
        write("backend/Migrations/20260718_New.cs", "allow",
              why="prefixo de diretorio declarado, arquivo novo fora do disco"),
        write("frontend/app.ts", "allow",
              why="glob declarado, arquivo novo fora do disco"),
        write(".harness/work/nova-feature/spec.md", "allow",
              why="autoria do proximo contrato"),
        write(".harness/work/nova-feature/Plans.md", "allow",
              why="autoria do proximo contrato"),
        write(".harness/work/x/.env", "deny",
              why="floor de segredo precede a excecao de .harness/work/**"),
    )


# ---------------- superfície do contrato: Bash ----------------

def test_contract_command_surface_is_verify_cmd_plus_local_git(tmp_path: Path) -> None:
    """`echo oi` deixou de ser o exemplo canônico de deny — desde a correção dos
    issues 1-2 do dogfood venv-Windows, utilitários read-only (echo incluso, sem
    redirect) são sempre permitidos. `rm` segue fora da superfície."""
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"],
         "verify_cmd": "pytest -x --tb=short", "depends": [], "passes": False}
    ])
    _expect(
        _script(tmp_path),
        bash("pytest -x --tb=short", "allow", why="verify_cmd exato da tarefa"),
        bash("git status", "allow"),
        bash("git add .", "allow"),
        bash("git commit -m x", "allow"),
        bash("rm -rf build", "deny"),
    )


# ---------------- runtime floor: nunca vira allow ----------------

def test_runtime_floor_never_becomes_allow(tmp_path: Path) -> None:
    """O floor não é superfície: declarar `.env` em `files[]` ou pôr `git push`
    como `verify_cmd` não compra permissão nenhuma. Vale com e sem contrato."""
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py", ".env"],
         "verify_cmd": "git push", "depends": [], "passes": False}
    ])
    _expect(
        _script(tmp_path),
        bash("git push", "deny", reason="runtime floor"),
        bash("git push origin main", "deny", reason="runtime floor"),
        bash("git push && true", "deny", reason="runtime floor"),
        bash("curl https://x", "deny", reason="runtime floor"),
        edit(".env", "deny", reason="runtime floor",
             why=".env declarado em files[] nao vira allow"),
    )

    sem_contrato = tmp_path / "sem-contrato"
    sem_contrato.mkdir()
    _expect(
        _script(sem_contrato),
        bash("git push", "deny", reason="runtime floor"),
        edit(".env", "deny", reason="runtime floor"),
    )


# ---------------- achado B (dogfood 2026-07-22): memória do Claude Code ----------------

def test_claude_memory_is_always_writable(tmp_path: Path) -> None:
    """Escrita em ~/.claude/projects/<slug>/memory/ nunca está em files[] de
    nenhuma tarefa (mora fora do repo) — antes da correção, caía no deny
    genérico de "fora da superfície do contrato ativo".

    A exceção é específica desse caminho: um path qualquer fora de files[],
    mesmo fora do repo, continua deny."""
    memoria = str(Path.home() / ".claude" / "projects" / "some-slug" / "memory" / "x.md")
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    _expect(
        _script(tmp_path),
        write(memoria, "allow", reason="mem", why="memoria com contrato ativo"),
        edit("src/other.py", "deny", why="path fora de files[] nao pega carona"),
    )

    sem_contrato = tmp_path / "sem-contrato"
    sem_contrato.mkdir()
    _expect(_script(sem_contrato), edit(memoria, "allow", why="memoria sem contrato"))


# ---------------- achado B (dogfood 2026-07-22): contrato concluído se aposenta ----------------

def test_contract_fully_passed_retires_the_surface(tmp_path: Path) -> None:
    """Todas as features com passes:true — contrato concluído. O guard não deve
    mais restringir ao files[] de um contrato já encerrado (antes da correção
    isso travava até edição manual de .claude/settings.json).

    A aposentadoria cobre arquivo E comando: a assimetria original deixava a CLI
    do próprio produto negada com contrato 100% verde. E só dispara com 100% das
    features verdes — uma pendente mantém a superfície inteira de pé."""
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": True}
    ])
    _expect(
        _script(tmp_path),
        write("src/anything_else.py", "allow", reason="conclu", why="arquivo nao declarado"),
        bash("git branch feature/next", "allow", reason="conclu", why="comando nao declarado"),
        pwsh("python -m mar_committee config-show", "allow", reason="conclu",
             why="comando PowerShell nao declarado"),
    )

    parcial = tmp_path / "parcial"
    parcial.mkdir()
    _write_feature_list(parcial, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": True},
        {"id": "T-02", "desc": "y", "files": ["src/other.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False},
    ])
    _expect(
        _script(parcial),
        bash("git branch feature/next", "deny", why="uma feature pendente ainda gateia comando"),
        write("src/unrelated.py", "deny", why="uma feature pendente ainda gateia arquivo"),
    )


def test_contract_fully_passed_still_obeys_the_floor(tmp_path: Path) -> None:
    """Aposentadoria relaxa a SUPERFÍCIE, nunca o floor nem a regra de branch
    protegida."""
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": True}
    ])
    git_dir = tmp_path / ".git"
    git_dir.mkdir(parents=True, exist_ok=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    _expect(
        _script(tmp_path),
        bash("git push origin main", "deny", reason="runtime floor"),
        bash("echo x > .env", "deny", reason="runtime floor"),
        bash("python -m harness.cli disable", "deny", reason="runtime floor"),
        pwsh("Invoke-WebRequest https://x", "deny", reason="runtime floor"),
        pwsh("python -m harness.cli disable", "deny", reason="runtime floor"),
        edit(".env", "deny", reason="runtime floor"),
        bash("git commit -m x", "deny", reason="protegida",
             why="branch protegida continua valendo com contrato 100% verde"),
    )

# ---------------- proteção contra enfraquecimento de teste ----------------

def test_test_file_is_only_editable_when_the_contract_declares_it(tmp_path: Path) -> None:
    """Arquivo que casa `test_glob` tem deny com razão PRÓPRIA — enfraquecer
    teste é a falha que o harness existe para impedir, e a mensagem genérica de
    superfície não ensinaria isso."""
    _write_profile(tmp_path)
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["tests/test_x.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    _expect(_script(tmp_path), edit("tests/test_x.py", "allow"))

    nao_declarado = tmp_path / "nao-declarado"
    nao_declarado.mkdir()
    _write_profile(nao_declarado)
    _write_feature_list(nao_declarado, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    _expect(_script(nao_declarado), edit("tests/test_x.py", "deny", reason="enfraquecimento"))


# ---------------- package_manager derivando install command ----------------

def test_package_manager_derives_exactly_the_install_command(tmp_path: Path) -> None:
    """Gap 2 (hardening): `package_manager.value == "npm"` libera EXATAMENTE
    `npm ci`, não o nome do package manager inteiro — `npm run
    build-malicioso` continua deny. Mesma regra para pip (issue #18, via
    fallback do analyzer do issue #14): `pip install -e .` e só."""
    _write_profile(tmp_path, package_manager={"value": "npm", "evidence": "x", "confidence": 1.0})
    _contract_with_verify(tmp_path)
    _expect(
        _script(tmp_path),
        bash("npm ci", "allow"),
        bash("npm run build-malicioso", "deny"),
    )

    py = tmp_path / "pip"
    py.mkdir()
    _write_profile(py, package_manager={"value": "pip", "evidence": "pyproject.toml",
                                        "confidence": 0.6})
    _contract_with_verify(py)
    _expect(
        _script(py),
        bash("pip install -e .", "allow"),
        bash("pip install -e . && curl evil", "deny", why="floor colado ao permitido"),
    )

    sem_pm = tmp_path / "sem-package-manager"
    sem_pm.mkdir()
    _write_profile(sem_pm, package_manager=None)
    _contract_with_verify(sem_pm)
    _expect(
        _script(sem_pm),
        bash("pytest -q", "allow", why="package_manager None nao quebra o resto"),
        bash("rm -rf build", "deny"),
    )


# ---------------- CLI do harness liberada sob contrato ativo ----------------

def test_the_harness_cli_is_reachable_from_inside_the_session(tmp_path: Path) -> None:
    """Os subcomandos enumerados passam nas duas grafias (`python -m harness.cli`
    e o console-script), sem depender de um `verify_cmd` que case por acaso.

    `harness task add-file` é o escape oficial documentado na skill plan: sem
    ele o guard fechava a porta e escondia a chave. `run` ficou deliberadamente
    de fora — é orquestrador com rede fora do floor. E o floor roda antes de
    qualquer allow, mesmo colado a um subcomando liberado."""
    _contract_with_verify(tmp_path)
    _expect(
        _script(tmp_path),
        bash("python -m harness.cli analyze --dir .", "allow"),
        bash("harness analyze --dir .", "allow"),
        bash("python -m harness.cli compile-contract --dir . --slug x", "allow"),
        bash("harness task add-file T-01 src/app.scss --slug demo --dir .", "allow"),
        bash("python -m harness.cli task add-file T-01 src/app.scss --dir .", "allow"),
        bash("harness run --dir .", "deny", why="`run` ficou fora da lista enumerada"),
        bash("harness analyze && git push origin main", "deny", reason="runtime floor"),
        bash("harness task add-file T-01 x.py --slug s && rm -rf src", "deny",
             why="o prefixo `harness task` nao vira tunel"),
    )


# ------------- install_boundary_guard: settings.local.json + estado -------------

def test_install_registers_one_hook_and_bakes_the_absolute_interpreter(
    tmp_path: Path,
) -> None:
    """Item 1 do backlog do dogfood venv-Windows: `python` nu é resolvido pelo
    PATH só no instante da tool call. Se não resolver ali, o hook não roda — e a
    tool call PASSA sem floor, sem proteção de segredo, sem bloqueio de push (só
    exit 2 bloqueia; qualquer outro não-zero é erro não-bloqueante para o Claude
    Code).

    Instalar duas vezes não duplica a entrada, e a chave de estado convive com
    as dos outros hooks."""
    state_path = tmp_path / SESSION_STATE_FILE
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"session_permissions_hook_command": "sibling"}),
                          encoding="utf-8")

    script = install_boundary_guard(tmp_path)
    install_boundary_guard(tmp_path)

    settings = json.loads(
        (tmp_path / ".claude" / "settings.local.json").read_text(encoding="utf-8")
    )
    entries = settings["hooks"]["PreToolUse"]
    matching = [e for e in entries if e.get("matcher") == BOUNDARY_HOOK_MATCHER]
    assert len(matching) == 1, "instalar duas vezes nao pode duplicar a entrada"

    command = matching[0]["hooks"][0]["command"]
    assert str(script) in command
    assert sys.executable in command
    assert not command.startswith("python ")

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["session_permissions_hook_command"] == "sibling"
    assert BOUNDARY_STATE_KEY in state


def test_install_records_content_hash_matching_the_installed_file(tmp_path: Path) -> None:
    """T-03/onda-3 (item 10 restante do laudo): o hook SessionStart (stdlib-only)
    detecta edição à mão do boundary_guard.py instalado comparando hashes, sem
    poder re-renderizar (dependeria de HarnessConfig/pydantic/yaml). O hash
    gravado precisa bater com os BYTES reais do arquivo — não com a string em
    memória antes do `write_text` (que traduz `\\n` -> `\\r\\n` no Windows)."""
    import hashlib

    script = install_boundary_guard(tmp_path)

    state_path = tmp_path / SESSION_STATE_FILE
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert BOUNDARY_CONTENT_HASH_STATE_KEY in state
    assert state[BOUNDARY_CONTENT_HASH_STATE_KEY] == hashlib.sha256(script.read_bytes()).hexdigest()


def test_install_replaces_legacy_command_format_without_duplicating(tmp_path: Path) -> None:
    """Entrada no formato antigo AUSENTE do compiled-state-session.json (state
    apagado, ou settings.json versionado vindo de outra máquina) não pode
    sobreviver ao merge — dois guards por tool call é o sintoma."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.local.json").write_text(json.dumps({
        "hooks": {"PreToolUse": [
            {"matcher": "*", "hooks": [{
                "type": "command",
                "command": 'python ".harness/hooks/boundary_guard.py"',
            }]},
        ]},
    }), encoding="utf-8")

    install_boundary_guard(tmp_path)

    entries = json.loads((claude_dir / "settings.local.json").read_text(encoding="utf-8"))
    guard_entries = [
        e for e in entries["hooks"]["PreToolUse"]
        if BOUNDARY_HOOK_FILENAME in json.dumps(e)
    ]
    assert len(guard_entries) == 1
    assert sys.executable in guard_entries[0]["hooks"][0]["command"]


def test_install_preserves_unrelated_settings_and_hooks(tmp_path: Path) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.local.json").write_text(json.dumps({
        "model": "opus",
        "permissions": {"allow": ["Bash(npm run *)"]},
        "hooks": {"PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "meu-hook.sh"}]},
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "outra-ferramenta.py"}]},
        ]},
    }), encoding="utf-8")

    install_boundary_guard(tmp_path)

    settings = json.loads((claude_dir / "settings.local.json").read_text(encoding="utf-8"))
    assert settings["model"] == "opus"
    assert "Bash(npm run *)" in settings["permissions"]["allow"]
    user_hooks = [e for e in settings["hooks"]["PreToolUse"] if "meu-hook.sh" in json.dumps(e)]
    assert len(user_hooks) == 1
    outros_hooks = [e for e in settings["hooks"]["PreToolUse"] if "outra-ferramenta.py" in json.dumps(e)]
    assert len(outros_hooks) == 1


def test_install_removes_legacy_guard_tests_hook(tmp_path: Path) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.local.json").write_text(json.dumps({
        "hooks": {"PreToolUse": [
            {"matcher": "Write|Edit",
             "hooks": [{"type": "command", "command": 'python ".harness/hooks/guard_tests.py"'}]},
        ]},
    }), encoding="utf-8")

    install_boundary_guard(tmp_path)

    settings = json.loads((claude_dir / "settings.local.json").read_text(encoding="utf-8"))
    legacy = [e for e in settings["hooks"]["PreToolUse"] if "guard_tests.py" in json.dumps(e)]
    assert legacy == []
    new_entries = [e for e in settings["hooks"]["PreToolUse"] if e.get("matcher") == BOUNDARY_HOOK_MATCHER]
    assert len(new_entries) == 1


def test_install_removes_legacy_guard_test_runner_hook(tmp_path: Path) -> None:
    """T-01/onda-3: guard_test_runner.py (matcher Bash, sempre-`allow`, nunca
    lia o payload) foi aposentado — media ~125ms por chamada de Bash sem
    mudar nenhuma decisão, já que este hook (matcher `*`) cobre todo Bash.
    Uma instalação existente com a entrada antiga não pode ficar rodando os
    dois hooks pra sempre só porque recompilou; mesmo tratamento que
    `guard_tests.py` já recebe acima."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.local.json").write_text(json.dumps({
        "hooks": {"PreToolUse": [
            {"matcher": "Bash",
             "hooks": [{"type": "command", "command": 'python ".harness/hooks/guard_test_runner.py"'}]},
        ]},
    }), encoding="utf-8")

    install_boundary_guard(tmp_path)

    settings = json.loads((claude_dir / "settings.local.json").read_text(encoding="utf-8"))
    legacy = [e for e in settings["hooks"]["PreToolUse"] if "guard_test_runner.py" in json.dumps(e)]
    assert legacy == []
    new_entries = [e for e in settings["hooks"]["PreToolUse"] if e.get("matcher") == BOUNDARY_HOOK_MATCHER]
    assert len(new_entries) == 1


# ---------------- feature-lock: edição do próprio feature_list.json ----------------

def _transition_case(tmp_path: Path, decision: str, reason: str | None = None,
                     why: str = "", before=None) -> Case:
    """Marcar `passes:true` no feature_list é a única escrita que o agente
    poderia usar para se autodeclarar pronto — por isso passa pelo feature-lock
    em vez da superfície comum."""
    payload = _transition_payload(tmp_path)
    return Case("Write", payload["tool_input"], decision, reason, why=why, before=before)


def test_feature_lock_requires_evidence_newer_than_the_last_commit(tmp_path: Path) -> None:
    """A defesa é TEMPORAL: evidência mais antiga que o último commit não cobre
    o diff atual. Sem evidência nenhuma, a mensagem manda rodar `harness verify`
    — é o único caminho que grava a prova."""
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    _expect(
        _script(tmp_path),
        _transition_case(tmp_path, "deny", reason="harness verify", why="sem evidencia nenhuma"),
        _transition_case(tmp_path, "deny", reason="T-01", why="sem evidencia nenhuma"),
    )

    velha = tmp_path / "evidencia-velha"
    velha.mkdir()
    _init_git_repo_with_commit(velha, "2026-06-01T00:00:00+00:00")
    _write_feature_list(velha, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    _write_evidence(velha, "T-01", recorded_at="2026-01-01T00:00:00+00:00")
    _expect(
        _script(velha),
        _transition_case(velha, "deny", reason="T-01", why="evidencia anterior ao commit"),
    )

    fresca = tmp_path / "evidencia-fresca"
    fresca.mkdir()
    _init_git_repo_with_commit(fresca, "2026-01-01T00:00:00+00:00")
    _write_feature_list(fresca, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    _write_evidence(fresca, "T-01", recorded_at="2026-06-01T00:00:00+00:00")
    _expect(
        _script(fresca),
        _transition_case(fresca, "allow", reason="T-01", why="evidencia posterior ao commit"),
        # A checagem é da TRANSIÇÃO, não da tool: o Edit com old_string/new_string
        # passa pelo mesmo lock.
        Case("Edit", {"file_path": ".harness/feature_list.json",
                      "old_string": '"passes": false', "new_string": '"passes": true'},
             "allow", why="mesma transicao via Edit"),
    )

    sem_transicao = tmp_path / "sem-transicao"
    sem_transicao.mkdir()
    _write_feature_list(sem_transicao, [
        {"id": "T-01", "desc": "x antigo", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    _expect(
        _script(sem_transicao),
        Case("Write", {"file_path": ".harness/feature_list.json",
                       "content": _feature_list_json([
                           {"id": "T-01", "desc": "x novo", "files": ["src/main.py"],
                            "verify_cmd": "pytest -q", "depends": [], "passes": False}])},
             "deny", why="edicao que nao transiciona segue o comportamento comum"),
    )


# ---------------- feature-lock: veto do revisor (Fase 4, produtor-revisor) ----------------

def test_feature_lock_honors_the_reviewer_veto(tmp_path: Path) -> None:
    """Fase 4. Sem `.harness/team/manifest.json` — ou com um que não declare os
    DOIS papéis — a evidência fresca já basta: comportamento idêntico ao da Fase
    3, sem checar revisão nenhuma. Com produtor+revisor declarados, a revisão
    passa a ser condição.

    A aprovação também tem frescor, e contra DOIS relógios: mais nova que o
    último commit (aprovação anterior ao commit não cobre o diff) e mais nova
    que `evidencia.recorded_at` — achado de reflect+judge, aprovação obsoleta
    porque a evidência foi regravada DEPOIS dela."""
    _init_git_repo_with_commit(tmp_path, "2026-01-01T00:00:00+00:00")
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    _write_evidence(tmp_path, "T-01", recorded_at="2026-06-01T00:00:00+00:00")
    script = _script(tmp_path)

    def revisao(status: str, updated_at: str, **kw):
        return lambda: _write_review(tmp_path, "T-01", status=status,
                                     updated_at=updated_at, **kw)

    _expect(
        script,
        _transition_case(tmp_path, "allow", why="sem manifesto: comportamento da Fase 3"),
        _transition_case(tmp_path, "allow", why="manifesto sem os dois papeis",
                         before=lambda: _write_manifest(tmp_path, roles=["producer"])),
        _transition_case(tmp_path, "deny", reason="T-01",
                         why="produtor+revisor declarados e nenhum registro de revisao",
                         before=lambda: _write_manifest(tmp_path)),
        _transition_case(tmp_path, "deny", reason="T-01", why="status rejected",
                         before=revisao("rejected", "2026-09-01T00:00:00+00:00")),
        _transition_case(tmp_path, "deny", reason="T-01", why="status in_review",
                         before=revisao("in_review", "2026-09-01T00:00:00+00:00")),
        _transition_case(tmp_path, "deny", reason="T-01", why="status pending",
                         before=revisao("pending", "2026-09-01T00:00:00+00:00")),
        _transition_case(tmp_path, "deny", reason="T-01",
                         why="aprovacao anterior ao ultimo commit",
                         before=revisao("approved", "2025-01-01T00:00:00+00:00")),
        _transition_case(tmp_path, "deny", reason="T-01",
                         why="aprovacao anterior a evidencia (2026-06-01)",
                         before=revisao("approved", "2026-03-01T00:00:00+00:00")),
    )

    # Aprovação mais nova que o commit E que a evidência -> allow.
    _write_evidence(tmp_path, "T-01", recorded_at="2026-03-01T00:00:00+00:00")
    _expect(
        script,
        _transition_case(tmp_path, "allow", reason="revis",
                         why="aprovacao fresca contra os dois relogios",
                         before=revisao("approved", "2026-06-01T00:00:00+00:00")),
    )


def test_feature_lock_requires_a_justification_for_a_test_diff(tmp_path: Path) -> None:
    """Feature cujo `files[]` toca o `test_glob` do repo-profile precisa de
    `justification` no registro de revisão — defesa em profundidade: uma
    reconfirmação na LEITURA, mesmo que `review.py` já bloqueie isso na
    escrita."""
    _init_git_repo_with_commit(tmp_path, "2026-01-01T00:00:00+00:00")
    _write_profile(tmp_path)
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["tests/test_x.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    _write_evidence(tmp_path, "T-01", recorded_at="2026-03-01T00:00:00+00:00")
    _write_manifest(tmp_path)
    script = _script(tmp_path)
    payload = _transition_payload(tmp_path, files=["tests/test_x.py"])

    _write_review(tmp_path, "T-01", status="approved", updated_at="2026-06-01T00:00:00+00:00",
                  justification=None)
    _expect(script, Case("Write", payload["tool_input"], "deny", reason="justificativa"))

    _write_review(tmp_path, "T-01", status="approved", updated_at="2026-06-01T00:00:00+00:00",
                  justification="expectativa mudou porque o contrato foi renegociado")
    _expect(script, Case("Write", payload["tool_input"], "allow"))


# ---------------------------------------------------------------------------
# T-04/onda-3: prova de paridade entre as duas implementações do veto do
# revisor — a importável (`_review_gate_problem`, usa `harness.review.
# load_review`) e a embutida no script standalone (não pode importar
# `harness.review`: puxaria `harness.analyzer`/`harness.patterns`, não-stdlib
# — ver docstring do módulo). "Embutir via inspect.getsource()", a técnica
# sugerida pelo laudo original para o item 11, não é executável aqui por
# essa mesma razão (correção registrada no spec.md desta onda). A prova
# possível é esta: mesmos fixtures, mesmo veredito (allow/deny) dos dois
# lados — trava a divergência já encontrada (mensagens de erro diferentes
# para JSON malformado) sem prometer uma fusão que a arquitetura impede.
# ---------------------------------------------------------------------------

def test_review_gate_parity_between_importable_and_standalone_implementations(
    tmp_path: Path,
) -> None:
    _init_git_repo_with_commit(tmp_path, "2026-01-01T00:00:00+00:00")
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    _write_evidence(tmp_path, "T-01", recorded_at="2026-03-01T00:00:00+00:00")
    _write_manifest(tmp_path)
    script = _script(tmp_path)
    payload = _transition_payload(tmp_path)

    def _standalone_allows() -> bool:
        out = _run_hook(script, {"tool_name": "Write", "cwd": str(tmp_path),
                                  "tool_input": payload["tool_input"]})
        return out["permissionDecision"] == "allow"

    def _importable_allows() -> bool:
        problem = _review_gate_problem(
            tmp_path, "T-01",
            {"id": "T-01", "files": ["src/main.py"]},
            "2026-01-01T00:00:00+00:00",
            {"recorded_at": "2026-03-01T00:00:00+00:00"},
        )
        return problem is None

    casos = (
        ("sem registro de revisao", lambda: None),
        ("status pending", lambda: _write_review(tmp_path, "T-01", status="pending",
                                                  updated_at="2026-09-01T00:00:00+00:00")),
        ("status in_review", lambda: _write_review(tmp_path, "T-01", status="in_review",
                                                     updated_at="2026-09-01T00:00:00+00:00")),
        ("status rejected", lambda: _write_review(tmp_path, "T-01", status="rejected",
                                                    updated_at="2026-09-01T00:00:00+00:00")),
        ("aprovacao anterior ao commit", lambda: _write_review(
            tmp_path, "T-01", status="approved", updated_at="2025-01-01T00:00:00+00:00")),
        ("aprovacao anterior a evidencia", lambda: _write_review(
            tmp_path, "T-01", status="approved", updated_at="2026-02-01T00:00:00+00:00")),
        ("aprovacao fresca", lambda: _write_review(
            tmp_path, "T-01", status="approved", updated_at="2026-06-01T00:00:00+00:00")),
        ("json malformado", lambda: (tmp_path / ".harness" / "review" / "T-01.json")
            .write_text("{nao e json valido", encoding="utf-8")),
    )

    divergencias = []
    for why, setup in casos:
        setup()
        standalone = _standalone_allows()
        importavel = _importable_allows()
        if standalone != importavel:
            divergencias.append(f"{why}: standalone={standalone} importavel={importavel}")
    assert not divergencias, "\n".join(divergencias)


# ---------------- Achado 1: command smuggling no guard de Bash ----------------


def _contract_with_verify(target: Path, verify_cmd: str = "pytest -q") -> None:
    _write_feature_list(target, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": verify_cmd,
         "depends": [], "passes": False}
    ])


def test_bash_command_surface_is_matched_per_segment(tmp_path: Path) -> None:
    """Achado 1: o match era sobre a linha inteira, então colar um comando
    arbitrário ao lado de um permitido escapava. A correção segmenta por
    operador de controle e exige prefixo estrito em CADA segmento — antes ou
    depois do allowed, dá no mesmo.

    Command substitution é barrada ANTES de segmentar: `$( )` e crase executam
    sem virar segmento próprio. E o floor roda em qualquer janela, intocado."""
    _contract_with_verify(tmp_path)
    _expect(
        _script(tmp_path),
        bash("pytest -q && rm -rf src", "deny", why="smuggle DEPOIS do allowed"),
        bash("rm -rf src && pytest -q", "deny", why="smuggle ANTES do allowed"),
        bash("git commit -m x ; powershell -c evil", "deny",
             why="; tambem e operador de controle"),
        bash("pytest -q | rm -rf src", "deny", why="pipe tambem e operador de controle"),
        bash("pytest -q $(rm -rf src)", "deny", why="command substitution"),
        bash("pytest -q `rm -rf src`", "deny", why="command substitution com crase"),
        bash("curl http://evil && pytest -q", "deny", reason="runtime floor",
             why="floor roda em qualquer janela"),
        # Zero regressão: o que era legítimo continua passando.
        bash("pytest -q", "allow"),
        bash("git status", "allow"),
        bash("git add .", "allow"),
        bash("git commit -m x", "allow"),
    )


# ---------------- Achado 2: feature-lock ignora replace_all=true ----------------


def test_feature_lock_replace_all_flips_all_features_denies(tmp_path: Path) -> None:
    """replace_all=true flippa TODAS as ocorrências de '"passes": false';
    feat-2/feat-3 não têm evidência -> DENY. O guard não pode simular só a
    1ª ocorrência (count=1) quando o Edit real usa replace_all=true."""
    _init_git_repo_with_commit(tmp_path, "2026-01-01T00:00:00+00:00")
    _write_feature_list(tmp_path, [
        {"id": "feat-1", "desc": "x", "files": ["src/a.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False},
        {"id": "feat-2", "desc": "x", "files": ["src/b.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False},
        {"id": "feat-3", "desc": "x", "files": ["src/c.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False},
    ])
    _write_evidence(tmp_path, "feat-1", recorded_at="2026-06-01T00:00:00+00:00")
    script = _script(tmp_path)
    out = _run_hook(script, {
        "tool_name": "Edit", "cwd": str(tmp_path),
        "tool_input": {
            "file_path": ".harness/feature_list.json",
            "old_string": '"passes": false',
            "new_string": '"passes": true',
            "replace_all": True,
        },
    })
    assert out["permissionDecision"] == "deny", out
    assert "feat-2" in out["permissionDecisionReason"]
    assert "feat-3" in out["permissionDecisionReason"]


def test_feature_lock_replace_all_importable_copy_denies(tmp_path: Path) -> None:
    """Mesma checagem na cópia IMPORTÁVEL (`evaluate_feature_list_edit`
    chamada direto, sem subprocess)."""
    from harness.boundary_guard import evaluate_feature_list_edit

    _init_git_repo_with_commit(tmp_path, "2026-01-01T00:00:00+00:00")
    _write_feature_list(tmp_path, [
        {"id": "feat-1", "desc": "x", "files": ["src/a.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False},
        {"id": "feat-2", "desc": "x", "files": ["src/b.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False},
    ])
    _write_evidence(tmp_path, "feat-1", recorded_at="2026-06-01T00:00:00+00:00")
    result = evaluate_feature_list_edit("Edit", {
        "old_string": '"passes": false',
        "new_string": '"passes": true',
        "replace_all": True,
    }, tmp_path)
    assert result is not None
    decision, reason = result
    assert decision == "deny", reason
    assert "feat-2" in reason


# ---------------- SUBAGENTE 02: mensagem de JSON invalido no feature-lock ----------------

_SUPERFICIE_GENERICA_MSG = "arquivo fora da superficie do contrato ativo"


def test_feature_list_edit_producing_invalid_json_denies_with_json_message(tmp_path: Path) -> None:
    """old_string fecha uma chave que new_string nao reabre -> JSON quebrado
    -> deny citando JSON invalido, NAO a mensagem generica de superficie."""
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    script = _script(tmp_path)
    out = _run_hook(script, {
        "tool_name": "Edit", "cwd": str(tmp_path),
        "tool_input": {
            "file_path": ".harness/feature_list.json",
            "old_string": '"passes": false}',
            "new_string": '"passes": true',
        },
    })
    assert out["permissionDecision"] == "deny", out
    reason = out["permissionDecisionReason"]
    assert "JSON" in reason
    assert "invalido" in reason.lower() or "inválido" in reason.lower()
    assert _SUPERFICIE_GENERICA_MSG not in reason


def test_feature_list_write_producing_invalid_json_denies_with_json_message(tmp_path: Path) -> None:
    """Mesmo caminho via Write (content bruto quebrado)."""
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    script = _script(tmp_path)
    out = _run_hook(script, {
        "tool_name": "Write", "cwd": str(tmp_path),
        "tool_input": {
            "file_path": ".harness/feature_list.json",
            "content": '{"contract": "x", "features": [',  # JSON truncado
        },
    })
    assert out["permissionDecision"] == "deny", out
    reason = out["permissionDecisionReason"]
    assert "JSON" in reason
    assert "invalido" in reason.lower() or "inválido" in reason.lower()
    assert _SUPERFICIE_GENERICA_MSG not in reason


def test_feature_list_edit_old_string_not_found_denies_with_specific_message(tmp_path: Path) -> None:
    """old_string que nao bate literalmente no current_text (ex.: espaco a
    mais) -> deny citando old_string nao encontrado, NAO a mensagem
    generica de superficie (achado do reflect/Fable: segundo caminho pro
    mesmo sintoma, replace() vira no-op silencioso, JSON continua valido)."""
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    script = _script(tmp_path)
    out = _run_hook(script, {
        "tool_name": "Edit", "cwd": str(tmp_path),
        "tool_input": {
            "file_path": ".harness/feature_list.json",
            "old_string": '"passes":  false',  # espaco extra: nao bate literalmente
            "new_string": '"passes": true',
        },
    })
    assert out["permissionDecision"] == "deny", out
    reason = out["permissionDecisionReason"]
    assert "old_string" in reason
    assert "encontrado" in reason.lower() or "nao foi encontrado" in reason.lower()
    assert _SUPERFICIE_GENERICA_MSG not in reason


def test_feature_list_edit_old_string_not_found_importable_copy_denies(tmp_path: Path) -> None:
    """Mesma checagem na copia IMPORTAVEL (evaluate_feature_list_edit)."""
    from harness.boundary_guard import evaluate_feature_list_edit

    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    result = evaluate_feature_list_edit("Edit", {
        "old_string": '"passes":  false',
        "new_string": '"passes": true',
    }, tmp_path)
    assert result is not None
    decision, reason = result
    assert decision == "deny"
    assert "old_string" in reason


def test_feature_list_transition_without_evidence_message_unchanged(tmp_path: Path) -> None:
    """Nao-regressao: transicao sem evidencia fresca continua citando
    'feature-lock: transicao' (mensagem intocada pelo SUBAGENTE 02)."""
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    script = _script(tmp_path)
    new_content = _feature_list_json([
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": True}
    ])
    out = _run_hook(script, {
        "tool_name": "Write", "cwd": str(tmp_path),
        "tool_input": {"file_path": ".harness/feature_list.json", "content": new_content},
    })
    assert out["permissionDecision"] == "deny"
    reason = out["permissionDecisionReason"]
    assert "feature-lock" in reason
    assert "sem evidencia fresca" in reason or "sem evidência fresca" in reason


# ---------------- SUBAGENTE 01: CLI do harness liberada sob contrato ativo ----------------


def test_feature_lock_replace_all_false_flips_only_first(tmp_path: Path) -> None:
    """Controle: replace_all ausente/false mantém count=1 — só a 1ª feature
    (feat-1, com evidência fresca) transiciona -> ALLOW."""
    _init_git_repo_with_commit(tmp_path, "2026-01-01T00:00:00+00:00")
    _write_feature_list(tmp_path, [
        {"id": "feat-1", "desc": "x", "files": ["src/a.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False},
        {"id": "feat-2", "desc": "x", "files": ["src/b.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False},
    ])
    _write_evidence(tmp_path, "feat-1", recorded_at="2026-06-01T00:00:00+00:00")
    script = _script(tmp_path)
    out = _run_hook(script, {
        "tool_name": "Edit", "cwd": str(tmp_path),
        "tool_input": {
            "file_path": ".harness/feature_list.json",
            "old_string": '"passes": false',
            "new_string": '"passes": true',
            "replace_all": False,
        },
    })
    assert out["permissionDecision"] == "allow", out


# =============================================================================
# Correção do backlog do issue #1 (bypass de tool de escrita + PowerShell +
# floor de segredo no Bash + docs/**) — itens 1 a 4.
# =============================================================================

# ---------------- Item 1: matcher "*" + roteamento explícito por tool ----------------


def test_boundary_hook_matcher_is_wildcard() -> None:
    """Decisão documentada no docstring do módulo: matcher "*" (não mais
    "Edit|Write|Bash") — confirmado via doc oficial do Claude Code que, para
    PreToolUse, "*"/""/omitido casam TODA tool call."""
    assert BOUNDARY_HOOK_MATCHER == "*"


def _notebook(path: str, decision: str, reason: str | None = None, why: str = "") -> Case:
    return Case("NotebookEdit", {"notebook_path": path}, decision, reason,
                why=why or f"NotebookEdit: {path}")


def _multiedit(path: str, decision: str, reason: str | None = None, why: str = "") -> Case:
    return Case("MultiEdit",
                {"file_path": path, "edits": [{"old_string": "a", "new_string": "b"}]},
                decision, reason, why=why or f"MultiEdit: {path}")


def test_every_write_tool_is_routed_to_the_file_rules(tmp_path: Path) -> None:
    """Achado #1: com o matcher estreito (`Edit|Write|Bash`), NotebookEdit nunca
    invocava o hook. MultiEdit era pior — invocava e caía no ramo de tool
    desconhecida, onde o nome contendo "edit" virava deny sempre.

    As duas passaram a ser roteadas explicitamente para `_evaluate_file`
    (`notebook_path` e `file_path`), o que lhes dá a superfície inteira — files[],
    `docs/**` — e também o floor inteiro."""
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py", "notebooks/analysis.ipynb"],
         "verify_cmd": "pytest -q", "depends": [], "passes": False}
    ])
    _expect(
        _script(tmp_path),
        _notebook("notebooks/analysis.ipynb", "allow", why="notebook declarado"),
        _notebook("notebooks/outro.ipynb", "deny", why="notebook fora de files[]"),
        _notebook(".env", "deny", reason="runtime floor"),
        _multiedit("src/main.py", "allow"),
        _multiedit("src/other.py", "deny"),
        _multiedit("docs/x.md", "allow", why="MultiEdit tambem herda docs/**"),
        _multiedit(".env", "deny", reason="runtime floor"),
    )


def test_unknown_tools_are_judged_by_the_name_pattern(tmp_path: Path) -> None:
    """Tool de escrita fantasma (nome arbitrário, não enumerado) cai em deny pelo
    padrão-de-nome. O contrapeso é a regressão que um default-deny ingênuo
    causaria: leitura (Read/Glob/Grep) e utilitárias conhecidas — Task incluída,
    que o próprio harness usa — continuam allow. Tool desconhecida cujo nome NÃO
    casa write/create/edit vira allow LOGADO: política mínima, risco residual
    assumido e documentado.

    T-02/onda-3 (item 17 do laudo): `TaskCreate` foi negada por engano numa
    sessão real deste projeto — o nome contém "create" e a tool não estava
    na allowlist conhecida. `TaskCreate`/`TaskGet`/`TaskList`/`TaskOutput`/
    `TaskStop`/`TaskUpdate` são as ferramentas nativas read-only-adjacentes de
    acompanhamento de tarefa do próprio Claude Code (não escrevem no
    repositório-alvo) — entram na allowlist junto de `Task`."""
    _expect(
        _script(tmp_path),
        Case("mcp__filesystem__write_file", {"path": "/etc/passwd", "content": "x"}, "deny"),
        Case("mcp__foo__create_file", {}, "deny"),
        Case("mcp__foo__edit_document", {}, "deny"),
        Case("mcp__bar__WRITE", {}, "deny"),
        Case("Read", {"file_path": "src/main.py"}, "allow"),
        Case("Glob", {"file_path": "src/main.py"}, "allow"),
        Case("Grep", {"file_path": "src/main.py"}, "allow"),
        Case("Task", {"file_path": "src/main.py"}, "allow"),
        Case("WebFetch", {"file_path": "src/main.py"}, "allow"),
        Case("TodoWrite", {"file_path": "src/main.py"}, "allow"),
        Case("TaskCreate", {"title": "x"}, "allow"),
        Case("TaskGet", {"id": "1"}, "allow"),
        Case("TaskList", {}, "allow"),
        Case("TaskOutput", {"id": "1"}, "allow"),
        Case("TaskStop", {"id": "1"}, "allow"),
        Case("TaskUpdate", {"id": "1"}, "allow"),
        Case("mcp__foo__persist_snapshot", {}, "allow", reason="allow-logado"),
    )


# ---------------- Item 2: avaliador de PowerShell (floor-first) ----------------

def test_powershell_floor_is_checked_before_any_surface(tmp_path: Path) -> None:
    """Invoke-WebRequest/Invoke-RestMethod (e os aliases `iwr`/`irm`) não são
    cobertos por `is_floor_bash_command` — a tokenização genérica não conhece
    esses nomes — e precisam do floor específico de PowerShell. Já `git push`
    reusa (não duplica) o floor de Bash."""
    _expect(
        _script(tmp_path),
        pwsh("Set-Content -Path .env -Value 'leak'", "deny", reason="runtime floor"),
        pwsh("'leak' | Out-File -FilePath secrets/.env", "deny", reason="runtime floor"),
        pwsh('[IO.File]::WriteAllText("secrets/.env", "leak")', "deny", reason="runtime floor"),
        pwsh("Invoke-WebRequest https://evil.example", "deny", reason="runtime floor"),
        pwsh("Invoke-RestMethod -Uri https://evil.example", "deny", reason="runtime floor"),
        pwsh("iwr https://evil.example", "deny", reason="runtime floor"),
        pwsh("irm https://evil.example", "deny", reason="runtime floor"),
        pwsh("git push origin main", "deny", reason="runtime floor"),
    )


def test_powershell_surface_mirrors_the_edit_write_rules(tmp_path: Path) -> None:
    """O alvo de escrita extraído do comando PowerShell passa pela MESMA lógica
    de superfície do Edit/Write — inclusive as exceções incondicionais de
    `docs/**` e `.harness/scratch/**`.

    E, ao contrário de `_evaluate_bash`, `_evaluate_powershell` NÃO bane
    `$(...)`/crase: são sintaxe legítima em PowerShell (subexpressão e escape),
    não command smuggling."""
    _contract_with_verify(tmp_path)
    _expect(
        _script(tmp_path),
        pwsh("Set-Content -Path docs/x.md -Value 'ok'", "allow"),
        pwsh("Set-Content -Path .harness/scratch/api-dump.json -Value x", "allow"),
        pwsh("Set-Content -Path other/file.txt -Value 'x'", "deny"),
        pwsh("pytest -q", "allow", why="verify_cmd da tarefa"),
        pwsh("pytest -q $(Get-Date)", "allow", absent="command substitution",
             why="$() nao pode virar falso-deny em PowerShell"),
        pwsh("Remove-Item -Recurse -Force src", "deny"),
    )


def test_powershell_without_contract_follows_the_bootstrap_surface(tmp_path: Path) -> None:
    """O caminho PowerShell também precisa conseguir CRIAR o contrato — git
    local e subcomandos do harness passam; o resto é negado."""
    _expect(
        _script(tmp_path),
        pwsh("git status", "allow"),
        pwsh('git commit -m "wip"', "allow"),
        pwsh("harness compile-contract --dir . --slug demo", "allow"),
        pwsh("harness --help", "allow"),
        pwsh("Remove-Item -Recurse -Force src", "deny", reason="nenhum contrato ativo"),
    )


# ---------------- Item 3: paridade do floor de segredo no caminho Bash ----------------

def test_bash_secret_floor_has_parity_with_powershell(tmp_path: Path) -> None:
    """Achado #3: antes da correção o floor de segredo só era checado no caminho
    Edit/Write, e `echo LEAK > .env` retornava allow.

    Os alvos entre aspas são a correção seguinte (validação adversarial Opus): a
    regex antiga capturava as aspas junto do valor (`".env"` inteiro) e
    `is_floor_secret_path` exige sufixo exato, então `".env"` falhava o match. O
    fix foi tokenizar. O floor de PowerShell nunca teve esse furo — já
    tokenizava desde o Item 2 —, e os dois casos abaixo travam isso."""
    _expect(
        _script(tmp_path),
        bash("echo LEAK > .env", "deny", reason="runtime floor",
             why="controle: sem aspas, ja funcionava antes"),
        bash("echo LEAK >> config/.env", "deny", reason="runtime floor"),
        bash("echo LEAK | tee .env", "deny", reason="runtime floor"),
        bash('echo LEAK > ".env"', "deny", reason="runtime floor"),
        bash("echo LEAK > '.env'", "deny", reason="runtime floor"),
        bash('echo LEAK >> "id_rsa"', "deny", reason="runtime floor"),
        bash('echo LEAK > "config/.env"', "deny", reason="runtime floor"),
        pwsh('Set-Content -Path ".env" -Value "leak"', "deny", reason="runtime floor"),
        pwsh("Set-Content -Path '.env' -Value 'leak'", "deny", reason="runtime floor"),
    )


def test_bash_secret_floor_is_scoped_to_writes_not_mentions(tmp_path: Path) -> None:
    """O floor cobre redirecionamento/tee — não persegue todo comando que
    meramente MENCIONA um path de segredo. E o simétrico: redirecionar para
    arquivo normal fora do `verify_cmd` continua deny, mas pelo guard genérico
    de Bash, sem citar floor (a razão certa manda o agente para `verify_cmd` ou
    `extra_allowed_commands`)."""
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/app.py"],
         "verify_cmd": "cat .env && pytest -q", "depends": [], "passes": False}
    ])
    _expect(
        _script(tmp_path),
        bash("cat .env", "allow", absent="runtime floor", why="leitura, sem redirect"),
        bash("echo x > src/app.py", "deny", reason="superficie compilada",
             absent="runtime floor", why="redirect nao-segredo fora do verify_cmd"),
    )


# ---------------- Item 4: superfície de docs via docs/** dedicado ----------------

def test_docs_surface_is_the_docs_prefix_and_nothing_else(tmp_path: Path) -> None:
    """Análoga a WORK_DIR_PREFIX: `docs/**` é sempre gravável, com ou sem
    contrato ativo. A correção NÃO usa allowlist `*.md` na raiz (proposta
    rejeitada) — por isso `README.md` na raiz continua exigindo declaração, e
    `AGENTS.md`/`CLAUDE.md`/`Plans.md`/`spec.md` são protegidos explicitamente,
    defense-in-depth, mesmo não estando fisicamente dentro de `docs/`.

    `docs/../AGENTS.md` normaliza para `AGENTS.md`: traversal não escapa. E o
    floor de segredo precede a exceção, como em work/ e scratch/."""
    _contract_with_verify(tmp_path)
    _expect(
        _script(tmp_path),
        write("docs/ARQUITETURA.md", "allow"),
        write("docs/adr/0001-decisao.md", "allow"),
        write("AGENTS.md", "deny"),
        write("CLAUDE.md", "deny"),
        write("Plans.md", "deny"),
        write("spec.md", "deny"),
        write(".harness/harness.yaml", "deny"),
        write("README.md", "deny", why="raiz nao e docs/**"),
        write("docs/../AGENTS.md", "deny", why="traversal normaliza para AGENTS.md"),
        write("docs/.env", "deny", reason="runtime floor"),
    )

    sem_contrato = tmp_path / "sem-contrato"
    sem_contrato.mkdir()
    _expect(_script(sem_contrato), write("docs/README.md", "allow"))


# ---------------- superfície de scratch (.harness/scratch/**) ----------------

def test_scratch_surface_is_always_writable(tmp_path: Path) -> None:
    """Artefato temporário de verificação (screenshot, dump) nunca está em
    files[] de nenhuma tarefa — `.harness/scratch/**` tem que ser sempre
    gravável, senão o agente acaba salvando na raiz do repo-alvo. Por isso a
    deny message genérica de superfície ENSINA o destino correto: é o que
    corrige o comportamento em sessão, sem depender de ele ter lido AGENTS.md."""
    _contract_with_verify(tmp_path)
    _expect(
        _script(tmp_path),
        write(".harness/scratch/login-page.png", "allow"),
        write(".harness/scratch/ui-check/dump-rede.json", "allow"),
        write(".harness/scratch/.env", "deny", reason="runtime floor"),
        write(".harness/scratch/credentials.json", "deny", reason="runtime floor"),
        write("screenshot-login.png", "deny", reason=".harness/scratch/",
              why="a deny message ensina o destino de artefato temporario"),
    )

    sem_contrato = tmp_path / "sem-contrato"
    sem_contrato.mkdir()
    _expect(_script(sem_contrato), write(".harness/scratch/debug.html", "allow"))


def test_floor_and_surface_predicates_are_importable() -> None:
    """Os predicados são reusados pelo compilador e pelo audit, então precisam
    ser corretos como FUNÇÃO, não só pelo desfecho do hook. `_is_work_surface_path`
    carrega a regressão do fix de traversal: o check antigo era `startswith` sobre
    o path bruto, e `.harness/work/../../qualquer.py` escapava."""
    from harness.boundary_guard import (
        _is_docs_surface_path,
        _is_scratch_surface_path,
        _is_work_surface_path,
        is_floor_bash_secret_redirect,
        is_floor_powershell_network,
        is_floor_powershell_secret_write,
    )

    assert is_floor_powershell_network("Invoke-WebRequest https://x") is True
    assert is_floor_powershell_network("iwr https://x") is True
    assert is_floor_powershell_network("git push origin main") is True
    assert is_floor_powershell_network("Get-ChildItem") is False

    assert is_floor_powershell_secret_write("Set-Content -Path .env -Value x") is True
    assert is_floor_powershell_secret_write("Set-Content -Path docs/x.md -Value x") is False
    assert is_floor_powershell_secret_write("Get-Content .env") is False

    assert is_floor_bash_secret_redirect("echo x > .env") is True
    assert is_floor_bash_secret_redirect("echo x >> id_rsa") is True
    assert is_floor_bash_secret_redirect("echo x | tee credentials.json") is True
    assert is_floor_bash_secret_redirect("cat .env") is False
    assert is_floor_bash_secret_redirect("echo x > src/app.py") is False
    # Regressão do bug de aspas (validação adversarial Opus).
    assert is_floor_bash_secret_redirect('echo x > ".env"') is True
    assert is_floor_bash_secret_redirect("echo x > '.env'") is True
    assert is_floor_bash_secret_redirect('echo x >> "config/.env"') is True

    assert _is_docs_surface_path("docs/ARQUITETURA.md") is True
    assert _is_docs_surface_path("docs/sub/x.md") is True
    assert _is_docs_surface_path("AGENTS.md") is False
    assert _is_docs_surface_path("README.md") is False
    assert _is_docs_surface_path(".harness/harness.yaml") is False
    assert _is_docs_surface_path("docs/../AGENTS.md") is False
    assert _is_docs_surface_path("docs/../CLAUDE.md") is False

    assert _is_scratch_surface_path(".harness/scratch/shot.png") is True
    assert _is_scratch_surface_path(".harness/scratch/sub/dump.html") is True
    assert _is_scratch_surface_path(".harness/scratch") is False
    assert _is_scratch_surface_path(".harness/scratch/../../src/main.py") is False
    assert _is_scratch_surface_path(".harness/work/x.md") is False
    assert _is_scratch_surface_path("src/main.py") is False

    assert _is_work_surface_path(".harness/work/nova-feature/spec.md") is True
    assert _is_work_surface_path(".harness/work/../../AGENTS.md") is False
    assert _is_work_surface_path(".harness/work/../../src/evil.py") is False
    assert _is_work_surface_path("docs/x.md") is False


def test_install_creates_self_ignoring_scratch_gitignore(tmp_path: Path) -> None:
    """install_boundary_guard cria .harness/scratch/.gitignore auto-contido
    (`*` + `!.gitignore`) — git status limpo sem tocar no .gitignore da raiz
    do usuário. Não sobrescreve um .gitignore customizado já existente."""
    install_boundary_guard(tmp_path)
    gitignore = tmp_path / ".harness" / "scratch" / ".gitignore"
    assert gitignore.is_file()
    content = gitignore.read_text(encoding="utf-8")
    assert "*" in content and "!.gitignore" in content

    gitignore.write_text("# customizado\n*.png\n", encoding="utf-8")
    install_boundary_guard(tmp_path)
    assert gitignore.read_text(encoding="utf-8") == "# customizado\n*.png\n"


def test_write_work_dir_traversal_denies(tmp_path: Path) -> None:
    """Regressão end-to-end do furo de traversal: um Write com segmentos ..
    escapando de .harness/work/ não pode virar allow pela exceção de work.
    Payload sem cwd (a âncora de repo_root gravada pelo install resolve a
    raiz) — evita que _absolutize_against_payload_cwd normalize o path antes
    de o check de superfície rodar."""
    _contract_with_verify(tmp_path)
    script = _script(tmp_path)
    for rel in (".harness/work/../../AGENTS.md",
                ".harness/scratch/../../AGENTS.md"):
        out = _run_hook(script, {"tool_name": "Write", "cwd": "",
                                  "tool_input": {"file_path": rel, "content": "x"}})
        assert out["permissionDecision"] == "deny", (rel, out)


# -------- issue 3 do dogfood venv-Windows: bookkeeping do harness + escape task --------


def test_progress_md_is_writable_but_only_the_canonical_one(tmp_path: Path) -> None:
    """`.harness/progress.md` é gerado/mantido pelo próprio harness (o lifecycle,
    passo 12, manda atualizá-lo) — negar a escrita era auto-derrotante. A
    superfície é do arquivo canônico da RAIZ: homônimo em subdiretório não ganha
    carona."""
    _contract_with_verify(tmp_path)
    _expect(
        _script(tmp_path),
        write(".harness/progress.md", "allow"),
        write(".HARNESS/PROGRESS.MD", "allow"),
        Case("Edit", {"file_path": str(tmp_path / ".harness/progress.md"),
                      "old_string": "a", "new_string": "b"},
             "allow", why="path absoluto, a forma que a tool manda na pratica"),
        write("src/.harness/progress.md", "deny", why="homonimo em subdiretorio"),
    )


def test_is_progress_file_path_importable() -> None:
    from harness.boundary_guard import _is_progress_file_path

    assert _is_progress_file_path(".harness/progress.md") is True
    assert _is_progress_file_path(".HARNESS/PROGRESS.MD") is True
    assert _is_progress_file_path("docs/../.harness/progress.md") is True
    assert _is_progress_file_path("src/.harness/progress.md") is False
    assert _is_progress_file_path("progress.md") is False
    assert _is_progress_file_path(".harness/sub/progress.md") is False
    assert _is_progress_file_path(".harness/progress.md.bak") is False
    assert _is_progress_file_path("") is False


# -------- issues 1-2 do dogfood venv-Windows: shell read-only + cd intra-repo + 2>&1 --------

def test_bash_readonly_utilities_and_intra_repo_cd_are_allowed(tmp_path: Path) -> None:
    """Issue 1: `<allowed> | head -N` era o papercut nº1, e utilitário de
    leitura sozinho não tinha ganho de segurança nenhum em ser negado.

    Duas adaptações vieram do parecer cético: `>` DENTRO de aspas é padrão de
    busca (`->`, `<div>`), não redirect; e `2>&1` é duplicação de fd, nenhum
    arquivo escrito — o splitter cortava no `&` e o segmento `1` órfão derrubava
    o comando inteiro.

    `cd <subdir> && <allowed>` é muscle-memory universal (issue 2). Sai do repo,
    porém, é deny: `git add`/`commit` são liberados incondicionalmente e
    operariam em OUTRO repositório."""
    _contract_with_verify(tmp_path)
    _expect(
        _script(tmp_path),
        bash("pytest -q | head -40", "allow"),
        bash("pytest -q | tail -20", "allow"),
        bash("pytest -q | grep FAILED | wc -l", "allow"),
        bash("wc -l .harness/scratch/build.log", "allow"),
        bash("tail -50 .harness/scratch/task.output", "allow"),
        bash("ls -la src", "allow"),
        bash("cat README.md", "allow"),
        bash('grep -rn "TODO" src', "allow"),
        bash('grep "->" -r src', "allow", why="> entre aspas e padrao de busca"),
        bash('grep "=>" src/app.ts', "allow", why="> entre aspas e padrao de busca"),
        bash("grep '>' arquivo.xml", "allow", why="> entre aspas e padrao de busca"),
        bash("pytest -q 2>&1", "allow", why="2>&1 nao escreve arquivo"),
        bash("pytest -q 2>&1 | tail -30", "allow"),
        bash("find src -name '*.py' -type f", "allow", why="find de busca pura"),
        bash("rg --pretty padrao src", "allow", why="--pretty nao executa nada"),
        bash("cd frontend && pytest -q", "allow"),
        bash(f'cd "{tmp_path.as_posix()}" && pytest -q', "allow",
             why="path absoluto do proprio repo, em forma POSIX"),
        bash("cd . && git status", "allow"),
    )


def test_bash_readonly_allowlist_never_covers_a_write_or_an_exec(tmp_path: Path) -> None:
    """A guarda inegociável do issue 1: utilitário da allowlist + redirect de
    escrita fora de aspas é escrita fora da superfície de arquivos.

    Os três achados do cético estão aqui: `find` escreve SEM `>` via
    `-fprint`/`-fprintf`/`-fls` (furaria até o floor de segredo com
    `find . -fprint .env`) e executa via `-delete`/`-exec`/`-ok`; `rg --pre <cmd>`
    executa comando arbitrário por arquivo; e `<(cmd)` executa o cmd sem que o
    check de `$(`/crase o cubra.

    E a mensagem cita QUAL segmento derrubou o comando — a genérica atrasava o
    diagnóstico (issue 2)."""
    _contract_with_verify(tmp_path)
    _expect(
        _script(tmp_path),
        bash("echo x > src/app.py", "deny"),
        bash("cat a.txt > b.txt", "deny"),
        bash("grep -r TODO src >> dump.txt", "deny"),
        bash("head -1 f >&saida.txt", "deny"),
        bash("find . -name '*.py' -delete", "deny"),
        bash("find . -name '*.py' -exec rm {} ;", "deny"),
        bash("find . -fprint .env", "deny"),
        bash("find . -fprintf saida.txt %p", "deny"),
        bash("find . -fls listagem.txt", "deny"),
        bash("find . -okdir rm {} ;", "deny"),
        bash("rg --pre malicioso padrao .", "deny"),
        bash("rg --pre=malicioso padrao", "deny"),
        bash("rg --hostname-bin=evil padrao", "deny"),
        bash("grep --pre x padrao f", "deny"),
        bash("cat <(comando-malicioso)", "deny", why="process substitution executa"),
        bash("cd C:/outro-repo && pytest -q", "deny", why="cd para fora do repo"),
        bash("cd .. && git add .", "deny"),
        bash("cd $HOME && pytest -q", "deny"),
        bash("cd ~ && pytest -q", "deny"),
        bash("cd - && pytest -q", "deny"),
        bash("pytest -q && rm -rf src", "deny", reason="segmento 'rm -rf src'",
             why="o deny cita o segmento que derrubou"),
    )


def test_readonly_helpers_importable() -> None:
    from harness.boundary_guard import (
        _is_readonly_shell_segment,
        _is_safe_cd_segment,
        _segment_has_file_redirect,
    )

    assert _segment_has_file_redirect("echo x > f.txt") is True
    assert _segment_has_file_redirect("cmd >> f.txt") is True
    assert _segment_has_file_redirect("cmd >&arquivo") is True
    assert _segment_has_file_redirect("pytest -q 2>&1") is False
    assert _segment_has_file_redirect('grep ">" f') is False
    assert _segment_has_file_redirect("grep '->' src") is False

    assert _is_readonly_shell_segment("head -40") is True
    assert _is_readonly_shell_segment("/usr/bin/grep -r x src") is True
    assert _is_readonly_shell_segment("grep.exe -r x src") is True
    assert _is_readonly_shell_segment("tee saida.txt") is False
    assert _is_readonly_shell_segment("find . -fprint0 f") is False
    assert _is_readonly_shell_segment("rg --pre-glob=*.py --pre=x padrao") is False

    root = "C:/Projetos/demo" if sys.platform.startswith("win") else "/home/u/demo"
    assert _is_safe_cd_segment("cd sub/dir", root) is True
    assert _is_safe_cd_segment('cd "pasta com espaco"', root) is True
    assert _is_safe_cd_segment("cd ..", root) is False
    assert _is_safe_cd_segment("cd sub/../..", root) is False
    assert _is_safe_cd_segment("cd $VAR", root) is False
    assert _is_safe_cd_segment("cd sub", "") is False  # sem âncora -> não aceita
    assert _is_safe_cd_segment("cdx algo", root) is False


# ---------------- Item 6: raiz do repo fixada (deriva de cwd) ----------------

def test_repo_root_anchor_survives_a_derived_cwd(tmp_path: Path) -> None:
    """Cenário central do Item 6: o `cwd` do payload "derivou" (o agente rodou
    `cd frontend/` e não voltou) mas `compile-session` já gravou `repo_root` em
    `compiled-state-session.json`. A avaliação tem que se ancorar na raiz
    gravada, para Edit e para Bash.

    O motivo do allow importa tanto quanto o allow: "sem contrato ativo" seria o
    SINTOMA fail-open que este item corrige, não a correção. E as provas
    negativas garantem que a âncora não degenerou num allow geral."""
    _contract_with_verify(tmp_path)  # files=["src/main.py"], verify_cmd="pytest -q"
    script = _script(tmp_path)  # grava repo_root = str(tmp_path.resolve())
    derivado = str(tmp_path / "frontend")  # não precisa existir em disco
    _expect(
        script,
        Case("Edit", {"file_path": str(tmp_path / "src" / "main.py"),
                      "old_string": "x", "new_string": "y"},
             "allow", reason="declarado em files", absent="sem contrato ativo",
             cwd=derivado, why="path absoluto in-surface, cwd derivado"),
        Case("Edit", {"file_path": str(tmp_path / "unrelated" / "other.py"),
                      "old_string": "x", "new_string": "y"},
             "deny", reason="fora da superficie", cwd=derivado,
             why="path absoluto out-of-surface nao vira allow geral"),
        Case("Bash", {"command": "pytest -q"}, "allow", absent="sem contrato ativo",
             cwd=derivado, why="a mesma ancora vale no caminho Bash"),
        edit("src/main.py", "allow", reason="declarado em files",
             why="regressao: sem deriva, o resultado e identico ao de antes"),
    )


def test_derived_cwd_absolutizes_a_relative_path_before_anchoring(tmp_path: Path) -> None:
    """Ressalva 3b (validação Opus pós-implementação): trocar `cwd` pela âncora
    resolve certo para `file_path` ABSOLUTO, mas um `file_path` RELATIVO a um
    `cwd` derivado (shell preso em `<repo>/frontend`, tool manda `x.ts` querendo
    `frontend/x.ts`) precisa ser absolutizado contra o `cwd` ORIGINAL do payload
    ANTES do strip pela âncora — senão `x.ts` cru seria avaliado contra a raiz e
    daria falso-deny.

    A prova negativa vem junto: a correção resolve o path, não abre allow."""
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["frontend/x.ts"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    derivado = str(tmp_path / "frontend")
    _expect(
        _script(tmp_path),
        Case("Edit", {"file_path": "x.ts", "old_string": "a", "new_string": "b"},
             "allow", reason="declarado em files", absent="sem contrato ativo",
             cwd=derivado, why="x.ts + cwd <repo>/frontend vira frontend/x.ts"),
    )

    fora = tmp_path / "fora-da-superficie"
    fora.mkdir()
    _write_feature_list(fora, [
        {"id": "T-01", "desc": "x", "files": ["frontend/y.ts"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    _expect(
        _script(fora),
        Case("Edit", {"file_path": "x.ts", "old_string": "a", "new_string": "b"},
             "deny", reason="fora da superficie", cwd=str(fora / "frontend"),
             why="mesma absolutizacao, path que nao casa files[]"),
    )


def test_missing_repo_root_key_falls_back_to_current_cwd_behavior(tmp_path: Path) -> None:
    """Repo sem `compile-session` recente (ou compilado por uma versão
    anterior a este item): `compiled-state-session.json` existe (tem
    `boundary_guard_hook_command`) mas NÃO tem `repo_root`. Fallback
    obrigatório: comportamento ATUAL (usa o `cwd` do payload) — com `cwd`
    derivado, isso reproduz o sintoma fail-open PRÉ-existente (não piora,
    não quebra; só não é corrigido sem a chave), provando que o fallback não
    regride quem nunca rodou `compile-session` com esta versão."""
    _contract_with_verify(tmp_path)
    script = _script(tmp_path)

    state_path = tmp_path / SESSION_STATE_FILE
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert REPO_ROOT_STATE_KEY in state  # sanity: install_boundary_guard grava por padrão
    del state[REPO_ROOT_STATE_KEY]
    state_path.write_text(json.dumps(state), encoding="utf-8")

    derived_cwd = str(tmp_path / "frontend")
    absolute_target = str(tmp_path / "src" / "main.py")
    out = _run_hook(script, {
        "tool_name": "Edit", "cwd": derived_cwd,
        "tool_input": {"file_path": absolute_target, "old_string": "x", "new_string": "y"},
    })
    # sem a chave, cai no cwd do payload (derivado) -> _load_json não acha
    # feature_list.json sob <tmp_path>/frontend. Com o fix Fase 2 (default-deny
    # sem contrato), essa situação agora retorna deny em vez de fail-open allow.
    # (Um contrato EXISTE, mas em lugar inacessível por causa do cwd derivado —
    # é falha de ancoragem, tratada corretamente: nega em vez de deixar passar.)
    assert out["permissionDecision"] == "deny", out
    assert "nenhum contrato ativo" in out["permissionDecisionReason"], out


def test_install_boundary_guard_writes_repo_root_preserving_other_keys(tmp_path: Path) -> None:
    """`install_boundary_guard` grava `REPO_ROOT_STATE_KEY` = raiz absoluta,
    sem apagar chaves já gravadas por outros mecanismos (merge
    não-destrutivo, mesmo padrão já usado por `BOUNDARY_STATE_KEY`)."""
    state_path = tmp_path / SESSION_STATE_FILE
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"managed_session_permissions": ["Bash(pytest -q)"]}),
                           encoding="utf-8")

    install_boundary_guard(tmp_path)

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["managed_session_permissions"] == ["Bash(pytest -q)"]
    assert state[REPO_ROOT_STATE_KEY] == str(tmp_path.resolve())
    assert BOUNDARY_STATE_KEY in state


def test_session_state_degrades_without_crashing(tmp_path: Path) -> None:
    """Sem `compiled-state-session.json`, ou com ele corrompido, o hook não pode
    quebrar — só não há âncora a aplicar, e cai no `cwd` do payload (sem drift
    nestes casos). A prova de que não houve crash é o `proc.returncode == 0`
    verificado dentro de `_run_hook`."""
    _contract_with_verify(tmp_path)
    script = _script(tmp_path)

    (tmp_path / SESSION_STATE_FILE).unlink()
    _expect(script, edit("src/main.py", "allow", why="state ausente"))

    (tmp_path / SESSION_STATE_FILE).write_text("{ isto nao e json valido", encoding="utf-8")
    _expect(script, edit("src/main.py", "allow", why="state com JSON invalido"))


def test_find_session_state_path_climbs_until_it_finds_or_gives_up(tmp_path: Path) -> None:
    """A busca sobe por VÁRIOS níveis, não só um — simula o script instalado bem
    mais fundo que `.harness/hooks`. Não deveria acontecer na prática, mas prova
    que o mecanismo não depende de uma profundidade fixa hardcoded."""
    from harness.boundary_guard import _find_session_state_path

    assert _find_session_state_path(tmp_path) is None

    state_path = tmp_path / SESSION_STATE_FILE
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({REPO_ROOT_STATE_KEY: str(tmp_path)}), encoding="utf-8")

    deep_dir = tmp_path / "a" / "b" / "c" / "d"
    deep_dir.mkdir(parents=True, exist_ok=True)
    assert _find_session_state_path(deep_dir) == state_path.resolve()


def test_resolve_repo_root_anchor_importable(tmp_path: Path) -> None:
    """Testes diretos (sem subprocess) das peças puras: acha o state
    subindo a partir de um diretório filho, lê `repo_root`, e devolve `None`
    nos casos de fallback (sem arquivo, sem chave, JSON inválido, diretório
    inexistente)."""
    from harness.boundary_guard import (
        _find_session_state_path,
        _read_repo_root_from_state,
        _resolve_repo_root_anchor,
    )

    state_path = tmp_path / SESSION_STATE_FILE
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({REPO_ROOT_STATE_KEY: str(tmp_path)}), encoding="utf-8")

    # simula o script instalado em <tmp_path>/.harness/hooks/boundary_guard.py
    hooks_dir = tmp_path / ".harness" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    fake_script = hooks_dir / "boundary_guard.py"
    fake_script.write_text("# fake", encoding="utf-8")

    found = _find_session_state_path(hooks_dir)
    assert found == state_path.resolve()
    assert _read_repo_root_from_state(found) == str(tmp_path)
    assert _resolve_repo_root_anchor(str(fake_script)) == str(tmp_path)

    # sem a chave
    state_path.write_text(json.dumps({"outra_chave": 1}), encoding="utf-8")
    assert _resolve_repo_root_anchor(str(fake_script)) is None

    # JSON inválido
    state_path.write_text("{ nao e json", encoding="utf-8")
    assert _resolve_repo_root_anchor(str(fake_script)) is None

    # diretório gravado não existe mais
    state_path.write_text(json.dumps({REPO_ROOT_STATE_KEY: str(tmp_path / "nao-existe")}),
                           encoding="utf-8")
    assert _resolve_repo_root_anchor(str(fake_script)) is None

    # sem o arquivo de state (deletado)
    state_path.unlink()
    assert _resolve_repo_root_anchor(str(fake_script)) is None


# ---------------- governance.extra_allowed_commands (harness.yaml) ----------------

def test_load_extra_allowed_commands_degrades_to_empty(tmp_path: Path) -> None:
    """YAML ausente ou quebrado nunca vira allow: a falta de configuração lê
    como lista vazia, não como permissão."""
    from harness.boundary_guard import load_extra_allowed_commands

    assert load_extra_allowed_commands(tmp_path) == []

    _write_harness_yaml(tmp_path, ["python -m mar_committee"])
    assert load_extra_allowed_commands(tmp_path) == ["python -m mar_committee"]

    (tmp_path / ".harness" / "harness.yaml").write_text(
        "governance: [isto nao fecha", encoding="utf-8")
    assert load_extra_allowed_commands(tmp_path) == []


def test_extra_allowed_command_widens_by_token_prefix_and_nothing_else(
    tmp_path: Path,
) -> None:
    """CLI do produto declarada em `extra_allowed_commands` fica liberada mesmo
    sem `verify_cmd` cobrindo — cenário real do dogfood entebate. Vale nas duas
    superfícies de comando.

    O match continua sendo de TOKENS, não substring solta: um binário cujo nome
    apenas COMEÇA com o declarado (`mar_committee_evil`) não passa. O Item 4
    mudou o caso vizinho de propósito — `mar_committee --help` com `python -m
    mar_committee` declarado é ALLOW, porque as duas formas invocam o mesmo
    binário —, e o que este teste fixa é que a normalização não afrouxou a
    fronteira de token.

    E declarar uma sequência do runtime floor não a libera: o floor roda
    incondicionalmente antes de qualquer checagem de superfície."""
    _contract_with_verify(tmp_path)
    _write_harness_yaml(tmp_path, ["python -m mar_committee"])
    _expect(
        _script(tmp_path),
        bash("python -m mar_committee --help", "allow"),
        bash("python -m mar_committee config-show", "allow"),
        pwsh("python -m mar_committee config-show", "allow"),
        bash("mar_committee_evil --help", "deny"),
        bash("mar_committeex", "deny"),
    )

    no_floor = tmp_path / "declara-o-floor"
    no_floor.mkdir()
    _contract_with_verify(no_floor)
    _write_harness_yaml(no_floor, ["git push"])
    _expect(
        _script(no_floor),
        bash("git push origin main", "deny", reason="runtime floor"),
    )

    sem_yaml = tmp_path / "sem-yaml"
    sem_yaml.mkdir()
    _contract_with_verify(sem_yaml)
    _expect(
        _script(sem_yaml),
        bash("python -m mar_committee --help", "deny",
             why="sem harness.yaml o hook se comporta como antes da feature"),
    )

def _write_harness_yaml(target: Path, extra_allowed_commands: list[str]) -> None:
    path = target / ".harness" / "harness.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["governance:", "  extra_allowed_commands:"]
    lines.extend(f'    - "{cmd}"' for cmd in extra_allowed_commands)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------- branches protegidas: git commit só via PR ----------------

def _write_git_head(target: Path, content: str) -> None:
    """Simula o estado de branch escrevendo `.git/HEAD` direto — o guard lê
    só esse arquivo (stdlib, sem subprocess git), então não precisa de um
    repo git real aqui."""
    git_dir = target / ".git"
    git_dir.mkdir(parents=True, exist_ok=True)
    (git_dir / "HEAD").write_text(content, encoding="utf-8")


def _on_branch(target: Path, branch: str | None):
    """`before` de um Case: põe o repo na branch dada (ou em detached HEAD)."""
    ref = ("a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2\n" if branch is None
           else f"ref: refs/heads/{branch}\n")
    return lambda: _write_git_head(target, ref)


def test_git_commit_is_denied_on_a_protected_branch(tmp_path: Path) -> None:
    """Finding C (dogfood 2026-07-22): a regra "nunca commit direto na main, só
    via PR" virou floor — vale com ou sem contrato ativo, no Bash e no
    PowerShell. Só COMMIT é negado: preparar staging não viola a regra do PR.

    Detached HEAD é fail-OPEN aqui (o oposto da postura do push): sem branch não
    há branch protegida a violar, e travar o commit nesse estado atrapalharia
    rebase interativo sem proteger nada."""
    _contract_with_verify(tmp_path)
    _expect(
        _script(tmp_path),
        bash("git commit -m x", "deny", reason="protegida", before=_on_branch(tmp_path, "main")),
        bash("git commit -m x", "deny", reason="protegida",
             before=_on_branch(tmp_path, "homolog")),
        bash("git commit -m x", "deny", reason="protegida",
             before=_on_branch(tmp_path, "develop")),
        pwsh("git commit -m x", "deny", reason="protegida",
             before=_on_branch(tmp_path, "develop")),
        bash("git commit -m x", "allow", before=_on_branch(tmp_path, "contract/exemplo-feature")),
        bash("git commit -m x", "allow", before=_on_branch(tmp_path, None),
             why="detached HEAD e fail-open no commit"),
        bash("git status", "allow", before=_on_branch(tmp_path, "main")),
        bash("git add .", "allow", before=_on_branch(tmp_path, "main")),
        bash("git diff", "allow", before=_on_branch(tmp_path, "main")),
    )

    sem_contrato = tmp_path / "sem-contrato"
    sem_contrato.mkdir()
    _write_git_head(sem_contrato, "ref: refs/heads/main\n")
    _expect(
        _script(sem_contrato),
        bash("git commit -m x", "deny", reason="protegida",
             why="a regra e incondicional: vale sem contrato"),
    )


def test_protected_branches_override_from_harness_yaml(tmp_path: Path) -> None:
    """`governance.protected_branches` do harness.yaml é bakeado no script
    gerado (mesmo padrão de EXTRA_ALLOWED_COMMANDS): override substitui o
    default — main deixa de ser protegida se o dono declarar só trunk."""
    _contract_with_verify(tmp_path)
    yaml_path = tmp_path / ".harness" / "harness.yaml"
    yaml_path.write_text(
        "governance:\n  protected_branches:\n    - trunk\n", encoding="utf-8"
    )
    script = _script(tmp_path)

    _write_git_head(tmp_path, "ref: refs/heads/trunk\n")
    out = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                              "tool_input": {"command": "git commit -m x"}})
    assert out["permissionDecision"] == "deny", out

    _write_git_head(tmp_path, "ref: refs/heads/main\n")
    out = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                              "tool_input": {"command": "git commit -m x"}})
    assert out["permissionDecision"] == "allow", out


# ---------------- push: floor escopado à branch do contrato (item 6, dogfood miojo) ----------------

from harness.boundary_guard import (  # noqa: E402
    contract_branch_push_problem,
    is_floor_bash_command,
    is_git_push_command,
)

_PROTECTED = ("main", "homolog", "develop")


def _push(script: Path, tmp_path: Path, command: str, tool: str = "Bash") -> dict:
    return _run_hook(script, {"tool_name": tool, "cwd": str(tmp_path),
                              "tool_input": {"command": command}})


def test_push_is_allowed_only_on_the_active_contract_branch(tmp_path: Path) -> None:
    """Item 6 do backlog do dogfood miojo: `git push` era deny incondicional,
    inclusive na `contract/<slug>` que a própria sessão criou — o humano tinha
    que rodar o push à mão no fim de um ciclo cuja aprovação real (o contrato)
    já tinha acontecido.

    A exceção é estreita e fail-CLOSED. Detached HEAD nega — postura OPOSTA à do
    floor de commit, porque não saber a branch é exatamente o caso em que o push
    pode ir para onde não devia. E a branch certa não basta: reescrita de
    histórico, refspec explícito, destino diferente da branch atual e
    encadeamento seguem floor."""
    _contract_with_verify(tmp_path)
    na_branch = _on_branch(tmp_path, "contract/test")
    _expect(
        _script(tmp_path),
        bash("git push", "allow", before=na_branch),
        bash("git push origin", "allow", before=na_branch),
        bash("git push -u origin contract/test", "allow", before=na_branch),
        bash("git push --set-upstream origin contract/test", "allow", before=na_branch),
        pwsh("git push -u origin contract/test", "allow", before=na_branch,
             why="as duas superficies respondem igual sobre push"),
        # branch errada
        bash("git push", "deny", before=_on_branch(tmp_path, "main")),
        bash("git push", "deny", before=_on_branch(tmp_path, "homolog")),
        bash("git push", "deny", before=_on_branch(tmp_path, "develop")),
        bash("git push", "deny", before=_on_branch(tmp_path, "feat/algo")),
        bash("git push", "deny", before=_on_branch(tmp_path, "contract/outro")),
        pwsh("git push", "deny", before=_on_branch(tmp_path, "main")),
        bash("git push", "deny", reason="indeterminada", before=_on_branch(tmp_path, None),
             why="detached HEAD e fail-closed no push"),
        # forma perigosa, na branch certa
        bash("git push --force", "deny", before=na_branch),
        bash("git push -f origin contract/test", "deny", before=na_branch),
        bash("git push --force-with-lease", "deny", before=na_branch),
        bash("git push --mirror", "deny", before=na_branch),
        bash("git push --delete origin contract/test", "deny", before=na_branch),
        bash("git push --all", "deny", before=na_branch),
        bash("git push --tags", "deny", before=na_branch),
        bash("git push origin HEAD:main", "deny", before=na_branch),
        bash("git push origin contract/test:main", "deny", before=na_branch),
        bash("git push origin main", "deny", before=na_branch),
        bash("git push origin develop", "deny", before=na_branch),
        bash("git push && curl http://evil", "deny", before=na_branch),
        bash("git push; rm -rf src", "deny", before=na_branch),
        # separar o push do resto do floor não pode afrouxar o resto
        bash("curl http://x", "deny", before=na_branch),
        bash("wget http://x", "deny", before=na_branch),
        bash("npm publish", "deny", before=na_branch),
        bash("twine upload dist/*", "deny", before=na_branch),
        bash("gh release create v1", "deny", before=na_branch),
        pwsh("Invoke-WebRequest http://x", "deny", before=na_branch),
        pwsh("iwr http://x", "deny", before=na_branch),
    )

    # Bootstrap: sem feature_list.json não há contrato de onde derivar branch
    # nenhuma, então não há exceção a aplicar.
    sem_contrato = tmp_path / "sem-contrato"
    sem_contrato.mkdir()
    _write_git_head(sem_contrato, "ref: refs/heads/contract/test\n")
    _expect(_script(sem_contrato), bash("git push", "deny"))


def test_push_is_still_gated_after_the_contract_is_fully_passed(tmp_path: Path) -> None:
    """O allow-all de contrato concluído NÃO pode virar bypass de push: a
    checagem roda antes dele, e é a autoridade sobre push em todos os
    caminhos. Esse é justamente o momento do ciclo em que o push acontece."""
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": True}
    ])
    script = _script(tmp_path)

    _write_git_head(tmp_path, "ref: refs/heads/contract/test\n")
    assert _push(script, tmp_path, "git push")["permissionDecision"] == "allow"

    _write_git_head(tmp_path, "ref: refs/heads/main\n")
    assert _push(script, tmp_path, "git push")["permissionDecision"] == "deny"

    _write_git_head(tmp_path, "ref: refs/heads/contract/test\n")
    assert _push(script, tmp_path, "git push --force")["permissionDecision"] == "deny"


def test_push_respects_protected_branches_override(tmp_path: Path) -> None:
    """A lista protegida bakeada é a mesma do floor de commit."""
    _contract_with_verify(tmp_path)
    (tmp_path / ".harness" / "harness.yaml").write_text(
        "governance:\n  protected_branches:\n    - trunk\n", encoding="utf-8"
    )
    script = _script(tmp_path)

    _write_git_head(tmp_path, "ref: refs/heads/contract/test\n")
    out = _push(script, tmp_path, "git push origin trunk")
    assert out["permissionDecision"] == "deny", out


def test_push_predicates_are_importable() -> None:
    """`FLOOR_BASH_SEQUENCES` não mudou de propósito: é o que mantém
    `verify.run_verify`, o dry-check de contrato e o filtro do
    `settings.local.json` recusando push. E `is_git_push_command` casa por
    PREFIXO, não por janela — um push colado depois de outro comando não é um
    push isolado e não pode entrar na exceção."""
    assert is_floor_bash_command("git push") is True
    assert is_floor_bash_command(".venv/Scripts/git.exe push") is True

    assert is_git_push_command("git push") is True
    assert is_git_push_command(".venv/Scripts/git.exe push origin x") is True
    assert is_git_push_command("uv run git push") is True
    assert is_git_push_command("echo ok && git push") is False
    assert is_git_push_command("curl http://x") is False

    for command in ("git push", "git push origin", "git push -u origin contract/slug"):
        assert contract_branch_push_problem(
            command, "contract/slug", "slug", _PROTECTED
        ) is None, command

    for command, branch, slug in (
        ("git push", "main", "slug"),                       # branch protegida
        ("git push", "feat/x", "slug"),                     # não é a do contrato
        ("git push", None, "slug"),                         # branch desconhecida
        ("git push", "contract/slug", ""),                  # sem contrato ativo
        ("git push --force", "contract/slug", "slug"),      # reescrita de histórico
        ("git push origin main", "contract/slug", "slug"),  # destino diferente
        ("git push origin a:b", "contract/slug", "slug"),   # refspec explícito
        ("git push a b c", "contract/slug", "slug"),        # argumentos demais
        ("git push | tee /tmp/x", "contract/slug", "slug"),  # encadeado
        ("curl http://x", "contract/slug", "slug"),         # nem é push
    ):
        problem = contract_branch_push_problem(command, branch, slug, _PROTECTED)
        assert problem is not None, command
        assert "floor" in problem, command


# ---------------- kill-switch: floor anti-auto-desativação + short-circuit ----------------

from harness.boundary_guard import (  # noqa: E402
    is_floor_bash_disable_redirect,
    is_floor_disable_command,
    is_floor_disable_sentinel_path,
)


def _sentinel(tmp_path: Path) -> Path:
    return tmp_path / ".harness" / "harness.disabled"


def test_disable_predicates_are_importable() -> None:
    assert is_floor_disable_sentinel_path(".harness/harness.disabled") is True
    assert is_floor_disable_sentinel_path("harness.disabled") is True
    assert is_floor_disable_sentinel_path("src/harness/killswitch.py") is False

    assert is_floor_disable_command("harness disable") is True
    assert is_floor_disable_command("python -m harness.cli disable") is True
    assert is_floor_disable_command("harness disable --note x") is True
    assert is_floor_disable_command("harness enable") is False
    assert is_floor_disable_command("harness status") is False
    assert is_floor_disable_command("pytest tests -q") is False

    assert is_floor_bash_disable_redirect("echo x > .harness/harness.disabled") is True
    assert is_floor_bash_disable_redirect("echo x | tee .harness/harness.disabled") is True
    assert is_floor_bash_disable_redirect("echo x > out.txt") is False


def test_the_agent_can_never_disable_the_harness_itself(tmp_path: Path) -> None:
    """Floor incondicional, por toda rota: o subcomando (nas duas grafias e nas
    duas superfícies de comando) e a criação do sentinel à mão (Write ou
    redirect de shell). Desligar o guard é decisão do humano, no terminal
    dele."""
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/x.py"], "verify_cmd": "pytest", "passes": False},
    ])
    _write_profile(tmp_path)
    _expect(
        _script(tmp_path),
        bash("harness disable", "deny"),
        bash("python -m harness.cli disable", "deny"),
        pwsh("harness disable", "deny"),
        write(str(_sentinel(tmp_path)), "deny", why="cria o sentinel a mao"),
        bash("echo x > .harness/harness.disabled", "deny", why="cria o sentinel por redirect"),
    )

    sem_contrato = tmp_path / "sem-contrato"
    sem_contrato.mkdir()
    _expect(_script(sem_contrato), bash("harness disable", "deny",
                                        why="floor vale sem contrato tambem"))


def test_hook_short_circuits_to_allow_when_sentinel_present(tmp_path: Path) -> None:
    """Sentinel presente (harness desativado) -> qualquer tool call vira allow,
    mesmo uma que normalmente seria negada (comando arbitrário com contrato
    ativo)."""
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/x.py"], "verify_cmd": "pytest", "passes": False},
    ])
    _write_profile(tmp_path)
    script = _script(tmp_path)

    # sem sentinel: comando arbitrário é negado
    out = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                             "tool_input": {"command": "rm -rf algo"}})
    assert out["permissionDecision"] == "deny", out

    # com sentinel: short-circuit -> allow
    _sentinel(tmp_path).write_text("{}", encoding="utf-8")
    out = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                             "tool_input": {"command": "rm -rf algo"}})
    assert out["permissionDecision"] == "allow", out


def test_install_ignores_every_machine_local_artifact(tmp_path: Path) -> None:
    """Itens 2 e 3 do P0: o estado de máquina (`compiled-state*.json`,
    `hooks/`, `settings.local.json`) nasce ignorado por regra que o PRODUTO
    escreve em arquivo tool-owned. Antes disso, o dogfood só parecia limpo
    porque o gitignore GLOBAL da máquina do usuário cobria o settings local —
    nada que o alvo herdasse."""
    _script(tmp_path)

    harness_lines = (tmp_path / ".harness" / ".gitignore").read_text(encoding="utf-8").split()
    for entry in ("compiled-state.json", "compiled-state-session.json", "hooks/",
                  "harness.disabled"):
        assert entry in harness_lines

    claude_lines = (tmp_path / ".claude" / ".gitignore").read_text(encoding="utf-8").split()
    assert "settings.local.json" in claude_lines

    # A raiz do usuário continua intocada — decisão de design preservada.
    assert not (tmp_path / ".gitignore").exists()


# ---------------------------------------------------------------------------
# Feature-lock: identidade de contrato (achado de teste isento)
# ---------------------------------------------------------------------------

def test_feature_lock_denies_evidence_from_another_contract(tmp_path: Path) -> None:
    """A prova de um contrato ANTERIOR não pode destravar `passes:true` numa
    tarefa nunca verificada. Todo contrato começa em `T-01`, então o cenário é
    o normal, não o exótico. Antes existia só o frescor contra o último commit
    — defesa TEMPORAL, que depende de haver um commit entre os dois contratos.

    A evidência aqui está FRESCA e no diretório do contrato ativo (como se
    tivesse sido copiada à mão): o caminho escopado sozinho não pegaria."""
    _init_git_repo_with_commit(tmp_path, "2026-01-01T00:00:00+00:00")
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    _write_evidence(
        tmp_path, "T-01", recorded_at="2026-06-01T00:00:00+00:00",
        contract="contrato-antigo", dir_contract="test",
    )
    script = _script(tmp_path)
    new_content = _feature_list_json([
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": True}
    ])

    out = _run_hook(script, {
        "tool_name": "Write", "cwd": str(tmp_path),
        "tool_input": {"file_path": ".harness/feature_list.json", "content": new_content},
    })

    assert out["permissionDecision"] == "deny", out
    reason = out["permissionDecisionReason"]
    assert "contrato-antigo" in reason and "test" in reason, reason


def test_feature_lock_allows_evidence_of_the_active_contract(tmp_path: Path) -> None:
    """O outro lado: evidência fresca E do contrato ativo continua liberando."""
    _init_git_repo_with_commit(tmp_path, "2026-01-01T00:00:00+00:00")
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    _write_evidence(tmp_path, "T-01", recorded_at="2026-06-01T00:00:00+00:00")
    script = _script(tmp_path)
    new_content = _feature_list_json([
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": True}
    ])

    out = _run_hook(script, {
        "tool_name": "Write", "cwd": str(tmp_path),
        "tool_input": {"file_path": ".harness/feature_list.json", "content": new_content},
    })

    assert out["permissionDecision"] == "allow", out
# ---------------------------------------------------------------------------
# Item 0 do plano v2 — floor do plano de controle (`.harness/**`).
#
# O furo que estes testes fecham foi provado por execução contra o guard do
# HEAD: `harness task add-file T-01 .harness/harness.yaml` (allow) tornava o
# `Write` nesse path allow, o agente escrevia a própria
# `governance.extra_allowed_commands`, `harness compile-session` re-bakeava o
# guard, e um comando fora do floor (`scp`) virava allow. Quatro tool calls,
# nenhum toque humano.
# ---------------------------------------------------------------------------

_CONTROL_PLANE_DENIED = [
    ".harness/harness.yaml",
    ".harness/repo-profile.json",
    ".harness/evidence/T-01.json",
    ".harness/team/manifest.json",
    ".harness/review/T-01.json",
    ".harness/hooks/boundary_guard.py",
    ".harness/compiled-state-session.json",
]


def test_control_plane_write_denied_even_when_declared_in_files(tmp_path: Path) -> None:
    """O núcleo do Item 0: declarar o path em `files[]` NÃO abre exceção.

    Antes, esta era exatamente a rota de auto-ampliação — a superfície do
    contrato governava `.harness/`, e a superfície é ampliável pelo agente."""
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": _CONTROL_PLANE_DENIED,
         "verify_cmd": "pytest -q", "passes": False},
    ])
    script = _script(tmp_path)
    for path in _CONTROL_PLANE_DENIED:
        for tool in ("Write", "Edit", "MultiEdit"):
            out = _run_hook(script, {"tool_name": tool, "cwd": str(tmp_path),
                                     "tool_input": {"file_path": path}})
            assert out["permissionDecision"] == "deny", (path, tool, out)
            assert "plano de controle" in out["permissionDecisionReason"], (path, tool, out)


def test_control_plane_floor_holds_in_every_state(tmp_path: Path) -> None:
    """Postura de floor: vale sem `feature_list.json` — o caminho em que
    `_evaluate_file` devolveria allow por "sem contrato ativo" — e vale com o
    contrato 100% passed, em que o guard se aposenta da SUPERFÍCIE (achado B do
    dogfood 2026-07-22). O floor não se aposenta junto.

    As duas áreas com regra própria continuam sempre graváveis: sem isso o floor
    quebraria o planejamento do próximo contrato. E a mensagem não pode ser um
    beco sem saída — quem precisa mudar governança sai dela sabendo que o
    caminho é o terminal do usuário."""
    _expect(
        _script(tmp_path),
        write(".harness/harness.yaml", "deny", reason="plano de controle",
              why="sem contrato nenhum"),
        write(".harness/work/novo-contrato/spec.md", "allow"),
        write(".harness/work/novo-contrato/Plans.md", "allow"),
        write(".harness/scratch/dump.html", "allow"),
        # os dois bypasses triviais: `..` para entrar por fora, e barra
        # invertida (o path chega Windows-style em algumas tools)
        write(".harness/work/../harness.yaml", "deny"),
        write(".harness/scratch/../../.harness/harness.yaml", "deny"),
        write(r".harness\harness.yaml", "deny"),
        write(".harness/./harness.yaml", "deny"),
    )

    out = _run_hook(_script(tmp_path), {"tool_name": "Write", "cwd": str(tmp_path),
                                        "tool_input": {"file_path": ".harness/harness.yaml"}})
    reason = out["permissionDecisionReason"]
    assert "SEU terminal" in reason, reason
    assert "compile-session" in reason, reason
    assert ".harness/work/" in reason, reason

    concluido = tmp_path / "concluido"
    concluido.mkdir()
    _write_feature_list(concluido, [
        {"id": "T-01", "desc": "x", "files": ["src/app.py"],
         "verify_cmd": "pytest -q", "passes": True},
    ])
    _expect(
        _script(concluido),
        write(".harness/harness.yaml", "deny", reason="plano de controle",
              why="contrato 100% verde nao aposenta o floor"),
    )


def test_control_plane_write_via_bash_redirect_is_denied(tmp_path: Path) -> None:
    """Rota nao coberta pelos testes originais (so exercitavam Write/Edit/
    MultiEdit): gravar no plano de controle por redirecionamento de shell."""
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/a.py"],
         "verify_cmd": "pytest -q", "passes": False},
    ])
    _write_profile(tmp_path)
    _expect(
        _script(tmp_path),
        bash("echo evil > .harness/harness.yaml", "deny"),
        bash("echo evil >> .harness/harness.yaml", "deny"),
        bash("echo evil | tee .harness/harness.yaml", "deny"),
    )


def test_control_plane_floor_blocks_the_proven_amplification_chain(tmp_path: Path) -> None:
    """Regressão da cadeia completa do Item 0, na ordem em que foi executada
    contra o guard do HEAD. Passos 1 e 2 são negados INDEPENDENTEMENTE — é o
    ponto de ter duas camadas; qualquer uma sozinha fecharia a cadeia, e as
    duas juntas sobrevivem a uma delas ser contornada."""
    from harness.contract import ContractError, add_task_file

    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/a.py"],
         "verify_cmd": "pytest -q", "passes": False},
    ])
    _write_profile(tmp_path)
    script = _script(tmp_path)

    # Passo 1 — camada 1: `add-file` recusa o path na entrada.
    plans = tmp_path / ".harness" / "work" / "demo" / "Plans.md"
    plans.parent.mkdir(parents=True, exist_ok=True)
    plans.write_text(
        "## [T-01] x\n- files: `src/a.py`\n- verify: `pytest -q`\n", encoding="utf-8"
    )
    try:
        add_task_file(tmp_path, "demo", "T-01", ".harness/harness.yaml")
        raise AssertionError("add_task_file deveria recusar path do plano de controle")
    except ContractError as exc:
        assert "plano de controle" in str(exc), exc
    # E não escreveu nada: o Plans.md continua sem o path.
    assert ".harness/harness.yaml" not in plans.read_text(encoding="utf-8")

    # Passo 2 — camada 2: mesmo com o path JÁ na superfície (simulando um
    # Plans.md editado à mão, ou um contrato legado já compilado), o Write é
    # negado pelo floor.
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/a.py", ".harness/harness.yaml"],
         "verify_cmd": "pytest -q", "passes": False},
    ])
    out = _run_hook(script, {"tool_name": "Write", "cwd": str(tmp_path),
                             "tool_input": {"file_path": ".harness/harness.yaml"}})
    assert out["permissionDecision"] == "deny", out
    assert "plano de controle" in out["permissionDecisionReason"], out



# ---------------------------------------------------------------------------
# B1 — variantes de path que precisam casar o floor do plano de controle.
#
# O primeiro desenho do floor era prefixo case-SENSITIVE sobre o path ja
# `/`-separado. No Windows -- plataforma exata do dogfood -- `.Harness\x` e
# `.harness\x` sao o MESMO arquivo, entao trocar a caixa contornava as DUAS
# camadas de uma vez: `add_task_file` aceitava o path e o guard devolvia allow.
# As duas camadas compartilhavam o mesmo predicado, entao nao eram duas
# barreiras -- eram uma barreira instanciada duas vezes.
#
# Esta tabela e o teste do DESFECHO ("escrita no plano de controle e negada"),
# nao da rota: qualquer grafia que aponte para o mesmo arquivo tem que cair.
# ---------------------------------------------------------------------------

_CONTROL_PLANE_VARIANTS = [
    ".harness/harness.yaml",
    ".Harness/harness.yaml",
    ".HARNESS/harness.yaml",
    ".hArNeSs/harness.yaml",
    ".harness/HARNESS.YAML",
    r".harness\harness.yaml",
    r".Harness\harness.yaml",
    "./.harness/harness.yaml",
    ".harness/./harness.yaml",
    ".harness/work/../harness.yaml",
    ".Harness/work/../harness.yaml",
    ".harness/scratch/../../.harness/harness.yaml",
    "C:/Projetos/alvo/.harness/harness.yaml",
    r"C:\Projetos\alvo\.harness\harness.yaml",
    "/home/user/alvo/.harness/harness.yaml",
    ".harness/repo-profile.json",
    ".HARNESS/repo-profile.json",
    ".harness/hooks/boundary_guard.py",
    ".harness/evidence/T-01.json",
]


def test_control_plane_predicate_covers_every_path_variant() -> None:
    """O simetrico vem junto: alargar o predicado nao pode engolir path
    legitimo. `.harness-notes/`, `harness/` e homonimos parciais seguem fora."""
    falhas = [v for v in _CONTROL_PLANE_VARIANTS if not is_floor_control_plane_path(v)]
    assert not falhas, f"variantes que escapam do floor: {falhas}"

    for path in (
        "harness/x.py",
        ".harnessfoo/x.py",
        ".harness-notes/x.md",
        "src/.harness_notes.md",
        "docs/harness.yaml",
        "src/dotharness/x.py",
    ):
        assert not is_floor_control_plane_path(path), path


def test_control_plane_floor_denies_every_path_variant(tmp_path: Path) -> None:
    """O desfecho, ponta a ponta, com o path JA declarado em files[] --
    simula a camada 1 contornada e exige que a camada 2 segure sozinha."""
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": list(_CONTROL_PLANE_VARIANTS),
         "verify_cmd": "pytest -q", "passes": False},
    ])
    _expect(_script(tmp_path), *[write(p, "deny") for p in _CONTROL_PLANE_VARIANTS])


# ---------------------------------------------------------------------------
# Item 5 — mensagens de deny apontam o escape barato
# ---------------------------------------------------------------------------

def test_deny_messages_name_the_cheap_escape_first(tmp_path: Path) -> None:
    """O deny de arquivo cita `harness task add-file` com o id PENDENTE (não o
    primeiro da lista: é a tarefa pendente que o agente precisa passar), e o
    replan continua mencionado — mas DEPOIS, como último recurso. O deny de
    comando aponta `extra_allowed_commands` no `harness.yaml`, que é o escape
    que funciona sem recompilar nada."""
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "ja feita", "files": ["src/a.py"],
         "verify_cmd": "pytest -q", "passes": True},
        {"id": "T-07", "desc": "pendente", "files": ["src/b.py"],
         "verify_cmd": "pytest -q", "passes": False},
    ])
    _write_profile(tmp_path)
    script = _script(tmp_path)
    _expect(
        script,
        write("src/novo.py", "deny", reason="harness task add-file T-07 src/novo.py"),
        bash("mypy src", "deny", reason="extra_allowed_commands"),
        bash("mypy src", "deny", reason="harness.yaml"),
    )

    out = _run_hook(script, {"tool_name": "Write", "cwd": str(tmp_path),
                             "tool_input": {"file_path": "src/novo.py"}})
    reason = out["permissionDecisionReason"]
    assert reason.index("add-file") < reason.index("/harness-creator:plan"), reason


def test_protected_branch_deny_refutes_the_commit_message_theory(tmp_path: Path) -> None:
    """Item 5, ponto 2. O texto anterior sugeria `harness compile-session`, que
    não resolve nada quando o problema é estar em `main` — e numa sessão real o
    agente diagnosticou errado, atribuindo o deny à tokenização da mensagem de
    commit e gastando ciclos reescrevendo a mensagem. A mensagem agora nomeia a
    saída (`git checkout -b`) e refuta a hipótese errada explicitamente.

    A refutação vira regressão na segunda metade: fora de branch protegida,
    TODAS as formas de `git commit` são allow."""
    _contract_with_verify(tmp_path)
    _write_git_head(tmp_path, "ref: refs/heads/main\n")
    script = _script(tmp_path)
    _expect(
        script,
        bash("git commit -m x", "deny", reason="git checkout -b"),
        bash("git commit -m x", "deny", reason="MENSAGEM do commit NAO e o problema"),
    )

    fora = _on_branch(tmp_path, "feat/algo")
    _expect(
        script,
        bash("git commit -m x", "allow", before=fora),
        bash('git commit -m "mensagem com espacos e acentuacao"', "allow", before=fora),
        bash("git commit -F -", "allow", before=fora),
        bash("git commit", "allow", before=fora),
        bash('git commit -m "linha 1\nlinha 2"', "allow", before=fora),
    )

# ---------------------------------------------------------------------------
# Floor do plano de controle x progress.md movido (integracao dos dois planos)
# ---------------------------------------------------------------------------

def test_control_plane_floor_lets_only_progress_md_through(tmp_path: Path) -> None:
    """O floor do Item 0 (plano v2 do dogfood venv-Windows) nega `.harness/**` e e
    avaliado ANTES de `_is_progress_file_path`. Como o item 6 do laudo de
    footprint moveu o progresso para `.harness/progress.md`, sem esta excecao
    o agente perderia a escrita no arquivo que o proprio lifecycle (passo 12)
    manda manter e o `runtime_audit` cobra se ausente — a contradicao interna
    que o issue 3 do dogfood venv-Windows existe para corrigir.

    A excecao e de ARQUIVO nomeado, nao de diretorio: `.harness/sub/progress.md`
    e `.harness/progress.md/x` continuam deny."""
    liberados = (".harness/progress.md", ".HARNESS/PROGRESS.MD",
                 ".harness/work/x/spec.md", ".harness/scratch/a.png")
    negados = (".harness/harness.yaml", ".harness/feature_list.json",
               ".harness/hooks/boundary_guard.py", ".harness/compiled-state.json",
               ".harness/sub/progress.md", ".harness/progress.md/x")

    for path in liberados:
        assert is_floor_control_plane_path(path) is False, path
    for path in negados:
        assert is_floor_control_plane_path(path) is True, path


def test_generated_hook_allows_writing_the_moved_progress_file(tmp_path: Path) -> None:
    """Prova de ponta a ponta no hook standalone gerado: o lifecycle continua
    executavel depois do merge dos dois planos."""
    _contract_with_verify(tmp_path)
    script = _script(tmp_path)

    allow = _run_hook(script, {"tool_name": "Write", "cwd": str(tmp_path),
                               "tool_input": {"file_path": ".harness/progress.md",
                                              "content": "# progresso"}})
    assert allow["permissionDecision"] == "allow", allow

    deny = _run_hook(script, {"tool_name": "Write", "cwd": str(tmp_path),
                              "tool_input": {"file_path": ".harness/harness.yaml",
                                             "content": "governance: {}"}})
    assert deny["permissionDecision"] == "deny", deny
    assert "plano de controle" in deny["permissionDecisionReason"]


# ===========================================================================
# Item 4 (dogfood venv-Windows) — normalização da FORMA de invocação
# ===========================================================================

def test_normalize_invocation_tokens_reduces_only_real_equivalences() -> None:
    """`python -c` executa string arbitrária e `python x.py` roda um script —
    nenhum dos dois é invocação de binário nomeado, então normalizar seria
    inventar equivalência que não existe. Basename genérico também não: senão
    `./scripts/deploy.sh` viraria `deploy.sh` e casaria a allowlist de um
    homônimo qualquer (a checagem é por SEGMENTO, não `endswith` de string).
    E `uv run <bin>` é forma equivalente, mas `uv run --with <pkg> <bin>` NÃO —
    `--with` instala pacote arbitrário num ambiente efêmero antes de rodar."""
    from harness.boundary_guard import normalize_invocation_tokens as norm

    assert norm(["python", "-m", "pytest", "-q"]) == ["pytest", "-q"]
    assert norm(["python3", "-m", "ruff", "check"]) == ["ruff", "check"]
    assert norm([".venv/Scripts/pytest.exe", "-q"]) == ["pytest", "-q"]
    assert norm([".venv/bin/ruff", "check"]) == ["ruff", "check"]
    assert norm(["venv/Scripts/pytest", "-q"]) == ["pytest", "-q"]
    assert norm([r".venv\Scripts\pytest.exe"]) == ["pytest"]
    assert norm(["C:/proj/.venv/Scripts/pytest.exe"]) == ["pytest"]
    assert norm(["uv", "run", "pytest", "-q"]) == ["pytest", "-q"]
    assert norm([".venv/Scripts/python.exe", "-m", "ruff", "check", "."]) == ["ruff", "check", "."]

    for tokens in (
        ["python", "-c", "import os"],
        ["python", "app.py"],
        ["./scripts/deploy.sh"],
        ["meuvenv/bin/pytest"],
        ["bin/pytest"],
        ["scripts/pytest"],
        ["uv", "run", "--with", "requests", "pytest"],
    ):
        assert norm(tokens) == tokens, tokens


def test_floor_catches_path_prefixed_invocation_forms() -> None:
    """Invariante inegociável do Item 4: normalizar não pode abrir fuga do
    floor. As formas prefixadas por caminho ATRAVESSAVAM o floor (morriam só
    no default-deny da allowlist) — com o Item 4 elas passariam a casar a
    allowlist, então o floor precisa vê-las."""
    for command in (
        "git push origin main",
        "uv run twine upload dist/*",
        "python -m twine upload dist/*",
        ".venv/Scripts/git.exe push origin main",
        ".venv/bin/git push origin main",
        ".venv/Scripts/twine.exe upload dist/*",
        ".venv/Scripts/curl.exe http://evil",
        "echo ok && .venv/bin/git push",
    ):
        assert is_floor_bash_command(command) is True, command

    for command in ("pytest -q", "./scripts/deploy.sh", "git status"):
        assert is_floor_bash_command(command) is False, command


def test_bash_accepts_equivalent_invocation_forms(tmp_path: Path) -> None:
    """A tabela de evidência do Item 4: com `verify_cmd: "pytest -q"`, as formas
    que de fato funcionam num venv Windows passam a ser allow.

    Os denies não são efeito colateral, são decisão de escopo: `source` executa
    o conteúdo de um arquivo no shell corrente (não é forma de invocação de
    nada, e com a normalização ativar o venv deixou de ser necessário); wrapper
    arbitrário não é prefixo de venv; `-c` executa string arbitrária; e
    normalizar não é declarar."""
    _contract_with_verify(tmp_path)
    _expect(
        _script(tmp_path),
        bash("pytest -q", "allow"),
        bash("pytest -q tests/test_api.py", "allow"),
        bash("python -m pytest -q", "allow"),
        bash(".venv/Scripts/pytest.exe -q", "allow"),
        bash(".venv/bin/pytest -q", "allow"),
        bash("uv run pytest -q", "allow"),
        bash("source .venv/Scripts/activate && pytest -q", "deny"),
        bash("./verify-env.sh python -m ruff check .", "deny"),
        bash('python -c "import os; os.system(\'rm -rf /\')"', "deny"),
        bash("ruff check .", "deny", why="normalizar nao e declarar"),
    )


def test_normalization_applies_to_the_allowlist_entry_without_widening_it(
    tmp_path: Path,
) -> None:
    """O caso SIMÉTRICO: quem precisa normalizar é a entrada da allowlist. Com
    `python -m ruff` declarado, `ruff check .` passa — foi o item 6 do relato
    (`.venv/Scripts/ruff` -> `python -m ruff` -> `.venv/Scripts/ruff`), ida e
    volta que custou um ciclo por tentativa.

    Invariante 2: normalizar muda a FORMA, nunca o ESCOPO. E declarar a forma
    prefixada de um comando de floor não a libera."""
    _contract_with_verify(tmp_path)
    _write_harness_yaml(tmp_path, ["python -m ruff"])
    _expect(
        _script(tmp_path),
        bash("ruff check .", "allow"),
        bash(".venv/Scripts/ruff.exe check .", "allow"),
        bash("uv run ruff check .", "allow"),
    )

    escopo = tmp_path / "escopo"
    escopo.mkdir()
    _contract_with_verify(escopo)
    _write_harness_yaml(escopo, ["pip install -e ."])
    _expect(
        _script(escopo),
        bash("python -m pip install -e .", "allow"),
        bash("python -m pip install evil", "deny",
             why="normaliza para `pip install evil`, que nao prefixa a entrada"),
    )

    floor = tmp_path / "floor"
    floor.mkdir()
    _contract_with_verify(floor)
    _write_harness_yaml(floor, [".venv/Scripts/git.exe push"])
    _expect(
        _script(floor),
        bash(".venv/Scripts/git.exe push origin main", "deny", reason="runtime floor"),
    )

# ===========================================================================
# Postura C do Item 9 — o escape de comando tem que ser trivial
#
# Decisão do dono do repo (2026-07-27): NÃO existe `harness allow-command`. O
# caminho é o usuário editar `.harness/harness.yaml`. Essa decisão só se
# sustenta se editar for trivial — o objetivo declarado do harness é barrar o
# MÍNIMO, porque ele existe para o agente rodar horas sem humano no meio. Todo
# deny que o usuário não resolve em dez segundos empurra para o kill-switch, e
# o kill-switch é desproteção total.
# ===========================================================================

def test_suggested_allowlist_entry_is_canonical_and_keeps_the_mode() -> None:
    """A entrada sugerida é normalizada (a forma prefixada por caminho não vira
    a declaração) e tem binário + subcomando, não a linha inteira: o match é por
    prefixo, e travar nos argumentos obrigaria uma entrada nova por variação.

    A regra de dois tokens, porém, produziria `git checkout` — que casa por
    prefixo e liberaria `git checkout .` (descarte de trabalho não commitado)
    junto com `git checkout -b`. Nos subcomandos de git em que o MODO decide se
    a operação é destrutiva, a sugestão inclui o terceiro token."""
    from harness.boundary_guard import suggested_allowlist_entry as sugerir

    assert sugerir(".venv/Scripts/alembic.exe upgrade head") == "alembic upgrade"
    assert sugerir("python -m mypy src") == "mypy src"
    assert sugerir("alembic upgrade head --sql") == "alembic upgrade"
    assert sugerir("ruff --fix .") == "ruff", "flag nao e subcomando"
    assert sugerir("docker") == "docker"
    assert sugerir("") is None

    assert sugerir("git checkout -b chore/x") == "git checkout -b"
    assert sugerir("git switch -c chore/x") == "git switch -c"
    assert sugerir("git checkout .") == "git checkout ."
    assert sugerir("git reset --hard HEAD") == "git reset --hard"
    assert sugerir("git branch chore/x") == "git branch chore/x"
    # subcomando de git SEM modo sensível continua na regra de dois tokens
    assert sugerir("git cherry-pick abc123") == "git cherry-pick"
    # sem terceiro token não há modo a preservar
    assert sugerir("git checkout") == "git checkout"


def test_escape_hint_omits_governance_key_when_harness_yaml_already_has_it(tmp_path: Path) -> None:
    """A instrução mais óbvia seria a que quebra: quando `harness.yaml` já tem
    `governance:`, colar a chave de novo produz duplicata — que o parser
    mínimo do hook trata degradando a lista INTEIRA para vazia. Por isso o bloco
    sugerido começa em `extra_allowed_commands`, não em `governance`, quando a
    chave já existe."""
    _contract_with_verify(tmp_path)
    (tmp_path / ".harness" / "harness.yaml").write_text(
        "governance:\n  approval_policy: default\n", encoding="utf-8"
    )
    _expect(
        _script(tmp_path),
        bash("alembic upgrade head", "deny",
             reason="extra_allowed_commands:\n    - alembic upgrade"),
        bash("alembic upgrade head", "deny", reason="sem recompilar"),
        bash("alembic upgrade head", "deny", absent="\ngovernance:"),
        pwsh("alembic upgrade head", "deny", reason="- alembic upgrade",
             why="a superficie PowerShell carrega o mesmo bloco"),
    )


def test_escape_hint_includes_governance_key_when_harness_yaml_is_missing(tmp_path: Path) -> None:
    """Issue #72: repo que rodou `/harness-creator:plan` direto, sem
    `/harness-creator:init` antes, chega ao bootstrap SEM `.harness/harness.yaml`.
    O bloco antigo sempre omitia `governance:`, assumindo que a chave já
    existia — apontava para dentro de um bloco que não existe, em arquivo que
    não existe. Com a correção, o bloco colável inclui o cabeçalho."""
    _contract_with_verify(tmp_path)
    assert not (tmp_path / ".harness" / "harness.yaml").exists()
    _expect(
        _script(tmp_path),
        bash("alembic upgrade head", "deny", reason="governance:\n  extra_allowed_commands:"),
        bash("alembic upgrade head", "deny", reason="/harness-creator:init"),
        pwsh("alembic upgrade head", "deny", reason="governance:\n  extra_allowed_commands:",
             why="a superficie PowerShell carrega o mesmo bloco"),
    )


def test_allowlist_yaml_hint_includes_governance_key_when_yaml_missing(tmp_path: Path) -> None:
    from harness.boundary_guard import allowlist_yaml_hint

    hint = allowlist_yaml_hint("alembic upgrade head", repo_root=tmp_path)
    assert "governance:\n  extra_allowed_commands:" in hint
    assert "- alembic upgrade" in hint


def test_allowlist_yaml_hint_omits_governance_key_when_already_present(tmp_path: Path) -> None:
    from harness.boundary_guard import allowlist_yaml_hint

    yaml_path = tmp_path / ".harness" / "harness.yaml"
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    yaml_path.write_text("governance:\n  approval_policy: default\n", encoding="utf-8")

    hint = allowlist_yaml_hint("alembic upgrade head", repo_root=tmp_path)
    assert "\ngovernance:" not in hint  # não repete o cabeçalho — já está lá
    assert "extra_allowed_commands:" in hint


def test_allowlist_yaml_hint_includes_governance_key_when_yaml_lacks_the_key(tmp_path: Path) -> None:
    """`harness.yaml` pode existir sem a chave `governance:` (arquivo escrito à
    mão, só com outras chaves) — mesmo tratamento do arquivo ausente."""
    from harness.boundary_guard import allowlist_yaml_hint

    yaml_path = tmp_path / ".harness" / "harness.yaml"
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    yaml_path.write_text("outra_chave:\n  x: 1\n", encoding="utf-8")

    hint = allowlist_yaml_hint("alembic upgrade head", repo_root=tmp_path)
    assert "governance:\n  extra_allowed_commands:" in hint


def test_allowlist_yaml_hint_default_repo_root_does_not_raise() -> None:
    """Sem `repo_root` (compatibilidade com chamadas antigas): não lança,
    trata como YAML ausente."""
    from harness.boundary_guard import allowlist_yaml_hint

    hint = allowlist_yaml_hint("pip install x")
    assert isinstance(hint, str)


def test_the_suggested_entry_actually_unblocks_the_command(tmp_path: Path) -> None:
    """O teste que fecha o ciclo: pega a entrada que a mensagem de deny sugeriu,
    escreve no YAML exatamente como ela manda, e confirma que o comando passa.
    Sem isto, a sugestão pode estar sintaticamente certa e semanticamente
    inútil — que é o modo de falha que o Item 3 introduziu com o segundo parser."""
    from harness.boundary_guard import suggested_allowlist_entry

    _contract_with_verify(tmp_path)
    script = _script(tmp_path)
    command = "alembic upgrade head --sql"

    before = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                                 "tool_input": {"command": command}})
    assert before["permissionDecision"] == "deny", before

    entry = suggested_allowlist_entry(command)
    (tmp_path / ".harness" / "harness.yaml").write_text(
        "governance:\n  approval_policy: auto\n"
        f"  extra_allowed_commands:\n    - {entry}\n",
        encoding="utf-8",
    )

    after = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                                "tool_input": {"command": command}})
    assert after["permissionDecision"] == "allow", after


# ===========================================================================
# Item 3 (dogfood venv-Windows) — extra_allowed_commands lido em RUNTIME
# ===========================================================================

def test_parse_extra_allowed_commands_block_and_flow() -> None:
    from harness.boundary_guard import parse_extra_allowed_commands_text

    block = "governance:\n  extra_allowed_commands:\n    - pytest -q\n    - \"python -m ruff\"\n"
    assert parse_extra_allowed_commands_text(block) == ["pytest -q", "python -m ruff"]

    flow = "governance:\n  extra_allowed_commands: [alembic upgrade, \"uv run mypy\"]\n"
    assert parse_extra_allowed_commands_text(flow) == ["alembic upgrade", "uv run mypy"]


def test_parse_extra_allowed_commands_tolerates_comments_and_colons() -> None:
    from harness.boundary_guard import parse_extra_allowed_commands_text

    text = (
        "# topo\n"
        "governance:   # bloco de governanca\n"
        "  approval_policy: auto\n"
        "  extra_allowed_commands:\n"
        "    # o runner do projeto\n"
        "    - pytest tests/a.py::test_b   # caso especifico\n"
        "  branch_per_contract: true\n"
    )
    assert parse_extra_allowed_commands_text(text) == ["pytest tests/a.py::test_b"]


def test_parse_extra_allowed_commands_degrades_to_empty() -> None:
    """O custo honesto de um segundo parser: o que ele não entende vira lista
    VAZIA — nunca lixo aceito, nunca superfície maior. Cada entrada aqui é uma
    grafia YAML legítima que o pyyaml leria e este parser recusa de propósito."""
    from harness.boundary_guard import parse_extra_allowed_commands_text

    unsupported = {
        "tab": "governance:\n\textra_allowed_commands:\n\t  - pytest\n",
        "ancora": "governance:\n  extra_allowed_commands:\n    - &ancora pytest\n",
        "alias": "governance:\n  extra_allowed_commands:\n    - *ancora\n",
        "escalar_de_bloco": "governance:\n  extra_allowed_commands: |\n    pytest\n",
        "aninhado": "governance:\n  extra_allowed_commands:\n    - cmd: pytest\n",
        "flow_aninhado": "governance:\n  extra_allowed_commands: [[a], b]\n",
        "aspas_desbalanceadas": "governance:\n  extra_allowed_commands:\n    - \"pytest\n",
        "chave_duplicada": (
            "governance:\n  extra_allowed_commands:\n    - a\n  extra_allowed_commands:\n    - b\n"
        ),
        "escalar_simples": "governance:\n  extra_allowed_commands: pytest\n",
        "sem_governance": "verification:\n  extra_allowed_commands:\n    - evil\n",
        "chave_ausente": "governance:\n  approval_policy: auto\n",
        "vazio": "",
    }
    for name, text in unsupported.items():
        assert parse_extra_allowed_commands_text(text) == [], name


def test_extra_allowed_commands_is_read_at_runtime_in_both_directions(
    tmp_path: Path,
) -> None:
    """O ITEM 3 em uma linha: editar o YAML basta, `compile-session` deixa de ser
    obrigatório a cada ajuste de allowlist. O hook é instalado ANTES do YAML
    existir e mesmo assim honra a edição posterior.

    A direção inversa importa tanto quanto: tirar do YAML fecha na hora. Se o
    bake sobrevivesse como fallback, a remoção não valeria sem recompilar — e a
    superfície ficaria maior do que o arquivo declara. E erro de parse REDUZ
    para lista vazia, nunca alarga."""
    from harness.boundary_guard import read_extra_allowed_commands_runtime

    assert read_extra_allowed_commands_runtime(tmp_path) == []
    assert read_extra_allowed_commands_runtime(None) == []

    _contract_with_verify(tmp_path)
    yaml_path = tmp_path / ".harness" / "harness.yaml"
    _expect(
        _script(tmp_path),
        bash("alembic upgrade head", "deny", why="antes de declarar"),
        bash("alembic upgrade head", "allow", why="depois de declarar, sem recompilar",
             before=lambda: _write_harness_yaml(tmp_path, ["alembic upgrade"])),
        bash("alembic upgrade head", "deny", why="removido do yaml fecha na hora",
             before=lambda: yaml_path.write_text(
                 "governance:\n  approval_policy: auto\n", encoding="utf-8")),
        bash("alembic upgrade head", "deny", why="yaml quebrado nunca alarga",
             before=lambda: yaml_path.write_text(
                 "governance:\n  extra_allowed_commands: [alembic upgrade\n",
                 encoding="utf-8")),
    )


def test_render_boundary_guard_does_not_bake_extra_allowed_commands() -> None:
    """Regressão estrutural: se a constante bakeada voltar, os dois testes de
    edição/remoção acima podem continuar verdes por acidente (o bake e o YAML
    concordando), e o item silenciosamente regride."""
    from harness.boundary_guard import render_boundary_guard

    assert "EXTRA_ALLOWED_COMMANDS" not in render_boundary_guard()


def test_render_boundary_guard_is_deterministic_across_calls() -> None:
    """`render_boundary_guard` embute vários `set(...)!r` no código-fonte
    gerado — a ordem de iteração de um `set` real varia ENTRE processos
    Python (hash de string randomizado por padrão, fixo dentro de um mesmo
    processo), então comparar duas chamadas no mesmo processo pytest não
    pega o bug: o hash seed é o mesmo nas duas. O teste precisa de dois
    processos Python DISTINTOS, com seed potencialmente diferente, para
    provar que o texto gerado não depende do hash seed. Sem isso, nenhum
    check de drift por comparação/hash do hook compilado é possível."""
    code = (
        "from harness.boundary_guard import render_boundary_guard\n"
        "import sys\n"
        "sys.stdout.write(render_boundary_guard(['main', 'develop']))\n"
    )
    runs = []
    for seed in ("111", "222"):
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=30, encoding="utf-8",
            env={**os.environ, "PYTHONHASHSEED": seed, "PYTHONIOENCODING": "utf-8"},
        )
        assert proc.returncode == 0, proc.stderr
        runs.append(proc.stdout)
    assert runs[0] == runs[1]


def test_extra_allowed_commands_grammar_problem(tmp_path: Path) -> None:
    """Contrapartida do parser burro: `compile-session` avisa quando o pyyaml
    e o parser do hook leem coisas diferentes. Sem isso a entrada vira deny
    silencioso, com o settings.json afirmando o contrário."""
    from harness.boundary_guard import extra_allowed_commands_grammar_problem

    assert extra_allowed_commands_grammar_problem(tmp_path) is None

    _write_harness_yaml(tmp_path, ["alembic upgrade"])
    assert extra_allowed_commands_grammar_problem(tmp_path) is None

    (tmp_path / ".harness" / "harness.yaml").write_text(
        "governance:\n  extra_allowed_commands:\n    - !!str alembic upgrade\n",
        encoding="utf-8",
    )
    problem = extra_allowed_commands_grammar_problem(tmp_path)
    assert problem is not None
    assert "alembic upgrade" in problem


# ===========================================================================
# Item 7 (dogfood venv-Windows) — PowerShell deixa de ser cidadão de segunda
# ===========================================================================

def test_powershell_readonly_cmdlets_and_pipelines_are_allowed(tmp_path: Path) -> None:
    """Correção da assimetria entre os dois caminhos: o Bash tinha
    `cat`/`ls`/`grep`/`echo` liberados por `READONLY_SHELL_UTILITIES`, mas o
    PowerShell não tinha os equivalentes — `Get-ChildItem` era deny mesmo COM
    contrato ativo. Quem só tem PowerShell 5.1 não conseguia nem listar um
    diretório sem declarar o comando no contrato.

    Pipeline é a forma idiomática da linguagem, e `Select-Object` nunca vai
    prefixar uma allowlist derivada de `verify_cmd`. Sem esse escape o caminho
    PowerShell era inutilizável sob contrato ativo — o que empurrava tudo para a
    Bash tool, justamente a que não enxerga o venv Windows."""
    _contract_with_verify(tmp_path)
    (tmp_path / "src").mkdir(exist_ok=True)
    _expect(
        _script(tmp_path),
        pwsh("pytest -q | Select-Object -First 5", "allow"),
        pwsh("pytest -q | Where-Object { $_ }", "allow"),
        pwsh("pytest -q | Measure-Object", "allow"),
        pwsh("pytest -q | Sort-Object | Format-Table", "allow"),
        pwsh(".venv/Scripts/pytest.exe -q | Select-Object -First 5", "allow"),
        pwsh("Get-ChildItem", "allow"),
        pwsh("Get-ChildItem -Recurse src", "allow"),
        pwsh("ls src", "allow"),
        pwsh("dir", "allow"),
        pwsh("Get-Content src/main.py", "allow"),
        pwsh("cat src/main.py", "allow"),
        pwsh("type src/main.py", "allow"),
        pwsh("gc src/main.py | Select-Object -First 20", "allow"),
        pwsh("Select-String -Pattern TODO -Path src/main.py", "allow"),
        pwsh("sls TODO src/main.py", "allow"),
        pwsh("Write-Output hello", "allow"),
        pwsh("echo hello", "allow"),
        pwsh("Get-Location", "allow"),
        pwsh("pwd", "allow"),
        pwsh("Get-Item src/main.py", "allow"),
        pwsh("Test-Path src/main.py", "allow"),
        pwsh("cd src", "allow", why="os dois escapes que _evaluate_bash ja tinha"),
        pwsh("cd src; pytest -q", "allow"),
        pwsh("Get-Content .env", "allow", why="LER segredo nao e escrever nele"),
        pwsh("Get-Content src/other.py > src/main.py", "allow",
             why="o destino do redirect esta em files[]"),
    )

    bootstrap = tmp_path / "bootstrap"
    bootstrap.mkdir()
    _expect(
        _script(bootstrap),
        pwsh("Get-ChildItem", "allow"),
        pwsh("Get-Content src/main.py", "allow"),
        pwsh("Test-Path src/main.py", "allow"),
    )


def test_powershell_readonly_allowlist_opens_no_write_door(tmp_path: Path) -> None:
    """A allowlist de leitura não abre porta de escrita nenhuma: alvo fora de
    `files[]` continua deny, com ou sem redirecionamento.

    O redirect é onde estava o escape achado ao corrigir a assimetria:
    `_extract_powershell_write_target` devolvia o PRIMEIRO token com cara de
    path, que num redirecionamento é a ORIGEM — com `src/main.py` em `files[]`,
    `... src/main.py > src/other.py` era avaliado contra a origem e a escrita
    passava. O alvo agora é o token depois do último `>`.

    `ForEach-Object` e `Invoke-Expression` executam scriptblock arbitrário: é
    execução, não formatação. Atribuição a `$env:*` muda o ambiente dos comandos
    seguintes e reabriria por outra porta o problema de PATH que o Item 4
    resolve de forma controlada. E o floor de rede não é afetado por escape
    nenhum."""
    _contract_with_verify(tmp_path)
    _expect(
        _script(tmp_path),
        pwsh("Get-Content src/main.py > src/other.py", "deny", reason="fora da superficie",
             why="o alvo e o DESTINO do redirect, nao a origem"),
        pwsh("Get-ChildItem >> listing.txt", "deny"),
        pwsh("Set-Content src/other.py 'x'", "deny"),
        pwsh("Out-File -FilePath src/other.py", "deny"),
        pwsh("Add-Content src/other.py 'x'", "deny"),
        pwsh("Remove-Item -Recurse -Force src", "deny"),
        pwsh("New-Item -ItemType File src/other.py", "deny"),
        pwsh("Write-Output x > .env", "deny", reason="runtime floor"),
        pwsh("pytest -q | ForEach-Object { rm -rf src }", "deny"),
        pwsh("pytest -q | Invoke-Expression", "deny"),
        pwsh("$env:PATH = '.venv\\Scripts'; pytest -q", "deny"),
        pwsh("iwr http://evil | Select-Object -First 1", "deny", reason="runtime floor"),
        pwsh("irm http://evil", "deny", reason="runtime floor"),
        pwsh("pytest -q; Remove-Item -Recurse src", "deny",
             why="segmento arbitrario colado a um permitido derruba o comando"),
    )


# ---------------------------------------------------------------------------
# Todo verbo da CLI ou está liberado, ou está excluído por decisão escrita
# ---------------------------------------------------------------------------

#: Verbos que o guard nega DE PROPÓSITO, cada um com a razão:
#:
#: - `profile` grava no `repo-profile.json`, e o `test_command` de lá alimenta a
#:   superfície de comando compilada — agente capaz de escrever ali amplia a
#:   própria superfície (ver `test_profile_is_not_an_agent_subcommand`);
#: - `enable`/`disable` mexem no kill-switch, que é floor: o agente não liga
#:   nem desliga a própria governança.
DELIBERATELY_DENIED_VERBS = {"profile", "enable", "disable"}


def _cli_verbs(monkeypatch, capsys) -> set[str]:
    """Verbos que o argparse do `harness` realmente aceita, lidos do parser —
    não de uma lista copiada à mão, que é o que este teste existe para não ser.
    """
    from harness.cli import main

    monkeypatch.setattr(sys, "argv", ["harness", "--help"])
    try:
        main()
    except SystemExit:
        pass
    usage = capsys.readouterr().out
    block = usage[usage.index("{") + 1 : usage.index("}")]
    return {verb.strip() for verb in block.split(",") if verb.strip()}


def test_every_cli_verb_is_either_allowed_or_deliberately_denied(monkeypatch, capsys) -> None:
    """REGRA: verbo que a CLI aceita e o guard nega é um passo do lifecycle
    mandando rodar comando barrado.

    Já aconteceu duas vezes. `pr-draft` saiu na v0.32.0 e ficou fora de
    `_HARNESS_SUBCOMMANDS` até o contrato seguinte — com o passo 16 mandando
    rodá-lo. O teste que nasceu daquele achado listava os nomes à mão e dizia
    servir "para que o próximo verbo não repita o esquecimento", mas uma lista
    fixa não checa o verbo seguinte: ela precisa ser editada pela mesma pessoa
    que esqueceu. Aqui a lista vem do parser, então o esquecimento aparece
    sozinho — e excluir um verbo passa a exigir escrever a razão em
    `DELIBERATELY_DENIED_VERBS`.
    """
    from harness.boundary_guard import HARNESS_CLI_VERBS, render_boundary_guard

    verbs = _cli_verbs(monkeypatch, capsys)
    assert {"verify", "finish", "budget", "reconcile"} <= verbs, (
        "âncora: a leitura do parser quebrou, não a lista do guard"
    )

    # Contra a CONSTANTE: desde o contrato `compilar-as-primeiras-licoes` ela é
    # a fonte única (o hook a recebe bakeada, o settings a importa). O texto
    # gerado é consequência dela, e tem âncora própria logo abaixo.
    missing = sorted(verbs - DELIBERATELY_DENIED_VERBS - set(HARNESS_CLI_VERBS))
    assert not missing, (
        f"verbos que a CLI aceita e o guard nega: {missing}. "
        "Ou entram em `HARNESS_CLI_VERBS`, ou entram em "
        "DELIBERATELY_DENIED_VERBS com a razão escrita."
    )

    generated = render_boundary_guard()
    assert json.dumps(list(HARNESS_CLI_VERBS)) in generated, (
        "a constante existe mas não chegou ao hook gerado — o hook é "
        "stdlib-only e depende da lista BAKEADA para liberar qualquer verbo"
    )

