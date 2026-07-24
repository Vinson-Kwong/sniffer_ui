"""SSH transport wrapper + Session/Channel protocols the rest of the core depends on."""
from typing import Protocol

import paramiko


class Channel(Protocol):
    def recv(self, n: int) -> bytes: ...
    def send(self, data) -> int: ...
    def send_ready(self) -> bool: ...
    def exit_status_ready(self) -> bool: ...
    def close(self) -> None: ...


class Session(Protocol):
    connected: bool

    def connect(self, host: str, port: int, user: str, password: str, timeout: float = 10.0) -> None: ...
    def run(self, command: str, timeout: int = 30) -> "tuple[int, str, str]": ...
    def sftp_upload(self, local_path: str, remote_path: str) -> None: ...
    def open_shell(self) -> Channel: ...
    def close(self) -> None: ...


def decode_exec(stdout_bytes: bytes, stderr_bytes: bytes, exit_code: int) -> "tuple[int, str, str]":
    out = stdout_bytes.decode("utf-8", errors="replace")
    err = stderr_bytes.decode("utf-8", errors="replace")
    return exit_code, out, err


class SSHSession:
    """Concrete Session backed by paramiko."""

    def __init__(self) -> None:
        self._client: "paramiko.SSHClient | None" = None

    @property
    def connected(self) -> bool:
        if self._client is None:
            return False
        transport = self._client.get_transport()
        return transport is not None and transport.is_active()

    def connect(self, host, port, user, password, timeout=10.0) -> None:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            host,
            port=int(port),
            username=user,
            password=password,
            timeout=timeout,
            allow_agent=False,
            look_for_keys=False,
        )
        self._client = client

    def run(self, command: str, timeout: int = 30) -> "tuple[int, str, str]":
        if self._client is None:
            raise RuntimeError("not connected")
        _stdin, stdout, stderr = self._client.exec_command(command, timeout=timeout)
        out_bytes = stdout.read()
        err_bytes = stderr.read()
        code = stdout.channel.recv_exit_status()
        return decode_exec(out_bytes, err_bytes, code)

    def sftp_upload(self, local_path: str, remote_path: str) -> None:
        if self._client is None:
            raise RuntimeError("not connected")
        sftp = self._client.open_sftp()
        try:
            sftp.put(local_path, remote_path)
        finally:
            sftp.close()

    def open_shell(self):
        if self._client is None:
            raise RuntimeError("not connected")
        chan = self._client.invoke_shell()
        chan.settimeout(0.0)  # non-blocking recv for the reader loop
        return chan

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
