# VM Sync Tool

语言：[中文](README.md) | [English](README.en.md)

VM Sync Tool 是一个 Windows 桌面工具，用于在宿主机和 VMware Workstation 虚拟机之间同步 Keil 固件工程。工具通过 VMware `vmrun.exe` 和 VMware Tools 操作虚拟机文件，不依赖共享文件夹、网络盘或虚拟机网卡。

典型流程：

1. 在宿主机编辑 Keil 工程源码。
2. 将工程同步到虚拟机。
3. 在虚拟机里用 Keil 手动编译。
4. 将生成的 `.bin` 固件回传到宿主机。

## 功能特性

- 自动探测并保存 `vmrun.exe` 路径。
- 校验配置的 `.vmx` 是否为 `vmrun list` 当前正在运行的虚拟机。
- 通过 zip 上传和 VM 内解压执行全量工程同步。
- 监听宿主机工程文件变化，并将匹配扩展名的文件增量同步到 VM。
- 监听配置的 VM `.bin` 输出文件，仅在内容变化时回传到宿主机。
- 启动同步时记录 VM 内已有 `.bin` 作为基线，避免旧固件立即覆盖宿主机文件。
- 点击“启动”时会先保存配置并执行与“保存并检测”相同的检查，检查失败不会启动同步。
- 保存配置会在日志中提示路径已保存至 `config.json` 文件。
- `.bin` 时间戳变化但内容未变化时会跳过覆盖，并通过托盘通知提示。
- 支持系统托盘运行，窗口隐藏后同步服务可继续工作。
- 退出程序时停止同步线程并清理临时 VM 状态文件。

## 运行要求

- Windows。
- VMware Workstation。
- 目标虚拟机已安装 VMware Tools。
- 目标 Windows 虚拟机可正常启动并进入桌面。
- 虚拟机内已安装并可使用 Keil MDK。
- 虚拟机 Windows 账户设置了密码，并可通过 `vmrun -gu/-gp` 登录。

本工具不会安装 VMware Workstation、VMware Tools、Keil，也不会创建虚拟机。

## 使用入口

普通使用者应下载项目发布页中的文件夹版发行包。发行包结构如下：

```text
VM Sync/
  VM Sync.exe
  _internal/
  README.md
  config.example.json
```

直接运行 `VM Sync.exe` 即可。发行包内的 `README.md` 由 [docs/USER_GUIDE.md](docs/USER_GUIDE.md) 生成，`README.en.md` 由 [docs/USER_GUIDE.en.md](docs/USER_GUIDE.en.md) 生成，包含配置项说明、首次使用流程、同步覆盖规则和常见问题。

开发者请使用源码仓库，并参考下方的 [开发](#开发)、[诊断](#诊断)、[测试](#测试) 和 [打包](#打包) 章节。

## 同步行为

- **全量同步**：上传宿主机工程根目录下的全部文件，并解压到 VM 工程路径。VM 中相同相对路径的文件会被覆盖；VM 中额外存在的文件不会被删除。
- **增量同步**：点击“启动”会先保存配置并执行与“保存并检测”相同的预检；通过后才启动同步服务。同步服务启动后，监听宿主机新增或修改的文件，仅处理 `watch_extensions` 中配置的扩展名。VM 中相同相对路径的文件会被覆盖；删除、重命名和不在扩展名列表内的文件不会自动同步。
- **`.bin` 回传**：只拉取配置的 VM `.bin` 目标。同步服务启动时会先记录 VM 当前 `.bin` 作为基线，不会立即回传；后续内容变化才会覆盖宿主机固件回传目录中的同名文件。仅时间戳变化且内容相同的文件会被跳过并显示托盘通知。停止同步后，迟到的 `.bin` 轮询结果不会再触发日志、通知或覆盖。

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
  preflight.py                    路径、VM、Keil 工程和 .bin 预检
  vmrun_resolver.py               vmrun 探测和运行中 VM 解析
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

源码模式的运行配置保存在仓库工作目录的 `config.json`。发行包模式的运行配置保存在 `VM Sync.exe` 同目录下。

## 诊断

完成一次软件配置后，可使用诊断脚本检查 `vmrun`、VM 凭据和文件往返能力：

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
python -m py_compile main.py config_manager.py syncer.py ui.py preflight.py vmrun_resolver.py tools/vmrun_probe.py tests/test_syncer.py tests/test_ui_full_sync.py tests/test_ui_tray.py tests/test_main_single_instance.py
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
```

发布时应分发整个 `VM Sync` 文件夹，不能只分发单独的 `VM Sync.exe`，因为 exe 依赖旁边的 `_internal` 目录。

## 仓库维护

本地运行配置和构建产物已通过 `.gitignore` 排除，包括 `config.json`、`dist/`、`build/`、`__pycache__/` 和 `vmrun_probe_result.txt`。`config.example.json` 是保留在仓库中的安全配置模板。
