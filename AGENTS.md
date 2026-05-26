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
- After sync starts, the first `.bin` poll records the current VM `.bin` as a startup baseline and does not copy it back immediately.
- `.bin` is copied back only when content hash changes. If the timestamp changes but content is identical, the app logs a skipped update once for that file state.
- The UI currently starts at `760x860`, has minimum size `680x720`, and has no maximum-size cap.
- The source repository has bilingual project documentation: Chinese `README.md` and English `README.en.md`.
- The release user guide is also bilingual: `docs/USER_GUIDE.md` and `docs/USER_GUIDE.en.md`.
- `build_release.ps1` builds a folder-based exe release and copies the user guides into `dist\VM Sync\README.md` and `dist\VM Sync\README.en.md`, rewriting language links for the release package.
- Local runtime config, release output, build output, caches, and probe logs are intentionally ignored by git.
- Known open issue: window dragging can still feel less responsive than a normal native window on some machines. Do not pause timers, log updates, or polling while dragging, because that makes the app feel frozen.

## Stack

- **Language:** Python 3.12+
- **UI:** CustomTkinter native desktop window plus pystray system tray
- **File watch:** watchdog
- **VM communication:** `subprocess.run(...)` calling `vmrun.exe`
- **Full sync packaging:** Python `zipfile`, then guest PowerShell `Expand-Archive`

## Repository Layout

This file is meant for local AI/development agents, so it documents both tracked repository files and local ignored files. Ignored files may still be important for debugging a user's machine, but they must not be committed.

Full local workspace layout:

```text
vm-sync-tool/
  .gitignore                                      tracked
  AGENTS.md                                      tracked, local AI/maintainer context
  README.md                                      tracked, Chinese GitHub/developer README
  README.en.md                                   tracked, English GitHub/developer README
  docs/
    USER_GUIDE.md                                tracked, Chinese release user guide source
    USER_GUIDE.en.md                             tracked, English release user guide source
  main.py                                        tracked, app entry point
  ui.py                                          tracked, CustomTkinter UI and tray behavior
  syncer.py                                      tracked, sync engine and vmrun operations
  config_manager.py                              tracked, config model and persistence
  preflight.py                                   tracked, path/VM/bin validation
  vmrun_resolver.py                              tracked, vmrun and running VM detection
  tools/
    vmrun_probe.py                               tracked, local vmrun diagnostic helper
  tests/                                         tracked, unit/regression tests
  packaging_hooks/
    pre_find_module_path/
      hook-tkinter.py                            tracked, PyInstaller Tcl/Tk hook
      __pycache__/                               ignored, local Python cache
  requirements.txt                               tracked, runtime dependencies
  requirements-dev.txt                           tracked, development/build dependencies
  config.example.json                            tracked, safe public config template
  config.json                                    ignored, real local config with paths/credentials
  dev_start.cmd                                  tracked, source-mode local launcher
  build_release.ps1                              tracked, release build script
  VM Sync.spec                                   tracked, PyInstaller spec
  build/                                         ignored, PyInstaller intermediate output
  dist/
    VM Sync/                                     ignored, generated folder-based release
      VM Sync.exe                                ignored, generated executable
      _internal/                                 ignored, bundled runtime/dependencies
      README.md                                  ignored, generated Chinese user guide
      README.en.md                               ignored, generated English user guide
      config.example.json                        ignored, copied public config template
  vmrun_probe_result.txt                         ignored, local probe output if generated
  __vm_sync_probe_*.txt                          ignored, temporary probe output if generated
  task_plan.md / findings.md / progress.md       ignored, optional local planning notes
```

Tracked files that belong in the source repository:

| Path | Purpose |
|------|---------|
| `.gitignore` | Excludes local config, build output, caches, probe output, and editor/OS noise |
| `AGENTS.md` | AI/maintainer context, project rules, architecture notes, and verification commands |
| `README.md` | Chinese GitHub/developer-facing project overview |
| `README.en.md` | English GitHub/developer-facing project overview |
| `docs/USER_GUIDE.md` | Chinese end-user guide copied to release `README.md` |
| `docs/USER_GUIDE.en.md` | English end-user guide copied to release `README.en.md` |
| `main.py` | Entry point, single-instance lock on `127.0.0.1:19998`, config load, vmrun/VMX auto-discovery |
| `ui.py` | CustomTkinter UI: `App`, panels, `AutoScrollFrame`, log coloring, status bar, tray icon/menu |
| `syncer.py` | `SyncManager`: watchdog observer, debouncer, vmrun calls, full sync, `.bin` polling/return |
| `config_manager.py` | `ConfigManager` and `Config`: load/save `config.json`, normalize paths/defaults |
| `preflight.py` | Path, VM, vmrun, running-VM, Keil project, and `.bin` configuration checks |
| `vmrun_resolver.py` | `vmrun.exe` candidate resolution, `vmrun list`, VMX path normalization |
| `tools/vmrun_probe.py` | One-shot diagnostic script for testing `vmrun` connectivity |
| `tests/` | Unit/regression tests for config, preflight, vmrun resolver, sync logic, and UI behavior |
| `packaging_hooks/pre_find_module_path/hook-tkinter.py` | PyInstaller pre-find hook for Tcl/Tk packaging compatibility |
| `requirements.txt` | Runtime dependencies |
| `requirements-dev.txt` | Development and release packaging dependencies |
| `config.example.json` | Safe public config template |
| `dev_start.cmd` | One-click source-mode launcher for local Windows development |
| `build_release.ps1` | Folder-based exe release build script |
| `VM Sync.spec` | PyInstaller build configuration; explicitly unignored in `.gitignore` |

Current test files:

```text
tests/
  __init__.py
  test_config_manager.py
  test_main_single_instance.py
  test_preflight.py
  test_syncer.py
  test_ui_bin_hint.py
  test_ui_full_sync.py
  test_ui_log.py
  test_ui_start_async.py
  test_ui_status_async.py
  test_ui_tray.py
  test_vmrun_resolver.py
```

Local/generated files that should remain untracked:

| Path | Purpose |
|------|---------|
| `config.json` | Local user configuration persisted by the app; may contain real paths, username, and password. Local AI may inspect it for debugging, but must not commit or expose secrets. |
| `dist/` | Release output generated by `build_release.ps1`; use it to test the packaged app locally, but regenerate instead of editing contents by hand. |
| `build/` | PyInstaller intermediate build output; disposable and regenerated by packaging. |
| `__pycache__/` and `*.pyc` | Python bytecode caches |
| `packaging_hooks/pre_find_module_path/__pycache__/` | Local hook bytecode cache |
| `vmrun_probe_result.txt` and `__vm_sync_probe_*.txt` | Local diagnostic/probe output |
| `task_plan.md`, `findings.md`, `progress.md` | Optional local planning/session notes from planning workflows |

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
  -> service starts quickly and the first poll records existing VM .bin as a baseline
  -> app polls configured VM .bin every 1 second
  -> read LastWriteTimeUtc ticks, length, SHA256
  -> vmrun CopyFileFromGuestToHost only when content changes after startup
  -> host output directory
```

## Documentation and Release Packaging

- Root docs are for GitHub and developers:
  - `README.md` is the default Chinese overview.
  - `README.en.md` is the English counterpart.
  - Both files should contain language links near the top.
- End-user docs live under `docs/`:
  - `docs/USER_GUIDE.md` is Chinese.
  - `docs/USER_GUIDE.en.md` is English.
  - These files should focus on using the release package, configuration fields, first-use flow, sync overwrite rules, and FAQ.
- Release package layout after `build_release.ps1`:

```text
dist\VM Sync\
  VM Sync.exe
  _internal\
  README.md
  README.en.md
  config.example.json
```

- `build_release.ps1` copies `docs/USER_GUIDE.md` to release `README.md` and `docs/USER_GUIDE.en.md` to release `README.en.md`.
- The build script rewrites guide language links from `USER_GUIDE*.md` to `README*.md` so links work inside the release package.
- Do not commit `dist/`, `build/`, `config.json`, `__pycache__/`, or `vmrun_probe_result.txt`.
- `config.example.json` stays tracked because it is safe to share and documents the public config shape.

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
- On the first poll after service start, an existing VM `.bin` becomes the baseline and is ignored until it changes after startup.
- If guest file state cannot be read while establishing the startup baseline, the app copies the existing VM `.bin` to a host temp file only to calculate a signature; it still does not overwrite `host_output_path`.
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
- Do not block `SyncManager.start()` on startup `.bin` hashing/copying; baseline work belongs in the poller after the service reports running.
- Do not reintroduce "pause timer/log/polling while dragging" as a drag-lag workaround.

## Verification Commands

Run these after code changes:

```powershell
python -m unittest discover -v
python -m py_compile main.py config_manager.py syncer.py ui.py preflight.py vmrun_resolver.py tools/vmrun_probe.py tests/test_config_manager.py tests/test_main_single_instance.py tests/test_preflight.py tests/test_syncer.py tests/test_ui_bin_hint.py tests/test_ui_full_sync.py tests/test_ui_log.py tests/test_ui_start_async.py tests/test_ui_status_async.py tests/test_ui_tray.py tests/test_vmrun_resolver.py
```

Run these after documentation or packaging-script changes:

```powershell
git diff --check
powershell -ExecutionPolicy Bypass -File .\build_release.ps1
```

## Naming Conventions

- Python files: `snake_case`
- UI classes: `PascalCase`
- UI methods: `_private_method` for internal callbacks/helpers
- Config keys: `snake_case` in JSON
