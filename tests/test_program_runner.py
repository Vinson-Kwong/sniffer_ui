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


def test_read_loop_logs_eof_reason():
    chan = FakeChannel([b"Last login: ...\n"])   # banner, then b"" (EOF)
    session = FakeSession()
    session.shell = chan
    outputs = []
    runner = ProgramRunner(session, on_output=outputs.append, on_ended=lambda: None)
    runner.start()
    _wait(runner)
    assert "远端关闭了连接" in "".join(outputs)


def test_read_loop_logs_exception_reason():
    class ErrChannel(FakeChannel):
        def recv(self, n):
            raise OSError("pipe broken")
    session = FakeSession()
    session.shell = ErrChannel()
    outputs = []
    runner = ProgramRunner(session, on_output=outputs.append, on_ended=lambda: None)
    runner.start()
    _wait(runner)
    joined = "".join(outputs)
    assert "通道异常" in joined
    assert "pipe broken" in joined


def test_start_uses_custom_command():
    chan = FakeChannel([b"output\n"])
    session = FakeSession()
    session.shell = chan
    runner = ProgramRunner(session, on_output=lambda s: None, on_ended=lambda: None)
    runner.start("sudo /opt/foo/run --x")
    _wait(runner)
    assert b"sudo /opt/foo/run --x\n" in chan.sent


def test_read_loop_strips_ansi_from_output():
    # The sniffer emits color codes via the PTY; they must not leak into the log.
    chan = FakeChannel([b"\x1b[1;34mcreated file\x1b[0m\n"])
    session = FakeSession()
    session.shell = chan
    outputs = []
    runner = ProgramRunner(session, on_output=outputs.append, on_ended=lambda: None)
    runner.start()
    _wait(runner)
    joined = "".join(outputs)
    assert "created file\n" in joined
    assert "\x1b" not in joined


def test_read_loop_survives_recv_timeouts():
    # A non-blocking/paced socket raises socket.timeout when no data has arrived
    # YET. The reader must retry, not treat it as a fatal error and exit.
    import socket

    class TimeoutyChannel:
        def __init__(self):
            self.sent = []
            self._n = 0
            self.closed = False

        def recv(self, n):
            self._n += 1
            if self._n <= 3:
                raise socket.timeout("no data yet")
            if self._n == 4:
                return b"sniffer running\n"
            return b""

        def send(self, d):
            if isinstance(d, str):
                d = d.encode()
            self.sent.append(d)
            return len(d)

        def send_ready(self):
            return True

        def exit_status_ready(self):
            return False

        def close(self):
            self.closed = True

    session = FakeSession()
    session.shell = TimeoutyChannel()
    outputs = []
    runner = ProgramRunner(session, on_output=outputs.append, on_ended=lambda: None)
    runner.start()
    _wait(runner)
    joined = "".join(outputs)
    assert "sniffer running\n" in joined          # survived the timeouts, got data
    assert "通道异常" not in joined                # timeout is not an error
    assert RUN_COMMAND.encode() in session.shell.sent




def test_stop_resets_state_and_ends_session_for_live_shell():
    # A live interactive shell (what invoke_shell actually is) does NOT EOF when
    # the foreground process dies. stop() must still reset state + close the
    # channel + fire on_ended, or the UI stays stuck on "停止".
    import threading
    import time

    class LiveChannel:
        def __init__(self):
            self.sent = []
            self._evt = threading.Event()
            self.closed = False

        def recv(self, n):
            self._evt.wait(timeout=5)
            return b""

        def send(self, data):
            if isinstance(data, str):
                data = data.encode()
            self.sent.append(data)
            return len(data)

        def send_ready(self):
            return True

        def exit_status_ready(self):
            return False

        def close(self):
            self.closed = True
            self._evt.set()

    class LiveSession(FakeSession):
        def open_shell(self):
            self.shell = LiveChannel()
            return self.shell

    ended = []
    session = LiveSession()
    runner = ProgramRunner(session, on_output=lambda s: None, on_ended=lambda: ended.append(True))
    runner.start()
    time.sleep(0.2)
    assert runner.is_running is True
    runner.stop()
    time.sleep(0.3)
    assert runner.is_running is False
    assert session.shell.closed is True
    assert ended == [True]

