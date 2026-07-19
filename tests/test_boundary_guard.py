"""Testes do boundary_guard (Fase 2): dispatcher único de fronteira
(Edit/Write/Bash) a partir da superfície do contrato ativo."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from harness.boundary_guard import (
    BOUNDARY_HOOK_MATCHER,
    BOUNDARY_STATE_KEY,
    REPO_ROOT_STATE_KEY,
    SESSION_STATE_FILE,
    install_boundary_guard,
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


def _write_evidence(target: Path, feature_id: str, recorded_at: str, **overrides) -> None:
    path = target / ".harness" / "evidence" / f"{feature_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "feature_id": feature_id,
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


# ---------------- sem contrato ativo ----------------

def test_no_feature_list_allows_edit(tmp_path: Path) -> None:
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Edit", "cwd": str(tmp_path),
                              "tool_input": {"file_path": "src/main.py"}})
    assert out["permissionDecision"] == "allow"


# ---------------- superfície do contrato: Edit/Write ----------------

def test_edit_file_declared_in_contract_allows(tmp_path: Path) -> None:
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Edit", "cwd": str(tmp_path),
                              "tool_input": {"file_path": "src/main.py"}})
    assert out["permissionDecision"] == "allow"


def test_edit_file_not_declared_denies(tmp_path: Path) -> None:
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Edit", "cwd": str(tmp_path),
                              "tool_input": {"file_path": "src/other.py"}})
    assert out["permissionDecision"] == "deny"


def test_write_new_file_under_declared_directory_prefix_allows(tmp_path: Path) -> None:
    """files[] pode declarar um diretorio (ex. "Migrations/") em vez de um
    arquivo exato — uma migration nova dentro dele deve ser permitida mesmo
    sem existir no disco ainda (Write cria arquivo que nao existe)."""
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["backend/Migrations/"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Write", "cwd": str(tmp_path),
                              "tool_input": {"file_path": "backend/Migrations/20260718_New.cs",
                                             "content": "x"}})
    assert out["permissionDecision"] == "allow"


def test_write_new_file_matching_declared_glob_allows_even_if_not_on_disk(tmp_path: Path) -> None:
    """Glob em files[] deve casar contra o path do candidato diretamente,
    nao depender de disco-walk — senao um arquivo genuinamente novo (que
    ainda nao existe) nunca reconhece seu proprio glob declarado."""
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["backend/Migrations/*.cs"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Write", "cwd": str(tmp_path),
                              "tool_input": {"file_path": "backend/Migrations/20260718_New.cs",
                                             "content": "x"}})
    assert out["permissionDecision"] == "allow"


def test_write_contract_authoring_dir_allows_even_with_active_contract(tmp_path: Path) -> None:
    """Autoria do PRÓXIMO contrato (.harness/work/<slug-novo>/{spec,Plans}.md)
    nunca está em files[] do contrato ativo — deve ser sempre gravável, senão
    planejar a próxima feature fica bloqueado pela superfície da atual."""
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    script = _script(tmp_path)
    for rel in (".harness/work/nova-feature/spec.md",
                ".harness/work/nova-feature/Plans.md"):
        out = _run_hook(script, {"tool_name": "Write", "cwd": str(tmp_path),
                                  "tool_input": {"file_path": rel, "content": "x"}})
        assert out["permissionDecision"] == "allow", rel


def test_secret_inside_work_dir_still_denies(tmp_path: Path) -> None:
    """Floor de segredo precede a exceção de .harness/work/** — um .env
    escondido lá dentro continua bloqueado."""
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Write", "cwd": str(tmp_path),
                              "tool_input": {"file_path": ".harness/work/x/.env", "content": "k=v"}})
    assert out["permissionDecision"] == "deny"


# ---------------- superfície do contrato: Bash ----------------

def test_bash_exact_verify_cmd_allows(tmp_path: Path) -> None:
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -x --tb=short",
         "depends": [], "passes": False}
    ])
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                              "tool_input": {"command": "pytest -x --tb=short"}})
    assert out["permissionDecision"] == "allow"


def test_bash_git_local_commands_allow(tmp_path: Path) -> None:
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    script = _script(tmp_path)
    for cmd in ("git status", "git add .", 'git commit -m x'):
        out = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                                  "tool_input": {"command": cmd}})
        assert out["permissionDecision"] == "allow", cmd


def test_bash_unrelated_command_denies(tmp_path: Path) -> None:
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                              "tool_input": {"command": "echo oi"}})
    assert out["permissionDecision"] == "deny"


# ---------------- runtime floor: nunca vira allow ----------------

def test_floor_git_push_denies_even_with_full_contract(tmp_path: Path) -> None:
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py", ".env"],
         "verify_cmd": "git push", "depends": [], "passes": False}
    ])
    script = _script(tmp_path)
    for cmd in ("git push", "git push origin main", "git push && true"):
        out = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                                  "tool_input": {"command": cmd}})
        assert out["permissionDecision"] == "deny", cmd
        assert "runtime floor" in out["permissionDecisionReason"]


def test_floor_curl_denies(tmp_path: Path) -> None:
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                              "tool_input": {"command": "curl https://x"}})
    assert out["permissionDecision"] == "deny"
    assert "runtime floor" in out["permissionDecisionReason"]


def test_floor_env_file_denies_even_if_declared_in_contract(tmp_path: Path) -> None:
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": [".env"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Edit", "cwd": str(tmp_path),
                              "tool_input": {"file_path": ".env"}})
    assert out["permissionDecision"] == "deny"
    assert "runtime floor" in out["permissionDecisionReason"]


def test_floor_git_push_denies_without_any_contract(tmp_path: Path) -> None:
    """CRÍTICO: sem feature_list.json (nenhum contrato ativo), git push
    AINDA é deny — o floor roda antes do 'sem contrato -> allow'."""
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                              "tool_input": {"command": "git push origin main"}})
    assert out["permissionDecision"] == "deny"
    assert "runtime floor" in out["permissionDecisionReason"]


def test_floor_env_file_denies_without_any_contract(tmp_path: Path) -> None:
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Edit", "cwd": str(tmp_path),
                              "tool_input": {"file_path": ".env"}})
    assert out["permissionDecision"] == "deny"
    assert "runtime floor" in out["permissionDecisionReason"]


# ---------------- proteção contra enfraquecimento de teste ----------------

def test_test_file_declared_in_contract_allows(tmp_path: Path) -> None:
    _write_profile(tmp_path)
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["tests/test_x.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Edit", "cwd": str(tmp_path),
                              "tool_input": {"file_path": "tests/test_x.py"}})
    assert out["permissionDecision"] == "allow"


def test_test_file_not_declared_denies_with_weakening_reason(tmp_path: Path) -> None:
    _write_profile(tmp_path)
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Edit", "cwd": str(tmp_path),
                              "tool_input": {"file_path": "tests/test_x.py"}})
    assert out["permissionDecision"] == "deny"
    assert "enfraquecimento" in out["permissionDecisionReason"]


# ---------------- package_manager derivando install command ----------------

def test_package_manager_install_command_is_allowed(tmp_path: Path) -> None:
    _write_profile(tmp_path, package_manager={"value": "npm", "evidence": "x", "confidence": 1.0})
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                              "tool_input": {"command": "npm ci"}})
    assert out["permissionDecision"] == "allow"


def test_package_manager_value_alone_is_not_a_free_pass_for_any_subcommand(tmp_path: Path) -> None:
    """Gap 2 (hardening): `package_manager.value == "npm"` deve liberar
    EXATAMENTE `npm ci` (o comando de instalação), não o nome do package
    manager inteiro — `npm run build-malicioso` (um comando `npm ...`
    qualquer, mas não `npm ci` exato) continua deny."""
    _write_profile(tmp_path, package_manager={"value": "npm", "evidence": "x", "confidence": 1.0})
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    script = _script(tmp_path)

    allowed = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                                  "tool_input": {"command": "npm ci"}})
    assert allowed["permissionDecision"] == "allow"

    denied = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                                 "tool_input": {"command": "npm run build-malicioso"}})
    assert denied["permissionDecision"] == "deny", denied


def test_package_manager_none_does_not_break_allowed_bash(tmp_path: Path) -> None:
    _write_profile(tmp_path, package_manager=None)
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                              "tool_input": {"command": "pytest -q"}})
    assert out["permissionDecision"] == "allow"
    out2 = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                               "tool_input": {"command": "echo oi"}})
    assert out2["permissionDecision"] == "deny"


# ---------------- ferramenta fora do escopo ----------------

def test_other_tool_allows_by_default(tmp_path: Path) -> None:
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Read", "cwd": str(tmp_path),
                              "tool_input": {"file_path": "src/main.py"}})
    assert out["permissionDecision"] == "allow"


# ---------------- install_boundary_guard: settings.json + estado ----------------

def test_install_registers_hook_in_settings(tmp_path: Path) -> None:
    script = install_boundary_guard(tmp_path)
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    entries = settings["hooks"]["PreToolUse"]
    matching = [e for e in entries if e.get("matcher") == BOUNDARY_HOOK_MATCHER]
    assert len(matching) == 1
    assert str(script) in matching[0]["hooks"][0]["command"]


def test_install_is_idempotent(tmp_path: Path) -> None:
    install_boundary_guard(tmp_path)
    install_boundary_guard(tmp_path)
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    entries = settings["hooks"]["PreToolUse"]
    matching = [e for e in entries if e.get("matcher") == BOUNDARY_HOOK_MATCHER]
    assert len(matching) == 1


def test_install_preserves_unrelated_settings_and_hooks(tmp_path: Path) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text(json.dumps({
        "model": "opus",
        "permissions": {"allow": ["Bash(npm run *)"]},
        "hooks": {"PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "meu-hook.sh"}]},
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "python .harness/hooks/guard_test_runner.py"}]},
        ]},
    }), encoding="utf-8")

    install_boundary_guard(tmp_path)

    settings = json.loads((claude_dir / "settings.json").read_text(encoding="utf-8"))
    assert settings["model"] == "opus"
    assert "Bash(npm run *)" in settings["permissions"]["allow"]
    user_hooks = [e for e in settings["hooks"]["PreToolUse"] if "meu-hook.sh" in json.dumps(e)]
    assert len(user_hooks) == 1
    runner_hooks = [e for e in settings["hooks"]["PreToolUse"] if "guard_test_runner.py" in json.dumps(e)]
    assert len(runner_hooks) == 1


def test_install_removes_legacy_guard_tests_hook(tmp_path: Path) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text(json.dumps({
        "hooks": {"PreToolUse": [
            {"matcher": "Write|Edit",
             "hooks": [{"type": "command", "command": 'python ".harness/hooks/guard_tests.py"'}]},
        ]},
    }), encoding="utf-8")

    install_boundary_guard(tmp_path)

    settings = json.loads((claude_dir / "settings.json").read_text(encoding="utf-8"))
    legacy = [e for e in settings["hooks"]["PreToolUse"] if "guard_tests.py" in json.dumps(e)]
    assert legacy == []
    new_entries = [e for e in settings["hooks"]["PreToolUse"] if e.get("matcher") == BOUNDARY_HOOK_MATCHER]
    assert len(new_entries) == 1


def test_install_writes_state_key_preserving_siblings(tmp_path: Path) -> None:
    state_path = tmp_path / SESSION_STATE_FILE
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"session_permissions_hook_command": "sibling"}), encoding="utf-8")

    install_boundary_guard(tmp_path)

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["session_permissions_hook_command"] == "sibling"
    assert BOUNDARY_STATE_KEY in state


# ---------------- feature-lock: edição do próprio feature_list.json ----------------

def test_feature_list_transition_to_passes_true_denies_without_evidence(tmp_path: Path) -> None:
    """Sem NENHUMA evidência gravada, uma edição que marca passes:true é deny."""
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
    assert "T-01" in out["permissionDecisionReason"]
    assert "harness verify" in out["permissionDecisionReason"]


def test_feature_list_transition_to_passes_true_denies_with_stale_evidence(tmp_path: Path) -> None:
    """Evidência existe mas é MAIS ANTIGA que o último commit -> deny."""
    _init_git_repo_with_commit(tmp_path, "2026-06-01T00:00:00+00:00")
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    _write_evidence(tmp_path, "T-01", recorded_at="2026-01-01T00:00:00+00:00")
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
    assert "T-01" in out["permissionDecisionReason"]


def test_feature_list_transition_to_passes_true_allows_with_fresh_evidence(tmp_path: Path) -> None:
    """Evidência existe e é MAIS NOVA que o último commit -> allow."""
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
    assert "T-01" in out["permissionDecisionReason"]


def test_feature_list_edit_variant_uses_old_string_new_string(tmp_path: Path) -> None:
    """Via Edit (old_string/new_string), não só Write: mesma checagem de
    feature-lock se aplica."""
    _init_git_repo_with_commit(tmp_path, "2026-01-01T00:00:00+00:00")
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    _write_evidence(tmp_path, "T-01", recorded_at="2026-06-01T00:00:00+00:00")
    script = _script(tmp_path)
    out = _run_hook(script, {
        "tool_name": "Edit", "cwd": str(tmp_path),
        "tool_input": {
            "file_path": ".harness/feature_list.json",
            "old_string": '"passes": false',
            "new_string": '"passes": true',
        },
    })
    assert out["permissionDecision"] == "allow", out


def test_feature_list_edit_without_passes_true_transition_keeps_current_behavior(tmp_path: Path) -> None:
    """Edição a feature_list.json que NÃO transiciona nenhuma feature para
    passes:true mantém o comportamento ATUAL (deny) — sem evidência
    nenhuma, sem repo git algum."""
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x antigo", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    script = _script(tmp_path)
    new_content = _feature_list_json([
        {"id": "T-01", "desc": "x novo", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    out = _run_hook(script, {
        "tool_name": "Write", "cwd": str(tmp_path),
        "tool_input": {"file_path": ".harness/feature_list.json", "content": new_content},
    })
    assert out["permissionDecision"] == "deny"


# ---------------- feature-lock: veto do revisor (Fase 4, produtor-revisor) ----------------

def test_feature_lock_without_manifest_keeps_phase3_behavior(tmp_path: Path) -> None:
    """Sem `.harness/team/manifest.json`, evidência fresca já basta —
    comportamento IDÊNTICO à Fase 3, sem checar revisão nenhuma."""
    _init_git_repo_with_commit(tmp_path, "2026-01-01T00:00:00+00:00")
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    _write_evidence(tmp_path, "T-01", recorded_at="2026-06-01T00:00:00+00:00")
    script = _script(tmp_path)
    out = _run_hook(script, _transition_payload(tmp_path))
    assert out["permissionDecision"] == "allow", out


def test_feature_lock_with_manifest_missing_producer_or_reviewer_role_keeps_phase3_behavior(
    tmp_path: Path,
) -> None:
    """Manifesto existe mas NÃO declara os dois papéis (só 'producer') ->
    checagem de revisão continua pulada, comportamento da Fase 3."""
    _init_git_repo_with_commit(tmp_path, "2026-01-01T00:00:00+00:00")
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    _write_evidence(tmp_path, "T-01", recorded_at="2026-06-01T00:00:00+00:00")
    _write_manifest(tmp_path, roles=["producer"])
    script = _script(tmp_path)
    out = _run_hook(script, _transition_payload(tmp_path))
    assert out["permissionDecision"] == "allow", out


def test_feature_lock_with_producer_reviewer_manifest_denies_without_review_record(
    tmp_path: Path,
) -> None:
    """Manifesto declara producer+reviewer, evidência fresca, mas SEM
    `.harness/review/T-01.json` -> deny (registro default é status='pending')."""
    _init_git_repo_with_commit(tmp_path, "2026-01-01T00:00:00+00:00")
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    _write_evidence(tmp_path, "T-01", recorded_at="2026-06-01T00:00:00+00:00")
    _write_manifest(tmp_path)
    script = _script(tmp_path)
    out = _run_hook(script, _transition_payload(tmp_path))
    assert out["permissionDecision"] == "deny", out
    assert "T-01" in out["permissionDecisionReason"]


def test_feature_lock_with_review_rejected_in_review_or_pending_denies(tmp_path: Path) -> None:
    """status='rejected'/'in_review'/'pending' (não 'approved') -> deny,
    mesmo com updated_at bem no futuro."""
    _init_git_repo_with_commit(tmp_path, "2026-01-01T00:00:00+00:00")
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    _write_evidence(tmp_path, "T-01", recorded_at="2026-06-01T00:00:00+00:00")
    _write_manifest(tmp_path)
    script = _script(tmp_path)
    for status in ("rejected", "in_review", "pending"):
        _write_review(tmp_path, "T-01", status=status, updated_at="2026-09-01T00:00:00+00:00")
        out = _run_hook(script, _transition_payload(tmp_path))
        assert out["permissionDecision"] == "deny", (status, out)
        assert "T-01" in out["permissionDecisionReason"]


def test_feature_lock_with_review_approved_but_older_than_commit_denies(tmp_path: Path) -> None:
    """status='approved' mas updated_at MAIS ANTIGO que o último commit ->
    deny (aprovação anterior ao próprio commit não cobre o diff atual)."""
    _init_git_repo_with_commit(tmp_path, "2026-01-01T00:00:00+00:00")
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    _write_evidence(tmp_path, "T-01", recorded_at="2026-06-01T00:00:00+00:00")
    _write_manifest(tmp_path)
    _write_review(tmp_path, "T-01", status="approved", updated_at="2025-01-01T00:00:00+00:00")
    script = _script(tmp_path)
    out = _run_hook(script, _transition_payload(tmp_path))
    assert out["permissionDecision"] == "deny", out
    assert "T-01" in out["permissionDecisionReason"]


def test_feature_lock_with_review_approved_but_older_than_evidence_denies(tmp_path: Path) -> None:
    """status='approved', updated_at mais novo que o commit, mas MAIS
    ANTIGO que evidencia.recorded_at (achado de reflect+judge: aprovação
    obsoleta porque a evidência foi regravada DEPOIS da aprovação) -> deny."""
    _init_git_repo_with_commit(tmp_path, "2026-01-01T00:00:00+00:00")
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    _write_evidence(tmp_path, "T-01", recorded_at="2026-06-01T00:00:00+00:00")
    _write_manifest(tmp_path)
    _write_review(tmp_path, "T-01", status="approved", updated_at="2026-03-01T00:00:00+00:00")
    script = _script(tmp_path)
    out = _run_hook(script, _transition_payload(tmp_path))
    assert out["permissionDecision"] == "deny", out
    assert "T-01" in out["permissionDecisionReason"]


def test_feature_lock_with_review_approved_fresh_allows(tmp_path: Path) -> None:
    """status='approved' com updated_at mais novo que o commit E que a
    evidência -> allow, e a mensagem de sucesso cita a revisão aprovada."""
    _init_git_repo_with_commit(tmp_path, "2026-01-01T00:00:00+00:00")
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    _write_evidence(tmp_path, "T-01", recorded_at="2026-03-01T00:00:00+00:00")
    _write_manifest(tmp_path)
    _write_review(tmp_path, "T-01", status="approved", updated_at="2026-06-01T00:00:00+00:00")
    script = _script(tmp_path)
    out = _run_hook(script, _transition_payload(tmp_path))
    assert out["permissionDecision"] == "allow", out
    assert "revis" in out["permissionDecisionReason"].lower()


def test_feature_lock_test_diff_approved_without_justification_denies(tmp_path: Path) -> None:
    """Feature transicionada cujo files[] toca o test_glob do repo-profile:
    review aprovado fresco mas SEM justification -> deny (defesa em
    profundidade — reconfirmação de leitura mesmo que review.py já
    bloqueie isso na escrita)."""
    _init_git_repo_with_commit(tmp_path, "2026-01-01T00:00:00+00:00")
    _write_profile(tmp_path)
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["tests/test_x.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    _write_evidence(tmp_path, "T-01", recorded_at="2026-03-01T00:00:00+00:00")
    _write_manifest(tmp_path)
    _write_review(tmp_path, "T-01", status="approved", updated_at="2026-06-01T00:00:00+00:00",
                  justification=None)
    script = _script(tmp_path)
    out = _run_hook(script, _transition_payload(tmp_path, files=["tests/test_x.py"]))
    assert out["permissionDecision"] == "deny", out
    assert "justificativa" in out["permissionDecisionReason"]


def test_feature_lock_test_diff_approved_with_justification_allows(tmp_path: Path) -> None:
    """Mesmo cenário acima, mas COM justification preenchida -> allow."""
    _init_git_repo_with_commit(tmp_path, "2026-01-01T00:00:00+00:00")
    _write_profile(tmp_path)
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["tests/test_x.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    _write_evidence(tmp_path, "T-01", recorded_at="2026-03-01T00:00:00+00:00")
    _write_manifest(tmp_path)
    _write_review(tmp_path, "T-01", status="approved", updated_at="2026-06-01T00:00:00+00:00",
                  justification="expectativa mudou porque o contrato foi renegociado")
    script = _script(tmp_path)
    out = _run_hook(script, _transition_payload(tmp_path, files=["tests/test_x.py"]))
    assert out["permissionDecision"] == "allow", out


# ---------------- Achado 1: command smuggling no guard de Bash ----------------


def _contract_with_verify(target: Path, verify_cmd: str = "pytest -q") -> None:
    _write_feature_list(target, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": verify_cmd,
         "depends": [], "passes": False}
    ])


def test_bash_smuggle_after_verify_cmd_denies(tmp_path: Path) -> None:
    """`<verify_cmd> && rm -rf src` -> DENY (o rm colado depois do allowed
    não pode escapar)."""
    _contract_with_verify(tmp_path)
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                             "tool_input": {"command": "pytest -q && rm -rf src"}})
    assert out["permissionDecision"] == "deny", out


def test_bash_smuggle_before_verify_cmd_denies(tmp_path: Path) -> None:
    """`rm -rf src && <verify_cmd>` -> DENY (smuggle ANTES do allowed)."""
    _contract_with_verify(tmp_path)
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                             "tool_input": {"command": "rm -rf src && pytest -q"}})
    assert out["permissionDecision"] == "deny", out


def test_bash_smuggle_via_semicolon_after_git_denies(tmp_path: Path) -> None:
    """`git commit -m x ; powershell -c evil` -> DENY (git local é allowed,
    powershell não)."""
    _contract_with_verify(tmp_path)
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                             "tool_input": {"command": "git commit -m x ; powershell -c evil"}})
    assert out["permissionDecision"] == "deny", out


def test_bash_smuggle_via_pipe_denies(tmp_path: Path) -> None:
    """`<verify_cmd> | rm -rf src` -> DENY (pipe também é operador de
    controle)."""
    _contract_with_verify(tmp_path)
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                             "tool_input": {"command": "pytest -q | rm -rf src"}})
    assert out["permissionDecision"] == "deny", out


def test_bash_command_substitution_denies(tmp_path: Path) -> None:
    """`<verify_cmd> $(rm -rf src)` e a variante com crase -> DENY (command
    substitution barrada antes de segmentar)."""
    _contract_with_verify(tmp_path)
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                             "tool_input": {"command": "pytest -q $(rm -rf src)"}})
    assert out["permissionDecision"] == "deny", out
    out2 = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                              "tool_input": {"command": "pytest -q `rm -rf src`"}})
    assert out2["permissionDecision"] == "deny", out2


def test_bash_floor_smuggle_still_denies_after_fix(tmp_path: Path) -> None:
    """Regressão do floor: `curl http://evil && pytest -q` continua DENY
    citando runtime floor (floor roda em qualquer janela, intocado)."""
    _contract_with_verify(tmp_path)
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                             "tool_input": {"command": "curl http://evil && pytest -q"}})
    assert out["permissionDecision"] == "deny", out
    assert "runtime floor" in out["permissionDecisionReason"]


def test_bash_legit_commands_still_allow_after_fix(tmp_path: Path) -> None:
    """Zero regressão: verify_cmd sozinho, git local (add/commit/status)
    continuam ALLOW com prefixo estrito por segmento."""
    _contract_with_verify(tmp_path)
    script = _script(tmp_path)
    for cmd in ("pytest -q", "git status", "git add .", "git commit -m x"):
        out = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                                 "tool_input": {"command": cmd}})
        assert out["permissionDecision"] == "allow", (cmd, out)


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


def test_harness_cli_python_module_form_allows(tmp_path: Path) -> None:
    """python -m harness.cli <subcomando enumerado> deve ser allow, mesmo
    sem nenhum verify_cmd/lint/build que case por acaso."""
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                              "tool_input": {"command": "python -m harness.cli analyze --dir ."}})
    assert out["permissionDecision"] == "allow", out


def test_harness_cli_console_script_form_allows(tmp_path: Path) -> None:
    """A forma console-script (`harness <sub>`) tambem liberada."""
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                              "tool_input": {"command": "harness analyze --dir ."}})
    assert out["permissionDecision"] == "allow", out


def test_harness_compile_contract_via_python_module_allows(tmp_path: Path) -> None:
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    script = _script(tmp_path)
    out = _run_hook(script, {
        "tool_name": "Bash", "cwd": str(tmp_path),
        "tool_input": {"command": "python -m harness.cli compile-contract --dir . --slug x"},
    })
    assert out["permissionDecision"] == "allow", out


def test_harness_cli_smuggled_with_floor_command_still_denies(tmp_path: Path) -> None:
    """`harness analyze && git push origin main` continua deny — o floor
    roda antes de qualquer allow, mesmo colado a um subcomando liberado."""
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    script = _script(tmp_path)
    out = _run_hook(script, {
        "tool_name": "Bash", "cwd": str(tmp_path),
        "tool_input": {"command": "harness analyze && git push origin main"},
    })
    assert out["permissionDecision"] == "deny", out
    assert "runtime floor" in out["permissionDecisionReason"]


def test_harness_run_subcommand_is_not_in_enumerated_allowlist(tmp_path: Path) -> None:
    """Prova negativa: `run` (orquestrador com rede fora do floor) foi
    deliberadamente deixado de fora da lista enumerada."""
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                              "tool_input": {"command": "harness run --dir ."}})
    assert out["permissionDecision"] == "deny", out


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


def test_notebookedit_outside_surface_denies(tmp_path: Path) -> None:
    """Achado #1: NotebookEdit nunca invocava o hook (matcher estreito) —
    agora roteado explicitamente para _evaluate_file sobre notebook_path."""
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "NotebookEdit", "cwd": str(tmp_path),
                              "tool_input": {"notebook_path": "notebooks/analysis.ipynb"}})
    assert out["permissionDecision"] == "deny", out


def test_notebookedit_in_surface_allows(tmp_path: Path) -> None:
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["notebooks/analysis.ipynb"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "NotebookEdit", "cwd": str(tmp_path),
                              "tool_input": {"notebook_path": "notebooks/analysis.ipynb"}})
    assert out["permissionDecision"] == "allow", out


def test_notebookedit_secret_floor_denies(tmp_path: Path) -> None:
    """NotebookEdit tocando um path de segredo cai no mesmo runtime floor de
    Edit/Write — nunca vira allow, com ou sem contrato."""
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "NotebookEdit", "cwd": str(tmp_path),
                              "tool_input": {"notebook_path": ".env"}})
    assert out["permissionDecision"] == "deny", out
    assert "runtime floor" in out["permissionDecisionReason"]


def test_multiedit_in_surface_allows(tmp_path: Path) -> None:
    """Correção pós-implementação (achado adversarial Opus): MultiEdit é
    tool de escrita REAL do Claude Code, não estava roteada e caía no ramo
    de tool desconhecida (nome contém "edit" -> deny sempre). Roteada
    explicitamente para _evaluate_file sobre tool_input.file_path."""
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    script = _script(tmp_path)
    out = _run_hook(script, {
        "tool_name": "MultiEdit", "cwd": str(tmp_path),
        "tool_input": {
            "file_path": "src/main.py",
            "edits": [
                {"old_string": "a", "new_string": "b"},
                {"old_string": "c", "new_string": "d"},
            ],
        },
    })
    assert out["permissionDecision"] == "allow", out


def test_multiedit_secret_floor_denies(tmp_path: Path) -> None:
    script = _script(tmp_path)
    out = _run_hook(script, {
        "tool_name": "MultiEdit", "cwd": str(tmp_path),
        "tool_input": {"file_path": ".env", "edits": [{"old_string": "a", "new_string": "b"}]},
    })
    assert out["permissionDecision"] == "deny", out
    assert "runtime floor" in out["permissionDecisionReason"]


def test_multiedit_outside_surface_denies(tmp_path: Path) -> None:
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    script = _script(tmp_path)
    out = _run_hook(script, {
        "tool_name": "MultiEdit", "cwd": str(tmp_path),
        "tool_input": {"file_path": "src/other.py", "edits": [{"old_string": "a", "new_string": "b"}]},
    })
    assert out["permissionDecision"] == "deny", out


def test_multiedit_docs_allows(tmp_path: Path) -> None:
    """MultiEdit também se beneficia da superfície docs/** (Item 4)."""
    _contract_with_verify(tmp_path)
    script = _script(tmp_path)
    out = _run_hook(script, {
        "tool_name": "MultiEdit", "cwd": str(tmp_path),
        "tool_input": {"file_path": "docs/x.md", "edits": [{"old_string": "a", "new_string": "b"}]},
    })
    assert out["permissionDecision"] == "allow", out


def test_ghost_mcp_write_tool_denies(tmp_path: Path) -> None:
    """Tool de escrita fantasma (mcp__x__write, nome arbitrário não
    enumerado) -> deny por padrão-de-nome, mesmo sem estar na allowlist
    explícita de roteamento."""
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "mcp__filesystem__write_file", "cwd": str(tmp_path),
                              "tool_input": {"path": "/etc/passwd", "content": "x"}})
    assert out["permissionDecision"] == "deny", out


def test_ghost_mcp_create_and_edit_tools_deny(tmp_path: Path) -> None:
    script = _script(tmp_path)
    for name in ("mcp__foo__create_file", "mcp__foo__edit_document", "mcp__bar__WRITE"):
        out = _run_hook(script, {"tool_name": name, "cwd": str(tmp_path), "tool_input": {}})
        assert out["permissionDecision"] == "deny", (name, out)


def test_readonly_and_utility_tools_allow_without_regressing_to_default_deny(tmp_path: Path) -> None:
    """Read/Glob/Grep (leitura) e Task/WebFetch/TodoWrite (utilitárias
    conhecidas, incluindo Task — usada pelo próprio harness) continuam
    allow — a regressão que um default-deny ingênuo causaria."""
    script = _script(tmp_path)
    for name in ("Read", "Glob", "Grep", "Task", "WebFetch", "TodoWrite"):
        out = _run_hook(script, {"tool_name": name, "cwd": str(tmp_path),
                                  "tool_input": {"file_path": "src/main.py"}})
        assert out["permissionDecision"] == "allow", (name, out)


def test_unknown_tool_without_write_name_pattern_allows_logged(tmp_path: Path) -> None:
    """Tool desconhecida cujo nome NÃO contém write/create/edit -> allow
    LOGADO (política mínima; risco residual assumido e documentado)."""
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "mcp__foo__persist_snapshot", "cwd": str(tmp_path),
                              "tool_input": {}})
    assert out["permissionDecision"] == "allow", out
    assert "allow-logado" in out["permissionDecisionReason"]


# ---------------- Item 2: avaliador de PowerShell (floor-first) ----------------


def test_powershell_set_content_secret_denies_without_contract(tmp_path: Path) -> None:
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "PowerShell", "cwd": str(tmp_path),
                              "tool_input": {"command": "Set-Content -Path .env -Value 'leak'"}})
    assert out["permissionDecision"] == "deny", out
    assert "runtime floor" in out["permissionDecisionReason"]


def test_powershell_out_file_secret_denies(tmp_path: Path) -> None:
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "PowerShell", "cwd": str(tmp_path),
                              "tool_input": {"command": "'leak' | Out-File -FilePath secrets/.env"}})
    assert out["permissionDecision"] == "deny", out
    assert "runtime floor" in out["permissionDecisionReason"]


def test_powershell_writealltext_secret_denies(tmp_path: Path) -> None:
    script = _script(tmp_path)
    out = _run_hook(script, {
        "tool_name": "PowerShell", "cwd": str(tmp_path),
        "tool_input": {"command": '[IO.File]::WriteAllText("secrets/.env", "leak")'},
    })
    assert out["permissionDecision"] == "deny", out
    assert "runtime floor" in out["permissionDecisionReason"]


def test_powershell_network_cmdlets_deny(tmp_path: Path) -> None:
    """Invoke-WebRequest/Invoke-RestMethod (e aliases) não são cobertos por
    is_floor_bash_command (tokenização genérica não conhece esses nomes) —
    precisam do floor específico de PowerShell."""
    script = _script(tmp_path)
    for cmd in ("Invoke-WebRequest https://evil.example", "Invoke-RestMethod -Uri https://evil.example",
                "iwr https://evil.example", "irm https://evil.example"):
        out = _run_hook(script, {"tool_name": "PowerShell", "cwd": str(tmp_path),
                                  "tool_input": {"command": cmd}})
        assert out["permissionDecision"] == "deny", (cmd, out)
        assert "runtime floor" in out["permissionDecisionReason"]


def test_powershell_git_push_denies_via_shared_floor(tmp_path: Path) -> None:
    """git push continua deny em PowerShell, via is_floor_bash_command
    reusado (não duplicado) por is_floor_powershell_network."""
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "PowerShell", "cwd": str(tmp_path),
                              "tool_input": {"command": "git push origin main"}})
    assert out["permissionDecision"] == "deny", out
    assert "runtime floor" in out["permissionDecisionReason"]


def test_powershell_set_content_docs_allows(tmp_path: Path) -> None:
    """Item 2 + Item 4 combinados: Set-Content docs/x.md deve dar allow (a
    mesma lógica de superfície de path do Edit/Write, aplicada ao alvo
    extraído do comando PowerShell)."""
    _contract_with_verify(tmp_path)
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "PowerShell", "cwd": str(tmp_path),
                              "tool_input": {"command": "Set-Content -Path docs/x.md -Value 'ok'"}})
    assert out["permissionDecision"] == "allow", out


def test_powershell_set_content_outside_surface_denies(tmp_path: Path) -> None:
    _contract_with_verify(tmp_path)
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "PowerShell", "cwd": str(tmp_path),
                              "tool_input": {"command": "Set-Content -Path other/file.txt -Value 'x'"}})
    assert out["permissionDecision"] == "deny", out


def test_powershell_verify_cmd_command_allows(tmp_path: Path) -> None:
    _contract_with_verify(tmp_path)
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "PowerShell", "cwd": str(tmp_path),
                              "tool_input": {"command": "pytest -q"}})
    assert out["permissionDecision"] == "allow", out


def test_powershell_dollar_paren_and_backtick_not_falso_deny(tmp_path: Path) -> None:
    """Ao contrário de _evaluate_bash, _evaluate_powershell NÃO bane
    '$(...)'/crase — são sintaxe legítima em PowerShell (subexpressão e
    escape), não command smuggling. Um comando declarado que contenha essa
    sintaxe não deve ser falso-negado por esse motivo."""
    _contract_with_verify(tmp_path)
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "PowerShell", "cwd": str(tmp_path),
                              "tool_input": {"command": "pytest -q $(Get-Date)"}})
    assert out["permissionDecision"] == "allow", out
    assert "command substitution" not in out["permissionDecisionReason"]


def test_powershell_unrelated_command_denies(tmp_path: Path) -> None:
    _contract_with_verify(tmp_path)
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "PowerShell", "cwd": str(tmp_path),
                              "tool_input": {"command": "Remove-Item -Recurse -Force src"}})
    assert out["permissionDecision"] == "deny", out


def test_powershell_no_contract_allows(tmp_path: Path) -> None:
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "PowerShell", "cwd": str(tmp_path),
                              "tool_input": {"command": "Get-ChildItem"}})
    assert out["permissionDecision"] == "allow", out


def test_is_floor_powershell_network_importable() -> None:
    from harness.boundary_guard import is_floor_powershell_network

    assert is_floor_powershell_network("Invoke-WebRequest https://x") is True
    assert is_floor_powershell_network("iwr https://x") is True
    assert is_floor_powershell_network("git push origin main") is True
    assert is_floor_powershell_network("Get-ChildItem") is False


def test_is_floor_powershell_secret_write_importable() -> None:
    from harness.boundary_guard import is_floor_powershell_secret_write

    assert is_floor_powershell_secret_write("Set-Content -Path .env -Value x") is True
    assert is_floor_powershell_secret_write("Set-Content -Path docs/x.md -Value x") is False
    assert is_floor_powershell_secret_write("Get-Content .env") is False


# ---------------- Item 3: paridade do floor de segredo no caminho Bash ----------------


def test_bash_echo_redirect_secret_denies_without_contract(tmp_path: Path) -> None:
    """Achado #3: antes da correção, isto retornava allow (o floor de
    segredo só era checado no caminho Edit/Write)."""
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                              "tool_input": {"command": "echo LEAK > .env"}})
    assert out["permissionDecision"] == "deny", out
    assert "runtime floor" in out["permissionDecisionReason"]


def test_bash_append_redirect_secret_denies(tmp_path: Path) -> None:
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                              "tool_input": {"command": "echo LEAK >> config/.env"}})
    assert out["permissionDecision"] == "deny", out
    assert "runtime floor" in out["permissionDecisionReason"]


def test_bash_tee_secret_denies(tmp_path: Path) -> None:
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                              "tool_input": {"command": "echo LEAK | tee .env"}})
    assert out["permissionDecision"] == "deny", out
    assert "runtime floor" in out["permissionDecisionReason"]


def test_bash_redirect_quoted_secret_target_denies(tmp_path: Path) -> None:
    """Correção de bug (validação adversarial Opus, pós-implementação): o
    alvo do redirecionamento entre aspas duplas/simples escapava do floor
    porque a regex antiga capturava as aspas junto do valor (`".env"`
    inteiro), e is_floor_secret_path exige sufixo exato (`.endswith(".env")`)
    — `".env"` com aspas falhava o match. Fix: tokenizar (remove aspas),
    mesma técnica já usada no ramo `tee`. `echo LEAK > .env` (sem aspas)
    já era pego corretamente antes — mantido como controle."""
    script = _script(tmp_path)
    for cmd in (
        'echo LEAK > ".env"',
        "echo LEAK > '.env'",
        'echo LEAK >> "id_rsa"',
        'echo LEAK > "config/.env"',
        "echo LEAK > .env",  # controle: sem aspas, já funcionava antes
    ):
        out = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                                  "tool_input": {"command": cmd}})
        assert out["permissionDecision"] == "deny", (cmd, out)
        assert "runtime floor" in out["permissionDecisionReason"], (cmd, out)


def test_powershell_secret_write_quoted_target_still_denies(tmp_path: Path) -> None:
    """Teste de regressão travando que o floor de PowerShell NÃO tem o
    mesmo furo de aspas do Bash: is_floor_powershell_secret_write já
    tokenizava o comando (via _tokenize_command, que trata aspas como
    separador) desde a implementação original do Item 2 — nunca dependeu de
    regex sobre o texto bruto."""
    script = _script(tmp_path)
    for cmd in (
        'Set-Content -Path ".env" -Value "leak"',
        "Set-Content -Path '.env' -Value 'leak'",
    ):
        out = _run_hook(script, {"tool_name": "PowerShell", "cwd": str(tmp_path),
                                  "tool_input": {"command": cmd}})
        assert out["permissionDecision"] == "deny", (cmd, out)
        assert "runtime floor" in out["permissionDecisionReason"], (cmd, out)


def test_bash_read_secret_without_redirect_not_blocked_by_floor(tmp_path: Path) -> None:
    """cat .env (leitura, sem redirecionamento) não é bloqueado pelo floor
    de segredo — escopo restrito a redirecionamento/tee (não persegue todo
    comando que meramente MENCIONA um path de segredo)."""
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                              "tool_input": {"command": "cat .env"}})
    assert out["permissionDecision"] == "allow", out


def test_bash_redirect_non_secret_not_blocked_by_secret_floor(tmp_path: Path) -> None:
    """echo x > src/app.py não é bloqueado pelo FLOOR de segredo (pode ainda
    ser deny pela superfície genérica — não testado aqui — mas a razão não
    deve citar runtime floor de segredo)."""
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                              "tool_input": {"command": "echo x > src/app.py"}})
    # sem contrato ativo, cai no "sem contrato -> allow" genérico, não no floor
    assert out["permissionDecision"] == "allow", out
    assert "runtime floor" not in out["permissionDecisionReason"]


def test_is_floor_bash_secret_redirect_importable() -> None:
    from harness.boundary_guard import is_floor_bash_secret_redirect

    assert is_floor_bash_secret_redirect("echo x > .env") is True
    assert is_floor_bash_secret_redirect("echo x >> id_rsa") is True
    assert is_floor_bash_secret_redirect("echo x | tee credentials.json") is True
    assert is_floor_bash_secret_redirect("cat .env") is False
    assert is_floor_bash_secret_redirect("echo x > src/app.py") is False
    # Regressão do bug de aspas (validação adversarial Opus): alvo entre
    # aspas duplas/simples tinha que ser reconhecido tanto quanto sem aspas.
    assert is_floor_bash_secret_redirect('echo x > ".env"') is True
    assert is_floor_bash_secret_redirect("echo x > '.env'") is True
    assert is_floor_bash_secret_redirect('echo x >> "config/.env"') is True


# ---------------- Item 4: superfície de docs via docs/** dedicado ----------------


def test_write_docs_markdown_allows(tmp_path: Path) -> None:
    _contract_with_verify(tmp_path)
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Write", "cwd": str(tmp_path),
                              "tool_input": {"file_path": "docs/ARQUITETURA.md", "content": "x"}})
    assert out["permissionDecision"] == "allow", out


def test_write_docs_subdir_allows(tmp_path: Path) -> None:
    _contract_with_verify(tmp_path)
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Write", "cwd": str(tmp_path),
                              "tool_input": {"file_path": "docs/adr/0001-decisao.md", "content": "x"}})
    assert out["permissionDecision"] == "allow", out


def test_write_docs_allows_even_without_contract(tmp_path: Path) -> None:
    """Análoga a WORK_DIR_PREFIX: docs/** é sempre gravável, com ou sem
    contrato ativo — não é uma exceção só-sob-contrato."""
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Write", "cwd": str(tmp_path),
                              "tool_input": {"file_path": "docs/README.md", "content": "x"}})
    assert out["permissionDecision"] == "allow", out


def test_write_agents_md_root_denies(tmp_path: Path) -> None:
    """AGENTS.md protegido explicitamente (defense-in-depth) — nunca cai na
    allowlist de docs/**, mesmo não estando fisicamente dentro de docs/."""
    _contract_with_verify(tmp_path)
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Write", "cwd": str(tmp_path),
                              "tool_input": {"file_path": "AGENTS.md", "content": "x"}})
    assert out["permissionDecision"] == "deny", out


def test_write_claude_plans_spec_md_root_deny(tmp_path: Path) -> None:
    _contract_with_verify(tmp_path)
    script = _script(tmp_path)
    for name in ("CLAUDE.md", "Plans.md", "spec.md"):
        out = _run_hook(script, {"tool_name": "Write", "cwd": str(tmp_path),
                                  "tool_input": {"file_path": name, "content": "x"}})
        assert out["permissionDecision"] == "deny", (name, out)


def test_write_harness_yaml_denies(tmp_path: Path) -> None:
    _contract_with_verify(tmp_path)
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Write", "cwd": str(tmp_path),
                              "tool_input": {"file_path": ".harness/harness.yaml", "content": "x"}})
    assert out["permissionDecision"] == "deny", out


def test_write_readme_root_denies_not_docs_prefix(tmp_path: Path) -> None:
    """README.md na raiz NÃO é docs/** — continua exigindo declaração em
    files[] (a correção NÃO usa allowlist *.md na raiz, proposta rejeitada)."""
    _contract_with_verify(tmp_path)
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Write", "cwd": str(tmp_path),
                              "tool_input": {"file_path": "README.md", "content": "x"}})
    assert out["permissionDecision"] == "deny", out


def test_write_docs_traversal_to_agents_md_denies(tmp_path: Path) -> None:
    """docs/../AGENTS.md normaliza para AGENTS.md — não escapa a proteção
    via segmentos de path traversal."""
    _contract_with_verify(tmp_path)
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Write", "cwd": str(tmp_path),
                              "tool_input": {"file_path": "docs/../AGENTS.md", "content": "x"}})
    assert out["permissionDecision"] == "deny", out


def test_secret_inside_docs_dir_still_denies(tmp_path: Path) -> None:
    """Floor de segredo precede a exceção docs/** — um .env escondido lá
    dentro continua bloqueado (mesmo padrão de test_secret_inside_work_dir_still_denies)."""
    _contract_with_verify(tmp_path)
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Write", "cwd": str(tmp_path),
                              "tool_input": {"file_path": "docs/.env", "content": "k=v"}})
    assert out["permissionDecision"] == "deny", out
    assert "runtime floor" in out["permissionDecisionReason"]


def test_is_docs_surface_path_importable() -> None:
    from harness.boundary_guard import _is_docs_surface_path

    assert _is_docs_surface_path("docs/ARQUITETURA.md") is True
    assert _is_docs_surface_path("docs/sub/x.md") is True
    assert _is_docs_surface_path("AGENTS.md") is False
    assert _is_docs_surface_path("README.md") is False
    assert _is_docs_surface_path(".harness/harness.yaml") is False
    assert _is_docs_surface_path("docs/../AGENTS.md") is False
    assert _is_docs_surface_path("docs/../CLAUDE.md") is False


# ---------------- Item 6: raiz do repo fixada (deriva de cwd) ----------------


def test_derived_cwd_with_repo_root_anchors_edit_correctly(tmp_path: Path) -> None:
    """Cenário central do Item 6: `cwd` do payload "derivou" (ex.: o agente
    rodou `cd frontend/` sem voltar) mas `compile-session` já gravou
    `repo_root` em `compiled-state-session.json`. Um `Edit` sobre um arquivo
    IN-SURFACE (path absoluto real, sob a raiz verdadeira) deve resolver
    corretamente contra a raiz gravada — `allow`, com o motivo de
    superfície (NÃO "sem contrato ativo": isso provaria o sintoma fail-open
    que este item corrige, não a correção)."""
    _contract_with_verify(tmp_path)  # files=["src/main.py"], verify_cmd="pytest -q"
    script = _script(tmp_path)  # grava repo_root = str(tmp_path.resolve())

    derived_cwd = str(tmp_path / "frontend")  # não precisa existir em disco
    absolute_target = str(tmp_path / "src" / "main.py")

    out = _run_hook(script, {
        "tool_name": "Edit", "cwd": derived_cwd,
        "tool_input": {"file_path": absolute_target, "old_string": "x", "new_string": "y"},
    })
    assert out["permissionDecision"] == "allow", out
    assert "sem contrato ativo" not in out["permissionDecisionReason"], out
    assert "declarado em files" in out["permissionDecisionReason"], out


def test_derived_cwd_relative_file_path_allows_when_in_surface(tmp_path: Path) -> None:
    """Ressalva 3b (validação Opus pós-implementação): a troca incondicional
    de `cwd` pela âncora resolve certo pra `file_path` ABSOLUTO (teste
    acima), mas um `file_path` RELATIVO a um `cwd` derivado (shell preso em
    `<repo>/frontend`, tool manda `x.ts` querendo `frontend/x.ts`) tinha que
    ser absolutizado contra o `cwd` ORIGINAL do payload ANTES do strip pela
    âncora — senão `x.ts` bruto seria avaliado contra a raiz ancorada e daria
    falso-deny (fail-safe, mas exatamente a classe de bug que o Item 6
    corrige). Com a correção: `x.ts` + `cwd` payload `<repo>/frontend` vira
    `frontend/x.ts` (absolutizado contra o cwd do payload), que a âncora
    depois resolve certinho contra `files[]=["frontend/x.ts"]` — `allow`."""
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["frontend/x.ts"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    script = _script(tmp_path)  # grava repo_root = str(tmp_path.resolve())

    derived_cwd = str(tmp_path / "frontend")
    out = _run_hook(script, {
        "tool_name": "Edit", "cwd": derived_cwd,
        "tool_input": {"file_path": "x.ts", "old_string": "a", "new_string": "b"},
    })
    assert out["permissionDecision"] == "allow", out
    assert "sem contrato ativo" not in out["permissionDecisionReason"], out
    assert "declarado em files" in out["permissionDecisionReason"], out


def test_derived_cwd_relative_file_path_denies_when_out_of_surface(tmp_path: Path) -> None:
    """Prova negativa complementar: mesmo cwd derivado e mesma absolutização,
    um `file_path` relativo que NÃO casa nenhum `files[]` continua negado —
    a correção da Ressalva 3b não abre um allow geral, só corrige a
    resolução do path relativo."""
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["frontend/y.ts"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    script = _script(tmp_path)

    derived_cwd = str(tmp_path / "frontend")
    out = _run_hook(script, {
        "tool_name": "Edit", "cwd": derived_cwd,
        "tool_input": {"file_path": "x.ts", "old_string": "a", "new_string": "b"},
    })
    assert out["permissionDecision"] == "deny", out
    assert "fora da superficie" in out["permissionDecisionReason"], out


def test_no_drift_relative_file_path_still_allows_identically(tmp_path: Path) -> None:
    """Regressão (caso comum, cwd NÃO derivado): `file_path` relativo com
    `cwd` do payload igual à raiz real continua idêntico — absolutiza contra
    `cwd_payload` (a própria raiz), a âncora (mesma raiz) faz o strip de
    volta, resultado igual a antes da Ressalva 3b."""
    _contract_with_verify(tmp_path)  # files=["src/main.py"]
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Edit", "cwd": str(tmp_path),
                              "tool_input": {"file_path": "src/main.py"}})
    assert out["permissionDecision"] == "allow", out
    assert "declarado em files" in out["permissionDecisionReason"], out


def test_derived_cwd_with_repo_root_still_denies_out_of_surface_file(tmp_path: Path) -> None:
    """Prova negativa complementar: com a mesma raiz ancorada e o mesmo cwd
    derivado, um arquivo NÃO declarado em `files[]` continua negado — se a
    correção tivesse degenerado num allow geral (fail-open disfarçado), este
    teste pegaria."""
    _contract_with_verify(tmp_path)
    script = _script(tmp_path)

    derived_cwd = str(tmp_path / "frontend")
    absolute_target = str(tmp_path / "unrelated" / "other.py")

    out = _run_hook(script, {
        "tool_name": "Edit", "cwd": derived_cwd,
        "tool_input": {"file_path": absolute_target, "old_string": "x", "new_string": "y"},
    })
    assert out["permissionDecision"] == "deny", out
    assert "fora da superficie" in out["permissionDecisionReason"], out


def test_derived_cwd_with_repo_root_anchors_bash_verify_cmd(tmp_path: Path) -> None:
    """A mesma âncora tem que valer pro caminho Bash (`_load_json` também é
    usado por `_evaluate_bash`) — `verify_cmd` declarado no contrato roda
    mesmo com `cwd` derivado, em vez de cair no "sem contrato ativo"."""
    _contract_with_verify(tmp_path, verify_cmd="pytest -q")
    script = _script(tmp_path)

    derived_cwd = str(tmp_path / "frontend")
    out = _run_hook(script, {
        "tool_name": "Bash", "cwd": derived_cwd,
        "tool_input": {"command": "pytest -q"},
    })
    assert out["permissionDecision"] == "allow", out
    assert "sem contrato ativo" not in out["permissionDecisionReason"], out


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
    # feature_list.json sob <tmp_path>/frontend -> fail-open PRÉ-existente,
    # comportamento IDÊNTICO ao pré-correção (não quebra, não regride).
    assert out["permissionDecision"] == "allow", out
    assert "sem contrato ativo" in out["permissionDecisionReason"], out


def test_missing_session_state_file_falls_back_without_crashing(tmp_path: Path) -> None:
    """Sem `compiled-state-session.json` nenhum — o hook não pode quebrar;
    só não há âncora pra aplicar (cai no `cwd` do payload, sem drift neste
    teste)."""
    _contract_with_verify(tmp_path)
    script = _script(tmp_path)
    (tmp_path / SESSION_STATE_FILE).unlink()

    out = _run_hook(script, {"tool_name": "Edit", "cwd": str(tmp_path),
                              "tool_input": {"file_path": "src/main.py"}})
    assert out["permissionDecision"] == "allow", out


def test_invalid_json_session_state_falls_back_without_crashing(tmp_path: Path) -> None:
    """`compiled-state-session.json` corrompido (JSON inválido) — fallback
    ao `cwd` do payload, sem lançar exceção/crash no hook (prova de execução
    via subprocess: `proc.returncode == 0` é verificado dentro de
    `_run_hook`)."""
    _contract_with_verify(tmp_path)
    script = _script(tmp_path)
    (tmp_path / SESSION_STATE_FILE).write_text("{ isto nao e json valido", encoding="utf-8")

    out = _run_hook(script, {"tool_name": "Edit", "cwd": str(tmp_path),
                              "tool_input": {"file_path": "src/main.py"}})
    assert out["permissionDecision"] == "allow", out


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


def test_find_session_state_path_climbs_multiple_levels(tmp_path: Path) -> None:
    """A busca sobe por VÁRIOS níveis, não só um — simula o script instalado
    bem mais fundo que `.harness/hooks` (não deveria acontecer na prática,
    mas prova que o mecanismo não depende de uma profundidade fixa
    hardcoded)."""
    from harness.boundary_guard import _find_session_state_path

    state_path = tmp_path / SESSION_STATE_FILE
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({REPO_ROOT_STATE_KEY: str(tmp_path)}), encoding="utf-8")

    deep_dir = tmp_path / "a" / "b" / "c" / "d"
    deep_dir.mkdir(parents=True, exist_ok=True)

    assert _find_session_state_path(deep_dir) == state_path.resolve()


def test_find_session_state_path_returns_none_when_absent(tmp_path: Path) -> None:
    from harness.boundary_guard import _find_session_state_path

    assert _find_session_state_path(tmp_path) is None
