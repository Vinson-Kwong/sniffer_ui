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
    assert build_decompress_command("~/ats/a.tar.gz") == 'tar -xzf "~/ats/a.tar.gz" -C ~/ats/'
    assert build_decompress_command("~/ats/a.TGZ") == 'tar -xzf "~/ats/a.TGZ" -C ~/ats/'
    assert build_decompress_command("~/ats/a.tar") == 'tar -xf "~/ats/a.tar" -C ~/ats/'
    assert build_decompress_command("~/ats/a.zip") == 'unzip -o "~/ats/a.zip" -d ~/ats/'
    assert build_decompress_command("~/ats/a.bin") is None


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
