"""VM Sync Tool 鈥?Entry point.

Syncs source files from host to VMware VM for Keil compilation,
pulls compiled .bin back to host, via vmrun.exe (no network required).

Usage:
    python main.py
"""

import sys
import os
import socket
from pathlib import Path

def app_base_dir() -> Path:
    """Return project dir in source mode, exe dir in PyInstaller mode."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent.resolve()
    return Path(__file__).parent.resolve()


def configure_tcl_tk():
    """Point tkinter at bundled Tcl/Tk when running from PyInstaller."""
    if not getattr(sys, "frozen", False):
        return
    bundle_dir = Path(getattr(sys, "_MEIPASS", app_base_dir()))
    os.environ.setdefault("TCL_LIBRARY", str(bundle_dir / "_tcl_data"))
    os.environ.setdefault("TK_LIBRARY", str(bundle_dir / "_tk_data"))


TOOL_DIR = app_base_dir()
os.chdir(str(TOOL_DIR))

_LOCK_PORT = 19998
_lock_sock: socket.socket | None = None


def check_single_instance() -> bool:
    """Bind a localhost port to ensure only one instance runs. Returns True if OK."""
    global _lock_sock
    try:
        _lock_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # DO NOT set SO_REUSEADDR 鈥?on Windows it permits multiple binds to the same port
        _lock_sock.bind(("127.0.0.1", _LOCK_PORT))
        _lock_sock.listen(1)
        return True
    except OSError:
        return False


def notify_existing_instance() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", _LOCK_PORT), timeout=0.5) as sock:
            sock.sendall(b"SHOW\n")
        return True
    except OSError:
        return False


def main():
    configure_tcl_tk()
    if not check_single_instance():
        if not notify_existing_instance():
            import tkinter.messagebox as mb
            from config_manager import ConfigManager
            from i18n import Translator

            config_manager = ConfigManager(str(TOOL_DIR / "config.json"))
            t = Translator(config_manager.config.language).tr
            mb.showwarning(
                "VM Sync",
                t("app.already_running"),
            )
        sys.exit(0)

    from config_manager import ConfigManager
    from syncer import SyncManager
    from ui import App
    from vmrun_resolver import resolve_vmrun_path

    config_path = TOOL_DIR / "config.json"
    config_manager = ConfigManager(str(config_path))
    cfg = config_manager.config

    detected_vmrun = resolve_vmrun_path(cfg.vmrun_path)
    if detected_vmrun and detected_vmrun != cfg.vmrun_path:
        cfg.vmrun_path = detected_vmrun
        config_manager.save()

    sync_managers = [
        SyncManager(config_manager, project_index=0),
        SyncManager(config_manager, project_index=1),
    ]
    app = App(config_manager, sync_managers)
    app.attach_single_instance_socket(_lock_sock)
    app.run()


if __name__ == "__main__":
    main()
