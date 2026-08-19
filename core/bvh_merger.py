"""Local BVH merge: extract the selected tar.gz archive to a temp dir,
copy the selected bvh in under its original name, run mocap-merge on the
extracted folder, then move the resulting <folder>_merge.bvh next to the
archive and clean up, streaming the tool's output.

Runner selection (AV false positives hit the packed exe):
- dev with merge_app/src present: `python -m mocap_merge` subprocess
  (isolation: a tool crash cannot take the UI down)
- package importable (bundled into the frozen exe): call cli.main() in-process
- last resort: merge_app/mocap-merge.exe subprocess"""
import contextlib
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
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


def copy_dest_name(bvh_path) -> str:
    """Destination filename inside the merge folder: the original name.

    mocap_merge discovers the optical bvh by filename suffix
    (*BDX.bvh / *BDX0709.bvh), so renaming the copy would hide it from
    the tool. A same-named stale copy is simply overwritten."""
    return Path(bvh_path).name


ARCHIVE_SUFFIXES = (".tar.gz", ".tgz")


def is_supported_archive(path) -> bool:
    """数据拷贝产出 tar.gz（远端 tar -czf）；BVH融合只接受这一族压缩包。"""
    return str(path).lower().endswith(ARCHIVE_SUFFIXES)


def merge_dir_in_extracted(root: Path) -> Path:
    """The folder mocap-merge runs on inside a fresh extraction `root`:
    the single top-level directory (数据拷贝 packs with -C <parent> <name>),
    or `root` itself for flat archives of loose files."""
    entries = list(root.iterdir())
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return root


def build_merge_command(exe_path, folder) -> list:
    return [str(exe_path), str(folder), "--verbose"]


def _import_cli():
    """The installed/bundled mocap_merge.cli, or None when not importable."""
    try:
        from mocap_merge import cli
    except Exception:
        return None
    return cli


class _LogStream:
    """file-like adapter routing print()/traceback output to the log callback."""

    def __init__(self, log):
        self._log = log
        self._buf = ""

    def write(self, text):
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._log(line + "\n")
        return len(text)

    def flush(self):
        if self._buf:
            self._log(self._buf + "\n")
            self._buf = ""


def decode_output(raw: bytes) -> str:
    """mocap-merge may print UTF-8 or GBK (Chinese Windows); never crash."""
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


class BvhMerger:
    """Extracts the tar.gz archive, copies the bvh in under its original
    name, runs mocap-merge on the extracted folder, copies the resulting
    <folder>_merge.bvh next to the archive, and cleans up the temp dir —
    streaming output through `log`."""

    def __init__(self, schedule, log, exe_path=None, source_dir=None,
                 allow_inprocess=True):
        self._schedule = schedule
        self._log = log
        self._exe = Path(exe_path) if exe_path else merge_app_exe_path()
        self._source_dir = Path(source_dir) if source_dir else mocap_merge_source_dir()
        self._allow_inprocess = allow_inprocess

    def _has_local_source(self) -> bool:
        if getattr(sys, "frozen", False):
            return False  # no interpreter next to a frozen app
        return (self._source_dir / "mocap_merge" / "__init__.py").is_file()

    def _runner_kind(self) -> str:
        """'python-subprocess' | 'inprocess' | 'exe'."""
        if self._has_local_source():
            return "python-subprocess"
        if self._allow_inprocess and _import_cli() is not None:
            return "inprocess"
        return "exe"

    def _resolve_runner(self):
        """(command_prefix, extra_env, must_exist_path_or_None) — subprocess
        runners only."""
        if self._has_local_source():
            env = dict(os.environ)
            old = env.get("PYTHONPATH")
            env["PYTHONPATH"] = f"{self._source_dir}{os.pathsep}{old}" if old \
                else str(self._source_dir)
            return [sys.executable, "-m", "mocap_merge"], env, None
        return [str(self._exe)], None, self._exe

    def _run_inprocess(self, folder_path) -> int:
        """Run mocap_merge.cli.main() inside this process (frozen builds:
        the package is bundled, so no exe and no interpreter are needed)."""
        cli = _import_cli()
        self._log(f"[BVH融合] 执行: mocap_merge.cli.main {folder_path} --verbose（进程内）\n")
        try:
            with contextlib.redirect_stdout(_LogStream(self._log)), \
                    contextlib.redirect_stderr(_LogStream(self._log)):
                return cli.main([str(folder_path), "--verbose"])
        except SystemExit as e:  # argparse --help / bad args
            return e.code if isinstance(e.code, int) else 1
        except Exception as e:
            self._log(f"{type(e).__name__}: {e}\n")
            return 1

    def merge(self, archive, bvh_path, on_done):
        """Async entry point from the UI thread."""

        def work():
            try:
                self._merge_sync(archive, bvh_path)
                self._schedule(lambda: on_done(ok=True, error=None))
            except Exception as e:
                msg = str(e)  # bind before the lambda (except target is cleared on exit)
                self._log(f"[BVH融合失败] {e}\n")
                self._schedule(lambda: on_done(ok=False, error=msg))
        threading.Thread(target=work, daemon=True).start()

    def _merge_sync(self, archive_path, bvh_path):
        archive = Path(archive_path)
        if not archive.is_file():
            raise ValueError(f"压缩包不存在: {archive_path}")
        if not is_supported_archive(archive):
            raise ValueError(f"仅支持 tar.gz/tgz 压缩包: {archive_path}")
        src = Path(bvh_path)
        if not src.is_file():
            raise ValueError(f"BVH 文件不存在: {bvh_path}")
        kind = self._runner_kind()
        if kind == "exe" and not self._exe.is_file():
            raise ValueError(
                f"未找到 {self._exe}（也可以 pip 安装 mocap_merge，"
                f"或把源码放到 {self._source_dir}）"
            )
        with tempfile.TemporaryDirectory(prefix="bvh-merge-") as tmp:
            extract_root = Path(tmp)
            self._log(f"[BVH融合] 解压 {archive.name} → 临时目录\n")
            with tarfile.open(archive, mode="r:gz") as tar:
                tar.extractall(extract_root, filter="data")
            folder_path = merge_dir_in_extracted(extract_root)
            self._log(f"[BVH融合] 融合文件夹: {folder_path}\n")
            dest = folder_path / copy_dest_name(src)
            # dest may be a stale copy packed inside the archive:
            # overwriting it is an update of the same logical input.
            shutil.copy2(src, dest)
            self._log(f"[BVH融合] 已拷贝 {src.name} -> {dest}\n")

            if kind == "inprocess":
                code = self._run_inprocess(folder_path)
            else:
                prefix, env, _must_exist = self._resolve_runner()
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
            produced = folder_path / f"{folder_path.name}_merge.bvh"
            if not produced.is_file():
                raise FileNotFoundError(f"融合成功但未找到产物: {produced}")
            saved = archive.parent / produced.name
            shutil.copy2(produced, saved)  # stale product from an earlier run: overwrite
            self._log(f"[BVH融合] 产物已保存: {saved}\n")
            self._log("[BVH融合] 完成\n")
