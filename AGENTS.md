# VM Sync Tool

## Overview

Windows desktop GUI tool that keeps a Keil firmware project synchronized between the local PC and a VMware Workstation virtual machine. It uses `vmrun.exe` through VMware Tools / VIX, so it does not require network access and the virtual machine NIC can remain disabled.

The intended workflow is:

1. Edit source files on the local PC.
2. Sync the project into the virtual machine.
3. Build manually in Keil inside the virtual machine.
4. Pull the generated `.bin` back to a local PC output directory.

## Current Status

- `vmrun.exe` auto-detection is implemented and persisted in `config.json`.
- VMX preflight verifies that the configured VMX is the virtual machine currently listed by `vmrun list`.
- Configuration is now shared virtual machine settings plus a `projects` list. VMX, virtual machine username, and virtual machine password are shared; each project owns `enabled`, Local PC project path, virtual machine project path, `.bin` relative path, and firmware return directory.
- Legacy single-project configs are migrated into project 1 automatically. When legacy project fields and `projects` coexist, `projects` wins, and saves write the new structure.
- The UI supports up to two project panes in this release. Project 2 is enabled with `添加同步项目`; disabling project 2 hides its pane and shrinks the window back to the single-project layout.
- Project 1 and project 2 have independent start/pause, save/check, full sync/cancel, logs, `.bin` hints, watchdog state, upload queues, hash baselines, `.bin` baselines, and return directories.
- The top start button is atomic across enabled projects: if any enabled project fails preflight, no project starts, and projects that passed log that they are waiting for the failing project to be fixed.
- Local-PC-to-virtual-machine incremental sync is implemented with watchdog and a 500 ms debounce.
- Local-PC-to-virtual-machine incremental sync copies into a virtual-machine-side temp file in the target directory, then moves it over the destination to avoid direct half-writes to the final file.
- Full sync is implemented as zip upload plus guest-side PowerShell extraction into a virtual machine temp directory, followed by `Copy-Item -Recurse -Force` into the project directory.
- Full sync packages project files except directories named `Output` and preserves empty directories in the archive.
- Full sync does not fall back to slow per-file copy. If zip upload/extract/cover fails, it reports the error, stops, and attempts to clean virtual machine temp files/directories.
- Full sync has cooperative cancellation. The UI disables config/start, changes the full-sync button to cancel, and cancellation waits for the current `vmrun` operation before cleanup.
- Virtual-machine-to-local-PC `.bin` return is implemented and has been confirmed to transfer a file from the running virtual machine.
- `.bin` polling defaults to 1 second. Old configs with `poll_interval_sec = 3` are upgraded to `1`.
- Runtime UI language supports Chinese and English. Old configs without `language` are initialized from Windows UI language APIs first, then Python locale fallback; manual switching saves `zh` or `en` to `config.json`.
- After sync starts, the first `.bin` poll records the current virtual machine `.bin` as a startup baseline and does not copy it back immediately.
- Start from the UI saves the current entry values, runs save/check preflight, then reuses that result only if the saved preflight config snapshot still matches the current config. This avoids repeating slow virtual machine checks before the first baseline poll without allowing stale UI/config values to bypass validation.
- Start records a startup watch window before building the local PC hash baseline; source files detected as modified during that baseline pass are enqueued after the observer starts.
- After the startup baseline is recorded, the first timestamp-only update of that same `.bin` is copied back once even if the content hash is unchanged. This covers users who accidentally compiled before start, then immediately rebuild after start with identical output.
- Start runs the same save/check flow as `保存并检测` before the sync worker is launched. If preflight or `.bin` target validation fails, sync does not start.
- Saving from the UI logs that paths have been saved to `config.json`, including the resolved config file path.
- `.bin` is copied back only when content hash changes. If the timestamp changes but content is identical, the app logs a skipped update once for that file state and sends the same readiness-style local PC/tray notification.
- Stop requests suppress late `.bin` poller logs, skip notifications, and guest-to-local-PC copies after the service has been stopped.
- Stale run-token checks suppress late incremental moves, `.bin` local PC overwrites, `.bin` logs/notifications, and stale readiness state after a project is paused or restarted.
- Incremental upload timeout suspends only the affected project's incremental queue and surfaces `部分异常` / `Partially degraded` in the top status when applicable.
- `vmrun` subprocess text output is decoded with `errors="replace"` so invalid VMware/guest bytes do not crash reader threads.
- The UI currently starts at `700x955`, has minimum size `640x720`, widens to `1180x955` with minimum size `1040x740` when project 2 is enabled, and has no maximum-size cap.
- The tray menu is bilingual/dynamic: status, show, start/pause, and quit labels update after language switching and can show running, partially running, or partially degraded state. The start/pause menu item is bold/default in the menu, while tray icon activation itself restores the window instead of toggling sync.
- The source repository has bilingual project documentation: Chinese `README.md` and English `README.en.md`.
- The release user guide is also bilingual: `docs/USER_GUIDE.md` and `docs/USER_GUIDE.en.md`.
- `build_release.ps1` builds a folder-based exe release, copies the user guides into `dist\VM Sync\README.md` and `dist\VM Sync\README.en.md`, rewrites language links for the release package, and creates `dist\VM-Sync-v1.2.1.zip`.
- Local runtime config, release output, build output, caches, and probe logs are intentionally ignored by git.
- Known open issue: window dragging can still feel less responsive than a normal native window on some machines. Do not pause timers, log updates, or polling while dragging, because that makes the app feel frozen.

## Stack

- **Language:** Python 3.12+
- **UI:** CustomTkinter native desktop window plus pystray system tray
- **File watch:** watchdog
- **Virtual machine communication:** `subprocess.run(...)` calling `vmrun.exe`
- **Full sync packaging:** Python `zipfile`, then guest PowerShell `Expand-Archive`

## Repository Layout

This file is meant for local AI/development agents, so it documents both tracked repository files and local ignored files. Ignored files may still be important for debugging a user's machine, but they must not be committed.

Full local workspace layout:

```text
vm-sync-tool/
  .gitignore                                      tracked
  AGENTS.md                                      tracked, local AI/maintainer context
  LICENSE                                        tracked, MIT license
  README.md                                      tracked, Chinese GitHub/developer README
  README.en.md                                   tracked, English GitHub/developer README
  docs/
    USER_GUIDE.md                                tracked, Chinese release user guide source
    USER_GUIDE.en.md                             tracked, English release user guide source
  main.py                                        tracked, app entry point
  ui.py                                          tracked, CustomTkinter UI and tray behavior
  syncer.py                                      tracked, sync engine and vmrun operations
  config_manager.py                              tracked, config model and persistence
  i18n.py                                        tracked, Chinese/English runtime translations
  preflight.py                                   tracked, path/virtual-machine/bin validation
  vmrun_resolver.py                              tracked, vmrun and running virtual machine detection
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
    VM-Sync-v1.2.1.zip                          ignored, generated release archive
    VM Sync/                                     ignored, generated folder-based release
      VM Sync.exe                                ignored, generated executable
      _internal/                                 ignored, bundled runtime/dependencies
      README.md                                  ignored, generated Chinese user guide
      README.en.md                               ignored, generated English user guide
      LICENSE                                    ignored, copied MIT license
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
| `LICENSE` | MIT license text |
| `README.md` | Chinese GitHub/developer-facing project overview |
| `README.en.md` | English GitHub/developer-facing project overview |
| `docs/USER_GUIDE.md` | Chinese end-user guide copied to release `README.md` |
| `docs/USER_GUIDE.en.md` | English end-user guide copied to release `README.en.md` |
| `main.py` | Entry point, single-instance lock on `127.0.0.1:19998`, config load, vmrun/VMX auto-discovery |
| `ui.py` | CustomTkinter UI: `App`, panels, `AutoScrollFrame`, log coloring, status bar, tray icon/menu |
| `syncer.py` | `SyncManager`: watchdog observer, debouncer, vmrun calls, full sync, `.bin` polling/return |
| `config_manager.py` | `ConfigManager` and `Config`: load/save `config.json`, normalize paths/defaults |
| `i18n.py` | Runtime Chinese/English translations and system-language detection |
| `preflight.py` | Path, virtual machine, vmrun, running virtual machine, Keil project, and `.bin` configuration checks |
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
  test_i18n.py
  test_main_single_instance.py
  test_preflight.py
  test_syncer.py
  test_ui_bin_hint.py
  test_ui_full_sync.py
  test_ui_log.py
  test_ui_start_async.py
  test_ui_status_async.py
  test_ui_tray.py
  test_ui_multi_project.py
  test_vmrun_resolver.py
```

Local/generated files that should remain untracked:

| Path | Purpose |
|------|---------|
| `config.json` | Local user configuration persisted by the app; may contain real paths, username, and password. Local AI may inspect it for debugging, but must not commit or expose secrets. |
| `dist/` | Release output generated by `build_release.ps1`, including `dist\VM Sync\` and the generated release zip; use it to test the packaged app locally, but regenerate instead of editing contents by hand. |
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
| `vmx_path` | VMware `.vmx` file for the target virtual machine. Must match a currently running virtual machine from `vmrun list`. |
| `vm_guest_user` | Windows username inside the virtual machine for `vmrun -gu`. |
| `vm_guest_password` | Virtual machine user password for `vmrun -gp`. Blank passwords are blocked because they can trigger VIX crashes/popups. |
| `projects` | List of project configs. This release's UI supports project 1 and project 2, but the file format is list-based for future expansion. |
| `projects[].enabled` | Whether the project participates in top start/preflight and is visible in the UI. Project 1 is always ensured enabled; project 2 defaults disabled. |
| `projects[].host_project_path` | Local PC project root for this project. |
| `projects[].vm_project_path` | Virtual-machine-side project root for this project. Full sync extracts here and incremental sync writes under this root. |
| `projects[].vm_bin_relative_path` | `.bin` path relative to this project's `vm_project_path`. May be an exact `.bin` file or a directory to scan. The UI converts absolute paths under `vm_project_path` into relative paths before saving; absolute paths outside `vm_project_path` remain invalid. |
| `projects[].host_output_path` | Local PC directory where this project's returned `.bin` is written. Created on start if missing. |
| `language` | Runtime UI/log language. `zh` and `en` are supported; missing, blank, or invalid values are initialized from Windows UI language APIs first, then Python locale fallback. |
| `debounce_ms` | Local PC file-change debounce, currently `500`. |
| `poll_interval_sec` | Virtual machine `.bin` poll interval, currently `1`. |
| `watch_extensions` | Incremental local-PC-to-virtual-machine extensions. Includes modern and legacy Keil files. |

Legacy top-level `host_project_path`, `vm_project_path`, `vm_bin_relative_path`, and `host_output_path` are read only for migration when `projects` is absent. Path values are normalized to Windows backslashes when saved.

## Architecture

```text
Startup
  -> load config
  -> migrate legacy single-project fields into projects[0] when needed
  -> normalize paths and runtime defaults
  -> resolve vmrun.exe
  -> verify vmrun list and running VMX during preflight

Local PC edit
  -> per-project Start button saves shared virtual machine + project config and runs save/check preflight first
  -> per-project watchdog
  -> per-project debounce(500 ms)
  -> per-project upload queue and local file hash baseline
  -> source files changed during the startup baseline pass are rechecked and enqueued after the observer starts
  -> vmrun CopyFileFromHostToGuest to a temp file in this project's virtual machine destination directory
  -> guest PowerShell Move-Item -Force to this project's final virtual machine path
  -> this project's virtual machine project directory

Full sync button
  -> save and preflight
  -> zip this project's local PC project excluding `Output` directories
  -> disable config/start and turn the full-sync button into cancel
  -> vmrun CopyFileFromHostToGuest to a virtual machine temp zip
  -> run guest PowerShell Expand-Archive -Force into a virtual machine temp directory
  -> cancellation checkpoints between zip/upload/extract/cover
  -> run guest PowerShell Get-ChildItem -Force plus Copy-Item -Recurse -Force into this project's virtual machine project path
  -> delete guest temp zip/temp extract directory

Keil build in virtual machine
  -> each project service starts quickly and the first poll records that project's existing virtual machine .bin as a baseline
  -> users should start sync before building in Keil; a build made before start is treated as baseline and is not returned immediately
  -> each project polls its configured virtual machine .bin every 1 second
  -> read LastWriteTimeUtc ticks, length, SHA256
  -> vmrun CopyFileFromGuestToHost only when this project's content changes after startup
  -> the first post-baseline timestamp-only update is copied back once even if content is identical
  -> timestamp-only/content-identical changes log once and notify the local PC/tray
  -> stop requests and stale tokens prevent late poller logs, notifications, and copies
  -> this project's local PC output directory
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
dist\VM-Sync-v1.2.1.zip
dist\VM Sync\
  VM Sync.exe
  _internal\
  README.md
  README.en.md
  LICENSE
  config.example.json
```

- `build_release.ps1` copies `docs/USER_GUIDE.md` to release `README.md`, `docs/USER_GUIDE.en.md` to release `README.en.md`, and `LICENSE` to the release folder.
- The build script rewrites guide language links from `USER_GUIDE*.md` to `README*.md` so links work inside the release package.
- The build script also regenerates `dist\VM-Sync-v1.2.1.zip` and prints its SHA256.
- Do not commit `dist/`, `build/`, `config.json`, `__pycache__/`, or `vmrun_probe_result.txt`.
- `config.example.json` stays tracked because it is safe to share and documents the public config shape.

## Full Sync Behavior

- UI button label is `全量同步`.
- Each project has its own full sync button and cancellation state. While a project's full sync is running, that project's config inputs, its disable-project button, and the top start button are disabled, and the project's full-sync button becomes `取消全量同步`.
- Cancel full sync is cooperative: it sets a cancel flag, disables the cancel button as `取消中...`, waits for the current virtual machine operation to finish, then runs cleanup.
- Saves current config before checking.
- Requires the enhanced preflight to pass.
- Shows progress in the log/progress UI instead of logging every file.
- Packages project files under this project's `host_project_path`, not only watched source extensions, but skips any directory named `Output`.
- Preserves empty directories in the full-sync zip so project structures that depend on empty folders are not lost.
- Uploads the zip to a virtual machine temp path, extracts into a virtual machine temp directory, then copies extracted files into this project's `vm_project_path`.
- Matching virtual machine files are overwritten during the final copy step.
- Extra files that already exist in the virtual machine destination are not deleted.
- If cancellation/failure leaves a virtual machine temp path that cannot be cleaned, the log must print the path for manual deletion.
- No slow compatibility fallback is enabled.

## Incremental Sync Behavior

- Start first saves the current UI config, logs the `config.json` save path, and starts only after preflight and `.bin` target validation pass.
- Watches this project's `host_project_path` recursively.
- Debounces changes by `debounce_ms`.
- Debounced local PC changes are enqueued and processed by this project's one incremental copy worker. Do not run many local-PC-to-virtual-machine `vmrun` copies concurrently; VIX can become unstable and show VMware Workstation error dialogs. Cross-project file copy, create, delete, and overwrite `vmrun` calls are serialized with `VMRUN_CALL_LOCK`. Read-only `.bin` target checks and stdout-based guest `.bin` state reads may bypass that lock so two projects can establish startup baselines in parallel.
- On start, the app builds a local PC content signature baseline for watched files. A later file event is uploaded only if the on-disk file content hash changes; timestamp-only/editor probe events are ignored so unsaved VS Code edits are not pushed to the virtual machine.
- Files detected as modified during the startup baseline pass are queued after the watchdog observer starts, reducing the startup window where a just-saved source file could be missed.
- Copies only files whose suffix is in `watch_extensions`.
- Copies each changed file to a temp file in the target virtual machine directory first, then moves it over the final path with guest PowerShell. If the final move fails, it attempts to delete the temp file and logs any leftover path.
- If an incremental `vmrun` upload times out, local-PC-to-virtual-machine incremental uploads for that project are suspended and that project's pending upload queue is cleared. The service logs one actionable error, the top state can show `部分异常`, and the other project keeps running.
- Uses the configured `vmrun_path`; there is no hard-coded business-path entry point.
- All subprocess calls must include `creationflags=subprocess.CREATE_NO_WINDOW` to prevent flashing CMD windows.
- All text-mode `subprocess.run` calls that read VMware output should include `errors="replace"` so unexpected guest/VMware bytes cannot raise `UnicodeDecodeError`.

## `.bin` Return Behavior

- `projects[].vm_bin_relative_path` is relative to that project's `projects[].vm_project_path`.
- The UI normalizes path entries to Windows backslashes. If the user pastes a virtual machine `.bin`/Output absolute path under `vm_project_path`, save/start converts it to a relative path and writes the converted value back to the entry and `config.json`.
- If it points to an exact `.bin`, the app uses only that file.
- If it points to a directory with one `.bin`, the app auto-resolves that one file, logs the selected relative file, fills the config entry with the exact relative `.bin` path, and saves it to `config.json`.
- If it points to a directory with multiple `.bin` files, save/check and start are blocked and the log asks the user to fill the exact file name.
- The app must not default to project-specific names such as `RL6492_Project.bin`.
- The guest file state is `(LastWriteTimeUtc.Ticks, Length, SHA256)`.
- On the first poll after service start, an existing virtual machine `.bin` becomes the baseline and is ignored until it changes after startup.
- The baseline log should explain that users should compile after start. The first post-baseline timestamp update with identical content is still returned once, then later identical-content updates are skipped as usual.
- After a `.bin` is successfully copied back, a short post-copy timestamp drift window suppresses same-hash timestamp-only notifications. This avoids noisy "content unchanged" logs caused by virtual machine filesystem or copy timing immediately after a real return.
- If guest file state cannot be read while establishing the startup baseline, the app copies the existing virtual machine `.bin` to a local temp file only to calculate a signature; it still does not overwrite `host_output_path`.
- If the timestamp changes but the content hash is identical, the app logs one skipped overwrite for that file state and shows a local PC/tray notification.
- After a project `stop()` is requested, in-flight `.bin` checks for that project must not emit late skip logs/notifications or copy guest files back to the local PC. Stale run tokens are checked before logging, notifying, and replacing local output.
- If stdout from guest PowerShell is unreliable, the app uses one guest temp sidecar file from `CreateTempfileInGuest`, copies it back, parses it, and deletes it when sync stops/quits.
- Guest state sidecar files must not be created in the project `Output` directory.

## Preflight Rules

General preflight is shared by `保存并检测`, start/pause, and full sync. `保存并检测` and start save the current UI config first and log the `config.json` path. Save/check and start also validate the guest `.bin` target uniqueness:

- `vmrun_path` must be configured and exist.
- `vmrun list` must complete without timeout/error.
- `vmx_path` must exist.
- Configured `vmx_path` must match a currently running VMX by normalized absolute path, not just file name.
- Virtual machine guest username and password are required.
- Each enabled project's `host_project_path` must exist and be a directory.
- Keil project detection accepts `.uvprojx`, `.uvoptx`, `.uvproj`, `.uvopt`, `.uv2`, and `.opt`.
- Each enabled project's `vm_project_path` must not be a disk root or broad risky system path.
- Each enabled project's `host_output_path` must be a directory if it already exists.
- Each enabled project's `vm_bin_relative_path` is required and must not remain absolute after UI normalization. Absolute paths inside that project's `vm_project_path` are converted before preflight; absolute paths outside `vm_project_path` are rejected.
- A `.bin` name that does not match the detected primary Keil project name is a warning, not a blocking error.
- When more than one project is enabled, Local PC project paths and virtual machine project paths must not overlap. This applies to top start and single-project start/check paths so independent transfers cannot point into each other.

## UI Layout

```text
Title bar: status dot, "VM SYNC", compact `中 / EN` language switch, state text
Control panel: start/pause, full sync, counters/status
AutoScrollFrame: auto-hiding page scrollbar
  - Shared virtual machine config panel: VMX, virtual machine username, virtual machine password
  - `添加同步项目` / Add Sync Project button when project 2 is disabled
  - Project 1 pane: project config, per-project start/pause, save/check, full sync/cancel, log
  - Project 2 pane: same controls and log, shown only when enabled
Status bar: virtual machine status, vmrun status, poll interval
```

UI notes:

- `AutoScrollFrame` replaces `CTkScrollableFrame`; CTk's built-in scroll frame did not auto-hide the scrollbar.
- `AutoScrollFrame` should not call `update_idletasks()` inside `<Configure>` handlers.
- Event polling is capped by `App.EVENTS_PER_TICK = 40`.
- Stats labels should only update when displayed values change.
- Log text color is per log line/event. A red or green message must not recolor previous messages.
- Log event icons should use the semantic emoji constants in `LogIcon` instead of ad hoc symbols such as `✓`, `✗`, or `⏹`. Log wording should be concise and consistent: state what happened, include the relevant path/object when useful, and give a concrete recovery action for warnings/errors.
- Config inputs are disabled while sync/full-sync is running.

## Window and Tray Lifecycle

- Close button hides the window with `withdraw()`; sync keeps running.
- Tray left-click/double-click or `显示窗口` restores the window. Tray icon activation must not toggle sync.
- Tray menu dynamically shows current state, start/pause state, show-window, and quit labels in the current language. Status can show running, partially running, or partially degraded. Start/pause is the bold/default menu item; show-window is not bold.
- Tray `退出` stops sync, deletes the guest state sidecar if present, removes the tray icon, and quits the process.
- The tray icon appears on startup and persists until `退出`.

## Hard Constraints

- Single instance uses socket bind `127.0.0.1:19998`.
- Do not use `SO_REUSEADDR` for the single-instance socket on Windows.
- All `subprocess.run` calls must include `creationflags=subprocess.CREATE_NO_WINDOW`.
- Text-mode `subprocess.run` calls that read `vmrun` output must include `errors="replace"`.
- Font family: `Microsoft YaHei UI` for normal UI and `Microsoft YaHei` for log/monospace-style text.
- Do not use network sync. The tool is designed around VMware Tools / `vmrun.exe`.
- Keep UI responsive. Avoid blocking vmrun calls on the Tk main thread.
- Do not block `SyncManager.start()` on startup `.bin` hashing/copying; baseline work belongs in the poller after the service reports running.
- Do not reintroduce "pause timer/log/polling while dragging" as a drag-lag workaround.

## Verification Commands

Run these after code changes:

```powershell
python -m unittest discover -v
python -m py_compile main.py config_manager.py i18n.py syncer.py ui.py preflight.py vmrun_resolver.py tools/vmrun_probe.py tests/test_config_manager.py tests/test_i18n.py tests/test_main_single_instance.py tests/test_preflight.py tests/test_syncer.py tests/test_ui_bin_hint.py tests/test_ui_full_sync.py tests/test_ui_log.py tests/test_ui_start_async.py tests/test_ui_status_async.py tests/test_ui_tray.py tests/test_ui_multi_project.py tests/test_vmrun_resolver.py
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
