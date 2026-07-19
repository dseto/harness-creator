"""Verificação: `verify_cmd` de uma feature -> evidência executável.

Fecha o passo 11 do lifecycle (Fase 2/3): uma feature só é considerada
"provada" se o `verify_cmd` declarado em `.harness/feature_list.json` rodou
de verdade e saiu com exit code 0. Este módulo NÃO decide bloqueio de
edição sobre `feature_list.json` (outro escopo) nem ordena por `depends[]`
(idem) — apenas executa o comando de UMA feature e, em caso de sucesso,
grava a prova em `.harness/evidence/<feature_id>.json`.

Campo opcional `cwd` da feature (ver `contract.py`): diretório relativo a
`target_dir` onde `verify_cmd` roda via subprocess — existe para monorepo
(`backend/`+`frontend/`), onde um comando como `ng test` só resolve o
binário de dentro do workspace do frontend. Afeta SÓ o `cwd` do
subprocess; `target_dir` (resolução de `feature_list.json` e
`compute_files_hash`) nunca muda.

Schema exato da evidência (outras tarefas do ROADMAP dependem deste
formato — não mudar sem atualizar consumidores):

    {
      "feature_id": "T-01",
      "verify_cmd": "pytest tests/test_x.py -q",
      "recorded_at": "2026-07-16T12:00:00+00:00",
      "exit_code": 0,
      "files_hash": "sha256:<hex>"
    }

`files_hash` é o SHA-256 do conteúdo atual dos `files[]` da feature,
concatenados em ordem determinística (`sorted(files)`). Serve para uma
tarefa futura detectar evidência desatualizada (arquivo mudou depois da
verificação) sem precisar reimplementar o hash — por isso
`compute_files_hash` é exposta como função pública de módulo.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness.boundary_guard import is_floor_bash_command
from harness.contract import FEATURE_LIST_FILE

EVIDENCE_DIR = ".harness/evidence"
_VERIFY_TIMEOUT_SECONDS = 600


class VerifyError(Exception):
    """Erro antes mesmo de rodar o `verify_cmd` (feature/contrato ausente)."""


class VerifyFailedError(Exception):
    """`verify_cmd` rodou mas saiu com exit code != 0 — evidência NÃO gravada."""

    def __init__(self, feature_id: str, exit_code: int, stdout: str, stderr: str) -> None:
        super().__init__(
            f"verify_cmd da feature {feature_id} falhou com exit code {exit_code}"
        )
        self.feature_id = feature_id
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


def compute_files_hash(files: list[str], target_dir: Path) -> str:
    """SHA-256 determinístico do conteúdo atual de `files` (relativos a `target_dir`).

    Concatena, em ordem `sorted(files)`, para cada caminho: o próprio
    caminho relativo + "\n" + os bytes do arquivo + "\n". Arquivo ausente em
    disco não levanta exceção — usa o literal `b"<missing>\n"` no lugar do
    conteúdo. Retorna a string prefixada `"sha256:<hex>"`.
    """
    digest = hashlib.sha256()
    for rel_path in sorted(files):
        digest.update(rel_path.encode("utf-8"))
        digest.update(b"\n")
        file_path = target_dir / rel_path
        if file_path.is_file():
            digest.update(file_path.read_bytes())
        else:
            digest.update(b"<missing>\n")
        digest.update(b"\n")
    return f"sha256:{digest.hexdigest()}"


def _load_feature(target_dir: Path, feature_id: str) -> dict[str, Any]:
    feature_list_path = target_dir / FEATURE_LIST_FILE
    if not feature_list_path.is_file():
        raise VerifyError(f"{feature_list_path}: feature_list.json não encontrado")

    try:
        data = json.loads(feature_list_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise VerifyError(f"{feature_list_path}: JSON inválido — {exc}") from exc

    for feature in data.get("features", []):
        if feature.get("id") == feature_id:
            return feature

    raise VerifyError(f"feature '{feature_id}' não encontrada em {feature_list_path}")


def run_verify(target_dir: Path, feature_id: str) -> Path:
    """Roda o `verify_cmd` da feature `feature_id` e, se exit code == 0, grava evidência.

    Levanta `VerifyError` se a feature ou o `feature_list.json` não existirem.
    Levanta `VerifyFailedError` (carregando stdout/stderr/exit_code) se o
    `verify_cmd` sair com código != 0 — NADA é gravado em disco nesse caso.
    Retorna o Path do arquivo de evidência gravado em caso de sucesso.
    """
    target_dir = target_dir.resolve()
    feature = _load_feature(target_dir, feature_id)
    verify_cmd = feature["verify_cmd"]
    files = feature.get("files", [])

    if is_floor_bash_command(verify_cmd):
        raise VerifyError(
            f"feature '{feature_id}': verify_cmd '{verify_cmd}' bate no "
            "runtime floor (push/rede/publicacao) — nunca executado, "
            "mesmo vindo de um contrato compilado"
        )

    verify_cwd = target_dir
    feature_cwd = feature.get("cwd")
    if feature_cwd:
        verify_cwd = target_dir / feature_cwd
        if not verify_cwd.is_dir():
            raise VerifyError(
                f"feature '{feature_id}': cwd '{feature_cwd}' não existe em {target_dir}"
            )

    try:
        result = subprocess.run(
            verify_cmd,
            shell=True,
            cwd=verify_cwd,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=_VERIFY_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise VerifyError(
            f"feature '{feature_id}': verify_cmd '{verify_cmd}' excedeu o "
            f"timeout de {_VERIFY_TIMEOUT_SECONDS}s"
        ) from exc

    if result.returncode != 0:
        raise VerifyFailedError(feature_id, result.returncode, result.stdout, result.stderr)

    evidence = {
        "feature_id": feature_id,
        "verify_cmd": verify_cmd,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "exit_code": result.returncode,
        "files_hash": compute_files_hash(files, target_dir),
    }

    evidence_path = target_dir / EVIDENCE_DIR / f"{feature_id}.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return evidence_path
