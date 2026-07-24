from core.program_runner import CTRL_C, RUN_COMMAND, ProgramRunner
from tests.conftest import FakeChannel, FakeSession


def _wait(reader):
    if reader._thread is not None:
        reader._thread.join(timeout=2)
        assert not reader._thread.is_alive(), "reader thread did not finish"


def test_start_sends_run_command_and_streams_output():
    chan = FakeChannel([b"sniffer started\n"])
    session = FakeSession()
    session.shell = chan
    outputs = []
    runner = ProgramRunner(session, on_output=outputs.append, on_ended=lambda: None)
    runner.start()
    _wait(runner)
    assert RUN_COMMAND.encode() in chan.sent
    assert "sniffer started\n" in "".join(outputs)
    assert runner.is_running is False  # ended after EOF


def test_start_feeds_sudo_password_when_prompted():
    chan = FakeChannel([b"[sudo] password for robot: "])
    session = FakeSession()
    session.shell = chan
    runner = ProgramRunner(session, on_output=lambda s: None, on_ended=lambda: None, sudo_password="MangoTango")
    runner.start()
    _wait(runner)
    assert b"MangoTango\n" in chan.sent


def test_stop_sends_ctrl_c():
    chan = FakeChannel()
    session = FakeSession()
    session.shell = chan
    runner = ProgramRunner(session, on_output=lambda s: None, on_ended=lambda: None)
    runner._running = True
    runner._channel = chan
    runner.stop()
    assert CTRL_C in chan.sent
