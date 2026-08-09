"""Re-prova incremental — a fatia nova não quebra a fatia antiga em silêncio.

§6 do design de loop engineering. A verificação de uma fatia é barata porque só
roda a prova DAQUELA fatia; o preço disso é que ela não olha para trás. A fatia 5
pode quebrar a fatia 2 e o `feature_list.json` segue alegando `passes: true` até
o gate final — muitas iterações depois, quando o diff suspeito já tem o tamanho
da demanda inteira e o diagnóstico custa caro.

A correção do design não é rodar a suíte completa a cada volta (isso é a camada
3, explicitamente proibida dentro do loop): é re-rodar as provas das fatias já
concluídas que **compartilham arquivo** com a que acabou de fechar. O custo fica
proporcional ao acoplamento real, e a regressão é pega enquanto o suspeito ainda
é do tamanho de uma iteração.

O acoplamento vem de `files[]`, que o contrato já declara — não de import, de
chamada de função nem de histórico do git. Inferir seria mais esperto e menos
confiável: acoplamento não declarado é defeito do contrato, e `harness task
add-file` existe justamente para corrigi-lo sem replanejar.

Duas escolhas do agrupamento merecem nota, porque é nelas que a re-prova deixa de
ser barata se forem erradas:

- **O comando de prova da tarefa atual não é repetido.** Ele acabou de rodar
  verde, no mesmo estado da árvore. Rodar de novo é gasto puro, e num contrato
  cujas tarefas dividem arquivo de teste (o caso comum) esse gasto seria a maior
  parte da re-prova.
- **Tarefas provadas pelo MESMO comando viram um alvo só.** O que é vermelho ou
  verde é o comando, não a tarefa: se ele falha, toda tarefa cuja prova é ele
  está sem prova. Rodá-lo uma vez por tarefa daria o mesmo veredito N vezes.
  O `cwd` entra na chave do agrupamento porque o mesmo comando em diretório
  diferente é outro comando — juntá-los rodaria a prova no lugar errado.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness.attempts import (
    extract_failure_line,
    open_failures,
    read_attempts,
    record_failure,
)
from harness.boundary_guard import is_floor_bash_command
from harness.contract import FEATURE_LIST_FILE
from harness.templates import update_progress_attempts, update_progress_status
from harness.verify import (
    _VERIFY_TIMEOUT_SECONDS,
    _run_verify_cmd,
    compute_files_hash,
    mark_feature_regressed,
    normalize_command_head,
)


class RegressionError(Exception):
    """Falha de pré-condição da re-prova (feature inexistente, contrato ilegível)."""


@dataclass(frozen=True)
class ReproofTarget:
    """Um comando de prova a re-executar e as tarefas que ele prova.

    `feature_ids` é plural de propósito: o veredito do comando vale para todas
    elas de uma vez — é isso que torna o rebaixamento (T-02) uma decisão só.
    """

    verify_cmd: str
    cwd: str | None
    feature_ids: tuple[str, ...]


def reproof_targets(feature_list: dict[str, Any], feature_id: str) -> list[ReproofTarget]:
    """Alvos de re-prova depois que `feature_id` fechou verde.

    Entra na lista a tarefa que satisfaz TODAS as condições: já está
    `passes: true`, não é a própria `feature_id`, compartilha pelo menos um
    caminho de `files[]` com ela, e sua prova não é a mesma que acabou de rodar.

    A ordem é a do próprio contrato — a de `features[]`, não a da descoberta —
    para que duas execuções sobre o mesmo estado produzam o mesmo relatório.

    Levanta `RegressionError` se `feature_id` não existir no contrato: lista
    vazia é a resposta legítima de "nada acoplado", e usá-la também para "id
    errado" desligaria a proteção em silêncio no caso em que alguém errou o id.
    """
    features = feature_list.get("features") or []

    current: dict[str, Any] | None = None
    for feature in features:
        if feature.get("id") == feature_id:
            current = feature
            break
    if current is None:
        raise RegressionError(
            f"feature '{feature_id}' não encontrada no contrato — "
            "não há de onde derivar o acoplamento para a re-prova"
        )

    current_files = set(current.get("files") or [])
    # O par (comando, cwd) é a identidade da prova, não o comando sozinho: o
    # mesmo `pytest -q` em outro diretório é outra prova, e tratá-lo como "já
    # rodou" deixaria uma tarefa acoplada sem re-prova nenhuma.
    current_proof = (current.get("verify_cmd"), current.get("cwd"))
    if not current_files:
        return []

    # dict preserva a ordem de inserção, que é a ordem do contrato — ver
    # docstring sobre determinismo do relatório.
    grouped: dict[tuple[str, str | None], list[str]] = {}
    for feature in features:
        if feature.get("id") == feature_id:
            continue
        if feature.get("passes") is not True:
            continue
        if not current_files.intersection(feature.get("files") or []):
            continue

        proof = (feature.get("verify_cmd"), feature.get("cwd"))
        if not proof[0] or proof == current_proof:
            continue

        grouped.setdefault(proof, []).append(feature["id"])

    return [
        ReproofTarget(verify_cmd=cmd, cwd=cwd, feature_ids=tuple(ids))
        for (cmd, cwd), ids in grouped.items()
    ]


def load_feature_list(target_dir: Path) -> dict[str, Any]:
    """Lê `.harness/feature_list.json`. Ausência ou JSON inválido -> `RegressionError`.

    Erro, nunca dict vazio: dict vazio faria a re-prova devolver "nada acoplado"
    para um contrato ilegível — a proteção desligada com cara de proteção ativa.
    """
    path = Path(target_dir) / FEATURE_LIST_FILE
    if not path.is_file():
        raise RegressionError(f"{path}: feature_list.json não encontrado")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise RegressionError(f"{path}: JSON inválido — {exc}") from exc


def run_reproof(
    target_dir: Path,
    feature_id: str,
    *,
    timeout_seconds: int = _VERIFY_TIMEOUT_SECONDS,
    stream: bool = False,
) -> dict[str, Any]:
    """Re-executa as provas acopladas a `feature_id` e rebaixa o que ficou vermelho.

    Chamada DEPOIS de `feature_id` já ter fechado verde. Devolve o relatório::

        {"feature_id": ..., "checked": [ {...} ], "regressed": [ids]}

    Cada item de `checked` traz `verify_cmd`, `cwd`, `feature_ids` (as tarefas
    que aquele comando prova) e um `status`:

    - ``green``     — a prova continua passando; nada muda.
    - ``regressed`` — a prova falhou: TODAS as `feature_ids` voltam a
      `passes: false`, com tentativa registrada e `progress.md` sincronizado.
    - ``error``     — não foi possível julgar (timeout, prova no runtime floor).
      **Ninguém é rebaixado.** Falha de infraestrutura (§8.3) não é regressão de
      código, e rebaixar por causa de uma máquina lenta destruiria um registro
      válido — mas o item continua no relatório, porque uma proteção que falhou
      em silêncio é indistinguível de uma proteção que passou.

    Nunca levanta por prova vermelha — vermelho é o resultado que a função
    existe para produzir. Levanta `RegressionError` só por pré-condição
    quebrada: contrato ausente/ilegível ou `feature_id` inexistente.
    """
    target_dir = Path(target_dir).resolve()
    feature_list = load_feature_list(target_dir)
    contract = str(feature_list.get("contract") or "")
    by_id = {f["id"]: f for f in feature_list.get("features") or [] if "id" in f}

    checked: list[dict[str, Any]] = []
    regressed: list[str] = []

    for target in reproof_targets(feature_list, feature_id):
        entry: dict[str, Any] = {
            "verify_cmd": target.verify_cmd,
            "cwd": target.cwd,
            "feature_ids": list(target.feature_ids),
            "status": "green",
            "exit_code": None,
            "problem": None,
        }
        checked.append(entry)

        if is_floor_bash_command(target.verify_cmd):
            # Mesma recusa de `run_verify`: um verify_cmd que bate no floor não
            # é executado nem vindo de contrato compilado. Aqui vira `error`, não
            # `regressed` — o comando não rodou, então não há veredito sobre o
            # código.
            entry["status"] = "error"
            entry["problem"] = (
                f"verify_cmd '{target.verify_cmd}' bate no runtime floor "
                "(push/rede/publicação) — não executado"
            )
            continue

        verify_cwd = target_dir / target.cwd if target.cwd else target_dir
        if not verify_cwd.is_dir():
            entry["status"] = "error"
            entry["problem"] = f"cwd '{target.cwd}' não existe em {target_dir}"
            continue

        try:
            returncode, stdout, stderr = _run_verify_cmd(
                normalize_command_head(target.verify_cmd),
                verify_cwd,
                timeout_seconds,
                stream,
            )
        except subprocess.TimeoutExpired:
            entry["status"] = "error"
            entry["problem"] = (
                f"excedeu o timeout de {timeout_seconds}s — árvore de processos "
                "encerrada; re-prova sem veredito"
            )
            continue
        except OSError as exc:
            entry["status"] = "error"
            entry["problem"] = f"não foi possível executar a prova: {exc}"
            continue

        entry["exit_code"] = returncode
        if returncode == 0:
            continue

        entry["status"] = "regressed"
        entry["problem"] = extract_failure_line(stdout, stderr)
        for regressed_id in target.feature_ids:
            _demote(
                target_dir,
                contract,
                by_id.get(regressed_id, {"id": regressed_id}),
                verify_cmd=target.verify_cmd,
                exit_code=returncode,
                stdout=stdout,
                stderr=stderr,
            )
            regressed.append(regressed_id)

    return {"feature_id": feature_id, "checked": checked, "regressed": regressed}


def _demote(
    target_dir: Path,
    contract: str,
    feature: dict[str, Any],
    *,
    verify_cmd: str,
    exit_code: int,
    stdout: str,
    stderr: str,
) -> None:
    """Tira o `passes: true` da feature e deixa o rastro da regressão.

    O rebaixamento em `feature_list.json` é o efeito que importa e é o único que
    pode levantar. O rastro (tentativa + `progress.md`) é subproduto: falha nele
    não pode desfazer nem esconder o rebaixamento, mesmo motivo de
    `metrics.record_event` — por isso o `except Exception` largo.
    """
    feature_id = feature["id"]
    mark_feature_regressed(target_dir, feature_id)
    try:
        record_failure(
            target_dir,
            contract,
            feature_id,
            verify_cmd=verify_cmd,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            files_hash=compute_files_hash(feature.get("files") or [], target_dir),
            recorded_at=datetime.now(timezone.utc).isoformat(),
        )
        update_progress_attempts(
            target_dir,
            feature_id,
            open_failures(read_attempts(target_dir, contract, feature_id)),
        )
        # A tabela do progress.md é o que a próxima sessão lê. Deixá-la em
        # `done` faria a reconciliação da abertura encontrar o progress
        # brigando com o feature_list — divergência fabricada por nós mesmos.
        update_progress_status(target_dir, feature_id, "pending")
    except Exception:  # noqa: BLE001
        pass


def render_reproof_report(report: dict[str, Any]) -> str | None:
    """Texto para o humano, ou `None` quando não há nada a dizer.

    `None` no caso limpo é regra, não economia: texto a cada verificação verde
    treina a ignorar o texto, e aí o aviso que importa passa junto com o ruído
    — mesmo motivo pelo qual `reconcile` fica calado em repositório íntegro.
    """
    interesting = [e for e in report.get("checked") or [] if e.get("status") != "green"]
    if not interesting:
        return None

    feature_id = report.get("feature_id", "?")
    lines = [
        f"re-prova incremental de {feature_id}: as provas abaixo compartilham "
        "arquivo com esta tarefa e NÃO passaram."
    ]
    for entry in interesting:
        ids = ", ".join(entry.get("feature_ids") or [])
        cwd = f" (cwd: {entry['cwd']})" if entry.get("cwd") else ""
        # Prova que falha sem escrever nada (um `exit 1` seco) deixaria um
        # travessão pendurado no fim da linha — o exit code já disse o que havia
        # a dizer.
        problem = f" — {entry['problem']}" if entry.get("problem") else ""
        if entry.get("status") == "regressed":
            lines.append(
                f"  REGRESSÃO em {ids}: `{entry['verify_cmd']}`{cwd} saiu com "
                f"exit {entry.get('exit_code')}{problem}"
            )
            lines.append(
                f"    {ids}: passes voltou para false. Conserte antes de seguir; "
                "o `harness supervise` já devolve a tarefa."
            )
        else:
            lines.append(
                f"  SEM VEREDITO para {ids}: `{entry['verify_cmd']}`{cwd}{problem}"
            )
            lines.append(
                "    Falha de ambiente não rebaixa ninguém: o registro segue "
                "valendo, mas esta prova NÃO foi confirmada."
            )
    return "\n".join(lines)
