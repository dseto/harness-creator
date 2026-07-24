"""CLI: `harness run|compile|audit`.

`compile`/`audit` são o modo plugin (governança nativa do Claude Code) e não
dependem de Docker/Anthropic — imports do orquestrador são lazy de propósito.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> None:
    # No Windows, stdout redirecionado/piped fica na locale cp1252 e corrompia o JSON
    # ensure_ascii=False do laudo (UnicodeEncodeError em paths com caracteres fora do cp1252, ex. cirílico/CJK).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
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

    cs = sub.add_parser(
        "compile-session",
        help="Compila a sessão autônoma (Fase 2): permissions, boundary guard, lifecycle, templates, SessionStart",
    )
    cs.add_argument("--dir", default=".", help="Raiz do projeto-alvo")

    ver = sub.add_parser(
        "verify", help="Roda o verify_cmd de uma feature e grava .harness/evidence/<id>.json"
    )
    ver.add_argument("feature_id", help="Id da feature em .harness/feature_list.json")
    ver.add_argument("--dir", default=".", help="Raiz do projeto-alvo")
    ver.add_argument(
        "--mark-passed", action="store_true",
        help="Se exit_code==0, grava passes:true na feature em feature_list.json "
        "(opt-in; sessão orquestradora sequencial únicas — não usar com múltiplos "
        "agentes em paralelo no mesmo feature_list.json)",
    )
    ver.add_argument(
        "--timeout", type=int, default=None, metavar="SEGUNDOS",
        help="Timeout do verify_cmd em segundos (default 600). Suítes "
        "legítimas mais lentas que o default eram mortas — use isto em vez "
        "de dividir o verify_cmd",
    )
    ver.add_argument(
        "--stream", action="store_true",
        help="Espelha stdout/stderr do verify_cmd no console em tempo real "
        "(tee) — para humano distinguir suíte lenta de travada. Opt-in: com "
        "streaming sempre ligado, toda a saída da suíte entraria no contexto "
        "do agente a cada verify",
    )

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

    aud_team = sub.add_parser("audit-team", help="Audita os artefatos de time da Fase 4 — score + findings JSON")
    aud_team.add_argument("--dir", default=".", help="Raiz do projeto-alvo")

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

    args = parser.parse_args()

    if args.command == "compile":
        from harness.compiler import compile_project

        try:
            result = compile_project(Path(args.dir))
        except (FileNotFoundError, ValueError) as exc:
            print(f"erro: {exc}", file=sys.stderr)
            sys.exit(1)
        print(json.dumps({
            "settings": str(result.settings_path),
            "agents_md": str(result.agents_path),
            "hooks": [str(p) for p in result.hooks_written],
            "warnings": result.warnings,
        }, indent=2, ensure_ascii=False))
        sys.exit(0)

    if args.command == "audit":
        from harness.audit import audit_project

        report = audit_project(Path(args.dir))
        print(report.to_json())
        # score < 60 = estrutura comprometida (algum critical) -> exit 1
        sys.exit(0 if report.score >= 60 else 1)

    if args.command == "audit-runtime":
        from harness.runtime_audit import audit_runtime

        report = audit_runtime(Path(args.dir))
        print(report.to_json())
        # score < 60 = estrutura runtime comprometida (algum critical) -> exit 1
        sys.exit(0 if report.score >= 60 else 1)

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

    if args.command == "compile-session":
        from harness.boundary_guard import install_boundary_guard
        from harness.branching import (
            BranchingError,
            ensure_contract_branch,
            is_git_repository,
            load_branch_per_contract,
        )
        from harness.lifecycle import install_lifecycle
        from harness.session_permissions import (
            FEATURE_LIST_FILE,
            REPO_PROFILE_FILE,
            compile_session_permissions,
        )
        from harness.session_start import install_session_start
        from harness.stop_hook import install_stop_hook
        from harness.templates import install_templates

        target_dir = Path(args.dir)
        resolved_dir = target_dir.resolve()
        feature_list_path = resolved_dir / FEATURE_LIST_FILE

        # Fluxo branch-first (finding C): posicionar em contract/<slug> ANTES
        # de qualquer escrita — o dirty-check não pode contar artefatos que o
        # próprio compile-session grava. Sem feature_list, pula: o
        # compile_session_permissions abaixo produz o erro canônico.
        branch = None
        if load_branch_per_contract(target_dir) and feature_list_path.is_file():
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

        feature_list = json.loads(feature_list_path.read_text(encoding="utf-8-sig"))
        profile_path = resolved_dir / REPO_PROFILE_FILE
        profile = json.loads(profile_path.read_text(encoding="utf-8-sig")) if profile_path.is_file() else {}

        boundary_guard_path = install_boundary_guard(target_dir)
        agents_path, lifecycle_detail_path = install_lifecycle(target_dir)
        templates_written = install_templates(target_dir, feature_list, profile)
        session_start_path = install_session_start(target_dir)
        stop_hook_path = install_stop_hook(target_dir)

        print(json.dumps({
            "settings": str(settings_path),
            "boundary_guard": str(boundary_guard_path),
            "agents_md": str(agents_path),
            "lifecycle_detail": str(lifecycle_detail_path),
            "templates": [str(p) for p in templates_written],
            "session_start_hook": str(session_start_path),
            "stop_hook": str(stop_hook_path),
            "branch": branch,
        }, indent=2, ensure_ascii=False))
        sys.exit(0)

    if args.command == "verify":
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
            print(exc.stdout, file=sys.stderr)
            print(exc.stderr, file=sys.stderr)
            if exc.file_lock_hint:
                print(f"aviso: {exc.file_lock_hint}", file=sys.stderr)
            sys.exit(exc.exit_code)
        except VerifyError as exc:
            print(f"erro: {exc}", file=sys.stderr)
            sys.exit(1)

        if args.mark_passed:
            mark_feature_passed(Path(args.dir), args.feature_id)

        from harness.supervisor import on_feature_verified

        on_feature_verified(Path(args.dir), args.feature_id)

        data = json.loads(evidence_path.read_text(encoding="utf-8-sig"))
        print(json.dumps(data, indent=2, ensure_ascii=False))
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

    if args.command == "audit-team":
        from harness.team_audit import audit_team

        report = audit_team(Path(args.dir))
        print(report.to_json())
        sys.exit(0 if report.score >= 60 else 1)

    if args.command == "disable":
        from harness.killswitch import disable, status

        disable(Path(args.dir), note=args.note)
        print(json.dumps(status(Path(args.dir)), indent=2, ensure_ascii=False))
        sys.exit(0)

    if args.command == "enable":
        from harness.killswitch import enable, status

        removed = enable(Path(args.dir))
        result = status(Path(args.dir))
        result["removed"] = removed
        print(json.dumps(result, indent=2, ensure_ascii=False))
        sys.exit(0)

    if args.command == "status":
        from harness.killswitch import status

        print(json.dumps(status(Path(args.dir)), indent=2, ensure_ascii=False))
        sys.exit(0)

    if args.command == "doctor":
        from harness.doctor import run_doctor

        report = run_doctor(Path(args.dir))
        print(report.to_json())
        sys.exit(0 if report.ok else 1)


if __name__ == "__main__":
    main()
