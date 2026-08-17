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
