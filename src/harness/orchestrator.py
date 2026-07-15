"""AgentOrchestrator — o loop agêntico que amarra as 6 camadas.

Fluxo por turn:
    TokenBudget.enforce() -> EETEvaluator.evaluate() -> model.generate()
    -> tool_use? ApprovalPolicy.gate() -> ToolRegistry.dispatch() (sandbox)
    -> ExecutionTracer.record_*() -> resultado volta ao contexto -> repete.

Nenhuma chamada de ferramenta escapa do gate HITL; nenhuma execução escapa
do sandbox; nenhum turn escapa da telemetria.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Awaitable, Callable

import anthropic

from harness.config import HarnessConfig
from harness.context.manager import ContextManager
from harness.governance.approval import ApprovalPolicy
from harness.governance.budget import BudgetExceededError, SessionBudget, TokenBudget
from harness.governance.sandbox import SandboxEnvironment
from harness.routing.eet import EETEvaluator, TrajectoryStep
from harness.routing.router import ModelRouter, RoutingDecision
from harness.telemetry.tracer import ExecutionTracer
from harness.tools.filesystem import FileReadTool, FileWriteTool
from harness.tools.mcp_client import MCPClient
from harness.tools.registry import ToolExecutionError, ToolRegistry
from harness.tools.terminal import TerminalTool
from harness.verification.tdd_guard import TDDGuard
from harness.verification.tdd_loop import TDDCycle


class AgentOrchestrator:
    def __init__(
        self,
        config: HarnessConfig,
        repo_root: Path,
        *,
        approval_prompt: Callable[[str], Awaitable[bool]] | None = None,
        session_budget: SessionBudget | None = None,
    ) -> None:
        """`approval_prompt` é o ponto de injeção real do HITL (ex.: o
        ApprovalBroker de um cockpit) — substitui o `input()` de terminal.
        `session_budget` é um `SessionBudget` COMPARTILHADO entre tarefas
        (contrato: 1 AgentOrchestrator por tarefa; um TaskManager cria um
        único SessionBudget e injeta em cada instância). O `task_usage` fica
        sempre isolado por instância — sem clobber entre tarefas concorrentes."""
        self.config = config
        self.repo_root = repo_root.resolve()
        self._task_started = False  # backstop do contrato "1 tarefa por instância"

        # Camada 3 — contexto e memória
        self.context = ContextManager(config.context, self.repo_root)
        # Camada 4 — governança
        self.approval = ApprovalPolicy(config.governance.approval_policy, prompt_fn=approval_prompt)
        self.budget = TokenBudget(config.governance.budget, session=session_budget)
        # Camada 6 — routing e EET
        self.router = ModelRouter(config.routing)
        # Camada 1 — ferramentas
        self.registry = ToolRegistry()
        self.mcp = MCPClient()
        self._tdd_cycle = None    # setado por _register_core_tools (por tarefa)
        self._tdd_guard = None    # setado por _register_core_tools (Inc.5)

        self._client = anthropic.AsyncAnthropic()

    # ------------------------------------------------------------------

    async def run_task(
        self,
        task_description: str,
        *,
        task_id: str | None = None,
        tracer: ExecutionTracer | None = None,
    ) -> dict[str, Any]:
        """Executa uma tarefa completa dentro do harness. Retorna resumo
        (status, custo, trace_id) — insumo direto do relatório de ROI.

        `task_id`/`tracer` são o ponto de injeção para quem lança a tarefa
        de fora (ex.: um TaskManager de cockpit): criar o `ExecutionTracer`
        com um `task_id` conhecido ANTES de agendar esta corrotina permite
        seguir o arquivo `.jsonl` em tempo real desde o primeiro evento —
        sem isso, o trace_id só existiria depois que a tarefa terminasse."""
        # Contrato: 1 AgentOrchestrator por tarefa. A instância não é
        # reutilizável (ToolRegistry e MCPClient internos não reinicializam);
        # falhar cedo e claro é melhor que o ValueError críptico de "ferramenta
        # duplicada" no meio do _register_core_tools.
        if self._task_started:
            raise RuntimeError(
                "AgentOrchestrator não é reutilizável: 1 instância por tarefa. "
                "Crie um novo AgentOrchestrator (compartilhe orçamento via session_budget)."
            )
        self._task_started = True

        tracer = tracer or ExecutionTracer(self.config.telemetry, self.repo_root, task_id=task_id)
        eet = EETEvaluator(self.config.eet)
        decision = self.router.route(task_description)
        tracer.emit("routing", tier=decision.tier.value, model=decision.model,
                    rationale=decision.rationale)

        self.budget.reset_task()
        status = "unknown"

        try:
            async with SandboxEnvironment(self.config.sandbox, self.repo_root) as sandbox:
                tracer.emit("sandbox_started", container_id=sandbox.container_id)
                # Ferramentas ligadas a ESTE sandbox — Camada 1 + 2.
                self._register_core_tools(sandbox)
                await self._connect_mcp_servers(tracer)

                system_prompt = self.context.build_system_prompt(task_description)
                messages: list[dict[str, Any]] = [{"role": "user", "content": task_description}]

                try:
                    status = await self._agent_loop(
                        decision=decision,
                        system_prompt=system_prompt,
                        messages=messages,
                        tracer=tracer,
                        eet=eet,
                    )
                except BudgetExceededError as exc:
                    tracer.record_governance("budget_exceeded", str(exc))
                    status = "aborted_budget"
                finally:
                    await self.mcp.close()
                    tracer.emit("trace_end", status=status, roi=tracer.roi_summary())
        except asyncio.CancelledError:
            # A destruição do sandbox já foi tentada (blindada com asyncio.shield
            # + timeout) dentro de __aexit__ mesmo sob cancelamento — aqui só
            # registramos a governança antes de repropagar.
            tracer.record_governance(
                "cancelled", "Tarefa cancelada; destruição do sandbox tentada no __aexit__."
            )
            raise

        return {"status": status, "trace_id": tracer.trace_id, **tracer.roi_summary()}

    # ------------------------------------------------------------------

    async def _agent_loop(
        self,
        decision: RoutingDecision,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tracer: ExecutionTracer,
        eet: EETEvaluator,
    ) -> str:
        escalated = False
        while True:
            # Guardrails ANTES de gastar tokens.
            self.budget.enforce()
            verdict = eet.evaluate()
            if verdict.terminate:
                tracer.record_governance("eet_termination", verdict.reason)
                return "terminated_eet"

            # Confiança degradando mas ainda acima do limiar duro: escala para
            # um tier de modelo mais capaz antes de desistir. No máximo uma vez
            # por tarefa, para não ficar alternando (ping-pong) entre tiers.
            if not escalated and verdict.confidence < self.config.eet.escalate_confidence_threshold:
                old_tier = decision.tier.value
                decision = self.router.escalate(decision)
                escalated = True
                tracer.record_governance(
                    "model_escalated",
                    f"{old_tier}->{decision.tier.value} model={decision.model} "
                    f"confidence={verdict.confidence:.2f}",
                )

            with tracer.span("model_turn", model=decision.model):
                response = await self._client.messages.create(
                    model=decision.model,
                    max_tokens=self.config.generation.max_tokens,
                    system=system_prompt,
                    messages=messages,
                    tools=self.registry.to_api_format(),
                )

            usage = response.usage
            self.budget.record_model_turn(usage.input_tokens, usage.output_tokens)
            reasoning = "\n".join(
                block.text for block in response.content if block.type == "text"
            )
            tracer.record_model_turn(
                model=decision.model,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                reasoning=reasoning,
                stop_reason=response.stop_reason,
            )

            if response.stop_reason != "tool_use":
                return "completed"

            # Processa cada tool_use do turn.
            messages.append({"role": "assistant", "content": response.content})
            tool_results: list[dict[str, Any]] = []

            for block in response.content:
                if block.type != "tool_use":
                    continue
                result_payload = await self._execute_tool(
                    name=block.name, arguments=dict(block.input), tracer=tracer, eet=eet
                )
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result_payload, ensure_ascii=False, default=str),
                        "is_error": bool(result_payload.get("error")),
                    }
                )

            messages.append({"role": "user", "content": tool_results})

    # ------------------------------------------------------------------

    async def _execute_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        tracer: ExecutionTracer,
        eet: EETEvaluator,
    ) -> dict[str, Any]:
        try:
            spec = self.registry.get(name)
        except ToolExecutionError as exc:
            # Nome de ferramenta alucinado pelo modelo: vira erro estruturado
            # de volta ao contexto (autocorreção), nunca crash da tarefa.
            tracer.record_tool_call(name, arguments, str(exc), ok=False)
            eet.observe(TrajectoryStep(
                tool=name, arguments_digest=TrajectoryStep.digest(arguments),
                failed=True, failure_signature="unknown_tool", made_progress=False,
            ))
            return {"error": str(exc), **exc.payload}

        # Guardrail TDD — camada 2. Roda ANTES do gate HITL: bloqueia atalhos
        # (editar teste, rodar suíte fora da máquina de estados) mesmo que o
        # humano aprovasse a ferramenta em si. Chaveado por risk_class.
        if self._tdd_guard is not None:
            blocked = self._tdd_guard.check_pre_dispatch(spec.risk_class, arguments)
            if blocked:
                tracer.record_governance("tdd_guard_blocked", f"{name}: {blocked}")
                eet.observe(TrajectoryStep(
                    tool=name, arguments_digest=TrajectoryStep.digest(arguments),
                    failed=True, failure_signature="tdd_guard_blocked", made_progress=False,
                ))
                return {"error": blocked}

        # Gate HITL — camada 4. Rejeição humana volta como erro ao modelo.
        gate = await self.approval.gate(name, spec.risk_class, arguments)
        tracer.record_governance("hitl", f"{name}: {gate.reason}")
        if not gate.approved:
            eet.observe(TrajectoryStep(
                tool=name, arguments_digest=TrajectoryStep.digest(arguments),
                failed=True, failure_signature="hitl_rejected", made_progress=False,
            ))
            return {"error": f"Ação rejeitada pelo humano ({gate.reason}). Proponha alternativa."}

        self.budget.record_tool_call()
        try:
            result = await self.registry.dispatch(name, arguments)
            ok = not (isinstance(result, dict) and result.get("exit_code", 0) != 0)
            if self._tdd_guard is not None:
                self._tdd_guard.note_post_dispatch(spec.risk_class, arguments, ok)
            tracer.record_tool_call(name, arguments, str(result)[:500], ok=ok)
            eet.observe(TrajectoryStep(
                tool=name, arguments_digest=TrajectoryStep.digest(arguments),
                failed=not ok,
                failure_signature=self._failure_signature(result) if not ok else None,
                made_progress=ok and spec.risk_class in {"edit", "execute", "edit_test"},
            ))
            return result if isinstance(result, dict) else {"result": result}
        except ToolExecutionError as exc:
            tracer.record_tool_call(name, arguments, str(exc), ok=False)
            eet.observe(TrajectoryStep(
                tool=name, arguments_digest=TrajectoryStep.digest(arguments),
                failed=True, failure_signature=str(exc)[:120], made_progress=False,
            ))
            # Erro estruturado volta ao modelo -> autocorreção (Camada 1).
            return {"error": str(exc), **exc.payload}

    # ------------------------------------------------------------------

    def _register_core_tools(self, sandbox: SandboxEnvironment) -> None:
        terminal = TerminalTool(sandbox)
        self.registry.register_native(
            name=terminal.name,
            description=terminal.description,
            input_schema=terminal.input_schema,
            handler=terminal,
            risk_class=terminal.risk_class,
        )

        # Ferramentas discretas de arquivo — risk_class reflete o poder real
        # da ação (leitura nunca gateada, escrita gateada em paranoid/balanced),
        # ao contrário de run_terminal, que concentra tudo sob "execute".
        for tool in (FileReadTool(self.repo_root), FileWriteTool(self.repo_root)):
            self.registry.register_native(
                name=tool.name,
                description=tool.description,
                input_schema=tool.input_schema,
                handler=tool,
                risk_class=tool.risk_class,
            )

        # Camada 2 — o ciclo TDD exposto como ferramentas: o modelo não roda
        # a máquina de estados, ele PEDE transições; o harness valida.
        tdd = TDDCycle(
            sandbox=sandbox,
            workspace=self.repo_root,
            test_command=self.config.verification.test_command,
            test_glob=self.config.verification.test_glob,
            max_green_iterations=self.config.governance.budget.max_green_iterations,
        )
        self._tdd_cycle = tdd
        self._tdd_guard = TDDGuard(
            cycle=tdd,
            test_command=self.config.verification.test_command,
            enabled=self.config.verification.enforce_tdd,
        )

        async def tdd_assert_red() -> dict:
            result = await tdd.assert_red()
            return {"phase": tdd.phase.value, **result.to_model_payload()}

        async def tdd_try_green() -> dict:
            result = await tdd.try_green()
            return {"phase": tdd.phase.value, **result.to_model_payload()}

        async def tdd_assert_still_green() -> dict:
            result = await tdd.assert_still_green()
            return {"phase": tdd.phase.value, **result.to_model_payload()}

        async def tdd_finish() -> dict:
            tdd.finish()
            return {"phase": tdd.phase.value}

        async def tdd_request_test_edit() -> dict:
            # Só é chamado depois de risk_class="edit_test" ser aprovado pelo
            # humano (sempre gateado, ver _ALWAYS_GATED). O TDDGuard consome
            # este pedido concedendo um token de uso único ao write seguinte;
            # o re-hash real acontece DEPOIS da escrita (ver
            # TDDGuard.note_post_dispatch) para não congelar o conteúdo antigo.
            # self._tdd_guard é sempre setado logo acima nesta mesma função.
            self._tdd_guard.grant_test_edit_token()
            return {"phase": tdd.phase.value, "test_edit_token_granted": True}

        empty = {"type": "object", "properties": {}}
        self.registry.register_native(
            "tdd_assert_red",
            "Valida fase RED: roda a suíte e confirma que o teste novo FALHA. Obrigatório antes de implementar.",
            empty, tdd_assert_red, risk_class="execute",
        )
        self.registry.register_native(
            "tdd_try_green",
            "Fase GREEN: roda a suíte após implementação. Retorna stack traces em falha; repita até passar.",
            empty, tdd_try_green, risk_class="execute",
        )
        self.registry.register_native(
            "tdd_assert_still_green",
            "Fase REFACTOR: confirma que a suíte continua verde após uma melhoria de código.",
            empty, tdd_assert_still_green, risk_class="execute",
        )
        self.registry.register_native(
            "tdd_finish",
            "Encerra o ciclo TDD (fase REFACTOR -> DONE) quando a tarefa está completa.",
            empty, tdd_finish, risk_class="execute",
        )
        self.registry.register_native(
            "tdd_request_test_edit",
            "Solicita permissão para editar um arquivo de teste protegido durante GREEN/REFACTOR. "
            "SEMPRE exige aprovação humana explícita, em qualquer modo de política.",
            empty, tdd_request_test_edit, risk_class="edit_test",
        )

    async def _connect_mcp_servers(self, tracer: ExecutionTracer) -> None:
        if not self.config.mcp.allow_host_execution:
            tracer.emit("mcp_disabled", reason="host_execution_not_allowed")
            return
        for server in self.config.mcp.servers:
            try:
                count = await self.mcp.register_tools(server, self.registry)
                tracer.emit("mcp_connected", server=server.name, tools=count)
            except Exception as exc:  # noqa: BLE001 — servidor MCP indisponível não derruba a tarefa
                tracer.emit("mcp_failed", server=server.name, error=repr(exc))

    @staticmethod
    def _failure_signature(result: Any) -> str | None:
        if isinstance(result, dict):
            stderr = str(result.get("stderr", ""))
            return stderr.splitlines()[0][:120] if stderr else None
        return None
