"""Parsing da saída de runners de teste: quantos testes pularam, por quê
quando o motivo aparece na saída, e se nenhum teste chegou a ser coletado.

Origem: `harness verify` decidia o verde só pelo exit code
(`verify.py:596`) — pytest/dotnet test/jest saem 0 mesmo com dezenas de
testes pulados, e nada olhava o que o runner de fato imprimiu. Este módulo é
só a leitura de texto: nunca executa processo, nunca decide o que fazer com
o resultado (isso é `verify.py`, que chama `parse_skips` com o stdout/stderr
que já tem em mão).

Multi-runner por padrão de TEXTO, nunca presumindo pytest — o harness roda
sobre projetos em várias linguagens (há dogfood .NET). Cada runner formata a
saída de skip de um jeito, e nem todos imprimem motivo por padrão:

- pytest: contagem sempre sai no resumo (`N skipped`); o MOTIVO só aparece
  com `-rs`/`-ra` (linha `SKIPPED [1] arquivo:linha: motivo`). Sem essas
  flags, a contagem existe e o motivo não — `reasons_visible=False` é esse
  caso, não um erro de parsing.
- dotnet test: só contagem (`Skipped: N` no resumo moderno, `Skipped: N.`
  no formato legado `Total tests: N. ...`). O runner não expõe motivo de
  skip na saída padrão.
- jest: só contagem (`Tests: N skipped, ...`). Mesma limitação.
- go test: cada skip vira uma linha própria (`--- SKIP: TestFoo`), com a
  razão às vezes na linha seguinte de log — não capturada aqui por não ter
  formato fixo entre projetos; fica de fora até haver caso real.

"Zero coletados" é o mesmo tipo de cegueira (exit 0 sobre nada executado) e
por isso mora no mesmo relatório, não em módulo separado. Para pytest o caso
já sai vermelho hoje (exit 5, "no tests ran") — a lacuna real está em
`dotnet test` ("Total tests: 0") e jest ("No tests found").
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class SkippedTest:
    """Um teste pulado. `nodeid`/`reason` ficam `None` quando o runner não
    expôs essa informação na saída (ver `reasons_visible` do relatório)."""

    nodeid: str | None
    reason: str | None


@dataclass(frozen=True)
class SkipReport:
    """Resultado da leitura de uma saída de runner.

    `skipped` só é preenchida quando o runner nomeia CADA skip
    individualmente (pytest com `-rs`/`-ra`, go test); runners que só
    imprimem contagem agregada (dotnet test, jest, pytest sem `-rs`) deixam
    a lista vazia — inventar `skipped_count` entradas sem nodeid/reason não
    acrescentaria informação real, só um preenchimento artificial.
    """

    skipped_count: int
    skipped: list[SkippedTest] = field(default_factory=list)
    zero_collected: bool = False
    reasons_visible: bool = True


_PYTEST_NO_TESTS = re.compile(r"\bno tests ran\b", re.IGNORECASE)
_PYTEST_SUMMARY_COUNT = re.compile(r"(\d+)\s+skipped\b")
_PYTEST_SKIPPED_LINE = re.compile(
    r"^SKIPPED\s+\[\d+\]\s+(?P<nodeid>\S+):\s*(?P<reason>.*)$", re.MULTILINE
)

_DOTNET_ZERO_TOTAL = re.compile(r"\bTotal tests:\s*0\b")
_DOTNET_SKIPPED_MODERN = re.compile(r"\bSkipped:\s*(\d+)\s*,")
_DOTNET_SKIPPED_LEGACY = re.compile(r"\bSkipped:\s*(\d+)\.")

_JEST_NO_TESTS = re.compile(r"\bNo tests found\b", re.IGNORECASE)
_JEST_SUMMARY_COUNT = re.compile(r"\bTests:.*?(\d+)\s+skipped\b")

_GO_NO_TEST_FILES = re.compile(r"\[no test files\]")
_GO_SKIP_LINE = re.compile(r"^---\s*SKIP:\s*(?P<nodeid>\S+)", re.MULTILINE)


def parse_skips(stdout: str, stderr: str) -> SkipReport:
    """Lê a saída combinada de um `verify_cmd` e devolve o que pulou.

    Testa os padrões de cada runner na saída inteira (stdout+stderr) em vez
    de exigir detecção prévia de qual runner rodou — mais simples e
    suficiente: os formatos não colidem entre si na prática, e um
    `verify_cmd` roda um único runner por vez.
    """
    text = f"{stdout or ''}\n{stderr or ''}"

    if _PYTEST_NO_TESTS.search(text) or _JEST_NO_TESTS.search(text) or _GO_NO_TEST_FILES.search(text):
        return SkipReport(skipped_count=0, skipped=[], zero_collected=True, reasons_visible=True)

    if _DOTNET_ZERO_TOTAL.search(text):
        return SkipReport(skipped_count=0, skipped=[], zero_collected=True, reasons_visible=True)

    skipped_lines = [
        SkippedTest(nodeid=m.group("nodeid"), reason=m.group("reason").strip())
        for m in _PYTEST_SKIPPED_LINE.finditer(text)
    ]
    if skipped_lines:
        return SkipReport(
            skipped_count=len(skipped_lines), skipped=skipped_lines, zero_collected=False, reasons_visible=True
        )

    go_lines = [SkippedTest(nodeid=m.group("nodeid"), reason=None) for m in _GO_SKIP_LINE.finditer(text)]
    if go_lines:
        return SkipReport(
            skipped_count=len(go_lines), skipped=go_lines, zero_collected=False, reasons_visible=False
        )

    for pattern in (_PYTEST_SUMMARY_COUNT, _DOTNET_SKIPPED_MODERN, _DOTNET_SKIPPED_LEGACY, _JEST_SUMMARY_COUNT):
        match = pattern.search(text)
        if match:
            return SkipReport(
                skipped_count=int(match.group(1)), skipped=[], zero_collected=False, reasons_visible=False
            )

    return SkipReport(skipped_count=0, skipped=[], zero_collected=False, reasons_visible=True)


#: Teto de caracteres do resumo formatado — mesmo motivo de
#: `attempts._FAILURE_LINE_MAX`: o anti-objetivo de `verify.py:298-301` é
#: explícito contra despejar a saída inteira da suíte no contexto do agente
#: a cada verify verde. Um resumo, não um relatório.
_SUMMARY_MAX_CHARS = 500


def format_skip_summary(report: SkipReport, *, max_chars: int = _SUMMARY_MAX_CHARS) -> str | None:
    """Texto pronto para console/evidência, ou `None` quando não há nada a
    dizer (sem skip, sem zero_collected). Chamado em TODA execução de
    `harness verify`, verde ou vermelho — nunca atrás de flag."""
    if report.zero_collected:
        return (
            "ATENCAO: nenhum teste foi coletado — o verify_cmd saiu sem "
            "executar nada (ver saída do runner)"
        )
    if report.skipped_count == 0:
        return None
    if not report.reasons_visible:
        return (
            f"{report.skipped_count} teste(s) pulado(s) — motivo não aparece na "
            "saída atual do verify_cmd; acrescente `-rs` (pytest) ou a flag "
            "equivalente do runner ao verify_cmd do contrato para revelar os motivos"
        )
    body = "; ".join(f"{s.nodeid}: {s.reason}" for s in report.skipped)
    if len(body) > max_chars:
        body = body[: max_chars - 1] + "…"
    return f"{report.skipped_count} teste(s) pulado(s): {body}"


# --- Baseline (T-03) ---------------------------------------------------
#
# O conjunto de skips CONHECIDOS de uma feature, escrito só por ação humana
# deliberada (`harness skips baseline`), nunca por `harness verify`. Decisão
# registrada no spec: nada no fluxo roda a suíte antes da aprovação do
# contrato (D-007 proíbe isso no health check), e deixar o primeiro verify
# virar baseline carimbaria como conhecido justamente o skip que apareceu no
# meio do processo — o dano original, com um passo a mais.

BASELINE_DIR = ".harness/skips-baseline"

#: Mesmo nome de diretório-fallback de `attempts.UNSCOPED_ATTEMPTS_DIR` — um
#: `feature_list.json` sem `contract` declarado (versão antiga, ou fixture)
#: não pode gravar num caminho que colidiria entre contratos diferentes.
_UNSCOPED_BASELINE_DIR = "_sem-contrato"


class BaselineError(Exception):
    """Falha ao descobrir o baseline: feature/contrato ausente, verify_cmd no
    runtime floor, ou skips sem identidade visível (sem `-rs`/equivalente)."""


def baseline_path(target_dir: Path, contract: str, feature_id: str) -> Path:
    slug = str(contract or "").strip() or _UNSCOPED_BASELINE_DIR
    return Path(target_dir) / BASELINE_DIR / slug / f"{feature_id}.json"


def read_baseline(target_dir: Path, contract: str, feature_id: str) -> list[SkippedTest]:
    """O conjunto conhecido, ou `[]` se nunca baselinado/arquivo ilegível —
    nunca levanta: um baseline ausente é o estado normal de uma feature nova,
    não um erro."""
    path = baseline_path(target_dir, contract, feature_id)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [
        SkippedTest(nodeid=item.get("nodeid"), reason=item.get("reason"))
        for item in data
        if isinstance(item, dict)
    ]


def write_baseline(
    target_dir: Path, contract: str, feature_id: str, skipped: list[SkippedTest]
) -> Path:
    path = baseline_path(target_dir, contract, feature_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [{"nodeid": s.nodeid, "reason": s.reason} for s in skipped]
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def run_baseline(
    target_dir: Path, feature_id: str, *, timeout_seconds: int = 600
) -> tuple[SkipReport, Path]:
    """Roda o `verify_cmd` da feature UMA vez, fora do caminho de `harness
    verify` — sem gravar evidência nem tentativa, só para descobrir e
    registrar o que pulou. Import de `harness.verify` é local para não criar
    dependência circular no topo do módulo (verify.py importa `skips.py`
    desde T-02).

    Skip sem motivo/local visível na saída (`reasons_visible=False`) não vira
    baseline: sem identidade por skip, T-04 não teria como distinguir "já
    conhecido" de "novo". Em vez de inventar identidade, a função recusa e
    aponta o mesmo ajuste que o console de `harness verify` já sugere —
    acrescentar `-rs`/equivalente ao `verify_cmd` do contrato — nunca altera
    o comando sozinha (decisão registrada nº 3 do spec).
    """
    from harness.verify import VerifyError, _load_feature, _run_verify_cmd, normalize_command_head

    target_dir = Path(target_dir).resolve()
    try:
        feature, contract = _load_feature(target_dir, feature_id)
    except VerifyError as exc:
        raise BaselineError(str(exc)) from exc

    verify_cmd = feature["verify_cmd"]

    from harness.boundary_guard import is_floor_bash_command

    if is_floor_bash_command(verify_cmd):
        raise BaselineError(
            f"feature '{feature_id}': verify_cmd '{verify_cmd}' bate no runtime "
            "floor (push/rede/publicacao) — nunca executado, nem para baseline"
        )

    verify_cwd = target_dir
    feature_cwd = feature.get("cwd")
    if feature_cwd:
        verify_cwd = target_dir / feature_cwd
        if not verify_cwd.is_dir():
            raise BaselineError(f"feature '{feature_id}': cwd '{feature_cwd}' não existe em {target_dir}")

    exec_cmd = normalize_command_head(verify_cmd)
    _returncode, stdout, stderr = _run_verify_cmd(exec_cmd, verify_cwd, timeout_seconds, False)

    report = parse_skips(stdout, stderr)
    if report.skipped_count and not report.reasons_visible:
        raise BaselineError(
            f"feature '{feature_id}': {report.skipped_count} teste(s) pulado(s), mas o "
            "verify_cmd não expõe motivo/local — baseline exige identidade por "
            "skip; acrescente `-rs` (pytest) ou a flag equivalente do runner ao "
            "verify_cmd do contrato e rode `harness skips baseline` de novo"
        )

    path = write_baseline(target_dir, contract, feature_id, report.skipped)
    return report, path


# --- Delta (T-04) --------------------------------------------------------
#
# Skip presente na execução e ausente do baseline derruba o verify; skip já
# conhecido passa mudo; skip que sumiu do baseline só informa. Identidade =
# par `(nodeid, reason)` — decisão registrada no spec: só `nodeid` faz
# renomear um teste virar bloqueio sem regressão nenhuma; só `reason` faz
# dois testes distintos com a mesma frase colapsarem num item, e aí um skip
# novo passaria mudo (o dano original). Motivo diferente no MESMO local
# também conta como skip novo — condição mudou.


def skip_delta_violation(report: SkipReport, known: list[SkippedTest]) -> str | None:
    """`None` quando nada bloqueia; senão a mensagem de bloqueio (motivo da
    falha, não uma exceção — quem chama decide o que fazer com o veredito).

    Motivo invisível (`reasons_visible=False`) com pelo menos um skip
    bloqueia SEMPRE, mesmo sem conseguir comparar contra o baseline: a
    assimetria é intencional (spec, "falso positivo custa uma linha de
    aprovação; falso negativo é o dano que originou esta demanda") — sem
    identidade não há como provar que os skips atuais são os já conhecidos.
    """
    if report.skipped_count == 0:
        return None

    if not report.reasons_visible:
        return (
            f"{report.skipped_count} teste(s) pulado(s) sem motivo/local visível na "
            "saída — o delta contra o baseline não pode ser calculado com segurança; "
            "acrescente `-rs` (pytest) ou a flag equivalente do runner ao verify_cmd "
            "do contrato e rode `harness skips baseline` para estabelecer o conjunto "
            "conhecido"
        )

    known_pairs = {(s.nodeid, s.reason) for s in known}
    new = [s for s in report.skipped if (s.nodeid, s.reason) not in known_pairs]
    if not new:
        return None

    body = "; ".join(f"{s.nodeid}: {s.reason}" for s in new)
    return (
        f"{len(new)} teste(s) pulado(s) NOVO(S), fora do baseline conhecido: {body} — "
        "revise; se são esperados, rode `harness skips baseline <feature_id>` para "
        "aprovar; se não, corrija o que causou o pulo"
    )


# --- Skip acionável + liberação (T-05) -----------------------------------
#
# Skip cujo motivo indica falta de algo do lado de fora do código — variável
# de ambiente, credencial, ferramenta não instalada — bloqueia `harness
# verify` já na PRIMEIRA execução, sem esperar delta (T-04): não é código
# errado, é ambiente incompleto, e §8.3 do design classifica isso como
# INFRAESTRUTURA, não teste vermelho (mesma família de `governance_stale`).
# A assimetria é intencional (spec): falso positivo (skip de plataforma
# classificado como acionável) custa uma linha em `.harness/harness.yaml`;
# falso negativo é o dano que originou esta demanda.

_ACTIONABLE_PATTERN = re.compile(
    r"\benv\b|\benvironment variable\b|\bnot set\b|n[ãa]o\s+definid[ao]|"
    r"\bnot installed\b|\bnot found\b|n[ãa]o\s+encontrad[ao]|\bcredential\b|"
    r"\bmissing\b|path\s+ausente",
    re.IGNORECASE,
)


def is_actionable_skip_reason(reason: str | None) -> bool:
    """True quando o texto do `reason` indica que falta AÇÃO DO USUÁRIO, não
    código quebrado. Falso positivo (skip de plataforma cujo texto casa por
    acidente) é aceitável — vira uma linha de liberação; falso negativo
    deixaria passar despercebido o exato dano que originou esta demanda."""
    return bool(_ACTIONABLE_PATTERN.search(reason or ""))


def _is_liberated(reason: str | None, allowed: list[str]) -> bool:
    text = reason or ""
    return any(substr in text for substr in allowed if substr)


def load_allowed_skips(target_dir: Path) -> list[str]:
    """Lê `verification.allowed_skips` de `<target_dir>/.harness/harness.yaml`.

    Mesma degradação graciosa de `branching.load_branch_per_contract`:
    arquivo ausente, YAML inválido, ou schema divergente -> lista vazia (nada
    liberado) — nunca levanta. Import local de `yaml`/`pydantic`/`HarnessConfig`
    pelo mesmo motivo do import local em `run_baseline`: evita ciclo e mantém
    o custo de import fora do caminho comum de quem só quer `parse_skips`.
    """
    import yaml
    from pydantic import ValidationError

    from harness.config import HarnessConfig

    yaml_path = Path(target_dir) / ".harness" / "harness.yaml"
    if not yaml_path.is_file():
        return []
    try:
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return []
    if not isinstance(raw, dict):
        return []
    try:
        config = HarnessConfig.model_validate(raw)
    except ValidationError:
        return []
    return list(config.verification.allowed_skips)


def actionable_skip_violation(report: SkipReport, allowed: list[str]) -> str | None:
    """`None` quando nada bloqueia; senão a mensagem INFRA nomeando o que
    falta. Só considera skips com motivo VISÍVEL — sem `-rs`/equivalente o
    classificador não tem texto para julgar, e T-02/T-04 já cobrem esse caso
    pedindo a mesma flag."""
    if not report.reasons_visible:
        return None

    unliberated = [
        s for s in report.skipped
        if is_actionable_skip_reason(s.reason) and not _is_liberated(s.reason, allowed)
    ]
    if not unliberated:
        return None

    body = "; ".join(f"{s.nodeid}: {s.reason}" for s in unliberated)
    return (
        f"{len(unliberated)} teste(s) pulado(s) por falta de algo do lado de fora "
        f"do código (variável de ambiente, credencial, ferramenta): {body} — "
        "resolva o que falta, ou se é esperado neste ambiente, libere no "
        "`.harness/harness.yaml` (`verification.allowed_skips`, um trecho do "
        "motivo por linha) e rode `harness verify` de novo"
    )


def without_liberated_actionable_skips(report: SkipReport, allowed: list[str]) -> SkipReport:
    """Mesmo relatório, sem os skips acionáveis já liberados — para o delta
    (T-04): liberação em `harness.yaml` destrava de vez, sem precisar também
    entrar no baseline por feature."""
    if not report.reasons_visible:
        return report
    remaining = [
        s for s in report.skipped
        if not (is_actionable_skip_reason(s.reason) and _is_liberated(s.reason, allowed))
    ]
    if len(remaining) == len(report.skipped):
        return report
    return SkipReport(
        skipped_count=len(remaining),
        skipped=remaining,
        zero_collected=report.zero_collected,
        reasons_visible=report.reasons_visible,
    )
