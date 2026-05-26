# VM Sync Tool

## Overview

Windows desktop GUI tool that keeps a Keil firmware project synchronized between the host machine and a VMware Workstation VM. It uses `vmrun.exe` through VMware Tools / VIX, so it does not require network access and the VM NIC can remain disabled.

The intended workflow is:

1. Edit source files on the host.
2. Sync the project into the VM.
3. Build manually in Keil inside the VM.
4. Pull the generated `.bin` back to a host output directory.

## Current Status

- `vmrun.exe` auto-detection is implemented and persisted in `config.json`.
- VMX preflight verifies that the configured VMX is the VM currently listed by `vmrun list`.
- Host-to-VM incremental sync is implemented with watchdog and a 500 ms debounce.
- Full sync is implemented as zip upload plus guest-side PowerShell extraction.
- Full sync does not fall back to slow per-file copy. If zip upload/extract fails, it reports the error and stops.
- VM-to-host `.bin` return is implemented and has been confirmed to transfer a file from the running VM.
- `.bin` polling defaults to 1 second. Old configs with `poll_interval_sec = 3` are upgraded to `1`.
- `.bin` is copied back only when content hash changes. If the timestamp changes but content is identical, the app logs a skipped update once for that file state.
- The UI currently starts at `760x860`, has minimum size `680x720`, and has no maximum-size cap.
- Known open issue: window dragging can still feel less responsive than a normal native window on some machines. Do not pause timers, log updates, or polling while dragging, because that makes the app feel frozen.

## Stack

- **Language:** Python 3.12+
- **UI:** CustomTkinter native desktop window plus pystray system tray
- **File watch:** watchdog
- **VM communication:** `subprocess.run(...)` calling `vmrun.exe`
- **Full sync packaging:** Python `zipfile`, then guest PowerShell `Expand-Archive`

## File Map

| File | Purpose |
|------|---------|
| `main.py` | Entry point, single-instance lock on `127.0.0.1:19998`, config load, vmrun/VMX auto-discovery |
| `ui.py` | CustomTkinter UI: `App`, panels, `AutoScrollFrame`, log coloring, status bar, tray icon/menu |
| `syncer.py` | `SyncManager`: watchdog observer, debouncer, vmrun calls, full sync, `.bin` polling/return |
| `config_manager.py` | `ConfigManager` and `Config`: load/save `config.json`, normalize paths/defaults |
| `preflight.py` | Path, VM, vmrun, running-VM, Keil project, and `.bin` configuration checks |
| `vmrun_resolver.py` | `vmrun.exe` candidate resolution, `vmrun list`, VMX path normalization |
| `config.json` | User configuration persisted by the app |
| `test_*.py` | Unit/regression tests for config, preflight, vmrun resolver, sync logic, UI behavior |

## Config Keys

`config.json` uses snake_case keys:

| Key | Meaning |
|-----|---------|
| `vmrun_path` | Resolved `vmrun.exe` path. Auto-detected from config, common VMware paths, then PATH. |
| `vmx_path` | VMware `.vmx` file for the target VM. Must match a currently running VM from `vmrun list`. |
| `vm_guest_user` | Windows username inside the VM for `vmrun -gu`. |
| `vm_guest_password` | VM user password for `vmrun -gp`. Blank passwords are blocked because they can trigger VIX crashes/popups. |
| `host_project_path` | Host-side project root. |
| `vm_project_path` | VM-side project root. Full sync extracts here and incremental sync writes under this root. |
| `vm_bin_relative_path` | `.bin` path relative to `vm_project_path`. May be an exact `.bin` file or a directory to scan. Absolute paths are invalid. |
| `host_output_path` | Host directory where the returned `.bin` is written. Created on start if missing. |
| `debounce_ms` | Host file-change debounce, currently `500`. |
| `poll_interval_sec` | VM `.bin` poll interval, currently `1`. |
| `watch_extensions` | Incremental host-to-VM extensions. Includes modern and legacy Keil files. |

Path values are normalized to Windows backslashes when saved.

## Architecture

```text
Startup
  -> load config
  -> normalize paths and runtime defaults
  -> resolve vmrun.exe
  -> verify vmrun list and running VMX during preflight

Host edit
  -> watchdog
  -> debounce(500 ms)
  -> vmrun CopyFileFromHostToGuest
  -> VM project directory

Full sync button
  -> save and preflight
  -> zip the full host project
  -> vmrun CopyFileFromHostToGuest
  -> run guest PowerShell Expand-Archive -Force
  -> delete guest zip

Keil build in VM
  -> app polls configured VM .bin every 1 second
  -> read LastWriteTimeUtc ticks, length, SHA256
  -> vmrun CopyFileFromGuestToHost only when content changed
  -> host output directory
```

## Full Sync Behavior

- UI button label is `全量同步`.
- Saves current config before checking.
- Requires the enhanced preflight to pass.
- Shows progress in the log/progress UI instead of logging every file.
- Packages all files under `host_project_path`, not only watched source extensions.
- Extracts into `vm_project_path` with `Expand-Archive -Force`.
- Matching VM files are overwritten by extracted files.
- Extra files that already exist in the VM destination are not deleted.
- No slow compatibility fallback is enabled.

## Incremental Sync Behavior

- Starts only after preflight and `.bin` target validation pass.
- Watches `host_project_path` recursively.
- Debounces changes by `debounce_ms`.
- Copies only files whose suffix is in `watch_extensions`.
- Uses the configured `vmrun_path`; there is no hard-coded business-path entry point.
- All subprocess calls must include `creationflags=subprocess.CREATE_NO_WINDOW` to prevent flashing CMD windows.

## `.bin` Return Behavior

- `vm_bin_relative_path` is relative to `vm_project_path`.
- If it points to an exact `.bin`, the app uses only that file.
- If it points to a directory with one `.bin`, the app auto-resolves that one file.
- If it points to a directory with multiple `.bin` files, save/check and start are blocked and the log asks the user to fill the exact file name.
- The app must not default to project-specific names such as `RL6492_Project.bin`.
- The guest file state is `(LastWriteTimeUtc.Ticks, Length, SHA256)`.
- If stdout from guest PowerShell is unreliable, the app uses one guest temp sidecar file from `CreateTempfileInGuest`, copies it back, parses it, and deletes it when sync stops/quits.
- Guest state sidecar files must not be created in the project `Output` directory.

## Preflight Rules

General preflight is shared by `保存并检测`, start/pause, and full sync. Save/check and start also validate the guest `.bin` target uniqueness:

- `vmrun_path` must be configured and exist.
- `vmrun list` must complete without timeout/error.
- `vmx_path` must exist.
- Configured `vmx_path` must match a currently running VMX by normalized absolute path, not just file name.
- VM guest username and password are required.
- `host_project_path` must exist and be a directory.
- Keil project detection accepts `.uvprojx`, `.uvoptx`, `.uvproj`, `.uvopt`, `.uv2`, and `.opt`.
- `vm_project_path` must not be a disk root or broad risky system path.
- `host_output_path` must be a directory if it already exists.
- `vm_bin_relative_path` is required and must not be absolute.
- A `.bin` name that does not match the detected primary Keil project name is a warning, not a blocking error.

## UI Layout

```text
Title bar: status dot, "VM SYNC", state text
Control panel: start/pause, full sync, counters/status
AutoScrollFrame: auto-hiding page scrollbar
  - Config panel: paths, credentials, save/check, full sync
  - Log panel: colored CTkTextbox, internal scrollbar
Status bar: VM status, vmrun status, poll interval
```

UI notes:

- `AutoScrollFrame` replaces `CTkScrollableFrame`; CTk's built-in scroll frame did not auto-hide the scrollbar.
- `AutoScrollFrame` should not call `update_idletasks()` inside `<Configure>` handlers.
- Event polling is capped by `App.EVENTS_PER_TICK = 40`.
- Stats labels should only update when displayed values change.
- Log text color is per log line/event. A red or green message must not recolor previous messages.
- Config inputs are disabled while sync/full-sync is running.

## Window and Tray Lifecycle

- Close button hides the window with `withdraw()`; sync keeps running.
- Tray left-click or `显示窗口` restores the window.
- Tray menu dynamically shows current start/pause state.
- Tray `退出` stops sync, deletes the guest state sidecar if present, removes the tray icon, and quits the process.
- The tray icon appears on startup and persists until `退出`.

## Hard Constraints

- Single instance uses socket bind `127.0.0.1:19998`.
- Do not use `SO_REUSEADDR` for the single-instance socket on Windows.
- All `subprocess.run` calls must include `creationflags=subprocess.CREATE_NO_WINDOW`.
- Font family: `Microsoft YaHei UI` for normal UI and `Microsoft YaHei` for log/monospace-style text.
- Do not use network sync. The tool is designed around VMware Tools / `vmrun.exe`.
- Keep UI responsive. Avoid blocking vmrun calls on the Tk main thread.
- Do not reintroduce "pause timer/log/polling while dragging" as a drag-lag workaround.

## Verification Commands

Run these after code changes:

```powershell
python -m unittest discover -v
python -m py_compile main.py config_manager.py syncer.py ui.py preflight.py vmrun_resolver.py test_syncer.py test_ui_full_sync.py
```

## Naming Conventions

- Python files: `snake_case`
- UI classes: `PascalCase`
- UI methods: `_private_method` for internal callbacks/helpers
- Config keys: `snake_case` in JSON
