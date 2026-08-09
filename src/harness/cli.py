"""CLI: `harness run|compile|audit`.

`compile`/`audit` são o modo plugin (governança nativa do Claude Code) e não
dependem de Docker/Anthropic — imports do orquestrador são lazy de propósito.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

#: Erro de USO (não de execução) — mesmo código que o argparse já usa quando o
#: comando não existe ou falta argumento. Distinto de `1`, que os subcomandos
#: reservam para "rodou e o resultado é ruim" (audit com critical, doctor com
#: issue): um `--dir` errado não é um achado sobre o projeto.
USAGE_ERROR_EXIT = 2

#: Teto de linhas por stream (stdout/stderr) impresso quando um `verify_cmd`
#: falha — uma suíte verbosa (centenas/milhares de linhas) não deve entrar
#: inteira no contexto do agente; o FIM é o que importa (onde a asserção
#: quebrou), não o começo.
_MAX_FAILURE_OUTPUT_LINES = 40


def _truncate_output(text: str, max_lines: int = _MAX_FAILURE_OUTPUT_LINES) -> str:
    """Mantém só as últimas `max_lines` linhas de `text`, com aviso explícito
    de quantas foram omitidas — nunca um corte silencioso."""
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    omitted = len(lines) - max_lines
    kept = "\n".join(lines[-max_lines:])
    return f"... ({omitted} linhas omitidas, mostrando as últimas {max_lines}) ...\n{kept}"


def _validated_target_dir(raw: str) -> Path:
    """`--dir` só pode apontar para um diretório que JÁ existe.

    Sem esta guarda, `harness analyze --dir <path errado>` criava a árvore
    inteira e gravava um `repo-profile.json` vazio com exit 0 — um erro de
    digitação materializava um projeto fantasma, e no caso real observado
    (path mutilado pelo shell) a escrita caiu DENTRO da raiz do repo-alvo,
    exatamente o que o produto promete nunca fazer. `harness audit` tinha a
    variante silenciosa: devolvia score 60 e "rode `/harness-creator:init`"
    sobre um caminho inexistente — um laudo plausível sobre nada.

    A validação vive aqui, no CLI, e não em cada função de biblioteca: elas
    recebem `Path` de quem já resolveu o alvo, e `mkdir(parents=True)` é
    legítimo dentro de um projeto que existe (é assim que `.harness/` nasce).
    O que não pode existir é o comando ESCOLHER a raiz.
    """
    path = Path(raw)
    if not path.is_dir():
        print(
            f"erro: --dir aponta para um caminho que não existe (ou não é "
            f"diretório): {path}\n"
            "       nenhum arquivo foi escrito. Confira o caminho — em Git Bash, "
            "prefira aspas simples para path do Windows ('C:\\Projetos\\alvo').",
            file=sys.stderr,
        )
        raise SystemExit(USAGE_ERROR_EXIT)
    return path


def _audit_exit_code(report: Any) -> int:
    """Exit code dos três comandos de auditoria (`audit`, `audit-runtime`,
    `audit-team`).

    Era `0 if score >= 60 else 1`, e isso contradizia a própria
    `skills/audit/SKILL.md` ("Exit code 1 = estrutura comprometida (algum
    finding crítico)") num caso nada raro: UM critical custa 40 pontos, deixa
    o score em exatamente 60, e o comando saía 0. Um repositório sem harness
    nenhum passava por qualquer gate de CI que olhasse o exit code.

    A regra agora é a que o documento sempre prometeu — qualquer `critical`
    sai 1 —, mantendo o piso de score para o caso de acúmulo de findings
    menores (quatro `warning` também comprometem a estrutura, sem nenhum
    critical).
    """
    if any(f.severity == "critical" for f in report.findings):
        return 1
    return 0 if report.score >= 60 else 1


#: Subcomandos que NÃO disparam a atualização automática dos artefatos
#: compilados, por três razões distintas:
#:
#: - `compile`/`compile-session`: são o próprio alvo da recompilação — o
#:   gatilho aqui os chamaria em laço.
#: - `doctor`: existe para mostrar o estado REAL das 3 camadas de versão.
#:   Corrigir uma delas antes de reportar tornaria o laudo uma ficção.
#: - `status`/`enable`/`disable`: o kill-switch precisa responder em qualquer
#:   estado, inclusive com o harness quebrado. É a saída de emergência; nada
#:   pode rodar antes dela.
_AUTO_UPDATE_EXEMPT_COMMANDS = frozenset(
    {"compile", "compile-session", "doctor", "status", "enable", "disable"}
)


def _auto_update(command: str | None, target_dir: Path) -> None:
    """Sincroniza os artefatos compilados com o pacote instalado antes de
    despachar o subcomando. Ver `harness.autoupdate`.

    O `except` amplo é o mesmo compromisso do módulo: uma falha na
    atualização automática nunca pode mudar o resultado do comando que o
    usuário pediu."""
    if command in _AUTO_UPDATE_EXEMPT_COMMANDS:
        return
    try:
        from harness.autoupdate import sync_if_outdated

        sync_if_outdated(target_dir)
    except Exception as exc:
        print(f"aviso: atualização automática do harness ignorada ({exc})", file=sys.stderr)


def main() -> None:
    # No Windows, stdout redirecionado/piped fica na locale cp1252 e corrompia o JSON
    # ensure_ascii=False do laudo (UnicodeEncodeError em paths com caracteres fora do cp1252, ex. cirílico/CJK).
    #
    # O stderr entrou junto (atrito 4 do ciclo `harness-finish`): reconfigurar só
    # o stdout deixava os dois streams em codecs DIFERENTES, e as mensagens de
    # erro acentuadas ("contrato não aprovado") saíam em cp1252. Quem captura o
    # stderr decodificando UTF-8 — qualquer chamador programático, e a suíte e2e
    # entre eles — recebia `UnicodeDecodeError` na thread leitora do subprocess
    # e um `stderr` `None` no lugar do texto. O sintoma não parecia de encoding:
    # o teste quebrava com `TypeError` num assert sobre a mensagem.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="harness", description="harness-creator — Agente = Modelo + Harness")
    sub = parser.add_subparsers(dest="command", required=True)

    comp = sub.add_parser("compile", help="Compila .harness/harness.yaml -> governança nativa do Claude Code")
    comp.add_argument("--dir", default=".", help="Raiz do projeto-alvo")

    aud = sub.add_parser("audit", help="Avalia a estrutura de harness do projeto (score + findings JSON)")
    aud.add_argument("--dir", default=".", help="Raiz do projeto-alvo")

    aud_rt = sub.add_parser(
        "audit-runtime",
        help="Audita os artefatos runtime-mutáveis (feature_list.json, evidence, progress) — score + findings JSON",
    )
    aud_rt.add_argument("--dir", default=".", help="Raiz do projeto-alvo")

    ana = sub.add_parser("analyze", help="Analisa o repo-alvo e grava .harness/repo-profile.json")
    ana.add_argument("--dir", default=".", help="Raiz do projeto-alvo")

    pf = sub.add_parser(
        "preflight",
        help="Avalia a prontidão do repo-alvo para instalação do harness (laudo PASS/WARNING/FAIL) — JSON only",
    )
    pf.add_argument("--dir", default=".", help="Raiz do projeto-alvo")

    cc = sub.add_parser("compile-contract", help="Compila .harness/work/<slug> -> .harness/feature_list.json")
    cc.add_argument("--dir", default=".", help="Raiz do projeto-alvo")
    cc.add_argument("--slug", required=True, help="Identificador do contrato em .harness/work/<slug>")
    cc.add_argument(
        "--dry-run-verify", action="store_true",
        help="Roda cada verify_cmd com timeout curto e avisa (stderr) se falhar "
        "rápido — não bloqueia a compilação",
    )

    task = sub.add_parser("task", help="Comandos sobre tarefas de um contrato (Plans.md)")
    task_sub = task.add_subparsers(dest="task_command", required=True)

    task_add_file = task_sub.add_parser(
        "add-file",
        help="Adiciona um path ao files[] de uma task existente em Plans.md e recompila o contrato",
    )
    task_add_file.add_argument("task_id", help="Id da task em Plans.md (ex.: T-01)")
    task_add_file.add_argument("path", help="Path a adicionar ao files[] da task")
    task_add_file.add_argument("--dir", default=".", help="Raiz do projeto-alvo")
    task_add_file.add_argument(
        "--slug", default=None,
        help="Identificador do contrato em .harness/work/<slug> — se omitido e "
        "houver exatamente um contrato em .harness/work/, é inferido",
    )
    task_add_file.add_argument(
        "--dry-run-verify", action="store_true",
        help="Repassado para a recompilação — ver `compile-contract --dry-run-verify`",
    )

    prof = sub.add_parser(
        "profile",
        help="Correcao pontual do .harness/repo-profile.json — rodar no terminal do USUARIO",
    )
    prof_sub = prof.add_subparsers(dest="profile_command", required=True)

    prof_set = prof_sub.add_parser(
        "set",
        help="Grava uma chave de AMBIENTE do profile (package_manager, "
        "test_command, lint_command, typecheck_command, build_command)",
    )
    prof_set.add_argument("key", help="Chave a ajustar (enumeração fechada)")
    prof_set.add_argument("value", help="Novo valor")
    prof_set.add_argument("--dir", default=".", help="Raiz do projeto-alvo")

    cs = sub.add_parser(
        "compile-session",
        help="Compila a sessão autônoma (Fase 2): permissions, boundary guard, lifecycle, templates, SessionStart",
    )
    cs.add_argument("--dir", default=".", help="Raiz do projeto-alvo")
    cs.add_argument(
        "--no-branch", action="store_true",
        help="Compila os artefatos sem criar nem trocar a branch de contrato, "
        "mesmo com branch_per_contract ativo. Existe para a recompilação "
        "automática (harness.autoupdate), que não pode mover o desenvolvedor "
        "de branch sem ele pedir",
    )

    ver = sub.add_parser(
        "verify", help="Roda o verify_cmd de uma feature e grava .harness/evidence/<id>.json"
    )
    ver.add_argument("feature_id", help="Id da feature em .harness/feature_list.json")
    ver.add_argument("--dir", default=".", help="Raiz do projeto-alvo")
    ver.add_argument(
        "--no-mark-passed", action="store_false", dest="mark_passed", default=True,
        help="Não grava passes:true mesmo com exit_code==0 — só a evidência. "
        "Para fleets com múltiplos agentes escrevendo o mesmo "
        "feature_list.json em paralelo (a escrita não tem lock entre "
        "processos). Sessão sequencial normal não precisa disto",
    )
    ver.add_argument(
        "--mark-passed", action="store_true", dest="mark_passed", default=True,
        help="(compat) no-op — marcar passou a ser o default na v0.23.0",
    )
    ver.add_argument(
        "--timeout", type=int, default=None, metavar="SEGUNDOS",
        help="Timeout do verify_cmd em segundos (default 600). Suítes "
        "legítimas mais lentas que o default eram mortas — use isto em vez "
        "de dividir o verify_cmd",
    )
    ver.add_argument(
        "--no-reproof", action="store_false", dest="reproof", default=True,
        help="Não re-prova as tarefas já concluídas que compartilham arquivo "
        "com esta (§6 do design). Escape hatch para quando a própria re-prova "
        "é o problema — prova antiga lenta, ambiente meio quebrado. Desligar "
        "custa a detecção de regressão entre fatias",
    )
    ver.add_argument(
        "--stream", action="store_true",
        help="Espelha stdout/stderr do verify_cmd no console em tempo real "
        "(tee) — para humano distinguir suíte lenta de travada. Opt-in: com "
        "streaming sempre ligado, toda a saída da suíte entraria no contexto "
        "do agente a cada verify",
    )

    decide = sub.add_parser(
        "decide",
        help="Registra uma decisão do projeto (com o porquê) em .harness/decisions.md",
    )
    decide.add_argument("title", help="Título curto da decisão")
    decide.add_argument(
        "--decision", required=True, help="O que foi decidido, em uma frase",
    )
    decide.add_argument(
        "--why", required=True,
        help="A razão, incluindo a alternativa descartada e por quê. Obrigatório: "
        "decisão sem porquê não impede ninguém de re-litigar, que é o único "
        "trabalho deste registro",
    )
    decide.add_argument("--dir", default=".", help="Raiz do projeto-alvo")

    lesson = sub.add_parser(
        "lesson",
        help="Anota uma fricção observada em .harness/lessons.md (quem compila é o humano)",
    )
    lesson.add_argument("friction", help="A fricção observada, em uma linha")
    lesson.add_argument(
        "--fix", required=True, help="A melhoria candidata no harness/skill/critério",
    )
    lesson.add_argument("--dir", default=".", help="Raiz do projeto-alvo")

    blind = sub.add_parser(
        "blind",
        help="Camada 3 (§6): monta o pacote de verificação cega e registra o veredito",
    )
    blind_sub = blind.add_subparsers(dest="blind_command", required=True)

    blind_package = blind_sub.add_parser(
        "package",
        help="Monta .harness/scratch/blind-package.md a partir do contrato — "
        "sem nada do raciocínio de quem implementou",
    )
    blind_package.add_argument("--dir", default=".", help="Raiz do projeto-alvo")

    blind_verdict = blind_sub.add_parser(
        "verdict",
        help="Registra o veredito do verificador em .harness/blind-review/<contrato>.json",
    )
    blind_side = blind_verdict.add_mutually_exclusive_group(required=True)
    blind_side.add_argument(
        "--pass", dest="passed", action="store_true", help="A entrega confere com o critério",
    )
    blind_side.add_argument(
        "--fail", dest="passed", action="store_false", help="A entrega não confere com o critério",
    )
    blind_verdict.add_argument(
        "--evidence", required=True,
        help="O quê e ONDE (`arquivo:linha`). Obrigatório: veredito sem "
        "evidência gera re-tentativa cega (§9.1)",
    )
    blind_verdict.add_argument("--dir", default=".", help="Raiz do projeto-alvo")

    team = sub.add_parser("team", help="Team-Architecture Factory (Fase 4): design/generate de times de agentes")
    team_sub = team.add_subparsers(dest="team_command", required=True)

    team_design = team_sub.add_parser(
        "design", help="Dry-run: analisa o domínio e recomenda um padrão de time (não escreve nada)"
    )
    team_design.add_argument("--dir", default=".", help="Raiz do projeto-alvo")
    team_design.add_argument("--description", required=True, help="Descrição da demanda/domínio em linguagem natural")

    team_generate = team_sub.add_parser(
        "generate", help="Gera os artefatos do time (.claude/agents, .claude/skills, AGENTS.md, manifesto)"
    )
    team_generate.add_argument("--dir", default=".", help="Raiz do projeto-alvo")
    team_generate.add_argument("--pattern", required=True, help="Nome do padrão de time (catálogo src/harness/teams/patterns/)")
    team_generate.add_argument(
        "--mode", default="subagents", choices=["subagents", "agent-teams"], help="Modo de execução do time"
    )
    team_generate.add_argument(
        "--max-review-iterations", type=int, default=3, help="Teto de iterações de revisão do padrão produtor-revisor"
    )

    rev = sub.add_parser("review", help="Transições do state machine de revisão do padrão Produtor-Revisor")
    rev.add_argument("feature_id", help="Id da feature em .harness/feature_list.json")
    rev.add_argument("decision", choices=["submit", "approve", "reject"], help="Transição a aplicar")
    rev.add_argument("--dir", default=".", help="Raiz do projeto-alvo")
    rev.add_argument("--note", default="", help="Nota da decisão (aprovação/rejeição)")
    rev.add_argument("--justification", default=None, help="Justificativa (obrigatória para aprovar diff de teste)")

    sup = sub.add_parser("supervise", help="Devolve a próxima feature pronta a trabalhar (ou null)")
    sup.add_argument("--dir", default=".", help="Raiz do projeto-alvo")

    bud = sub.add_parser(
        "budget",
        help="Disjuntor do loop: conta o rastro de tentativas de uma feature e "
        "devolve continue/stop_same_failure/stop_iterations. Só leitura",
    )
    bud.add_argument("--feature", required=True, help="Id da feature em .harness/feature_list.json")
    bud.add_argument("--dir", default=".", help="Raiz do projeto-alvo")

    rec = sub.add_parser(
        "reconcile",
        help="Reconcilia estado declarado × estado real na abertura da sessão — "
        "prova velha, tarefa marcada sem prova, sobra na tree, progresso de outra "
        "demanda. Só leitura",
    )
    rec.add_argument("--dir", default=".", help="Raiz do projeto-alvo")

    aud_team = sub.add_parser("audit-team", help="Audita os artefatos de time da Fase 4 — score + findings JSON")
    aud_team.add_argument("--dir", default=".", help="Raiz do projeto-alvo")

    fin = sub.add_parser(
        "finish",
        help="Encerra a demanda: audita o fecho (evidência fresca, tudo passando, "
        "sem resíduo) e varre os descartáveis do .harness/. Nunca toca git",
    )
    fin.add_argument("--dir", default=".", help="Raiz do projeto-alvo")

    dis = sub.add_parser(
        "disable",
        help="Kill-switch: desativa COMPLETAMENTE o harness (todos os hooks) — rodar só no terminal do usuário",
    )
    dis.add_argument("--dir", default=".", help="Raiz do projeto-alvo")
    dis.add_argument("--note", default="", help="Nota livre registrada no sentinel (motivo da desativação)")

    ena = sub.add_parser("enable", help="Kill-switch: reativa o harness (remove o sentinel de desativação)")
    ena.add_argument("--dir", default=".", help="Raiz do projeto-alvo")

    stat = sub.add_parser("status", help="Kill-switch: mostra se o harness está ativo ou desativado")
    stat.add_argument("--dir", default=".", help="Raiz do projeto-alvo")

    doc = sub.add_parser(
        "doctor",
        help="Compara a versão do pacote pip, do .harness/ compilado e do cache de "
        "plugin do Claude Code — aponta o comando exato para corrigir divergência",
    )
    doc.add_argument("--dir", default=".", help="Raiz do projeto-alvo")

    prd = sub.add_parser(
        "pr-draft",
        help="Monta o corpo do Pull Request a partir do contrato e imprime o comando "
        "`gh pr create` pronto — NÃO abre PR nenhum",
    )
    prd.add_argument("--dir", default=".", help="Raiz do projeto-alvo")

    args = parser.parse_args()

    # Um ponto só para os 19 subcomandos que aceitam `--dir` — validar em cada
    # branch do dispatch é o tipo de coisa que fica pela metade (foi assim que
    # `compile` acertava e `analyze`/`audit` erravam).
    if getattr(args, "dir", None) is not None:
        args.dir = str(_validated_target_dir(args.dir))
        _auto_update(args.command, Path(args.dir))

    if args.command == "compile":
        from harness.compiler import compile_project
        from harness.boundary_guard import install_boundary_guard

        try:
            result = compile_project(Path(args.dir))
            # Instala boundary_guard já no compile (Fase 2): default-deny sem contrato ativo,
            # atualizado/liberado em compile-session conforme features aprovadas.
            target_dir = Path(args.dir).resolve()
            boundary_guard_path = install_boundary_guard(target_dir)
            hooks_written = list(result.hooks_written) + [boundary_guard_path]
        except (FileNotFoundError, ValueError) as exc:
            print(f"erro: {exc}", file=sys.stderr)
            sys.exit(1)
        print(json.dumps({
            "settings": str(result.settings_path),
            "agents_md": str(result.agents_path),
            "hooks": [str(p) for p in hooks_written],
            "warnings": result.warnings,
        }, indent=2, ensure_ascii=False))
        sys.exit(0)

    if args.command == "pr-draft":
        from harness.pr_draft import PrDraftError, build_pr_draft

        try:
            draft = build_pr_draft(Path(args.dir))
        except PrDraftError as exc:
            print(f"erro: {exc}", file=sys.stderr)
            sys.exit(1)
        print(json.dumps({
            "title": draft.title,
            "branch": draft.branch,
            "body": str(draft.body_path),
            "command": draft.command,
        }, indent=2, ensure_ascii=False))
        sys.exit(0)

    if args.command == "audit":
        from harness.audit import audit_project

        report = audit_project(Path(args.dir))
        print(report.to_json())
        sys.exit(_audit_exit_code(report))

    if args.command == "audit-runtime":
        from harness.runtime_audit import audit_runtime

        report = audit_runtime(Path(args.dir))
        print(report.to_json())
        sys.exit(_audit_exit_code(report))

    if args.command == "analyze":
        from harness.analyzer import analyze_project, write_profile

        profile = analyze_project(Path(args.dir))
        write_profile(profile, Path(args.dir))
        print(json.dumps(profile.to_dict(), indent=2, ensure_ascii=False))
        sys.exit(0)

    if args.command == "preflight":
        from harness.preflight import PreflightError, run_preflight

        try:
            report = run_preflight(Path(args.dir))
        except PreflightError as exc:
            print(f"erro: {exc}", file=sys.stderr)
            sys.exit(2)

        print(report.to_json())
        if report.verdict == "NOT_READY":
            sys.exit(1)
        sys.exit(0)

    if args.command == "compile-contract":
        from harness.contract import ContractError, compile_contract

        try:
            result = compile_contract(Path(args.dir), args.slug, dry_run_verify=args.dry_run_verify)
        except ContractError as exc:
            print(f"erro: {exc}", file=sys.stderr)
            sys.exit(1)
        data = json.loads(result.read_text(encoding="utf-8"))
        print(json.dumps({
            "feature_list": str(result),
            "features": len(data.get("features", [])),
            "contract": args.slug,
        }, indent=2, ensure_ascii=False))
        sys.exit(0)

    if args.command == "task" and args.task_command == "add-file":
        from harness.contract import ContractError, ContractNotApprovedError, add_task_file, compile_contract

        target_dir = Path(args.dir)

        slug = args.slug
        if slug is None:
            work_dir = target_dir / ".harness" / "work"
            candidates = sorted(
                p.name for p in work_dir.iterdir()
                if p.is_dir() and (p / "spec.md").is_file()
            ) if work_dir.is_dir() else []
            if len(candidates) == 1:
                slug = candidates[0]
            elif not candidates:
                print(
                    "erro: nenhum contrato encontrado em .harness/work/ — rode "
                    "harness compile-contract primeiro ou informe --slug",
                    file=sys.stderr,
                )
                sys.exit(1)
            else:
                print(
                    "erro: múltiplos contratos em .harness/work/ ("
                    + ", ".join(candidates)
                    + ") — informe --slug explicitamente",
                    file=sys.stderr,
                )
                sys.exit(1)

        try:
            added = add_task_file(target_dir, slug, args.task_id, args.path)
        except ContractError as exc:
            print(f"erro: {exc}", file=sys.stderr)
            sys.exit(1)

        if not added:
            print(
                f"aviso: '{args.path}' já está em files[] de {args.task_id} — nada a fazer",
                file=sys.stderr,
            )

        try:
            result = compile_contract(target_dir, slug, dry_run_verify=args.dry_run_verify)
        except ContractNotApprovedError as exc:
            print(
                f"erro: Plans.md atualizado ({args.task_id}: +{args.path}), mas a "
                f"recompilação foi barrada — {exc}",
                file=sys.stderr,
            )
            sys.exit(1)
        except ContractError as exc:
            print(f"erro: {exc}", file=sys.stderr)
            sys.exit(1)

        data = json.loads(result.read_text(encoding="utf-8"))
        print(json.dumps({
            "feature_list": str(result),
            "features": len(data.get("features", [])),
            "contract": slug,
            "task_id": args.task_id,
            "path": args.path,
            "added": added,
        }, indent=2, ensure_ascii=False))
        sys.exit(0)

    if args.command == "profile" and args.profile_command == "set":
        from harness.profile_edit import ProfileEditError, next_step_note, set_profile_value

        try:
            profile_path = set_profile_value(Path(args.dir), args.key, args.value)
        except ProfileEditError as exc:
            print(f"erro: {exc}", file=sys.stderr)
            sys.exit(1)

        print(json.dumps({
            "profile": str(profile_path),
            "key": args.key,
            "value": args.value,
            "note": next_step_note(args.key),
        }, indent=2, ensure_ascii=False))
        sys.exit(0)

    if args.command == "compile-session":
        from harness.boundary_guard import install_boundary_guard
        from harness.branching import (
            BranchingError,
            ensure_contract_branch,
            is_git_repository,
            load_branch_per_contract,
        )
        from harness.lifecycle import install_lifecycle
        from harness.metrics import record_event
        from harness.session_permissions import (
            FEATURE_LIST_FILE,
            REPO_PROFILE_FILE,
            compile_session_permissions,
            missing_harness_yaml_warning,
        )
        from harness.session_start import install_session_start
        from harness.stop_hook import install_stop_hook
        from harness.templates import install_templates, manual_init_scripts

        target_dir = Path(args.dir)
        resolved_dir = target_dir.resolve()
        feature_list_path = resolved_dir / FEATURE_LIST_FILE

        # Fluxo branch-first (finding C): posicionar em contract/<slug> ANTES
        # de qualquer escrita — o dirty-check não pode contar artefatos que o
        # próprio compile-session grava. Sem feature_list, pula: o
        # compile_session_permissions abaixo produz o erro canônico.
        # `--no-branch` desliga o posicionamento em `contract/<slug>` — com ele
        # o dirty-check de `ensure_contract_branch` também não se aplica, porque
        # o que aquele check protege é a CRIAÇÃO da branch. Ver `--no-branch` em
        # `add_argument` e `harness.autoupdate`.
        branch = None
        if not args.no_branch and load_branch_per_contract(target_dir) and feature_list_path.is_file():
            if not is_git_repository(resolved_dir):
                print(
                    "aviso: branch_per_contract ativo mas o diretório não é um "
                    "repositório git — branch de contrato não criada",
                    file=sys.stderr,
                )
            else:
                contract_slug = json.loads(
                    feature_list_path.read_text(encoding="utf-8-sig")
                ).get("contract", "")
                try:
                    branch = ensure_contract_branch(resolved_dir, contract_slug)
                except BranchingError as exc:
                    print(f"erro: {exc}", file=sys.stderr)
                    sys.exit(1)

        try:
            settings_path = compile_session_permissions(target_dir)
        except FileNotFoundError as exc:
            print(f"erro: {exc}", file=sys.stderr)
            sys.exit(1)

        yaml_warning = missing_harness_yaml_warning(target_dir)
        if yaml_warning:
            print(f"aviso: {yaml_warning}", file=sys.stderr)

        feature_list = json.loads(feature_list_path.read_text(encoding="utf-8-sig"))
        profile_path = resolved_dir / REPO_PROFILE_FILE
        profile = json.loads(profile_path.read_text(encoding="utf-8-sig")) if profile_path.is_file() else {}

        boundary_guard_path = install_boundary_guard(target_dir)
        agents_path, lifecycle_detail_path = install_lifecycle(target_dir)
        templates_written = install_templates(target_dir, feature_list, profile)
        # `init.*` sem o marcador gerenciado foi editado à mão e NÃO é
        # regenerado (item 5 do laudo de footprint). Preservar em silêncio
        # deixaria o script divergindo do profile sem sinal nenhum.
        templates_preserved = manual_init_scripts(target_dir)
        session_start_path = install_session_start(target_dir)
        stop_hook_path = install_stop_hook(target_dir)

        for path in templates_preserved:
            print(
                f"aviso: {path} foi editado à mão (sem o marcador do harness) — "
                "preservado, NÃO regenerado a partir do repo-profile.json; "
                "apague o arquivo e recompile para voltar ao script gerado",
                file=sys.stderr,
            )

        # Item 3: a allowlist de comandos extras passou a ser lida em runtime
        # por um parser stdlib deliberadamente burro. Se ele não entende o que
        # o pyyaml entendeu, o comando vira deny silencioso — com o
        # settings.json compilado logo acima afirmando o contrário.
        from harness.boundary_guard import extra_allowed_commands_grammar_problem

        grammar_problem = extra_allowed_commands_grammar_problem(target_dir)
        if grammar_problem:
            print(f"aviso: {grammar_problem}", file=sys.stderr)

        # F7: o `test_glob` tinha duas fontes — a do `harness.yaml` alimentava o
        # `guard_tests`, a do `repo-profile.json` alimentava o gate de diff de
        # teste da revisão. Governança vence, e precisa chegar às duas.
        from harness.profile_edit import reconcile_test_glob

        test_glob_reconciled = reconcile_test_glob(target_dir)
        if test_glob_reconciled:
            print(f"aviso: {test_glob_reconciled}", file=sys.stderr)

        record_event(target_dir, "compile-session")

        print(json.dumps({
            "settings": str(settings_path),
            "boundary_guard": str(boundary_guard_path),
            "agents_md": str(agents_path),
            "lifecycle_detail": str(lifecycle_detail_path),
            "templates": [str(p) for p in templates_written],
            "templates_preserved": [str(p) for p in templates_preserved],
            "session_start_hook": str(session_start_path),
            "stop_hook": str(stop_hook_path),
            "branch": branch,
            "extra_allowed_commands_grammar_problem": grammar_problem,
            "test_glob_reconciled": test_glob_reconciled,
        }, indent=2, ensure_ascii=False))
        sys.exit(0)

    if args.command == "verify":
        from harness.contract import FEATURE_LIST_FILE
        from harness.verify import (
            _VERIFY_TIMEOUT_SECONDS,
            VerifyError,
            VerifyFailedError,
            mark_feature_passed,
            run_verify,
        )

        try:
            evidence_path = run_verify(
                Path(args.dir), args.feature_id,
                timeout_seconds=args.timeout if args.timeout is not None
                else _VERIFY_TIMEOUT_SECONDS,
                stream=args.stream,
            )
        except VerifyFailedError as exc:
            print(_truncate_output(exc.stdout), file=sys.stderr)
            print(_truncate_output(exc.stderr), file=sys.stderr)
            if exc.file_lock_hint:
                print(f"aviso: {exc.file_lock_hint}", file=sys.stderr)
            sys.exit(exc.exit_code)
        except VerifyError as exc:
            print(f"erro: {exc}", file=sys.stderr)
            sys.exit(1)

        # Item 3 do backlog do dogfood miojo: a saída precisa DIZER em que
        # estado a tarefa ficou. Antes, o verify verde não marcava `passes` e
        # não mencionava a flag que faria isso — `harness supervise` seguia
        # devolvendo a mesma tarefa e não havia de onde deduzir o porquê.
        # stderr, nunca stdout: o stdout é o JSON da evidência, consumido por
        # `json.loads` mundo afora.
        if args.mark_passed:
            mark_feature_passed(Path(args.dir), args.feature_id)
            print(
                f"{args.feature_id}: passes:true gravado em "
                f"{FEATURE_LIST_FILE} — tarefa fechada",
                file=sys.stderr,
            )
        else:
            print(
                f"{args.feature_id}: evidência gravada, mas passes continua "
                "false (--no-mark-passed) — `harness supervise` vai devolver "
                "esta tarefa de novo",
                file=sys.stderr,
            )

        from harness.supervisor import on_feature_verified

        on_feature_verified(Path(args.dir), args.feature_id)

        # Re-prova incremental (§6): a prova desta fatia acabou de passar, mas
        # ela pode ter quebrado uma fatia já concluída que mexe nos mesmos
        # arquivos. Roda aqui, sem ninguém precisar lembrar — o mesmo motivo
        # pelo qual o aviso do `reconcile` chega pelo hook e não por disciplina.
        # Depois do `mark_feature_passed`: a re-prova lê o `feature_list.json`,
        # e a tarefa atual precisa estar com o estado final antes disso.
        # `--no-mark-passed` desliga junto: ele existe para fleet paralelo, e é
        # justamente o caso em que escrever `passes: false` em tarefas de OUTRO
        # agente é a corrida que a flag foi criada para evitar.
        reproof_report = None
        if args.reproof and args.mark_passed:
            import harness.regression as regression_module

            try:
                reproof_report = regression_module.run_reproof(
                    Path(args.dir), args.feature_id,
                    timeout_seconds=args.timeout if args.timeout is not None
                    else _VERIFY_TIMEOUT_SECONDS,
                )
            except Exception as exc:  # noqa: BLE001
                # A evidência desta tarefa já está gravada. Derrubar o comando
                # aqui apagaria um verde legítimo por causa de um subproduto —
                # mas o aviso é obrigatório: proteção que falhou em silêncio é
                # indistinguível de proteção que passou.
                print(
                    f"aviso: re-prova incremental não pôde rodar ({exc}) — a "
                    "regressão em tarefas já concluídas NÃO foi verificada",
                    file=sys.stderr,
                )

        data = json.loads(evidence_path.read_text(encoding="utf-8-sig"))
        print(json.dumps(data, indent=2, ensure_ascii=False))

        if reproof_report is not None:
            rendered = regression_module.render_reproof_report(reproof_report)
            if rendered:
                print(rendered, file=sys.stderr)
            if reproof_report["regressed"]:
                # Mesma convenção de `budget` e `reconcile`: 2 é veredito
                # legítimo de parada, distinto do erro de execução (1). O verde
                # desta fatia continua verdadeiro e gravado — o que o exit code
                # diz é que o trabalho não acabou.
                sys.exit(2)

        sys.exit(0)

    if args.command == "team" and args.team_command == "design":
        from harness.teams import analyze_domain, load_pattern, recommend_pattern

        domain = analyze_domain(Path(args.dir))
        pattern_name, justification = recommend_pattern(domain, args.description)
        pattern = load_pattern(pattern_name)
        print(json.dumps({
            "pattern": pattern_name,
            "justification": justification,
            "roles": [r.name for r in pattern.roles],
        }, indent=2, ensure_ascii=False))
        sys.exit(0)

    if args.command == "team" and args.team_command == "generate":
        from harness.teams import TeamError, generate_team

        try:
            result = generate_team(
                Path(args.dir),
                args.pattern,
                mode=args.mode,
                max_review_iterations=args.max_review_iterations,
            )
        except TeamError as exc:
            print(f"erro: {exc}", file=sys.stderr)
            sys.exit(1)

        print(json.dumps({
            "pattern": result.pattern,
            "mode": result.mode,
            "roles": result.roles,
            "agents_written": [str(p) for p in result.agents_written],
            "skills_written": [str(p) for p in result.skills_written],
            "agents_md": str(result.agents_md),
            "team_detail": str(result.team_detail),
            "manifest": str(result.manifest),
        }, indent=2, ensure_ascii=False))
        sys.exit(0)

    if args.command == "review":
        from harness.contract import FEATURE_LIST_FILE
        from harness.review import REVIEW_DIR, ReviewError, record_decision, submit_for_review

        target_dir = Path(args.dir)

        if args.decision == "submit":
            try:
                submit_for_review(target_dir, args.feature_id)
            except ReviewError as exc:
                print(f"erro: {exc}", file=sys.stderr)
                sys.exit(1)
        else:
            feature_list_path = target_dir.resolve() / FEATURE_LIST_FILE
            if not feature_list_path.is_file():
                print(f"erro: {feature_list_path}: feature_list.json não encontrado", file=sys.stderr)
                sys.exit(1)

            try:
                feature_list_data = json.loads(feature_list_path.read_text(encoding="utf-8-sig"))
            except json.JSONDecodeError as exc:
                print(f"erro: {feature_list_path}: JSON inválido — {exc}", file=sys.stderr)
                sys.exit(1)

            feature = next(
                (f for f in feature_list_data.get("features", []) if f.get("id") == args.feature_id),
                None,
            )
            if feature is None:
                print(f"erro: feature '{args.feature_id}' não encontrada em {feature_list_path}", file=sys.stderr)
                sys.exit(1)

            decision = "approved" if args.decision == "approve" else "rejected"
            try:
                record_decision(
                    target_dir, args.feature_id, feature, decision, args.note, args.justification
                )
            except ReviewError as exc:
                print(f"erro: {exc}", file=sys.stderr)
                sys.exit(1)

        review_path = target_dir.resolve() / REVIEW_DIR / f"{args.feature_id}.json"
        data = json.loads(review_path.read_text(encoding="utf-8-sig"))
        print(json.dumps(data, indent=2, ensure_ascii=False))
        sys.exit(0)

    if args.command == "supervise":
        from harness.supervisor import dispatch_next

        next_feature = dispatch_next(Path(args.dir))
        print(json.dumps({"next": next_feature}, indent=2, ensure_ascii=False))
        sys.exit(0)

    if args.command == "budget":
        from harness.budget import CONTINUE, BudgetError, check_budget

        try:
            report = check_budget(Path(args.dir), args.feature)
        except BudgetError as exc:
            print(f"erro: {exc}", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        # Exit 2 no veredito de parada: um `if` de shell distingue "continua"
        # de "para" sem parsear JSON, e 2 (não 1) porque 1 já significa erro de
        # execução no resto da CLI — parar por budget é resultado legítimo do
        # comando, não falha dele.
        sys.exit(0 if report["verdict"] == CONTINUE else 2)

    if args.command == "reconcile":
        import harness.reconcile as reconcile_module

        try:
            report = reconcile_module.reconcile(Path(args.dir))
        except Exception as exc:  # noqa: BLE001 — ver docstring abaixo
            # Falhar ao PRODUZIR o relatório não pode ser confundido com "não
            # há divergência". Este comando é consultado na abertura da sessão
            # para decidir se dá para continuar; um exit 0 por não ter
            # conseguido olhar seria a resposta mais perigosa possível.
            print(f"erro: não foi possível reconciliar: {exc}", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        # Exit 2 = há divergência, mesma convenção de `harness budget`: resultado
        # legítimo do comando, não falha dele (1 segue sendo erro de execução).
        sys.exit(2 if report["divergences"] else 0)

    if args.command == "finish":
        from harness.finish import audit_closure, sweep_disposables

        from harness.spine import open_lessons

        report = audit_closure(Path(args.dir))
        # A auditoria é o gate: reprovada, o comando reporta e sai sem varrer
        # nada — limpar por cima de um fecho quebrado apagaria o rastro
        # necessário para consertá-lo.
        if not report["blockers"]:
            report["swept"] = sweep_disposables(Path(args.dir))
        # As lições saem SEMPRE, inclusive com bloqueador: elas não são veredito
        # de fecho, são a pauta do humano (§5.3), e a demanda que travou é
        # justamente a que costuma ter gerado fricção. Lista sempre presente —
        # chave ausente e lista vazia dizem coisas diferentes a quem consome
        # este JSON.
        report["open_lessons"] = [
            f"{lesson.friction} → {lesson.fix}" if lesson.fix else lesson.friction
            for lesson in open_lessons(Path(args.dir))
        ]
        print(json.dumps(report, indent=2, ensure_ascii=False))
        sys.exit(1 if report["blockers"] else 0)

    if args.command == "decide":
        from harness.spine import DECISIONS_FILE, record_decision

        decision_id = record_decision(
            Path(args.dir), args.title, decision=args.decision, why=args.why,
        )
        print(json.dumps({
            "id": decision_id,
            "file": DECISIONS_FILE,
            "title": args.title,
        }, indent=2, ensure_ascii=False))
        sys.exit(0)

    if args.command == "lesson":
        from harness.spine import LESSONS_FILE, open_lessons, record_lesson

        line = record_lesson(Path(args.dir), args.friction, fix=args.fix)
        print(json.dumps({
            "line": line,
            "file": LESSONS_FILE,
            # A contagem de abertas é o único número que interessa aqui: ela é o
            # que o humano vai encontrar no fecho da demanda.
            "open": len(open_lessons(Path(args.dir))),
        }, indent=2, ensure_ascii=False))
        sys.exit(0)

    if args.command == "blind" and args.blind_command == "package":
        from harness.blind import (
            BLIND_PACKAGE_FILE,
            BlindError,
            build_package,
            load_contract,
            package_tasks,
        )

        try:
            build_package(Path(args.dir))
            data = load_contract(Path(args.dir))
        except BlindError as exc:
            print(f"erro: {exc}", file=sys.stderr)
            sys.exit(1)
        # Path RELATIVO ao alvo, e não o absoluto do processo: quem lê este JSON
        # é o despacho do subagente, que roda com o repo como raiz.
        print(json.dumps({
            "package": BLIND_PACKAGE_FILE,
            "contract": data.get("contract"),
            "tasks": len(package_tasks(data)),
        }, indent=2, ensure_ascii=False))
        sys.exit(0)

    if args.command == "blind" and args.blind_command == "verdict":
        from harness.blind import BlindError, record_verdict

        try:
            entry = record_verdict(
                Path(args.dir), passed=args.passed, evidence=args.evidence,
            )
        except BlindError as exc:
            print(f"erro: {exc}", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(entry, indent=2, ensure_ascii=False))
        # 2 como em `budget`/`reconcile`/re-prova: veredito legítimo de parada,
        # não falha de execução. Reprovar é resultado normal deste passo.
        sys.exit(0 if args.passed else 2)

    if args.command == "audit-team":
        from harness.team_audit import audit_team

        report = audit_team(Path(args.dir))
        print(report.to_json())
        sys.exit(_audit_exit_code(report))

    if args.command == "disable":
        from harness.killswitch import disable, status
        from harness.metrics import record_event

        disable(Path(args.dir), note=args.note)
        record_event(Path(args.dir), "disable")
        print(json.dumps(status(Path(args.dir)), indent=2, ensure_ascii=False))
        sys.exit(0)

    if args.command == "enable":
        from harness.killswitch import enable, status
        from harness.metrics import record_event

        removed = enable(Path(args.dir))
        record_event(Path(args.dir), "enable")
        result = status(Path(args.dir))
        result["removed"] = removed
        print(json.dumps(result, indent=2, ensure_ascii=False))
        sys.exit(0)

    if args.command == "status":
        from harness.killswitch import status
        from harness.metrics import friction_summary
        from harness.session_permissions import FEATURE_LIST_FILE, missing_harness_yaml_warning

        result = status(Path(args.dir))
        # Instrumentação da onda 3: o gate da onda 5 (postura B vs C) precisa
        # do número de ciclos que um dogfood real ainda gasta. `status` é o
        # comando de leitura natural — o número aparece onde já se olha.
        result["friction"] = friction_summary(Path(args.dir))
        # Issue #72: sessão compilada (feature_list.json) sem harness.yaml —
        # mesmo aviso que compile-session/doctor já emitem, aqui também.
        if (Path(args.dir) / FEATURE_LIST_FILE).is_file():
            warning = missing_harness_yaml_warning(Path(args.dir))
            if warning:
                result["partial_governance_warning"] = warning
        print(json.dumps(result, indent=2, ensure_ascii=False))
        sys.exit(0)

    if args.command == "doctor":
        from harness.doctor import run_doctor

        report = run_doctor(Path(args.dir))
        print(report.to_json())
        sys.exit(0 if report.ok else 1)


if __name__ == "__main__":
    main()
