# VM Sync Tool

Language: [中文](README.md) | [English](README.en.md)

VM Sync Tool is a Windows desktop utility for synchronizing a Keil firmware project between your local PC and a VMware Workstation virtual machine. It operates virtual machine files through VMware `vmrun.exe` and VMware Tools, so it does not rely on shared folders, network drives, or a virtual machine network adapter.

This software was written, debugged, and documented by the author with assistance from Codex and Claude Code.

Current release: `v1.3.0`

Typical workflow:

1. Edit the Keil project source code on the local PC.
2. Sync the project into the virtual machine.
3. Build manually with Keil inside the virtual machine.
4. Pull the generated `.bin` firmware back to the local PC.

## What's New in v1.3.0

- Adds named sync profiles that can be created, switched immediately, saved, renamed, and deleted from the main window.
- Gives the new-profile dialog explicit Create Profile and Cancel actions, with Copy Current and Blank Profile sources.
- Saves configuration atomically, keeps `config.json.bak`, preserves damaged input, and restores the backup when possible.
- Closes the profile dropdown on focus loss, minimization, and tray hiding; the list shows up to eight records and scrolls beyond that limit.
- Fixes high-DPI dropdown width, height, text clipping, border overlap, and rounded-corner artifacts while preserving gray hover feedback.
- Centralizes `vmrun` output decoding so Chinese guest paths and PowerShell errors remain readable.

## Features

- Automatically detects and saves the `vmrun.exe` path.
- Verifies that the configured `.vmx` is the virtual machine currently running in `vmrun list`.
- Creates, names, saves, loads, renames, and deletes multiple sync profiles directly in the main window. Each profile contains the shared virtual machine settings and both project slots and remains available after restart through `config.json`.
- Supports watching two independent Keil projects under the same virtual machine and the same virtual machine account. Project 1 and Project 2 each keep their own Local PC project path, virtual machine project path, `.bin` relative path, and firmware return directory.
- Legacy single-project `config.json` files are migrated into Project 1 automatically. New configs use a `projects` list so future multi-project expansion is easier to maintain.
- Project 1 and Project 2 can each start, pause, save/check, full-sync, cancel full-sync, and show logs independently; the top controls can still start or pause all enabled projects.
- Performs full project sync by uploading a zip archive and extracting it inside the virtual machine; `Output` directories are skipped and empty directories are preserved.
- Watches Local PC project file changes and incrementally syncs matching file extensions into the virtual machine.
- Incremental sync writes to a temporary file in the virtual machine destination directory first, then moves it over the final file to reduce half-written target files if interrupted.
- During startup, saved file changes detected in the startup watch window are queued after the observer is ready, reducing missed uploads when a file is edited immediately after Start.
- Watches the configured virtual machine `.bin` output and pulls it back to the local PC only when the file content changes.
- Records the existing virtual machine `.bin` as a startup baseline, preventing old firmware from immediately overwriting the local PC output.
- The two projects have separate watchers, upload queues, hash baselines, `.bin` baselines, return directories, and log panes. File copy, create, delete, and overwrite `vmrun` operations are serialized to reduce VMware VIX instability, while read-only `.bin` target checks and state reads can run in parallel.
- Clicking Start first saves the configuration and runs the same checks as "Save and Check"; sync is not started if the checks fail.
- The top Start All action is atomic: if any enabled project fails preflight, neither project starts, and the project that passed logs that it is waiting for the failed project to be fixed.
- Configuration saves are logged with the `config.json` path.
- `.bin` timestamp-only updates with unchanged content are skipped and reported through a tray notification.
- During full sync, configuration fields and Start are disabled, the full-sync button changes to Cancel Full Sync, and cancellation waits for the current virtual machine operation before cleanup.
- Supports Chinese/English UI switching. First launch prefers the Windows display/UI language, and manual changes are remembered.
- Supports system tray operation, so the sync service can continue after the window is hidden. Single-clicking or double-clicking the tray icon only restores the window; the right-click menu can start/pause sync, show the window, or exit, and follows the selected language while reporting running, partially running, or partially degraded state.
- `vmrun` subprocesses run in the background, and VMware output is decoded with replacement for invalid bytes so command windows and decode errors do not interrupt normal use.
- Stops sync threads and cleans temporary virtual machine state files when the application exits.

## Requirements

- Windows.
- VMware Workstation.
- VMware Tools installed in the target virtual machine.
- A target Windows virtual machine that can boot normally and reach the desktop.
- Keil MDK installed and usable inside the virtual machine.
- A Windows account inside the virtual machine with a password, accessible through `vmrun -gu/-gp`.

This tool does not install VMware Workstation, VMware Tools, or Keil, and it does not create virtual machines.

## Usage Entry Points

Regular users should download the release package: [VM-Sync-v1.3.0.zip](https://github.com/Expelliarmus-Lai/vm-sync-tool/releases/download/v1.3.0/VM-Sync-v1.3.0.zip).

You can also open [GitHub Releases](https://github.com/Expelliarmus-Lai/vm-sync-tool/releases/latest) for the latest version. The release package should look like this:

```text
VM Sync/
  VM Sync.exe
  _internal/
  README.md
  README.en.md
  LICENSE
  config.example.json
```

Run `VM Sync.exe` directly. The `README.md` included in the release package is generated from [docs/USER_GUIDE.md](docs/USER_GUIDE.md), and `README.en.md` is generated from [docs/USER_GUIDE.en.md](docs/USER_GUIDE.en.md). They contain configuration descriptions, first-use steps, sync overwrite rules, and common troubleshooting notes.

Developers should use the source repository and refer to the sections below: [Development](#development), [Diagnostics](#diagnostics), [Testing](#testing), and [Packaging](#packaging).

## Sync Behavior

- **Full sync**: Uploads project files under the Local PC project root except `Output` directories, preserves empty directories, extracts the archive into a virtual machine temporary directory, then copies the extracted files into the virtual machine project path. Virtual machine files with the same relative paths are overwritten; extra files that already exist in the virtual machine are not deleted. Full sync can be cancelled; cancellation runs after the current virtual machine operation and attempts to clean the temporary zip and extraction directory.
- **Incremental sync**: Clicking Start first saves the configuration and runs the same preflight as "Save and Check"; the service starts only after those checks pass. After the sync service starts, newly created or modified local PC files are watched and only extensions configured in `watch_extensions` are processed. Saved changes detected while the startup baseline is being built are queued once the observer is ready. A file is uploaded only when its on-disk content hash changes; editor probes, timestamp-only updates, and unsaved VS Code edits are ignored. Each file is copied to a temporary file in the virtual machine destination directory before it is moved over the final path; deletes, renames, and files outside the extension list are not automatically synced.
- **`.bin` return**: Pulls back only the configured virtual machine `.bin` target. The `.bin` path is ultimately saved relative to the virtual machine project path; if you paste an absolute path under the virtual machine project path, the UI converts it to a relative path and displays Windows backslashes consistently. When the sync service starts, the current virtual machine `.bin` is recorded as a baseline and is not copied back immediately. Later content changes overwrite the same-named file in the Local PC firmware output directory. Files whose timestamp changes but content stays the same are skipped and reported through a tray notification. After sync is stopped, late `.bin` poll results no longer emit logs, notifications, or overwrites.
- **Dual-project watching**: Enable Project 2 with "Add Sync Project". Both projects share the VMX, virtual machine username, and virtual machine password, but project paths, full sync, incremental uploads, `.bin` return, pause/cancel state, and logs are isolated. If enabled projects have overlapping Local PC or virtual machine paths, preflight blocks startup to prevent mixed transfers.
- **Start timing**: Sync the project into the virtual machine first, click Start, then build in Keil. A `.bin` that already exists before Start is treated as the baseline; the first post-baseline timestamp update is copied back once even if the content is unchanged.

For detailed user instructions, see [docs/USER_GUIDE.md](docs/USER_GUIDE.md).

## Source Layout

```text
vm-sync-tool/
  README.md                       Chinese project overview and developer guide
  README.en.md                    English project overview and developer guide
  AGENTS.md                       Maintenance conventions and coding notes
  docs/USER_GUIDE.md              User guide copied into the release package during build
  docs/USER_GUIDE.en.md           English user guide copied into the release package during build
  main.py                         Application entry point and single-instance handling
  ui.py                           CustomTkinter UI, logs, status bar, and tray menu
  syncer.py                       Sync engine, vmrun calls, full sync, and .bin return
  config_manager.py               Config loading/saving and path normalization
  preflight.py                    Path, virtual machine, Keil project, and .bin preflight checks
  vmrun_resolver.py               vmrun detection and running virtual machine parsing
  tools/vmrun_probe.py            vmrun connection diagnostic script
  tests/                          Unit and regression tests
  packaging_hooks/                PyInstaller hook adjustments
  requirements.txt                Runtime dependencies
  requirements-dev.txt            Development and packaging dependencies
  config.example.json             Safe configuration template
  dev_start.cmd                   Source-mode development launcher
  build_release.ps1               Folder-based exe build script
  VM Sync.spec                    PyInstaller build configuration
```

## Development

Install runtime dependencies:

```powershell
python -m pip install -r requirements.txt
```

Run from source:

```powershell
python main.py
```

For local Windows development, you can also double-click `dev_start.cmd`. It starts the application from source and keeps the console open if startup fails, making errors easier to inspect.

In source mode, runtime configuration is saved as `config.json` in the repository working directory. In release mode, runtime configuration is saved next to `VM Sync.exe`. Named sync profiles use stable IDs in the `profiles` list, and `active_profile_id` selects the current profile. Legacy single-project and dual-project configs are migrated into a default profile. The top-level VM and `projects` fields continue to mirror the active profile for compatibility.

Configuration saves use atomic file replacement and keep the previous valid data in `config.json.bak`. If `config.json` is damaged, the application preserves it as `config.json.corrupt`, restores the backup when possible, and reports any save failure in the profile toolbar. All three files may contain the virtual machine password in plaintext and must not be shared or committed.

## Diagnostics

After completing the application configuration, run the diagnostic script to check `vmrun`, virtual machine credentials, and file round-trip capability:

```powershell
python tools\vmrun_probe.py
```

The diagnostic log is written to `vmrun_probe_result.txt`. This file is excluded from version control.

## Testing

Run regression tests:

```powershell
python -m unittest discover -v
```

Compile-check the main modules and higher-risk tests:

```powershell
python -m py_compile main.py config_manager.py i18n.py syncer.py ui.py preflight.py vmrun_resolver.py vmrun_output.py tools/vmrun_probe.py tests/test_config_manager.py tests/test_i18n.py tests/test_main_single_instance.py tests/test_preflight.py tests/test_syncer.py tests/test_ui_bin_hint.py tests/test_ui_full_sync.py tests/test_ui_log.py tests/test_ui_start_async.py tests/test_ui_status_async.py tests/test_ui_tray.py tests/test_ui_multi_project.py tests/test_ui_profiles.py tests/test_vmrun_resolver.py tests/test_vmrun_output.py
```

## Packaging

Install packaging dependencies:

```powershell
python -m pip install -r requirements-dev.txt
```

Build the folder-based Windows exe:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_release.ps1
```

The build output is generated at:

```text
dist\VM Sync\
dist\VM-Sync-v1.3.0.zip
```

Distribute `VM-Sync-v1.3.0.zip`, or distribute the entire `VM Sync` folder. Do not distribute only `VM Sync.exe`, because the executable depends on the adjacent `_internal` directory.

## Repository Maintenance

Local runtime configuration and build outputs are excluded by `.gitignore`, including `config.json`, `dist/`, `build/`, `__pycache__/`, and `vmrun_probe_result.txt`. `config.example.json` is the safe configuration template that remains in the repository.

## License

This project is licensed under the [MIT License](LICENSE).
