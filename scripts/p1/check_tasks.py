"""Finite P1.1 Task integration checks; synthetic facts do not prove product delivery."""

from scripts.p1.database_fixture import DatabaseFixture
from scripts.p1.task_control_checks import run_completion_checks, run_operation_checks, run_submission_checks
from scripts.p1.task_fault_checks import run_fault_checks
from scripts.p1.task_fixture import TaskFixtureFailure
from scripts.p1.task_probe import TaskCheckFailure, TaskProbe, require
from scripts.p1.task_race_checks import run_race_checks
from scripts.p1.task_runtime_checks import run_runtime_checks


def run_checks(fixture: DatabaseFixture) -> dict[str, bool]:
    """Use one existing initialized fixture; all owned engines/processes close on exit."""
    probe = None
    scene = "task_fixture_setup_failed"
    try:
        require(isinstance(fixture, DatabaseFixture) and fixture.baseline is not None,
                "task_initialized_fixture_required")
        probe = TaskProbe(fixture)
        probe.open()
        checks = {}
        for scene, action in (
            ("task_submission_checks_failed", run_submission_checks),
            ("task_atomic_handoff_checks_failed", run_fault_checks),
            ("task_completion_checks_failed", run_completion_checks),
            ("task_operation_checks_failed", run_operation_checks),
            ("task_competing_command_checks_failed", run_race_checks),
            ("task_real_workflow_checks_failed", run_runtime_checks),
        ):
            checks.update(action(probe))
        return checks
    except (TaskCheckFailure, TaskFixtureFailure) as error:
        raise TaskCheckFailure(str(error)) from None
    except Exception:
        raise TaskCheckFailure(scene) from None
    finally:
        if probe is not None:
            probe.close()


if __name__ == "__main__":
    raise SystemExit("task_checks_require_shared_fixture")
