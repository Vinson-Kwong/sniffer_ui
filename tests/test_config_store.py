import json

from config_store import DEFAULTS, load_config, save_config


def test_load_returns_defaults_when_file_missing(tmp_path):
    cfg = load_config(tmp_path / "config.json")
    assert cfg["target_ip"] == "192.168.1.111"
    assert cfg["username"] == "robot"
    assert cfg["password"] == "MangoTango"
    assert cfg["port"] == 22


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
