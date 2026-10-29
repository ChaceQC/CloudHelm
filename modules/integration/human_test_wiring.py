"""One composition for API commands and bounded worker maintenance."""

from modules.integration.human_test_repairs import create_human_test_repair
from modules.integration.human_tests import HumanTestApplication


def human_test_application(engine, control_engine, previews):
    return HumanTestApplication(engine, control_engine, prepare=previews.prepare_human,
        readiness=previews.readiness, stop=previews.stop_human, can_renew=previews.can_renew,
        create_repair=create_human_test_repair)
