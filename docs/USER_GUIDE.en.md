# VM Sync Tool User Guide

Language: [中文](USER_GUIDE.md) | [English](USER_GUIDE.en.md)

VM Sync Tool is a Windows desktop utility for synchronizing a Keil firmware project between your local PC and a VMware Workstation virtual machine. It operates virtual machine files through VMware `vmrun.exe` and VMware Tools, so it does not require network sharing or a virtual machine network adapter.

Applies to version: `v1.3.0`

## v1.3.0 Release Highlights

- Adds named sync profiles that can be created, switched, saved, renamed, and deleted in the main window.
- Adds atomic configuration replacement, backup retention, and damaged-file recovery.
- Limits the profile dropdown to eight visible records with scrolling, and closes it on outside clicks, focus loss, minimization, or tray hiding.
- Fixes the new-profile confirmation action, high-DPI sizing, option clipping, border overlap, and rounded-corner rendering.
- Improves decoding of Chinese virtual machine paths and PowerShell error output.

## Requirements

Before using the tool, make sure the local PC and virtual machine are ready:

- Windows.
- VMware Workstation.
- VMware Tools installed in the target virtual machine.
- The target virtual machine can boot normally and enter the Windows desktop.
- Keil MDK is installed and usable inside the virtual machine.
- The Windows account inside the virtual machine has a password and can be used with `vmrun -gu/-gp`.

This tool does not install VMware, VMware Tools, or Keil, and it does not create virtual machines.

## Release Package Contents

The release package should contain:

```text
VM Sync/
  VM Sync.exe
  _internal/
  README.md
  README.en.md
  CHANGELOG.md
  CHANGELOG.en.md
  LICENSE
  config.example.json
```

Double-click `VM Sync.exe` to start the application. Regular users do not need to install Python or run any bat/cmd/vbs script.

On first run, the application creates `config.json` in the same directory as `VM Sync.exe`. This file stores named sync profiles, local paths, virtual machine paths, the virtual machine username, and the virtual machine password. Do not share it publicly.

Saves use atomic replacement and retain the previous valid configuration as `config.json.bak`. If the main file is damaged, it is preserved as `config.json.corrupt` and the backup is restored when possible. A failed save is shown in the Sync Profiles card. The main, backup, and corrupt files can all contain the password in plaintext, so do not share any of them.

`config.example.json` is a public template that shows the config file format. The application actually reads from and writes to `config.json`.

A compact `中 / EN` language switch is available in the upper-right of the window. First launch prefers the Windows display/UI language; after you switch manually, the choice is saved to `config.json` and reused next time.

## Single-Project and Dual-Project Modes

By default, only Project 1 is shown, and the window keeps the same width as the older single-project UI. The default window size is `700x955`; named profiles, shared virtual machine settings, and project areas are placed on the scrolling page. To watch a second codebase at the same time, click "Add Sync Project"; the window expands to the right with Project 2's configuration and log pane and switches to the `1180x955` dual-project layout. Clicking "Disable Project 2" pauses Project 2 and returns the window to the single-project layout.

Project 1 and Project 2 share the same VMX, virtual machine username, and virtual machine password. Each project has its own Local PC project path, virtual machine project path, `.bin` relative path, firmware return directory, Start/Pause controls, Save and Check, Full Sync/Cancel, and log pane. Legacy single-project configs are automatically filled into Project 1, and Project 2 starts disabled.

The top Start/Pause controls apply to all enabled projects. When you click the top Start button, startup is atomic: if any enabled project fails preflight, all projects remain stopped. A project that passed preflight will log that it did not start because another project needs to be fixed first. Clicking Start or Pause inside a project pane affects only that project.

## Named Sync Profiles

The Sync Profiles card at the top of the scrolling configuration area manages multiple project configurations. Switching, saving, renaming, and deleting stay in the main window; only New opens a compact dialog. Each profile contains the VMX, virtual machine username and password, and the enabled state and paths for Project 1 and Project 2.

- Open Current profile and select a record to switch immediately; there is no separate Load action. If the current fields have unsaved changes, the card offers Save and Load, Discard and Load, or Cancel.
- The current profile name is shown directly in the selector without a duplicate name field. To rename a saved profile, open the list and click its edit button; the list closes and the Current Profile segment switches in place to a name entry with Save and Cancel actions.
- Click New in the selector toolbar to open a compact dialog, enter a name, and choose Copy Current or Blank Profile. After creation, continue editing paths in the existing fields in the main window.
- New, Save, and Delete share the same toolbar as the profile selector. Save stores all current configuration fields; the dropdown's edit action starts renaming in the main toolbar; Delete starts the inline confirmation.
- Delete Profile requires a second inline confirmation, and the application always keeps at least one profile.
- Profile management is disabled while sync, startup checks, or full sync are active. Pause or cancel the current operation before loading or deleting a profile.
- Legacy `config.json` files are migrated into a default profile. On normal exit, the application asks whether to save remaining edits.

The `vmrun.exe` path, UI language, polling interval, and watched extensions are machine-wide settings and do not change when profiles are switched.

## Configuration Fields

After opening the application, fill in the shared virtual machine configuration first, then fill in each project's own configuration and click that project's "保存并检测" (Save and Check).

Shared virtual machine configuration:

| Field | Meaning | Example |
|---|---|---|
| VMX path | Path to the virtual machine `.vmx` file. It must be the virtual machine that is currently running. | `D:\VMs\Win10\Windows 10.vmx` |
| Virtual machine username | Windows login username inside the virtual machine, used by `vmrun` for file operations. | `h` |
| Virtual machine password | Windows login password inside the virtual machine. Blank passwords are not recommended. | `123456` |

Per-project configuration:

| Field | Meaning | Example |
|---|---|---|
| Local PC project path | The Keil project root that you edit on the local PC. | `C:\Users\Administrator\Desktop\project` |
| Virtual machine project path | The project root inside the virtual machine. Full sync extracts here; incremental sync also writes here. | `C:\Users\h\Desktop\project` |
| `.bin` relative path | The `.bin` file or directory relative to the virtual machine project path. | `Output\RL6492\firmware.bin` |
| Firmware return directory | Local PC folder where returned `.bin` files are written. | `C:\Users\Administrator\Desktop\bin` |

The Local PC project paths and virtual machine project paths of two enabled projects must not overlap. For example, do not put Project 2 under Project 1's directory, and do not point both projects at the same virtual machine project folder. Preflight blocks overlapping paths to prevent mixed transfers.

### How to Fill `.bin` Relative Path

The recommended value is the exact `.bin` file:

```text
Output\RL6492\firmware.bin
```

You can also fill in the directory that contains the `.bin`:

```text
Output\RL6492
```

If the directory contains exactly one `.bin`, the application auto-detects it, logs which file was selected, fills the configuration field with the exact relative `.bin` path, and saves it to `config.json`. If it contains multiple `.bin` files, the application will report an error and ask you to choose the exact file name.

If you paste a full absolute path that is under the virtual machine project path, the application converts it to a relative path and displays it with Windows backslashes. For example, `C:\Users\h\Desktop\project\Output\RL6492` is saved as `Output\RL6492`. If the absolute path is outside the virtual machine project path, the check fails; correct either the relative `.bin` path or the virtual machine project path.

## Basic Workflow

1. Start VMware Workstation and open the target virtual machine desktop.
2. Double-click `VM Sync.exe`.
3. Use the default record in Sync Profiles or create a named profile.
4. Fill in the shared virtual machine and project fields, then click Save Profile.
5. Click "保存并检测" (Save and Check) for the relevant project.
6. When setting up a project for the first time, click "全量同步" (Full Sync) to copy the project files into the virtual machine; `Output` directories are skipped and empty directories are preserved.
7. If you need a second codebase, click "Add Sync Project", fill in Project 2's paths, and run Save and Check for Project 2.
8. Click the top Start button to start all enabled projects, or click Start inside one project pane to start only that project. The application first saves the configuration and runs the same checks as Save and Check. After the checks pass, it begins watching Local PC file changes and virtual machine `.bin` output.
9. After the corresponding project log records the current `.bin` state, build that project manually with Keil inside the virtual machine.
10. After the `.bin` content changes, the application automatically copies it back to that project's firmware return directory.

## Full Sync vs Start Sync

### Full Sync

Full sync packages project files under the Local PC project directory except `Output` directories, preserves empty directories, uploads the archive to the virtual machine, and extracts it into the virtual machine project path. Use it when configuring a project for the first time, after large project structure changes, or when files are missing in the virtual machine project directory.

Full sync is independent per project. Project 1's Full Sync uses only Project 1's Local PC and virtual machine project paths; Project 2 behaves the same way. During full sync, that project's configuration panel and the top Start button are disabled, and the Full Sync button changes to Cancel Full Sync. When cancelled, the application does not force-kill the current virtual machine file operation. It waits for the current step to finish, stops later steps, and cleans the local temporary zip, virtual machine temporary zip, and virtual machine temporary extraction directory. If cleanup fails, the log prints the temporary path that should be removed manually.

Overwrite rule: Virtual machine files with the same relative paths are overwritten by Local PC files. Extra files that already exist in the virtual machine are not deleted. Full sync extracts into a virtual machine temporary directory first, then copies from that temporary directory into the virtual machine project path. In other words, full sync updates matching files from the local PC but does not clear the virtual machine directory.

### Start Sync

After start sync is enabled, the application does two things:

- Watches Local PC project file changes and incrementally syncs them into the virtual machine.
- Polls the virtual machine `.bin` output file and copies it back to the local PC when the content changes.

When you click Start inside one project pane, the application first saves the current configuration, logs that the paths have been saved to `config.json` in that project's log, and runs the same checks as Save and Check. If the checks fail, sync does not start; fix the configuration according to the log first. When you click the top Start button, all enabled projects are checked first. If any one fails, all projects remain stopped so you do not accidentally run with a partial or unsafe configuration.

The intended timing is: sync the project files into the virtual machine, click Start, then build in Keil. Do not build first and then start the application expecting the existing `.bin` to be returned; a `.bin` that already exists before Start is recorded as the baseline and is not copied back immediately. If you compile again after Start, the application will copy the `.bin` back once even when the content is unchanged but the timestamp was updated, so repeated builds right after startup still produce a return event.

Incremental sync only handles files that are created or modified under that project's Local PC path, and only when their extensions are included in `watch_extensions`. Saved changes detected while the startup baseline is being built are queued once the observer is ready, reducing missed uploads when a file is edited immediately after Start. The app compares the on-disk file content hash and uploads only when the content really changes; editor probes, timestamp-only updates, and unsaved VS Code edits are ignored. Each file is copied to a temporary file in that project's virtual machine destination directory first, then moved over the final path, reducing the risk of damaging the target file if sync is paused or the app exits. Virtual machine files with the same relative paths are overwritten. Deletes, renames, and files outside the extension list are not automatically synced. The two projects have separate upload queues and hash baselines; an incremental upload timeout pauses only the project that hit the error and does not stop the other project.

`.bin` return targets only the `.bin` file configured for that project. When sync starts, the application records the existing virtual machine `.bin` as a baseline and does not immediately pull it back to overwrite an old local PC file. After startup, the `.bin` is copied back when its content changes. After the first baseline record, one timestamp-only update with unchanged content is also copied back once; later timestamp-only updates are skipped and reported through a tray notification, similar to the firmware-ready notification. After one project is stopped, late `.bin` poll results no longer emit that project's logs, notifications, or overwrites, and they do not affect the other project.

## System Tray

Closing the main window only hides it to the system tray; sync keeps running. Single-clicking or double-clicking the tray icon only restores the main window and does not start or pause sync.

Right-click the tray icon to open the menu. The menu shows the current state and provides Start/Pause Sync, Show Window, and Exit. Start/Pause Sync is the primary menu action and is shown in bold; Show Window is not bold. To fully exit the application, use Exit from the tray right-click menu.

## FAQ

### The application reports that vmrun.exe cannot be found

Make sure VMware Workstation is installed. The application automatically checks common installation paths and `vmrun.exe` in PATH.

### The configured VMX is reported as not running

Start the target virtual machine in VMware Workstation first, and make sure the configured VMX path is the virtual machine that is currently running.

### The virtual machine directory contains multiple `.bin` files

Change the `.bin` relative path from a directory to an exact file name, for example:

```text
Output\RL6492\firmware.bin
```

### The `.bin` is not copied back immediately after start

This is expected. Start sync before building in Keil; a `.bin` that already existed before Start is treated as the baseline and is not copied back immediately. See the `.bin` return rules above.

### The application still runs after closing the window

Closing the window only hides the application to the system tray. Sync continues running. Single-click or double-click the tray icon to show the window again; to fully exit, right-click the tray icon and choose "退出" (Exit).

## Source Code and Further Development

If you need to modify the source code or rebuild the application, use the full source repository. The root `README.md` and `README.en.md` include development startup, testing, diagnostics, and packaging instructions.
