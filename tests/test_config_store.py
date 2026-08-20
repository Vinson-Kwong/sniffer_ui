import json
import sys
from pathlib import Path

from config_store import (
    DEFAULTS,
    app_base_dir,
    config_path,
    default_config_path,
    ensure_default_config_file,
    load_config,
    restore_defaults,
    save_config,
)


def test_load_returns_defaults_when_file_missing(tmp_path):
    cfg = load_config(tmp_path / "config.json")
    assert cfg["target_ip"] == "192.168.1.111"
    assert cfg["username"] == "robot"
    assert cfg["password"] == "MangoTango"
    assert cfg["port"] == 22
    assert cfg["run_command"] == "cd ~/ats && sudo ./sniffer --bin --nokov-wait"


def test_save_then_load_round_trips(tmp_path):
    p = tmp_path / "config.json"
    cfg = dict(DEFAULTS)
    cfg["target_ip"] = "10.0.0.5"
    cfg["password"] = "secret"
    save_config(cfg, p)
    loaded = load_config(p)
    assert loaded["target_ip"] == "10.0.0.5"
    assert loaded["password"] == "secret"


def test_corrupt_file_falls_back_to_defaults(tmp_path):
    p = tmp_path / "config.json"
    p.write_text("{ not valid json", encoding="utf-8")
    cfg = load_config(p)
    assert cfg["target_ip"] == "192.168.1.111"  # default restored


def test_load_merges_partial_file_over_defaults(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"target_ip": "1.2.3.4"}), encoding="utf-8")
    cfg = load_config(p)
    assert cfg["target_ip"] == "1.2.3.4"
    assert cfg["username"] == "robot"  # default kept for missing keys


def test_ensure_default_config_file_copies_from_bundled(tmp_path):
    bundled = tmp_path / "bundled.json"
    bundled.write_text(json.dumps({"target_ip": "9.9.9.9"}), encoding="utf-8")
    dest = tmp_path / "default_config.json"
    assert not dest.exists()
    ensure_default_config_file(default_path=dest, bundled_path=bundled)
    assert dest.exists()
    assert json.loads(dest.read_text(encoding="utf-8"))["target_ip"] == "9.9.9.9"


def test_ensure_default_config_file_creates_from_defaults_when_no_bundled(tmp_path):
    dest = tmp_path / "default_config.json"
    ensure_default_config_file(default_path=dest, bundled_path=tmp_path / "missing.json")
    assert dest.exists()
    assert json.loads(dest.read_text(encoding="utf-8"))["target_ip"] == DEFAULTS["target_ip"]


def test_restore_defaults_copies_default_into_config(tmp_path):
    default = tmp_path / "default_config.json"
    default.write_text(json.dumps({"target_ip": "10.0.0.99", "username": "admin"}), encoding="utf-8")
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"target_ip": "wrong"}), encoding="utf-8")

    cfg = restore_defaults(default_file=default, config_file=config)

    assert cfg["target_ip"] == "10.0.0.99"
    assert cfg["username"] == "admin"
    # config.json now mirrors default_config.json
    saved = json.loads(config.read_text(encoding="utf-8"))
    assert saved["target_ip"] == "10.0.0.99"


def test_restore_defaults_creates_config_when_missing(tmp_path):
    default = tmp_path / "default_config.json"
    default.write_text(json.dumps({"run_command": "sudo ~/ats/x --go"}), encoding="utf-8")
    config = tmp_path / "config.json"
    cfg = restore_defaults(default_file=default, config_file=config)
    assert config.exists()
    assert cfg["run_command"] == "sudo ~/ats/x --go"


# ---- path-selection keys + app_base_dir (2026-08-20 spec) ----

def test_defaults_include_path_selection_keys():
    assert DEFAULTS["data_copy_dir"] == ""
    assert DEFAULTS["last_copy_dir"] == ""
    assert DEFAULTS["bvh_output_dir"] == ""
    assert DEFAULTS["last_bvh_out_dir"] == ""


def test_load_old_config_without_new_keys_uses_blank_defaults(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"target_ip": "1.2.3.4"}), encoding="utf-8")
    cfg = load_config(p)
    assert cfg["data_copy_dir"] == ""
    assert cfg["bvh_output_dir"] == ""


def test_app_base_dir_is_project_root_in_dev():
    # dev (not frozen): the directory holding config_store.py == repo root
    assert app_base_dir() == Path(__file__).resolve().parent.parent


def test_app_base_dir_is_exe_dir_when_frozen(monkeypatch, tmp_path):
    fake_exe = tmp_path / "dist" / "sniffer_ui.exe"
    fake_exe.parent.mkdir()
    fake_exe.write_bytes(b"MZ")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe), raising=False)
    assert app_base_dir() == fake_exe.parent


def test_config_paths_live_in_app_base_dir():
    assert config_path() == app_base_dir() / "config.json"
    assert default_config_path() == app_base_dir() / "default_config.json"
