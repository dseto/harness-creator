"""Auditoria: avalia a estrutura de harness de um projeto-alvo.

Dogfooding deliberado: em vez de reimplementar as regras, o audit RECOMPILA
em memória (`compiler.render`) e compara com o que está em disco — qualquer
divergência é drift. Score 0-100 + findings estruturados (JSON), pensado
para a skill /harness-creator:audit apresentar e oferecer correção.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from harness.config import HarnessConfig
from harness.compiler import (
    AGENTS_BEGIN,
    AGENTS_END,
    HARNESS_YAML,
    HOOKS_DIR,
    render,
)
from harness.verification.tdd_loop import _glob_to_regex


@dataclass
class Finding:
    severity: str          # "critical" | "warning" | "info"
    code: str              # slug estável p/ máquina
    message: str           # frase p/ humano
    fix: str               # como corrigir

    def to_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "code": self.code,
                "message": self.message, "fix": self.fix}


@dataclass
class AuditReport:
    score: int
    findings: list[Finding] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"score": self.score, "findings": [f.to_dict() for f in self.findings]}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


_PENALTY = {"critical": 40, "warning": 15, "info": 5}

# Diretórios de build/vendor ignorados ao procurar arquivos de teste.
_SKIP_DIRS = {".harness", ".git", "__pycache__", ".venv", "node_modules",
              "bin", "obj", "target", "dist", "build"}


def audit_project(target_dir: Path) -> AuditReport:
    target_dir = target_dir.resolve()
    findings: list[Finding] = []

    # --- 1. harness.yaml existe e valida ---
    yaml_path = target_dir / HARNESS_YAML
    if not yaml_path.is_file():
        findings.append(Finding(
            "critical", "missing_harness_yaml",
            f"{HARNESS_YAML} não existe — projeto sem harness.",
            "Rode /harness-creator:init para criar a estrutura.",
        ))
        return _finish(findings)

    try:
        raw: dict[str, Any] = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        config = HarnessConfig.model_validate(raw)
    except (yaml.YAMLError, ValidationError) as exc:
        findings.append(Finding(
            "critical", "invalid_harness_yaml",
            f"harness.yaml inválido: {str(exc)[:200]}",
            "Corrija o YAML (schema: HarnessConfig) e rode `harness compile`.",
        ))
        return _finish(findings)

    expected = render(config, target_dir, raw_keys=set(raw))

    # --- 2. hooks presentes e com conteúdo esperado ---
    hooks_dir = target_dir / HOOKS_DIR
    for name, expected_content in expected.hook_files.items():
        path = hooks_dir / name
        if not path.is_file():
            findings.append(Finding(
                "critical", "missing_hook",
                f"Hook {name} ausente — a regra que ele enforça não vale em sessão.",
                "Rode `harness compile` para regenerar os hooks.",
            ))
        elif path.read_text(encoding="utf-8") != expected_content:
            findings.append(Finding(
                "warning", "hook_drift",
                f"Hook {name} difere do que o harness.yaml atual geraria.",
                "Rode `harness compile` (hooks não devem ser editados à mão).",
            ))

    # --- 3. settings.json coerente (permissions + hooks registrados) ---
    settings_path = target_dir / ".claude" / "settings.json"
    if not settings_path.is_file():
        findings.append(Finding(
            "critical", "missing_settings",
            ".claude/settings.json ausente — nenhuma permission/hook ativo.",
            "Rode `harness compile`.",
        ))
    else:
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            settings = None
            findings.append(Finding(
                "critical", "invalid_settings",
                ".claude/settings.json não é JSON válido.",
                "Corrija o arquivo ou apague e rode `harness compile`.",
            ))
        if settings is not None:
            perms = settings.get("permissions", {})
            for bucket, rules in expected.permission_rules.items():
                present = set(perms.get(bucket, []))
                missing = [r for r in rules if r not in present]
                if missing:
                    findings.append(Finding(
                        "warning", "permissions_drift",
                        f"Permissions '{bucket}' sem as regras: {', '.join(missing)}.",
                        "Rode `harness compile` para ressincronizar.",
                    ))
            registered = {
                h.get("command")
                for e in settings.get("hooks", {}).get("PreToolUse", [])
                for h in e.get("hooks", [])
            }
            for entry in expected.hook_entries:
                script = entry["hooks"][0]["command"]
                if script not in registered:
                    findings.append(Finding(
                        "critical", "hook_not_registered",
                        f"Hook não registrado no settings.json: {script}",
                        "Rode `harness compile`.",
                    ))

    # --- 4. AGENTS.md com bloco gerenciado ---
    agents_path = target_dir / "AGENTS.md"
    if not agents_path.is_file():
        findings.append(Finding(
            "warning", "missing_agents_md",
            "AGENTS.md ausente — agente sem diretrizes de governança no contexto.",
            "Rode `harness compile` para gerar o bloco.",
        ))
    else:
        text = agents_path.read_text(encoding="utf-8")
        if AGENTS_BEGIN not in text or AGENTS_END not in text:
            findings.append(Finding(
                "warning", "missing_agents_block",
                "AGENTS.md existe mas sem o bloco gerenciado do harness.",
                "Rode `harness compile` para inserir o bloco.",
            ))
        elif expected.agents_block not in text:
            findings.append(Finding(
                "info", "agents_block_drift",
                "Bloco do harness no AGENTS.md difere do harness.yaml atual.",
                "Rode `harness compile` para atualizar o bloco.",
            ))

    # --- 5. qualidade da política ---
    if config.governance.approval_policy == "auto":
        findings.append(Finding(
            "warning", "auto_policy",
            "Política 'auto' NÃO é read-only: edita arquivos e roda comandos "
            "sem aprovação humana.",
            "Prefira 'balanced' salvo autonomia total deliberada.",
        ))
    glob_regex = _glob_to_regex(config.verification.test_glob)
    has_test_files = any(
        glob_regex.match(rel.as_posix())
        for p in target_dir.rglob("*")
        if p.is_file()
        and not _SKIP_DIRS.intersection((rel := p.relative_to(target_dir)).parts)
    )
    if config.verification.enforce_tdd and not has_test_files:
        findings.append(Finding(
            "info", "no_test_files",
            f"Nenhum arquivo casa test_glob='{config.verification.test_glob}' — "
            "o guard de testes não protege nada ainda.",
            "Confirme o test_glob ou crie a suíte de testes.",
        ))
    for warning in expected.warnings:
        findings.append(Finding("info", "ignored_sections", warning,
                                "Remova as seções de execução do harness.yaml se não usar."))

    return _finish(findings)


def _finish(findings: list[Finding]) -> AuditReport:
    score = 100
    for f in findings:
        score -= _PENALTY.get(f.severity, 0)
    return AuditReport(score=max(0, score), findings=findings)
