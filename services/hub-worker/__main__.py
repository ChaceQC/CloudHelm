"""Run with python -B -m services.hub-worker; SIGTERM requests SDK shutdown."""

import argparse
import signal
import threading

from database.readiness import DatabaseNotReady
from database.settings import DatabaseConfigurationError
from database.uow import DatabaseFailure

from .process_lock import WorkerProcessLockError
from .runtime import WorkerRuntimeError, emit_status, run_worker


def main() -> int:
    parser = argparse.ArgumentParser(description="CloudHelm single local DBOS worker")
    parser.add_argument("--shutdown-grace-seconds", type=int, default=10,
                        help="SDK workflow drain budget, from 0 to 30 seconds (default: 10)")
    args = parser.parse_args()
    if not 0 <= args.shutdown_grace_seconds <= 30:
        parser.error("shutdown grace must be between 0 and 30 seconds")
    stop = threading.Event()
    background_failed = threading.Event()

    def request_stop(_signum, _frame) -> None:
        stop.set()

    def thread_failure(_args) -> None:
        background_failed.set()
        emit_status("failed", reason="worker_background_thread_failed")
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    threading.excepthook = thread_failure
    try:
        run_worker(stop, shutdown_grace_seconds=args.shutdown_grace_seconds)
        return 1 if background_failed.is_set() else 0
    except (DatabaseNotReady, DatabaseConfigurationError, DatabaseFailure,
            WorkerProcessLockError, WorkerRuntimeError) as failure:
        emit_status("rejected", reason=str(failure))
        return 1
    except Exception:
        emit_status("failed", reason="worker_start_or_shutdown_failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
