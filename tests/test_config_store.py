import json

from config_store import (
    DEFAULTS,
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
    assert cfg["run_command"] == "sudo ~/ats/sniffer --bin"


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
