# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: single-file, windowed, bundling CustomTkinter data."""
from PyInstaller.utils.hooks import collect_data_files

datas = []
datas += collect_data_files("customtkinter")
datas += [("default_config.json", ".")]  # materialized next to the exe on first run

block_cipher = None

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=["customtkinter"],
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
