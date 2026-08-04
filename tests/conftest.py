"""Shared test fakes implementing the Session/Channel protocols in core/ssh_session.py."""
from __future__ import annotations

from pathlib import Path


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
        self.downloaded = []
        self.downloaded_dirs = []
        self.shell = None
        self.run_calls = []
        self.run_inputs = []
        self._run_results = []
        self.closed = False

    def connect(self, host, port, user, password, timeout=10.0):
        self.connect_args = (host, port, user, password)

    def run(self, command, timeout=30, input_data=""):
        self.run_calls.append(command)
        self.run_inputs.append(input_data)
        if self._run_results:
            return self._run_results.pop(0)
        return (0, "", "")

    def sftp_upload(self, local_path, remote_path):
        self.uploaded.append((local_path, remote_path))

    def sftp_download(self, remote_path, local_path, callback=None):
        self.downloaded.append((remote_path, local_path))
        Path(local_path).write_bytes(b"test data")
        if callback is not None:
            callback(9, 9)

    def sftp_download_dir(self, remote_path, local_parent):
        self.downloaded_dirs.append((remote_path, local_parent))
        return str(Path(local_parent) / remote_path.rstrip("/").split("/")[-1])

    def open_shell(self):
        return self.shell

    def close(self):
        self.closed = True
        self.connected = False

    # test helper
    def queue_run(self, code, out="", err=""):
        self._run_results.append((code, out, err))
