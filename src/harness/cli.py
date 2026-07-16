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

    ana = sub.add_parser("analyze", help="Analisa o repo-alvo e grava .harness/repo-profile.json")
    ana.add_argument("--dir", default=".", help="Raiz do projeto-alvo")

    cc = sub.add_parser("compile-contract", help="Compila .harness/work/<slug> -> .harness/feature_list.json")
    cc.add_argument("--dir", default=".", help="Raiz do projeto-alvo")
    cc.add_argument("--slug", required=True, help="Identificador do contrato em .harness/work/<slug>")

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


if __name__ == "__main__":
    main()
