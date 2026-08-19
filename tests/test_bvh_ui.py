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
            "bvh_archive": "D:/data-abc.tar.gz", "bvh_file": "D:/take.bvh",
            "last_bvh_dir": "D:/data", "local_ip": "",
        })
        a._load_config_into_ui()
        assert a.bvh_archive_entry.get() == "D:/data-abc.tar.gz"
        assert a.bvh_file_entry.get() == "D:/take.bvh"
        assert a._last_bvh_dir == "D:/data"
    finally:
        a.destroy()


def test_persist_config_includes_bvh_keys(monkeypatch):
    a = _fresh_app()
    try:
        a.bvh_archive_entry.delete(0, "end"); a.bvh_archive_entry.insert(0, "D:/data-abc.tar.gz")
        a.bvh_file_entry.delete(0, "end"); a.bvh_file_entry.insert(0, "D:/take.bvh")
        a._last_bvh_dir = "D:/data"
        saved = {}
        monkeypatch.setattr(appmod, "save_config", lambda cfg: saved.update(cfg))
        a._persist_config()
        assert saved["bvh_archive"] == "D:/data-abc.tar.gz"
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
        a.bvh_archive_entry.delete(0, "end")
        a.bvh_file_entry.delete(0, "end")
        a.on_merge_bvh()          # both entries now empty
        a._poll()                 # drain scheduled log callback
        assert a._merging is False
        assert "请先选择压缩包" in a.log_view.get("1.0", "end")
    finally:
        a.destroy()


def test_on_merge_bvh_rejects_missing_archive_and_wrong_suffix(tmp_path):
    a = _fresh_app()
    try:
        a.bvh_archive_entry.delete(0, "end")
        a.bvh_archive_entry.insert(0, str(tmp_path / "missing.tar.gz"))
        a.on_merge_bvh(); a._poll()
        assert "压缩包不存在" in a.log_view.get("1.0", "end")

        zip_like = tmp_path / "data.zip"; zip_like.write_bytes(b"PK")
        a.bvh_archive_entry.delete(0, "end")
        a.bvh_archive_entry.insert(0, str(zip_like))
        a.on_merge_bvh(); a._poll()
        assert "仅支持 tar.gz/tgz" in a.log_view.get("1.0", "end")
        assert a._merging is False   # never started
    finally:
        a.destroy()
