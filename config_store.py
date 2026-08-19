"""Persisted application parameters (config.json next to the executable)."""
import json
import shutil
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
    "run_command": "cd ~/ats && sudo ./sniffer --bin",
    "bvh_archive": "",
    "bvh_file": "",
    "last_bvh_dir": "",
}


def config_path() -> Path:
    """config.json lives next to the frozen exe, else next to this source file."""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parent
    return base / "config.json"


def default_config_path() -> Path:
    """default_config.json lives next to the exe/script (the 'factory defaults')."""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parent
    return base / "default_config.json"


def _bundled_default_path() -> Path:
    """In a frozen build, the bundled default_config.json lives under _MEIPASS."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "default_config.json"
    return Path(__file__).resolve().parent / "default_config.json"


def ensure_default_config_file(default_path: Optional[Path] = None,
                               bundled_path: Optional[Path] = None) -> None:
    """Make sure default_config.json exists next to the exe/script so it is editable.

    Copies it from the bundled resource (frozen build) or writes DEFAULTS."""
    p = default_path or default_config_path()
    if p.exists():
        return
    src = bundled_path or _bundled_default_path()
    if src.exists():
        try:
            shutil.copyfile(src, p)
            return
        except OSError:
            pass
    save_config(DEFAULTS, p)


def restore_defaults(default_file: Optional[Path] = None,
                     config_file: Optional[Path] = None) -> dict:
    """Copy default_config.json -> config.json and return the loaded config."""
    ensure_default_config_file(default_path=default_file)
    src = default_file or default_config_path()
    dst = config_file or config_path()
    try:
        shutil.copyfile(src, dst)
    except OSError:
        save_config(DEFAULTS, dst)
    return load_config(dst)


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
