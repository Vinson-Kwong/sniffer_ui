# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: single-file, windowed, bundling CustomTkinter data."""
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

datas = []
datas += collect_data_files("customtkinter")
datas += [("default_config.json", ".")]  # materialized next to the exe on first run
# mocap_merge templates (sample.bvh, bdx_v4.urdf): its paths._template_dir()
# resolves <_MEIPASS>/data when frozen.
_mocap_data = Path(SPECPATH) / "merge_app" / "src" / "data"
datas += [(str(p), "data") for p in sorted(_mocap_data.glob("*"))]

block_cipher = None

a = Analysis(
    ["main.py"],
    pathex=[str(Path(SPECPATH) / "merge_app" / "src")],  # resolve the lazily-imported mocap_merge package from its source tree
    binaries=[],
    datas=datas,
    hiddenimports=["customtkinter", "mocap_merge.cli", "numpy", "yaml"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="sniffer_ui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    runtime_tmpdir=None,
    console=False,           # --windowed (no console window)
    disable_windowed_traceback=False,
    icon=None,
)
