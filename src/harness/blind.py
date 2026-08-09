"""Camada 3 da verificação (§6) com isolamento de viés (§9.1) — o pacote cego
e o veredito do gate de entrega.

As camadas 1 e 2 já existem no harness: `pytest -k` do escopo a cada iteração,
`harness verify` + re-prova incremental ao fechar a fatia. Nenhuma das duas
pergunta se o que foi entregue é o que a demanda prometia — elas provam que o
teste passa, e o teste foi escrito pela mesma cabeça que escreveu o código.

O §9.1 do design chama UM ponto de independência de mínimo obrigatório, e é
este: antes da entrega, alguém que não implementou lê o artefato contra o
critério e devolve veredito.

**O que dá para mecanizar é a ausência.** O julgamento é do verificador; o que
o harness garante é o que ele NÃO recebe. Um prompt redigido por quem acabou de
implementar vaza a justificativa por construção, sem má-fé nenhuma — e o §9.1
é explícito: *"se o prompt do verificador contém a justificativa do
implementador, a avaliação já nasceu contaminada"*. Por isso o pacote é
derivado por código do `feature_list.json`, que já é a projeção limpa do
contrato: `desc` (o que foi prometido), `files[]` (onde olhar), `verify_cmd`
(a prova declarada). Nada mais atravessa.

Limite declarado, e não escondido: o harness não consegue provar que o
subagente recebeu SÓ o pacote — ele é um agente com acesso ao repositório, e os
arquivos do racional continuam no disco. O que o pacote faz é nomeá-los e pedir
que não sejam abertos; o que o harness garante é que o texto deles não entra
no que ele mesmo monta, e que o veredito fica preso ao estado que julgou.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness.contract import FEATURE_LIST_FILE
from harness.verify import compute_files_hash

#: Onde o pacote é gravado. `scratch/` porque é descartável: o pacote se
#: reconstrói do contrato a qualquer momento, e quem guarda a prova do
#: julgamento é o veredito, não ele.
BLIND_PACKAGE_FILE = ".harness/scratch/blind-package.md"

#: Onde o veredito fica. Fora de `scratch/`, e versionado como a evidência da
#: camada 2: é prova de que a entrega passou por um olho que não implementou.
BLIND_REVIEW_DIR = ".harness/blind-review"

#: Contrato sem slug — mesma convenção da evidência (`verify.UNSCOPED_...`).
UNSCOPED_REVIEW_FILE = "_sem-contrato"

#: Arquivos que carregam o raciocínio de quem implementou. O pacote os nomeia
#: para o verificador não abrir — cada um com o motivo, porque "não leia" sem
#: motivo é a instrução que mais se ignora.
FORBIDDEN_SOURCES = (
    (
        ".harness/work/{slug}/spec.md",
        "as decisões de desenho de quem implementou — ler isso é receber a "
        "justificativa antes do artefato",
    ),
    (
        ".harness/progress.md",
        "o histórico de tentativas: saber o que já falhou induz o julgamento "
        "na direção da explicação pronta",
    ),
    (
        ".harness/decisions.md",
        "o porquê das escolhas do projeto — mesma contaminação, com validade "
        "mais longa",
    ),
    (
        ".harness/lessons.md",
        "as fricções anotadas durante a demanda",
    ),
)


class BlindError(Exception):
    """Não há o que julgar, ou o veredito não pôde ser registrado."""


@dataclass(frozen=True)
class PackageTask:
    """Uma tarefa como o verificador a vê: promessa, lugar e prova.

    Deliberadamente NÃO tem campo para racional, nota ou justificativa. O tipo
    é a fronteira: o que não cabe aqui não chega ao verificador."""

    id: str
    desc: str
    files: tuple[str, ...]
    verify_cmd: str


def load_contract(target_dir: Path | str) -> dict[str, Any]:
    path = Path(target_dir) / FEATURE_LIST_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise BlindError(
            f"`{FEATURE_LIST_FILE}` ausente — não há contrato a julgar. "
            "Rode `harness compile-contract` antes."
        ) from exc
    except (OSError, ValueError) as exc:
        raise BlindError(f"`{FEATURE_LIST_FILE}` ilegível: {exc}") from exc
    if not isinstance(data, dict):
        raise BlindError(f"`{FEATURE_LIST_FILE}` não é um objeto JSON.")
    return data


def package_tasks(contract_data: dict[str, Any]) -> list[PackageTask]:
    tasks: list[PackageTask] = []
    for feature in contract_data.get("features") or []:
        tasks.append(
            PackageTask(
                id=str(feature.get("id") or "?"),
                desc=str(feature.get("desc") or "").strip(),
                files=tuple(str(f) for f in (feature.get("files") or [])),
                verify_cmd=str(feature.get("verify_cmd") or "").strip(),
            )
        )
    return tasks


def contract_files(contract_data: dict[str, Any]) -> list[str]:
    """União dos `files[]` de todas as tarefas — o estado que o veredito julga.

    Sem duplicata e sem ordem de contrato: quem consome é o hash, que ordena
    por conta própria."""
    files: set[str] = set()
    for feature in contract_data.get("features") or []:
        files.update(str(f) for f in (feature.get("files") or []))
    return sorted(files)


def render_package(contract: str, tasks: list[PackageTask]) -> str:
    slug = contract or "sem-contrato"
    lines = [
        f"# Verificação independente — contrato `{slug}`",
        "",
        "Você é o verificador desta entrega. Você NÃO implementou nada dela, e",
        "é justamente por isso que está sendo chamado: quem escreveu o código",
        "tende a validar as mesmas suposições que produziram o erro.",
        "",
        "## Seu papel",
        "",
        "- Julgue cada tarefa abaixo: o que está no repositório entrega o que",
        "  a tarefa prometia? Rode a prova declarada se quiser confirmar.",
        "- Devolva **veredito com evidência** — o quê e ONDE (`arquivo:linha`).",
        "  Veredito sem evidência gera re-tentativa cega.",
        "- **Não conserte nada.** Quem verificou não corrige: o veredito volta",
        "  ao loop, e é ele quem decide o que fazer. Corrigir aqui destrói o",
        "  ponto de independência que este passo existe para criar.",
        "",
        "## Não abra estes arquivos",
        "",
        "Eles contêm o raciocínio de quem implementou. Lê-los antes de julgar",
        "é receber a explicação junto com o artefato — e aí a avaliação já",
        "nasce contaminada:",
        "",
    ]
    for template, reason in FORBIDDEN_SOURCES:
        lines.append(f"- `{template.format(slug=slug)}` — {reason}")
    lines.extend(
        [
            "- as mensagens de commit (`git log`, `git show`) — é onde o racional",
            "  mais completo costuma estar escrito",
            "",
            "## O que a demanda prometia entregar",
            "",
        ]
    )
    for task in tasks:
        lines.append(f"### {task.id} — {task.desc}")
        lines.append("")
        lines.append("- onde olhar: " + ", ".join(f"`{f}`" for f in task.files))
        lines.append(f"- prova declarada: `{task.verify_cmd}`")
        lines.append("")
    lines.extend(
        [
            "## Como devolver o veredito",
            "",
            "```",
            'harness blind verdict --pass --evidence "<o que você conferiu, com arquivo:linha>"',
            'harness blind verdict --fail --evidence "<o que não confere, com arquivo:linha>"',
            "```",
            "",
            "Reprovar é um resultado legítimo do passo, não um acidente: um gate",
            "que só sabe aprovar não é gate.",
        ]
    )
    return "\n".join(lines) + "\n"


def build_package(target_dir: Path | str) -> Path:
    """Monta o pacote e o grava em disco. Devolve o caminho.

    Arquivo, e não string devolvida: o valor do pacote é poder ser despachado
    como está. Uma string que passa pela redação de quem implementou perde
    exatamente a garantia que ele existe para dar."""
    target_dir = Path(target_dir)
    data = load_contract(target_dir)
    tasks = package_tasks(data)
    if not tasks:
        raise BlindError(
            "o contrato compilado não tem tarefa nenhuma — não há entrega a julgar."
        )
    path = target_dir / BLIND_PACKAGE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_package(str(data.get("contract") or ""), tasks), encoding="utf-8"
    )
    return path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def review_path(target_dir: Path | str, contract: Any) -> Path:
    """Escopado por contrato, como a evidência da camada 2: o veredito de uma
    demanda não fala nada sobre a seguinte."""
    slug = str(contract or "").strip() or UNSCOPED_REVIEW_FILE
    return Path(target_dir) / BLIND_REVIEW_DIR / f"{slug}.json"


def read_review(target_dir: Path | str) -> dict[str, Any] | None:
    """O registro de vereditos do contrato ativo, ou `None`.

    Qualquer falha de leitura vira `None` — e isso é deliberado: arquivo
    corrompido não pode virar "aprovado" por omissão. Ausência de veredito
    legível é ausência de veredito, e o fecho volta a cobrar um."""
    target_dir = Path(target_dir)
    try:
        data = load_contract(target_dir)
    except BlindError:
        return None
    path = review_path(target_dir, data.get("contract"))
    try:
        review = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    if not isinstance(review, dict) or not isinstance(review.get("verdicts"), list):
        return None
    return review


def record_verdict(
    target_dir: Path | str,
    *,
    passed: bool,
    evidence: str,
    now: str | None = None,
) -> dict[str, Any]:
    """Acrescenta um veredito ao registro do contrato ativo.

    Append, nunca substituição: reprovação que some é reprovação que se
    re-litiga — a volta seguinte do loop não sabe que aquilo já foi julgado e
    recusado uma vez. Mesma razão de `decisions.md` ser append-only."""
    target_dir = Path(target_dir)
    evidence = (evidence or "").strip()
    if not evidence:
        raise BlindError(
            "veredito sem evidência não é veredito: um 'reprovado' sem o quê e "
            "onde gera re-tentativa cega (§9.1). Use `--evidence` com "
            "`arquivo:linha`."
        )

    data = load_contract(target_dir)
    contract = str(data.get("contract") or "")
    path = review_path(target_dir, contract)

    review = read_review(target_dir) or {"contract": contract, "verdicts": []}
    entry = {
        "verdict": "pass" if passed else "fail",
        "evidence": evidence,
        "files_hash": compute_files_hash(contract_files(data), target_dir),
        "recorded_at": now or _now(),
    }
    review["contract"] = contract
    review["verdicts"] = list(review.get("verdicts") or []) + [entry]

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(review, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return entry


def review_state(target_dir: Path | str) -> dict[str, Any]:
    """Estado do veredito da demanda: `missing`, `stale`, `failed` ou `fresh`.

    A ordem da checagem é decisão de desenho, não detalhe: o hash é conferido
    ANTES do veredito. Um "reprovado" sobre um código que já mudou não descreve
    mais o código — dizer `failed` mandaria o loop consertar algo que talvez já
    esteja consertado, quando o que falta é julgar de novo. Os dois estados
    bloqueiam o fecho de qualquer jeito; o que muda é o que o humano lê."""
    target_dir = Path(target_dir)
    review = read_review(target_dir)
    verdicts = list((review or {}).get("verdicts") or [])
    if not verdicts:
        return {"state": "missing", "verdict": None}

    last = verdicts[-1]
    try:
        data = load_contract(target_dir)
    except BlindError:
        return {"state": "missing", "verdict": None}

    current_hash = compute_files_hash(contract_files(data), target_dir)
    if last.get("files_hash") != current_hash:
        return {"state": "stale", "verdict": last}
    if last.get("verdict") != "pass":
        return {"state": "failed", "verdict": last}
    return {"state": "fresh", "verdict": last}
