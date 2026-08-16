"""Bloqueio declarado: o estado "parei, é sua vez".

T-01 do contrato `parei-e-sua-vez`. Até aqui uma feature existia em dois
estados — `passes: true` ou `passes: false` (`contract.py:781-795`) — e por
isso "estou esperando uma pessoa" era indistinguível de "ainda não
implementei". O efeito, medido numa sessão real: o agente entendeu que
dependia de uma edição humana, escreveu isso na tela, e mesmo assim continuou
tentando a mesma tarefa dezenas de vezes, porque `supervisor.ready_features`
devolvia a fatia como próxima e o hook Stop cobrava a verificação dela. A
informação existia; não tinha onde ser registrada.

Divisão de responsabilidade — este módulo NÃO decide nada e NÃO lê contrato:

- `blocks.py` (aqui): grava o registro, lê e lista. Nunca abre
  `feature_list.json`, nunca chama git/subprocess, nunca executa `verify_cmd`.
  A conferência de "este id existe no contrato?" chega pronta em `known_ids`,
  vinda de quem já leu o contrato (a CLI) — mesma divisão de `attempts.py`.
- `supervisor.py` (T-02): para de oferecer a fatia bloqueada.
- `stop_hook.py` (T-03): para de cobrar verificação dela e enuncia o que está
  na mão do humano.
- `panel.py`/`templates.py` (T-04): mostram.
- `verify.py`/CLI (T-05): destravam.
- `finish.py` (T-06): impede o fecho da demanda com bloqueio pendente.

Formato — `.harness/blocks/<contrato>/<feature_id>.json`, um objeto por
feature bloqueada:

    {"feature_id": "T-04", "contract": "meu-contrato",
     "needs": "editar test_glob na linha 27 de .harness/harness.yaml e rodar
               harness compile-session",
     "recorded_at": "2026-08-12T01:00:00+00:00",
     "watch": ".harness/harness.yaml"}

Um arquivo por feature (e não um jsonl append-only como o rastro de
tentativas) porque bloqueio é estado ATUAL, não histórico: a pergunta é
"esta fatia está parada agora?", e a resposta anterior não interessa. Quem
guarda histórico de tentativa é `attempts.py`.

`needs` é a frase que o humano lê no placar, no progresso e no fecho. Ela é
gravada íntegra — só as pontas são aparadas. Truncar ou resumir aqui é jogar
fora exatamente o que faz o bloqueio ser acionável em vez de mais um
"pendente".
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

BLOCKS_DIR = ".harness/blocks"

#: Espelha `attempts.UNSCOPED_ATTEMPTS_DIR` e `verify.UNSCOPED_EVIDENCE_DIR`:
#: subdiretório usado quando o `feature_list.json` não declara `contract`
#: (contrato compilado por versão antiga, ou fixture de teste). Nome inválido
#: como slug de propósito.
UNSCOPED_BLOCKS_DIR = "_sem-contrato"

#: Carimbo de "o arquivo esperado não existia quando o bloqueio foi declarado".
#: Precisa ser um valor, e não `None`, porque criar o arquivo é o caso mais
#: comum de "o arquivo mudou" — com `None` ali, essa espera nunca terminava.
WATCH_ABSENT = "absent"


class BlockError(Exception):
    """Declaração de bloqueio recusada — motivo ausente ou id fora do contrato."""


def block_path(target_dir: Path, contract: Any, feature_id: str) -> Path:
    """`.harness/blocks/<contrato>/<feature_id>.json`.

    Escopado por contrato pelo MESMO motivo de `attempts.attempts_path`: todo
    contrato começa em `T-01`. Um bloqueio não escopado faria o contrato novo
    nascer com uma fatia parada que outro contrato declarou — e o supervisor
    pularia trabalho que ninguém pediu para pular.
    """
    slug = str(contract or "").strip() or UNSCOPED_BLOCKS_DIR
    return Path(target_dir) / BLOCKS_DIR / slug / f"{feature_id}.json"


def record_block(
    target_dir: Path,
    contract: Any,
    feature_id: str,
    *,
    needs: Any,
    recorded_at: str,
    watch: str | None = None,
    known_ids: list[str] | None = None,
) -> Path:
    """Grava o bloqueio da feature. Retorna o caminho do json.

    `needs` é obrigatório e não pode ser branco: o freio contra o bloqueio
    virar fuga de trabalho difícil é o motivo ser acionável e ficar visível em
    toda saída que conta a verdade. Bloqueio sem motivo é o `passes: false`
    mudo que já existia, com nome novo — então não nasce.

    `known_ids`, quando dado, é a lista de ids do contrato ativo: id fora dela
    é recusado. Passar `None` significa "não há lista a conferir" (chamador que
    não leu contrato), não "aceite qualquer coisa em silêncio" — quem chama
    pela CLI sempre passa a lista.

    `recorded_at` vem de fora pelo mesmo motivo de `attempts.record_failure`:
    quem chama já tem um carimbo do evento, e um relógio novo aqui produziria
    dois timestamps divergentes para o mesmo fato.

    Regravar a mesma feature SUBSTITUI o bloqueio anterior — bloqueio é estado
    atual, e dois motivos ao mesmo tempo para a mesma fatia é estado
    contraditório, não histórico.
    """
    reason = str(needs).strip() if needs is not None else ""
    if not reason:
        raise BlockError(
            f"bloqueio de {feature_id} recusado: falta dizer o que você precisa do "
            "humano. Um bloqueio sem motivo é uma tarefa pendente com nome novo — "
            "escreva a ação concreta (arquivo, linha, comando), porque é ela que "
            "aparece no placar, no progresso e no fecho da demanda."
        )

    if known_ids is not None and feature_id not in known_ids:
        conhecidos = ", ".join(known_ids) if known_ids else "(nenhuma)"
        raise BlockError(
            f"bloqueio recusado: {feature_id} não é uma tarefa do contrato ativo. "
            f"Tarefas do contrato: {conhecidos}."
        )

    path = block_path(target_dir, contract, feature_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "feature_id": feature_id,
                "contract": str(contract or "").strip() or None,
                "needs": reason,
                "recorded_at": recorded_at,
                "watch": watch,
                "watch_hash": _watch_hash(target_dir, watch),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _watch_hash(target_dir: Path, watch: str | None) -> str | None:
    """Carimbo do conteúdo do arquivo que o bloqueio está esperando mudar.

    Sem carimbar no momento da declaração não há com o que comparar depois — e
    o bloqueio ou nunca destrava, ou destrava na primeira leitura.

    Arquivo INEXISTENTE tem carimbo próprio (`ABSENT`), não `None`: "o arquivo
    que você precisa criar ainda não existe" é um estado tão comparável quanto
    qualquer conteúdo, e criá-lo é o caso mais comum de "o arquivo mudou". Com
    `None` ali, a espera por um arquivo a criar nunca terminava.

    `None` fica reservado para NÃO SEI (erro de I/O, arquivo travado por um
    editor no meio de um save). Quem lê trata desconhecido como "sem mudança" e
    mantém o bloqueio — um erro transitório de leitura não pode destravar
    trabalho sozinho.
    """
    if not watch:
        return None
    path = Path(target_dir) / watch
    try:
        if not path.is_file():
            return WATCH_ABSENT
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def read_block(target_dir: Path, contract: Any, feature_id: str) -> dict[str, Any] | None:
    """O bloqueio da feature, ou `None` se ela não está parada.

    Degrada graciosamente, como `attempts.read_attempts` e
    `supervisor.dispatch_next`: ausente, ilegível, JSON inválido, JSON que não
    é objeto e objeto sem motivo utilizável devolvem `None` sem levantar. O
    default é NÃO estar bloqueado — um arquivo escrito pela metade não pode
    travar uma fatia que ninguém declarou parada.
    """
    path = block_path(target_dir, contract, feature_id)
    if not path.is_file():
        return None

    try:
        record = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError, ValueError):
        return None

    if not isinstance(record, dict):
        return None
    if not str(record.get("needs") or "").strip():
        return None

    # Segundo dos três caminhos de destrave: o arquivo que a espera declarou
    # mudou de conteúdo. Comparação por hash, e não por mtime, pelo mesmo
    # motivo da evidência: `touch` não é edição, e um `git checkout` que
    # devolve o arquivo ao estado anterior não deve contar como resolvido.
    watch = record.get("watch")
    if watch and record.get("watch_hash") is not None:
        current = _watch_hash(target_dir, str(watch))
        # `None` aqui é NÃO SEI (erro de I/O), não "mudou": tratar desconhecido
        # como mudança faria um arquivo travado por um save de editor destravar
        # trabalho sozinho, em silêncio.
        if current is not None and current != record.get("watch_hash"):
            return None
    return record


def clear_block(target_dir: Path, contract: Any, feature_id: str) -> bool:
    """Apaga o bloqueio da feature. `True` se havia um, `False` se não havia.

    Primeiro e terceiro caminhos de destrave: a pessoa libera (`harness
    unblock`), ou a verificação passa (`verify.run_verify`) — se passou, o que
    travava deixou de travar, e manter o registro seria outra mentira de
    estado, com a fatia sumindo da fila justamente quando ficou pronta.

    NO-OP silencioso quando não há bloqueio: destravar o que não estava travado
    é o resultado que quem chamou queria.
    """
    path = block_path(target_dir, contract, feature_id)
    if not path.is_file():
        return False
    try:
        path.unlink()
    except OSError:
        return False
    return True


def is_blocked(target_dir: Path, contract: Any, feature_id: str) -> bool:
    """`True` se a feature está parada esperando o humano."""
    return read_block(target_dir, contract, feature_id) is not None


def settle_blocks(target_dir: Path, contract: Any) -> list[str]:
    """Apaga do disco os bloqueios que o segundo caminho já resolveu. Devolve
    os ids liquidados, em ordem.

    `read_block` decide a espera na hora da leitura, e essa preguiça é
    barata para quem lê — mas deixa o arquivo no disco. O problema não é o
    arquivo: é que `.harness/progress.md` guarda o texto da espera numa
    coluna ESCRITA, e ele é o que a próxima sessão lê primeiro
    (`session_start`). Sem liquidar, quatro superfícies concordam que a fatia
    voltou a andar e o progresso continua dizendo AGUARDANDO VOCÊ — a mentira
    de estado deste contrato, com o sinal trocado.

    Quem chama é a CLI, antes de despachar um comando: `dispatch_next` e o
    placar continuam SÓ LEITURA, como prometem os seus docstrings.
    """
    settled: list[str] = []
    slug = str(contract or "").strip() or UNSCOPED_BLOCKS_DIR
    directory = Path(target_dir) / BLOCKS_DIR / slug
    if not directory.is_dir():
        return settled

    for path in sorted(directory.glob("*.json")):
        if not _watch_resolved(target_dir, path):
            continue
        try:
            path.unlink()
        except OSError:
            continue
        settled.append(path.stem)
    return settled


def _watch_resolved(target_dir: Path, path: Path) -> bool:
    """True SÓ quando um bloqueio bem formado teve o `watch` resolvido.

    Estreito de propósito: `read_block() is None` também cobre json inválido,
    não-objeto e registro sem motivo — apagar esses seria destruir o artefato
    de perícia justamente no caso em que alguém vai querer olhar o que
    aconteceu. A decisão de leitura não muda (corrompido já não bloqueia,
    `read_block`); o que não fazemos é jogar fora a evidência do defeito.
    """
    try:
        record = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError, ValueError):
        return False
    if not isinstance(record, dict) or not str(record.get("needs") or "").strip():
        return False

    watch = record.get("watch")
    stored = record.get("watch_hash")
    if not watch or stored is None:
        return False
    current = _watch_hash(target_dir, str(watch))
    return current is not None and current != stored


def list_blocks(target_dir: Path, contract: Any) -> list[dict[str, Any]]:
    """Todos os bloqueios do contrato, ordenados por id da feature.

    Ordenado porque `finish` (T-06) e o placar (T-04) nomeiam TODAS as fatias
    paradas, e um relatório que muda de ordem entre execuções é ruído em cima
    de diff. Entrada corrompida é pulada em silêncio, pela mesma razão de
    `read_block`.
    """
    slug = str(contract or "").strip() or UNSCOPED_BLOCKS_DIR
    directory = Path(target_dir) / BLOCKS_DIR / slug
    if not directory.is_dir():
        return []

    blocks: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        block = read_block(target_dir, contract, path.stem)
        if block is not None:
            blocks.append(block)
    return blocks
