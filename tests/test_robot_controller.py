from core.robot_controller import (
    PROGRAM_CHECK_COMMAND,
    program_present_from_output,
    RobotController,
)
from tests.conftest import FakeSession


def _make(session):
    return RobotController(session, schedule=lambda f: f(), log=lambda s: None)


def test_present_parse_tokens():
    assert program_present_from_output("__EXISTS__\n") is True
    assert program_present_from_output("__MISSING__\n") is False
    assert program_present_from_output("garbage") is None


def test_connect_sync_returns_presence_and_records_connect():
    s = FakeSession()
    s.queue_run(0, "__EXISTS__\n")  # result of PROGRAM_CHECK_COMMAND
    c = _make(s)
    present = c._connect_sync("192.168.1.111", 22, "robot", "MangoTango")
    assert s.connect_args == ("192.168.1.111", 22, "robot", "MangoTango")
    assert PROGRAM_CHECK_COMMAND in s.run_calls
    assert present is True


def test_connect_sync_raises_on_connect_failure():
    class BoomSession(FakeSession):
        def connect(self, *a, **k):
            raise OSError("refused")
    c = _make(BoomSession())
    try:
        c._connect_sync("1.2.3.4", 22, "robot", "pw")
        assert False, "expected raise"
    except OSError:
        pass
