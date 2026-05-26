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

from preflight import PreflightChecker

# Prevent CMD windows from popping up on Windows subprocess calls
_CREATE_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
GUEST_CMD = r"C:\Windows\System32\cmd.exe"
GUEST_POWERSHELL = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"


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

    def __init__(self, config_manager):
        self.config_manager = config_manager
        self.config = config_manager
        self.event_queue = queue.Queue()
        self._observer: Observer | None = None
        self._debouncer: Debouncer | None = None
        self._poller_thread: threading.Thread | None = None
        self._running = False
        self._last_bin_mtime = 0
        self._last_bin_signature: tuple[int, str] | None = None
        self._last_bin_state: tuple | None = None
        self._last_bin_unchanged_log_state: tuple | None = None
        self._cached_bin_target_key: tuple[str, str, str, str] | None = None
        self._cached_bin_target: tuple[str, str] | None = None
        self._guest_state_output_mode: str | None = None
        self._guest_state_sidecar_vmx: str | None = None
        self._guest_state_sidecar_path: str | None = None
        self._last_bin_missing_log_time = 0.0
        self._synced_count = 0
        self._bin_ready = False

    @property
    def running(self) -> bool:
        return self._running

    @property
    def synced_count(self) -> int:
        return self._synced_count

    @property
    def bin_ready(self) -> bool:
        return self._bin_ready

    # ── Lifecycle ──────────────────────────────────────────

    def start(self) -> bool:
        if self._running:
            return True
        if not self._can_start():
            return False
        self._clear_bin_target_cache()
        self._running = True
        self._start_observer()
        self._start_poller()
        self._emit("info", "▶", "同步服务已启动")
        return True

    def stop(self):
        self._running = False
        if self._debouncer:
            self._debouncer.cancel_all()
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=2)
            self._observer = None
        self._join_poller_for_stop()
        self._clear_guest_state_sidecar(delete=True)
        self._emit("info", "⏹", "同步服务已停止")

    def _can_start(self) -> bool:
        report = PreflightChecker(self.config.config).check()
        if not report.ok:
            self._emit("error", "✕", f"路径预检失败:\n{report.error_text}")
            return False
        try:
            Path(self.config.config.host_output_path).mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self._emit("error", "✕", f"无法创建输出目录: {e}")
            return False
        if not self._can_resolve_bin_target_for_start():
            return False
        return True

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

    def _start_observer(self):
        host_root = self.config.config.host_project_path
        if not host_root or not Path(host_root).exists():
            self._emit("warning", "⚠", f"宿主机工程路径无效: {host_root}")
            return

        self._debouncer = Debouncer(
            self.config.config.debounce_ms,
            self._do_copy_to_vm,
        )
        handler = ProjectFileHandler(self)
        self._observer = Observer()
        self._observer.schedule(handler, host_root, recursive=True)
        self._observer.start()
        self._emit("info", "✓", f"监听宿主机工程: {host_root}")

    def _on_file_changed(self, host_path: str):
        if not self._running:
            return
        if not self._debouncer:
            return
        self._debouncer.trigger(host_path, host_path)

    def _do_copy_to_vm(self, host_path: str):
        if not self._running:
            return
        try:
            host_root = Path(self.config.config.host_project_path)
            rel = Path(host_path).relative_to(host_root)
            vm_dest = str(
                (Path(self.config.config.vm_project_path) / rel).as_posix()
            ).replace("/", "\\")

            self._emit("info", "↗", f"{rel} → VM")

            result = subprocess.run(
                self._vmrun_command([
                    "CopyFileFromHostToGuest",
                    self.config.config.vmx_path,
                    host_path,
                    vm_dest,
                ]),
                capture_output=True, text=True, timeout=15,
                creationflags=_CREATE_FLAGS,
            )

            if result.returncode == 0:
                self._synced_count += 1
                self._emit("success", "✓", str(rel))
            else:
                err = result.stderr.strip() or "unknown error"
                self._emit("error", "✗", f"{rel}: {err}")

        except subprocess.TimeoutExpired:
            self._emit("error", "✗", f"vmrun 超时: {Path(host_path).name}")
        except Exception as e:
            self._emit("error", "✗", f"{Path(host_path).name}: {e}")

    # ── Poller (VM → Host, .bin) ───────────────────────────

    def _start_poller(self):
        self._poller_thread = threading.Thread(
            target=self._poll_loop, daemon=True
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

    def _poll_loop(self):
        while self._running:
            try:
                self._check_bin()
            except Exception as e:
                self._emit_bin_warning(f".bin 轮询异常: {e}")
            # Sleep in small chunks so we can respond to stop() quickly
            interval = self.config.config.poll_interval_sec
            for _ in range(interval * 2):
                if not self._running:
                    return
                time.sleep(0.5)

    def _check_bin(self):
        vmx = self.config.config.vmx_path
        resolved = self._resolve_vm_bin_cached()
        if not resolved:
            self._bin_ready = False
            return
        vm_bin, bin_filename = resolved

        host_out = (
            Path(self.config.config.host_output_path)
            / bin_filename
        )
        guest_state = self._get_guest_file_state(vm_bin, vmx)
        if guest_state is not None:
            state_key = (vm_bin.lower(), *guest_state)
            if state_key == self._last_bin_state and host_out.exists():
                self._bin_ready = True
                return
            if self._guest_bin_content_is_unchanged(state_key, host_out):
                self._last_bin_state = state_key
                self._log_bin_content_unchanged_once(state_key, bin_filename)
                self._bin_ready = True
                return
        else:
            state_key = None

        Path(self.config.config.host_output_path).mkdir(parents=True, exist_ok=True)
        tmp = tempfile.NamedTemporaryFile(
            prefix=".vm_sync_bin_", suffix=".tmp", delete=False,
        )
        tmp_path = Path(tmp.name)
        tmp.close()

        result = subprocess.run(
            self._vmrun_command([
                "CopyFileFromGuestToHost",
                vmx, vm_bin, str(tmp_path),
            ]),
            capture_output=True, text=True, timeout=30,
            creationflags=_CREATE_FLAGS,
        )

        if result.returncode == 0:
            data = tmp_path.read_bytes()
            signature = (len(data), hashlib.sha256(data).hexdigest())
            if signature == self._last_bin_signature and host_out.exists():
                tmp_path.unlink(missing_ok=True)
                unchanged_log_key = state_key
                if state_key is not None:
                    self._last_bin_state = state_key
                else:
                    unchanged_log_key = (vm_bin.lower(), "copied", *signature)
                self._log_bin_content_unchanged_once(unchanged_log_key, bin_filename)
                self._bin_ready = True
                return

            tmp_path.replace(host_out)
            self._last_bin_signature = signature
            if state_key is not None:
                self._last_bin_state = state_key
            self._bin_ready = True
            self._emit(
                "success", "🔥",
                f"{bin_filename} → {self.config.config.host_output_path}"
            )
            self._emit("info", "⚡", "固件已就绪，可烧录")
            # Trigger tray notification
            self.event_queue.put(("bin_ready", bin_filename))
        else:
            tmp_path.unlink(missing_ok=True)
            err = self._vmrun_error(result)
            self._emit("error", "✗", f"拉取 .bin 失败: {err}")

    def _guest_bin_content_is_unchanged(self, state_key: tuple, host_out: Path) -> bool:
        if not host_out.exists() or not self._last_bin_state:
            return False
        if len(state_key) < 4 or len(self._last_bin_state) < 4:
            return False
        return (
            state_key[0] == self._last_bin_state[0]
            and state_key[-1] == self._last_bin_state[-1]
        )

    def _log_bin_content_unchanged_once(self, log_key: tuple, bin_filename: str):
        if log_key == self._last_bin_unchanged_log_state:
            return
        self._emit(
            "info",
            "ℹ",
            f"检测到 {bin_filename} 更新，但内容未变化，已跳过覆盖",
        )
        self._last_bin_unchanged_log_state = log_key

    def _resolve_vm_bin(self) -> tuple[str, str] | None:
        return self.validate_bin_target(emit=True).resolved

    def _bin_target_cache_key(self) -> tuple[str, str, str, str]:
        cfg = self.config.config
        return (
            cfg.vmx_path,
            cfg.vm_project_path,
            cfg.vm_bin_relative_path,
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
        return self._resolve_vm_bin()

    def validate_bin_target(self, emit: bool = False) -> BinTargetCheck:
        vm_bin = self.config.get_vm_bin_full_path()
        rel_path = PureWindowsPath(self.config.config.vm_bin_relative_path)
        if rel_path.suffix.lower() == ".bin":
            return self._validate_explicit_bin_file(vm_bin, emit=emit)
        return self._validate_bin_directory(vm_bin, emit=emit)

    def _validate_explicit_bin_file(self, vm_bin: str, emit: bool = False) -> BinTargetCheck:
        filename = PureWindowsPath(vm_bin).name
        try:
            if self._guest_file_exists(vm_bin):
                return BinTargetCheck(True, resolved=(vm_bin, filename))
        except subprocess.TimeoutExpired:
            message = f"VM .bin 文件检测超时: {vm_bin}"
            if emit:
                self._emit_bin_error(message)
            return BinTargetCheck(False, "error", message)

        vm_dir = str(PureWindowsPath(vm_bin).parent)
        listing = self._list_guest_bin_names(vm_dir)
        if not listing.ok:
            message = f"无法读取 VM .bin 目录: {vm_dir}: {listing.message}"
            if emit:
                self._emit_bin_error(message)
            return BinTargetCheck(False, "error", message)

        choices = ", ".join(
            self._guest_path_join(self._guest_relative_to_project(vm_dir), name)
            for name in listing.names
        )
        if choices:
            message = f"VM .bin 文件不存在: {self._guest_relative_to_project(vm_bin)}；当前目录可选: {choices}"
        else:
            message = f"VM .bin 文件不存在: {self._guest_relative_to_project(vm_bin)}；当前目录没有 .bin 文件"
        if emit:
            self._emit_bin_error(message)
        return BinTargetCheck(False, "error", message)

    def _validate_bin_directory(self, vm_dir: str, emit: bool = False) -> BinTargetCheck:
        listing = self._list_guest_bin_names(vm_dir)
        if not listing.ok:
            message = f"无法读取 VM .bin 目录: {vm_dir}: {listing.message}"
            if emit:
                self._emit_bin_error(message)
            return BinTargetCheck(False, "error", message)

        if len(listing.names) == 1:
            name = listing.names[0]
            return BinTargetCheck(
                True,
                resolved=(self._guest_path_join(vm_dir, name), name),
            )
        if not listing.names:
            message = f"未找到 VM .bin: {vm_dir}"
            if emit:
                self._emit_bin_warning(message)
            return BinTargetCheck(True, "warning", message)

        examples = ", ".join(
            self._guest_path_join(self._guest_relative_to_project(vm_dir), name)
            for name in listing.names
        )
        message = (
            "VM 目录下有多个 .bin，请在配置面板的“.bin 相对路径”"
            f"填写完整文件名，例如: {examples}"
        )
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
            return GuestBinListing(False, [], "vmrun 超时")
        if result.returncode != 0:
            return GuestBinListing(False, [], self._vmrun_error(result))
        return GuestBinListing(True, self._parse_bin_names(result.stdout or ""))

    def _guest_file_exists(self, vm_path: str) -> bool:
        result = subprocess.run(
            self._vmrun_command([
                "fileExistsInGuest",
                self.config.config.vmx_path,
                vm_path,
            ]),
            capture_output=True, text=True, timeout=10,
            creationflags=_CREATE_FLAGS,
        )
        return "file exists" in (result.stdout or "").lower()

    def _can_resolve_bin_target_for_start(self) -> bool:
        return self.validate_bin_target(emit=True).ok

    def _guest_relative_to_project(self, vm_path: str) -> str:
        path = PureWindowsPath(vm_path)
        project_root = PureWindowsPath(self.config.config.vm_project_path)
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
            self._emit("warning", "⚠", message)
            self._last_bin_missing_log_time = now

    def _emit_bin_error(self, message: str):
        now = time.time()
        if now - self._last_bin_missing_log_time > 30:
            self._emit("error", "✗", message)
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
            result = subprocess.run(
                self._vmrun_command([
                    "runProgramInGuest",
                    vmx,
                    GUEST_CMD, "/c",
                    f'dir /T:W "{vm_path}" 2>nul',
                ]),
                capture_output=True, text=True, timeout=10,
                creationflags=_CREATE_FLAGS,
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
        self._emit("error", "✗", message)
        self._emit_progress(1.0, f"全量同步失败: {message}", active=False)
        return 0

    def _vmrun_error(self, result) -> str:
        stderr = result.stderr or ""
        stdout = result.stdout or ""
        err = stderr.strip() or stdout.strip() or "unknown error"
        if err == "unknown error" and hasattr(result, "returncode"):
            err = f"{err} (return code {result.returncode})"
        if "Guest user:" in err:
            return "VM 用户名/密码无效或未配置，无法在虚拟机内执行命令"
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
        return subprocess.run(
            self._vmrun_command(args),
            capture_output=True, text=True, timeout=timeout,
            creationflags=_CREATE_FLAGS,
        )

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
        """Initial full sync: upload a filtered zip and extract it in the VM."""
        cfg = self.config.config
        if not cfg.vmx_path:
            self._emit("error", "✗", "请先配置 VMX 路径")
            return 0
        if not cfg.host_project_path:
            self._emit("error", "✗", "请先配置宿主机工程路径")
            return 0
        if not cfg.vm_project_path:
            self._emit("error", "✗", "请先配置 VM 工程路径")
            return 0
        if not self._has_guest_credentials():
            return self._fail_full_sync(
                "请先配置 VM 用户名和密码；空密码可能触发 VMware VIX 异常弹窗或卡死"
            )

        host_root = Path(cfg.host_project_path)
        if not host_root.exists():
            self._emit("error", "✗", "宿主机工程路径不存在，无法全量同步")
            return 0

        files = self._syncable_files(host_root)
        total = len(files)
        if total == 0:
            self._emit("warning", "⚠", "没有找到需要同步的文件")
            self._emit_progress(1.0, "没有需要同步的文件", active=False)
            return 0

        zip_path = ""
        guest_zip = self._guest_path_join(cfg.vm_project_path, "__vm_sync_fullsync.zip")
        self._emit("info", "🔄", f"全量同步开始，准备打包 {total} 个文件")
        self._emit_progress(0.0, "准备文件列表")

        try:
            self._emit_progress(0.15, "正在压缩工程文件")
            zip_path = self._create_full_sync_zip(host_root, files)
            zip_size_mb = Path(zip_path).stat().st_size / (1024 * 1024)
            self._emit("info", "📦", f"压缩包已生成 ({zip_size_mb:.1f} MB)")

            self._emit_progress(0.35, "正在创建 VM 目标目录")
            mkdir = self._ensure_guest_directory(cfg.vm_project_path)
            if mkdir.returncode != 0:
                err = self._vmrun_error(mkdir)
                return self._fail_full_sync(f"创建 VM 目录失败: {err}")

            self._emit_progress(0.50, "正在上传压缩包到 VM")
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
                return self._fail_full_sync(f"上传压缩包失败: {err}")

            self._emit_progress(0.75, "正在 VM 内解压覆盖")
            ps_command = (
                "$ErrorActionPreference='Stop'; "
                f"Expand-Archive -LiteralPath {self._ps_literal(guest_zip)} "
                f"-DestinationPath {self._ps_literal(cfg.vm_project_path)} -Force"
            )
            extract = self._run_vmrun(
                [
                    "runProgramInGuest", cfg.vmx_path,
                    *self._guest_powershell_command(ps_command),
                ],
                timeout=180,
            )
            if extract.returncode != 0:
                err = self._vmrun_error(extract)
                return self._fail_full_sync(f"VM 内解压失败: {err}")

            self._emit_progress(0.92, "正在清理临时文件")
            cleanup = self._run_vmrun(
                [
                    "deleteFileInGuest", cfg.vmx_path, guest_zip,
                ],
                timeout=15,
            )
            if cleanup.returncode != 0:
                self._emit("warning", "⚠", "VM 临时压缩包清理失败，可忽略")

            self._synced_count += total
            self._emit_progress(1.0, f"全量同步完成 ({total}/{total})", active=False)
            self._emit("success", "✅", f"全量同步完成 ({total}/{total})")
            return total
        except subprocess.TimeoutExpired as e:
            return self._fail_full_sync(f"全量同步超时: {e}")
        except Exception as e:
            return self._fail_full_sync(str(e))
        finally:
            if zip_path:
                try:
                    Path(zip_path).unlink(missing_ok=True)
                except Exception:
                    pass
