"""SSH transport wrapper + Session/Channel protocols the rest of the core depends on."""
import posixpath
import re
import stat
from pathlib import Path
from typing import Protocol

import paramiko

# ANSI/VT100 CSI escape sequences (color, cursor, etc.) -- programs emit these
# when attached to a PTY; we strip them so the log shows clean text.
_ANSI_RE = re.compile(r"\x1B\[[0-9;?]*[a-zA-Z]")


def strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


class Channel(Protocol):
    def recv(self, n: int) -> bytes: ...
    def send(self, data) -> int: ...
    def send_ready(self) -> bool: ...
    def exit_status_ready(self) -> bool: ...
    def close(self) -> None: ...


class Session(Protocol):
    connected: bool

    def connect(self, host: str, port: int, user: str, password: str, timeout: float = 10.0) -> None: ...
    def run(self, command: str, timeout: int = 30,
            input_data: str = "") -> "tuple[int, str, str]": ...
    def sftp_upload(self, local_path: str, remote_path: str) -> None: ...
    def sftp_download(self, remote_path: str, local_path: str,
                      callback=None) -> None: ...
    def sftp_download_dir(self, remote_path: str, local_parent: str) -> str: ...
    def open_shell(self) -> Channel: ...
    def close(self) -> None: ...


def decode_exec(stdout_bytes: bytes, stderr_bytes: bytes, exit_code: int) -> "tuple[int, str, str]":
    out = strip_ansi(stdout_bytes.decode("utf-8", errors="replace"))
    err = strip_ansi(stderr_bytes.decode("utf-8", errors="replace"))
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

    def run(self, command: str, timeout: int = 30,
            input_data: str = "") -> "tuple[int, str, str]":
        if self._client is None:
            raise RuntimeError("not connected")
        stdin, stdout, stderr = self._client.exec_command(command, timeout=timeout)
        if input_data:
            stdin.write(input_data)
            stdin.flush()
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

    def sftp_download(self, remote_path: str, local_path: str,
                      callback=None) -> None:
        if self._client is None:
            raise RuntimeError("not connected")
        sftp = self._client.open_sftp()
        try:
            sftp.get(remote_path, local_path, callback=callback)
        finally:
            sftp.close()

    def sftp_download_dir(self, remote_path: str, local_parent: str) -> str:
        if self._client is None:
            raise RuntimeError("not connected")
        remote_path = remote_path.rstrip("/")
        name = posixpath.basename(remote_path)
        if not name:
            raise ValueError("远端目录无效")
        destination = Path(local_parent).resolve() / name
        sftp = self._client.open_sftp()
        try:
            self._download_tree(sftp, remote_path, destination)
        finally:
            sftp.close()
        return str(destination)

    def _download_tree(self, sftp, remote_dir: str, local_dir: Path) -> None:
        local_dir.mkdir(parents=True, exist_ok=True)
        for entry in sftp.listdir_attr(remote_dir):
            remote_item = posixpath.join(remote_dir, entry.filename)
            local_item = local_dir / entry.filename
            if stat.S_ISDIR(entry.st_mode):
                self._download_tree(sftp, remote_item, local_item)
            else:
                sftp.get(remote_item, str(local_item))

    def open_shell(self):
        if self._client is None:
            raise RuntimeError("not connected")
        chan = self._client.invoke_shell()
        chan.settimeout(1.0)  # paced recv: the reader retries on socket.timeout
        return chan

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
