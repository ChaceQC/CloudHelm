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
from modules.collaboration.guards import read_task
from modules.collaboration.tables import work_items
from modules.tool_gateway.gateway import ToolGateway
from packages.contracts.p0.core_contracts import TurnResult
from packages.contracts.p0.engineering_contracts import EngineeringRef
from .admission import RuntimeAdmission
from .registration import start_run
from .sdk import RuntimeFailure, run_turn
from .tables import agent_histories, agent_model_requests, agent_runs, agent_sessions

EMPTY_HISTORY = "sha256:" + hashlib.sha256(b"[]").hexdigest()


class AgentRuntimeApplication:
    def __init__(self, engine, client, provider=None):
        self.engine, self.client, self.provider = engine, client, provider

    def start(self, source_command_id, request):
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
            item_goal = uow.connection.scalar(select(work_items.c.goal).where(
                work_items.c.work_item_id == request.context.work_item_id,
                work_items.c.task_id == request.runtime_input.task_id))

        async def task_read(arguments):
            if arguments:
                raise TaskBoundaryError("task_read_arguments_invalid")
            with UnitOfWork(self.engine) as uow:
                task = read_task(uow.connection, request.runtime_input.task_id)
                return {"task_id": task["task_id"], "state": task["state"],
                        "goal": goal, "work_item_goal": item_goal}

        gateway = ToolGateway({name: task_read for name in request.context.tool_names}, admission.tool)
        prompt = json.dumps({"task_goal": goal, "work_item_goal": item_goal,
            "requirement": request.context.requirement_ref.model_dump(mode="json"),
            "acceptance": request.context.acceptance_assets_ref.model_dump(mode="json"),
            "source": request.context.source_ref.model_dump(mode="json"),
            "tools": [{"name": name, "arguments": {}} for name in request.context.tool_names]}, ensure_ascii=False)
        try:
            result = await run_turn(model_name=request.policy.model_name, base_url=self.provider.base_url,
                api_key=self.provider.api_key(), prompt=prompt, message_history=history,
                max_requests=request.policy.max_requests, max_seconds=max(0, (deadline - datetime.now(UTC)).total_seconds()),
                max_output_tokens=request.policy.max_output_tokens, admit_request=admission.model_request,
                gateway=gateway)
        except RuntimeFailure as failure:
            return self._finish(run_id, None, failure.code)
        raw = ModelMessagesTypeAdapter.dump_json([*history, *result.new_messages])
        # Canonical local representation is the history content identity.
        raw = json.dumps(json.loads(raw), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(raw) > 131072:
            return self._finish(run_id, None, "agent_history_limit")
        return self._finish(run_id, raw, None)

    def _finish(self, run_id, history, failure):
        with UnitOfWork(self.engine) as uow:
            stored = uow.connection.execute(select(agent_runs.c.start_json).where(
                agent_runs.c.run_id == run_id)).scalar_one()
            from packages.contracts.p2.runtime import RuntimeStartRequest
            request = RuntimeStartRequest.model_validate(stored)
            task = read_task(uow.connection, request.runtime_input.task_id, for_update=True)
            session = uow.connection.execute(select(agent_sessions).where(
                agent_sessions.c.session_id == request.runtime_input.session_id).with_for_update()).mappings().one()
            run = uow.connection.execute(select(agent_runs).where(
                agent_runs.c.run_id == run_id).with_for_update()).mappings().one()
            if run["result_json"] is not None:
                return run["result_json"]
            current = (task["state"] == "active" and not task["ordinary_progress_closed"]
                and task["cancel_requested_at"] is None and task["input_status"] == "valid"
                and task["control_revision"] == request.runtime_input.expected_task_control_revision
                and task["input_validity_revision"] == request.runtime_input.expected_input_validity_revision)
            key = request.runtime_input.committed_history.digest
            if history is not None:
                key = "sha256:" + hashlib.sha256(history).hexdigest()
                uow.connection.execute(pg_insert(agent_histories).values(history_key=key,
                    session_id=session["session_id"], value_json=json.loads(history)).on_conflict_do_nothing())
            ids = tuple(uow.connection.scalars(select(agent_model_requests.c.request_record_id).where(
                agent_model_requests.c.run_id == run_id).order_by(agent_model_requests.c.request_sequence)))
            reference = EngineeringRef(kind="history", object_id=session["session_id"], revision=str(session["version"] + 1),
                digest=key, digest_algorithm="sha256")
            turn = TurnResult(run_id=run_id, outcome="continue_required", history_delta=reference,
                request_records=ids, reason_code=failure or ("agent_turn_committed" if current else "agent_result_requires_review"))
            result = {"state": "failed" if failure else ("succeeded" if current else "interrupted"),
                "turn": turn.model_dump(mode="json"), "fenced_control_revision": task["control_revision"]}
            uow.connection.execute(update(agent_runs).where(agent_runs.c.run_id == run_id).values(
                state=result["state"], result_json=result))
            uow.connection.execute(update(agent_sessions).where(agent_sessions.c.session_id == session["session_id"]).values(
                version=session["version"] + 1, state="idle" if current else "paused", history_key=key,
                epoch_id=request.policy.epoch_id))
            return result
