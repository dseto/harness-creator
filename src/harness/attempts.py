"""Rastro de tentativas: toda passada do `verify_cmd` deixa registro em disco.

Incremento 1 do design de loop engineering
(`docs/reference/loop-engineering-design.md`, §5.1 "histórico de tentativas é
obrigatório", §4.2 budget mecânico, §8.2 regra do padrão repetido). Antecipa o
item 3 da Fase 6 do `docs/roadmap-autonomous.md`.

O que este módulo corrige: `harness verify` gravava evidência SÓ no verde — no
vermelho, por regra explícita, "NADA é gravado em disco". O efeito prático é
que o loop de autocorreção do passo 10 do lifecycle rodava de memória. Dentro
de uma sessão, o agente lembrava o que já tinha tentado; na sessão seguinte, o
`progress.md` dizia ONDE parou mas não O QUE já falhou, e a tentativa 1 era
refeita de boa fé. Pior: a regra do padrão repetido ("mesmo erro de novo = a
abordagem está errada, não a execução") não tinha nenhum dado para ser aplicada
por máquina.

Divisão de responsabilidade — este módulo NÃO decide nada:

- `attempts.py` (aqui): grava o registro e deriva contadores. Nunca executa
  `verify_cmd`, nunca lê `feature_list.json`, nunca chama git/subprocess.
- `verify.py` (T-02): chama `record_failure`/`record_pass` no caminho que já
  tem o resultado real do subprocess.
- `budget.py` (T-04): lê os contadores daqui + os tetos do contrato e emite o
  veredito `continue`/`stop_same_failure`/`stop_iterations`.

Formato — `.harness/attempts/<contrato>/<feature_id>.jsonl`, uma linha JSON
por passada, em ordem cronológica de append:

    {"result": "fail", "contract": "meu-contrato", "feature_id": "T-01",
     "recorded_at": "2026-08-09T04:00:00+00:00",
     "verify_cmd": "pytest tests/test_x.py -q", "exit_code": 1,
     "failure_line": "E   assert 1 == 2", "failure_signature": "9f2b1c...",
     "files_hash": "sha256:<hex>"}
    {"result": "pass", "recorded_at": "...", "files_hash": "sha256:<hex>"}

O registro de verde é curto de propósito: quem descreve um sucesso em detalhe é
a evidência (`.harness/evidence/`), que já existe e é a moeda de "pronto". Aqui
o `pass` serve para UMA coisa — marcar onde a sequência de falhas consecutivas
termina. E o arquivo **nunca é apagado no verde**: a pergunta "o que já falhou
nesta fatia?" é feita pela sessão seguinte, depois de a fatia ter passado.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ATTEMPTS_DIR = ".harness/attempts"

#: Espelha `verify.UNSCOPED_EVIDENCE_DIR`: subdiretório usado quando o
#: `feature_list.json` não declara `contract` (contrato compilado por versão
#: antiga, ou fixture de teste). Nome inválido como slug de propósito.
UNSCOPED_ATTEMPTS_DIR = "_sem-contrato"

#: Teto de caracteres da linha de falha guardada. A linha existe para caber
#: numa tabela do `progress.md` e num relatório de escalada — traceback inteiro
#: é o que está no terminal e no jsonl do runner, não aqui.
_FAILURE_LINE_MAX = 300

#: Prefixo do sha256 usado como assinatura. 12 hex (48 bits) é curto o
#: bastante para caber na linha do `progress.md` e longo o bastante para que
#: duas falhas distintas da MESMA fatia colidirem seja irrelevante na prática —
#: o universo comparado é uma dúzia de tentativas, não um índice global.
_SIGNATURE_LENGTH = 12


def attempts_path(target_dir: Path, contract: Any, feature_id: str) -> Path:
    """`.harness/attempts/<contrato>/<feature_id>.jsonl`.

    Escopado por contrato pelo MESMO motivo de `verify.evidence_path`: todo
    contrato começa em `T-01`. Um rastro não escopado faria o contrato novo
    herdar a contagem de falhas do anterior, e o disjuntor de `budget.py`
    pararia o loop por falhas que outro contrato cometeu — o inverso exato do
    que ele existe para fazer.
    """
    slug = str(contract or "").strip() or UNSCOPED_ATTEMPTS_DIR
    return Path(target_dir) / ATTEMPTS_DIR / slug / f"{feature_id}.jsonl"


def failure_signature(failure_line: str) -> str:
    """Assinatura estável da linha de falha — o sinal de §8.2.

    Normaliza só espaço em branco (strip + colapso), nunca caixa nem
    pontuação: runner de teste realinha coluna entre rodadas e isso não é
    mudança de falha, mas `AssertionError` e `assertionerror` vindos de
    lugares diferentes do código são falhas diferentes e precisam continuar
    distinguíveis.
    """
    normalized = " ".join((failure_line or "").split())
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return digest[:_SIGNATURE_LENGTH]


def extract_failure_line(stdout: str, stderr: str) -> str:
    """Primeira linha ÚTIL do erro cru, stderr antes de stdout.

    §3 do design: "o feedback para o Adjustment é a mensagem de erro exata, não
    um resumo — resumir erro é jogar fora o sinal". O que entra aqui é a linha
    do runner, nunca uma descrição escrita pelo agente.

    stderr primeiro porque é onde traceback e erro de importação saem; o
    fallback para stdout existe porque pytest imprime o resumo da falha lá, e
    numa suíte que só falhou em assert o stderr vem vazio. Sem nenhuma saída
    útil, devolve string vazia — `failure_signature("")` continua estável, e a
    tentativa é registrada assim mesmo (uma falha sem mensagem é um fato sobre
    a falha, não motivo para não registrá-la).
    """
    for source in (stderr, stdout):
        for raw_line in (source or "").splitlines():
            line = raw_line.strip()
            if line:
                return line[:_FAILURE_LINE_MAX]
    return ""


def _append(path: Path, record: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def record_failure(
    target_dir: Path,
    contract: Any,
    feature_id: str,
    *,
    verify_cmd: str,
    exit_code: int,
    stdout: str,
    stderr: str,
    files_hash: str,
    recorded_at: str,
) -> Path:
    """Acrescenta uma tentativa FALHA ao rastro. Retorna o caminho do jsonl.

    `recorded_at` é obrigatório e vem de fora de propósito: quem chama já tem
    um carimbo do evento, e gerar um relógio novo aqui produziria dois
    timestamps divergentes para a mesma passada (a mesma regra que fez
    `run_verify` reusar o `recorded_at` da evidência na nota do progress.md).
    """
    failure_line = extract_failure_line(stdout, stderr)
    return _append(
        attempts_path(target_dir, contract, feature_id),
        {
            "result": "fail",
            "contract": str(contract or "").strip() or None,
            "feature_id": feature_id,
            "recorded_at": recorded_at,
            "verify_cmd": verify_cmd,
            "exit_code": exit_code,
            "failure_line": failure_line,
            "failure_signature": failure_signature(failure_line),
            "files_hash": files_hash,
        },
    )


def record_pass(
    target_dir: Path,
    contract: Any,
    feature_id: str,
    *,
    files_hash: str,
    recorded_at: str,
) -> Path:
    """Acrescenta o marcador de VERDE ao rastro. Retorna o caminho do jsonl.

    Deliberadamente magro: o registro completo de um sucesso é a evidência em
    `.harness/evidence/`. Este marcador existe só para encerrar a sequência de
    falhas consecutivas — sem ele, uma fatia que passou e voltou a quebrar
    entraria no disjuntor já perto do teto, carregando falhas que o verde
    tornou irrelevantes.
    """
    return _append(
        attempts_path(target_dir, contract, feature_id),
        {
            "result": "pass",
            "recorded_at": recorded_at,
            "files_hash": files_hash,
        },
    )


def read_attempts(target_dir: Path, contract: Any, feature_id: str) -> list[dict[str, Any]]:
    """Lê o rastro em ordem cronológica. Ausente/ilegível -> `[]`, nunca levanta.

    Linha corrompida (JSON inválido, ou JSON válido que não é objeto) é PULADA
    em silêncio em vez de derrubar a leitura: o rastro é subproduto, e uma
    escrita interrompida no meio de uma linha não pode inutilizar as tentativas
    já registradas — nem, via `verify`, fazer uma verificação mudar de
    resultado. Mesma degradação graciosa de `supervisor.dispatch_next` e
    `branching.load_branch_per_contract`.
    """
    path = attempts_path(target_dir, contract, feature_id)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return []

    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def open_failures(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """As falhas AINDA EM ABERTO: a sequência desde o último verde, em ordem
    cronológica. Sem falha pendente -> `[]`.

    É a leitura de trilha que tanto o disjuntor (`summarize`, e daí o
    `harness budget`) quanto o bloco legível do `progress.md` consomem. Mora
    aqui, e não em cada consumidor, porque "o que ainda está pendente" precisa
    ser UMA definição: se o markdown decidisse por conta própria, a pessoa
    leria uma pendência enquanto a máquina contava outra.
    """
    meaningful = [r for r in records if r.get("result") in ("fail", "pass")]

    trailing: list[dict[str, Any]] = []
    for record in reversed(meaningful):
        if record.get("result") == "pass":
            break
        trailing.append(record)
    trailing.reverse()
    return trailing


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Contadores que o disjuntor de §4.2/§8.2 consome.

    - `attempts_total`: todas as falhas já registradas na fatia (histórico
      completo, atravessa verdes — serve para o relatório, não para o teto).
    - `consecutive_failures`: falhas desde o último verde. É o teto de
      iterações de §4.2.
    - `same_signature_streak`: quantas das últimas falhas consecutivas
      compartilham a assinatura da mais recente. É o sinal de §8.2 — insistir
      não adianta, a abordagem é que está errada.
    - `last_failure_line`/`last_failure_signature`: o último erro CRU, que o
      formato de escalada de §8 exige. `None` quando a última passada foi
      verde (não há falha pendente a relatar).

    Registro com `result` fora de `{"fail", "pass"}` é ignorado: só esses dois
    têm significado definido, e adivinhar o resto seria inventar sinal.
    """
    attempts_total = sum(1 for r in records if r.get("result") == "fail")
    trailing = open_failures(records)

    if trailing:
        last = trailing[-1]
        last_signature = last.get("failure_signature")
        streak = 0
        for record in reversed(trailing):
            if record.get("failure_signature") != last_signature:
                break
            streak += 1
        last_line = last.get("failure_line")
    else:
        last_signature = None
        last_line = None
        streak = 0

    return {
        "attempts_total": attempts_total,
        "consecutive_failures": len(trailing),
        "same_signature_streak": streak,
        "last_failure_line": last_line,
        "last_failure_signature": last_signature,
    }
