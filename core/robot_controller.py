"""One-shot robot business actions (connect/check/upload/delete) + pure helpers."""
import os
from pathlib import Path, PurePosixPath
import shlex
import threading
import uuid

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


def binary_path_from_command(command: str):
    """Best-effort: the binary path in a run command, for a pre-flight existence check.

    Skips a leading `sudo` and its dash-options, then returns the first remaining
    token if it looks like a path (contains '/'). Returns None for PATH commands
    (e.g. `ls`, `systemctl`) or unparseable input, so the caller can skip the check.
    """
    tokens = (command or "").strip().split()
    i = 0
    if i < len(tokens) and tokens[i] == "sudo":
        i += 1
        while i < len(tokens) and tokens[i].startswith("-"):
            i += 1
    if i < len(tokens) and "/" in tokens[i]:
        return tokens[i]
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

    def program_present_sync(self, path=PROGRAM_PATH):
        """Quick pre-flight: is the binary at `path` present? Used before running."""
        try:
            code, _out, _err = self._session.run(f"test -f {path}")
        except Exception as e:
            self._log(f"[检查程序异常] {e}\n")
            return False
        return code == 0

    def connect_and_check(self, host, port, user, password, on_done):
        def work():
            try:
                present = self._connect_sync(host, port, user, password)
                self._schedule(lambda: on_done(connected=True, present=present, error=None))
            except Exception as e:
                msg = str(e)  # bind before the lambda: the except target `e` is cleared on block exit (PEP 3110)
                self._log(f"[连接失败] {e}\n")
                self._schedule(lambda: on_done(connected=False, present=None, error=msg))
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
                msg = str(e)  # bind before the lambda (except target is cleared on block exit)
                self._log(f"[上传/解压失败] {e}\n")
                self._schedule(lambda: on_done(ok=False, error=msg))
        threading.Thread(target=work, daemon=True).start()

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
                msg = str(e)  # bind before the lambda (except target is cleared on block exit)
                self._log(f"[删除失败] {e}\n")
                self._schedule(lambda: on_done(ok=False, error=msg))
        threading.Thread(target=work, daemon=True).start()

    # ---- mocap data copy ----
    def _copy_mocap_sync(self, remote_path, local_parent, on_progress=None):
        remote_path = remote_path.strip().rstrip("/")
        remote_dir = PurePosixPath(remote_path)
        if not remote_path or not remote_dir.name:
            raise ValueError("尚未获取有效的 mocap 目录")

        local_parent = Path(local_parent).resolve()
        local_parent.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex
        remote_name = f".sniffer-mocap-{token}.tar.gz"
        local_name = f"{remote_dir.name}-{token}.tar.gz"
        remote_archive = str(remote_dir.parent / remote_name)
        local_archive = local_parent / local_name
        partial_archive = local_parent / f"{local_name}.part"

        quoted_path = shlex.quote(remote_path)
        quoted_archive = shlex.quote(remote_archive)
        quoted_parent = shlex.quote(str(remote_dir.parent))
        quoted_name = shlex.quote(remote_dir.name)
        copy_succeeded = False

        try:
            code, _out, err = self._session.run(
                f"test -d {quoted_path}", timeout=30
            )
            if code != 0:
                raise RuntimeError(f"mocap 目录不存在: {remote_path} {err.strip()}")

            self._log(f"[数据压缩] {remote_path}\n")
            code, _out, err = self._session.run(
                f"tar -czf {quoted_archive} -C {quoted_parent} {quoted_name}",
                timeout=3600,
            )
            if code != 0:
                raise RuntimeError(f"压缩失败 exit={code} {err.strip()}")

            self._log(f"[数据下载] {remote_archive} -> {local_archive}\n")
            self._session.sftp_download(
                remote_archive, str(partial_archive), callback=on_progress
            )
            partial_archive.replace(local_archive)
            copy_succeeded = True

            self._log(f"[数据拷贝完成] 压缩包已保存: {local_archive}\n")
            return str(local_archive)
        finally:
            try:
                cleanup_command = f"rm -f {quoted_archive}"
                input_data = ""
                if copy_succeeded:
                    cleanup_command += f" && sudo -S rm -rf -- {quoted_path}"
                    input_data = self._sudo_password() + "\n"
                code, _out, err = self._session.run(
                    cleanup_command, timeout=30, input_data=input_data
                )
                if code != 0:
                    self._log(f"[远端数据清理失败] {err.strip()}\n")
                elif copy_succeeded:
                    self._log(f"[远端数据已删除] {remote_path}\n")
            except Exception as e:
                self._log(f"[远端数据清理失败] {e}\n")
            try:
                partial_archive.unlink(missing_ok=True)
            except OSError as e:
                self._log(f"[本地临时文件清理失败] {e}\n")

    def copy_mocap_data(self, remote_path, local_parent, on_done,
                        on_progress=None):
        def progress(transferred, total):
            if on_progress is not None:
                self._schedule(
                    lambda transferred=transferred, total=total:
                    on_progress(transferred, total)
                )

        def work():
            try:
                archive_path = self._copy_mocap_sync(
                    remote_path, local_parent, progress
                )
                self._schedule(
                    lambda: on_done(ok=True, error=None,
                                    archive_path=archive_path)
                )
            except Exception as e:
                msg = str(e)
                self._log(f"[数据拷贝失败] {e}\n")
                self._schedule(
                    lambda: on_done(ok=False, error=msg, archive_path=None)
                )
        threading.Thread(target=work, daemon=True).start()
