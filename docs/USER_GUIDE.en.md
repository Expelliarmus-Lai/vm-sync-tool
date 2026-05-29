# VM Sync Tool User Guide

Language: [中文](USER_GUIDE.md) | [English](USER_GUIDE.en.md)

VM Sync Tool is a Windows desktop utility for synchronizing a Keil firmware project between a host machine and a VMware Workstation virtual machine. It operates VM files through VMware `vmrun.exe` and VMware Tools, so it does not require network sharing or a VM network adapter.

## Requirements

Before using the tool, make sure the host and VM are ready:

- Windows.
- VMware Workstation.
- VMware Tools installed in the target VM.
- The target VM can boot normally and enter the Windows desktop.
- Keil MDK is installed and usable inside the VM.
- The Windows account inside the VM has a password and can be used with `vmrun -gu/-gp`.

This tool does not install VMware, VMware Tools, or Keil, and it does not create virtual machines.

## Release Package Contents

The release package should contain:

```text
VM Sync/
  VM Sync.exe
  _internal/
  README.md
  README.en.md
  LICENSE
  config.example.json
```

Double-click `VM Sync.exe` to start the application. Regular users do not need to install Python or run any bat/cmd/vbs script.

On first run, the application creates `config.json` in the same directory as `VM Sync.exe`. This file stores local paths, VM paths, the VM username, and the VM password. Do not share it publicly.

`config.example.json` is a public template that shows the config file format. The application actually reads from and writes to `config.json`.

A compact `中 / EN` language switch is available in the upper-right of the window. First launch prefers the Windows display/UI language; after you switch manually, the choice is saved to `config.json` and reused next time.

## Single-Project and Dual-Project Modes

By default, only Project 1 is shown, and the window keeps the same width as the older single-project UI. To watch a second codebase at the same time, click "Add Project Sync"; the window expands to the right with Project 2's configuration and log pane. Clicking "Disable Project 2" pauses Project 2 and returns the window to the single-project layout.

Project 1 and Project 2 share the same VMX, VM username, and VM password. Each project has its own host project path, VM project path, `.bin` relative path, firmware return directory, Start/Pause controls, Save and Check, Full Sync/Cancel, and log pane. Legacy single-project configs are automatically filled into Project 1, and Project 2 starts disabled.

The top Start/Pause controls apply to all enabled projects. When you click the top Start button, startup is atomic: if any enabled project fails preflight, all projects remain stopped. A project that passed preflight will log that it did not start because another project needs to be fixed first. Clicking Start or Pause inside a project pane affects only that project.

## Configuration Fields

After opening the application, fill in the shared VM configuration first, then fill in each project's own configuration and click that project's "保存并检测" (Save and Check).

Shared VM configuration:

| Field | Meaning | Example |
|---|---|---|
| VMX path | Path to the VM `.vmx` file. It must be the VM that is currently running. | `D:\VMs\Win10\Windows 10.vmx` |
| VM username | Windows login username inside the VM, used by `vmrun` for file operations. | `h` |
| VM password | Windows login password inside the VM. Blank passwords are not recommended. | `123456` |

Per-project configuration:

| Field | Meaning | Example |
|---|---|---|
| Host project path | The Keil project root that you edit on the host. | `C:\Users\Administrator\Desktop\project` |
| VM project path | The project root inside the VM. Full sync extracts here; incremental sync also writes here. | `C:\Users\h\Desktop\project` |
| `.bin` relative path | The `.bin` file or directory relative to the VM project path. | `Output\RL6492\firmware.bin` |
| Firmware return directory | Host directory where returned `.bin` files are written. | `C:\Users\Administrator\Desktop\bin` |

The host project paths and VM project paths of two enabled projects must not overlap. For example, do not put Project 2 under Project 1's directory, and do not point both projects at the same VM project folder. Preflight blocks overlapping paths to prevent mixed transfers.

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

If you paste a full absolute path that is under the VM project path, the application converts it to a relative path and displays it with Windows backslashes. For example, `C:\Users\h\Desktop\project\Output\RL6492` is saved as `Output\RL6492`. If the absolute path is outside the VM project path, the check fails; correct either the relative `.bin` path or the VM project path.

## Basic Workflow

1. Start VMware Workstation and open the target VM desktop.
2. Double-click `VM Sync.exe`.
3. Fill in the configuration fields.
4. Click "保存并检测" (Save and Check).
5. When setting up a project for the first time, click "全量同步" (Full Sync) to copy the whole project into the VM.
6. If you need a second codebase, click "Add Project Sync", fill in Project 2's paths, and run Save and Check for Project 2.
7. Click the top Start button to start all enabled projects, or click Start inside one project pane to start only that project. The application first saves the configuration and runs the same checks as Save and Check. After the checks pass, it begins watching host file changes and VM `.bin` output.
8. After the corresponding project log records the current `.bin` state, build that project manually with Keil inside the VM.
9. After the `.bin` content changes, the application automatically copies it back to that project's firmware return directory.

## Full Sync vs Start Sync

### Full Sync

Full sync packages every file under the host project directory, uploads the archive to the VM, and extracts it into the VM project path. Use it when configuring a project for the first time, after large project structure changes, or when files are missing in the VM project directory.

Full sync is independent per project. Project 1's Full Sync uses only Project 1's host and VM project paths; Project 2 behaves the same way. During full sync, that project's configuration panel and the top Start button are disabled, and the Full Sync button changes to Cancel Full Sync. When cancelled, the application does not force-kill the current VM file operation. It waits for the current step to finish, stops later steps, and cleans the local temporary zip, VM temporary zip, and VM temporary extraction directory. If cleanup fails, the log prints the temporary path that should be removed manually.

Overwrite rule: VM files with the same relative paths are overwritten by host files. Extra files that already exist in the VM are not deleted. Full sync extracts into a VM temporary directory first, then copies from that temporary directory into the VM project path. In other words, full sync updates matching files from the host but does not clear the VM directory.

### Start Sync

After start sync is enabled, the application does two things:

- Watches host project file changes and incrementally syncs them into the VM.
- Polls the VM `.bin` output file and copies it back to the host when the content changes.

When you click Start inside one project pane, the application first saves the current configuration, logs that the paths have been saved to `config.json` in that project's log, and runs the same checks as Save and Check. If the checks fail, sync does not start; fix the configuration according to the log first. When you click the top Start button, all enabled projects are checked first. If any one fails, all projects remain stopped so you do not accidentally run with a partial or unsafe configuration.

The intended timing is: sync the project files into the VM, click Start, then build in Keil. Do not build first and then start the application expecting the existing `.bin` to be returned; a `.bin` that already exists before Start is recorded as the baseline and is not copied back immediately. If you compile again after Start, the application will copy the `.bin` back once even when the content is unchanged but the timestamp was updated, so repeated builds right after startup still produce a return event.

Incremental sync only handles files that are created or modified under that project's host path, and only when their extensions are included in `watch_extensions`. The app compares the on-disk file content hash and uploads only when the content really changes; editor probes, timestamp-only updates, and unsaved VS Code edits are ignored. Each file is copied to a temporary file in that project's VM destination directory first, then moved over the final path, reducing the risk of damaging the target file if sync is paused or the app exits. VM files with the same relative paths are overwritten. Deletes, renames, and files outside the extension list are not automatically synced. The two projects have separate upload queues and hash baselines; an incremental upload timeout pauses only the project that hit the error and does not stop the other project.

`.bin` return targets only the `.bin` file configured for that project. When sync starts, the application records the existing VM `.bin` as a baseline and does not immediately pull it back to overwrite an old host file. After startup, the `.bin` is copied back when its content changes. After the first baseline record, one timestamp-only update with unchanged content is also copied back once; later timestamp-only updates are skipped and reported through a tray notification, similar to the firmware-ready notification. After one project is stopped, late `.bin` poll results no longer emit that project's logs, notifications, or overwrites, and they do not affect the other project.

## FAQ

### The application reports that vmrun.exe cannot be found

Make sure VMware Workstation is installed. The application automatically checks common installation paths and `vmrun.exe` in PATH.

### The configured VMX is reported as not running

Start the target VM in VMware Workstation first, and make sure the configured VMX path is the VM that is currently running.

### The VM directory contains multiple `.bin` files

Change the `.bin` relative path from a directory to an exact file name, for example:

```text
Output\RL6492\firmware.bin
```

### The `.bin` is not copied back immediately after start

This is expected. Start sync before building in Keil; a `.bin` that already existed before Start is treated as the baseline and is not copied back immediately. See the `.bin` return rules above.

### The application still runs after closing the window

Closing the window only hides the application to the system tray. Sync continues running. To fully exit, right-click the tray icon and choose "退出" (Exit).

## Source Code and Further Development

If you need to modify the source code or rebuild the application, use the full source repository. The root `README.md` and `README.en.md` include development startup, testing, diagnostics, and packaging instructions.
