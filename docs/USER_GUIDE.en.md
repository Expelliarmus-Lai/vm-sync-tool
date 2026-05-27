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
  config.example.json
```

Double-click `VM Sync.exe` to start the application. Regular users do not need to install Python or run any bat/cmd/vbs script.

On first run, the application creates `config.json` in the same directory as `VM Sync.exe`. This file stores local paths, VM paths, the VM username, and the VM password. Do not share it publicly.

`config.example.json` is a public template that shows the config file format. The application actually reads from and writes to `config.json`.

## Configuration Fields

After opening the application, fill in the configuration panel and click "保存并检测" (Save and Check).

| Field | Meaning | Example |
|---|---|---|
| VMX path | Path to the VM `.vmx` file. It must be the VM that is currently running. | `D:\VMs\Win10\Windows 10.vmx` |
| VM username | Windows login username inside the VM, used by `vmrun` for file operations. | `h` |
| VM password | Windows login password inside the VM. Blank passwords are not recommended. | `123456` |
| Host project path | The Keil project root that you edit on the host. | `C:\Users\Administrator\Desktop\project` |
| VM project path | The project root inside the VM. Full sync extracts here; incremental sync also writes here. | `C:\Users\h\Desktop\project` |
| `.bin` relative path | The `.bin` file or directory relative to the VM project path. | `Output\RL6492\firmware.bin` |
| Firmware return directory | Host directory where returned `.bin` files are written. | `C:\Users\Administrator\Desktop\bin` |

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

Do not enter an absolute path inside the VM. This field is relative to the "VM project path".

## Basic Workflow

1. Start VMware Workstation and open the target VM desktop.
2. Double-click `VM Sync.exe`.
3. Fill in the configuration fields.
4. Click "保存并检测" (Save and Check).
5. When setting up a project for the first time, click "全量同步" (Full Sync) to copy the whole project into the VM.
6. Click "启动" (Start). The application first saves the configuration and runs the same checks as "保存并检测" (Save and Check). After the checks pass, it begins watching host file changes and VM `.bin` output.
7. After the log records the current `.bin` state, build the project manually with Keil inside the VM.
8. After the `.bin` content changes, the application automatically copies it back to the firmware return directory.

## Full Sync vs Start Sync

### Full Sync

Full sync packages every file under the host project directory, uploads the archive to the VM, and extracts it into the VM project path. Use it when configuring a project for the first time, after large project structure changes, or when files are missing in the VM project directory.

During full sync, the configuration panel and Start button are disabled, and the Full Sync button changes to Cancel Full Sync. When cancelled, the application does not force-kill the current VM file operation. It waits for the current step to finish, stops later steps, and cleans the local temporary zip, VM temporary zip, and VM temporary extraction directory. If cleanup fails, the log prints the temporary path that should be removed manually.

Overwrite rule: VM files with the same relative paths are overwritten by host files. Extra files that already exist in the VM are not deleted. Full sync extracts into a VM temporary directory first, then copies from that temporary directory into the VM project path. In other words, full sync updates matching files from the host but does not clear the VM directory.

### Start Sync

After start sync is enabled, the application does two things:

- Watches host project file changes and incrementally syncs them into the VM.
- Polls the VM `.bin` output file and copies it back to the host when the content changes.

When you click Start, the application first saves the current configuration, logs that the paths have been saved to `config.json`, and runs the same checks as "Save and Check". If the checks fail, sync does not start; fix the configuration according to the log first.

The intended timing is: sync the project files into the VM, click Start, then build in Keil. Do not build first and then start the application expecting the existing `.bin` to be returned; a `.bin` that already exists before Start is recorded as the baseline and is not copied back immediately. If you compile again after Start, the application will copy the `.bin` back once even when the content is unchanged but the timestamp was updated, so repeated builds right after startup still produce a return event.

Incremental sync only handles files that are created or modified on the host, and only when their extensions are included in `watch_extensions`. The app compares the on-disk file content hash and uploads only when the content really changes; editor probes, timestamp-only updates, and unsaved VS Code edits are ignored. Each file is copied to a temporary file in the VM destination directory first, then moved over the final path, reducing the risk of damaging the target file if sync is paused or the app exits. VM files with the same relative paths are overwritten. Deletes, renames, and files outside the extension list are not automatically synced.

`.bin` return only targets one configured `.bin` file. When sync starts, the application records the existing VM `.bin` as a baseline and does not immediately pull it back to overwrite an old host file. After startup, the `.bin` is copied back when its content changes. After the first baseline record, one timestamp-only update with unchanged content is also copied back once; later timestamp-only updates are skipped and reported through a tray notification, similar to the firmware-ready notification. After sync is stopped, late `.bin` poll results no longer emit logs, notifications, or overwrites.

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
