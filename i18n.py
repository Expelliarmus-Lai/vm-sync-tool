"""Small bilingual text layer for VM Sync Tool."""

from __future__ import annotations

import locale
import sys

if sys.platform == "win32":
    import ctypes
else:
    ctypes = None


SUPPORTED_LANGUAGES = ("zh", "en")
DEFAULT_LANGUAGE = "zh"


def normalize_language(language: str | None) -> str:
    text = str(language or "").strip().lower()
    if text in SUPPORTED_LANGUAGES:
        return text
    return ""


def _language_from_windows_lcid(lcid: int | None) -> str:
    if lcid is None:
        return ""
    try:
        primary_language_id = int(lcid) & 0x3FF
    except (TypeError, ValueError):
        return ""
    if primary_language_id == 0x04:
        return "zh"
    if primary_language_id == 0x09:
        return "en"
    return ""


def _detect_windows_ui_language() -> str:
    if sys.platform != "win32" or ctypes is None:
        return ""
    try:
        kernel32 = ctypes.windll.kernel32
    except Exception:
        return ""

    for api_name in (
        "GetUserDefaultUILanguage",
        "GetThreadUILanguage",
        "GetUserDefaultLangID",
        "GetSystemDefaultUILanguage",
    ):
        try:
            api = getattr(kernel32, api_name)
            language = _language_from_windows_lcid(api())
        except Exception:
            language = ""
        if language:
            return language
    return ""


def _language_from_locale_name(name: str | None) -> str:
    text = str(name or "").strip().lower().replace("-", "_")
    if not text:
        return ""
    if text.startswith("zh") or "chinese" in text or "中文" in text:
        return "zh"
    if text.startswith("en") or "english" in text:
        return "en"
    return ""


def detect_system_language() -> str:
    windows_language = _detect_windows_ui_language()
    if windows_language:
        return windows_language

    candidates = []
    try:
        candidates.append(locale.getlocale()[0])
    except Exception:
        pass
    try:
        candidates.append(locale.getlocale(locale.LC_CTYPE)[0])
    except Exception:
        pass

    for candidate in candidates:
        language = _language_from_locale_name(candidate)
        if language:
            return language
    return "en"


TRANSLATIONS = {
    "zh": {
        "app.already_running": "VM Sync 已在运行中\n\n请查看系统托盘图标或任务栏",
        "bin.autofill.relative": "已自动补全 .bin 相对路径: {path}",
        "bin.display.empty": "VM .bin 输出位置: —",
        "bin.display.file": "VM .bin 输出文件: {path}",
        "bin.display.dir": "VM .bin 输出目录: {path}",
        "bin.display.detected": "已识别 .bin: {relative}    VM .bin 输出文件: {path}",
        "bin.display.dir_choose_file": "VM .bin 输出目录: {path}    请选择具体 .bin 文件",
        "config.path_missing": "路径不存在",
        "config.vmx_missing": "VMX 文件不存在",
        "dialog.full_sync.title": "确认全量同步",
        "dialog.full_sync.message": "{details}\n\n确认执行全量同步吗？",
        "dialog.preflight.error.title": "路径预检失败",
        "dialog.preflight.warning.title": "路径预检警告",
        "dialog.warning_header": "警告:",
        "filedialog.dir": "选择目录",
        "filedialog.vmx": "选择 VMX 文件",
        "preflight.action.full": "将同步 {count} 个文件",
        "preflight.action.watch": "将监听 {count} 个文件",
        "preflight.bin.absolute": ".bin 相对路径不能是绝对路径",
        "preflight.bin.missing": "请先配置 .bin 相对路径",
        "preflight.bin.name_mismatch": ".bin 文件名与 Keil 工程名不一致，请确认输出路径是否填对",
        "preflight.guest.password_missing": "请先配置 VM 密码；空密码可能触发 VMware VIX 异常弹窗或卡死",
        "preflight.guest.user_missing": "请先配置 VM 用户名，用于 vmrun 在虚拟机内执行文件操作",
        "preflight.host_output.file": "宿主机输出路径不是目录: {path}",
        "preflight.host_output.missing": "请先配置宿主机输出路径",
        "preflight.host_project.file": "宿主机工程路径不是目录: {path}",
        "preflight.host_project.missing": "请先配置宿主机工程路径",
        "preflight.host_project.not_found": "宿主机工程路径不存在: {path}",
        "preflight.keil.not_found": "未找到 Keil 工程文件 (.uvprojx/.uvoptx/.uvproj/.uvopt/.uv2/.opt)，请确认宿主机工程路径是否正确",
        "preflight.summary.project": "工程文件: {project}",
        "preflight.summary.project.none": "未发现",
        "preflight.summary.source": "来源: {path}",
        "preflight.summary.target": "目标: VM {path}",
        "preflight.summary.output": "输出文件: {path}",
        "preflight.vm_project.danger": "VM 工程路径过宽，容易误覆盖: {path}",
        "preflight.vm_project.missing": "请先配置 VM 工程路径",
        "preflight.vm_project.root": "VM 工程路径不能是磁盘根目录",
        "preflight.vmrun.list_failed": "vmrun list 执行失败: {error}",
        "preflight.vmrun.list_timeout": "vmrun list 执行超时: {error}\n请确认 VMware Workstation 已打开且虚拟机已启动；如果仍超时，建议重启 VMware Workstation 或 VMware Authorization Service 后再试。",
        "preflight.vmrun.missing": "请先配置 vmrun.exe 路径",
        "preflight.vmrun.not_found": "vmrun.exe 不存在: {path}",
        "preflight.vmx.missing": "请先配置 VMX 路径",
        "preflight.vmx.not_found": "VMX 文件不存在: {path}",
        "preflight.vmx.not_running": "配置的 VMX 当前未运行，请先启动对应虚拟机",
        "sync.autoselect_bin": "已自动选择唯一 .bin 文件: {path}",
        "sync.bin_check_timeout": "VM .bin 文件检测超时: {path}",
        "sync.bin_dir_read_failed": "无法读取 VM .bin 目录: {path}: {error}",
        "sync.bin_file_missing_with_choices": "VM .bin 文件不存在: {path}；当前目录可选: {choices}",
        "sync.bin_file_missing_no_choices": "VM .bin 文件不存在: {path}；当前目录没有 .bin 文件",
        "sync.bin_missing": "未找到 VM .bin: {path}",
        "sync.bin_multiple": "VM 目录下有多个 .bin，请在配置面板的“.bin 相对路径”填写完整文件名，例如: {examples}",
        "sync.bin_poll_exception": ".bin 轮询异常: {error}",
        "sync.bin_unchanged": "检测到 .bin 时间更新但内容未变化: {filename}。已跳过覆盖。",
        "sync.cleanup_full_failed": "VM 临时路径清理失败: {path}。处理方法: 在 VM 中手动删除该路径。",
        "sync.cleanup_tmp_failed": "VM 临时文件清理失败: {path}。处理方法: 在 VM 中手动删除该文件后重试。",
        "sync.create_output_failed": "无法创建输出目录: {error}。处理方法: 检查路径权限，或手动创建该目录后重试。",
        "sync.full.cancel_progress": "全量同步已取消: {message}",
        "sync.full.cancel_requested": "已请求取消全量同步: 正在等待当前 VM 文件操作完成后清理",
        "sync.full.cancel_wait": "正在取消全量同步，等待当前操作完成",
        "sync.full.cancelled_before_upload": "上传前收到取消请求，未上传压缩包，未修改 VM 工程目录。",
        "sync.full.cancelled_after_upload": "上传后收到取消请求，已停止解压和覆盖，正在清理 VM 临时文件。",
        "sync.full.cancelled_before_extract": "解压前收到取消请求，未覆盖 VM 工程目录，正在清理 VM 临时文件。",
        "sync.full.cancelled_before_cover": "覆盖前收到取消请求，目标工程未被覆盖，正在清理 VM 临时文件。",
        "sync.full.cancelled_after_cover": "覆盖阶段收到取消请求，当前覆盖已完成，正在清理临时文件。",
        "sync.full.confirm_cancelled": "已取消全量同步: 用户未确认执行，未修改 VM 工程目录。",
        "sync.full.create_dir_failed": "创建 VM 工程目录失败: {error}。处理方法: 检查 VM 工程路径、用户权限和 VMware Tools 状态。",
        "sync.full.create_stage_failed": "创建 VM 临时解压目录失败: {error}。处理方法: 检查 VM 临时目录权限，或重启 VMware Tools 后重试。",
        "sync.full.done": "全量同步完成: 已同步 {count} 个文件",
        "sync.full.done_progress": "全量同步完成 ({done}/{total})",
        "sync.full.empty": "没有找到需要同步的文件。处理方法: 检查宿主机工程目录是否为空。",
        "sync.full.empty_progress": "没有需要同步的文件",
        "sync.full.extract_failed": "VM 内解压失败: {error}。处理方法: 检查 VM 磁盘空间、PowerShell Expand-Archive 是否可用。",
        "sync.full.failed_progress": "全量同步失败: {message}",
        "sync.full.host_missing": "宿主机工程路径不存在，无法全量同步。处理方法: 检查路径后重新保存配置。",
        "sync.full.missing_credentials": "缺少 VM 用户名或密码。处理方法: 在配置栏填写虚拟机 Windows 用户名和密码；不要使用空密码。",
        "sync.full.missing_host": "缺少宿主机工程路径。处理方法: 在配置栏选择宿主机 Keil 工程目录。",
        "sync.full.missing_vm_project": "缺少 VM 工程路径。处理方法: 填写虚拟机内的工程目录。",
        "sync.full.missing_vmx": "缺少 VMX 路径。处理方法: 在配置栏选择目标虚拟机的 .vmx 文件。",
        "sync.full.package_ready": "压缩包已生成: {size:.1f} MB",
        "sync.full.start": "全量同步开始: 准备打包 {count} 个文件",
        "sync.full.step_cleanup": "正在清理临时文件",
        "sync.full.step_compress": "正在压缩工程文件",
        "sync.full.step_cover": "正在覆盖 VM 工程目录",
        "sync.full.step_create_dir": "正在创建 VM 目标目录",
        "sync.full.step_create_stage": "正在创建 VM 临时解压目录",
        "sync.full.step_extract": "正在 VM 临时目录内解压",
        "sync.full.step_files": "准备文件列表",
        "sync.full.step_upload": "正在上传压缩包到 VM 临时目录",
        "sync.full.timeout": "全量同步超时: {error}。处理方法: 检查 VM 是否卡住，必要时重启 VMware Tools 后重试。",
        "sync.full.upload_failed": "上传压缩包到 VM 失败: {error}。处理方法: 检查 VM 是否运行、VMware Tools 是否正常，并确认 VM 临时目录可写。",
        "sync.full.cover_failed": "VM 工程覆盖失败: {error}。处理方法: 检查目标文件是否被 Keil 或其他程序占用，关闭占用程序后重试。",
        "sync.guest_auth_failed": "VM 用户名/密码无效或未配置，无法在虚拟机内执行命令",
        "sync.host_invalid": "宿主机工程路径无效: {path}。处理方法: 检查路径是否存在并重新保存配置。",
        "sync.incremental_suspended": "增量同步已暂停: vmrun 执行超时，后续文件未继续上传。出错文件: {filename}。处理方法: 先暂停脚本，确认 VM 可操作或重启 VMware Tools，再重新启动同步。",
        "sync.mkdir_failed": "创建 VM 目录失败: {path}。原因: {error}。处理方法: 检查 VM 路径、用户权限和 VMware Tools 状态。",
        "sync.pull_bin_failed": "拉取 .bin 失败: {error}。处理方法: 检查 VM 内 .bin 路径、用户权限和 VMware Tools 状态。",
        "sync.returned_firmware": "已回传固件: {filename} → {path}",
        "sync.service_started": "同步服务已启动",
        "sync.service_stopped": "同步服务已停止",
        "sync.startup_bin_content": "已记录当前 .bin 内容: {filename}。后续内容变化会触发回传。",
        "sync.startup_bin_state": "已记录当前 .bin 状态: {filename}。后续时间更新或内容变化会触发回传。",
        "sync.startup_same_content_copy": "检测到首次记录后 .bin 时间已更新: {filename}。内容未变化，本次仍回传一次。",
        "sync.to_vm": "同步到 VM: {path}",
        "sync.to_vm_done": "已同步到 VM: {path}",
        "sync.to_vm_failed": "同步到 VM 失败: {path}。原因: {error}。处理方法: 检查 VM 是否运行、VMware Tools 是否正常。",
        "sync.file_exception": "同步文件异常: {filename}。原因: {error}",
        "sync.vm_timeout": "vmrun 超时",
        "sync.watch_started": "已开始监听宿主机工程: {path}",
        "sync.write_target_failed": "写入 VM 目标失败: {path}。原因: {error}。处理方法: 检查目标文件是否被占用、VM 权限是否正常。",
        "sync.firmware_ready": "固件已就绪，可烧录",
        "ui.bin.ready": ".bin    就绪 ✓",
        "ui.bin.waiting": ".bin    —",
        "ui.button.cancel_full": "取消全量同步",
        "ui.button.canceling": "取消中...",
        "ui.button.add_project": "添加项目同步",
        "ui.button.clear": "清空",
        "ui.button.full_sync": "全量同步",
        "ui.button.pause": "暂停",
        "ui.button.remove_project": "停用项目 2",
        "ui.button.save_check": "保存并检测",
        "ui.button.start": "启动",
        "ui.config.field.bin": ".bin 相对路径",
        "ui.config.field.host_output": "固件回传目录",
        "ui.config.field.host_project": "宿主机工程路径",
        "ui.config.field.vm_password": "VM 密码",
        "ui.config.field.vm_project": "VM 工程路径",
        "ui.config.field.vm_user": "VM 用户名",
        "ui.config.field.vmx": "VMX 路径",
        "ui.config.placeholder.bin": "相对 VM 工程，如 Output\\RL6492",
        "ui.config.placeholder.host_output": "宿主机固件回传目录",
        "ui.config.placeholder.host_project": "宿主机 Keil 工程根目录",
        "ui.config.placeholder.vm_password": "VM Windows 登录密码",
        "ui.config.placeholder.vm_project": "VM 内工程根目录，如 C:\\project",
        "ui.config.placeholder.vm_user": "VM Windows 登录用户名",
        "ui.config.placeholder.vmx": "当前运行 VM 的 .vmx",
        "ui.config.saved": "路径已保存至 config.json 文件: {path}",
        "ui.config.status.error": "{icon} 已保存，检测失败",
        "ui.config.status.ok": "{icon} 已保存，检测通过",
        "ui.config.status.warning": "{icon} 已保存，有警告",
        "ui.control.synced": "已同步  {count}",
        "ui.control.uptime": "运行时间  {uptime}",
        "ui.control.uptime.empty": "运行时间  —",
        "ui.log.title": "同步日志",
        "ui.preflight.error": "路径预检失败:\n{message}",
        "ui.preflight.ok": "路径预检通过",
        "ui.preflight.warning": "路径预检警告:\n{message}",
        "ui.section.config": "配置",
        "ui.section.project": "项目 {number}",
        "ui.section.vm_shared": "共享 VM 配置",
        "ui.start.failed": "启动同步失败，请查看上方错误并修正配置",
        "ui.start.failed_with_error": "启动同步失败: {error}",
        "ui.start.blocked_by_project": "本项目预检通过，但未启动，因为项目 {number} 配置未通过。请先修正有问题的项目配置后，再重新点击启动全部。",
        "ui.pause.failed": "暂停同步失败: {error}。处理方法: 查看同步状态，必要时退出程序后重新启动。",
        "ui.status.ready": "就绪",
        "ui.status.running": "运行中",
        "ui.status.stopped": "已停止",
        "ui.status.vm.checking": "● 检查 VM...",
        "ui.status.vm.running": "● VM 运行中",
        "ui.status.vm.not_running": "○ VM 未运行",
        "ui.status.vm.unconfigured": "○ 未配置 VMX",
        "ui.status.vm.unknown": "○ VM 状态未知",
        "ui.status.vmrun.ready": "vmrun 就绪",
        "ui.status.vmrun.checking": "vmrun 检查中...",
        "ui.status.vmrun.timeout": "vmrun 检查超时",
        "ui.status.vmrun.unavailable": "vmrun 不可用",
        "ui.status.vmrun.empty": "vmrun —",
        "ui.status.poll": "轮询间隔 {seconds}s",
        "tray.show": "显示窗口",
        "tray.quit": "退出",
        "tray.status.running": "状态：运行中",
        "tray.status.stopped": "状态：已停止",
        "tray.sync.pause": "⏸  暂停同步 (运行中)",
        "tray.sync.start": "▶  启动同步 (已停止)",
        "tray.notify.background": "VM Sync 已在后台运行",
        "tray.notify.bin_ready": "固件已就绪: {filename}",
        "tray.notify.bin_unchanged": "固件内容未变化，已跳过覆盖: {filename}",
    },
    "en": {
        "app.already_running": "VM Sync is already running.\n\nCheck the system tray icon or taskbar.",
        "bin.autofill.relative": "Auto-filled .bin relative path: {path}",
        "bin.display.empty": "VM .bin output: —",
        "bin.display.file": "VM .bin output file: {path}",
        "bin.display.dir": "VM .bin output folder: {path}",
        "bin.display.detected": "Detected .bin: {relative}    VM .bin output file: {path}",
        "bin.display.dir_choose_file": "VM .bin output folder: {path}    Select the exact .bin file",
        "config.path_missing": "Path does not exist",
        "config.vmx_missing": "VMX file does not exist",
        "dialog.full_sync.title": "Confirm Full Sync",
        "dialog.full_sync.message": "{details}\n\nRun full sync now?",
        "dialog.preflight.error.title": "Path Check Failed",
        "dialog.preflight.warning.title": "Path Check Warning",
        "dialog.warning_header": "Warnings:",
        "filedialog.dir": "Select Folder",
        "filedialog.vmx": "Select VMX File",
        "preflight.action.full": "Will sync {count} files",
        "preflight.action.watch": "Will watch {count} files",
        "preflight.bin.absolute": ".bin relative path cannot be an absolute path",
        "preflight.bin.missing": "Configure the .bin relative path first",
        "preflight.bin.name_mismatch": ".bin file name does not match the Keil project name. Check the output path.",
        "preflight.guest.password_missing": "Configure the VM password first. Blank passwords can trigger VMware VIX popups or hangs.",
        "preflight.guest.user_missing": "Configure the VM username first so vmrun can operate files inside the VM",
        "preflight.host_output.file": "Host output path is not a folder: {path}",
        "preflight.host_output.missing": "Configure the host output path first",
        "preflight.host_project.file": "Host project path is not a folder: {path}",
        "preflight.host_project.missing": "Configure the host project path first",
        "preflight.host_project.not_found": "Host project path does not exist: {path}",
        "preflight.keil.not_found": "No Keil project file found (.uvprojx/.uvoptx/.uvproj/.uvopt/.uv2/.opt). Check the host project path.",
        "preflight.summary.project": "Project files: {project}",
        "preflight.summary.project.none": "none",
        "preflight.summary.source": "Source: {path}",
        "preflight.summary.target": "Target: VM {path}",
        "preflight.summary.output": "Output file: {path}",
        "preflight.vm_project.danger": "VM project path is too broad and may overwrite unintended files: {path}",
        "preflight.vm_project.missing": "Configure the VM project path first",
        "preflight.vm_project.root": "VM project path cannot be a drive root",
        "preflight.vmrun.list_failed": "vmrun list failed: {error}",
        "preflight.vmrun.list_timeout": "vmrun list timed out: {error}\nMake sure VMware Workstation is open and the VM is running. If it still times out, restart VMware Workstation or VMware Authorization Service and try again.",
        "preflight.vmrun.missing": "Configure the vmrun.exe path first",
        "preflight.vmrun.not_found": "vmrun.exe does not exist: {path}",
        "preflight.vmx.missing": "Configure the VMX path first",
        "preflight.vmx.not_found": "VMX file does not exist: {path}",
        "preflight.vmx.not_running": "The configured VMX is not running. Start the target VM first.",
        "sync.autoselect_bin": "Auto-selected the only .bin file: {path}",
        "sync.bin_check_timeout": "VM .bin file check timed out: {path}",
        "sync.bin_dir_read_failed": "Cannot read VM .bin folder: {path}: {error}",
        "sync.bin_file_missing_with_choices": "VM .bin file does not exist: {path}. Available .bin files in this folder: {choices}",
        "sync.bin_file_missing_no_choices": "VM .bin file does not exist: {path}. This folder has no .bin files.",
        "sync.bin_missing": "No VM .bin found: {path}",
        "sync.bin_multiple": "Multiple .bin files were found in the VM folder. In the config panel, fill the exact file name in '.bin relative path', for example: {examples}",
        "sync.bin_poll_exception": ".bin polling error: {error}",
        "sync.bin_unchanged": "Detected .bin timestamp update with unchanged content: {filename}. Skipped overwrite.",
        "sync.cleanup_full_failed": "Failed to clean VM temp path: {path}. Fix: delete this path manually inside the VM.",
        "sync.cleanup_tmp_failed": "Failed to clean VM temp file: {path}. Fix: delete this file manually inside the VM and retry.",
        "sync.create_output_failed": "Cannot create output folder: {error}. Fix: check folder permissions or create it manually and retry.",
        "sync.full.cancel_progress": "Full sync cancelled: {message}",
        "sync.full.cancel_requested": "Full sync cancellation requested: waiting for the current VM file operation before cleanup",
        "sync.full.cancel_wait": "Cancelling full sync; waiting for the current operation to finish",
        "sync.full.cancelled_before_upload": "Cancel requested before upload. The zip was not uploaded and the VM project folder was not modified.",
        "sync.full.cancelled_after_upload": "Cancel requested after upload. Extraction and overwrite were skipped; cleaning VM temp files.",
        "sync.full.cancelled_before_extract": "Cancel requested before extraction. The VM project folder was not overwritten; cleaning VM temp files.",
        "sync.full.cancelled_before_cover": "Cancel requested before overwrite. The target project was not overwritten; cleaning VM temp files.",
        "sync.full.cancelled_after_cover": "Cancel requested during overwrite. The current overwrite finished; cleaning temp files.",
        "sync.full.confirm_cancelled": "Full sync cancelled: user did not confirm. The VM project folder was not modified.",
        "sync.full.create_dir_failed": "Failed to create VM project folder: {error}. Fix: check the VM project path, user permissions, and VMware Tools state.",
        "sync.full.create_stage_failed": "Failed to create VM temp extraction folder: {error}. Fix: check VM temp folder permissions or restart VMware Tools and retry.",
        "sync.full.done": "Full sync complete: synced {count} files",
        "sync.full.done_progress": "Full sync complete ({done}/{total})",
        "sync.full.empty": "No files to sync. Fix: check whether the host project folder is empty.",
        "sync.full.empty_progress": "No files to sync",
        "sync.full.extract_failed": "VM extraction failed: {error}. Fix: check VM disk space and whether PowerShell Expand-Archive is available.",
        "sync.full.failed_progress": "Full sync failed: {message}",
        "sync.full.host_missing": "Host project path does not exist, so full sync cannot run. Fix: check the path and save the config again.",
        "sync.full.missing_credentials": "Missing VM username or password. Fix: fill the VM Windows username and password in the config panel; do not use a blank password.",
        "sync.full.missing_host": "Missing host project path. Fix: select the host Keil project folder in the config panel.",
        "sync.full.missing_vm_project": "Missing VM project path. Fix: fill the project folder inside the VM.",
        "sync.full.missing_vmx": "Missing VMX path. Fix: select the target VM .vmx file in the config panel.",
        "sync.full.package_ready": "Zip package created: {size:.1f} MB",
        "sync.full.start": "Full sync started: packaging {count} files",
        "sync.full.step_cleanup": "Cleaning temp files",
        "sync.full.step_compress": "Compressing project files",
        "sync.full.step_cover": "Overwriting VM project folder",
        "sync.full.step_create_dir": "Creating VM target folder",
        "sync.full.step_create_stage": "Creating VM temp extraction folder",
        "sync.full.step_extract": "Extracting inside the VM temp folder",
        "sync.full.step_files": "Preparing file list",
        "sync.full.step_upload": "Uploading zip to VM temp folder",
        "sync.full.timeout": "Full sync timed out: {error}. Fix: check whether the VM is stuck; restart VMware Tools if needed and retry.",
        "sync.full.upload_failed": "Failed to upload zip to VM: {error}. Fix: check whether the VM is running, VMware Tools is healthy, and the VM temp folder is writable.",
        "sync.full.cover_failed": "Failed to overwrite VM project folder: {error}. Fix: check whether target files are open in Keil or another program, close them, and retry.",
        "sync.guest_auth_failed": "VM username/password is invalid or missing, so commands cannot run inside the VM",
        "sync.host_invalid": "Host project path is invalid: {path}. Fix: check whether the path exists and save the config again.",
        "sync.incremental_suspended": "Incremental sync paused: vmrun timed out, so remaining files were not uploaded. Failed file: {filename}. Fix: pause the script, confirm the VM is responsive or restart VMware Tools, then start sync again.",
        "sync.mkdir_failed": "Failed to create VM folder: {path}. Reason: {error}. Fix: check the VM path, user permissions, and VMware Tools state.",
        "sync.pull_bin_failed": "Failed to pull .bin: {error}. Fix: check the VM .bin path, user permissions, and VMware Tools state.",
        "sync.returned_firmware": "Returned firmware: {filename} -> {path}",
        "sync.service_started": "Sync service started",
        "sync.service_stopped": "Sync service stopped",
        "sync.startup_bin_content": "Recorded current .bin content: {filename}. Later content changes will trigger return.",
        "sync.startup_bin_state": "Recorded current .bin state: {filename}. Later timestamp or content changes will trigger return.",
        "sync.startup_same_content_copy": "Detected .bin timestamp update after startup baseline: {filename}. Content is unchanged; returning it once.",
        "sync.to_vm": "Syncing to VM: {path}",
        "sync.to_vm_done": "Synced to VM: {path}",
        "sync.to_vm_failed": "Failed to sync to VM: {path}. Reason: {error}. Fix: check whether the VM is running and VMware Tools is healthy.",
        "sync.file_exception": "File sync error: {filename}. Reason: {error}",
        "sync.vm_timeout": "vmrun timed out",
        "sync.watch_started": "Started watching host project: {path}",
        "sync.write_target_failed": "Failed to write VM target: {path}. Reason: {error}. Fix: check whether the target file is in use and whether VM permissions are normal.",
        "sync.firmware_ready": "Firmware is ready to flash",
        "ui.bin.ready": ".bin    Ready ✓",
        "ui.bin.waiting": ".bin    —",
        "ui.button.cancel_full": "Cancel Full Sync",
        "ui.button.canceling": "Cancelling...",
        "ui.button.add_project": "Add Project Sync",
        "ui.button.clear": "Clear",
        "ui.button.full_sync": "Full Sync",
        "ui.button.pause": "Pause",
        "ui.button.remove_project": "Disable Project 2",
        "ui.button.save_check": "Save and Check",
        "ui.button.start": "Start",
        "ui.config.field.bin": ".bin relative path",
        "ui.config.field.host_output": "Firmware return folder",
        "ui.config.field.host_project": "Host project path",
        "ui.config.field.vm_password": "VM password",
        "ui.config.field.vm_project": "VM project path",
        "ui.config.field.vm_user": "VM username",
        "ui.config.field.vmx": "VMX path",
        "ui.config.placeholder.bin": "Relative to VM project, e.g. Output\\RL6492",
        "ui.config.placeholder.host_output": "Host folder for returned firmware",
        "ui.config.placeholder.host_project": "Host Keil project root",
        "ui.config.placeholder.vm_password": "VM Windows login password",
        "ui.config.placeholder.vm_project": "VM project root, e.g. C:\\project",
        "ui.config.placeholder.vm_user": "VM Windows login username",
        "ui.config.placeholder.vmx": "Currently running VM .vmx",
        "ui.config.saved": "Paths saved to config.json file: {path}",
        "ui.config.status.error": "{icon} Saved, check failed",
        "ui.config.status.ok": "{icon} Saved, check passed",
        "ui.config.status.warning": "{icon} Saved with warnings",
        "ui.control.synced": "Synced  {count}",
        "ui.control.uptime": "Uptime  {uptime}",
        "ui.control.uptime.empty": "Uptime  —",
        "ui.log.title": "Sync Log",
        "ui.preflight.error": "Path check failed:\n{message}",
        "ui.preflight.ok": "Path check passed",
        "ui.preflight.warning": "Path check warning:\n{message}",
        "ui.section.config": "Config",
        "ui.section.project": "Project {number}",
        "ui.section.vm_shared": "Shared VM Config",
        "ui.start.failed": "Failed to start sync. Check the errors above and fix the config.",
        "ui.start.failed_with_error": "Failed to start sync: {error}",
        "ui.start.blocked_by_project": "This project passed preflight but was not started because project {number} failed configuration checks. Fix the problem project, then start all again.",
        "ui.pause.failed": "Failed to pause sync: {error}. Fix: check sync status, or exit and restart the app if needed.",
        "ui.status.ready": "Ready",
        "ui.status.running": "Running",
        "ui.status.stopped": "Stopped",
        "ui.status.vm.checking": "● Checking VM...",
        "ui.status.vm.running": "● VM running",
        "ui.status.vm.not_running": "○ VM not running",
        "ui.status.vm.unconfigured": "○ VMX not configured",
        "ui.status.vm.unknown": "○ VM status unknown",
        "ui.status.vmrun.ready": "vmrun ready",
        "ui.status.vmrun.checking": "vmrun checking...",
        "ui.status.vmrun.timeout": "vmrun check timed out",
        "ui.status.vmrun.unavailable": "vmrun unavailable",
        "ui.status.vmrun.empty": "vmrun —",
        "ui.status.poll": "Poll interval {seconds}s",
        "tray.show": "Show Window",
        "tray.quit": "Exit",
        "tray.status.running": "Status: Running",
        "tray.status.stopped": "Status: Stopped",
        "tray.sync.pause": "⏸  Pause sync (running)",
        "tray.sync.start": "▶  Start sync (stopped)",
        "tray.notify.background": "VM Sync is running in the background",
        "tray.notify.bin_ready": "Firmware ready: {filename}",
        "tray.notify.bin_unchanged": "Firmware content unchanged, skipped overwrite: {filename}",
    },
}


class Translator:
    def __init__(self, language: str | None = None):
        self.language = normalize_language(language) or DEFAULT_LANGUAGE

    def tr(self, key: str, **kwargs) -> str:
        table = TRANSLATIONS.get(self.language, TRANSLATIONS[DEFAULT_LANGUAGE])
        text = table.get(key)
        if text is None:
            text = TRANSLATIONS[DEFAULT_LANGUAGE].get(key, key)
        if kwargs:
            return text.format(**kwargs)
        return text


def tr(language: str | None, key: str, **kwargs) -> str:
    return Translator(language).tr(key, **kwargs)
