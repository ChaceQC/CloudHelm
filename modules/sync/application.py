"""Current authorized sync reads on the control pool; no model/worker slots."""

from sqlalchemy import text

from database.uow import UnitOfWork
from modules.collaboration.errors import TaskBoundaryError
from modules.projects.queries import get_project
from modules.sync.dispatch import dispatch_pending, public_stream_id, read_batch, stream_head
from modules.sync.snapshot import build_snapshot


class SyncApplication:
    def __init__(self, engine, epoch):
        self.engine, self.epoch = engine, epoch

    def snapshot(self, actor, project_id):
        with UnitOfWork(self.engine) as uow:
            uow.connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
            project = get_project(uow, actor, project_id)
            head = stream_head(uow.connection, project_id)
            return build_snapshot(uow, actor, project, head, public_stream_id(head, self.epoch))

    def poll(self, actor, project_id, stream_id, after, permission_revision):
        with UnitOfWork(self.engine) as uow:
            project = get_project(uow, actor, project_id)
            if project.permission_revision != permission_revision:
                raise TaskBoundaryError("authorization_changed", status_code=409)
            head = stream_head(uow.connection, project_id, lock=True)
            if (stream_id != public_stream_id(head, self.epoch)
                    or not head["retained_from"] <= after <= head["last_cursor"]):
                raise TaskBoundaryError("snapshot_required", status_code=409)
            dispatch_pending(uow.connection, head)
            return read_batch(uow.connection, project_id, head, self.epoch, after)
