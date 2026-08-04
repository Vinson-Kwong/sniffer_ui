import stat
from types import SimpleNamespace

import paramiko

from core.ssh_session import SSHSession, decode_exec, strip_ansi


def test_strip_ansi_removes_color_codes():
    assert strip_ansi("\x1b[1;34mcreated\x1b[0m file") == "created file"
    assert strip_ansi("\x1b[?25lhide\x1b[?25h") == "hide"
    assert strip_ansi("plain text") == "plain text"


def test_decode_exec_decodes_and_keeps_exit_code():
    assert decode_exec(b"hi\n", b"w", 0) == (0, "hi\n", "w")


def test_decode_exec_replaces_invalid_utf8():
    code, out, err = decode_exec(b"\xff\xfeok", b"", 1)
    assert code == 1
    assert "ok" in out  # invalid bytes replaced, no crash


def test_decode_exec_strips_ansi():
    code, out, err = decode_exec(b"\x1b[32mok\x1b[0m\n", b"\x1b[31mwarn\x1b[0m", 0)
    assert out == "ok\n"
    assert err == "warn"


def test_connect_uses_password_auth_and_autoadd(monkeypatch):
    captured = {}

    class FakeClient:
        def set_missing_host_key_policy(self, policy):
            captured["policy"] = policy

        def connect(self, host, **kw):
            captured["host"] = host
            captured["kw"] = kw

    monkeypatch.setattr(paramiko, "SSHClient", FakeClient)
    s = SSHSession()
    s.connect("1.2.3.4", 22, "robot", "MangoTango")
    assert captured["host"] == "1.2.3.4"
    assert captured["kw"]["username"] == "robot"
    assert captured["kw"]["password"] == "MangoTango"
    assert captured["kw"]["allow_agent"] is False
    assert captured["kw"]["look_for_keys"] is False
    assert isinstance(captured["policy"], paramiko.AutoAddPolicy)


class _FakeStream:
    def __init__(self, data=b""):
        self._data = data
        self.written = ""
        self.flushed = False

    def read(self):
        return self._data

    def write(self, data):
        self.written += data

    def flush(self):
        self.flushed = True


class _FakeStdout(_FakeStream):
    def __init__(self, data, code):
        super().__init__(data)
        self._code = code

    @property
    def channel(self):
        outer = self

        class _C:
            def recv_exit_status(self):
                return outer._code

        return _C()


class FakeExecClient:
    def __init__(self, out, err, code):
        self._in = _FakeStream()
        self._out = _FakeStdout(out, code)
        self._err = _FakeStream(err)

    def exec_command(self, command, timeout=None):
        return self._in, self._out, self._err


def test_run_decodes_output_and_exit_code():
    s = SSHSession()
    s._client = FakeExecClient(b"ok\n", b"warn", 0)
    code, out, err = s.run("echo ok")
    assert (code, out, err) == (0, "ok\n", "warn")


def test_run_writes_input_data_for_sudo():
    s = SSHSession()
    client = FakeExecClient(b"", b"", 0)
    s._client = client
    s.run("sudo -S rm -rf /tmp/data", input_data="MangoTango\n")
    assert client._in.written == "MangoTango\n"
    assert client._in.flushed is True


def test_sftp_download_gets_file_and_closes_client(tmp_path):
    class FakeSFTP:
        def __init__(self):
            self.get_calls = []
            self.closed = False

        def get(self, remote, local, callback=None):
            self.get_calls.append((remote, local, callback))
            if callback is not None:
                callback(25, 100)

        def close(self):
            self.closed = True

    sftp = FakeSFTP()
    session = SSHSession()
    session._client = SimpleNamespace(open_sftp=lambda: sftp)
    local = tmp_path / "data.tar.gz"
    progress = []

    session.sftp_download(
        "/remote/data.tar.gz", str(local), callback=lambda a, b: progress.append((a, b))
    )

    assert len(sftp.get_calls) == 1
    assert sftp.get_calls[0][:2] == ("/remote/data.tar.gz", str(local))
    assert progress == [(25, 100)]
    assert sftp.closed is True


def test_sftp_download_dir_recursively_downloads_files(tmp_path):
    directory_mode = stat.S_IFDIR | 0o755
    file_mode = stat.S_IFREG | 0o644

    class FakeSFTP:
        def __init__(self):
            self.get_calls = []
            self.closed = False

        def listdir_attr(self, path):
            entries = {
                "/remote/session-1": [
                    SimpleNamespace(filename="capture.bin", st_mode=file_mode),
                    SimpleNamespace(filename="nested", st_mode=directory_mode),
                ],
                "/remote/session-1/nested": [
                    SimpleNamespace(filename="meta.txt", st_mode=file_mode),
                ],
            }
            return entries[path]

        def get(self, remote, local):
            self.get_calls.append((remote, local))

        def close(self):
            self.closed = True

    sftp = FakeSFTP()
    client = SimpleNamespace(open_sftp=lambda: sftp)
    session = SSHSession()
    session._client = client

    destination = session.sftp_download_dir(
        "/remote/session-1/", str(tmp_path)
    )

    assert destination == str((tmp_path / "session-1").resolve())
    assert sftp.get_calls == [
        ("/remote/session-1/capture.bin", str(tmp_path / "session-1" / "capture.bin")),
        ("/remote/session-1/nested/meta.txt", str(tmp_path / "session-1" / "nested" / "meta.txt")),
    ]
    assert (tmp_path / "session-1" / "nested").is_dir()
    assert sftp.closed is True
