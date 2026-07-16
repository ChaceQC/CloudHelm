"""Workflow dispatcher/reclaimer Linux 进程入口。"""

from __future__ import annotations

import argparse
import signal
import threading

from cloudhelm_workflow_engine.broker import CeleryBrokerPublisher
from cloudhelm_workflow_engine.celery_app import celery_app
from cloudhelm_workflow_engine.config import get_workflow_settings
from cloudhelm_workflow_engine.database import get_session_factory
from cloudhelm_workflow_engine.dispatcher import WorkflowDispatcher
from cloudhelm_workflow_engine.stale_reclaimer import StaleReclaimer


def main() -> None:
    """解析子命令并运行可被 SIGTERM 停止的服务循环。"""

    parser = argparse.ArgumentParser(
        description="CloudHelm durable Workflow Engine"
    )
    parser.add_argument(
        "process",
        choices=("dispatcher", "reclaimer"),
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="只执行一个周期后退出。",
    )
    args = parser.parse_args()

    settings = get_workflow_settings()
    session_factory = get_session_factory()
    stop_event = threading.Event()
    _install_signal_handlers(stop_event)
    if args.process == "dispatcher":
        process = WorkflowDispatcher(
            settings=settings,
            session_factory=session_factory,
            publisher=CeleryBrokerPublisher(
                app=celery_app,
                settings=settings,
            ),
        )
    else:
        process = StaleReclaimer(
            settings=settings,
            session_factory=session_factory,
        )
    if args.once:
        process.run_once()
    else:
        process.run_forever(stop_event)


def _install_signal_handlers(stop_event: threading.Event) -> None:
    """把 SIGINT/SIGTERM 转为循环 stop_event。"""

    def stop(_signum, _frame) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
