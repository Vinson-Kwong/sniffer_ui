"""Shared test fakes implementing the Session/Channel protocols in core/ssh_session.py."""
from __future__ import annotations


class FakeChannel:
    """Scripted paramiko.Channel stand-in. recv() returns queued bytes, then b'' (EOF)."""

    def __init__(self, script=None):
        self._script = list(script or [])
        self.sent = []
        self.closed = False

    def recv(self, n):
        if not self._script:
            return b""
        return self._script.pop(0)

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


class FakeSession:
    """In-memory Session: scripts run() results in FIFO order, records calls."""

    def __init__(self):
        self.connected = True
        self.connect_args = None
        self.uploaded = []
        self.shell = None
        self.run_calls = []
        self._run_results = []
        self.closed = False

    def connect(self, host, port, user, password, timeout=10.0):
        self.connect_args = (host, port, user, password)

    def run(self, command, timeout=30):
        self.run_calls.append(command)
        if self._run_results:
            return self._run_results.pop(0)
        return (0, "", "")

    def sftp_upload(self, local_path, remote_path):
        self.uploaded.append((local_path, remote_path))

    def open_shell(self):
        return self.shell

    def close(self):
        self.closed = True
        self.connected = False

    # test helper
    def queue_run(self, code, out="", err=""):
        self._run_results.append((code, out, err))
