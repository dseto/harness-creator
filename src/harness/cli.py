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
    parser = argparse.ArgumentParser(prog="harness", description="harness-creator — Agente = Modelo + Harness")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Executa uma tarefa dentro do harness (modo execução, congelado)")
    run.add_argument("task", help="Descrição da tarefa")
    run.add_argument("--config", default="config/harness.yaml")
    run.add_argument("--repo", default=".", help="Raiz do repositório alvo")

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

    cc = sub.add_parser("compile-contract", help="Compila .harness/work/<slug> -> .harness/feature_list.json")
    cc.add_argument("--dir", default=".", help="Raiz do projeto-alvo")
    cc.add_argument("--slug", required=True, help="Identificador do contrato em .harness/work/<slug>")

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
    team_generate.add_argument("--pattern", required=True, help="Nome do padrão de time (catálogo teams/patterns/)")
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

    args = parser.parse_args()

    if args.command == "run":
        import asyncio

        from harness.config import HarnessConfig
        from harness.orchestrator import AgentOrchestrator

        config = HarnessConfig.load(args.config)
        orchestrator = AgentOrchestrator(config, Path(args.repo))
        summary = asyncio.run(orchestrator.run_task(args.task))
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        sys.exit(0 if summary["status"] == "completed" else 1)

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

    if args.command == "compile-contract":
        from harness.contract import ContractError, compile_contract

        try:
            result = compile_contract(Path(args.dir), args.slug)
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

    if args.command == "compile-session":
        from harness.boundary_guard import install_boundary_guard
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

        try:
            settings_path = compile_session_permissions(target_dir)
        except FileNotFoundError as exc:
            print(f"erro: {exc}", file=sys.stderr)
            sys.exit(1)

        resolved_dir = target_dir.resolve()
        feature_list = json.loads((resolved_dir / FEATURE_LIST_FILE).read_text(encoding="utf-8"))
        profile_path = resolved_dir / REPO_PROFILE_FILE
        profile = json.loads(profile_path.read_text(encoding="utf-8")) if profile_path.is_file() else {}

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
        }, indent=2, ensure_ascii=False))
        sys.exit(0)

    if args.command == "verify":
        from harness.verify import VerifyError, VerifyFailedError, run_verify

        try:
            evidence_path = run_verify(Path(args.dir), args.feature_id)
        except VerifyFailedError as exc:
            print(exc.stdout, file=sys.stderr)
            print(exc.stderr, file=sys.stderr)
            sys.exit(exc.exit_code)
        except VerifyError as exc:
            print(f"erro: {exc}", file=sys.stderr)
            sys.exit(1)

        from harness.supervisor import on_feature_verified

        on_feature_verified(Path(args.dir), args.feature_id)

        data = json.loads(evidence_path.read_text(encoding="utf-8"))
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
                feature_list_data = json.loads(feature_list_path.read_text(encoding="utf-8"))
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
        data = json.loads(review_path.read_text(encoding="utf-8"))
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


if __name__ == "__main__":
    main()
