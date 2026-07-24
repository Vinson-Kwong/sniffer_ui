# Sniffer UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Windows desktop tool (CustomTkinter + paramiko) that connects to a robot over SSH, checks/uploads-decompresses/runs-stops/deletes the `~/ats/sniffer` program, with a real-time log and a config file that remembers the last-used parameters.

**Architecture:** Single-process GUI. Pure/testable core (`config_store`, `net_info`, `ssh_session`, `robot_controller`, `program_runner`) holds all SSH business logic and is unit-tested with fakes; a thin UI layer (`app.py`, `ui/`) marshals every SSH call onto worker threads and feeds results back to the Tk main loop via a thread-safe queue + `after()` polling. Run/Stop uses a persistent `invoke_shell()` channel; Stop sends `\x03` (Ctrl+C) on that same channel.

**Tech Stack:** Python 3.13, paramiko 5.0.0 (installed), CustomTkinter (to install), pytest + PyInstaller (to install).

**Reference spec:** `docs/superpowers/specs/2026-07-24-sniffer-ui-design.md`

## Global Constraints

- Python 3.13 on Windows; module entrypoint is `main.py`.
- SSH auth is **password only** (no keys): `paramiko` `connect(..., allow_agent=False, look_for_keys=False)`, host-key policy `AutoAddPolicy()`.
- Never call paramiko/SSH or touch Tk widgets from the UI (main) thread — all SSH in worker threads; all widget writes go through the marshalling queue.
- All user-facing strings are Chinese. All SSH exceptions caught and surfaced as readable Chinese log lines — no crashes, no native tracebacks to the user.
- Run command is exactly `sudo ~/ats/sniffer --bin`; the sudo password is the same as the login password (fed when `sudo` prompts).
- `config.json` lives **next to the exe** (next to `main.py` in dev); password stored **plaintext**.
- Program/decompress targets use literal `~/ats` (shell expands `~`); SFTP upload uses the absolute `$HOME` path.

---

## File Structure

```
sniffer_ui/  (repo root = E:\work\sniffer_ui)
├── main.py                  # Entrypoint: builds App, runs mainloop
├── app.py                   # App(ctk.CTk): UI build, thread marshalling, button handlers
├── config_store.py          # load_config()/save_config() — plain JSON, defaults
├── core/
│   ├── __init__.py
│   ├── net_info.py          # list_local_ipv4() via stdlib socket
│   ├── ssh_session.py       # SSHSession + Session/Channel Protocols + decode_exec()
│   ├── robot_controller.py  # RobotController + pure helpers (decompress/present parse)
│   └── program_runner.py    # ProgramRunner: interactive shell, Ctrl+C stop
├── ui/
│   ├── __init__.py
│   └── log_view.py          # LogView(ctk.CTkTextbox) — disabled-by-default, append()
├── tests/
│   ├── __init__.py
│   ├── conftest.py          # shared fakes: FakeSession, FakeChannel
│   ├── test_config_store.py
│   ├── test_net_info.py
│   ├── test_ssh_session.py
│   ├── test_robot_controller.py
│   └── test_program_runner.py
├── requirements.txt         # customtkinter, paramiko
├── requirements-dev.txt     # pytest, pyinstaller
├── sniffer_ui.spec          # PyInstaller spec (Task 11)
├── .gitignore
└── docs/...                 # spec + this plan (already present)
```

Responsibilities: `config_store` (persist params), `net_info` (enumerate local IPs), `ssh_session` (transport), `robot_controller` (one-shot business actions + pure command builders), `program_runner` (long-lived interactive channel), `app`/`ui` (presentation + threading).

---

## Task 1: Project scaffold

**Files:**
- Create: `requirements.txt`, `requirements-dev.txt`, `.gitignore`, `core/__init__.py`, `ui/__init__.py`, `tests/__init__.py`, `tests/conftest.py`

- [ ] **Step 1: Initialize git and create dependency files**

```bash
cd /e/work/sniffer_ui
git init -b main
```

`requirements.txt`:
```
customtkinter>=5.2.0
paramiko>=3.0.0
```

`requirements-dev.txt`:
```
-r requirements.txt
pytest>=8.0.0
pyinstaller>=6.0.0
```

`.gitignore`:
```
__pycache__/
*.pyc
.venv/
build/
dist/
config.json
```

- [ ] **Step 2: Create empty package init files**

`core/__init__.py`, `ui/__init__.py`, `tests/__init__.py` — each an empty file.

`tests/conftest.py` (shared fakes used by later tasks):
```python
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
```

- [ ] **Step 3: Install dependencies**

Run:
```bash
python -m pip install -r requirements-dev.txt
```
Expected: installs `customtkinter`, `paramiko` (already present, no-op), `pytest`, `pyinstaller`; exit code 0.

Verify:
```bash
python -m pytest --version
python -c "import customtkinter, paramiko; print('ok')"
python -m PyInstaller --version
```
Expected: a pytest version line, `ok`, a PyInstaller version line.

- [ ] **Step 4: Commit scaffold**

```bash
git add requirements.txt requirements-dev.txt .gitignore core ui tests docs feature.md
git commit -m "chore: project scaffold, deps, shared test fakes"
```

---

## Task 2: config_store

**Files:**
- Create: `config_store.py`
- Test: `tests/test_config_store.py`

**Interfaces:**
- Produces: `load_config(path=None) -> dict`, `save_config(cfg: dict, path=None) -> None`, `DEFAULTS` dict, `config_path() -> pathlib.Path`.

- [ ] **Step 1: Write the failing test**

`tests/test_config_store.py`:
```python
import json
from pathlib import Path

from config_store import DEFAULTS, load_config, save_config


def test_load_returns_defaults_when_file_missing(tmp_path):
    cfg = load_config(tmp_path / "config.json")
    assert cfg["target_ip"] == "192.168.1.111"
    assert cfg["username"] == "robot"
    assert cfg["password"] == "MangoTango"
    assert cfg["port"] == 22


def test_save_then_load_round_trips(tmp_path):
    p = tmp_path / "config.json"
    cfg = dict(DEFAULTS)
    cfg["target_ip"] = "10.0.0.5"
    cfg["password"] = "secret"
    save_config(cfg, p)
    loaded = load_config(p)
    assert loaded["target_ip"] == "10.0.0.5"
    assert loaded["password"] == "secret"


def test_corrupt_file_falls_back_to_defaults(tmp_path):
    p = tmp_path / "config.json"
    p.write_text("{ not valid json", encoding="utf-8")
    cfg = load_config(p)
    assert cfg["target_ip"] == "192.168.1.111"  # default restored


def test_load_merges_partial_file_over_defaults(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"target_ip": "1.2.3.4"}), encoding="utf-8")
    cfg = load_config(p)
    assert cfg["target_ip"] == "1.2.3.4"
    assert cfg["username"] == "robot"  # default kept for missing keys
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'config_store'`.

- [ ] **Step 3: Write minimal implementation**

`config_store.py`:
```python
"""Persisted application parameters (config.json next to the executable)."""
import json
import sys
from pathlib import Path
from typing import Optional

DEFAULTS = {
    "local_ip": "",
    "target_ip": "192.168.1.111",
    "port": 22,
    "username": "robot",
    "password": "MangoTango",
    "last_archive_dir": "",
}


def config_path() -> Path:
    """config.json lives next to the frozen exe, else next to this source file."""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parent
    return base / "config.json"


def load_config(path: Optional[Path] = None) -> dict:
    p = path or config_path()
    data = dict(DEFAULTS)
    if p.exists():
        try:
            with p.open("r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                data.update(loaded)
        except (json.JSONDecodeError, OSError):
            pass  # corrupt or unreadable -> use defaults
    return data


def save_config(cfg: dict, path: Optional[Path] = None) -> None:
    p = path or config_path()
    data = dict(DEFAULTS)
    data.update(cfg)
    with p.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config_store.py -v`
Expected: PASS — 4 passed.

- [ ] **Step 5: Commit**

```bash
git add config_store.py tests/test_config_store.py
git commit -m "feat: config_store load/save with defaults and corrupt-file recovery"
```

---

## Task 3: net_info (local IP enumeration)

**Files:**
- Create: `core/net_info.py`
- Test: `tests/test_net_info.py`

**Interfaces:**
- Produces: `list_local_ipv4() -> list[str]` (non-loopback IPv4, primary first, de-duplicated).

- [ ] **Step 1: Write the failing test**

`tests/test_net_info.py`:
```python
import socket

import core.net_info as net_info


def test_excludes_loopback_and_dedupes(monkeypatch):
    def fake_byname_ex(host):
        return (host, [], ["192.168.1.10", "192.168.1.10", "10.0.0.7"])

    def fake_gethostname():
        return "myhost"

    class FakeSock:
        def connect(self, *a, **k):
            pass

        def getsockname(self):
            return ("192.168.1.10", 0)

        def close(self):
            pass

    monkeypatch.setattr(socket, "gethostbyname_ex", fake_byname_ex)
    monkeypatch.setattr(socket, "gethostname", fake_gethostname)
    monkeypatch.setattr(socket, "socket", lambda *a, **k: FakeSock())

    addrs = net_info.list_local_ipv4()
    assert addrs[0] == "192.168.1.10"        # primary outbound IP first
    assert "10.0.0.7" in addrs
    assert "127.0.0.1" not in addrs
    assert len(addrs) == len(set(addrs))     # de-duplicated


def test_returns_empty_when_host_resolution_fails(monkeypatch):
    def raise_gaierror(*a, **k):
        raise socket.gaierror("nope")

    monkeypatch.setattr(socket, "gethostbyname_ex", raise_gaierror)

    class FakeSock:
        def connect(self, *a, **k):
            raise OSError("no route")

        def getsockname(self):
            return ("127.0.0.1", 0)

        def close(self):
            pass

    monkeypatch.setattr(socket, "socket", lambda *a, **k: FakeSock())
    assert net_info.list_local_ipv4() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_net_info.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.net_info'`.

- [ ] **Step 3: Write minimal implementation**

`core/net_info.py`:
```python
"""Enumerate this machine's non-loopback IPv4 addresses (stdlib only)."""
import socket


def list_local_ipv4() -> list[str]:
    addrs: list[str] = []
    seen: set[str] = set()

    def _add(ip: str) -> None:
        if ip and not ip.startswith("127.") and ip not in seen:
            seen.add(ip)
            addrs.append(ip)

    # 1) UDP "fake connect" reveals the primary outbound interface IP.
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            _add(s.getsockname()[0])
        finally:
            s.close()
    except OSError:
        pass

    # 2) gethostbyname_ex may surface additional interface IPs.
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            _add(ip)
    except socket.gaierror:
        pass

    return addrs
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_net_info.py -v`
Expected: PASS — 2 passed.

- [ ] **Step 5: Commit**

```bash
git add core/net_info.py tests/test_net_info.py
git commit -m "feat: enumerate local IPv4 addresses (stdlib, loopback-excluded)"
```

---

## Task 4: ssh_session (transport + Protocols)

**Files:**
- Create: `core/ssh_session.py`
- Test: `tests/test_ssh_session.py`

**Interfaces:**
- Produces: `Session` and `Channel` Protocols; `decode_exec(stdout_bytes, stderr_bytes, exit_code) -> tuple[int,str,str]`; class `SSHSession` with `connect(host,port,user,password,timeout=10.0)`, property `connected`, `run(command, timeout=30) -> (code,out,err)`, `sftp_upload(local, remote)`, `open_shell() -> Channel`, `close()`.

- [ ] **Step 1: Write the failing test**

`tests/test_ssh_session.py`:
```python
import paramiko

from core.ssh_session import SSHSession, decode_exec


def test_decode_exec_decodes_and_keeps_exit_code():
    assert decode_exec(b"hi\n", b"w", 0) == (0, "hi\n", "w")


def test_decode_exec_replaces_invalid_utf8():
    code, out, err = decode_exec(b"\xff\xfeok", b"", 1)
    assert code == 1
    assert "ok" in out  # invalid bytes replaced, no crash


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ssh_session.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.ssh_session'`.

- [ ] **Step 3: Write minimal implementation**

`core/ssh_session.py`:
```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_ssh_session.py -v`
Expected: PASS — 4 passed.

- [ ] **Step 5: Commit**

```bash
git add core/ssh_session.py tests/test_ssh_session.py
git commit -m "feat: SSHSession transport with password auth, exec, sftp, shell"
```

---

## Task 5: robot_controller — connect + program check

**Files:**
- Create: `core/robot_controller.py`
- Test: `tests/test_robot_controller.py`

**Interfaces:**
- Consumes: `Session` (from `core/ssh_session.py`); `FakeSession` (from `tests/conftest.py`).
- Produces: constants `PROGRAM_PATH`, `PROGRAM_CHECK_COMMAND`; pure `program_present_from_output(stdout) -> bool|None`; class `RobotController(session, schedule, log, sudo_password=None)` with `_connect_sync(host,port,user,password) -> bool|None`, `connect_and_check(host,port,user,password,on_done)`, `_check_program() -> bool|None`, `close()`.

- [ ] **Step 1: Write the failing test**

`tests/test_robot_controller.py` (continued in later tasks):
```python
from core.robot_controller import (
    PROGRAM_CHECK_COMMAND,
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_robot_controller.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.robot_controller'`.

- [ ] **Step 3: Write minimal implementation**

`core/robot_controller.py` (initial version; later tasks extend it):
```python
"""One-shot robot business actions (connect/check/upload/delete) + pure helpers."""
import threading

PROGRAM_PATH = "~/ats/sniffer"
REMOTE_DIR = "~/ats"
PROGRAM_CHECK_COMMAND = "test -f ~/ats/sniffer && echo __EXISTS__ || echo __MISSING__"

_PRESENT_TOKEN = "__EXISTS__"
_MISSING_TOKEN = "__MISSING__"


def program_present_from_output(stdout: str):
    if _PRESENT_TOKEN in stdout:
        return True
    if _MISSING_TOKEN in stdout:
        return False
    return None


class RobotController:
    def __init__(self, session, schedule, log, sudo_password=None):
        self._session = session
        self._schedule = schedule
        self._log = log
        self._sudo_password = sudo_password or (lambda: "")

    def close(self):
        try:
            self._session.close()
        except Exception:
            pass

    # ---- program check ----
    def _check_program(self):
        try:
            _code, out, _err = self._session.run(PROGRAM_CHECK_COMMAND)
        except Exception as e:
            self._log(f"[检查程序异常] {e}\n")
            return None
        present = program_present_from_output(out)
        label = "已存在" if present else ("不存在" if present is False else "未知")
        self._log(f"[程序检查] ~/ats/sniffer {label}\n")
        return present

    # ---- connect ----
    def _connect_sync(self, host, port, user, password):
        self._session.connect(host, int(port), user, password)
        self._log(f"[已连接] {user}@{host}:{port}\n")
        return self._check_program()

    def connect_and_check(self, host, port, user, password, on_done):
        def work():
            try:
                present = self._connect_sync(host, port, user, password)
                self._schedule(lambda: on_done(connected=True, present=present, error=None))
            except Exception as e:
                self._log(f"[连接失败] {e}\n")
                self._schedule(lambda: on_done(connected=False, present=None, error=str(e)))
        threading.Thread(target=work, daemon=True).start()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_robot_controller.py -v`
Expected: PASS — 3 passed.

- [ ] **Step 5: Commit**

```bash
git add core/robot_controller.py tests/test_robot_controller.py
git commit -m "feat: robot_controller connect + program-presence check"
```

---

## Task 6: robot_controller — upload + decompress

**Files:**
- Modify: `core/robot_controller.py` (add pure helper + `_upload_sync`/`upload_and_decompress`)
- Test: append to `tests/test_robot_controller.py`

**Interfaces:**
- Produces: pure `build_decompress_command(remote_archive_path) -> str|None`; `RobotController._upload_sync(local_path) -> bool|None` (raises on failure); `upload_and_decompress(local_path, on_done)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_robot_controller.py`:
```python
from core.robot_controller import build_decompress_command


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_robot_controller.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_decompress_command'`.

- [ ] **Step 3: Write minimal implementation**

Add to `core/robot_controller.py` (place `build_decompress_command` near the other module-level helpers, and the two methods inside `RobotController`):
```python
import os  # add to existing imports at top


def build_decompress_command(remote_archive_path: str):
    """Shell command to extract the archive into ~/ats/, or None if unsupported."""
    p = remote_archive_path.lower()
    dest = "~/ats/"
    if p.endswith(".tar.gz") or p.endswith(".tgz"):
        return f'tar -xzf "{remote_archive_path}" -C {dest}'
    if p.endswith(".tar"):
        return f'tar -xf "{remote_archive_path}" -C {dest}'
    if p.endswith(".zip"):
        return f'unzip -o "{remote_archive_path}" -d {dest}'
    return None
```

Inside `class RobotController`:
```python
    # ---- upload + decompress ----
    def _upload_sync(self, local_path):
        name = os.path.basename(local_path)
        cmd = build_decompress_command(f"~/ats/{name}")
        if cmd is None:
            raise ValueError(f"不支持的压缩格式: {name}")
        home = self._session.run("echo $HOME")[1].strip() or "~"
        abs_remote = f"{home}/ats/{name}"
        self._log(f"[上传] {name} -> ~/ats/\n")
        self._session.sftp_upload(local_path, abs_remote)
        self._log(f"[解压] {name}\n")
        code, _out, err = self._session.run(cmd)
        if code != 0:
            raise RuntimeError(f"解压失败 exit={code} {err.strip()}")
        return self._check_program()

    def upload_and_decompress(self, local_path, on_done):
        def work():
            try:
                present = self._upload_sync(local_path)
                self._schedule(lambda: on_done(ok=True, error=None, present=present))
            except Exception as e:
                self._log(f"[上传/解压失败] {e}\n")
                self._schedule(lambda: on_done(ok=False, error=str(e)))
        threading.Thread(target=work, daemon=True).start()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_robot_controller.py -v`
Expected: PASS — 7 passed total (3 prior + 4 new).

- [ ] **Step 5: Commit**

```bash
git add core/robot_controller.py tests/test_robot_controller.py
git commit -m "feat: upload + auto-decompress (tar.gz/tar/zip) with presence re-check"
```

---

## Task 7: robot_controller — delete

**Files:**
- Modify: `core/robot_controller.py` (add `_delete_sync`/`delete_program`)
- Test: append to `tests/test_robot_controller.py`

**Interfaces:**
- Produces: `RobotController._delete_sync() -> bool|None` (raises on failure); `delete_program(on_done)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_robot_controller.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_robot_controller.py -v`
Expected: FAIL — `AttributeError: 'RobotController' object has no attribute '_delete_sync'`.

- [ ] **Step 3: Write minimal implementation**

Inside `class RobotController`:
```python
    # ---- delete ----
    def _delete_sync(self):
        code, _out, err = self._session.run(f"rm -f {PROGRAM_PATH}")
        if code != 0:
            raise RuntimeError(f"删除失败 exit={code} {err.strip()}")
        self._log("[已删除] ~/ats/sniffer\n")
        return self._check_program()

    def delete_program(self, on_done):
        def work():
            try:
                present = self._delete_sync()
                self._schedule(lambda: on_done(ok=True, error=None, present=present))
            except Exception as e:
                self._log(f"[删除失败] {e}\n")
                self._schedule(lambda: on_done(ok=False, error=str(e)))
        threading.Thread(target=work, daemon=True).start()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_robot_controller.py -v`
Expected: PASS — 9 passed total.

- [ ] **Step 5: Commit**

```bash
git add core/robot_controller.py tests/test_robot_controller.py
git commit -m "feat: delete ~/ats/sniffer with presence re-check"
```

---

## Task 8: program_runner (interactive shell, Ctrl+C stop)

**Files:**
- Create: `core/program_runner.py`
- Test: `tests/test_program_runner.py`

**Interfaces:**
- Consumes: `Session.open_shell() -> Channel` (from Task 4); `FakeChannel` (from `tests/conftest.py`).
- Produces: constants `RUN_COMMAND="sudo ~/ats/sniffer --bin\n"`, `CTRL_C=b"\x03"`; class `ProgramRunner(session, on_output, on_ended, sudo_password="")` with `start()`, `stop()`, property `is_running`.

- [ ] **Step 1: Write the failing test**

`tests/test_program_runner.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_program_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.program_runner'`.

- [ ] **Step 3: Write minimal implementation**

`core/program_runner.py`:
```python
"""Long-lived interactive shell for `sudo ~/ats/sniffer --bin`; stop = Ctrl+C (\\x03)."""
import threading

RUN_COMMAND = "sudo ~/ats/sniffer --bin\n"
CTRL_C = b"\x03"


class ProgramRunner:
    def __init__(self, session, on_output, on_ended, sudo_password=""):
        self._session = session
        self._on_output = on_output
        self._on_ended = on_ended
        self._sudo_password = sudo_password if isinstance(sudo_password, str) else ""
        self._channel = None
        self._thread = None
        self._running = False
        self._lock = threading.Lock()
        self._sudo_sent = False

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._channel = self._session.open_shell()
            self._sudo_sent = False
            self._running = True
            self._thread = threading.Thread(target=self._read_loop, daemon=True)
            self._thread.start()
            self._channel.send(RUN_COMMAND.encode("utf-8"))

    def stop(self) -> None:
        with self._lock:
            if not self._running or self._channel is None:
                return
            self._channel.send(CTRL_C)

    def _read_loop(self) -> None:
        chan = self._channel
        buf = ""
        try:
            while True:
                try:
                    data = chan.recv(4096)
                except Exception:
                    break
                if not data:
                    break
                text = data.decode("utf-8", errors="replace")
                buf += text
                if not self._sudo_sent and "password" in buf.lower():
                    chan.send((self._sudo_password + "\n").encode("utf-8"))
                    self._sudo_sent = True
                self._on_output(text)
        finally:
            with self._lock:
                self._running = False
            self._on_ended()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_program_runner.py -v`
Expected: PASS — 3 passed.

- [ ] **Step 5: Commit**

```bash
git add core/program_runner.py tests/test_program_runner.py
git commit -m "feat: ProgramRunner interactive shell with live output and Ctrl+C stop"
```

---

## Task 9: ui/log_view (thread-safe log)

**Files:**
- Create: `ui/log_view.py`

**Interfaces:**
- Produces: `LogView(ctk.CTkTextbox)` with `append(text: str)` (disabled-by-default; only ever called on the UI thread via `App._log`/`schedule`).

**Note (no automated test):** This is a thin CustomTkinter widget; GUI widget testing is out of scope. Verified by the manual smoke test in Task 10.

- [ ] **Step 1: Write the implementation**

`ui/log_view.py`:
```python
"""Scrolling, read-only log console. append() is called only on the UI thread."""
import customtkinter as ctk


class LogView(ctk.CTkTextbox):
    def __init__(self, master, **kwargs):
        kwargs.setdefault("wrap", "word")
        kwargs.setdefault("font", ("Consolas", 12))
        super().__init__(master, **kwargs)
        self.configure(state="disabled")

    def append(self, text: str) -> None:
        self.configure(state="normal")
        self.insert("end", text)
        self.see("end")
        self.configure(state="disabled")

    def clear(self) -> None:
        self.configure(state="normal")
        self.delete("1.0", "end")
        self.configure(state="disabled")
```

- [ ] **Step 2: Smoke-check import (no display needed for import on Windows build envs; fails gracefully if no display)**

Run: `python -c "import ui.log_view; print('import ok')"`
Expected: prints `import ok` (customtkinter import works headless).

- [ ] **Step 3: Commit**

```bash
git add ui/log_view.py
git commit -m "feat: LogView read-only scrolling log console"
```

---

## Task 10: app + main window wiring (UI, threading, state)

**Files:**
- Create: `app.py`, `main.py`

**Interfaces:**
- Consumes: `config_store`, `core.net_info.list_local_ipv4`, `core.ssh_session.SSHSession`, `core.robot_controller.RobotController`, `core.program_runner.ProgramRunner`, `ui.log_view.LogView`.

**Note (no automated test):** UI/Threading integration. Verified by the manual smoke test below. All non-UI logic it depends on is already unit-tested in Tasks 2–8.

- [ ] **Step 1: Write app.py**

`app.py`:
```python
"""Main window: layout, worker-thread marshalling, button handlers."""
import os
import queue
import threading

import customtkinter as ctk
from tkinter import filedialog

from config_store import load_config, save_config
from core.net_info import list_local_ipv4
from core.ssh_session import SSHSession
from core.robot_controller import RobotController
from core.program_runner import ProgramRunner
from ui.log_view import LogView

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Sniffer 部署工具")
        self.geometry("760x680")
        self.minsize(660, 600)

        self._queue: "queue.Queue" = queue.Queue()
        self._last_dir = ""
        self._connected = False

        self.session = SSHSession()
        self.controller = RobotController(
            self.session,
            schedule=self._schedule,
            log=self._log,
            sudo_password=lambda: self.pw_entry.get(),
        )
        self.runner = ProgramRunner(
            self.session,
            on_output=self._log,
            on_ended=lambda: self._schedule(self._on_run_ended),
            sudo_password=lambda: self.pw_entry.get(),
        )

        self._build_ui()
        self._load_config_into_ui()
        self.after(100, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------- layout ----------------
    def _build_ui(self):
        pad = {"padx": 8, "pady": 6}

        conn = ctk.CTkFrame(self)
        conn.pack(fill="x", padx=12, pady=(12, 6))
        ctk.CTkLabel(conn, text="连接设置", font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", padx=8, pady=(6, 2))

        r1 = ctk.CTkFrame(conn, fg_color="transparent"); r1.pack(fill="x", **pad)
        ctk.CTkLabel(r1, text="本地IP:").pack(side="left")
        self.local_ip_var = ctk.StringVar()
        self.local_ip_box = ctk.CTkOptionMenu(r1, variable=self.local_ip_var, values=[], width=180)
        self.local_ip_box.pack(side="left", padx=8)
        ctk.CTkLabel(r1, text="端口:").pack(side="left", padx=(16, 0))
        self.port_entry = ctk.CTkEntry(r1, width=70); self.port_entry.insert(0, "22"); self.port_entry.pack(side="left", padx=8)

        r2 = ctk.CTkFrame(conn, fg_color="transparent"); r2.pack(fill="x", **pad)
        ctk.CTkLabel(r2, text="目标IP:").pack(side="left")
        self.target_entry = ctk.CTkEntry(r2, width=200); self.target_entry.pack(side="left", padx=8)
        ctk.CTkLabel(r2, text="用户名:").pack(side="left", padx=(16, 0))
        self.user_entry = ctk.CTkEntry(r2, width=120); self.user_entry.pack(side="left", padx=8)

        r3 = ctk.CTkFrame(conn, fg_color="transparent"); r3.pack(fill="x", **pad)
        ctk.CTkLabel(r3, text="密码:").pack(side="left")
        self.pw_entry = ctk.CTkEntry(r3, width=200, show="*"); self.pw_entry.pack(side="left", padx=8)
        self.pw_show_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(r3, text="显示", variable=self.pw_show_var, command=self._toggle_pw).pack(side="left", padx=8)
        self.connect_btn = ctk.CTkButton(r3, text="连接", width=100, command=self.on_connect)
        self.connect_btn.pack(side="left", padx=(16, 0))
        self.status_label = ctk.CTkLabel(r3, text="● 未连接", text_color="#e07b7b")
        self.status_label.pack(side="left", padx=12)

        deploy = ctk.CTkFrame(self); deploy.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(deploy, text="部署", font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", padx=8, pady=(6, 2))
        d1 = ctk.CTkFrame(deploy, fg_color="transparent"); d1.pack(fill="x", **pad)
        self.archive_entry = ctk.CTkEntry(d1, width=360); self.archive_entry.pack(side="left")
        ctk.CTkButton(d1, text="浏览", width=70, command=self.on_browse).pack(side="left", padx=8)
        self.upload_btn = ctk.CTkButton(d1, text="上传并解压", width=120, command=self.on_upload)
        self.upload_btn.pack(side="left", padx=8)
        self.check_label = ctk.CTkLabel(deploy, text="程序检查 ~/ats/sniffer: ❓ 未知")
        self.check_label.pack(anchor="w", padx=8, pady=(2, 6))

        runf = ctk.CTkFrame(self); runf.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(runf, text="运行", font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", padx=8, pady=(6, 2))
        rf1 = ctk.CTkFrame(runf, fg_color="transparent"); rf1.pack(fill="x", **pad)
        self.run_btn = ctk.CTkButton(rf1, text="运行", width=120, command=self.on_run_toggle)
        self.run_btn.pack(side="left")
        self.delete_btn = ctk.CTkButton(rf1, text="删除 ~/ats/sniffer", width=180,
                                        fg_color="#a33", hover_color="#922", command=self.on_delete)
        self.delete_btn.pack(side="left", padx=12)

        ctk.CTkLabel(self, text="日志", font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w", padx=16, pady=(8, 0))
        self.log_view = LogView(self, height=240)
        self.log_view.pack(fill="both", expand=True, padx=12, pady=(4, 12))

        self._refresh_controls()

    # ---------------- threading bridge ----------------
    def _schedule(self, fn):
        self._queue.put(fn)

    def _poll(self):
        try:
            while True:
                self._queue.get_nowait()()
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _log(self, text: str):
        self._schedule(lambda: self.log_view.append(text))

    # ---------------- config ----------------
    def _load_config_into_ui(self):
        cfg = load_config()
        self.target_entry.insert(0, cfg.get("target_ip", "192.168.1.111"))
        self.port_entry.delete(0, "end"); self.port_entry.insert(0, str(cfg.get("port", 22)))
        self.user_entry.insert(0, cfg.get("username", "robot"))
        self.pw_entry.insert(0, cfg.get("password", "MangoTango"))
        self._last_dir = cfg.get("last_archive_dir", "")
        self._refresh_local_ips(initial=cfg.get("local_ip", ""))

    def _refresh_local_ips(self, initial=""):
        ips = list_local_ipv4()
        if not ips:
            ips = [""]
        self.local_ip_box.configure(values=ips)
        chosen = initial if initial in ips else (ips[0] if ips else "")
        self.local_ip_var.set(chosen)

    def _persist_config(self):
        try:
            save_config({
                "local_ip": self.local_ip_var.get(),
                "target_ip": self.target_entry.get(),
                "port": int(self.port_entry.get() or 22),
                "username": self.user_entry.get(),
                "password": self.pw_entry.get(),
                "last_archive_dir": self._last_dir,
            })
        except Exception as e:
            self._log(f"[保存配置失败] {e}\n")

    # ---------------- helpers ----------------
    def _toggle_pw(self):
        self.pw_entry.configure(show="" if self.pw_show_var.get() else "*")

    def _set_status(self, connected: bool):
        self._connected = connected
        self.status_label.configure(
            text="● 已连接" if connected else "● 未连接",
            text_color="#7be08b" if connected else "#e07b7b",
        )

    def _set_check(self, present):
        if present is True:
            self.check_label.configure(text="程序检查 ~/ats/sniffer: ✅ 已存在", text_color="#7be08b")
        elif present is False:
            self.check_label.configure(text="程序检查 ~/ats/sniffer: ❌ 不存在", text_color="#e07b7b")
        else:
            self.check_label.configure(text="程序检查 ~/ats/sniffer: ❓ 未知", text_color="#cccccc")

    def _refresh_controls(self):
        running = self.runner.is_running
        self.connect_btn.configure(state="disabled" if running else "normal")
        ok = self._connected and not running
        self.upload_btn.configure(state="normal" if ok else "disabled")
        self.delete_btn.configure(state="normal" if ok else "disabled")
        self.run_btn.configure(state="normal" if self._connected else "disabled",
                               text="停止" if running else "运行")

    # ---------------- handlers ----------------
    def on_browse(self):
        path = filedialog.askopenfilename(
            initialdir=self._last_dir or None,
            filetypes=[("压缩包", "*.tar.gz *.tgz *.tar *.zip"), ("所有文件", "*.*")],
        )
        if path:
            self.archive_entry.delete(0, "end")
            self.archive_entry.insert(0, path)
            self._last_dir = os.path.dirname(path)

    def on_connect(self):
        host = self.target_entry.get().strip()
        if not host:
            self._log("[连接] 请填写目标IP\n"); return
        self.connect_btn.configure(state="disabled")
        self._log(f"[连接中] {host} ...\n")

        def done(connected, present, error):
            self._set_status(connected)
            self._set_check(present)
            if connected:
                self._log("[连接成功]\n")
            self._refresh_controls()

        self.controller.connect_and_check(
            host, self.port_entry.get(), self.user_entry.get(), self.pw_entry.get(), done
        )

    def on_upload(self):
        path = self.archive_entry.get().strip()
        if not path or not os.path.isfile(path):
            self._log("[上传] 请先选择有效的压缩包文件\n"); return
        self.upload_btn.configure(state="disabled")

        def done(ok, error, present=None):
            self._set_check(present)
            self._refresh_controls()

        self.controller.upload_and_decompress(path, done)

    def on_delete(self):
        self.delete_btn.configure(state="disabled")

        def done(ok, error, present=None):
            self._set_check(present)
            self._refresh_controls()

        self.controller.delete_program(done)

    def on_run_toggle(self):
        if self.runner.is_running:
            self.runner.stop()
            self._log("[停止] 已发送 Ctrl+C\n")
            return
        if not self.session.connected:
            self._log("[运行] 请先连接目标\n"); return
        self.run_btn.configure(state="disabled")

        def work():
            try:
                self.runner.start()
                self._schedule(self._refresh_controls)
            except Exception as e:
                self._log(f"[运行失败] {e}\n")
                self._schedule(self._refresh_controls)

        threading.Thread(target=work, daemon=True).start()

    def _on_run_ended(self):
        self._log("[运行结束]\n")
        self._refresh_controls()

    def _on_close(self):
        try:
            if self.runner.is_running:
                self.runner.stop()
        except Exception:
            pass
        self._persist_config()
        try:
            self.controller.close()
        except Exception:
            pass
        self.destroy()
```

- [ ] **Step 2: Write main.py**

`main.py`:
```python
"""Sniffer UI entrypoint."""
from app import App


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Syntax/import check**

Run: `python -c "import app; print('import ok')"`
Expected: prints `import ok`.

- [ ] **Step 4: Run full unit-test suite (regression guard)**

Run: `python -m pytest -q`
Expected: all tests from Tasks 2–8 PASS (no regressions from wiring).

- [ ] **Step 5: Manual smoke test**

Run: `python main.py`
Verify (requires a reachable robot or an SSH stub):
1. Window opens dark-themed, local-IP dropdown populated, target IP/username/password pre-filled from `config.json` (or defaults on first run).
2. Bad credentials → log shows `[连接失败] ...`, status stays red, no crash.
3. Valid connect → status green, `~/ats/sniffer` check shows ✅/❌.
4. Browse + 上传并解压 → log shows upload+decompress steps, check refreshes.
5. 运行 → button flips to 停止, sniffer output streams into the log; click 停止 → Ctrl+C sent, button returns to 运行.
6. 删除 → check becomes ❌.
7. Close window → `config.json` updated next to `main.py`; reopen → fields restored.

- [ ] **Step 6: Commit**

```bash
git add app.py main.py
git commit -m "feat: main window UI, threading bridge, and button handlers"
```

---

## Task 11: PyInstaller packaging

**Files:**
- Create: `sniffer_ui.spec`

- [ ] **Step 1: Generate and customize the spec**

Generate a base spec, then overwrite `sniffer_ui.spec` with the content below so CustomTkinter data files are bundled and `config.json` is written next to the exe (not into a temp dir).

Run: `python -m PyInstaller --onefile --windowed --name sniffer_ui --noconfirm main.py` (creates an initial spec + build artifacts to confirm packaging works).

Then replace `sniffer_ui.spec` with:
```python
# -*- mode: python ; coding: utf-8 -*-
import customtkinter
from PyInstaller.utils.hooks import collect_data_files

datas = []
datas += collect_data_files("customtkinter")

block_cipher = None

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=["customtkinter"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="sniffer_ui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    runtime_tmpdir=None,
    console=False,           # --windowed
    disable_windowed_traceback=False,
    icon=None,
)
```

- [ ] **Step 2: Build the single exe from the spec**

Run:
```bash
python -m PyInstaller sniffer_ui.spec --noconfirm --clean
```
Expected: finishes with `dist/sniffer_ui.exe` created; exit code 0.

- [ ] **Step 3: Verify the packaged exe**

Run: `dist/sniffer_ui.exe` (double-click or from terminal).
Verify:
1. App window opens (no console window).
2. On first close, `config.json` is created **next to `dist/sniffer_ui.exe`** (not in a temp `_MEI*` dir) — confirms `config_path()` uses `sys.frozen`/`sys.executable`.

- [ ] **Step 4: Commit**

```bash
git add sniffer_ui.spec
git commit -m "build: PyInstaller onefile/windowed spec bundling customtkinter"
```

---

## Self-Review Notes

- **Spec coverage:** §2 stack (T1 deps), §3 structure (file map + per-task files), §4 layout (T10), §5 state/threading (T10 `_poll`/`_refresh_controls` + controller/runner threads), §6.1 connect+check (T5), §6.2 upload+decompress (T6), §6.3 run/stop (T8 + T10 `on_run_toggle`), §6.4 delete (T7), §7 shell lifecycle (T8), §8 config (T2), §9 error handling (controller `try/except` in T5–T7 + UI guards `on_*`), §10 decisions (Global Constraints), §11 packaging (T11), §13 testing (T2–T8 unit + T10 smoke).
- **Placeholders:** none — every code step contains full code or exact commands.
- **Type consistency:** `Session`/`Channel` Protocols (T4) match `FakeSession`/`FakeChannel` (T1 conftest) and `SSHSession`/paramiko channel (T4); controller `_sync` method names (`_connect_sync`, `_upload_sync`, `_delete_sync`) and callback kwargs (`connected/present/error`, `ok/error/present`) are consistent across T5–T7 and the UI callbacks in T10.
```
