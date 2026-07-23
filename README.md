# VM Sync Tool

语言：[中文](README.md) | [English](README.en.md)

Windows GUI for VMware Keil firmware sync and `.bin` return.

VM Sync Tool 是一个 Windows 桌面工具，用于在本机电脑和 VMware Workstation 虚拟机之间同步 Keil 固件工程。工具通过 VMware `vmrun.exe` 和 VMware Tools 操作虚拟机文件，不依赖共享文件夹、网络盘或虚拟机网卡。

本软件由作者在 Codex 和 Claude Code 辅助下编写、调试和整理文档。

当前发行版本：`v1.3.0`

版本修改记录：[中文更新日志](CHANGELOG.md) | [English Changelog](CHANGELOG.en.md)

典型流程：

1. 在本机电脑编辑 Keil 工程源码。
2. 将工程同步到虚拟机。
3. 在虚拟机里用 Keil 手动编译。
4. 将生成的 `.bin` 固件回传到本机电脑。

## v1.3.0 更新内容

- 新增命名同步配置，可在主界面中创建、立即切换、保存、重命名和删除多套 VM/项目配置。
- 新建配置弹窗提供明确的“创建配置”和“取消”操作，并支持复制当前配置或创建空白配置。
- 配置文件改为原子保存，保留 `config.json.bak`；主配置损坏时会保留损坏副本并尽量自动恢复。
- 配置下拉栏支持窗口失焦、最小化和托盘隐藏时自动关闭，最多显示 8 条记录，更多记录可滚动查看。
- 修复高 DPI 下拉栏宽度、高度、文字裁切、边框侵占及圆角锯齿问题，同时保留灰色悬停反馈。
- 统一 `vmrun` 输出解码，提升虚拟机中文路径和 PowerShell 错误信息的可读性。

## 功能特性

- 自动探测并保存 `vmrun.exe` 路径。
- 校验配置的 `.vmx` 是否为 `vmrun list` 当前正在运行的虚拟机。
- 支持在主界面内创建、命名、保存、加载、重命名和删除多套同步配置；每套配置包含共享虚拟机信息和两个项目槽位，退出后仍保存在 `config.json`。
- 支持同一个虚拟机、同一个虚拟机账号下同时监听两个独立 Keil 工程；项目 1 和项目 2 各自保存本机工程路径、虚拟机工程路径、`.bin` 相对路径和固件回传目录。
- 旧版单项目 `config.json` 会自动迁移到项目 1，新版配置使用 `projects` 列表，后续扩展更多项目时更容易维护。
- 项目 1 和项目 2 可分别启动、暂停、保存检测、全量同步、取消全量同步和查看日志；顶部按钮仍可启动/暂停全部。
- 通过 zip 上传和虚拟机内解压执行全量工程同步；同步时跳过 `Output` 目录并保留空目录。
- 监听本机工程文件变化，并将匹配扩展名的文件增量同步到虚拟机。
- 增量同步会先写入虚拟机目标目录下的临时文件，再移动覆盖最终文件，降低中断时半写目标文件的风险。
- 启动建立监听时会补传启动窗口期内识别到的已保存文件变更，降低刚点击启动就修改文件时的漏传风险。
- 监听配置的虚拟机 `.bin` 输出文件，仅在内容变化时回传到本机电脑。
- 启动同步时记录虚拟机内已有 `.bin` 作为基线，避免旧固件立即覆盖本机文件。
- 两个项目的 watcher、上传队列、hash 基线、`.bin` 基线、回传目录和日志栏互相独立；文件复制、创建、删除和覆盖类 `vmrun` 操作串行执行以降低 VMware VIX 不稳定风险，只读的 `.bin` 目标检查和状态读取可并行。
- 点击“启动”时会先保存配置并执行与“保存并检测”相同的检查，检查失败不会启动同步。
- 点击顶部“启动全部”时采用原子启动：任一启用项目预检失败，两个项目都不会启动，已通过预检的一侧会提示用户先修正失败项目。
- 保存配置会在日志中提示路径已保存至 `config.json` 文件。
- `.bin` 时间戳变化但内容未变化时会跳过覆盖，并通过托盘通知提示。
- 全量同步期间配置栏和启动按钮会置灰，全量同步按钮会切换为“取消全量同步”，取消会等待当前虚拟机操作安全收尾并清理临时文件。
- 支持中英文界面切换，首次启动优先读取 Windows 显示/UI 语言，手动切换后会记住选择。
- 支持系统托盘运行，窗口隐藏后同步服务可继续工作；单击或双击托盘图标只会显示窗口，右键菜单可启动/暂停同步、显示窗口或退出，并随中英文切换显示运行、部分运行或部分异常状态。
- `vmrun` 子进程后台执行，并对 VMware 输出中的异常编码做容错解码，避免弹出命令行窗口或因解码错误中断程序。
- 退出程序时停止同步线程并清理临时虚拟机状态文件。

## 运行要求

- Windows。
- VMware Workstation。
- 目标虚拟机已安装 VMware Tools。
- 目标 Windows 虚拟机可正常启动并进入桌面。
- 虚拟机内已安装并可使用 Keil MDK。
- 虚拟机 Windows 账户设置了密码，并可通过 `vmrun -gu/-gp` 登录。

本工具不会安装 VMware Workstation、VMware Tools、Keil，也不会创建虚拟机。

## 使用入口

普通使用者请下载发行包：[VM-Sync-v1.3.0.zip](https://github.com/Expelliarmus-Lai/vm-sync-tool/releases/download/v1.3.0/VM-Sync-v1.3.0.zip)。

也可以打开 [GitHub Releases](https://github.com/Expelliarmus-Lai/vm-sync-tool/releases/latest) 查看最新版本。发行包结构如下：

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

直接运行 `VM Sync.exe` 即可。发行包内的 `README.md` 由 [docs/USER_GUIDE.md](docs/USER_GUIDE.md) 生成，`README.en.md` 由 [docs/USER_GUIDE.en.md](docs/USER_GUIDE.en.md) 生成，包含配置项说明、首次使用流程、同步覆盖规则和常见问题。

开发者请使用源码仓库，并参考下方的 [开发](#开发)、[诊断](#诊断)、[测试](#测试) 和 [打包](#打包) 章节。

## 同步行为

- **全量同步**：上传本机工程根目录下除 `Output` 目录外的工程文件，空目录也会保留；先解压到虚拟机临时目录，再覆盖到虚拟机工程路径。虚拟机中相同相对路径的文件会被覆盖；虚拟机中额外存在的文件不会被删除。全量同步可取消，取消会在当前虚拟机操作完成后清理临时 zip 和临时解压目录。
- **增量同步**：点击“启动”会先保存配置并执行与“保存并检测”相同的预检；通过后才启动同步服务。同步服务启动后，监听本机新增或修改的文件，仅处理 `watch_extensions` 中配置的扩展名。启动建立基线期间识别到的已保存变更会在监听就绪后补传。只有磁盘文件内容 hash 变化时才会上传；编辑器探测、时间戳变化或未保存的 VS Code 修改不会触发上传。文件会先复制到虚拟机目标目录的临时文件，再移动覆盖最终路径；删除、重命名和不在扩展名列表内的文件不会自动同步。
- **`.bin` 回传**：只拉取配置的虚拟机 `.bin` 目标。`.bin` 路径最终按相对于虚拟机工程路径的相对路径保存；如果粘贴的是虚拟机工程路径下面的绝对路径，界面会自动转换成相对路径并统一显示 Windows 反斜杠。同步服务启动时会先记录虚拟机当前 `.bin` 作为基线，不会立即回传；后续内容变化才会覆盖本机固件回传目录中的同名文件。仅时间戳变化且内容相同的文件会被跳过并显示托盘通知。停止同步后，迟到的 `.bin` 轮询结果不会再触发日志、通知或覆盖。
- **双项目监听**：项目 2 通过“添加同步项目”启用。两个项目共用 VMX、虚拟机用户名和虚拟机密码，但项目路径、全量同步、增量上传、`.bin` 回传、暂停/取消和日志互相独立。若两个启用项目的本机路径或虚拟机路径互相包含，预检会阻止启动，避免传输混淆。
- **启动时机**：建议先把工程同步到虚拟机，再点击“启动”，然后去 Keil 编译。启动前已经存在的 `.bin` 会作为基线；首次基线后的第一次时间更新即使内容相同也会回传一次。

更详细的用户操作说明见 [docs/USER_GUIDE.md](docs/USER_GUIDE.md)。

## 源码目录

```text
vm-sync-tool/
  README.md                       项目说明和开发指南
  README.en.md                    英文项目说明和开发指南
  AGENTS.md                       维护约定和编码注意事项
  docs/USER_GUIDE.md              使用者说明，构建时复制到发行包
  docs/USER_GUIDE.en.md           英文使用者说明，构建时复制到发行包
  main.py                         程序入口和单实例处理
  ui.py                           CustomTkinter 界面、日志、状态栏、托盘
  syncer.py                       同步引擎、vmrun 调用、全量同步、.bin 回传
  config_manager.py               配置读写和路径规范化
  preflight.py                    路径、虚拟机、Keil 工程和 .bin 预检
  vmrun_resolver.py               vmrun 探测和运行中虚拟机解析
  tools/vmrun_probe.py            vmrun 连接诊断脚本
  tests/                          单元测试和回归测试
  packaging_hooks/                PyInstaller hook 调整
  requirements.txt                运行依赖
  requirements-dev.txt            开发和打包依赖
  config.example.json             安全的配置模板
  dev_start.cmd                   源码模式开发启动脚本
  build_release.ps1               文件夹版 exe 构建脚本
  VM Sync.spec                    PyInstaller 构建配置
```

## 开发

安装运行依赖：

```powershell
python -m pip install -r requirements.txt
```

从源码启动：

```powershell
python main.py
```

Windows 本地开发时也可以双击 `dev_start.cmd`。该脚本会从源码启动程序，并在启动失败时保留控制台错误信息。

源码模式的运行配置保存在仓库工作目录的 `config.json`。发行包模式的运行配置保存在 `VM Sync.exe` 同目录下。命名同步配置使用稳定 ID 保存在 `profiles` 列表中，`active_profile_id` 指向当前配置；旧版单项目和双项目配置会自动迁移为默认配置。顶层 VM 和 `projects` 字段继续镜像当前配置，以保持兼容性。

保存配置时会使用原子替换，并把上一份有效内容保留为 `config.json.bak`。如果 `config.json` 损坏，软件会先将其保留为 `config.json.corrupt`，再尽量从备份恢复；保存失败时会在配置工具栏显示错误提示。这三个文件都可能明文包含虚拟机密码，请勿分享或提交到 Git。

## 诊断

完成一次软件配置后，可使用诊断脚本检查 `vmrun`、虚拟机凭据和文件往返能力：

```powershell
python tools\vmrun_probe.py
```

诊断日志输出到 `vmrun_probe_result.txt`，该文件不会进入版本控制。

## 测试

运行回归测试：

```powershell
python -m unittest discover -v
```

编译检查主要模块和高风险测试：

```powershell
python -m py_compile main.py config_manager.py i18n.py syncer.py ui.py preflight.py vmrun_resolver.py vmrun_output.py tools/vmrun_probe.py tests/test_config_manager.py tests/test_i18n.py tests/test_main_single_instance.py tests/test_preflight.py tests/test_syncer.py tests/test_ui_bin_hint.py tests/test_ui_full_sync.py tests/test_ui_log.py tests/test_ui_start_async.py tests/test_ui_status_async.py tests/test_ui_tray.py tests/test_ui_multi_project.py tests/test_ui_profiles.py tests/test_vmrun_resolver.py tests/test_vmrun_output.py
```

## 打包

安装打包依赖：

```powershell
python -m pip install -r requirements-dev.txt
```

构建文件夹版 Windows exe：

```powershell
powershell -ExecutionPolicy Bypass -File .\build_release.ps1
```

构建产物生成在：

```text
dist\VM Sync\
dist\VM-Sync-v1.3.0.zip
```

发布时应分发 `VM-Sync-v1.3.0.zip`，或分发整个 `VM Sync` 文件夹；不能只分发单独的 `VM Sync.exe`，因为 exe 依赖旁边的 `_internal` 目录。

## 仓库维护

本地运行配置和构建产物已通过 `.gitignore` 排除，包括 `config.json`、`dist/`、`build/`、`__pycache__/` 和 `vmrun_probe_result.txt`。`config.example.json` 是保留在仓库中的安全配置模板。

## 许可

本项目使用 [MIT License](LICENSE)。
