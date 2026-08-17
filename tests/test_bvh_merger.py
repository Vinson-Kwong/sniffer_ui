"""BVH merge helpers: naming, command building, path resolution, decoding."""
from pathlib import Path

from core.bvh_merger import (
    build_merge_command,
    decode_output,
    merge_app_exe_path,
    merged_copy_name,
)


def test_merged_copy_name_appends_merge_suffix():
    assert merged_copy_name("D:/take.bvh") == "take_merge.bvh"
    assert merged_copy_name("D:/a.b.bvh") == "a.b_merge.bvh"
    assert merged_copy_name(Path("C:/x/001-walk.bvh")) == "001-walk_merge.bvh"


def test_build_merge_command_is_folder_then_verbose():
    cmd = build_merge_command("E:/app/merge_app/mocap-merge.exe", "D:/data")
    assert cmd == ["E:/app/merge_app/mocap-merge.exe", "D:/data", "--verbose"]


def test_merge_app_exe_path_points_at_repo_merge_app():
    # repo root is two levels up from this test file's directory
    expected = Path(__file__).resolve().parent.parent / "merge_app" / "mocap-merge.exe"
    assert merge_app_exe_path() == expected


def test_decode_output_prefers_utf8_then_falls_back_to_gbk():
    assert decode_output("融合\n".encode("utf-8")) == "融合\n"
    assert decode_output("你好\n".encode("gbk")) == "你好\n"


def test_decode_output_replaces_undecodable_bytes():
    out = decode_output(b"\xff\xfe\x81")
    assert "�" in out


# ---- BvhMerger ----
import os
import threading

import pytest

from core.bvh_merger import BvhMerger


def make_fake_exe(directory: Path) -> Path:
    """A stand-in mocap exe: echoes its first arg; exits 3 if a FAIL file
    sits inside the target folder (how tests request a failing run)."""
    if os.name == "nt":
        exe = directory / "fake-mocap-merge.bat"
        exe.write_bytes(
            b"@echo off\r\n"
            b"if \"%~2\"==\"--verbose\" echo merge-ok %~1\r\n"
            b"if exist \"%~1\\FAIL\" exit /b 3\r\n"
            b"exit /b 0\r\n"
        )
        return exe
    exe = directory / "fake-mocap-merge.sh"
    exe.write_text(
        '#!/bin/sh\n'
        'if [ -f "$1/FAIL" ]; then exit 3; fi\n'
        'if [ "$2" = "--verbose" ]; then echo "merge-ok $1"; fi\n'
        'exit 0\n',
        encoding="ascii",
    )
    exe.chmod(0o755)
    return exe


@pytest.fixture
def merger(tmp_path):
    exe = make_fake_exe(tmp_path)
    logs = []

    def schedule(fn):
        fn()  # run callbacks inline: tests are single-threaded

    return BvhMerger(schedule, logs.append, exe_path=exe), logs


def _make_source(tmp_path, name="take.bvh", content=b"MOTION Frames 1"):
    src = tmp_path / name
    src.write_bytes(content)
    return src


def test_merge_sync_copies_bvh_with_merge_suffix_and_runs_exe(merger, tmp_path):
    m, logs = merger
    src = _make_source(tmp_path)
    folder = tmp_path / "data"
    folder.mkdir()

    m._merge_sync(str(folder), str(src))

    copied = folder / "take_merge.bvh"
    assert copied.read_bytes() == b"MOTION Frames 1"
    # the original-named file is never created
    assert not (folder / "take.bvh").exists()
    assert any("已拷贝" in line for line in logs)
    assert any("merge-ok" in line for line in logs), f"exe output not streamed: {logs}"
    assert any("退出码=0" in line for line in logs)
    assert any("完成" in line for line in logs)


def test_merge_sync_overwrites_own_merge_artifact(merger, tmp_path):
    m, _logs = merger
    src = _make_source(tmp_path, content=b"new")
    folder = tmp_path / "data"
    folder.mkdir()
    (folder / "take_merge.bvh").write_bytes(b"old")  # leftover from a previous run

    m._merge_sync(str(folder), str(src))

    assert (folder / "take_merge.bvh").read_bytes() == b"new"


def test_merge_sync_raises_on_exe_failure(merger, tmp_path):
    m, logs = merger
    src = _make_source(tmp_path)
    folder = tmp_path / "data"
    folder.mkdir()
    (folder / "FAIL").write_bytes(b"")  # ask the fake exe to exit 3

    with pytest.raises(RuntimeError, match="退出码=3"):
        m._merge_sync(str(folder), str(src))
    assert any("退出码=3" in line for line in logs)


def test_merge_sync_validates_inputs(merger, tmp_path):
    m, _logs = merger
    src = _make_source(tmp_path)
    folder = tmp_path / "data"
    folder.mkdir()

    with pytest.raises(ValueError, match="文件夹不存在"):
        m._merge_sync(str(tmp_path / "missing"), str(src))
    with pytest.raises(ValueError, match="BVH 文件不存在"):
        m._merge_sync(str(folder), str(tmp_path / "missing.bvh"))
    missing_exe = BvhMerger(lambda fn: fn(), lambda s: None,
                            exe_path=tmp_path / "nope.exe")
    with pytest.raises(ValueError, match="未找到"):
        missing_exe._merge_sync(str(folder), str(src))


def test_merge_reports_failure_through_on_done(merger, tmp_path):
    m, _logs = merger
    results = []
    done = threading.Event()

    def on_done(ok, error):
        results.append((ok, error))
        done.set()

    m.merge(str(tmp_path / "missing"), str(tmp_path / "x.bvh"), on_done)
    assert done.wait(timeout=5)
    ok, error = results[0]
    assert ok is False
    assert "文件夹不存在" in error
