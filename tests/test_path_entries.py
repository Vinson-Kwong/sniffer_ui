"""数据拷贝路径栏 + BVH输出路径栏:恢复、持久化、默认值解析、接线。"""
from types import SimpleNamespace

import app as appmod
from app import resolve_copy_dest
from config_store import app_base_dir


# ---- resolve_copy_dest ----

def test_resolve_copy_dest_blank_falls_back_to_app_base_dir():
    assert resolve_copy_dest("") == str(app_base_dir())
    assert resolve_copy_dest("   ") == str(app_base_dir())


def test_resolve_copy_dest_non_blank_wins():
    assert resolve_copy_dest("D:/data") == "D:/data"
    assert resolve_copy_dest("  D:/data  ") == "D:/data"


# ---- 数据拷贝路径栏 ----

def test_copy_dir_entry_restored_from_config(monkeypatch):
    a = appmod.App()
    try:
        monkeypatch.setattr(appmod, "load_config", lambda: {
            "target_ip": "1.2.3.4", "port": 22, "username": "robot",
            "password": "x", "run_command": "ls", "local_ip": "",
            "data_copy_dir": "D:/mocap", "last_copy_dir": "D:/mocap",
        })
        a._load_config_into_ui()
        assert a.copy_dir_entry.get() == "D:/mocap"
        assert a._last_copy_dir == "D:/mocap"
    finally:
        a.destroy()


def test_persist_config_includes_copy_dir_keys(monkeypatch):
    a = appmod.App()
    try:
        a.copy_dir_entry.delete(0, "end"); a.copy_dir_entry.insert(0, "D:/mocap")
        a._last_copy_dir = "D:/mocap"
        saved = {}
        monkeypatch.setattr(appmod, "save_config", lambda cfg: saved.update(cfg))
        a._persist_config()
        assert saved["data_copy_dir"] == "D:/mocap"
        assert saved["last_copy_dir"] == "D:/mocap"
    finally:
        a.destroy()


def test_on_copy_data_uses_entry_value_then_fallback(monkeypatch):
    a = appmod.App()
    try:
        monkeypatch.setattr(a, "session", SimpleNamespace(connected=True))
        a._set_mocap_dir("/remote/mocap/s1")
        captured = {}

        def fake_copy(remote, local_parent, on_done, on_progress=None):
            captured["remote"] = remote
            captured["local_parent"] = local_parent

        monkeypatch.setattr(a.controller, "copy_mocap_data", fake_copy)
        a.copy_dir_entry.delete(0, "end")
        a.copy_dir_entry.insert(0, "D:/mocap")
        a.on_copy_data()
        a._poll()  # drain the scheduled 目标目录 log
        assert captured["local_parent"] == "D:/mocap"
        assert "D:/mocap" in a.log_view.get("1.0", "end")

        a.copy_dir_entry.delete(0, "end")  # 留空 -> 回退 exe/项目根目录
        a.on_copy_data()
        assert captured["local_parent"] == str(app_base_dir())
    finally:
        a.destroy()
