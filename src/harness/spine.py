"""Decisões e lições — os dois registros da spine cuja vida é o PROJETO.

§5.2 e §5.3 do design de loop engineering. A spine tem três registros, e o
harness mecanizava só o primeiro:

- `.harness/progress.md` (vida: a demanda) — onde estamos. Nasce de template,
  é reescrito a cada verificação e regenerado a cada demanda nova. Mora em
  `harness.templates`, e é por isso que não mora aqui: o ciclo de vida é outro.
- `.harness/decisions.md` (vida: o projeto) — por que decidimos assim. Sem ele,
  loop longo re-litiga: a iteração 40 "descobre" e tenta a abordagem que a
  iteração 12 descartou por bom motivo, porque o motivo não foi persistido em
  lugar nenhum que ela leia.
- `.harness/lessons.md` (vida: o projeto) — o que atrapalhou. Anotado no momento
  da fricção, uma linha, sem interromper o trabalho.

**Append-only, sem exceção.** É a garantia inteira destes dois arquivos: um
registro de razões que pode ser reescrito não prova que a razão gravada é a
razão original, e essa prova é a única coisa que ele tem a oferecer. Mudou de
ideia? Registra-se outra decisão que supersede a anterior — a anterior fica,
com a data em que foi tomada.

**Quem escreve é o comando, não o agente.** Não por conveniência: o
`boundary_guard` barra escrita em `.harness/**` fora de `work/` e `scratch/`
(plano de controle não se auto-amplia), então ou existe verbo ou estes arquivos
nunca são escritos. O verbo também numera e data sem colisão, que é exatamente o
que se erra escrevendo markdown à mão.

**O agente anota a lição; o humano compila.** O loop NUNCA aplica lição sozinha
— auto-modificação do harness pelo próprio agente é a camada mais perigosa do
design. Por isso aqui não existe nada que feche um `- [ ]`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

DECISIONS_FILE = ".harness/decisions.md"
LESSONS_FILE = ".harness/lessons.md"

DECISIONS_HEADER = (
    "# Decisões do projeto\n"
    "\n"
    "Append-only. Escrito por `harness decide` — não edite entradas antigas;\n"
    "mudou de ideia, registre uma decisão nova que supersede a anterior.\n"
)
LESSONS_HEADER = (
    "# Lições — fricções observadas\n"
    "\n"
    "Append-only. Escrito por `harness lesson`. Quem fecha um item é o HUMANO,\n"
    "revisando em cadência própria — o agente anota, não aplica.\n"
)

#: Quantas decisões vão para o contexto de abertura da sessão. O acervo cresce
#: com o projeto; o contexto, não. Cinco cabe ao lado do aviso de reconciliação
#: e do resumo de progresso sem que os três virem parede de texto.
SESSION_DECISION_LIMIT = 5

_HEADING_RE = re.compile(r"^##\s+(D-\d+)\s+—\s+(.*?)\s+\((\d{4}-\d{2}-\d{2})\)\s*$")


@dataclass(frozen=True)
class Decision:
    id: str
    title: str
    date: str
    decision: str
    why: str


@dataclass(frozen=True)
class Lesson:
    friction: str
    fix: str
    done: bool


def _flatten(text: str) -> str:
    """Uma linha só. Cabeçalho markdown e item de lista não sobrevivem a `\\n`."""
    return " ".join(str(text).split())


def read_decisions(target_dir: Path | str) -> list[Decision]:
    """Decisões registradas, na ordem do arquivo. Arquivo ausente -> lista vazia.

    Vazio, nunca exceção: projeto que ainda não registrou decisão nenhuma é o
    estado inicial de todo projeto, e levantar aqui derrubaria o hook de
    abertura da sessão por causa de um arquivo que não precisa existir.
    """
    path = Path(target_dir) / DECISIONS_FILE
    if not path.is_file():
        return []

    decisions: list[Decision] = []
    current: dict[str, str] | None = None
    body: list[str] = []

    def _flush() -> None:
        if current is None:
            return
        decisions.append(
            Decision(
                id=current["id"],
                title=current["title"],
                date=current["date"],
                decision=current["decision"],
                why="\n".join(body).strip(),
            )
        )

    for line in path.read_text(encoding="utf-8-sig").splitlines():
        match = _HEADING_RE.match(line)
        if match:
            _flush()
            current = {
                "id": match.group(1),
                "title": match.group(2),
                "date": match.group(3),
                "decision": "",
            }
            body = []
            continue
        if current is None:
            continue
        if line.startswith("Decisão:") and not current["decision"]:
            current["decision"] = line[len("Decisão:") :].strip()
        elif line.startswith("Porquê:"):
            body = [line[len("Porquê:") :].strip()]
        elif body:
            body.append(line)
    _flush()
    return decisions


def next_decision_id(target_dir: Path | str) -> str:
    """Próximo id livre, derivado do MAIOR já gravado — não da contagem.

    Uma entrada escrita à mão (num terminal, fora daqui) deixa buraco na
    sequência; contar daria um id já usado, e o id é a única forma de citar uma
    decisão de outro documento.
    """
    highest = 0
    for decision in read_decisions(target_dir):
        try:
            highest = max(highest, int(decision.id.split("-", 1)[1]))
        except (IndexError, ValueError):
            continue
    return f"D-{highest + 1:03d}"


def record_decision(
    target_dir: Path | str,
    title: str,
    *,
    decision: str,
    why: str,
    today: str | None = None,
) -> str:
    """Acrescenta uma decisão ao fim de `.harness/decisions.md`. Devolve o id.

    Modo `append`: o conteúdo anterior não é lido para ser reescrito, só para
    descobrir o próximo id. `why` pode ter várias linhas — razão costuma ter —,
    mas `title` é achatado, porque o cabeçalho é uma linha por definição.
    """
    target_dir = Path(target_dir)
    path = target_dir / DECISIONS_FILE
    decision_id = next_decision_id(target_dir)
    stamp = today or datetime.now(timezone.utc).date().isoformat()

    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        path.write_text(DECISIONS_HEADER, encoding="utf-8")

    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            f"\n## {decision_id} — {_flatten(title)} ({stamp})\n"
            f"Decisão: {_flatten(decision)}\n"
            f"Porquê: {why.strip()}\n"
        )
    return decision_id


def read_lessons(target_dir: Path | str) -> list[Lesson]:
    """Lições do arquivo, em ordem. Só linhas `- [ ]`/`- [x]` contam — prosa
    solta que o humano escreveu ao redor não vira item contável."""
    path = Path(target_dir) / LESSONS_FILE
    if not path.is_file():
        return []

    lessons: list[Lesson] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        if not stripped.startswith("- ["):
            continue
        done = stripped[3:4].lower() == "x"
        text = stripped[stripped.index("]") + 1 :].strip()
        friction, _, fix = text.partition("→")
        if not fix:
            friction, _, fix = text.partition("->")
        lessons.append(Lesson(friction=friction.strip(), fix=fix.strip(), done=done))
    return lessons


def open_lessons(target_dir: Path | str) -> list[Lesson]:
    """As que o humano ainda não fechou. É a lista que o fecho da demanda mostra."""
    return [lesson for lesson in read_lessons(target_dir) if not lesson.done]


def record_lesson(target_dir: Path | str, friction: str, *, fix: str) -> str:
    """Acrescenta `- [ ] <fricção> → <melhoria candidata>`. Devolve a linha escrita.

    Tudo achatado em uma linha: uma lição por linha é o formato, e um item
    multi-linha viraria algo que os leitores seguintes não conseguem contar.
    """
    path = Path(target_dir) / LESSONS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        path.write_text(LESSONS_HEADER, encoding="utf-8")

    line = f"- [ ] {_flatten(friction)} → {_flatten(fix)}"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    return line


def render_decisions_section(
    decisions: list[Decision], *, limit: int = SESSION_DECISION_LIMIT
) -> str | None:
    """Seção para o contexto de abertura, ou `None` se não há decisão nenhuma.

    Só as `limit` mais recentes, e o corte é DITO: uma seção que mostra 5 de 12
    sem avisar faria a sessão acreditar estar vendo o acervo inteiro e concluir
    que uma alternativa nunca foi discutida.

    O `Porquê:` vai junto, não só o título. O modo de falha que este registro
    existe para evitar é re-tentar a alternativa já descartada — e o título
    sozinho diz que a decisão existe, não o que ela proíbe.
    """
    if not decisions:
        return None

    recent = decisions[-limit:]
    lines = [f"## Decisões do projeto ({len(recent)} mais recentes de {len(decisions)})"]
    lines.append("")
    for decision in recent:
        lines.append(f"- **{decision.id} — {decision.title}** ({decision.date})")
        lines.append(f"  - Decisão: {decision.decision}")
        lines.append(f"  - Porquê: {' '.join(decision.why.split())}")
    lines.append("")
    lines.append(
        "Registro append-only em `.harness/decisions.md`. Antes de retomar uma "
        "alternativa que alguma delas descartou, leia o porquê — ele está aí "
        "para não ser re-litigado."
    )
    return "\n".join(lines)


def _main(argv: list[str] | None = None) -> int:
    """`python -m harness.spine --dir <alvo>` — seção de decisões, já renderizada.

    Existe para o hook `SessionStart`: o script gerado roda com `-S` e não
    importa `harness`, então ele delega para um interpretador novo e recebe o
    texto pronto no campo `section`. Formatar lá dentro poria a formatação fora
    do alcance da suíte, onde divergiria na primeira mudança.

    Sempre exit 0: não há veredito aqui, só leitura. Ausência de decisões devolve
    `section: null`, que o hook trata como "nada a anexar".
    """
    import argparse
    import json

    parser = argparse.ArgumentParser(prog="harness.spine")
    parser.add_argument("--dir", default=".")
    parser.add_argument("--limit", type=int, default=SESSION_DECISION_LIMIT)
    args = parser.parse_args(argv)

    decisions = read_decisions(Path(args.dir))
    print(json.dumps({
        "decisions": len(decisions),
        "section": render_decisions_section(decisions, limit=args.limit),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover - entrada de processo
    raise SystemExit(_main())
