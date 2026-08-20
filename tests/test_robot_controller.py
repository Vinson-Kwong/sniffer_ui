from pathlib import Path
import threading

from core.robot_controller import (
    PROGRAM_CHECK_COMMAND,
    build_decompress_command,
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


def test_decompress_command_dispatch():
    assert build_decompress_command("~/ats/a.tar.gz") == 'tar -xzf "$HOME/ats/a.tar.gz" -C ~/ats/'
    assert build_decompress_command("~/ats/a.TGZ") == 'tar -xzf "$HOME/ats/a.TGZ" -C ~/ats/'
    assert build_decompress_command("~/ats/a.tar") == 'tar -xf "$HOME/ats/a.tar" -C ~/ats/'
    assert build_decompress_command("~/ats/a.zip") == 'unzip -o "$HOME/ats/a.zip" -d ~/ats/'
    assert build_decompress_command("/abs/a.tar.gz") == 'tar -xzf "/abs/a.tar.gz" -C ~/ats/'
    assert build_decompress_command("~/ats/a.bin") is None


def test_decompress_command_never_quotes_bare_tilde():
    # A quoted "~" is NOT expanded by the shell (POSIX), so tar/unzip would look for a
    # literal '~' file and fail with "Cannot open: No such file or directory".
    # "$HOME" DOES expand inside double quotes, so that is what the command must use.
    for path in ("~/ats/a.tar.gz", "~/ats/a.tgz", "~/ats/a.tar", "~/ats/a.zip"):
        cmd = build_decompress_command(path)
        assert '"~' not in cmd, cmd
        assert '"$HOME/' in cmd, cmd


def test_upload_sync_uploads_to_abs_home_and_decompresses(tmp_path):
    s = FakeSession()
    s.queue_run(0, "/home/robot\n")   # echo $HOME
    s.queue_run(0, "")                # decompress command
    s.queue_run(0, "__EXISTS__\n")    # presence re-check
    c = _make(s)

    archive = tmp_path / "pkg.tar.gz"
    archive.write_bytes(b"x")
    present = c._upload_sync(str(archive))

    assert present is True
    assert s.uploaded == [(str(archive), "/home/robot/ats/pkg.tar.gz")]
    assert any(cmd.startswith("tar -xzf") for cmd in s.run_calls)


def test_upload_sync_unsupported_format_raises(tmp_path):
    s = FakeSession()
    c = _make(s)
    bad = tmp_path / "pkg.bin"
    bad.write_bytes(b"x")
    try:
        c._upload_sync(str(bad))
        assert False, "expected raise"
    except ValueError:
        pass
    assert s.uploaded == []  # nothing transferred


def test_upload_sync_decompress_failure_raises(tmp_path):
    s = FakeSession()
    s.queue_run(0, "/home/robot\n")   # HOME
    s.queue_run(1, "", "broken zip")  # decompress fails
    c = _make(s)
    archive = tmp_path / "pkg.zip"
    archive.write_bytes(b"x")
    try:
        c._upload_sync(str(archive))
        assert False, "expected raise"
    except RuntimeError:
        pass


def test_delete_sync_removes_and_rechecks():
    s = FakeSession()
    s.queue_run(0, "")               # rm
    s.queue_run(0, "__MISSING__\n")  # presence re-check
    c = _make(s)
    present = c._delete_sync()
    assert present is False
    assert any("rm -f ~/ats/sniffer" in cmd for cmd in s.run_calls)


def test_delete_sync_failure_raises():
    s = FakeSession()
    s.queue_run(1, "", "permission denied")
    c = _make(s)
    try:
        c._delete_sync()
        assert False, "expected raise"
    except RuntimeError:
        pass


def test_copy_mocap_sync_keeps_archive_and_reports_progress(tmp_path):
    s = FakeSession()
    logs = []
    progress = []
    c = RobotController(
        s, schedule=lambda f: f(), log=logs.append,
        sudo_password=lambda: "MangoTango",
    )
    archive_path = c._copy_mocap_sync(
        "/data/mocap/session-1", str(tmp_path),
        on_progress=lambda transferred, total: progress.append((transferred, total)),
    )

    final_archive = Path(archive_path)
    assert final_archive.parent == tmp_path.resolve()
    assert final_archive.name.startswith("session-1-")
    assert final_archive.name.endswith(".tar.gz")
    assert final_archive.read_bytes() == b"test data"
    assert not (tmp_path / "session-1").exists()
    assert len(s.downloaded) == 1
    remote_archive, partial_archive = s.downloaded[0]
    assert remote_archive.startswith("/data/mocap/.sniffer-mocap-")
    assert remote_archive.endswith(".tar.gz")
    assert partial_archive.endswith(".tar.gz.part")
    assert not Path(partial_archive).exists()
    assert progress == [(9, 9)]
    assert any(cmd.startswith("tar -czf ") for cmd in s.run_calls)
    cleanup = next(cmd for cmd in s.run_calls if cmd.startswith("rm -f "))
    assert "&& sudo -S rm -rf -- /data/mocap/session-1" in cleanup
    cleanup_index = s.run_calls.index(cleanup)
    assert s.run_inputs[cleanup_index] == "MangoTango\n"
    assert any("压缩包已保存" in line for line in logs)
    assert any("远端数据已删除" in line for line in logs)


def test_copy_mocap_sync_cleans_remote_archive_when_compression_fails(tmp_path):
    s = FakeSession()
    s.queue_run(0, "")
    s.queue_run(1, "", "disk full")
    c = _make(s)

    try:
        c._copy_mocap_sync("/data/mocap/session-1", str(tmp_path))
        assert False, "expected raise"
    except RuntimeError as e:
        assert "压缩失败" in str(e)

    cleanup = next(cmd for cmd in s.run_calls if cmd.startswith("rm -f "))
    assert "sudo -S rm -rf" not in cleanup
    assert list(tmp_path.glob(".sniffer-mocap-*.tar.gz")) == []


def test_copy_mocap_sync_rejects_empty_path(tmp_path):
    c = _make(FakeSession())
    try:
        c._copy_mocap_sync("", str(tmp_path))
        assert False, "expected raise"
    except ValueError:
        pass


def test_program_present_sync_reflects_exit_code():
    from core.robot_controller import PROGRAM_PATH

    present = FakeSession(); present.queue_run(0)   # `test -f` exits 0
    c = _make(present)
    assert c.program_present_sync() is True
    assert any(PROGRAM_PATH in cmd for cmd in present.run_calls)

    absent = FakeSession(); absent.queue_run(1)     # `test -f` exits 1
    assert _make(absent).program_present_sync() is False


def test_program_present_sync_false_on_error():
    class ErrSession(FakeSession):
        def run(self, command, timeout=30):
            raise OSError("link down")
    assert _make(ErrSession()).program_present_sync() is False


def test_program_present_sync_uses_given_path():
    s = FakeSession()
    s.queue_run(0)
    c = _make(s)
    assert c.program_present_sync("/opt/foo/run") is True
    assert any("/opt/foo/run" in cmd for cmd in s.run_calls)


def test_binary_path_from_command():
    from core.robot_controller import binary_path_from_command
    assert binary_path_from_command("sudo ~/ats/sniffer --bin") == "~/ats/sniffer"
    assert binary_path_from_command("sudo -E ~/ats/sniffer --bin") == "~/ats/sniffer"
    assert binary_path_from_command("~/ats/sniffer") == "~/ats/sniffer"
    assert binary_path_from_command("sudo /opt/foo/run") == "/opt/foo/run"
    assert binary_path_from_command("ls -la") is None
    assert binary_path_from_command("sudo systemctl status x") is None
    assert binary_path_from_command("") is None



def _capture_threads(monkeypatch):
    """Replace threading.Thread with a recording subclass so tests can join workers
    before draining the deferred callback queue (reproduces the real UI timing where
    the except block has already exited and the exception variable has been cleared)."""
    created = []

    class RecordingThread(threading.Thread):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            created.append(self)

    monkeypatch.setattr(threading, "Thread", RecordingThread)
    return created


def test_connect_failure_callback_survives_except_exit(monkeypatch):
    created = _capture_threads(monkeypatch)
    pending, results = [], []

    class BoomSession(FakeSession):
        def connect(self, *a, **k):
            raise OSError("boom")

    c = RobotController(BoomSession(), schedule=pending.append, log=lambda s: None)
    c.connect_and_check("1.2.3.4", 22, "u", "p", lambda **kw: results.append(kw))
    for t in created:
        t.join(timeout=2)
    for fn in pending:  # drained AFTER except block exited -> `e` already cleared
        fn()

    assert results == [{"connected": False, "present": None, "error": "boom"}]


def test_upload_failure_callback_survives_except_exit(monkeypatch, tmp_path):
    created = _capture_threads(monkeypatch)
    pending, results = [], []

    c = RobotController(FakeSession(), schedule=pending.append, log=lambda s: None)
    bad = tmp_path / "pkg.bin"
    bad.write_bytes(b"x")
    c.upload_and_decompress(str(bad), lambda **kw: results.append(kw))
    for t in created:
        t.join(timeout=2)
    for fn in pending:
        fn()

    assert len(results) == 1
    assert results[0]["ok"] is False
    assert "不支持的压缩格式" in results[0]["error"]


def test_delete_failure_callback_survives_except_exit(monkeypatch):
    created = _capture_threads(monkeypatch)
    pending, results = [], []

    s = FakeSession()
    s.queue_run(1, "", "denied")
    c = RobotController(s, schedule=pending.append, log=lambda s: None)
    c.delete_program(lambda **kw: results.append(kw))
    for t in created:
        t.join(timeout=2)
    for fn in pending:
        fn()

    assert len(results) == 1
    assert results[0]["ok"] is False
    assert "删除失败" in results[0]["error"]

