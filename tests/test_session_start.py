"""Testes do hook SessionStart: injeção de estado (progress + feature + git log)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from harness.session_start import (
    HOOK_FILENAME,
    HOOKS_DIR,
    STATE_KEY,
    install_session_start,
    render_session_start_hook,
)

FEATURE_LIST_PENDING = {
    "contract": "exemplo-feature",
    "features": [
        {"id": "T-01", "desc": "Ja concluida", "files": [], "verify_cmd": "pytest", "passes": True},
        {"id": "T-02", "desc": "Ainda pendente", "files": [], "verify_cmd": "pytest", "passes": False},
    ],
}


def _write_hook_script(tmp_path: Path) -> Path:
    hooks_dir = tmp_path / ".harness" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    script_path = hooks_dir / "session_start.py"
    script_path.write_text(render_session_start_hook(), encoding="utf-8")
    return script_path


def _run_hook(script_path: Path, cwd: Path) -> dict:
    proc = subprocess.run(
        [sys.executable, str(script_path)],
        input=json.dumps({"cwd": str(cwd)}),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _context(payload: dict) -> str:
    return payload["hookSpecificOutput"]["additionalContext"]


# ---------------- render_session_start_hook / execução do script ----------------

def test_no_feature_list_mentions_no_active_contract(tmp_path: Path) -> None:
    """Diretório cru: sem `feature_list.json`, sem `progress.md` e sem repo git.
    Nenhuma dessas ausências pode quebrar o hook — ele ainda devolve JSON válido
    com o resto do contexto."""
    script_path = _write_hook_script(tmp_path)
    payload = _run_hook(script_path, tmp_path)

    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "Nenhum contrato ativo" in _context(payload)


def test_feature_list_with_pending_feature_cites_it(tmp_path: Path) -> None:
    feature_list_path = tmp_path / ".harness" / "feature_list.json"
    feature_list_path.parent.mkdir(parents=True, exist_ok=True)
    feature_list_path.write_text(json.dumps(FEATURE_LIST_PENDING), encoding="utf-8")

    script_path = _write_hook_script(tmp_path)
    payload = _run_hook(script_path, tmp_path)
    context = _context(payload)

    assert "T-02" in context
    assert "Ainda pendente" in context
    assert "Feature ativa/pendente: T-01" not in context


def test_feature_list_all_passing_says_no_pending_feature(tmp_path: Path) -> None:
    all_pass = {
        "features": [
            {"id": "T-01", "desc": "ok", "files": [], "verify_cmd": "pytest", "passes": True},
        ]
    }
    feature_list_path = tmp_path / ".harness" / "feature_list.json"
    feature_list_path.parent.mkdir(parents=True, exist_ok=True)
    feature_list_path.write_text(json.dumps(all_pass), encoding="utf-8")

    script_path = _write_hook_script(tmp_path)
    payload = _run_hook(script_path, tmp_path)
    assert "Nenhuma feature pendente" in _context(payload)


def test_empty_feature_list_says_no_pending_feature(tmp_path: Path) -> None:
    feature_list_path = tmp_path / ".harness" / "feature_list.json"
    feature_list_path.parent.mkdir(parents=True, exist_ok=True)
    feature_list_path.write_text(json.dumps({"features": []}), encoding="utf-8")

    script_path = _write_hook_script(tmp_path)
    payload = _run_hook(script_path, tmp_path)
    assert "Nenhuma feature pendente" in _context(payload)


def test_progress_file_content_appears_in_context(tmp_path: Path) -> None:
    progress_path = tmp_path / ".harness/progress.md"
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    progress_path.write_text(
        "# Progresso\n" + "\n".join(f"linha {i}" for i in range(30)) + "\nMARCA-UNICA-XYZ",
        encoding="utf-8",
    )

    script_path = _write_hook_script(tmp_path)
    payload = _run_hook(script_path, tmp_path)
    assert "MARCA-UNICA-XYZ" in _context(payload)


def test_git_log_appears_when_repo_has_commits(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, text=True, check=True)
    subprocess.run(["git", "config", "user.email", "a@b.com"], cwd=str(tmp_path), capture_output=True, text=True, check=True)
    subprocess.run(["git", "config", "user.name", "a"], cwd=str(tmp_path), capture_output=True, text=True, check=True)
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=str(tmp_path), capture_output=True, text=True, check=True)
    subprocess.run(["git", "commit", "-m", "commit inicial unico"], cwd=str(tmp_path), capture_output=True, text=True, check=True)

    script_path = _write_hook_script(tmp_path)
    payload = _run_hook(script_path, tmp_path)
    assert "commit inicial unico" in _context(payload)


# ---------------- T-03/onda-3: drift do boundary_guard.py instalado ----------------

def test_no_drift_warning_when_content_hash_matches_installed_hook(tmp_path: Path) -> None:
    """Hash registrado bate com o conteúdo real em disco -> nenhum aviso.

    Hash calculado a partir dos BYTES do arquivo já gravado (`read_bytes`),
    não da string em memória — `write_text` traduz `\\n` -> `\\r\\n` no
    Windows, então hashear a string antes de escrever divergiria do arquivo
    real (mesmo cuidado do `install_boundary_guard`)."""
    hooks_dir = tmp_path / ".harness" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_path = hooks_dir / "boundary_guard.py"
    hook_path.write_text("conteudo-fake-do-boundary-guard\n", encoding="utf-8")

    import hashlib
    state_path = tmp_path / ".harness" / "compiled-state-session.json"
    state_path.write_text(json.dumps({
        "boundary_guard_content_hash": hashlib.sha256(hook_path.read_bytes()).hexdigest(),
    }), encoding="utf-8")

    script_path = _write_hook_script(tmp_path)
    payload = _run_hook(script_path, tmp_path)
    assert "boundary_guard.py pode estar desatualizado" not in _context(payload)


def test_drift_warning_appears_when_installed_hook_does_not_match_recorded_hash(
    tmp_path: Path,
) -> None:
    """T-03/onda-3 (item 10 restante do laudo): hoje `session_start` não avisa
    quando o `boundary_guard.py` instalado diverge do que foi gravado na
    última instalação (edição à mão, ou código-fonte mudou sem recompilar) —
    o único jeito de perceber era rodar `harness audit` de propósito, mesma
    classe de blind-spot do kill-switch invisível (issue #52)."""
    hooks_dir = tmp_path / ".harness" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    (hooks_dir / "boundary_guard.py").write_text("conteudo EDITADO a mao\n", encoding="utf-8")

    state_path = tmp_path / ".harness" / "compiled-state-session.json"
    state_path.write_text(json.dumps({
        "boundary_guard_content_hash": "0" * 64,  # hash de um conteudo diferente
    }), encoding="utf-8")

    script_path = _write_hook_script(tmp_path)
    payload = _run_hook(script_path, tmp_path)
    context = _context(payload)
    assert "boundary_guard.py pode estar desatualizado" in context
    assert "harness audit" in context


def test_no_drift_warning_when_state_has_no_recorded_hash(tmp_path: Path) -> None:
    """Instalação anterior a esta feature (sem a chave nova no state) não pode
    virar um falso-positivo permanente."""
    hooks_dir = tmp_path / ".harness" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    (hooks_dir / "boundary_guard.py").write_text("x", encoding="utf-8")
    state_path = tmp_path / ".harness" / "compiled-state-session.json"
    state_path.write_text(json.dumps({"boundary_guard_hook_command": "x"}), encoding="utf-8")

    script_path = _write_hook_script(tmp_path)
    payload = _run_hook(script_path, tmp_path)
    assert "boundary_guard.py pode estar desatualizado" not in _context(payload)


def test_disabled_sentinel_shows_visible_banner_instead_of_normal_context(
    tmp_path: Path,
) -> None:
    """US-1 (Onda 2/T-04): com o sentinel presente, a saída do SessionStart
    deixava de existir por completo (`main()` retornava sem imprimir nada) —
    o único jeito de perceber era rodar `harness status` de propósito, o que
    já causou 4 dias de kill-switch ligado sem ninguém notar (issue #52).
    Agora a primeira mensagem da sessão avisa sozinha: desativado, desde
    quando, e o comando pra reativar. Não substitui o resto do contexto
    (feature/progress/git log) — o kill-switch é o aviso prioritário."""
    feature_list_path = tmp_path / ".harness" / "feature_list.json"
    feature_list_path.parent.mkdir(parents=True, exist_ok=True)
    feature_list_path.write_text(json.dumps(FEATURE_LIST_PENDING), encoding="utf-8")
    (tmp_path / ".harness" / "harness.disabled").write_text(
        json.dumps({"disabled_at": "2026-07-25T10:00:00+00:00", "note": "pausa de teste"}),
        encoding="utf-8",
    )

    script_path = _write_hook_script(tmp_path)
    payload = _run_hook(script_path, tmp_path)
    context = _context(payload)

    assert "desativado" in context.lower()
    assert "2026-07-25T10:00:00+00:00" in context
    assert "harness enable" in context
    # o texto do kill-switch não pode ficar enterrado sem destaque nenhum
    assert context.startswith("## ")


def test_disabled_sentinel_without_metadata_still_shows_banner(tmp_path: Path) -> None:
    """Sentinel `{}` (sem disabled_at/note, ex.: criado manualmente): o aviso
    ainda aparece, sem quebrar por causa de campo ausente."""
    (tmp_path / ".harness").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".harness" / "harness.disabled").write_text("{}", encoding="utf-8")

    script_path = _write_hook_script(tmp_path)
    payload = _run_hook(script_path, tmp_path)
    context = _context(payload)

    assert "desativado" in context.lower()
    assert "harness enable" in context


def test_without_sentinel_context_is_unchanged(tmp_path: Path) -> None:
    """Não-regressão: sem `.harness/harness.disabled`, a saída continua sendo
    o contexto normal (feature/progress/git log) — este item é só sobre
    visibilidade do kill-switch, não muda o caminho comum."""
    feature_list_path = tmp_path / ".harness" / "feature_list.json"
    feature_list_path.parent.mkdir(parents=True, exist_ok=True)
    feature_list_path.write_text(json.dumps(FEATURE_LIST_PENDING), encoding="utf-8")

    script_path = _write_hook_script(tmp_path)
    payload = _run_hook(script_path, tmp_path)
    context = _context(payload)

    assert "desativado" not in context.lower()
    assert "T-02" in context


# ---------------- install_session_start ----------------

def test_install_writes_hook_file(tmp_path: Path) -> None:
    hook_path = install_session_start(tmp_path)
    assert hook_path.is_file()
    assert hook_path == tmp_path / HOOKS_DIR / HOOK_FILENAME
    assert "SessionStart" in hook_path.read_text(encoding="utf-8")


def test_install_registers_hook_under_session_start_event(tmp_path: Path) -> None:
    install_session_start(tmp_path)
    settings = json.loads(
        (tmp_path / ".claude" / "settings.local.json").read_text(encoding="utf-8")
    )
    assert "SessionStart" in settings["hooks"]
    assert "PreToolUse" not in settings["hooks"]
    entry = settings["hooks"]["SessionStart"][0]
    assert "session_start.py" in entry["hooks"][0]["command"]


def test_install_registers_matcher_scoped_to_real_session_starts(tmp_path: Path) -> None:
    """Onda 2/T-03: `matcher: "*"` reinjetava o contexto a cada `compact` da
    sessão (não só no início real) — 3 compacts = 2.400 tokens duplicados
    (achado #5 do laudo de simplificação). `startup|resume|clear` cobre todo
    início de sessão sem casar `compact`."""
    install_session_start(tmp_path)
    settings = json.loads(
        (tmp_path / ".claude" / "settings.local.json").read_text(encoding="utf-8")
    )
    entry = settings["hooks"]["SessionStart"][0]
    assert entry["matcher"] == "startup|resume|clear"


def test_install_is_idempotent_no_duplicate_entries(tmp_path: Path) -> None:
    install_session_start(tmp_path)
    install_session_start(tmp_path)

    settings = json.loads(
        (tmp_path / ".claude" / "settings.local.json").read_text(encoding="utf-8")
    )
    assert len(settings["hooks"]["SessionStart"]) == 1


def test_install_bakes_absolute_interpreter(tmp_path: Path) -> None:
    # Item 1 do backlog do dogfood venv-Windows — ver harness.hook_launcher.
    install_session_start(tmp_path)
    settings = json.loads((tmp_path / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
    command = settings["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    assert sys.executable in command
    assert not command.startswith("python ")


def test_install_replaces_legacy_command_format_without_duplicating(tmp_path: Path) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.local.json").write_text(json.dumps({
        "hooks": {"SessionStart": [
            {"matcher": "*", "hooks": [{
                "type": "command",
                "command": 'python ".harness/hooks/session_start.py"',
            }]},
        ]},
    }), encoding="utf-8")

    install_session_start(tmp_path)

    settings = json.loads((claude_dir / "settings.local.json").read_text(encoding="utf-8"))
    assert len(settings["hooks"]["SessionStart"]) == 1
    assert sys.executable in settings["hooks"]["SessionStart"][0]["hooks"][0]["command"]


def test_install_records_state_under_own_key(tmp_path: Path) -> None:
    install_session_start(tmp_path)
    state_path = tmp_path / ".harness" / "compiled-state-session.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert STATE_KEY in state
    assert "session_start.py" in state[STATE_KEY]


def test_install_preserves_sibling_state_keys(tmp_path: Path) -> None:
    state_path = tmp_path / ".harness" / "compiled-state-session.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({
        "managed_session_permissions": ["Bash(git status)"],
        "boundary_guard_hook_command": "python .harness/hooks/boundary_guard.py",
    }), encoding="utf-8")

    install_session_start(tmp_path)

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["managed_session_permissions"] == ["Bash(git status)"]
    assert state["boundary_guard_hook_command"] == "python .harness/hooks/boundary_guard.py"
    assert STATE_KEY in state


def test_install_preserves_manual_settings_and_other_hook_events(tmp_path: Path) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    (claude_dir / "settings.local.json").write_text(json.dumps({
        "permissions": {"allow": ["Bash(git status)"]},
        "hooks": {
            "PreToolUse": [{"matcher": "Write", "hooks": [{"type": "command", "command": "python x.py"}]}],
        },
    }), encoding="utf-8")

    install_session_start(tmp_path)

    settings = json.loads((claude_dir / "settings.local.json").read_text(encoding="utf-8"))
    assert settings["permissions"]["allow"] == ["Bash(git status)"]
    assert len(settings["hooks"]["PreToolUse"]) == 1
    assert "SessionStart" in settings["hooks"]
