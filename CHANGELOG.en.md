# Changelog

Language: [中文](CHANGELOG.md) | [English](CHANGELOG.en.md)

This file records the main changes in each formal release. See the Git history for implementation-level details and individual commits.

## v1.3.0 - 2026-07-23

### Added

- Added named sync profiles with stable UUIDs, shared VMX/guest credentials, and both project slots.
- Added create, immediate switch, save, rename, and delete actions in the main window. New profiles can copy the current values or start blank.
- Limited the profile dropdown to eight visible records and added scrolling for larger profile sets.
- Added the shared `vmrun_output.py` decoder for UTF-8, UTF-16, Windows host code pages, and GB18030 output returned by VMware and guest PowerShell.

### Improved

- Configuration writes now use a same-directory temporary file and atomic replacement while retaining the previous valid file as `config.json.bak`.
- Damaged main configuration is preserved as `config.json.corrupt` and restored from backup when possible. Failed saves roll back in-memory profile changes and are reported in the UI.
- Switching profiles refreshes shared VM fields, project fields, status checks, logs, and synchronization-manager caches.
- Rename editing now occurs in the main window toolbar for reliable Windows IME candidate placement, focus, and composition font sizing.
- The profile dropdown closes on outside application clicks, focus loss, minimization, or hiding to the system tray.
- Fixed high-DPI double scaling, insufficient option height, clipped text, border overlap, and rounded-corner artifacts in the profile selector and dropdown.
- The Windows popup uses native DWM antialiased rounding while retaining gray selected and hover feedback.
- The new-profile dialog sizes itself from its actual content and keeps explicit Create Profile and Cancel actions visible.
- Background VM status checks validate the configuration revision so stale results from an old VMX cannot overwrite the current status.

### Fixed

- Fixed source startup crashing because global pointer events were registered through the unsupported `CTkFrame.bind_all`; the root window now owns the binding.
- Fixed the profile dropdown remaining visible and clickable after the application was hidden.
- Fixed unfinished profile renames being silently lost during exit.
- Fixed mojibake in Chinese guest paths and PowerShell error output.

### Validation

- 256 automated tests passed.
- The complete `py_compile` check passed.
- The folder-based PyInstaller release build and zip-content checks passed.

## v1.2.1 - 2026-06-02

### Improvements and Fixes

- Hardened dual-project start, pause, full-sync, and virtual-machine shutdown cleanup.
- Added run-token checks that suppress stale incremental overwrites, `.bin` returns, logs, and notifications after pause or restart.
- An incremental upload timeout now suspends only the affected project and reports Partially degraded while the other project continues.
- Refined `.bin` startup baselines, the first same-content timestamp return, and post-copy timestamp-drift suppression.
- Improved tray state, per-project firmware-ready times, and UI feedback after the virtual machine stops.
- Updated dual-project documentation, the public configuration template, and regression coverage.

## v1.2.0 - 2026-05-29

### Added

- Added support for up to two independent Keil synchronization projects under one virtual machine.
- Each project has independent paths, start/pause, save/check, full-sync/cancel, logs, upload queue, hash baseline, and `.bin` return directory.
- Added shared virtual machine settings and Add Sync Project / Disable Project 2 layout controls.
- The top Start All action uses atomic preflight: if either project fails, all projects remain stopped.

### Improved

- Migrated configuration to shared VM fields plus a `projects` list, with automatic migration of legacy single-project configuration.
- Serialized file copy, create, delete, and overwrite `vmrun` operations to reduce VMware VIX concurrency instability.
- Dual-project mode expands to `1180x955`; single-project mode remains `700x955`.

## v1.1.0 - 2026-05-28

- Added runtime Chinese/English switching and automatic system-language detection.
- Added bilingual repository READMEs, user guides, and release documentation.
- Improved the system-tray menu, window icon, and packaging workflow.

## v1.0.0 - 2026-05-27

- Initial formal release.
- Added `vmrun.exe` detection, preflight, incremental sync, full sync, and `.bin` firmware return.
- Added system-tray operation and safe shutdown cleanup.
