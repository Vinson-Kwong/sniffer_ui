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
