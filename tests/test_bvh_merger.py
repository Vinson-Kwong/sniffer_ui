"""BVH merge helpers: naming, command building, path resolution, decoding."""
from pathlib import Path

from core.bvh_merger import (
    build_merge_command,
    copy_dest_name,
    decode_output,
    is_supported_archive,
    merge_dir_in_extracted,
    merge_app_exe_path,
)


def test_copy_dest_name_keeps_original_name():
    # mocap_merge discovers the optical bvh by filename suffix
    # (*BDX.bvh / *BDX0709.bvh), so the copy must keep the original name.
    assert copy_dest_name("D:/take.bvh") == "take.bvh"
    assert copy_dest_name(Path("C:/x/BDX_0817fang1-BDX0709.bvh")) == "BDX_0817fang1-BDX0709.bvh"


def test_is_supported_archive_accepts_tar_gz_family_only():
    assert is_supported_archive("D:/data-abc.tar.gz") is True
    assert is_supported_archive("D:/data.tgz") is True
    assert is_supported_archive("D:/DATA.TAR.GZ") is True  # case-insensitive
    assert is_supported_archive("D:/data.zip") is False
    assert is_supported_archive("D:/data.tar") is False
    assert is_supported_archive("D:/take.bvh") is False
    assert is_supported_archive("") is False


def test_merge_dir_in_extracted_picks_single_top_level_dir(tmp_path):
    # 数据拷贝打包结构: tar -czf <pkg> -C <父目录> <目录名> -> 单顶层目录
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "x8.bin").write_bytes(b"x")
    assert merge_dir_in_extracted(tmp_path) == tmp_path / "data"


def test_merge_dir_in_extracted_falls_back_to_root_for_loose_files(tmp_path):
    (tmp_path / "a.bvh").write_bytes(b"a")
    (tmp_path / "b.bin").write_bytes(b"b")
    assert merge_dir_in_extracted(tmp_path) == tmp_path


def test_merge_dir_in_extracted_single_file_falls_back_to_root(tmp_path):
    (tmp_path / "a.bvh").write_bytes(b"a")
    assert merge_dir_in_extracted(tmp_path) == tmp_path


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
import tarfile
import threading

import pytest

from core.bvh_merger import BvhMerger


def make_fake_exe(directory: Path) -> Path:
    """A stand-in mocap exe: echoes its first arg, cats the copied-in
    take.bvh (so tests can see WHICH copy the tool saw), writes the
    <folder>_merge.bvh product, exits 3 if a FAIL file sits inside the
    target folder."""
    if os.name == "nt":
        exe = directory / "fake-mocap-merge.bat"
        exe.write_bytes(
            b"@echo off\r\n"
            b"if exist \"%~1\\FAIL\" exit /b 3\r\n"
            b"if \"%~2\"==\"--verbose\" echo merge-ok %~1\r\n"
            b"type \"%~1\\take.bvh\" 2>nul\r\n"
            b"copy nul \"%~1\\%~n1_merge.bvh\" >nul\r\n"
            b"exit /b 0\r\n"
        )
        return exe
    exe = directory / "fake-mocap-merge.sh"
    exe.write_text(
        '#!/bin/sh\n'
        'if [ -f "$1/FAIL" ]; then exit 3; fi\n'
        'if [ "$2" = "--verbose" ]; then echo "merge-ok $1"; fi\n'
        'cat "$1/take.bvh" 2>/dev/null\n'
        ': > "$1/$(basename "$1")_merge.bvh"\n'
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


def _make_archive(tmp_path, folder_name="data", files=None) -> Path:
    """Pack tmp_path/folder_name (+files dict) into tmp_path/<folder_name>.tar.gz,
    mirroring 数据拷贝's `tar -czf <pkg> -C <parent> <name>` single top-level dir."""
    folder = tmp_path / folder_name
    folder.mkdir(parents=True, exist_ok=True)
    for name, content in (files or {}).items():
        (folder / name).write_bytes(content)
    archive = tmp_path / f"{folder_name}.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(folder, arcname=folder_name)
    return archive


def _temp_folder_from_logs(logs) -> Path:
    """The 融合文件夹 path the merger logged (the temp dir is gone by the
    time the assertion runs, so we can only recover it from the log)."""
    line = next(l for l in logs if "融合文件夹" in l)
    return Path(line.split(":", 1)[1].strip())


def test_merge_sync_extracts_archive_copies_bvh_and_runs_exe(merger, tmp_path):
    m, logs = merger
    src = _make_source(tmp_path)
    archive = _make_archive(tmp_path, "data", {"optical-BDX.bvh": b"optical"})

    m._merge_sync(str(archive), str(src))

    assert (tmp_path / "data_merge.bvh").is_file(), \
        f"product not copied next to the archive: {logs}"
    assert any("解压" in line for line in logs)
    assert any("融合文件夹" in line for line in logs)
    assert any("已拷贝" in line for line in logs)
    assert any("merge-ok" in line for line in logs), f"exe output not streamed: {logs}"
    assert any("退出码=0" in line for line in logs)
    assert any("产物已保存" in line for line in logs)
    assert any("完成" in line for line in logs)


def test_merge_sync_overwrites_stale_same_name_copy_inside_archive(merger, tmp_path):
    m, logs = merger
    src = _make_source(tmp_path, content=b"new-content")
    archive = _make_archive(tmp_path, "data", {"take.bvh": b"old"})  # stale copy

    m._merge_sync(str(archive), str(src))

    # the fake exe cats the copied-in take.bvh: the tool saw the fresh copy
    assert "new-content" in "".join(logs)


def test_merge_sync_overwrites_stale_product_next_to_archive(merger, tmp_path):
    m, _logs = merger
    src = _make_source(tmp_path)
    archive = _make_archive(tmp_path, "data", {"x8.bin": b"x"})
    (tmp_path / "data_merge.bvh").write_bytes(b"stale product")

    m._merge_sync(str(archive), str(src))

    assert (tmp_path / "data_merge.bvh").read_bytes() == b""  # replaced by fresh product


def test_merge_sync_cleans_up_temp_dir(merger, tmp_path):
    m, logs = merger
    src = _make_source(tmp_path)
    archive = _make_archive(tmp_path, "data", {})

    m._merge_sync(str(archive), str(src))

    temp_folder = _temp_folder_from_logs(logs)
    assert temp_folder.parent.name.startswith("bvh-merge-")
    assert not temp_folder.parent.exists()  # whole temp root removed


def test_merge_sync_raises_on_exe_failure_and_cleans_up(merger, tmp_path):
    m, logs = merger
    src = _make_source(tmp_path)
    archive = _make_archive(tmp_path, "data", {"FAIL": b""})  # ask exe to exit 3

    with pytest.raises(RuntimeError, match="退出码=3"):
        m._merge_sync(str(archive), str(src))
    assert any("退出码=3" in line for line in logs)
    assert not _temp_folder_from_logs(logs).parent.exists()
    # a failed merge must not leave a product next to the archive
    assert not (tmp_path / "data_merge.bvh").exists()


def test_merge_sync_uses_extraction_root_for_flat_archive(merger, tmp_path):
    m, logs = merger
    src = _make_source(tmp_path)
    archive = tmp_path / "flat.tar.gz"
    staging = tmp_path / "staging"; staging.mkdir()
    (staging / "optical-BDX.bvh").write_bytes(b"o")
    (staging / "x8.bin").write_bytes(b"x")
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(staging / "optical-BDX.bvh", arcname="optical-BDX.bvh")
        tar.add(staging / "x8.bin", arcname="x8.bin")

    m._merge_sync(str(archive), str(src))

    folder = _temp_folder_from_logs(logs)
    assert folder.name.startswith("bvh-merge-")  # the extraction root itself
    assert (tmp_path / f"{folder.name}_merge.bvh").is_file()


def test_merge_sync_validates_inputs(merger, tmp_path):
    m, _logs = merger
    src = _make_source(tmp_path)
    good = _make_archive(tmp_path, "data", {})
    zip_like = tmp_path / "data.zip"; zip_like.write_bytes(b"PK")

    with pytest.raises(ValueError, match="压缩包不存在"):
        m._merge_sync(str(tmp_path / "missing.tar.gz"), str(src))
    with pytest.raises(ValueError, match="仅支持 tar.gz/tgz"):
        m._merge_sync(str(zip_like), str(src))
    with pytest.raises(ValueError, match="BVH 文件不存在"):
        m._merge_sync(str(good), str(tmp_path / "missing.bvh"))
    missing_exe = BvhMerger(lambda fn: fn(), lambda s: None,
                            exe_path=tmp_path / "nope.exe",
                            source_dir=tmp_path / "no-src",
                            allow_inprocess=False)
    with pytest.raises(ValueError, match="未找到"):
        missing_exe._merge_sync(str(good), str(src))


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
    empty extracted folder. Errors must reach the log; no subprocess involved."""
    logs = []
    m = BvhMerger(lambda fn: fn(), logs.append,
                  exe_path=tmp_path / "nope.exe",
                  source_dir=tmp_path / "no-src")
    if m._runner_kind() != "inprocess":
        pytest.skip("mocap_merge not installed in this interpreter")
    src = _make_source(tmp_path)
    archive = _make_archive(tmp_path, "data", {})

    with pytest.raises(RuntimeError, match="退出码=1"):
        m._merge_sync(str(archive), str(src))

    assert any("已拷贝" in line for line in logs)  # copy happened before the tool ran
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
    python -m on an empty extracted folder."""
    repo_src = Path(__file__).resolve().parent.parent / "merge_app" / "src"
    if not (repo_src / "mocap_merge" / "__init__.py").is_file():
        pytest.skip("mocap_merge source not cloned")
    logs = []
    m = BvhMerger(lambda fn: fn(), logs.append, exe_path=tmp_path / "nope.exe",
                  source_dir=repo_src)
    src = _make_source(tmp_path)
    archive = _make_archive(tmp_path, "data", {})

    with pytest.raises(RuntimeError, match="退出码=1"):
        m._merge_sync(str(archive), str(src))

    assert any("已拷贝" in line for line in logs)
    assert any("missing required input" in line for line in logs)
    assert any("退出码=1" in line for line in logs)



def test_merge_reports_failure_through_on_done(merger, tmp_path):
    m, _logs = merger
    results = []
    done = threading.Event()

    def on_done(ok, error):
        results.append((ok, error))
        done.set()

    m.merge(str(tmp_path / "missing.tar.gz"), str(tmp_path / "x.bvh"), on_done)
    assert done.wait(timeout=5)
    ok, error = results[0]
    assert ok is False
    assert "压缩包不存在" in error


# ---- output_dir (2026-08-20 spec) ----

def test_merge_sync_without_output_dir_saves_next_to_archive(merger, tmp_path):
    m, _logs = merger
    src = _make_source(tmp_path)
    archive = _make_archive(tmp_path, "data", {"x8.bin": b"x"})

    m._merge_sync(str(archive), str(src))  # 不传 output_dir

    assert (tmp_path / "data_merge.bvh").is_file()


def test_merge_sync_output_dir_saves_product_there_and_creates_it(merger, tmp_path):
    m, logs = merger
    src = _make_source(tmp_path)
    archive = _make_archive(tmp_path, "data", {"x8.bin": b"x"})
    out = tmp_path / "results" / "merged"  # 尚不存在

    m._merge_sync(str(archive), str(src), output_dir=str(out))

    assert (out / "data_merge.bvh").is_file()
    assert not (tmp_path / "data_merge.bvh").exists()  # 不再落在压缩包旁
    assert any(str(out) in line for line in logs)


def test_merge_passes_output_dir_through(merger, tmp_path):
    m, _logs = merger
    src = _make_source(tmp_path)
    archive = _make_archive(tmp_path, "data", {"x8.bin": b"x"})
    out = tmp_path / "out"
    done = threading.Event()
    results = []

    def on_done(ok, error):
        results.append((ok, error))
        done.set()

    m.merge(str(archive), str(src), on_done, output_dir=str(out))
    assert done.wait(timeout=10)
    assert results[0][0] is True
    assert (out / "data_merge.bvh").is_file()
