"""Long-lived interactive shell for `sudo ~/ats/sniffer --bin`; stop = Ctrl+C (\\x03)."""
import socket
import threading

from core.ssh_session import strip_ansi

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
        self._ended = False

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._channel = self._session.open_shell()
            self._sudo_sent = False
            self._ended = False
            self._command_sent = False
            self._running = True
            self._thread = threading.Thread(target=self._read_loop, daemon=True)
            self._thread.start()
            # The run command is sent from the reader once the shell produces
            # its first output (= ready). Sending the instant invoke_shell()
            # returns can be lost on some SSH servers.

    def stop(self) -> None:
        """Send Ctrl+C to the foreground process, then end the session.

        The interactive shell stays open after the foreground process dies, so
        the reader loop would never see EOF and the UI would stay stuck on
        "停止". We close the channel and reset state here so the UI returns to
        idle (button -> 运行, other controls re-enabled)."""
        with self._lock:
            if not self._running or self._channel is None:
                return
            try:
                self._channel.send(CTRL_C)
            except Exception:
                pass
            try:
                self._channel.close()
            except Exception:
                pass
            self._running = False
        self._fire_ended()

    def _fire_ended(self) -> None:
        """Invoke on_ended exactly once per run (stop() and the reader race)."""
        with self._lock:
            if self._ended:
                return
            self._ended = True
        self._on_ended()

    def _read_loop(self) -> None:
        chan = self._channel
        buf = ""
        try:
            while True:
                try:
                    data = chan.recv(4096)
                except socket.timeout:
                    # Paced/non-blocking socket: no data arrived YET. Retry,
                    # do NOT exit (this was causing a false "immediate exit").
                    continue
                except Exception as e:
                    self._on_output(f"[运行] 通道异常: {type(e).__name__}: {e}\n")
                    break
                if not data:
                    self._on_output("[运行] 远端关闭了连接\n")
                    break
                text = strip_ansi(data.decode("utf-8", errors="replace"))
                buf += text
                # send the run command once the shell is ready (first output)
                if not self._command_sent:
                    self._command_sent = True
                    try:
                        chan.send(RUN_COMMAND.encode("utf-8"))
                    except Exception as e:
                        self._on_output(f"[运行] 发送命令失败: {type(e).__name__}: {e}\n")
                    else:
                        self._on_output("[运行] 已发送: sudo ~/ats/sniffer --bin\n")
                # feed the sudo password when prompted
                if not self._sudo_sent and "password" in buf.lower():
                    try:
                        chan.send((self._sudo_password + "\n").encode("utf-8"))
                    except Exception:
                        pass
                    self._sudo_sent = True
                self._on_output(text)
        finally:
            with self._lock:
                self._running = False
            self._fire_ended()
