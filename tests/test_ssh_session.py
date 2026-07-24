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

    def read(self):
        return self._data


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
        self._out = _FakeStdout(out, code)
        self._err = _FakeStream(err)

    def exec_command(self, command, timeout=None):
        return None, self._out, self._err


def test_run_decodes_output_and_exit_code():
    s = SSHSession()
    s._client = FakeExecClient(b"ok\n", b"warn", 0)
    code, out, err = s.run("echo ok")
    assert (code, out, err) == (0, "ok\n", "warn")
