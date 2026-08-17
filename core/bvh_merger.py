"""Local BVH merge: copy the selected bvh into a folder as *_merge.bvh, then
run merge_app/mocap-merge.exe <folder> --verbose and stream its output."""
import shutil
import subprocess
import sys
import threading
from pathlib import Path


def merge_app_exe_path() -> Path:
    """merge_app/ lives next to the frozen exe, else at the repo root."""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parent.parent
    return base / "merge_app" / "mocap-merge.exe"


def merged_copy_name(bvh_path) -> str:
    """Destination filename inside the merge folder: <stem>_merge.bvh."""
    return f"{Path(bvh_path).stem}_merge.bvh"


def build_merge_command(exe_path, folder) -> list:
    return [str(exe_path), str(folder), "--verbose"]


def decode_output(raw: bytes) -> str:
    """mocap-merge may print UTF-8 or GBK (Chinese Windows); never crash."""
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


class BvhMerger:
    """Copies the bvh into the folder as <stem>_merge.bvh, then runs
    mocap-merge.exe <folder> --verbose, streaming output through `log`."""

    def __init__(self, schedule, log, exe_path=None):
        self._schedule = schedule
        self._log = log
        self._exe = Path(exe_path) if exe_path else merge_app_exe_path()

    def merge(self, folder, bvh_path, on_done):
        """Async entry point from the UI thread."""
        def work():
            try:
                self._merge_sync(folder, bvh_path)
                self._schedule(lambda: on_done(ok=True, error=None))
            except Exception as e:
                msg = str(e)  # bind before the lambda (except target is cleared on exit)
                self._log(f"[BVH融合失败] {e}\n")
                self._schedule(lambda: on_done(ok=False, error=msg))
        threading.Thread(target=work, daemon=True).start()

    def _merge_sync(self, folder, bvh_path):
        folder_path = Path(folder)
        if not folder_path.is_dir():
            raise ValueError(f"文件夹不存在: {folder}")
        src = Path(bvh_path)
        if not src.is_file():
            raise ValueError(f"BVH 文件不存在: {bvh_path}")
        if not self._exe.is_file():
            raise ValueError(f"未找到 {self._exe}")
        dest = folder_path / merged_copy_name(src)
        # dest may exist from an earlier run of this same feature: overwrite it.
        shutil.copy2(src, dest)
        self._log(f"[BVH融合] 已拷贝 {src.name} -> {dest}\n")
        self._log(f"[BVH融合] 执行: {self._exe.name} {folder_path} --verbose\n")
        proc = subprocess.Popen(
            build_merge_command(self._exe, folder_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        for raw in proc.stdout:
            self._log(decode_output(raw))
        code = proc.wait()
        self._log(f"[BVH融合] 退出码={code}\n")
        if code != 0:
            raise RuntimeError(f"mocap-merge 退出码={code}")
        self._log("[BVH融合] 完成\n")
