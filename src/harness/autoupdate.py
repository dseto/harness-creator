"""Atualização transparente dos artefatos compilados — `harness.autoupdate`.

**O problema.** O plugin chega ao usuário por 3 camadas independentes, cada
uma com seu ciclo de atualização (o inventário está no docstring de
`harness.doctor`). Atualizar só o pacote pip deixa o `.harness/` compilado
do projeto preso na versão antiga: nada falha, nada avisa, e o Claude Code
segue rodando os hooks e o `settings.local.json` da versão anterior. Até
aqui a única saída era o usuário lembrar de rodar `harness compile` em cada
projeto, um por um.

Este módulo automatiza EXCLUSIVAMENTE a camada 2 (artefatos do projeto) a
partir da camada 1 (pacote pip instalado). As camadas 1 e 3 (cache de
plugin do Claude Code) continuam manuais e continuam reportadas pelo
`doctor` — nenhuma delas pode se auto-atualizar de dentro do processo
(exigem rede e, no caso do cache, reinício da sessão).

**Por que a comparação é por tupla e não por `!=`.** O `doctor` compara com
`!=` porque só reporta; para ele, divergir é divergir. Uma ação automática
precisa da ordem: `compilado < instalado` recompila, `compilado >
instalado` apenas avisa. O segundo caso é real — máquina B com pip antigo
abrindo um repositório cujo `.harness/` foi compilado na máquina A —, e
tratá-lo como "divergente" faria o auto-update REGREDIR os artefatos a cada
sessão, brigando com a outra máquina.

Este arquivo tem duas metades, deliberadamente separadas:

O módulo tem duas metades, deliberadamente separadas:

- **decisão** (`parse_version`, `plan_update`): pura, sem efeito colateral,
  sem subprocess. É ela que roda no caminho feliz, e custa uma leitura de
  JSON mais uma comparação de tuplas.
- **execução** (`sync_if_outdated`): dispara a recompilação. Fail-open por
  contrato — qualquer falha vira aviso em stderr, nunca exceção propagada
  para o comando que a chamou. Auto-update jamais pode transformar um
  comando que funcionava em erro; o custo de ficar uma versão atrás é
  pequeno, o de quebrar o comando do usuário não é.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from harness import __version__ as _INSTALLED_VERSION
from harness.compiler import HARNESS_YAML, STATE_FILE
from harness.killswitch import is_disabled
from harness.session_permissions import FEATURE_LIST_FILE

#: Vereditos possíveis da comparação entre o `.harness/` compilado e o pacote
#: instalado. Só `OUTDATED` autoriza escrita.
UP_TO_DATE = "up_to_date"
OUTDATED = "outdated"
AHEAD = "ahead"
UNKNOWN = "unknown"

#: Variável de ambiente de opt-out. Machine-local por natureza — mesma
#: natureza do output compilado, que também não viaja no clone —, por isso
#: NÃO é uma chave de `.harness/harness.yaml`, que é config versionada e
#: valeria para todo mundo que clona o repositório.
OPT_OUT_ENV = "HARNESS_AUTO_UPDATE"

#: Valores que desligam o auto-update. Comparação em caixa baixa.
_OPT_OUT_VALUES = frozenset({"0", "false", "no", "off"})

#: Marca no ambiente do subprocess de recompilação. O subprocess é uma
#: invocação da própria CLI, que roda o mesmo gatilho — a isenção por nome de
#: subcomando mora no chamador, e esta marca fecha o caso de dentro, para
#: qualquer chamador futuro.
RECURSION_ENV = "HARNESS_AUTO_UPDATE_RUNNING"

#: Teto de CADA passo. `compile` e `compile-session` escrevem ~10 artefatos
#: entre os dois; é questão de segundos. O teto existe para o caso patológico
#: (disco travado, interpretador pendurado) não segurar o início da sessão do
#: Claude Code — e por isso é deliberadamente menor que o timeout do hook que
#: chama este módulo (`session_start._auto_update`): matar o processo no nível
#: de fora, no meio de uma escrita de settings, seria pior que esperar.
RECOMPILE_TIMEOUT_SECONDS = 60

#: `X`, `X.Y` ou `X.Y.Z`, só dígitos. Sufixo de pré-release/dev
#: (`0.30.0rc1`, `0.30.0.dev1`) é deliberadamente ILEGÍVEL: numa instalação
#: de desenvolvimento não dá para afirmar a ordem em relação ao release, e o
#: fail-safe é não agir.
_VERSION_RE = re.compile(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?$")


def parse_version(raw: object) -> tuple[int, int, int] | None:
    """Versão `X[.Y[.Z]]` como tupla de 3 inteiros, ou `None` se ilegível.

    Completar com zero à direita é o que faz `"0.30"` e `"0.30.0"` serem a
    mesma versão. `None` para qualquer outra coisa — inclusive não-string —
    e quem chama trata `None` como "não sei, não age"."""
    if not isinstance(raw, str):
        return None
    match = _VERSION_RE.match(raw.strip())
    if match is None:
        return None
    return tuple(int(part) if part else 0 for part in match.groups())  # type: ignore[return-value]


@dataclass(frozen=True)
class UpdatePlan:
    """Veredito + o que regravar. Só descreve; não executa."""

    verdict: str
    compiled_version: str | None
    installed_version: str
    steps: tuple[str, ...]

    @property
    def should_recompile(self) -> bool:
        """Duas condições, ambas necessárias: estar atrás E ter o que
        regravar. Um diretório qualquer com um `compiled-state.json` órfão,
        sem `harness.yaml` nem `feature_list.json`, não é projeto governado
        — não há artefato a produzir, e escrever ali seria intrusão."""
        return self.verdict == OUTDATED and bool(self.steps)

    @property
    def summary(self) -> str:
        return f"{self.compiled_version} -> {self.installed_version}"


def _read_compiled_version(target_dir: Path) -> str | None:
    """`plugin_version` do estado compilado, ou `None`. Degradação graciosa
    idêntica à do `doctor`: arquivo ausente, JSON quebrado ou raiz que não é
    objeto devolvem `None` em vez de levantar."""
    path = target_dir / STATE_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    version = data.get("plugin_version")
    return version if isinstance(version, str) else None


def _steps_for(target_dir: Path) -> tuple[str, ...]:
    """Comandos a rodar, derivados do que o projeto de fato tem.

    `compile` antes de `compile-session`: é a ordem documentada em todas as
    mensagens de correção do `doctor`, e `compile-session` sobrescreve o
    `boundary_guard.py` que `compile` acabou de instalar com a versão
    enriquecida pela superfície do contrato. Inverter deixaria o guard sem o
    contrato."""
    steps: list[str] = []
    if (target_dir / HARNESS_YAML).is_file():
        steps.append("compile")
    if (target_dir / FEATURE_LIST_FILE).is_file():
        steps.append("compile-session")
    return tuple(steps)


def plan_update(target_dir: Path, installed_version: str = _INSTALLED_VERSION) -> UpdatePlan:
    """Compara o `.harness/` compilado com o pacote instalado. Sem efeito
    colateral: só lê."""
    compiled_version = _read_compiled_version(target_dir)
    compiled = parse_version(compiled_version)
    installed = parse_version(installed_version)

    if compiled is None or installed is None:
        verdict = UNKNOWN
    elif compiled < installed:
        verdict = OUTDATED
    elif compiled > installed:
        verdict = AHEAD
    else:
        verdict = UP_TO_DATE

    steps = _steps_for(target_dir) if verdict == OUTDATED else ()
    return UpdatePlan(
        verdict=verdict,
        compiled_version=compiled_version,
        installed_version=installed_version,
        steps=steps,
    )


# ---------------------------------------------------------------------------
# execução
# ---------------------------------------------------------------------------

#: Assinatura do executor de um passo: recebe o argv completo e devolve o
#: exit code. Existe como parâmetro para os testes não pagarem um subprocess
#: real por caso — e para o gatilho do hook poder trocar a estratégia sem
#: reescrever a lógica de decisão.
Runner = Callable[[list[str]], int]


@dataclass(frozen=True)
class UpdateResult:
    plan: UpdatePlan
    ran: tuple[str, ...]
    skipped_reason: str | None

    @property
    def recompiled(self) -> bool:
        return bool(self.ran) and self.ran == self.plan.steps


def _warn(message: str) -> None:
    """Toda saída deste módulo vai para stderr. O stdout dos comandos do
    harness é JSON que outros processos parseiam (a própria suíte e2e entre
    eles); uma linha solta ali quebraria o parse do chamador."""
    print(message, file=sys.stderr)


def _opted_out(env: Mapping[str, str]) -> bool:
    return env.get(OPT_OUT_ENV, "").strip().lower() in _OPT_OUT_VALUES


def _argv_for(step: str, target_dir: Path) -> list[str]:
    """`compile-session` leva `--no-branch` SEMPRE: recompilação automática
    não pode criar nem trocar a branch de contrato (T-02). Sem isso, quem
    está em `main` seria movido para `contract/<slug>` por abrir uma sessão."""
    argv = [sys.executable, "-m", "harness.cli", step, "--dir", str(target_dir)]
    if step == "compile-session":
        argv.append("--no-branch")
    return argv


def _default_runner(argv: list[str]) -> int:
    """Roda um passo num interpretador NOVO, sem `-S`/`-E`.

    Detalhe que não é opcional: quando o chamador é o hook `SessionStart`,
    o processo atual foi lançado com `-S -E` (ver `hook_launcher.hook_command`)
    e portanto NÃO enxerga `site-packages`. Herdar essas flags aqui faria o
    `import harness` do subprocess falhar — o auto-update nunca rodaria pelo
    gatilho de sessão, silenciosamente."""
    env = dict(os.environ)
    env[RECURSION_ENV] = "1"
    completed = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=RECOMPILE_TIMEOUT_SECONDS,
        env=env,
    )
    return completed.returncode


def sync_if_outdated(
    target_dir: Path,
    installed_version: str = _INSTALLED_VERSION,
    runner: Runner | None = None,
    env: Mapping[str, str] | None = None,
) -> UpdateResult:
    """Recompila os artefatos do projeto se eles estiverem atrás do pacote
    instalado. Nunca levanta: toda falha vira aviso em stderr."""
    env = os.environ if env is None else env
    try:
        plan = plan_update(target_dir, installed_version=installed_version)
    except Exception as exc:
        # A inspeção é só leitura de JSON e `is_file()`, mas ela roda antes de
        # TODO comando do harness: se algum dia levantar (path inválido para o
        # SO, disco em erro), quem quebra é o comando do usuário, não o
        # auto-update. Este `except` é o que torna a promessa do docstring
        # ("nunca levanta") verdadeira, e não só uma intenção.
        _warn(f"aviso: não foi possível inspecionar a versão do .harness/ ({type(exc).__name__}: {exc})")
        return UpdateResult(
            UpdatePlan(UNKNOWN, None, installed_version, ()), (), "falha ao inspecionar"
        )

    if _opted_out(env):
        return UpdateResult(plan, (), f"desligado por {OPT_OUT_ENV}")
    if env.get(RECURSION_ENV):
        return UpdateResult(plan, (), "já rodando dentro de uma recompilação (recursão)")
    if is_disabled(target_dir):
        return UpdateResult(plan, (), "harness desativado (kill-switch)")

    if plan.verdict == AHEAD:
        _warn(
            f"aviso: o .harness/ deste projeto foi compilado com a versão "
            f"{plan.compiled_version}, à frente do pacote instalado "
            f"({plan.installed_version}) — nada foi alterado. Atualize o pacote "
            f"(`pip install --upgrade harness-creator`) para alinhar."
        )
        return UpdateResult(plan, (), "artefatos à frente do pacote instalado")
    if not plan.should_recompile:
        return UpdateResult(plan, (), f"nada a fazer (veredito: {plan.verdict}, em dia)")

    run = runner or _default_runner
    ran: list[str] = []
    for step in plan.steps:
        try:
            exit_code = run(_argv_for(step, target_dir))
        except Exception as exc:  # fail-open: inclui timeout, OSError e o inesperado
            _warn(
                f"aviso: a atualização automática do harness falhou ao rodar "
                f"`{step}` ({type(exc).__name__}: {exc}) — o projeto segue na "
                f"versão {plan.compiled_version}. Rode `harness doctor` para o "
                f"diagnóstico completo."
            )
            return UpdateResult(plan, tuple(ran), "falha ao recompilar")
        if exit_code != 0:
            # Parar no primeiro erro: `compile-session` depende do que
            # `compile` grava, e encadear em cima de um passo que falhou só
            # produz um segundo erro menos legível que o primeiro.
            _warn(
                f"aviso: a atualização automática do harness falhou em `{step}` "
                f"(exit {exit_code}) — o projeto segue na versão "
                f"{plan.compiled_version}. Rode `harness {step}` na mão para ver "
                f"o erro completo."
            )
            return UpdateResult(plan, tuple(ran), "falha ao recompilar")
        ran.append(step)

    _warn(f"harness: artefatos recompilados {plan.summary}")
    return UpdateResult(plan, tuple(ran), None)


# ---------------------------------------------------------------------------
# entrypoint `python -m harness.autoupdate`
# ---------------------------------------------------------------------------
#
# Existe para o hook `SessionStart`, que é stdlib-only por design e não pode
# importar `harness` (roda com `-S`, sem `site-packages` — ver
# `hook_launcher.hook_command`). Sem este entrypoint, a alternativa seria
# duplicar a lógica de decisão dentro do script gerado, onde ela ficaria
# invisível para a suíte e divergiria na primeira mudança.
#
# O stdout é JSON de UMA linha para o hook parsear; os avisos legíveis
# continuam em stderr.

def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m harness.autoupdate",
        description="Recompila os artefatos do projeto se estiverem atrás do pacote instalado",
    )
    parser.add_argument("--dir", default=".", help="Raiz do projeto-alvo")
    args = parser.parse_args(argv)

    result = sync_if_outdated(Path(args.dir))
    print(json.dumps({
        "recompiled": result.recompiled,
        "verdict": result.plan.verdict,
        "compiled_version": result.plan.compiled_version,
        "installed_version": result.plan.installed_version,
        "ran": list(result.ran),
        "skipped_reason": result.skipped_reason,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
