"""BVH融合 UI wiring: entries restored from config, button gating, validation."""
import app as appmod


def _fresh_app():
    a = appmod.App()
    return a


def test_bvh_entries_restored_from_config(monkeypatch):
    a = _fresh_app()
    try:
        monkeypatch.setattr(appmod, "load_config", lambda: {
            "target_ip": "1.2.3.4", "port": 22, "username": "robot",
            "password": "x", "run_command": "ls",
            "bvh_folder": "D:/data", "bvh_file": "D:/take.bvh",
            "last_bvh_dir": "D:/data", "local_ip": "",
        })
        a._load_config_into_ui()
        assert a.bvh_folder_entry.get() == "D:/data"
        assert a.bvh_file_entry.get() == "D:/take.bvh"
        assert a._last_bvh_dir == "D:/data"
    finally:
        a.destroy()


def test_persist_config_includes_bvh_keys(monkeypatch):
    a = _fresh_app()
    try:
        a.bvh_folder_entry.delete(0, "end"); a.bvh_folder_entry.insert(0, "D:/data")
        a.bvh_file_entry.delete(0, "end"); a.bvh_file_entry.insert(0, "D:/take.bvh")
        a._last_bvh_dir = "D:/data"
        saved = {}
        monkeypatch.setattr(appmod, "save_config", lambda cfg: saved.update(cfg))
        a._persist_config()
        assert saved["bvh_folder"] == "D:/data"
        assert saved["bvh_file"] == "D:/take.bvh"
        assert saved["last_bvh_dir"] == "D:/data"
    finally:
        a.destroy()


def test_merge_button_disabled_while_merging():
    a = _fresh_app()
    try:
        assert a.merge_btn.cget("state") == "normal"
        a._merging = True
        a._refresh_controls()
        assert a.merge_btn.cget("state") == "disabled"
        a._merging = False
        a._refresh_controls()
        assert a.merge_btn.cget("state") == "normal"
    finally:
        a.destroy()


def test_on_merge_bvh_requires_both_paths_and_stays_idle():
    a = _fresh_app()
    try:
        # clear entries: this machine's config.json may carry real saved paths
        a.bvh_folder_entry.delete(0, "end")
        a.bvh_file_entry.delete(0, "end")
        a.on_merge_bvh()          # both entries now empty
        a._poll()                 # drain scheduled log callback
        assert a._merging is False
        assert "请先选择文件夹" in a.log_view.get("1.0", "end")
    finally:
        a.destroy()
