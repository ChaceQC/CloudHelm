"""One bounded SDK turn; durable execution receives identities and emits references."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime

from pydantic_ai.messages import ModelMessagesTypeAdapter
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from database.uow import UnitOfWork
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.command_support import lock_task_access
from modules.collaboration.guards import read_task
from modules.identity.actors import actor_for_command
from modules.identity.errors import IdentityError
from modules.tool_gateway.gateway import ToolGateway
from modules.workspaces.tables import workspaces
from pydantic_ai.tools import DeferredToolResults
from packages.contracts.p0.core_contracts import TurnResult
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p2.runtime import RuntimeStartRequest
from packages.contracts.p2.workspace_tools import WORKSPACE_TOOL_SCHEMAS
from packages.contracts.p2.workspace_edits import WORKSPACE_EDIT_SCHEMAS
from packages.contracts.p2.workspace_environment import WORKSPACE_ENVIRONMENT_SCHEMAS, WORKSPACE_ENVIRONMENT_WRITES
from packages.contracts.p2.workspace_builds import WORKSPACE_BUILD_SCHEMAS, WORKSPACE_BUILD_WRITES
from packages.contracts.p2.workspace_checks import WORKSPACE_CHECK_SCHEMAS
from .admission import RuntimeAdmission
from .billing import RuntimeBilling
from .context import load_context_in_uow
from .development import DevelopmentLoop, resolve_candidate_handoff_in_uow
from .source_context import safe_context_text
from .operations import (
    OperationGateway, load_deferred_results_in_uow, register_wait_in_uow,
    resume_ready_waits_in_uow,
)
from .registration import start_run
from .sdk import RuntimeFailure, TurnOutput, run_turn
from .tables import agent_histories, agent_model_requests, agent_runs, agent_sessions
from .workspace_tools import WorkspaceCodeGateway
from .workspace_edits import WorkspaceEditGateway
from .workspace_environment import WorkspaceEnvironmentGateway
from .workspace_builds import WorkspaceBuildGateway
from .workspace_checks import WorkspaceCheckGateway

EMPTY_HISTORY = "sha256:" + hashlib.sha256(b"[]").hexdigest()


class AgentRuntimeApplication:
    def __init__(self, engine, client, provider=None, *, source_loader=None, handoff_loader=None,
                 workspace_reader=None, workspace_editor=None, stage_workspace_content=None,
                 development_application=None, environment_log_reader=None,
                 build_definition_loader=None, build_result_reader=None, workspace_check_runner=None):
        self.engine, self.client, self.provider = engine, client, provider
        self.source_loader = source_loader
        self.handoff_loader = handoff_loader
        self.workspace_reader = workspace_reader
        self.workspace_editor, self.stage_workspace_content = workspace_editor, stage_workspace_content
        self.development_application, self.environment_log_reader = development_application, environment_log_reader
        self.build_definition_loader, self.build_result_reader = build_definition_loader, build_result_reader
        self.workspace_check_runner = workspace_check_runner

    def start(self, source_command_id, request: RuntimeStartRequest):
        if self.provider is None:
            raise TaskBoundaryError("agent_provider_not_configured")
        self.provider.check(request.policy)
        return start_run(self.engine, self.client, source_command_id, request)

    def advance_session(self, run_id):
        """Called only by the registered DBOS step. Never return raw SDK errors."""
        code = "agent_turn_failed"
        try:
            return asyncio.run(self._advance(run_id))
        except TaskBoundaryError as error:
            code = error.code
        except Exception:
            pass
        try:
            return self._finish(run_id, None, code)
        except Exception:
            pass
        # No caught exception (possibly containing provider material) is chained.
        raise RuntimeError("agent_state_commit_unconfirmed")

    async def _advance(self, run_id):
        admission = RuntimeAdmission(self.engine, run_id)
        request, goal, deadline = admission.begin()
        if self.provider is None:
            return self._finish(run_id, None, "agent_provider_not_configured")
        self.provider.check(request.policy)
        with UnitOfWork(self.engine) as uow:
            history_ref = request.runtime_input.committed_history
            if history_ref.digest == EMPTY_HISTORY:
                history = []
            else:
                value = uow.connection.scalar(select(agent_histories.c.value_json).where(
                    agent_histories.c.history_key == history_ref.digest,
                    agent_histories.c.session_id == request.runtime_input.session_id))
                if value is None:
                    raise TaskBoundaryError("agent_history_not_found")
                raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                if "sha256:" + hashlib.sha256(raw).hexdigest() != history_ref.digest:
                    raise TaskBoundaryError("agent_history_digest_mismatch")
                history = ModelMessagesTypeAdapter.validate_json(raw)
            deferred_results = load_deferred_results_in_uow(uow, run_id)
            request, context, prompt, instructions = load_context_in_uow(
                uow, run_id, self.source_loader, self.handoff_loader)

        async def task_read(arguments, tool_call_id):
            if arguments:
                raise TaskBoundaryError("task_read_arguments_invalid")
            with UnitOfWork(self.engine) as uow:
                task = read_task(uow.connection, request.runtime_input.task_id)
                workspace_id = uow.connection.scalar(select(workspaces.c.workspace_id).where(
                    workspaces.c.task_id == task["task_id"],
                    workspaces.c.work_item_id == request.context.work_item_id))
                return {"task_id": task["task_id"], "state": task["state"],
                        "goal": safe_context_text(goal), "work_item_goal": context["work_item_goal"],
                        "workspace_id": workspace_id, "human_changes": context["human_changes"]}

        operations = OperationGateway(self.engine, self.client)

        async def submit_operation(arguments, tool_call_id):
            return operations.submit_operation(run_id, tool_call_id, arguments)

        async def query_operation(arguments, tool_call_id):
            return operations.query_operation(run_id, arguments)

        async def await_operation(arguments, tool_call_id):
            return operations.await_operation(run_id, tool_call_id, arguments)

        routes = {"task.read": task_read, "submit_operation": submit_operation,
                  "query_operation": query_operation, "await_operation": await_operation}
        workspace_tools = WorkspaceCodeGateway(self.engine, self.workspace_reader)
        for name in WORKSPACE_TOOL_SCHEMAS:
            async def read_code(arguments, tool_call_id, route=name):
                return workspace_tools.query(run_id, route, arguments)

            routes[name] = read_code
        workspace_edits = WorkspaceEditGateway(self.engine, self.client,
            self.workspace_editor, self.stage_workspace_content)
        for name in WORKSPACE_EDIT_SCHEMAS:
            async def edit_code(arguments, tool_call_id, route=name):
                return workspace_edits.submit(run_id, tool_call_id, route, arguments)

            routes[name] = edit_code
        environments = WorkspaceEnvironmentGateway(self.engine, self.development_application,
                                                    self.environment_log_reader)
        for name in WORKSPACE_ENVIRONMENT_SCHEMAS:
            async def environment_tool(arguments, tool_call_id, route=name):
                if route in WORKSPACE_ENVIRONMENT_WRITES:
                    return environments.submit(run_id, tool_call_id, route, arguments)
                return environments.query(run_id, route, arguments)

            routes[name] = environment_tool
        builds = WorkspaceBuildGateway(self.engine, self.client,
                                       self.build_definition_loader, self.build_result_reader)
        for name in WORKSPACE_BUILD_SCHEMAS:
            async def build_tool(arguments, tool_call_id, route=name):
                if route in WORKSPACE_BUILD_WRITES:
                    return builds.submit(run_id, tool_call_id, route, arguments)
                return builds.query(run_id, route, arguments)

            routes[name] = build_tool
        checks = WorkspaceCheckGateway(self.engine, self.workspace_check_runner)
        for name in WORKSPACE_CHECK_SCHEMAS:
            async def check_workspace(arguments, tool_call_id):
                return checks.query(run_id, arguments)

            routes[name] = check_workspace
        developer = request.policy.role == "developer" and request.policy.instruction_revision == "agent-r2"
        loop = DevelopmentLoop(request.policy.max_no_progress_calls)
        if developer:
            for name, route in tuple(routes.items()):
                async def observed_tool(arguments, tool_call_id, route=route, name=name):
                    result = await route(arguments, tool_call_id)
                    loop.observe(name, arguments, tool_call_id, result)
                    return result

                routes[name] = observed_tool
        gateway = ToolGateway({name: routes[name] for name in request.context.tool_names}, admission.tool)
        failure = None
        try:
            output = await run_turn(model_name=request.policy.model_name, base_url=self.provider.base_url,
                api_key=self.provider.api_key(), prompt=prompt, message_history=history,
                max_requests=request.policy.max_requests, max_seconds=max(0, (deadline - datetime.now(UTC)).total_seconds()),
                max_output_tokens=request.policy.max_output_tokens, admit_request=admission.model_request,
                record_response=RuntimeBilling(self.engine).record, gateway=gateway,
                instructions=instructions,
                developer=developer, stop_reason=loop.stop_reason if developer else None,
                deferred_results=DeferredToolResults(calls=deferred_results) if deferred_results else None)
        except RuntimeFailure as error:
            failure = error.code
            output = TurnOutput(error.messages, None, stop_reason=error.code)
        raw = ModelMessagesTypeAdapter.dump_json([*history, *output.messages])
        # Canonical local representation is the history content identity.
        raw = json.dumps(json.loads(raw), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(raw) > 131072:
            return self._finish(run_id, None, "agent_history_limit")
        handoff = loop.handoff(output.handoff, output.stop_reason)
        return self._finish(run_id, raw, failure, output.deferred, handoff)

    def _finish(self, run_id, history, failure, deferred=None, handoff=None):
        with UnitOfWork(self.engine) as uow:
            stored = uow.connection.execute(select(agent_runs).where(
                agent_runs.c.run_id == run_id)).mappings().one()
            request = RuntimeStartRequest.model_validate(stored["start_json"])
            authorized = True
            try:
                actor = actor_for_command(uow, stored["source_command_id"])
                task, _ = lock_task_access(uow, actor, request.runtime_input.task_id, "task.command")
            except IdentityError:
                authorized = False
                task = read_task(uow.connection, request.runtime_input.task_id, for_update=True)
            session = uow.connection.execute(select(agent_sessions).where(
                agent_sessions.c.session_id == request.runtime_input.session_id).with_for_update()).mappings().one()
            run = uow.connection.execute(select(agent_runs).where(
                agent_runs.c.run_id == run_id).with_for_update()).mappings().one()
            if run["result_json"] is not None:
                return run["result_json"]
            current = (authorized and task["state"] == "active" and not task["ordinary_progress_closed"]
                and task["cancel_requested_at"] is None and task["input_status"] == "valid"
                and task["control_revision"] == request.runtime_input.expected_task_control_revision
                and task["input_validity_revision"] == request.runtime_input.expected_input_validity_revision)
            if current:
                from modules.workspaces.handoff_gates import active_handoff

                workspace_id = uow.connection.scalar(select(workspaces.c.workspace_id).where(
                    workspaces.c.task_id == task["task_id"], workspaces.c.work_item_id == request.context.work_item_id))
                current = workspace_id is None or active_handoff(uow.connection, workspace_id) is None
            key = request.runtime_input.committed_history.digest
            if history is not None:
                key = "sha256:" + hashlib.sha256(history).hexdigest()
                uow.connection.execute(pg_insert(agent_histories).values(history_key=key,
                    session_id=session["session_id"], value_json=json.loads(history)).on_conflict_do_nothing())
            ids = tuple(uow.connection.scalars(select(agent_model_requests.c.request_record_id).where(
                agent_model_requests.c.run_id == run_id).order_by(agent_model_requests.c.request_sequence)))
            reference = EngineeringRef(kind="history", object_id=session["session_id"], revision=str(session["version"] + 1),
                digest=key, digest_algorithm="sha256")
            if not current and handoff is not None:
                handoff = {**handoff, "reason": "agent_result_requires_review"}
            if current and handoff is not None:
                try:
                    with uow.connection.begin_nested():
                        resolve_candidate_handoff_in_uow(uow, run, request, handoff)
                except (TaskBoundaryError, IdentityError) as error:
                    handoff = {**handoff, "reason": error.code, "candidate_operation_id": None}
            delivery_refs = ()
            if current and handoff is not None and handoff["reason"] == "agent_candidate_ready":
                from .operations import _digest

                delivery_refs = (EngineeringRef(kind="delivery", object_id=run_id,
                    revision="agent-development-r1", authority="agent-runtime",
                    digest=_digest(handoff), digest_algorithm="sha256"),)
            paused = failure is not None or handoff is not None and handoff["reason"] not in {
                "agent_candidate_ready", "agent_continue_required", "request_limit_reached",
                "turn_limit_reached", "agent_request_limit", "agent_run_deadline_exceeded"}
            state = "failed" if failure else ("succeeded" if current else "interrupted")
            uow.connection.execute(update(agent_runs).where(agent_runs.c.run_id == run_id).values(
                state=state))
            uow.connection.execute(update(agent_sessions).where(agent_sessions.c.session_id == session["session_id"]).values(
                version=session["version"] + 1, state="idle" if current and not paused else "paused", history_key=key,
                epoch_id=request.policy.epoch_id))
            waits = ()
            if current and deferred is not None:
                try:
                    with uow.connection.begin_nested():
                        waits = tuple(register_wait_in_uow(uow, self.client, run_id, call.tool_call_id,
                            deferred.metadata[call.tool_call_id]["operation_id"]) for call in deferred.calls)
                except (IdentityError, TaskBoundaryError):
                    current, state = False, "interrupted"
                    uow.connection.execute(update(agent_runs).where(agent_runs.c.run_id == run_id).values(state=state))
                    uow.connection.execute(update(agent_sessions).where(
                        agent_sessions.c.session_id == session["session_id"]).values(state="paused"))
            turn = TurnResult(run_id=run_id, outcome="waiting_condition" if waits else
                "submitted" if delivery_refs else "continue_required",
                history_delta=reference, request_records=ids, wait_condition_refs=waits, delivery_refs=delivery_refs,
                reason_code=failure or ("agent_operation_waiting" if waits else
                    handoff["reason"] if current and handoff is not None else
                    "agent_turn_committed" if current else "agent_result_requires_review"))
            result = {"state": state, "turn": turn.model_dump(mode="json"),
                      "fenced_control_revision": task["control_revision"]}
            if handoff is not None:
                result["handoff"] = handoff
            uow.connection.execute(update(agent_runs).where(agent_runs.c.run_id == run_id).values(result_json=result))
            if current:
                resume_ready_waits_in_uow(uow, self.client, session["session_id"])
            return result
