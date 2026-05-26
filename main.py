"""VM Sync Tool — Entry point.

Syncs source files from host to VMware VM for Keil compilation,
pulls compiled .bin back to host, via vmrun.exe (no network required).

Usage:
    python main.py
"""

import sys
import os
import socket
from pathlib import Path

TOOL_DIR = Path(__file__).parent.resolve()
os.chdir(str(TOOL_DIR))

_LOCK_PORT = 19998
_lock_sock: socket.socket | None = None


def check_single_instance() -> bool:
    """Bind a localhost port to ensure only one instance runs. Returns True if OK."""
    global _lock_sock
    try:
        _lock_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # DO NOT set SO_REUSEADDR — on Windows it permits multiple binds to the same port
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
    if not check_single_instance():
        if not notify_existing_instance():
            import tkinter.messagebox as mb
            mb.showwarning(
                "VM Sync",
                "VM Sync 已在运行中\n\n请查看系统托盘图标或任务栏",
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

    sync_manager = SyncManager(config_manager)
    app = App(config_manager, sync_manager)
    app.attach_single_instance_socket(_lock_sock)
    app.run()


if __name__ == "__main__":
    main()
