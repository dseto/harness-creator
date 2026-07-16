"""Dispatcher único de fronteira: `boundary_guard.py` — Fase 2 do ROADMAP.

Substitui o padrão de N guards por ação (um hook por matcher) por UM único
hook `PreToolUse` que cobre `Edit`, `Write` e `Bash` ao mesmo tempo,
decidindo `allow`/`deny` a partir da superfície do contrato ATIVO
(`.harness/feature_list.json`, compilado por `contract.py`). Resolve a
latência de N subprocessos por tool call que o design anterior (um guard
por ação, em `compiler.py`) pagava.

Duas garantias, nesta ordem, sempre:

1. **Runtime floor** — roda incondicionalmente ANTES de qualquer outra
   verificação, inclusive antes de checar se existe contrato ativo:
   `git push`, publicação/rede não planejada (`curl`, `wget`, `npm publish`,
   `pip upload`, `twine upload`, `gh release`) e escrita em arquivo de
   segredo (`.env`, `.pem`, `id_rsa`, `*credentials*`) NUNCA viram `allow`,
   com ou sem contrato ativo. Não é um guard a mais na cascata — é avaliado
   primeiro, sem exceção, porque "sem contrato → allow" avaliado antes do
   floor abriria uma falha real de segurança (push/segredos liberados em
   qualquer repo sem `feature_list.json`).
2. **Proteção contra enfraquecimento de teste** — arquivo que casa
   `test_glob` (do `repo-profile.json`) só é editável se alguma tarefa do
   contrato ativo o declarar em `files[]`; substitui o `guard_tests.py`
   estático (sempre-`ask`) do `compiler.py` por uma decisão por-tarefa.

O script gerado por `render_boundary_guard()` é standalone (stdlib apenas:
`json`, `re`, `sys` — nada de `import harness`), porque hooks do Claude
Code rodam fora do pacote instalado. `install_boundary_guard()` é quem
escreve esse script em disco e registra o hook em `.claude/settings.json`,
com merge não-destrutivo via `.harness/compiled-state-session.json` — um
arquivo PRÓPRIO deste mecanismo, distinto de `.harness/compiled-state.json`
(que `compiler.py::_write_state` continua reconstruindo do zero a cada
`harness compile`; escrever a chave nova ali seria apagada na próxima
compilação do mecanismo antigo). `compiled-state-session.json` é
COMPARTILHADO com os hooks irmãos de sessão (`session_permissions.py`,
`session_start.py`): cada um grava sob sua própria chave, sempre
preservando as chaves alheias já presentes no arquivo.

**Feature-lock em `.harness/feature_list.json`** — caso especial avaliado
ANTES da checagem genérica de superfície (mas só quando o path editado é o
próprio `feature_list.json`): uma edição (`Edit`/`Write`) que faz alguma
feature transicionar de `passes` não-`true` (ausente, `false` ou qualquer
valor != `True`) para `passes: true` só vira `allow` se, para CADA feature
transicionada, existir `.harness/evidence/<id>.json` (schema fixado em
`verify.py`) válido, com `feature_id` correspondente e `recorded_at`
(ISO8601) mais novo que `git log -1 --format=%cI` (mesmo padrão de
subprocess de `session_start.py::_read_git_log`); sem timestamp de
commit (repo sem commits / não é repo git), exige-se apenas evidência
válida. Se QUALQUER transicionada não tiver evidência fresca, `deny`
citando o(s) id(s) problemáticos. Se a edição não transicionar NENHUMA
feature para `passes:true`, delega ao comportamento genérico de superfície
(hoje resulta em `deny`, já que `feature_list.json` normalmente não é
declarado em `files[]` de nenhuma tarefa).

Esta lógica existe em DUAS cópias que precisam ficar sincronizadas, pelo
mesmo motivo do runtime floor acima: uma dentro da string retornada por
`render_boundary_guard()` (stdlib apenas, sem import de `harness.*`) e uma
importável neste módulo (`evaluate_feature_list_edit` e afins, mais abaixo)
para ser testável via pytest direto. Mudou uma, muda a outra.

**Veto do revisor (Fase 4, padrão Produtor-Revisor)** — checagem ADICIONAL
avaliada depois que a evidência fresca de TODAS as features transicionadas
já foi confirmada (a checagem acima, intocada): se
`.harness/team/manifest.json` existir, for JSON válido e declarar os papéis
`producer` e `reviewer` (`{"producer", "reviewer"} <= set(roles)`), cada
feature transicionada exige ADICIONALMENTE `.harness/review/<id>.json` com
`status == 'approved'` (lido via `harness.review.load_review` na versão
importável; réplica stdlib-only equivalente na versão standalone) e
`updated_at` mais novo que o último commit (mesmo padrão de comparação da
evidência) E não mais antigo que `evidencia.recorded_at` da mesma feature
(reusa o dict de evidência já carregado pela checagem de frescor acima — uma
aprovação anterior à ÚLTIMA evidência gravada está cobrindo um diff que o
revisor nunca viu, portanto obsoleta). Se a feature transicionada tem
`files[]` tocando o `test_glob` do repo-profile (`harness.review.is_test_diff`
na versão importável; réplica standalone equivalente, sem import), o registro
de revisão aprovado também precisa ter `justification` não-vazia (defesa em
profundidade — `review.py` já barra isso na escrita, esta é uma reconfirmação
de leitura, caso o arquivo tenha sido editado por fora da API). Sem
`manifest.json` (ausente, JSON inválido, ou sem os dois papéis), esta
checagem inteira é pulada — comportamento IDÊNTICO à Fase 3.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from harness.review import ReviewError, is_test_diff, load_review

HOOKS_DIR = ".harness/hooks"
BOUNDARY_HOOK_FILENAME = "boundary_guard.py"
SESSION_STATE_FILE = ".harness/compiled-state-session.json"
BOUNDARY_STATE_KEY = "boundary_guard_hook_command"
LEGACY_GUARD_TESTS_MARKER = "guard_tests.py"


# ---------------------------------------------------------------------------
# Runtime floor (Python real, IMPORTÁVEL) — mesmos padrões usados dentro do
# script standalone gerado por `render_boundary_guard()` mais abaixo. O hook
# standalone não pode importar `harness.*` (roda fora do pacote instalado via
# subprocess), por isso mantém sua PRÓPRIA cópia inline dos mesmos critérios;
# esta versão importável existe para que outros módulos do pacote (hoje,
# `session_permissions.py`) apliquem exatamente o mesmo critério em vez de
# divergir com uma segunda implementação. Se um dos dois lados mudar, o outro
# tem que acompanhar.
_SHELL_SPLIT = re.compile(r"[\s;&|()<>`$\"']+")

FLOOR_BASH_SEQUENCES: list[list[str]] = [
    ["git", "push"],
    ["curl"],
    ["wget"],
    ["npm", "publish"],
    ["pip", "upload"],
    ["twine", "upload"],
    ["gh", "release"],
]


def _tokenize_command(command: str) -> list[str]:
    return [t for t in _SHELL_SPLIT.split(command or "") if t]


def _has_sequence(tokens: list[str], seq: list[str]) -> bool:
    n = len(seq)
    return n > 0 and any(tokens[i:i + n] == seq for i in range(len(tokens) - n + 1))


def is_floor_bash_command(command: str) -> bool:
    """True se `command` casa alguma sequência do runtime floor (git push,
    curl, wget, npm publish, pip upload, twine upload, gh release)."""
    tokens = _tokenize_command(command)
    return any(_has_sequence(tokens, seq) for seq in FLOOR_BASH_SEQUENCES)


def is_floor_secret_path(path: str) -> bool:
    """True se `path` é um arquivo de segredo do runtime floor (.env, .pem,
    id_rsa, ou nome contendo 'credentials')."""
    lower = (path or "").replace("\\", "/").lower()
    basename = lower.rsplit("/", 1)[-1]
    return (
        lower.endswith(".env")
        or lower.endswith(".pem")
        or lower.endswith("id_rsa")
        or "credentials" in basename
    )


# ---------------------------------------------------------------------------
# Feature-lock em feature_list.json (Python real, IMPORTÁVEL) — mesma lógica
# duplicada inline dentro do script standalone gerado por
# `render_boundary_guard()` mais abaixo. Ver nota de sincronização no
# docstring do módulo.
# ---------------------------------------------------------------------------
FEATURE_LIST_RELATIVE_PATH = ".harness/feature_list.json"
EVIDENCE_DIR_NAME = ".harness/evidence"
TEAM_MANIFEST_RELATIVE_PATH = ".harness/team/manifest.json"


def _read_last_commit_timestamp(cwd: Path | str | None) -> str | None:
    """Mesmo padrão de subprocess de `session_start.py::_read_git_log`:
    `git log -1 --format=%cI` (timestamp ISO8601 do committer). Retorna
    `None` se o comando falhar (sem commits, não é repo git, git ausente)."""
    try:
        proc = subprocess.run(
            ["git", "log", "-1", "--format=%cI"],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    output = proc.stdout.strip()
    return output or None


def _parse_iso8601(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _feature_passes_map(data: Any) -> dict[Any, bool]:
    result: dict[Any, bool] = {}
    if not isinstance(data, dict):
        return result
    for feat in data.get("features") or []:
        if not isinstance(feat, dict):
            continue
        fid = feat.get("id")
        if fid is not None:
            result[fid] = feat.get("passes") is True
    return result


def _transitions_to_true(old_data: Any, new_data: Any) -> list[Any]:
    old_map = _feature_passes_map(old_data)
    new_map = _feature_passes_map(new_data)
    return [fid for fid, val in new_map.items() if val and not old_map.get(fid, False)]


def _evidence_freshness_problem(
    cwd: Path | str | None, feature_id: Any, commit_ts: str | None
) -> tuple[str | None, dict[str, Any] | None]:
    """`(None, evidence)` se a evidência de `feature_id` existe, é válida e
    (quando `commit_ts` fornecido) mais nova que ele; senão, `(problema,
    None)` descrevendo o problema. O dict de evidência é devolvido junto
    (mesmo objeto já parseado, sem reler o arquivo) para o chamador reusar na
    checagem do veto do revisor (comparação contra `evidencia.recorded_at`)."""
    base = Path(cwd) if cwd else Path(".")
    evidence_path = base / EVIDENCE_DIR_NAME / f"{feature_id}.json"
    if not evidence_path.is_file():
        return f"{feature_id}: sem evidência (.harness/evidence/{feature_id}.json não existe)", None
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return f"{feature_id}: evidência inválida (JSON malformado)", None
    if not isinstance(evidence, dict) or evidence.get("feature_id") != feature_id:
        return f"{feature_id}: evidência inválida (feature_id não corresponde)", None
    recorded_dt = _parse_iso8601(evidence.get("recorded_at"))
    if recorded_dt is None:
        return f"{feature_id}: evidência inválida (recorded_at ausente ou não-ISO8601)", None
    if commit_ts is not None:
        commit_dt = _parse_iso8601(commit_ts)
        if commit_dt is not None and recorded_dt <= commit_dt:
            return (
                f"{feature_id}: evidência mais antiga que o último commit "
                f"(recorded_at={evidence.get('recorded_at')})"
            ), None
    return None, evidence


def _read_team_manifest(cwd: Path | str | None) -> dict[str, Any] | None:
    """Lê `.harness/team/manifest.json`; devolve o dict só se o arquivo
    existir e for JSON válido representando um objeto — ausência ou JSON
    inválido devolve `None` (time não compilado ou artefato corrompido: em
    ambos os casos a checagem do veto do revisor é pulada por inteiro,
    comportamento IDÊNTICO à Fase 3)."""
    base = Path(cwd) if cwd else Path(".")
    manifest_path = base / TEAM_MANIFEST_RELATIVE_PATH
    if not manifest_path.is_file():
        return None
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _manifest_requires_review(manifest: dict[str, Any] | None) -> bool:
    """`True` só quando o manifesto declara AMBOS os papéis `producer` e
    `reviewer` — decisão do planejador: revisão obrigatória é por PROJETO,
    não por-tarefa."""
    if manifest is None:
        return False
    roles = manifest.get("roles")
    if not isinstance(roles, list):
        return False
    role_set = {r for r in roles if isinstance(r, str)}
    return "producer" in role_set and "reviewer" in role_set


def _feature_by_id(data: Any, feature_id: Any) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    for feat in data.get("features") or []:
        if isinstance(feat, dict) and feat.get("id") == feature_id:
            return feat
    return None


def _review_gate_problem(
    cwd: Path | str | None,
    feature_id: Any,
    feature_data: dict[str, Any] | None,
    commit_ts: str | None,
    evidence: dict[str, Any] | None,
) -> str | None:
    """`None` se o veto do revisor está satisfeito para `feature_id`; senão,
    string descrevendo o problema específico. Só chamada depois que o
    manifesto já confirmou `producer`+`reviewer` (`_manifest_requires_review`)
    E a evidência da feature já foi confirmada fresca (`evidence` não é
    `None` quando chamada nesse fluxo)."""
    base = Path(cwd) if cwd else Path(".")
    try:
        review = load_review(base, feature_id)
    except ReviewError as exc:
        return f"{feature_id}: registro de revisão inválido ({exc})"

    status = review.get("status")
    if status != "approved":
        return (
            f"{feature_id}: revisão pendente/rejeitada (status='{status}') — "
            f"rode harness review {feature_id} approve antes"
        )

    review_dt = _parse_iso8601(review.get("updated_at"))
    if review_dt is None:
        return f"{feature_id}: registro de revisão sem updated_at válido"

    if commit_ts is not None:
        commit_dt = _parse_iso8601(commit_ts)
        if commit_dt is not None and review_dt <= commit_dt:
            return (
                f"{feature_id}: aprovação mais antiga que o último commit "
                f"(updated_at={review.get('updated_at')})"
            )

    if evidence is not None:
        recorded_dt = _parse_iso8601(evidence.get("recorded_at"))
        if recorded_dt is not None and review_dt < recorded_dt:
            return (
                f"{feature_id}: aprovação obsoleta — evidência foi regravada depois "
                f"da aprovação (evidencia.recorded_at={evidence.get('recorded_at')}, "
                f"review.updated_at={review.get('updated_at')})"
            )

    if is_test_diff(feature_data or {}, base):
        justification = review.get("justification")
        if not justification or not str(justification).strip():
            return f"{feature_id}: aprovação de diff de teste sem justificativa registrada"

    return None


def evaluate_feature_list_edit(
    tool_name: str, tool_input: dict[str, Any], cwd: Path | str | None
) -> tuple[str, str] | None:
    """Avalia edição (`Edit`/`Write`) especificamente ao próprio
    `.harness/feature_list.json`.

    Retorna `("allow"|"deny", motivo)` se a edição transicionar alguma
    feature de `passes` != `true` para `passes: true` (caso especial de
    feature-lock). Retorna `None` se não houver nenhuma transição — o
    chamador deve delegar ao comportamento genérico de superfície
    (`_evaluate_file`), que hoje já resulta em `deny` para este path.
    """
    base = Path(cwd) if cwd else Path(".")
    feature_list_path = base / FEATURE_LIST_RELATIVE_PATH
    current_text = (
        feature_list_path.read_text(encoding="utf-8") if feature_list_path.is_file() else "{}"
    )

    if tool_name == "Write":
        proposed_text = tool_input.get("content") or ""
    else:  # Edit
        old_string = tool_input.get("old_string") or ""
        new_string = tool_input.get("new_string") or ""
        proposed_text = current_text.replace(old_string, new_string, 1)

    try:
        old_data = json.loads(current_text) if current_text.strip() else {}
    except json.JSONDecodeError:
        old_data = {}
    try:
        new_data = json.loads(proposed_text)
    except json.JSONDecodeError:
        return None  # JSON proposto inválido — não dá pra avaliar transições, delega

    transitioned = _transitions_to_true(old_data, new_data)
    if not transitioned:
        return None

    commit_ts = _read_last_commit_timestamp(base)
    problems: list[str] = []
    evidence_by_id: dict[Any, dict[str, Any]] = {}
    for fid in transitioned:
        problem, evidence = _evidence_freshness_problem(base, fid, commit_ts)
        if problem:
            problems.append(problem)
        else:
            evidence_by_id[fid] = evidence  # type: ignore[assignment]
    if problems:
        return "deny", (
            "feature-lock: transição para passes:true sem evidência fresca — "
            + "; ".join(problems)
            + " — rode harness verify <id> primeiro"
        )

    manifest = _read_team_manifest(base)
    review_required = _manifest_requires_review(manifest)
    if review_required:
        review_problems = [
            p
            for p in (
                _review_gate_problem(
                    base, fid, _feature_by_id(new_data, fid), commit_ts, evidence_by_id.get(fid)
                )
                for fid in transitioned
            )
            if p
        ]
        if review_problems:
            return "deny", (
                "feature-lock: revisão do time (produtor-revisor) pendente/obsoleta — "
                + "; ".join(review_problems)
            )

    success_message = (
        "feature-lock: transição para passes:true com evidência fresca confirmada para "
        + ", ".join(str(fid) for fid in sorted(transitioned, key=str))
    )
    if review_required:
        success_message += " e revisão do time (produtor-revisor) aprovada"
    return "allow", success_message


# ---------------------------------------------------------------------------
# Render (puro) — devolve o CÓDIGO-FONTE do hook standalone
# ---------------------------------------------------------------------------

def render_boundary_guard() -> str:
    """Devolve o código-fonte (string) do hook `PreToolUse` standalone.

    O script gerado lê o payload JSON do stdin e decide `allow`/`deny` para
    os matchers `Edit`, `Write` e `Bash`, na ORDEM descrita no docstring do
    módulo. Não importa nada de `harness.*` — stdlib apenas.
    """
    return '''"""Hook PreToolUse gerado pelo harness-creator — NÃO editar à mão.

Dispatcher único de fronteira (Edit/Write/Bash) para a superfície do
contrato ativo (.harness/feature_list.json). Gerado por
harness.boundary_guard.render_boundary_guard(); para mudar o
comportamento, edite o contrato/profile e rode a instalação novamente —
não edite este arquivo diretamente.

ORDEM DE AVALIAÇÃO (não reordenar): o runtime floor roda incondicionalmente
antes de qualquer checagem de contrato — mesmo sem .harness/feature_list.json
no repo, git push e escrita em arquivo de segredo continuam DENY.
"""
import datetime
import json
import re
import subprocess
import sys

# Metacaracteres de shell contam como separador — "git push&&true" não escapa.
SHELL_SPLIT = re.compile(r"[\\s;&|()<>`$\\"']+")

# --- runtime floor: nunca vira allow, com ou sem contrato ativo ---
FLOOR_BASH_SEQUENCES = [
    ["git", "push"],
    ["curl"],
    ["wget"],
    ["npm", "publish"],
    ["pip", "upload"],
    ["twine", "upload"],
    ["gh", "release"],
]

# --- comandos git locais sempre liberados quando há contrato ativo ---
FIXED_GIT_SEQUENCES = [
    ["git", "status"],
    ["git", "log"],
    ["git", "diff"],
    ["git", "add"],
    ["git", "commit"],
]

FEATURE_LIST_PATH = ".harness/feature_list.json"
PROFILE_PATH = ".harness/repo-profile.json"
EVIDENCE_DIR = ".harness/evidence"
TEAM_MANIFEST_PATH = ".harness/team/manifest.json"
REVIEW_DIR = ".harness/review"

# package_manager.value (analyzer.py) -> comando de instalação EXATO. Mesmo
# mapeamento de harness.session_permissions/harness.templates: o valor bruto
# do profile (ex.: "npm") NUNCA vira um comando permitido por si só - isso
# liberaria qualquer subcomando ("npm run x", "npm exec"), nao so a instalacao.
INSTALL_COMMAND_BY_PACKAGE_MANAGER = {
    "npm": "npm ci",
    "pnpm": "pnpm install --frozen-lockfile",
    "yarn": "yarn install --frozen-lockfile",
    "uv": "uv sync",
    "poetry": "poetry install",
}


def _glob_to_regex(glob):
    """Mesmo algoritmo de harness.verification.tdd_loop._glob_to_regex,
    copiado inline (o hook não pode importar a lib)."""
    escaped = re.escape(glob.replace("\\\\", "/"))
    escaped = escaped.replace(r"\\*\\*/", "(?:.*/)?")
    escaped = escaped.replace(r"\\*\\*", ".*")
    escaped = escaped.replace(r"\\*", "[^/]*")
    escaped = escaped.replace(r"\\?", "[^/]")
    return re.compile("^" + escaped + "$")


def _resolve_path(raw_path, cwd):
    path = (raw_path or "").replace("\\\\", "/")
    cwd_norm = (cwd or "").replace("\\\\", "/").rstrip("/")
    if cwd_norm and path.lower().startswith(cwd_norm.lower() + "/"):
        path = path[len(cwd_norm) + 1:]
    return path


def _is_secret_path(path):
    lower = path.lower()
    basename = lower.rsplit("/", 1)[-1]
    return (
        lower.endswith(".env")
        or lower.endswith(".pem")
        or lower.endswith("id_rsa")
        or "credentials" in basename
    )


def _tokenize(command):
    return [t for t in SHELL_SPLIT.split(command or "") if t]


def _has_sequence(tokens, seq):
    n = len(seq)
    return n > 0 and any(tokens[i:i + n] == seq for i in range(len(tokens) - n + 1))


def _matches_any_sequence(tokens, sequences):
    return any(_has_sequence(tokens, seq) for seq in sequences)


def _load_json(cwd, relative):
    base = cwd or "."
    path_str = relative
    try:
        import os
        full = os.path.join(base, relative)
        with open(full, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _profile_entry_value(profile, key):
    if not isinstance(profile, dict):
        return None
    entry = profile.get(key)
    if isinstance(entry, dict):
        return entry.get("value")
    return None


def _profile_extra_value(profile, key):
    if not isinstance(profile, dict):
        return None
    extras = profile.get("extras")
    if not isinstance(extras, dict):
        return None
    entry = extras.get(key)
    if isinstance(entry, dict):
        return entry.get("value")
    return None


def _collect_allowed_files(feature_list):
    allowed = set()
    for feat in (feature_list or {}).get("features", []) or []:
        for f in feat.get("files") or []:
            allowed.add(str(f).replace("\\\\", "/"))
    return allowed


def _collect_allowed_bash_commands(feature_list, profile):
    commands = []
    for feat in (feature_list or {}).get("features", []) or []:
        vc = feat.get("verify_cmd")
        if vc:
            commands.append(vc)
    for key in ("lint_command", "typecheck_command", "build_command"):
        value = _profile_extra_value(profile, key)
        if value:
            commands.append(value)
    package_manager_value = _profile_entry_value(profile, "package_manager")
    install_cmd = (
        INSTALL_COMMAND_BY_PACKAGE_MANAGER.get(package_manager_value)
        if package_manager_value
        else None
    )
    if install_cmd:
        commands.append(install_cmd)
    return commands


def _read_last_commit_timestamp(cwd):
    try:
        proc = subprocess.run(
            ["git", "log", "-1", "--format=%cI"],
            cwd=cwd or None,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    output = proc.stdout.strip()
    return output or None


def _parse_iso8601(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _feature_passes_map(data):
    result = {}
    if not isinstance(data, dict):
        return result
    for feat in data.get("features") or []:
        if not isinstance(feat, dict):
            continue
        fid = feat.get("id")
        if fid is not None:
            result[fid] = feat.get("passes") is True
    return result


def _transitions_to_true(old_data, new_data):
    old_map = _feature_passes_map(old_data)
    new_map = _feature_passes_map(new_data)
    return [fid for fid, val in new_map.items() if val and not old_map.get(fid, False)]


def _evidence_freshness_problem(cwd, feature_id, commit_ts):
    evidence = _load_json(cwd, EVIDENCE_DIR + "/" + str(feature_id) + ".json")
    if evidence is None:
        return (str(feature_id) + ": sem evidencia (.harness/evidence/" + str(feature_id) + ".json nao existe ou JSON invalido)"), None
    if not isinstance(evidence, dict) or evidence.get("feature_id") != feature_id:
        return (str(feature_id) + ": evidencia invalida (feature_id nao corresponde)"), None
    recorded_dt = _parse_iso8601(evidence.get("recorded_at"))
    if recorded_dt is None:
        return (str(feature_id) + ": evidencia invalida (recorded_at ausente ou nao-ISO8601)"), None
    if commit_ts is not None:
        commit_dt = _parse_iso8601(commit_ts)
        if commit_dt is not None and recorded_dt <= commit_dt:
            return (str(feature_id) + ": evidencia mais antiga que o ultimo commit (recorded_at=" + str(evidence.get("recorded_at")) + ")"), None
    return None, evidence


def _read_team_manifest(cwd):
    return _load_json(cwd, TEAM_MANIFEST_PATH)


def _manifest_requires_review(manifest):
    if not isinstance(manifest, dict):
        return False
    roles = manifest.get("roles")
    if not isinstance(roles, list):
        return False
    role_set = set(r for r in roles if isinstance(r, str))
    return "producer" in role_set and "reviewer" in role_set


def _feature_by_id(data, feature_id):
    if not isinstance(data, dict):
        return None
    for feat in data.get("features") or []:
        if isinstance(feat, dict) and feat.get("id") == feature_id:
            return feat
    return None


def _is_test_diff(feature, cwd):
    """Equivalente standalone de harness.review.is_test_diff — o hook nao
    pode importar a lib, entao replica: casa feature['files'] contra o
    test_glob do repo-profile usando o _glob_to_regex ja copiado acima."""
    profile = _load_json(cwd, PROFILE_PATH)
    test_glob = _profile_entry_value(profile, "test_glob")
    if not test_glob:
        return False
    pattern = _glob_to_regex(test_glob)
    files = (feature or {}).get("files") or []
    for f in files:
        normalized = str(f).replace("\\\\", "/")
        if pattern.match(normalized):
            return True
    return False


def _load_review_record(cwd, feature_id):
    """Equivalente standalone de harness.review.load_review: devolve
    (record, problema). Arquivo ausente -> registro DEFAULT status='pending'
    (mesmo comportamento de load_review, sem gravar em disco); JSON invalido
    -> (None, problema)."""
    import os
    base = cwd or "."
    full = os.path.join(base, REVIEW_DIR, str(feature_id) + ".json")
    if not os.path.isfile(full):
        return {
            "feature_id": feature_id,
            "status": "pending",
            "iteration": 0,
            "max_iterations": 3,
            "history": [],
            "justification": None,
            "updated_at": "",
        }, None
    try:
        with open(full, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None, str(feature_id) + ": registro de revisao invalido (JSON malformado)"
    if not isinstance(data, dict):
        return None, str(feature_id) + ": registro de revisao invalido (formato inesperado)"
    return data, None


def _review_gate_problem(cwd, feature_id, feature_data, commit_ts, evidence):
    record, load_problem = _load_review_record(cwd, feature_id)
    if load_problem:
        return load_problem

    status = record.get("status")
    if status != "approved":
        return (
            str(feature_id) + ": revisao pendente/rejeitada (status='" + str(status) + "') - "
            "rode harness review " + str(feature_id) + " approve antes"
        )

    review_dt = _parse_iso8601(record.get("updated_at"))
    if review_dt is None:
        return str(feature_id) + ": registro de revisao sem updated_at valido"

    if commit_ts is not None:
        commit_dt = _parse_iso8601(commit_ts)
        if commit_dt is not None and review_dt <= commit_dt:
            return str(feature_id) + ": aprovacao mais antiga que o ultimo commit (updated_at=" + str(record.get("updated_at")) + ")"

    if evidence is not None:
        recorded_dt = _parse_iso8601(evidence.get("recorded_at"))
        if recorded_dt is not None and review_dt < recorded_dt:
            return (
                str(feature_id) + ": aprovacao obsoleta - evidencia foi regravada depois da "
                "aprovacao (evidencia.recorded_at=" + str(evidence.get("recorded_at")) +
                ", review.updated_at=" + str(record.get("updated_at")) + ")"
            )

    if _is_test_diff(feature_data, cwd):
        justification = record.get("justification")
        if not justification or not str(justification).strip():
            return str(feature_id) + ": aprovacao de diff de teste sem justificativa registrada"

    return None


def _evaluate_feature_list_edit(tool_name, tool_input, cwd):
    base = cwd or "."
    import os
    full = os.path.join(base, FEATURE_LIST_PATH)
    if os.path.isfile(full):
        with open(full, "r", encoding="utf-8") as fh:
            current_text = fh.read()
    else:
        current_text = "{}"

    if tool_name == "Write":
        proposed_text = tool_input.get("content") or ""
    else:
        old_string = tool_input.get("old_string") or ""
        new_string = tool_input.get("new_string") or ""
        proposed_text = current_text.replace(old_string, new_string, 1)

    try:
        old_data = json.loads(current_text) if current_text.strip() else {}
    except ValueError:
        old_data = {}
    try:
        new_data = json.loads(proposed_text)
    except ValueError:
        return None

    transitioned = _transitions_to_true(old_data, new_data)
    if not transitioned:
        return None

    commit_ts = _read_last_commit_timestamp(cwd)
    problems = []
    evidence_by_id = {}
    for fid in transitioned:
        problem, evidence = _evidence_freshness_problem(cwd, fid, commit_ts)
        if problem:
            problems.append(problem)
        else:
            evidence_by_id[fid] = evidence

    if problems:
        return "deny", (
            "feature-lock: transicao para passes:true sem evidencia fresca - "
            + "; ".join(problems)
            + " - rode harness verify <id> primeiro"
        )

    manifest = _read_team_manifest(cwd)
    review_required = _manifest_requires_review(manifest)
    if review_required:
        review_problems = []
        for fid in transitioned:
            problem = _review_gate_problem(
                cwd, fid, _feature_by_id(new_data, fid), commit_ts, evidence_by_id.get(fid)
            )
            if problem:
                review_problems.append(problem)
        if review_problems:
            return "deny", (
                "feature-lock: revisao do time (produtor-revisor) pendente/obsoleta - "
                + "; ".join(review_problems)
            )

    success_message = (
        "feature-lock: transicao para passes:true com evidencia fresca confirmada para "
        + ", ".join(str(fid) for fid in sorted(transitioned, key=str))
    )
    if review_required:
        success_message += " e revisao do time (produtor-revisor) aprovada"
    return "allow", success_message


def _evaluate_file(path, cwd):
    if _is_secret_path(path):
        return "deny", (
            "runtime floor: escrita em arquivo de segredo (.env/.pem/id_rsa/"
            "credentials) e bloqueio incondicional, independente de contrato ativo"
        )

    feature_list = _load_json(cwd, FEATURE_LIST_PATH)
    if feature_list is None:
        return "allow", "sem contrato ativo — boundary_guard não gateia fora de uma sessão de contrato"

    allowed_files = _collect_allowed_files(feature_list)
    profile = _load_json(cwd, PROFILE_PATH)
    test_glob = _profile_entry_value(profile, "test_glob")

    if test_glob:
        pattern = _glob_to_regex(test_glob)
        if pattern.match(path):
            if path in allowed_files:
                return "allow", "arquivo de teste declarado em files[] de uma tarefa do contrato ativo"
            return "deny", (
                "arquivo de teste protegido: nenhuma tarefa do contrato ativo declara "
                "este arquivo em files[] - enfraquecimento de teste fora do escopo aprovado"
            )

    if path in allowed_files:
        return "allow", "arquivo declarado em files[] de uma tarefa do contrato ativo"
    return "deny", (
        "arquivo fora da superficie do contrato ativo (nenhuma tarefa declara este "
        "path em files[]); replaneje via /harness-creator:plan se o escopo mudou"
    )


def _evaluate_bash(command, cwd):
    tokens = _tokenize(command)

    if _matches_any_sequence(tokens, FLOOR_BASH_SEQUENCES):
        return "deny", (
            "runtime floor: comando de push/publicacao/rede nao planejado - "
            "bloqueio incondicional, independente de contrato ativo"
        )

    feature_list = _load_json(cwd, FEATURE_LIST_PATH)
    if feature_list is None:
        return "allow", "sem contrato ativo — boundary_guard não gateia fora de uma sessão de contrato"

    profile = _load_json(cwd, PROFILE_PATH)
    allowed_commands = _collect_allowed_bash_commands(feature_list, profile)
    allowed_sequences = FIXED_GIT_SEQUENCES + [_tokenize(c) for c in allowed_commands]

    if _matches_any_sequence(tokens, allowed_sequences):
        return "allow", (
            "comando declarado na superficie compilada do contrato "
            "(verify_cmd/lint/typecheck/build/install/git local)"
        )
    return "deny", (
        "comando fora da superficie compilada do contrato "
        "(verify_cmd/lint/typecheck/build/install/git local); replaneje via "
        "/harness-creator:plan se precisar de outro comando"
    )


def main() -> None:
    data = json.load(sys.stdin)
    tool_name = data.get("tool_name") or ""
    tool_input = data.get("tool_input") or {}
    cwd = data.get("cwd") or ""

    if tool_name in ("Edit", "Write"):
        path = _resolve_path(tool_input.get("file_path") or "", cwd)
        special = None
        if path == FEATURE_LIST_PATH:
            special = _evaluate_feature_list_edit(tool_name, tool_input, cwd)
        if special is not None:
            decision, reason = special
        else:
            decision, reason = _evaluate_file(path, cwd)
    elif tool_name == "Bash":
        command = tool_input.get("command") or ""
        decision, reason = _evaluate_bash(command, cwd)
    else:
        decision, reason = "allow", "ferramenta fora do escopo do boundary_guard"

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }))


if __name__ == "__main__":
    main()
'''


# ---------------------------------------------------------------------------
# Apply (escreve no projeto-alvo) — sem importar compiler.py
# ---------------------------------------------------------------------------

def _load_json_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def install_boundary_guard(target_dir: Path) -> Path:
    """Instala `boundary_guard.py` como o único hook `PreToolUse` de
    Edit/Write/Bash em `target_dir`.

    Escreve `target_dir/.harness/hooks/boundary_guard.py` e registra o hook
    em `target_dir/.claude/settings.json` (matcher `"Edit|Write|Bash"`).
    Merge não-destrutivo via `target_dir/.harness/compiled-state-session.json`
    (chave própria `boundary_guard_hook_command`, preservando outras chaves
    já presentes — o arquivo é compartilhado com hooks irmãos de sessão).

    Também remove, de `hooks.PreToolUse`, qualquer entrada legada cujo
    `command` referencie o `guard_tests.py` gerado pelo `compiler.py`
    (mecanismo antigo, v0.10.0): o `boundary_guard.py` já cobre a proteção
    de teste (por tarefa do contrato), e manter os dois ativos faria o hook
    antigo disparar `ask` (auto-negado em modo headless) para o mesmo Edit
    que este já libera por `allow`. Nenhuma outra entrada de
    `hooks.PreToolUse` é tocada (ex.: `guard_test_runner.py`).
    """
    target_dir = target_dir.resolve()

    hooks_dir = target_dir / HOOKS_DIR
    hooks_dir.mkdir(parents=True, exist_ok=True)
    script_path = hooks_dir / BOUNDARY_HOOK_FILENAME
    script_path.write_text(render_boundary_guard(), encoding="utf-8")

    command = f'python "{script_path}"'

    settings_path = target_dir / ".claude" / "settings.json"
    settings: dict[str, Any] = _load_json_state(settings_path)

    state_path = target_dir / SESSION_STATE_FILE
    state: dict[str, Any] = _load_json_state(state_path)
    old_command = state.get(BOUNDARY_STATE_KEY)

    hooks = settings.setdefault("hooks", {})
    pre = hooks.get("PreToolUse", [])

    def _is_old_managed(entry: dict[str, Any]) -> bool:
        return old_command is not None and any(
            h.get("command") == old_command for h in entry.get("hooks", [])
        )

    def _is_legacy_guard_tests(entry: dict[str, Any]) -> bool:
        return any(
            LEGACY_GUARD_TESTS_MARKER in (h.get("command") or "")
            for h in entry.get("hooks", [])
        )

    kept_entries = [
        e for e in pre if not _is_old_managed(e) and not _is_legacy_guard_tests(e)
    ]
    new_entry = {
        "matcher": "Edit|Write|Bash",
        "hooks": [{"type": "command", "command": command}],
    }
    hooks["PreToolUse"] = kept_entries + [new_entry]

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    state[BOUNDARY_STATE_KEY] = command
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    return script_path
