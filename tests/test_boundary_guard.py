"""Testes do boundary_guard (Fase 2): dispatcher único de fronteira
(Edit/Write/Bash) a partir da superfície do contrato ativo."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from harness.boundary_guard import (
    BOUNDARY_STATE_KEY,
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
    matching = [e for e in entries if e.get("matcher") == "Edit|Write|Bash"]
    assert len(matching) == 1
    assert str(script) in matching[0]["hooks"][0]["command"]


def test_install_is_idempotent(tmp_path: Path) -> None:
    install_boundary_guard(tmp_path)
    install_boundary_guard(tmp_path)
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    entries = settings["hooks"]["PreToolUse"]
    matching = [e for e in entries if e.get("matcher") == "Edit|Write|Bash"]
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
    new_entries = [e for e in settings["hooks"]["PreToolUse"] if e.get("matcher") == "Edit|Write|Bash"]
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
