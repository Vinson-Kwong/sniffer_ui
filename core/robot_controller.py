"""One-shot robot business actions (connect/check/upload/delete) + pure helpers."""
import os
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
