# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files
import customtkinter as ctk
from pathlib import Path
import os
import sys


block_cipher = None
project_dir = Path.cwd()
customtkinter_dir = Path(ctk.__file__).resolve().parent
app_icon = customtkinter_dir / "assets" / "icons" / "CustomTkinter_icon_Windows.ico"
tcl_dir = Path(sys.base_prefix) / "tcl"
if tcl_dir.exists():
    os.environ.setdefault("TCL_LIBRARY", str(tcl_dir / "tcl8.6"))
    os.environ.setdefault("TK_LIBRARY", str(tcl_dir / "tk8.6"))
datas = collect_data_files("customtkinter")
if tcl_dir.exists():
    datas.append((str(tcl_dir), "tcl"))


a = Analysis(
    ["main.py"],
    pathex=[str(project_dir)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "tkinter",
        "tkinter.constants",
        "tkinter.filedialog",
        "tkinter.font",
        "tkinter.messagebox",
        "tkinter.ttk",
        "pystray._win32",
    ],
    hookspath=[str(project_dir / "packaging_hooks")],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "numpy", "PySide6"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VM Sync",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(app_icon),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="VM Sync",
)
