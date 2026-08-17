"""Local BVH merge: copy the selected bvh into a folder as *_merge.bvh, then
run mocap-merge on the folder and stream its output.

Runner selection (AV false positives hit the packed exe): prefer running the
mocap_merge source via `python -m mocap_merge` with PYTHONPATH pointing at
merge_app/src; fall back to merge_app/mocap-merge.exe (frozen builds, or when
the source tree is absent)."""
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path


def _app_base_dir() -> Path:
    """Resources live next to the frozen exe, else at the repo root."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def merge_app_exe_path() -> Path:
    return _app_base_dir() / "merge_app" / "mocap-merge.exe"


def mocap_merge_source_dir() -> Path:
    return _app_base_dir() / "merge_app" / "src"


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

    def __init__(self, schedule, log, exe_path=None, source_dir=None):
        self._schedule = schedule
        self._log = log
        self._exe = Path(exe_path) if exe_path else merge_app_exe_path()
        self._source_dir = Path(source_dir) if source_dir else mocap_merge_source_dir()

    def _resolve_runner(self):
        """(command_prefix, extra_env, must_exist_path_or_None).

        Source mode runs `python -m mocap_merge` — no packed exe for AV
        heuristics to flag. Only in a dev/source run; a frozen app has no
        interpreter, so it always uses the exe."""
        if not getattr(sys, "frozen", False) and \
                (self._source_dir / "mocap_merge" / "__init__.py").is_file():
            env = dict(os.environ)
            old = env.get("PYTHONPATH")
            env["PYTHONPATH"] = f"{self._source_dir}{os.pathsep}{old}" if old \
                else str(self._source_dir)
            return [sys.executable, "-m", "mocap_merge"], env, None
        return [str(self._exe)], None, self._exe

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
        prefix, env, must_exist = self._resolve_runner()
        if must_exist is not None and not must_exist.is_file():
            raise ValueError(
                f"未找到 {must_exist}（也可以把 mocap_merge 源码放到 {self._source_dir}）"
            )
        dest = folder_path / merged_copy_name(src)
        # dest may exist from an earlier run of this same feature: overwrite it.
        shutil.copy2(src, dest)
        self._log(f"[BVH融合] 已拷贝 {src.name} -> {dest}\n")
        self._log(f"[BVH融合] 执行: {' '.join(prefix)} {folder_path} --verbose\n")
        proc = subprocess.Popen(
            prefix + [str(folder_path), "--verbose"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
        )
        for raw in proc.stdout:
            self._log(decode_output(raw))
        code = proc.wait()
        self._log(f"[BVH融合] 退出码={code}\n")
        if code != 0:
            raise RuntimeError(f"mocap-merge 退出码={code}")
        self._log("[BVH融合] 完成\n")
