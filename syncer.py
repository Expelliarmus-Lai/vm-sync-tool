"""Core sync engine: watchdog + vmrun for Host<->VM file sync."""

import os
import hashlib
import re
import subprocess
import sys
import threading
import time
import queue
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from i18n import Translator
from preflight import PreflightChecker

# Prevent CMD windows from popping up on Windows subprocess calls
_CREATE_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
GUEST_CMD = r"C:\Windows\System32\cmd.exe"
GUEST_POWERSHELL = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
POST_COPY_TIMESTAMP_DRIFT_SUPPRESS_SEC = 10.0
VMRUN_CALL_LOCK = threading.Lock()


class LogIcon:
    START = "🚀"
    STOP = "🛑"
    CANCEL = "🚫"
    SUCCESS = "✅"
    ERROR = "❌"
    WARNING = "⚠️"
    INFO = "💡"
    CHECK = "🔍"
    CONFIG = "💾"
    WATCH = "👀"
    UPLOAD = "📤"
    DOWNLOAD = "📥"
    PACKAGE = "📦"
    TOOL = "🔧"
    CLEANUP = "🧹"
    FIRMWARE = "🔥"
    BIN = "🧾"
    FILE = "📄"


class LogEvent:
    def __init__(self, icon: str, message: str, level: str = "info"):
        self.icon = icon
        self.message = message
        self.timestamp = datetime.now().strftime("%H:%M:%S")
        self.level = level  # "info", "success", "error", "warning"


@dataclass
class BinTargetCheck:
    ok: bool
    level: str = "success"
    message: str = ""
    resolved: tuple[str, str] | None = None


@dataclass
class GuestBinListing:
    ok: bool
    names: list[str]
    message: str = ""


class Debouncer:
    """Merge rapid repeated events for the same file path."""

    def __init__(self, delay_ms: int, callback):
        self.delay_ms = delay_ms
        self.callback = callback
        self._timers: dict = {}
        self._lock = threading.Lock()

    def trigger(self, key: str, *args):
        with self._lock:
            if key in self._timers:
                self._timers[key].cancel()
            timer = threading.Timer(self.delay_ms / 1000.0, self._fire, [key, args])
            timer.daemon = True
            self._timers[key] = timer
            timer.start()

    def _fire(self, key: str, args):
        with self._lock:
            self._timers.pop(key, None)
        self.callback(*args)

    def cancel_all(self):
        with self._lock:
            timers = list(self._timers.values())
            self._timers.clear()
        for timer in timers:
            timer.cancel()


class ProjectFileHandler(FileSystemEventHandler):
    """Watchdog handler: on any file change, debounce and push to VM."""

    def __init__(self, sync_manager: "SyncManager"):
        self.sync = sync_manager
        self.extensions = {
            ext.lower() for ext in self.sync.config.config.watch_extensions
        }

    def _should_sync(self, path: str) -> bool:
        ext = Path(path).suffix.lower()
        return ext in self.extensions

    def on_modified(self, event):
        if not event.is_directory and self._should_sync(event.src_path):
            self.sync._on_file_changed(event.src_path)

    def on_created(self, event):
        if not event.is_directory and self._should_sync(event.src_path):
            self.sync._on_file_changed(event.src_path)


class SyncManager:
    """Manages the lifecycle of file sync between Host and VM."""

    def __init__(self, config_manager, project_index: int = 0):
        self.config_manager = config_manager
        self.config = config_manager
        self.project_index = project_index
        self.event_queue = queue.Queue()
        self._observer: Observer | None = None
        self._debouncer: Debouncer | None = None
        self._poller_thread: threading.Thread | None = None
        self._copy_worker_thread: threading.Thread | None = None
        self._copy_queue: queue.Queue | None = None
        self._copy_pending: set[str] = set()
        self._copy_lock = threading.Lock()
        self._host_signature_lock = threading.Lock()
        self._host_file_signatures: dict[str, tuple[int, str]] = {}
        self._running = False
        self._last_bin_mtime = 0
        self._last_bin_signature: tuple[int, str] | None = None
        self._last_bin_state: tuple | None = None
        self._last_bin_unchanged_log_state: tuple | None = None
        self._last_bin_copied_content_key: tuple[str, str] | None = None
        self._last_bin_copied_at = 0.0
        self._startup_bin_state: tuple | None = None
        self._startup_bin_content_key: tuple[str, str] | None = None
        self._startup_bin_signature: tuple[str, int, str] | None = None
        self._startup_bin_same_content_copy_pending = False
        self._startup_bin_baseline_pending = False
        self._cached_bin_target_key: tuple[str, str, str, str] | None = None
        self._cached_bin_target: tuple[str, str] | None = None
        self._guest_state_output_mode: str | None = None
        self._guest_state_sidecar_vmx: str | None = None
        self._guest_state_sidecar_path: str | None = None
        self._stop_requested = False
        self._full_sync_cancel = threading.Event()
        self._full_sync_active = False
        self._incremental_sync_suspended = False
        self._last_bin_missing_log_time = 0.0
        self._synced_count = 0
        self._bin_ready = False
        self._run_token = 0

    def _tr(self, key: str, **kwargs) -> str:
        return Translator(self.config.config.language).tr(key, **kwargs)

    def _project(self):
        projects = getattr(self.config.config, "projects", [])
        if self.project_index < len(projects):
            return projects[self.project_index]
        return self.config.config

    @property
    def running(self) -> bool:
        return self._running

    @property
    def synced_count(self) -> int:
        return self._synced_count

    @property
    def bin_ready(self) -> bool:
        return self._bin_ready

    @property
    def full_sync_active(self) -> bool:
        return self._full_sync_active

    @property
    def has_error(self) -> bool:
        return self._incremental_sync_suspended

    # ── Lifecycle ──────────────────────────────────────────

    def start(
        self,
        preflight_checked: bool = False,
        preflight_snapshot: tuple | None = None,
    ) -> bool:
        if self._running:
            return True
        if not self._can_start(
            preflight_checked=preflight_checked,
            preflight_snapshot=preflight_snapshot,
        ):
            return False
        self._reset_bin_tracking()
        self._defer_startup_bin_baseline()
        self._stop_requested = False
        self._incremental_sync_suspended = False
        self._emit("info", LogIcon.CHECK, self._tr("sync.host_baseline_start"))
        self._prime_host_file_signatures()
        run_token = self._advance_run_token()
        self._running = True
        self._start_copy_worker(run_token)
        self._start_observer(run_token)
        self._start_poller(run_token)
        self._emit("info", LogIcon.START, self._tr("sync.service_started"))
        return True

    def stop(self):
        self._stop_requested = True
        self._running = False
        self._incremental_sync_suspended = False
        self._advance_run_token()
        if self._debouncer:
            self._debouncer.cancel_all()
        self._drain_copy_queue()
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=2)
            self._observer = None
        self._join_copy_worker_for_stop()
        self._join_poller_for_stop()
        self._clear_guest_state_sidecar(delete=True)
        self._emit("info", LogIcon.STOP, self._tr("sync.service_stopped"))

    def request_full_sync_cancel(self):
        self._full_sync_cancel.set()
        if self._full_sync_active:
            self._emit("warning", LogIcon.CANCEL, self._tr("sync.full.cancel_requested"))
            self._emit_progress(0.95, self._tr("sync.full.cancel_wait"), active=True)

    def preflight_snapshot(self) -> tuple:
        cfg = self.config.config
        project = self._project()
        return (
            cfg.vmrun_path,
            cfg.vmx_path,
            cfg.vm_guest_user,
            cfg.vm_guest_password,
            project.enabled,
            project.host_project_path,
            project.vm_project_path,
            project.vm_bin_relative_path,
            project.host_output_path,
            cfg.debounce_ms,
            cfg.poll_interval_sec,
            cfg.language,
            tuple(cfg.watch_extensions),
        )

    def _can_reuse_preflight(
        self,
        preflight_checked: bool,
        preflight_snapshot: tuple | None,
    ) -> bool:
        return bool(
            preflight_checked
            and preflight_snapshot is not None
            and preflight_snapshot == self.preflight_snapshot()
        )

    def _can_start(
        self,
        preflight_checked: bool = False,
        preflight_snapshot: tuple | None = None,
    ) -> bool:
        if not getattr(self._project(), "enabled", True):
            return False
        if not self._can_reuse_preflight(preflight_checked, preflight_snapshot):
            report = PreflightChecker(self.config.config).check(
                project_index=self.project_index
            )
            if not report.ok:
                self._emit("error", LogIcon.ERROR, self._tr("ui.preflight.error", message=report.error_text))
                return False
        try:
            Path(self._project().host_output_path).mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self._emit("error", LogIcon.ERROR, self._tr("sync.create_output_failed", error=e))
            return False
        if not self._can_resolve_bin_target_for_start():
            return False
        return True

    def _reset_bin_tracking(self):
        self._last_bin_mtime = 0
        self._last_bin_signature = None
        self._last_bin_state = None
        self._last_bin_unchanged_log_state = None
        self._last_bin_copied_content_key = None
        self._last_bin_copied_at = 0.0
        self._startup_bin_state = None
        self._startup_bin_content_key = None
        self._startup_bin_signature = None
        self._startup_bin_same_content_copy_pending = False
        self._startup_bin_baseline_pending = False
        self._bin_ready = False

    def _advance_run_token(self) -> int:
        self._run_token += 1
        return self._run_token

    def _is_current_run_token(self, run_token: int | None) -> bool:
        if self._stop_requested:
            return False
        return run_token is None or run_token == self._run_token

    def _is_live_run(self, run_token: int | None) -> bool:
        if run_token is None:
            return not self._stop_requested
        return self._running and self._is_current_run_token(run_token)

    def _defer_startup_bin_baseline(self):
        cfg = self.config.config
        project = self._project()
        self._startup_bin_baseline_pending = bool(
            cfg.vmrun_path
            and cfg.vmx_path
            and project.vm_project_path
            and project.vm_bin_relative_path
        )

    def _record_startup_bin_state(
        self,
        vm_bin: str,
        bin_filename: str,
        guest_state: tuple[int, int, str],
    ):
        state_key = (vm_bin.lower(), *guest_state)
        self._startup_bin_state = state_key
        self._startup_bin_content_key = self._bin_state_content_key(state_key)
        self._startup_bin_same_content_copy_pending = True
        self._startup_bin_baseline_pending = False
        self._emit("info", LogIcon.BIN, self._tr("sync.startup_bin_state", filename=bin_filename))

    def _record_startup_bin_signature(
        self,
        vm_bin: str,
        bin_filename: str,
        signature: tuple[int, str],
    ):
        self._startup_bin_signature = (vm_bin.lower(), *signature)
        self._startup_bin_baseline_pending = False
        self._emit("info", LogIcon.BIN, self._tr("sync.startup_bin_content", filename=bin_filename))

    def _vmrun(self) -> str:
        return self.config.config.vmrun_path

    def _has_guest_credentials(self) -> bool:
        cfg = self.config.config
        return bool(cfg.vm_guest_user and cfg.vm_guest_password)

    def _vmrun_command(self, args: list[str]) -> list[str]:
        cfg = self.config.config
        command = [self._vmrun()]
        if cfg.vm_guest_user:
            command.extend(["-gu", cfg.vm_guest_user, "-gp", cfg.vm_guest_password])
        command.extend(args)
        return command

    # ── Observer (Host → VM) ───────────────────────────────

    def _start_observer(self, run_token: int | None = None):
        host_root = self._project().host_project_path
        if not host_root or not Path(host_root).exists():
            self._emit("warning", LogIcon.WARNING, self._tr("sync.host_invalid", path=host_root))
            return

        self._debouncer = Debouncer(
            self.config.config.debounce_ms,
            lambda host_path: self._enqueue_copy_to_vm(host_path, run_token),
        )
        handler = ProjectFileHandler(self)
        self._observer = Observer()
        self._observer.schedule(handler, host_root, recursive=True)
        self._observer.start()
        self._emit("info", LogIcon.WATCH, self._tr("sync.watch_started", path=host_root))

    def _on_file_changed(self, host_path: str):
        if not self._running:
            return
        if not self._debouncer:
            return
        self._debouncer.trigger(host_path, host_path)

    def _start_copy_worker(self, run_token: int | None = None):
        self._copy_queue = queue.Queue()
        self._copy_pending = set()
        self._copy_worker_thread = threading.Thread(
            target=self._copy_worker_loop, args=(run_token,), daemon=True
        )
        self._copy_worker_thread.start()

    def _join_copy_worker_for_stop(self):
        worker = self._copy_worker_thread
        if not worker:
            return
        if worker is threading.current_thread():
            return
        worker.join(timeout=1.0)
        if not worker.is_alive():
            self._copy_worker_thread = None

    def _enqueue_copy_to_vm(self, host_path: str, run_token: int | None = None):
        if not self._running or self._incremental_sync_suspended:
            return
        if not self._is_current_run_token(run_token):
            return
        if not self._copy_queue:
            return
        if not self._host_file_content_changed(host_path):
            return
        with self._copy_lock:
            if host_path in self._copy_pending:
                return
            self._copy_pending.add(host_path)
        self._copy_queue.put((run_token, host_path))

    def _watched_extensions(self) -> set[str]:
        return {ext.lower() for ext in self.config.config.watch_extensions}

    def _host_signature_key(self, host_path: str) -> str:
        try:
            return str(Path(host_path).resolve()).casefold()
        except Exception:
            return str(Path(host_path).absolute()).casefold()

    def _host_file_signature(self, host_path: str) -> tuple[int, str] | None:
        path = Path(host_path)
        try:
            if not path.is_file():
                return None
            digest = hashlib.sha256()
            size = 0
            with path.open("rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    size += len(chunk)
                    digest.update(chunk)
            return size, digest.hexdigest()
        except OSError:
            return None

    def _prime_host_file_signatures(self):
        root = Path(self._project().host_project_path)
        signatures: dict[str, tuple[int, str]] = {}
        if root.exists():
            extensions = self._watched_extensions()
            for path in root.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in extensions:
                    continue
                signature = self._host_file_signature(str(path))
                if signature is not None:
                    signatures[self._host_signature_key(str(path))] = signature
        with self._host_signature_lock:
            self._host_file_signatures = signatures

    def _host_file_content_changed(self, host_path: str) -> bool:
        signature = self._host_file_signature(host_path)
        if signature is None:
            return False
        key = self._host_signature_key(host_path)
        with self._host_signature_lock:
            previous = self._host_file_signatures.get(key)
            if previous == signature:
                return False
            self._host_file_signatures[key] = signature
        return True

    def _copy_worker_loop(self, run_token: int | None = None):
        while self._running and self._is_current_run_token(run_token):
            if self._incremental_sync_suspended:
                self._drain_copy_queue()
                return
            copy_queue = self._copy_queue
            if not copy_queue:
                return
            try:
                item = copy_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            item_token, host_path = item if isinstance(item, tuple) else (run_token, item)
            with self._copy_lock:
                self._copy_pending.discard(host_path)
            try:
                if (
                    self._running
                    and not self._incremental_sync_suspended
                    and self._is_current_run_token(item_token)
                ):
                    self._do_copy_to_vm(host_path, run_token=item_token)
            finally:
                try:
                    copy_queue.task_done()
                except ValueError:
                    pass

    def _drain_copy_queue(self):
        copy_queue = self._copy_queue
        if copy_queue:
            while True:
                try:
                    copy_queue.get_nowait()
                    copy_queue.task_done()
                except queue.Empty:
                    break
                except ValueError:
                    break
        with self._copy_lock:
            self._copy_pending.clear()

    def _suspend_incremental_uploads(self, host_path: str):
        if self._incremental_sync_suspended:
            return
        self._incremental_sync_suspended = True
        self._drain_copy_queue()
        self._emit(
            "error",
            LogIcon.ERROR,
            self._tr("sync.incremental_suspended", filename=Path(host_path).name),
        )

    def _do_copy_to_vm(self, host_path: str, run_token: int | None = None):
        if not self._running:
            return
        if not self._is_current_run_token(run_token):
            return
        if self._incremental_sync_suspended:
            return
        try:
            project = self._project()
            host_root = Path(project.host_project_path)
            rel = Path(host_path).relative_to(host_root)
            vm_dest = str(
                (Path(project.vm_project_path) / rel).as_posix()
            ).replace("/", "\\")
            vm_dest_path = PureWindowsPath(vm_dest)
            vm_dir = str(vm_dest_path.parent)
            vm_tmp = self._guest_path_join(
                vm_dir,
                f".{vm_dest_path.name}.vm_sync_tmp",
            )

            self._emit("info", LogIcon.UPLOAD, self._tr("sync.to_vm", path=rel))

            mkdir = self._ensure_guest_directory(vm_dir)
            if not self._is_current_run_token(run_token) or not self._running:
                return
            if mkdir.returncode != 0:
                err = self._vmrun_error(mkdir)
                self._emit("error", LogIcon.ERROR, self._tr("sync.mkdir_failed", path=rel, error=err))
                return

            result = self._run_vmrun(
                [
                    "CopyFileFromHostToGuest",
                    self.config.config.vmx_path,
                    host_path,
                    vm_tmp,
                ],
                timeout=15,
            )

            if result.returncode == 0:
                if (
                    self._stop_requested
                    or not self._running
                    or not self._is_current_run_token(run_token)
                ):
                    self._cleanup_guest_path(self.config.config.vmx_path, vm_tmp, is_dir=False)
                    return
                move = self._move_guest_file(vm_tmp, vm_dest, timeout=15)
                if (
                    self._stop_requested
                    or not self._running
                    or not self._is_current_run_token(run_token)
                ):
                    self._cleanup_guest_path(self.config.config.vmx_path, vm_tmp, is_dir=False)
                    return
                if move.returncode != 0:
                    err = self._vmrun_error(move)
                    if not self._cleanup_guest_path(self.config.config.vmx_path, vm_tmp, is_dir=False):
                        self._emit("warning", LogIcon.CLEANUP, self._tr("sync.cleanup_tmp_failed", path=vm_tmp))
                    self._emit("error", LogIcon.ERROR, self._tr("sync.write_target_failed", path=rel, error=err))
                    return
                self._synced_count += 1
                self._emit("success", LogIcon.SUCCESS, self._tr("sync.to_vm_done", path=rel))
            else:
                self._cleanup_guest_path(self.config.config.vmx_path, vm_tmp, is_dir=False)
                if not self._is_current_run_token(run_token) or not self._running:
                    return
                err = result.stderr.strip() or "unknown error"
                self._emit("error", LogIcon.ERROR, self._tr("sync.to_vm_failed", path=rel, error=err))

        except subprocess.TimeoutExpired:
            if self._is_current_run_token(run_token) and self._running:
                self._suspend_incremental_uploads(host_path)
        except Exception as e:
            if self._is_current_run_token(run_token) and self._running:
                self._emit("error", LogIcon.ERROR, self._tr("sync.file_exception", filename=Path(host_path).name, error=e))

    # ── Poller (VM → Host, .bin) ───────────────────────────

    def _start_poller(self, run_token: int | None = None):
        self._poller_thread = threading.Thread(
            target=self._poll_loop, args=(run_token,), daemon=True
        )
        self._poller_thread.start()

    def _join_poller_for_stop(self):
        poller = self._poller_thread
        if not poller:
            return
        if poller is threading.current_thread():
            return
        poller.join(timeout=1.0)
        if not poller.is_alive():
            self._poller_thread = None

    def _poll_loop(self, run_token: int | None = None):
        while self._running and self._is_current_run_token(run_token):
            try:
                if run_token is None:
                    self._check_bin()
                else:
                    self._check_bin(run_token=run_token)
            except Exception as e:
                if run_token is None or (
                    self._is_current_run_token(run_token) and self._running
                ):
                    self._emit_bin_warning(self._tr("sync.bin_poll_exception", error=e))
            # Sleep in small chunks so we can respond to stop() quickly
            interval = self.config.config.poll_interval_sec
            for _ in range(interval * 2):
                if not self._running or not self._is_current_run_token(run_token):
                    return
                time.sleep(0.5)

    def _check_bin(self, run_token: int | None = None):
        if self._stop_requested or not self._is_current_run_token(run_token):
            self._bin_ready = False
            return
        vmx = self.config.config.vmx_path
        resolved = self._resolve_vm_bin_cached()
        if not resolved:
            if self._startup_bin_baseline_pending:
                self._startup_bin_baseline_pending = False
            self._bin_ready = False
            return
        vm_bin, bin_filename = resolved

        host_out = (
            Path(self._project().host_output_path)
            / bin_filename
        )
        guest_state = self._get_guest_file_state(vm_bin, vmx)
        if self._stop_requested or not self._is_current_run_token(run_token):
            self._bin_ready = False
            return
        if guest_state is not None:
            if self._startup_bin_baseline_pending:
                if not self._is_live_run(run_token):
                    self._bin_ready = False
                    return
                self._record_startup_bin_state(vm_bin, bin_filename, guest_state)
                self._bin_ready = False
                return
            state_key = (vm_bin.lower(), *guest_state)
            if state_key == self._startup_bin_state:
                self._bin_ready = False
                return
            content_key = self._bin_state_content_key(state_key)
            if (
                content_key
                and self._startup_bin_content_key
                and content_key == self._startup_bin_content_key
            ):
                if self._startup_bin_same_content_copy_pending:
                    if not self._is_live_run(run_token):
                        self._bin_ready = False
                        return
                    self._emit(
                        "info",
                        LogIcon.BIN,
                        self._tr("sync.startup_same_content_copy", filename=bin_filename),
                    )
                    self._startup_bin_state = None
                    self._startup_bin_content_key = None
                    self._startup_bin_same_content_copy_pending = False
                else:
                    if not self._is_live_run(run_token):
                        self._bin_ready = False
                        return
                    self._startup_bin_state = state_key
                    self._log_bin_content_unchanged_once(state_key, bin_filename, run_token=run_token)
                    self._bin_ready = False
                    return
            if (
                content_key
                and self._startup_bin_content_key
                and content_key != self._startup_bin_content_key
            ):
                self._startup_bin_state = None
                self._startup_bin_content_key = None
            if state_key == self._last_bin_state and host_out.exists():
                self._bin_ready = True
                return
            if self._is_recent_post_copy_timestamp_drift(state_key):
                self._last_bin_state = state_key
                self._bin_ready = True
                return
            if self._guest_bin_content_is_unchanged(state_key, host_out):
                if not self._is_live_run(run_token):
                    self._bin_ready = False
                    return
                self._last_bin_state = state_key
                self._log_bin_content_unchanged_once(state_key, bin_filename, run_token=run_token)
                self._bin_ready = True
                return
        else:
            if self._startup_bin_baseline_pending:
                signature = self._read_guest_bin_signature(vm_bin, vmx)
                if signature is not None:
                    if not self._is_live_run(run_token):
                        self._bin_ready = False
                        return
                    self._record_startup_bin_signature(
                        vm_bin,
                        bin_filename,
                        signature,
                    )
                self._bin_ready = False
                return
            state_key = None

        Path(self._project().host_output_path).mkdir(parents=True, exist_ok=True)
        tmp = tempfile.NamedTemporaryFile(
            prefix=".vm_sync_bin_", suffix=".tmp", delete=False,
        )
        tmp_path = Path(tmp.name)
        tmp.close()

        result = self._run_vmrun(
            [
                "CopyFileFromGuestToHost",
                vmx, vm_bin, str(tmp_path),
            ],
            timeout=30,
        )
        if self._stop_requested or not self._is_current_run_token(run_token):
            tmp_path.unlink(missing_ok=True)
            self._bin_ready = False
            return

        if result.returncode == 0:
            data = tmp_path.read_bytes()
            signature = (len(data), hashlib.sha256(data).hexdigest())
            startup_signature = (vm_bin.lower(), *signature)
            if startup_signature == self._startup_bin_signature:
                tmp_path.unlink(missing_ok=True)
                self._bin_ready = False
                return
            if (
                self._startup_bin_signature
                and startup_signature[0] == self._startup_bin_signature[0]
                and startup_signature != self._startup_bin_signature
            ):
                self._startup_bin_signature = None
            if signature == self._last_bin_signature and host_out.exists():
                tmp_path.unlink(missing_ok=True)
                if not self._is_current_run_token(run_token):
                    self._bin_ready = False
                    return
                unchanged_log_key = state_key
                if state_key is not None:
                    self._last_bin_state = state_key
                else:
                    unchanged_log_key = (vm_bin.lower(), "copied", *signature)
                self._log_bin_content_unchanged_once(
                    unchanged_log_key,
                    bin_filename,
                    run_token=run_token,
                )
                self._bin_ready = True
                return

            if not self._is_live_run(run_token):
                tmp_path.unlink(missing_ok=True)
                self._bin_ready = False
                return
            tmp_path.replace(host_out)
            if not self._is_live_run(run_token):
                self._bin_ready = False
                return
            self._last_bin_signature = signature
            if state_key is not None:
                self._last_bin_state = state_key
                self._last_bin_copied_content_key = self._bin_state_content_key(state_key)
                self._last_bin_copied_at = time.time()
            self._bin_ready = True
            self._emit(
                "success", LogIcon.DOWNLOAD,
                self._tr("sync.returned_firmware", filename=bin_filename, path=self._project().host_output_path)
            )
            self._emit("info", LogIcon.FIRMWARE, self._tr("sync.firmware_ready"))
            # Trigger tray notification
            self.event_queue.put(("bin_ready", bin_filename))
        else:
            tmp_path.unlink(missing_ok=True)
            err = self._vmrun_error(result)
            self._emit("error", LogIcon.ERROR, self._tr("sync.pull_bin_failed", error=err))

    def _bin_state_content_key(self, state_key: tuple) -> tuple[str, str] | None:
        if len(state_key) < 4:
            return None
        return state_key[0], state_key[-1]

    def _read_guest_bin_signature(self, vm_path: str, vmx: str) -> tuple[int, str] | None:
        tmp = tempfile.NamedTemporaryFile(
            prefix=".vm_sync_startup_bin_", suffix=".tmp", delete=False,
        )
        tmp_path = Path(tmp.name)
        tmp.close()
        try:
            result = self._run_vmrun(
                [
                    "CopyFileFromGuestToHost",
                    vmx, vm_path, str(tmp_path),
                ],
                timeout=30,
            )
            if result.returncode != 0:
                return None
            data = tmp_path.read_bytes()
            return len(data), hashlib.sha256(data).hexdigest()
        except Exception:
            return None
        finally:
            tmp_path.unlink(missing_ok=True)

    def _guest_bin_content_is_unchanged(self, state_key: tuple, host_out: Path) -> bool:
        if not host_out.exists() or not self._last_bin_state:
            return False
        if len(state_key) < 4 or len(self._last_bin_state) < 4:
            return False
        return (
            state_key[0] == self._last_bin_state[0]
            and state_key[-1] == self._last_bin_state[-1]
        )

    def _is_recent_post_copy_timestamp_drift(self, state_key: tuple) -> bool:
        content_key = self._bin_state_content_key(state_key)
        if not content_key or content_key != self._last_bin_copied_content_key:
            return False
        if not self._last_bin_copied_at:
            return False
        if time.time() - self._last_bin_copied_at > POST_COPY_TIMESTAMP_DRIFT_SUPPRESS_SEC:
            return False
        return True

    def _log_bin_content_unchanged_once(
        self,
        log_key: tuple,
        bin_filename: str,
        run_token: int | None = None,
    ):
        if not self._is_live_run(run_token):
            return
        if log_key == self._last_bin_unchanged_log_state:
            return
        self._emit(
            "info",
            LogIcon.INFO,
            self._tr("sync.bin_unchanged", filename=bin_filename),
        )
        self.event_queue.put(("bin_unchanged", bin_filename))
        self._last_bin_unchanged_log_state = log_key

    def _resolve_vm_bin(self) -> tuple[str, str] | None:
        return self.validate_bin_target(emit=True).resolved

    def _bin_target_cache_key(self) -> tuple[str, str, str, str]:
        cfg = self.config.config
        project = self._project()
        return (
            cfg.vmx_path,
            project.vm_project_path,
            project.vm_bin_relative_path,
            cfg.vmrun_path,
        )

    def _clear_bin_target_cache(self):
        self._cached_bin_target_key = None
        self._cached_bin_target = None

    def _resolve_vm_bin_cached(self) -> tuple[str, str] | None:
        key = self._bin_target_cache_key()
        if self._cached_bin_target_key == key and self._cached_bin_target:
            return self._cached_bin_target
        resolved = self._resolve_vm_bin()
        if resolved:
            self._cached_bin_target_key = key
            self._cached_bin_target = resolved
        else:
            self._clear_bin_target_cache()
        return resolved

    def resolve_vm_bin_path_for_display(self) -> tuple[str, str] | None:
        return self._resolve_vm_bin_cached()

    def validate_bin_target(self, emit: bool = False) -> BinTargetCheck:
        vm_bin = self.config.get_vm_bin_full_path(self.project_index)
        rel_path = PureWindowsPath(self._project().vm_bin_relative_path)
        if rel_path.suffix.lower() == ".bin":
            check = self._validate_explicit_bin_file(vm_bin, emit=emit)
        else:
            check = self._validate_bin_directory(vm_bin, emit=emit)
        if check.resolved:
            self._cached_bin_target_key = self._bin_target_cache_key()
            self._cached_bin_target = check.resolved
        elif not check.ok:
            self._clear_bin_target_cache()
        return check

    def _validate_explicit_bin_file(self, vm_bin: str, emit: bool = False) -> BinTargetCheck:
        filename = PureWindowsPath(vm_bin).name
        try:
            if self._guest_file_exists(vm_bin):
                return BinTargetCheck(True, resolved=(vm_bin, filename))
        except subprocess.TimeoutExpired:
            message = self._tr("sync.bin_check_timeout", path=vm_bin)
            if emit:
                self._emit_bin_error(message)
            return BinTargetCheck(False, "error", message)

        vm_dir = str(PureWindowsPath(vm_bin).parent)
        listing = self._list_guest_bin_names(vm_dir)
        if not listing.ok:
            message = self._tr("sync.bin_dir_read_failed", path=vm_dir, error=listing.message)
            if emit:
                self._emit_bin_error(message)
            return BinTargetCheck(False, "error", message)

        choices = ", ".join(
            self._guest_path_join(self._guest_relative_to_project(vm_dir), name)
            for name in listing.names
        )
        if choices:
            message = self._tr("sync.bin_file_missing_with_choices", path=self._guest_relative_to_project(vm_bin), choices=choices)
        else:
            message = self._tr("sync.bin_file_missing_no_choices", path=self._guest_relative_to_project(vm_bin))
        if emit:
            self._emit_bin_error(message)
        return BinTargetCheck(False, "error", message)

    def _validate_bin_directory(self, vm_dir: str, emit: bool = False) -> BinTargetCheck:
        listing = self._list_guest_bin_names(vm_dir)
        if not listing.ok:
            message = self._tr("sync.bin_dir_read_failed", path=vm_dir, error=listing.message)
            if emit:
                self._emit_bin_error(message)
            return BinTargetCheck(False, "error", message)

        if len(listing.names) == 1:
            name = listing.names[0]
            resolved_path = self._guest_path_join(vm_dir, name)
            if emit:
                self._emit(
                    "info",
                    LogIcon.BIN,
                    self._tr("sync.autoselect_bin", path=self._guest_relative_to_project(resolved_path)),
                )
            return BinTargetCheck(
                True,
                resolved=(resolved_path, name),
            )
        if not listing.names:
            message = self._tr("sync.bin_missing", path=vm_dir)
            if emit:
                self._emit_bin_warning(message)
            return BinTargetCheck(True, "warning", message)

        examples = ", ".join(
            self._guest_path_join(self._guest_relative_to_project(vm_dir), name)
            for name in listing.names
        )
        message = self._tr("sync.bin_multiple", examples=examples)
        if emit:
            self._emit_bin_error(message)
        return BinTargetCheck(False, "error", message)

    def _list_guest_bin_names(self, vm_dir: str) -> GuestBinListing:
        try:
            result = self._run_vmrun(
                [
                    "listDirectoryInGuest",
                    self.config.config.vmx_path,
                    vm_dir,
                ],
                timeout=15,
            )
        except subprocess.TimeoutExpired:
            return GuestBinListing(False, [], self._tr("sync.vm_timeout"))
        if result.returncode != 0:
            return GuestBinListing(False, [], self._vmrun_error(result))
        return GuestBinListing(True, self._parse_bin_names(result.stdout or ""))

    def _guest_file_exists(self, vm_path: str) -> bool:
        result = self._run_vmrun(
            [
                "fileExistsInGuest",
                self.config.config.vmx_path,
                vm_path,
            ],
            timeout=10,
        )
        return "file exists" in (result.stdout or "").lower()

    def _can_resolve_bin_target_for_start(self) -> bool:
        if (
            self._cached_bin_target_key == self._bin_target_cache_key()
            and self._cached_bin_target
        ):
            return True
        return self.validate_bin_target(emit=True).ok

    def _guest_relative_to_project(self, vm_path: str) -> str:
        path = PureWindowsPath(vm_path)
        project_root = PureWindowsPath(self._project().vm_project_path)
        try:
            return str(path.relative_to(project_root))
        except ValueError:
            return str(path)

    def _parse_bin_names(self, listing: str) -> list[str]:
        names: list[str] = []
        for raw in listing.splitlines():
            line = raw.strip().strip('"')
            if not line or not line.lower().endswith(".bin"):
                continue
            names.append(PureWindowsPath(line).name)
        return sorted(set(names), key=str.lower)

    def _emit_bin_warning(self, message: str):
        now = time.time()
        if now - self._last_bin_missing_log_time > 30:
            self._emit("warning", LogIcon.WARNING, message)
            self._last_bin_missing_log_time = now

    def _emit_bin_error(self, message: str):
        now = time.time()
        if now - self._last_bin_missing_log_time > 30:
            self._emit("error", LogIcon.ERROR, message)
            self._last_bin_missing_log_time = now

    def _get_guest_file_state(self, vm_path: str, vmx: str) -> tuple[int, int, str] | None:
        """Return (LastWriteTimeUtc ticks, size, sha256) for a guest file."""
        if self._guest_state_output_mode != "sidecar":
            ps_command = self._guest_file_state_script(vm_path)
            try:
                result = self._run_vmrun(
                    [
                        "runProgramInGuest", vmx,
                        *self._guest_powershell_command(ps_command),
                    ],
                    timeout=10,
                )
            except Exception:
                return None
            if result.returncode != 0:
                return None

            parsed = self._parse_guest_file_state_output(result.stdout or "")
            if parsed is not None:
                self._guest_state_output_mode = "stdout"
                return parsed
            self._guest_state_output_mode = "sidecar"
        return self._get_guest_file_state_via_sidecar(vm_path, vmx)

    def _guest_file_state_script(self, vm_path: str, output_path: str | None = None) -> str:
        script = (
            "$ErrorActionPreference='Stop'; "
            f"$f=Get-Item -LiteralPath {self._ps_literal(vm_path)}; "
            "$sha=[System.Security.Cryptography.SHA256]::Create(); "
            "$fs=[System.IO.File]::Open($f.FullName,[System.IO.FileMode]::Open,"
            "[System.IO.FileAccess]::Read,[System.IO.FileShare]::ReadWrite); "
            "try { $hash=([System.BitConverter]::ToString($sha.ComputeHash($fs)))."
            "Replace('-','').ToLowerInvariant() } finally { $fs.Dispose(); $sha.Dispose() }; "
            "$state='{0}|{1}|{2}' -f $f.LastWriteTimeUtc.Ticks,$f.Length,$hash; "
        )
        if output_path:
            return (
                script
                + f"Set-Content -LiteralPath {self._ps_literal(output_path)} "
                "-Value $state -Encoding ASCII -NoNewline"
            )
        return script + "$state"

    def _guest_powershell_command(self, script: str) -> list[str]:
        return [
            GUEST_POWERSHELL,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-WindowStyle", "Hidden",
            "-ExecutionPolicy", "Bypass",
            "-Command", script,
        ]

    def _parse_guest_file_state_output(self, text: str) -> tuple[int, int, str] | None:
        for raw in reversed((text or "").splitlines() or [text]):
            line = raw.strip()
            if "|" not in line:
                continue
            parts = line.split("|", 2)
            parsed = self._parse_guest_file_state_parts(parts)
            if parsed is not None:
                return parsed
        return None

    def _parse_guest_file_state_parts(self, parts: list[str]) -> tuple[int, int, str] | None:
        if len(parts) != 3:
            return None
        ticks_text, size_text, hash_text = parts
        try:
            digest = hash_text.strip().lower()
            if len(digest) != 64:
                return None
            return int(ticks_text.strip()), int(size_text.strip()), digest
        except ValueError:
            return None

    def _get_guest_file_state_via_sidecar(self, vm_path: str, vmx: str) -> tuple[int, int, str] | None:
        sidecar_path = self._get_or_create_guest_state_sidecar(vmx)
        if not sidecar_path:
            return None
        tmp = tempfile.NamedTemporaryFile(
            prefix=".vm_sync_state_", suffix=".txt", delete=False,
        )
        tmp_path = Path(tmp.name)
        tmp.close()
        try:
            writer = self._run_vmrun(
                [
                    "runProgramInGuest", vmx,
                    *self._guest_powershell_command(
                        self._guest_file_state_script(vm_path, sidecar_path)
                    ),
                ],
                timeout=10,
            )
            if writer.returncode != 0:
                self._clear_guest_state_sidecar(delete=False)
                return None

            copied = self._run_vmrun(
                [
                    "CopyFileFromGuestToHost",
                    vmx, sidecar_path, str(tmp_path),
                ],
                timeout=10,
            )
            if copied.returncode != 0:
                self._clear_guest_state_sidecar(delete=False)
                return None
            return self._parse_guest_file_state_output(
                tmp_path.read_text(encoding="utf-8", errors="replace")
            )
        except Exception:
            return None
        finally:
            tmp_path.unlink(missing_ok=True)

    def _get_or_create_guest_state_sidecar(self, vmx: str) -> str | None:
        if (
            self._guest_state_sidecar_vmx == vmx
            and self._guest_state_sidecar_path
        ):
            return self._guest_state_sidecar_path
        sidecar_path = self._create_guest_tempfile(vmx)
        if not sidecar_path:
            return None
        self._guest_state_sidecar_vmx = vmx
        self._guest_state_sidecar_path = sidecar_path
        return sidecar_path

    def _clear_guest_state_sidecar(self, delete: bool = False):
        vmx = self._guest_state_sidecar_vmx
        sidecar_path = self._guest_state_sidecar_path
        self._guest_state_sidecar_vmx = None
        self._guest_state_sidecar_path = None
        if not delete or not vmx or not sidecar_path:
            return
        try:
            self._run_vmrun(
                ["deleteFileInGuest", vmx, sidecar_path],
                timeout=5,
            )
        except Exception:
            pass

    def _create_guest_tempfile(self, vmx: str) -> str | None:
        try:
            result = self._run_vmrun(
                ["CreateTempfileInGuest", vmx],
                timeout=10,
            )
        except Exception:
            return None
        if result.returncode != 0:
            return None
        return self._parse_guest_tempfile_path(
            "\n".join([result.stdout or "", result.stderr or ""])
        )

    def _parse_guest_tempfile_path(self, output: str) -> str | None:
        for raw in output.splitlines():
            line = raw.strip().strip('"')
            if not line:
                continue
            match = re.search(r"[A-Za-z]:\\[^\r\n\"]+", line)
            if match:
                return match.group(0).strip()
        return None

    def _get_guest_mtime(self, vm_path: str, vmx: str) -> float | None:
        """Get file modification time inside guest via vmrun runProgramInGuest."""
        vm_dir = str(Path(vm_path).parent)
        vm_name = Path(vm_path).name
        try:
            result = self._run_vmrun(
                [
                    "runProgramInGuest",
                    vmx,
                    GUEST_CMD, "/c",
                    f'dir /T:W "{vm_path}" 2>nul',
                ],
                timeout=10,
            )
            # Parse dir output: date and time
            for line in result.stdout.splitlines():
                if vm_name in line:
                    # Windows dir format: MM/DD/YYYY  HH:MM AM/PM ...
                    # or Chinese locale: YYYY/MM/DD  HH:MM ...
                    parts = line.strip().split()
                    # Take the date and time parts before the file size
                    for i, p in enumerate(parts):
                        if "/" in p or "-" in p or ":" in p:
                            date_part = parts[i]
                            time_part = parts[i + 1] if i + 1 < len(parts) else ""
                            ampm = parts[i + 2] if i + 2 < len(parts) and parts[i + 2] in ("AM", "PM", "上午", "下午") else ""
                            datetime_str = f"{date_part} {time_part} {ampm}".strip()
                            try:
                                from datetime import datetime as dt
                                # Try multiple formats
                                for fmt in [
                                    "%Y/%m/%d %H:%M %p",
                                    "%m/%d/%Y %H:%M %p",
                                    "%Y/%m/%d %H:%M",
                                    "%m/%d/%Y %H:%M",
                                    "%Y/%m/%d %p %I:%M",
                                ]:
                                    try:
                                        return dt.strptime(datetime_str, fmt).timestamp()
                                    except ValueError:
                                        continue
                            except Exception:
                                pass
                            break
        except Exception:
            pass

        return None

    # ── Event helpers ──────────────────────────────────────

    def _emit(self, level: str, icon: str, message: str):
        self.event_queue.put(("log", LogEvent(icon, message, level)))

    def _emit_progress(self, value: float, message: str, active: bool = True):
        self.event_queue.put((
            "full_sync_progress",
            {
                "value": max(0.0, min(1.0, value)),
                "message": message,
                "active": active,
            },
        ))

    def _fail_full_sync(self, message: str) -> int:
        self._emit("error", LogIcon.ERROR, message)
        self._emit_progress(1.0, self._tr("sync.full.failed_progress", message=message), active=False)
        return 0

    def _vmrun_error(self, result) -> str:
        stderr = result.stderr or ""
        stdout = result.stdout or ""
        err = stderr.strip() or stdout.strip() or "unknown error"
        if err == "unknown error" and hasattr(result, "returncode"):
            err = f"{err} (return code {result.returncode})"
        if "Guest user:" in err:
            return self._tr("sync.guest_auth_failed")
        return err

    def _ensure_guest_directory(self, vm_path: str):
        exists = self._run_vmrun(
            ["directoryExistsInGuest", self.config.config.vmx_path, vm_path],
            timeout=20,
        )
        output = ((exists.stdout or "") + "\n" + (exists.stderr or "")).lower()
        if exists.returncode == 0 and "exists" in output:
            return exists

        created = self._run_vmrun(
            ["createDirectoryInGuest", self.config.config.vmx_path, vm_path],
            timeout=30,
        )
        return created

    def _syncable_files(self, host_root: Path) -> list[Path]:
        return [
            p for p in host_root.rglob("*")
            if p.is_file()
        ]

    def _guest_path_join(self, root: str, name: str) -> str:
        return root.rstrip("\\/") + "\\" + name

    def _ps_literal(self, value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    def _run_vmrun(self, args: list[str], timeout: int):
        with VMRUN_CALL_LOCK:
            return subprocess.run(
                self._vmrun_command(args),
                capture_output=True, text=True, timeout=timeout,
                creationflags=_CREATE_FLAGS,
            )

    def _move_guest_file(self, source: str, destination: str, timeout: int):
        script = (
            "$ErrorActionPreference='Stop'; "
            f"Move-Item -LiteralPath {self._ps_literal(source)} "
            f"-Destination {self._ps_literal(destination)} -Force"
        )
        return self._run_vmrun(
            [
                "runProgramInGuest",
                self.config.config.vmx_path,
                *self._guest_powershell_command(script),
            ],
            timeout=timeout,
        )

    def _cleanup_guest_path(self, vmx: str, path: str, is_dir: bool) -> bool:
        try:
            recurse = " -Recurse" if is_dir else ""
            script = (
                "$ErrorActionPreference='Stop'; "
                f"$p={self._ps_literal(path)}; "
                "if (Test-Path -LiteralPath $p) { "
                f"Remove-Item -LiteralPath $p{recurse} -Force "
                "}"
            )
            result = self._run_vmrun(
                [
                    "runProgramInGuest",
                    vmx,
                    *self._guest_powershell_command(script),
                ],
                timeout=20,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _cleanup_full_sync_guest_paths(self, vmx: str, paths: list[tuple[str, bool]]):
        seen = set()
        for path, is_dir in paths:
            if not path or path in seen:
                continue
            seen.add(path)
            if not self._cleanup_guest_path(vmx, path, is_dir):
                self._emit("warning", LogIcon.CLEANUP, self._tr("sync.cleanup_full_failed", path=path))

    def _cancel_full_sync(self, message: str) -> int:
        self._emit("warning", LogIcon.CANCEL, self._tr("sync.full.cancel_progress", message=message))
        self._emit_progress(1.0, self._tr("sync.full.cancel_progress", message=message), active=False)
        return 0

    def _create_full_sync_zip(self, host_root: Path, files: list[Path]) -> str:
        tmp = tempfile.NamedTemporaryFile(
            prefix="vm_sync_full_", suffix=".zip", delete=False
        )
        tmp.close()
        with zipfile.ZipFile(tmp.name, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for host_path in files:
                rel = host_path.relative_to(host_root).as_posix()
                archive.write(host_path, rel)
        return tmp.name

    def full_sync(self) -> int:
        """Full sync with cooperative cancellation and temporary VM staging."""
        self._full_sync_cancel.clear()
        self._full_sync_active = True
        cfg = self.config.config
        project = self._project()
        zip_path = ""
        guest_cleanup: list[tuple[str, bool]] = []

        try:
            if not cfg.vmx_path:
                self._emit("error", LogIcon.ERROR, self._tr("sync.full.missing_vmx"))
                return 0
            if not project.host_project_path:
                self._emit("error", LogIcon.ERROR, self._tr("sync.full.missing_host"))
                return 0
            if not project.vm_project_path:
                self._emit("error", LogIcon.ERROR, self._tr("sync.full.missing_vm_project"))
                return 0
            if not self._has_guest_credentials():
                return self._fail_full_sync(
                    self._tr("sync.full.missing_credentials")
                )

            host_root = Path(project.host_project_path)
            if not host_root.exists():
                self._emit("error", LogIcon.ERROR, self._tr("sync.full.host_missing"))
                return 0

            files = self._syncable_files(host_root)
            total = len(files)
            if total == 0:
                self._emit("warning", LogIcon.WARNING, self._tr("sync.full.empty"))
                self._emit_progress(1.0, self._tr("sync.full.empty_progress"), active=False)
                return 0

            self._emit("info", LogIcon.TOOL, self._tr("sync.full.start", count=total))
            self._emit_progress(0.0, self._tr("sync.full.step_files"))
            self._emit_progress(0.15, self._tr("sync.full.step_compress"))
            zip_path = self._create_full_sync_zip(host_root, files)
            zip_size_mb = Path(zip_path).stat().st_size / (1024 * 1024)
            self._emit("info", LogIcon.PACKAGE, self._tr("sync.full.package_ready", size=zip_size_mb))
            if self._full_sync_cancel.is_set():
                return self._cancel_full_sync(self._tr("sync.full.cancelled_before_upload"))

            self._emit_progress(0.35, self._tr("sync.full.step_create_dir"))
            mkdir = self._ensure_guest_directory(project.vm_project_path)
            if mkdir.returncode != 0:
                err = self._vmrun_error(mkdir)
                return self._fail_full_sync(self._tr("sync.full.create_dir_failed", error=err))

            temp_marker = self._create_guest_tempfile(cfg.vmx_path)
            if temp_marker:
                guest_zip = temp_marker + ".zip"
                guest_stage_dir = temp_marker + "_extract"
                guest_cleanup.extend([
                    (temp_marker, False),
                    (guest_zip, False),
                    (guest_stage_dir, True),
                ])
            else:
                guest_zip = self._guest_path_join(project.vm_project_path, "__vm_sync_fullsync.zip")
                guest_stage_dir = self._guest_path_join(project.vm_project_path, "__vm_sync_fullsync_extract")
                guest_cleanup.extend([
                    (guest_zip, False),
                    (guest_stage_dir, True),
                ])

            self._emit_progress(0.50, self._tr("sync.full.step_upload"))
            upload = self._run_vmrun(
                [
                    "CopyFileFromHostToGuest",
                    cfg.vmx_path,
                    zip_path,
                    guest_zip,
                ],
                timeout=120,
            )
            if upload.returncode != 0:
                err = self._vmrun_error(upload)
                return self._fail_full_sync(self._tr("sync.full.upload_failed", error=err))
            if self._full_sync_cancel.is_set():
                return self._cancel_full_sync(self._tr("sync.full.cancelled_after_upload"))

            self._emit_progress(0.65, self._tr("sync.full.step_create_stage"))
            stage_dir = self._ensure_guest_directory(guest_stage_dir)
            if stage_dir.returncode != 0:
                err = self._vmrun_error(stage_dir)
                return self._fail_full_sync(self._tr("sync.full.create_stage_failed", error=err))
            if self._full_sync_cancel.is_set():
                return self._cancel_full_sync(self._tr("sync.full.cancelled_before_extract"))

            self._emit_progress(0.75, self._tr("sync.full.step_extract"))
            extract_script = (
                "$ErrorActionPreference='Stop'; "
                f"Expand-Archive -LiteralPath {self._ps_literal(guest_zip)} "
                f"-DestinationPath {self._ps_literal(guest_stage_dir)} -Force"
            )
            extract = self._run_vmrun(
                [
                    "runProgramInGuest",
                    cfg.vmx_path,
                    *self._guest_powershell_command(extract_script),
                ],
                timeout=180,
            )
            if extract.returncode != 0:
                err = self._vmrun_error(extract)
                return self._fail_full_sync(self._tr("sync.full.extract_failed", error=err))
            if self._full_sync_cancel.is_set():
                return self._cancel_full_sync(self._tr("sync.full.cancelled_before_cover"))

            self._emit_progress(0.86, self._tr("sync.full.step_cover"))
            cover_script = (
                "$ErrorActionPreference='Stop'; "
                f"New-Item -ItemType Directory -Force -Path {self._ps_literal(project.vm_project_path)} | Out-Null; "
                f"Copy-Item -LiteralPath {self._ps_literal(self._guest_path_join(guest_stage_dir, '*'))} "
                f"-Destination {self._ps_literal(project.vm_project_path)} -Recurse -Force"
            )
            cover = self._run_vmrun(
                [
                    "runProgramInGuest",
                    cfg.vmx_path,
                    *self._guest_powershell_command(cover_script),
                ],
                timeout=180,
            )
            if cover.returncode != 0:
                err = self._vmrun_error(cover)
                return self._fail_full_sync(self._tr("sync.full.cover_failed", error=err))
            if self._full_sync_cancel.is_set():
                return self._cancel_full_sync(self._tr("sync.full.cancelled_after_cover"))

            self._emit_progress(0.92, self._tr("sync.full.step_cleanup"))
            self._cleanup_full_sync_guest_paths(cfg.vmx_path, guest_cleanup)
            guest_cleanup = []

            self._synced_count += total
            self._emit_progress(1.0, self._tr("sync.full.done_progress", done=total, total=total), active=False)
            self._emit("success", LogIcon.SUCCESS, self._tr("sync.full.done", count=total))
            return total
        except subprocess.TimeoutExpired as e:
            return self._fail_full_sync(self._tr("sync.full.timeout", error=e))
        except Exception as e:
            return self._fail_full_sync(str(e))
        finally:
            if zip_path:
                try:
                    Path(zip_path).unlink(missing_ok=True)
                except Exception:
                    pass
            if guest_cleanup and cfg.vmx_path:
                self._cleanup_full_sync_guest_paths(cfg.vmx_path, guest_cleanup)
            self._full_sync_active = False
