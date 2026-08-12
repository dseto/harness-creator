"""Testes do hook Stop: aviso de feature em progresso sem verificação atualizada."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from harness.stop_hook import (
    HOOK_FILENAME,
    HOOKS_DIR,
    STATE_KEY,
    install_stop_hook,
    is_feature_in_progress,
    needs_verification,
    render_stop_hook,
)
from harness.verify import compute_files_hash


def _init_git_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, text=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "a@b.com"], cwd=str(tmp_path), capture_output=True, text=True, check=True
    )
    subprocess.run(["git", "config", "user.name", "a"], cwd=str(tmp_path), capture_output=True, text=True, check=True)


def _commit_all(tmp_path: Path, message: str) -> None:
    subprocess.run(["git", "add", "-A"], cwd=str(tmp_path), capture_output=True, text=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", message], cwd=str(tmp_path), capture_output=True, text=True, check=True
    )


def _write_feature_list(tmp_path: Path, features: list[dict]) -> None:
    path = tmp_path / ".harness" / "feature_list.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"contract": "exemplo", "features": features}), encoding="utf-8")


def _write_hook_script(tmp_path: Path) -> Path:
    hooks_dir = tmp_path / ".harness" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    script_path = hooks_dir / "stop_hook.py"
    script_path.write_text(render_stop_hook(), encoding="utf-8")
    return script_path


def _run_hook(script_path: Path, cwd: Path) -> str:
    proc = subprocess.run(
        [sys.executable, str(script_path)],
        input=json.dumps({"cwd": str(cwd)}),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def _make_feature_with_uncommitted_diff(tmp_path: Path, feature_id: str = "T-01") -> dict:
    """Cria um repo git com um arquivo commitado e depois modificado (diff não commitado)."""
    _init_git_repo(tmp_path)
    target_file = tmp_path / "src" / "example.py"
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text("value = 1\n", encoding="utf-8")
    _commit_all(tmp_path, "commit inicial")

    target_file.write_text("value = 2\n", encoding="utf-8")  # não commitado

    return {
        "id": feature_id,
        "desc": "feature em progresso",
        "files": ["src/example.py"],
        "verify_cmd": "pytest",
        "passes": False,
    }


# ---------------- render_stop_hook / execução do script (comportamento fim-a-fim) ----------------

def test_no_feature_list_signals_nothing(tmp_path: Path) -> None:
    script_path = _write_hook_script(tmp_path)
    output = _run_hook(script_path, tmp_path)
    assert output == ""


def test_all_features_passing_signals_nothing(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    _write_feature_list(tmp_path, [{"id": "T-01", "files": [], "verify_cmd": "pytest", "passes": True}])
    _commit_all(tmp_path, "commit inicial")

    script_path = _write_hook_script(tmp_path)
    output = _run_hook(script_path, tmp_path)
    assert output == ""


def test_feature_pending_without_uncommitted_diff_signals_nothing(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    target_file = tmp_path / "src" / "example.py"
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text("value = 1\n", encoding="utf-8")
    _write_feature_list(
        tmp_path, [{"id": "T-01", "files": ["src/example.py"], "verify_cmd": "pytest", "passes": False}]
    )
    _commit_all(tmp_path, "commit inicial")  # nada fica não commitado depois disso

    script_path = _write_hook_script(tmp_path)
    output = _run_hook(script_path, tmp_path)
    assert output == ""


def test_feature_in_progress_without_evidence_signals(tmp_path: Path) -> None:
    feature = _make_feature_with_uncommitted_diff(tmp_path)
    _write_feature_list(tmp_path, [feature])

    script_path = _write_hook_script(tmp_path)
    output = _run_hook(script_path, tmp_path)

    assert output != ""
    payload = json.loads(output)
    context = payload["hookSpecificOutput"]["additionalContext"]
    assert payload["hookSpecificOutput"]["hookEventName"] == "Stop"
    assert "T-01" in context
    assert "harness verify" in context


# ---------------- tarefa parada esperando o humano (contrato `parei-e-sua-vez`) ----------------
#
# O defeito medido: o hook cobrava `harness verify T-04` de uma fatia que só
# andava depois de uma edição humana. O agente obedecia, falhava pelo mesmo
# motivo, e o hook cobrava de novo. Aqui o hook para de cobrar e passa a
# mostrar o que está na mão da pessoa — sem nunca bloquear a sessão.

NEEDS = "editar test_glob na linha 27 de .harness/harness.yaml e rodar harness compile-session"


def _write_block(
    tmp_path: Path,
    feature_id: str,
    *,
    contract: str = "exemplo",
    watch: str | None = None,
) -> None:
    """Grava o bloqueio pelo MÓDULO REAL, nunca por um json escrito à mão.

    A fixture antiga montava o dicionário na mão e esquecia `watch_hash` — com
    a chave ausente, o segundo caminho de destrave ficava desligado nos dois
    lados e o teste passava com a lógica errada. Usar `record_block` faz o
    registro do teste ser o mesmo registro da produção, por construção."""
    from harness.blocks import record_block

    record_block(
        tmp_path,
        contract,
        feature_id,
        needs=NEEDS,
        recorded_at="2026-08-12T01:00:00+00:00",
        watch=watch,
    )


def test_blocked_feature_is_not_asked_to_verify(tmp_path: Path) -> None:
    feature = _make_feature_with_uncommitted_diff(tmp_path)
    _write_feature_list(tmp_path, [feature])
    _write_block(tmp_path, "T-01")

    output = _run_hook(_write_hook_script(tmp_path), tmp_path)

    assert output != "", "a fatia parada continua sendo reportada — só não é cobrada"
    context = json.loads(output)["hookSpecificOutput"]["additionalContext"]
    assert "harness verify" not in context
    assert NEEDS in context
    assert "T-01" in context


def test_blocked_and_pending_features_are_reported_side_by_side(tmp_path: Path) -> None:
    """Uma parada e uma em progresso ao mesmo tempo: a cobrança continua para a
    que depende só de código, e some para a que depende de uma pessoa."""
    _init_git_repo(tmp_path)
    for name in ("a", "b"):
        path = tmp_path / "src" / f"{name}.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("value = 1\n", encoding="utf-8")
    _commit_all(tmp_path, "commit inicial")
    for name in ("a", "b"):
        (tmp_path / "src" / f"{name}.py").write_text("value = 2\n", encoding="utf-8")

    _write_feature_list(
        tmp_path,
        [
            {"id": "T-01", "files": ["src/a.py"], "verify_cmd": "pytest", "passes": False},
            {"id": "T-02", "files": ["src/b.py"], "verify_cmd": "pytest", "passes": False},
        ],
    )
    _write_block(tmp_path, "T-02")

    output = _run_hook(_write_hook_script(tmp_path), tmp_path)
    context = json.loads(output)["hookSpecificOutput"]["additionalContext"]

    assert "harness verify" in context
    assert NEEDS in context
    charged = context.split("atualizada: ")[1].split(".")[0]
    assert charged == "T-01", "só a fatia que depende de código continua cobrada"


def test_a_block_of_another_contract_does_not_silence_the_charge(tmp_path: Path) -> None:
    feature = _make_feature_with_uncommitted_diff(tmp_path)
    _write_feature_list(tmp_path, [feature])
    _write_block(tmp_path, "T-01", contract="outro-contrato")

    output = _run_hook(_write_hook_script(tmp_path), tmp_path)
    context = json.loads(output)["hookSpecificOutput"]["additionalContext"]

    assert "harness verify" in context
    assert NEEDS not in context


def test_a_blocked_feature_alone_still_never_blocks_the_session(tmp_path: Path) -> None:
    """O canal continua sendo `additionalContext`: bloqueio declarado é
    informação de estado, nunca barreira de runtime (não-objetivo do spec)."""
    feature = _make_feature_with_uncommitted_diff(tmp_path)
    _write_feature_list(tmp_path, [feature])
    _write_block(tmp_path, "T-01")

    payload = json.loads(_run_hook(_write_hook_script(tmp_path), tmp_path))

    assert payload["hookSpecificOutput"]["hookEventName"] == "Stop"
    assert "decision" not in payload


def test_the_generated_hook_stops_announcing_a_wait_that_already_ended(
    tmp_path: Path,
) -> None:
    """O caminho 2 do destrave tem de valer para o hook TAMBÉM, e é ele que
    fica mais tempo sem ser olhado. Sem isto, supervisor, placar e finish já
    voltaram a tratar a fatia como normal enquanto o hook segue anunciando
    'está PARADA' — quatro leitores do mesmo estado contando histórias
    diferentes, indefinidamente."""
    feature = _make_feature_with_uncommitted_diff(tmp_path)
    _write_feature_list(tmp_path, [feature])
    watched = tmp_path / "cfg.yaml"
    watched.write_text("antes\n", encoding="utf-8")
    _write_block(tmp_path, "T-01", watch="cfg.yaml")

    script = _write_hook_script(tmp_path)
    before = json.loads(_run_hook(script, tmp_path))["hookSpecificOutput"]["additionalContext"]
    assert NEEDS in before

    watched.write_text("depois\n", encoding="utf-8")

    after = json.loads(_run_hook(script, tmp_path))["hookSpecificOutput"]["additionalContext"]
    assert NEEDS not in after, "a espera acabou — o hook não pode seguir anunciando"
    assert "harness verify" in after, "e a fatia volta a ser cobrada como qualquer outra"


def test_the_generated_hook_keeps_the_wait_when_the_watched_file_is_unreadable(
    tmp_path: Path,
) -> None:
    """Arquivo esperado que ainda não existe é espera legítima — e continuar
    esperando é o comportamento seguro. Destravar por ausência faria toda
    espera por um arquivo A CRIAR morrer na primeira leitura."""
    feature = _make_feature_with_uncommitted_diff(tmp_path)
    _write_feature_list(tmp_path, [feature])
    _write_block(tmp_path, "T-01", watch="nao-existe.yaml")

    context = json.loads(_run_hook(_write_hook_script(tmp_path), tmp_path))[
        "hookSpecificOutput"
    ]["additionalContext"]

    assert NEEDS in context


def test_the_generated_hook_reads_blocks_without_importing_harness(tmp_path: Path) -> None:
    """D-010: o arquivo gerado repete a LEITURA magra, nunca importa o pacote —
    ele roda fora do venv do projeto. Este teste executa o arquivo GERADO (não
    uma cópia da lógica), que é o que impede a duplicação de virar divergência
    silenciosa."""
    source = render_stop_hook()

    assert "import harness" not in source
    assert "from harness" not in source
    assert ".harness/blocks" in source


def test_no_block_keeps_the_message_byte_identical(tmp_path: Path) -> None:
    """Sem nenhuma fatia parada, a saída é a de sempre — a mudança não pode
    vazar para quem nunca declarou bloqueio nenhum."""
    feature = _make_feature_with_uncommitted_diff(tmp_path)
    _write_feature_list(tmp_path, [feature])

    context = json.loads(_run_hook(_write_hook_script(tmp_path), tmp_path))[
        "hookSpecificOutput"
    ]["additionalContext"]

    assert context == (
        "Feature(s) em progresso sem verificacao atualizada: T-01. "
        "Rode `harness verify <id>` antes de encerrar a sessao para gravar "
        "a evidencia em .harness/evidence/<contrato>/<id>.json."
    )


def test_disabled_sentinel_suppresses_stop_feedback(tmp_path: Path) -> None:
    """Kill-switch: com o sentinel presente, o Stop hook faz no-op (não injeta
    feedback) mesmo num cenário que normalmente sinalizaria."""
    feature = _make_feature_with_uncommitted_diff(tmp_path)
    _write_feature_list(tmp_path, [feature])
    (tmp_path / ".harness" / "harness.disabled").write_text("{}", encoding="utf-8")

    script_path = _write_hook_script(tmp_path)
    assert _run_hook(script_path, tmp_path) == ""


def test_feature_in_progress_with_up_to_date_evidence_signals_nothing(tmp_path: Path) -> None:
    feature = _make_feature_with_uncommitted_diff(tmp_path)
    _write_feature_list(tmp_path, [feature])

    # Evidência escopada por contrato: "exemplo" é o slug do _write_feature_list.
    evidence_dir = tmp_path / ".harness" / "evidence" / "exemplo"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    current_hash = compute_files_hash(feature["files"], tmp_path)
    (evidence_dir / "T-01.json").write_text(
        json.dumps({
            "feature_id": "T-01",
            "verify_cmd": "pytest",
            "recorded_at": "2026-07-16T12:00:00+00:00",
            "exit_code": 0,
            "files_hash": current_hash,
        }),
        encoding="utf-8",
    )

    script_path = _write_hook_script(tmp_path)
    output = _run_hook(script_path, tmp_path)
    assert output == ""


def test_feature_in_progress_with_stale_evidence_signals(tmp_path: Path) -> None:
    feature = _make_feature_with_uncommitted_diff(tmp_path)
    _write_feature_list(tmp_path, [feature])

    # Evidência escopada por contrato: "exemplo" é o slug do _write_feature_list.
    evidence_dir = tmp_path / ".harness" / "evidence" / "exemplo"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "T-01.json").write_text(
        json.dumps({
            "feature_id": "T-01",
            "verify_cmd": "pytest",
            "recorded_at": "2026-07-16T12:00:00+00:00",
            "exit_code": 0,
            "files_hash": "sha256:desatualizado",
        }),
        encoding="utf-8",
    )

    script_path = _write_hook_script(tmp_path)
    output = _run_hook(script_path, tmp_path)
    assert output != ""
    context = json.loads(output)["hookSpecificOutput"]["additionalContext"]
    assert "T-01" in context


# ---------------- is_feature_in_progress / needs_verification (chamadas diretas) ----------------

def test_is_feature_in_progress_true_when_passes_false_and_uncommitted_diff(tmp_path: Path) -> None:
    feature = _make_feature_with_uncommitted_diff(tmp_path)
    assert is_feature_in_progress(feature, tmp_path) is True


def test_is_feature_in_progress_false_when_passes_true(tmp_path: Path) -> None:
    feature = _make_feature_with_uncommitted_diff(tmp_path)
    feature["passes"] = True
    assert is_feature_in_progress(feature, tmp_path) is False


def test_is_feature_in_progress_false_when_no_files_declared(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    _commit_all(tmp_path, "inicial")
    (tmp_path / "a.txt").write_text("y", encoding="utf-8")

    feature = {"id": "T-01", "files": [], "verify_cmd": "pytest", "passes": False}
    assert is_feature_in_progress(feature, tmp_path) is False


def test_is_feature_in_progress_false_when_no_uncommitted_diff(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    target_file = tmp_path / "src" / "example.py"
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text("value = 1\n", encoding="utf-8")
    _commit_all(tmp_path, "inicial")

    feature = {"id": "T-01", "files": ["src/example.py"], "verify_cmd": "pytest", "passes": False}
    assert is_feature_in_progress(feature, tmp_path) is False


def test_needs_verification_true_when_evidence_missing(tmp_path: Path) -> None:
    feature = _make_feature_with_uncommitted_diff(tmp_path)
    assert needs_verification(feature, tmp_path) is True


def test_needs_verification_false_when_evidence_hash_matches(tmp_path: Path) -> None:
    feature = _make_feature_with_uncommitted_diff(tmp_path)
    # Evidência escopada por contrato: "exemplo" é o slug do _write_feature_list.
    evidence_dir = tmp_path / ".harness" / "evidence" / "exemplo"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    current_hash = compute_files_hash(feature["files"], tmp_path)
    (evidence_dir / "T-01.json").write_text(
        json.dumps({"feature_id": "T-01", "files_hash": current_hash}), encoding="utf-8"
    )
    assert needs_verification(feature, tmp_path, "exemplo") is False


def test_needs_verification_true_when_evidence_hash_stale(tmp_path: Path) -> None:
    feature = _make_feature_with_uncommitted_diff(tmp_path)
    # Evidência escopada por contrato: "exemplo" é o slug do _write_feature_list.
    evidence_dir = tmp_path / ".harness" / "evidence" / "exemplo"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "T-01.json").write_text(
        json.dumps({"feature_id": "T-01", "files_hash": "sha256:desatualizado"}), encoding="utf-8"
    )
    assert needs_verification(feature, tmp_path) is True


def test_needs_verification_false_when_not_in_progress(tmp_path: Path) -> None:
    feature = _make_feature_with_uncommitted_diff(tmp_path)
    feature["passes"] = True
    assert needs_verification(feature, tmp_path) is False


# ---------------- install_stop_hook ----------------

def test_install_writes_hook_file(tmp_path: Path) -> None:
    hook_path = install_stop_hook(tmp_path)
    assert hook_path.is_file()
    assert hook_path == tmp_path / HOOKS_DIR / HOOK_FILENAME
    assert "Stop" in hook_path.read_text(encoding="utf-8")


def test_install_registers_hook_under_stop_event_without_matcher(tmp_path: Path) -> None:
    install_stop_hook(tmp_path)
    settings = json.loads(
        (tmp_path / ".claude" / "settings.local.json").read_text(encoding="utf-8")
    )
    assert "Stop" in settings["hooks"]
    assert "PreToolUse" not in settings["hooks"]
    entry = settings["hooks"]["Stop"][0]
    assert "matcher" not in entry
    assert "stop_hook.py" in entry["hooks"][0]["command"]


def test_install_is_idempotent_no_duplicate_entries(tmp_path: Path) -> None:
    install_stop_hook(tmp_path)
    install_stop_hook(tmp_path)

    settings = json.loads(
        (tmp_path / ".claude" / "settings.local.json").read_text(encoding="utf-8")
    )
    assert len(settings["hooks"]["Stop"]) == 1


def test_install_bakes_absolute_interpreter(tmp_path: Path) -> None:
    # Item 1 do backlog do dogfood venv-Windows — ver harness.hook_launcher.
    install_stop_hook(tmp_path)
    settings = json.loads((tmp_path / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
    command = settings["hooks"]["Stop"][0]["hooks"][0]["command"]
    assert sys.executable in command
    assert not command.startswith("python ")


def test_install_replaces_legacy_command_format_without_duplicating(tmp_path: Path) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.local.json").write_text(json.dumps({
        "hooks": {"Stop": [
            {"hooks": [{
                "type": "command",
                "command": 'python ".harness/hooks/stop_hook.py"',
            }]},
        ]},
    }), encoding="utf-8")

    install_stop_hook(tmp_path)

    settings = json.loads((claude_dir / "settings.local.json").read_text(encoding="utf-8"))
    assert len(settings["hooks"]["Stop"]) == 1
    assert sys.executable in settings["hooks"]["Stop"][0]["hooks"][0]["command"]


def test_install_records_state_under_own_key(tmp_path: Path) -> None:
    install_stop_hook(tmp_path)
    state_path = tmp_path / ".harness" / "compiled-state-session.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert STATE_KEY in state
    assert "stop_hook.py" in state[STATE_KEY]


def test_install_preserves_sibling_state_keys(tmp_path: Path) -> None:
    state_path = tmp_path / ".harness" / "compiled-state-session.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({
        "managed_session_permissions": ["Bash(git status)"],
        "session_start_hook_command": "python .harness/hooks/session_start.py",
        "boundary_guard_hook_command": "python .harness/hooks/boundary_guard.py",
    }), encoding="utf-8")

    install_stop_hook(tmp_path)

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["managed_session_permissions"] == ["Bash(git status)"]
    assert state["session_start_hook_command"] == "python .harness/hooks/session_start.py"
    assert state["boundary_guard_hook_command"] == "python .harness/hooks/boundary_guard.py"
    assert STATE_KEY in state


def test_install_preserves_manual_settings_and_other_hook_events(tmp_path: Path) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    (claude_dir / "settings.local.json").write_text(json.dumps({
        "permissions": {"allow": ["Bash(git status)"]},
        "hooks": {
            "SessionStart": [{"matcher": "*", "hooks": [{"type": "command", "command": "python session_start.py"}]}],
        },
    }), encoding="utf-8")

    install_stop_hook(tmp_path)

    settings = json.loads((claude_dir / "settings.local.json").read_text(encoding="utf-8"))
    assert settings["permissions"]["allow"] == ["Bash(git status)"]
    assert len(settings["hooks"]["SessionStart"]) == 1
    assert "Stop" in settings["hooks"]
