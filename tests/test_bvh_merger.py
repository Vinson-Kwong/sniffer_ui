"""BVH merge helpers: naming, command building, path resolution, decoding."""
from pathlib import Path

from core.bvh_merger import (
    build_merge_command,
    copy_dest_name,
    decode_output,
    merge_app_exe_path,
)


def test_copy_dest_name_keeps_original_name():
    # mocap_merge discovers the optical bvh by filename suffix
    # (*BDX.bvh / *BDX0709.bvh), so the copy must keep the original name.
    assert copy_dest_name("D:/take.bvh") == "take.bvh"
    assert copy_dest_name(Path("C:/x/BDX_0817fang1-BDX0709.bvh")) == "BDX_0817fang1-BDX0709.bvh"


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
import sys
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

    # allow_inprocess=False keeps these tests on the exe path even when the
    # real mocap_merge package is installed in this interpreter.
    return BvhMerger(schedule, logs.append, exe_path=exe,
                     source_dir=tmp_path / "no-src",
                     allow_inprocess=False), logs


def _make_source(tmp_path, name="take.bvh", content=b"MOTION Frames 1"):
    src = tmp_path / name
    src.write_bytes(content)
    return src


def test_merge_sync_copies_bvh_under_original_name_and_runs_exe(merger, tmp_path):
    m, logs = merger
    src = _make_source(tmp_path)
    folder = tmp_path / "data"
    folder.mkdir()

    m._merge_sync(str(folder), str(src))

    copied = folder / "take.bvh"
    assert copied.read_bytes() == b"MOTION Frames 1"
    assert any("已拷贝" in line for line in logs)
    assert any("merge-ok" in line for line in logs), f"exe output not streamed: {logs}"
    assert any("退出码=0" in line for line in logs)
    assert any("完成" in line for line in logs)


def test_merge_sync_overwrites_stale_same_name_copy(merger, tmp_path):
    m, _logs = merger
    src = _make_source(tmp_path, content=b"new")
    folder = tmp_path / "data"
    folder.mkdir()
    (folder / "take.bvh").write_bytes(b"old")  # stale copy from a previous run

    m._merge_sync(str(folder), str(src))

    assert (folder / "take.bvh").read_bytes() == b"new"


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
                            exe_path=tmp_path / "nope.exe",
                            source_dir=tmp_path / "no-src",
                            allow_inprocess=False)
    with pytest.raises(ValueError, match="未找到"):
        missing_exe._merge_sync(str(folder), str(src))


# ---- source-run mode (AV-safe: python -m mocap_merge, no packed exe) ----

def _make_source_dir(root: Path) -> Path:
    src = root / "src"
    (src / "mocap_merge").mkdir(parents=True)
    (src / "mocap_merge" / "__init__.py").write_bytes(b"")
    return src


class _FakeCli:
    calls = []

    def main(self, argv):
        _FakeCli.calls.append(argv)
        return 0


def test_runner_kind_prefers_subprocess_when_source_present(merger, tmp_path):
    m, _logs = merger  # allow_inprocess=False, but source wins first
    m._source_dir = _make_source_dir(tmp_path)
    assert m._runner_kind() == "python-subprocess"


def test_runner_kind_inprocess_when_no_source_but_importable(tmp_path, monkeypatch):
    m = BvhMerger(lambda fn: fn(), lambda s: None,
                  exe_path=tmp_path / "nope.exe",
                  source_dir=tmp_path / "no-src")
    monkeypatch.setattr("core.bvh_merger._import_cli", lambda: _FakeCli())
    assert m._runner_kind() == "inprocess"


def test_runner_kind_exe_when_not_importable_or_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr("core.bvh_merger._import_cli", lambda: None)
    m = BvhMerger(lambda fn: fn(), lambda s: None,
                  exe_path=tmp_path / "nope.exe",
                  source_dir=tmp_path / "no-src")
    assert m._runner_kind() == "exe"

    m2 = BvhMerger(lambda fn: fn(), lambda s: None,
                   exe_path=tmp_path / "nope.exe",
                   source_dir=tmp_path / "no-src",
                   allow_inprocess=False)
    monkeypatch.setattr("core.bvh_merger._import_cli", lambda: _FakeCli())
    assert m2._runner_kind() == "exe"


def test_runner_kind_inprocess_when_frozen(tmp_path, monkeypatch):
    # frozen: no interpreter for subprocess mode, but the bundled package
    # (hiddenimport) is importable -> in-process
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr("core.bvh_merger._import_cli", lambda: _FakeCli())
    m = BvhMerger(lambda fn: fn(), lambda s: None,
                  exe_path=tmp_path / "nope.exe",
                  source_dir=_make_source_dir(tmp_path))
    assert m._runner_kind() == "inprocess"


def test_merge_sync_inprocess_runs_cli_and_surfaces_missing_input_error(tmp_path):
    """Integration: real installed mocap_merge, executed in-process on an
    empty folder. Errors must reach the log; no subprocess involved."""
    logs = []
    m = BvhMerger(lambda fn: fn(), logs.append,
                  exe_path=tmp_path / "nope.exe",
                  source_dir=tmp_path / "no-src")
    if m._runner_kind() != "inprocess":
        pytest.skip("mocap_merge not installed in this interpreter")
    src = _make_source(tmp_path)
    folder = tmp_path / "data"
    folder.mkdir()

    with pytest.raises(RuntimeError, match="退出码=1"):
        m._merge_sync(str(folder), str(src))

    # the copy happened before the tool ran
    assert (folder / "take.bvh").read_bytes() == b"MOTION Frames 1"
    assert any("missing required input" in line for line in logs)
    assert any("进程内" in line for line in logs)
    assert any("退出码=1" in line for line in logs)


def test_resolve_runner_prefers_source_with_pythonpath(merger, tmp_path):
    m, _logs = merger
    src = _make_source_dir(tmp_path)
    m._source_dir = src

    prefix, env, must_exist = m._resolve_runner()

    assert prefix == [sys.executable, "-m", "mocap_merge"]
    assert must_exist is None
    assert str(src) in env["PYTHONPATH"]


def test_resolve_runner_falls_back_to_exe_without_source(merger, tmp_path):
    m, _logs = merger  # fixture's source_dir does not exist

    prefix, env, must_exist = m._resolve_runner()

    assert prefix == [str(m._exe)]
    assert env is None
    assert must_exist == m._exe


def test_resolve_runner_uses_exe_when_frozen(merger, tmp_path, monkeypatch):
    m, _logs = merger
    m._source_dir = _make_source_dir(tmp_path)  # source exists, but frozen
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    prefix, _env, must_exist = m._resolve_runner()

    assert prefix == [str(m._exe)]
    assert must_exist == m._exe


def test_merge_sync_runs_real_source_and_surfaces_missing_input_error(tmp_path):
    """Integration: run the real mocap_merge source (repo merge_app/src) via
    python -m on an empty folder. The tool must fail VISIBLY (traceback in the
    log, nonzero exit) — the packed exe failed silently / was AV-blocked."""
    repo_src = Path(__file__).resolve().parent.parent / "merge_app" / "src"
    if not (repo_src / "mocap_merge" / "__init__.py").is_file():
        pytest.skip("mocap_merge source not cloned")
    logs = []
    m = BvhMerger(lambda fn: fn(), logs.append, exe_path=tmp_path / "nope.exe",
                  source_dir=repo_src)
    src = _make_source(tmp_path)
    folder = tmp_path / "data"
    folder.mkdir()

    with pytest.raises(RuntimeError, match="退出码=1"):
        m._merge_sync(str(folder), str(src))

    # the copy happened before the tool ran
    assert (folder / "take.bvh").read_bytes() == b"MOTION Frames 1"
    # the tool's own error is visible in the log (no more silent failure)
    assert any("missing required input" in line for line in logs)
    assert any("退出码=1" in line for line in logs)



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
