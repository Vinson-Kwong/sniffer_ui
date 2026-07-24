"""Persisted application parameters (config.json next to the executable)."""
import json
import sys
from pathlib import Path
from typing import Optional

DEFAULTS = {
    "local_ip": "",
    "target_ip": "192.168.1.111",
    "port": 22,
    "username": "robot",
    "password": "MangoTango",
    "last_archive_dir": "",
    "run_command": "sudo ~/ats/sniffer --bin",
}


def config_path() -> Path:
    """config.json lives next to the frozen exe, else next to this source file."""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parent
    return base / "config.json"


def load_config(path: Optional[Path] = None) -> dict:
    p = path or config_path()
    data = dict(DEFAULTS)
    if p.exists():
        try:
            with p.open("r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                data.update(loaded)
        except (json.JSONDecodeError, OSError):
            pass  # corrupt or unreadable -> use defaults
    return data


def save_config(cfg: dict, path: Optional[Path] = None) -> None:
    p = path or config_path()
    data = dict(DEFAULTS)
    data.update(cfg)
    with p.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
