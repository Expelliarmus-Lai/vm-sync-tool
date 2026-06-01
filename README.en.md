# VM Sync Tool

Language: [中文](README.md) | [English](README.en.md)

VM Sync Tool is a Windows desktop utility for synchronizing a Keil firmware project between a host machine and a VMware Workstation virtual machine. It operates VM files through VMware `vmrun.exe` and VMware Tools, so it does not rely on shared folders, network drives, or a VM network adapter.

This software was written, debugged, and documented by the author with assistance from Codex and Claude Code.

Typical workflow:

1. Edit the Keil project source code on the host machine.
2. Sync the project into the virtual machine.
3. Build manually with Keil inside the virtual machine.
4. Pull the generated `.bin` firmware back to the host machine.

## Features

- Automatically detects and saves the `vmrun.exe` path.
- Verifies that the configured `.vmx` is the VM currently running in `vmrun list`.
- Supports watching two independent Keil projects under the same VM and the same VM account. Project 1 and Project 2 each keep their own host project path, VM project path, `.bin` relative path, and firmware return directory.
- Legacy single-project `config.json` files are migrated into Project 1 automatically. New configs use a `projects` list so future multi-project expansion is easier to maintain.
- Project 1 and Project 2 can each start, pause, save/check, full-sync, cancel full-sync, and show logs independently; the top controls can still start or pause all enabled projects.
- Performs full project sync by uploading a zip archive and extracting it inside the VM.
- Watches host project file changes and incrementally syncs matching file extensions into the VM.
- Incremental sync writes to a temporary file in the VM destination directory first, then moves it over the final file to reduce half-written target files if interrupted.
- Watches the configured VM `.bin` output and pulls it back to the host only when the file content changes.
- Records the existing VM `.bin` as a startup baseline, preventing old firmware from immediately overwriting the host output.
- The two projects have separate watchers, upload queues, hash baselines, `.bin` baselines, return directories, and log panes. `vmrun` calls are still serialized to reduce VMware VIX instability.
- Clicking Start first saves the configuration and runs the same checks as "Save and Check"; sync is not started if the checks fail.
- The top Start All action is atomic: if any enabled project fails preflight, neither project starts, and the project that passed logs that it is waiting for the failed project to be fixed.
- Configuration saves are logged with the `config.json` path.
- `.bin` timestamp-only updates with unchanged content are skipped and reported through a tray notification.
- During full sync, configuration fields and Start are disabled, the full-sync button changes to Cancel Full Sync, and cancellation waits for the current VM operation before cleanup.
- Supports Chinese/English UI switching. First launch prefers the Windows display/UI language, and manual changes are remembered.
- Supports system tray operation, so the sync service can continue after the window is hidden. Single-clicking or double-clicking the tray icon only restores the window; the right-click menu can start/pause sync, show the window, or exit, and follows the selected language while reporting running, partially running, or partially degraded state.
- Stops sync threads and cleans temporary VM state files when the application exits.

## Requirements

- Windows.
- VMware Workstation.
- VMware Tools installed in the target VM.
- A target Windows VM that can boot normally and reach the desktop.
- Keil MDK installed and usable inside the VM.
- A Windows account inside the VM with a password, accessible through `vmrun -gu/-gp`.

This tool does not install VMware Workstation, VMware Tools, or Keil, and it does not create virtual machines.

## Usage Entry Points

Regular users should download the release package: [VM-Sync-v1.2.0.zip](https://github.com/Expelliarmus-Lai/vm-sync-tool/releases/download/v1.2.0/VM-Sync-v1.2.0.zip).

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

- **Full sync**: Uploads every file under the host project root, extracts the archive into a VM temporary directory, then copies the extracted files into the VM project path. VM files with the same relative paths are overwritten; extra files that already exist in the VM are not deleted. Full sync can be cancelled; cancellation runs after the current VM operation and attempts to clean the temporary zip and extraction directory.
- **Incremental sync**: Clicking Start first saves the configuration and runs the same preflight as "Save and Check"; the service starts only after those checks pass. After the sync service starts, newly created or modified host files are watched and only extensions configured in `watch_extensions` are processed. A file is uploaded only when its on-disk content hash changes; editor probes, timestamp-only updates, and unsaved VS Code edits are ignored. Each file is copied to a temporary file in the VM destination directory before it is moved over the final path; deletes, renames, and files outside the extension list are not automatically synced.
- **`.bin` return**: Pulls back only the configured VM `.bin` target. The `.bin` path is ultimately saved relative to the VM project path; if you paste an absolute path under the VM project path, the UI converts it to a relative path and displays Windows backslashes consistently. When the sync service starts, the current VM `.bin` is recorded as a baseline and is not copied back immediately. Later content changes overwrite the same-named file in the host firmware output directory. Files whose timestamp changes but content stays the same are skipped and reported through a tray notification. After sync is stopped, late `.bin` poll results no longer emit logs, notifications, or overwrites.
- **Dual-project watching**: Enable Project 2 with "Add Sync Project". Both projects share the VMX, VM username, and VM password, but project paths, full sync, incremental uploads, `.bin` return, pause/cancel state, and logs are isolated. If enabled projects have overlapping host or VM paths, preflight blocks startup to prevent mixed transfers.
- **Start timing**: Sync the project into the VM first, click Start, then build in Keil. A `.bin` that already exists before Start is treated as the baseline; the first post-baseline timestamp update is copied back once even if the content is unchanged.

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
  preflight.py                    Path, VM, Keil project, and .bin preflight checks
  vmrun_resolver.py               vmrun detection and running VM parsing
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

In source mode, runtime configuration is saved as `config.json` in the repository working directory. In release mode, runtime configuration is saved next to `VM Sync.exe`.

## Diagnostics

After completing the application configuration, run the diagnostic script to check `vmrun`, VM credentials, and file round-trip capability:

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
python -m py_compile main.py config_manager.py i18n.py syncer.py ui.py preflight.py vmrun_resolver.py tools/vmrun_probe.py tests/test_config_manager.py tests/test_i18n.py tests/test_main_single_instance.py tests/test_preflight.py tests/test_syncer.py tests/test_ui_bin_hint.py tests/test_ui_full_sync.py tests/test_ui_log.py tests/test_ui_start_async.py tests/test_ui_status_async.py tests/test_ui_tray.py tests/test_ui_multi_project.py tests/test_vmrun_resolver.py
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
dist\VM-Sync-v1.2.0.zip
```

Distribute `VM-Sync-v1.2.0.zip`, or distribute the entire `VM Sync` folder. Do not distribute only `VM Sync.exe`, because the executable depends on the adjacent `_internal` directory.

## Repository Maintenance

Local runtime configuration and build outputs are excluded by `.gitignore`, including `config.json`, `dist/`, `build/`, `__pycache__/`, and `vmrun_probe_result.txt`. `config.example.json` is the safe configuration template that remains in the repository.

## License

This project is licensed under the [MIT License](LICENSE).
