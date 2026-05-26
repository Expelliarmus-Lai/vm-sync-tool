# VM Sync Tool

VM Sync Tool 是一个 Windows 桌面工具，用于在宿主机和 VMware Workstation 虚拟机之间同步 Keil 固件工程。它通过 VMware 的 `vmrun.exe` 和 VMware Tools 操作虚拟机文件，不依赖网络共享或虚拟机网卡。

典型工作流是：在宿主机编辑源码，把工程同步到虚拟机，在虚拟机里用 Keil 编译，然后把生成的 `.bin` 固件回传到宿主机。

## 这个仓库里有什么

这个项目同时面向两类人：

- **普通使用者**：只需要拿到文件夹版发布包，双击 `VM Sync.exe` 使用。
- **维护开发者**：需要拿到完整源码仓库，修改 Python 代码、运行测试、重新打包 exe。

重要区别：

- `dist\VM Sync` 是构建出来的发布包，适合发给同事直接使用。
- 源码仓库才适合上传 GitHub、继续维护和二次开发。
- 只把 `dist\VM Sync` 文件夹上传到 GitHub，别人只能拿到 exe 和运行依赖，不能正常修改源码；这更像“发布软件”，不算真正意义上的源码开源。

如果希望别人能修改软件，请上传源码仓库里的 `.py`、测试、README、构建脚本等文件，并排除 `config.json`、`dist/`、`build/` 等本机产物。若要公开开源给外部人员使用，建议后续补一个 `LICENSE` 文件明确授权方式。

## 主要功能

- 自动探测并保存 `vmrun.exe` 路径。
- 检查配置的 VMX 是否为当前正在运行的虚拟机。
- 宿主机工程文件改动后，自动增量同步到虚拟机。
- 支持“全量同步”：把整个宿主机工程打包为 zip，上传到虚拟机后解压覆盖。
- 自动监听虚拟机里的 `.bin` 输出文件，内容变化后回传到宿主机。
- 启动同步时不会立即回传虚拟机里已有的旧 `.bin`，只会在启动后检测到新变化时回传。
- `.bin` 内容没有变化时不会覆盖宿主机输出文件。
- 支持系统托盘，关闭窗口后可继续后台运行。
- 退出程序时会停止同步线程并清理临时状态文件。

## 使用前提

使用者电脑需要已经准备好以下环境：

- Windows。
- VMware Workstation。
- 目标虚拟机已经安装 VMware Tools。
- 虚拟机能正常启动并进入 Windows 桌面。
- 虚拟机里已经安装并可使用 Keil MDK。
- 虚拟机 Windows 账户有密码，并且可被 `vmrun -gu/-gp` 登录。

本工具不会安装 VMware、VMware Tools、Keil，也不会创建虚拟机。

## 普通使用者：如何运行发布包

发布包目录应该长这样：

```text
VM Sync/
  VM Sync.exe
  _internal/
  README.md
  config.example.json
```

双击 `VM Sync.exe` 即可启动。使用发布包不需要安装 Python，也不需要运行 bat/cmd/vbs。

第一次运行时，程序会在 `VM Sync.exe` 同目录生成 `config.json`。这个文件保存本机路径、虚拟机路径、VM 用户名和密码，不要上传到 GitHub，也不要发给别人。

`config.example.json` 是公开模板，用来展示配置文件格式；程序运行真正使用的是 `config.json`。

## 配置项说明

打开软件后，在配置区域填写以下内容，然后点击“保存并检测”。

| 配置项 | 含义 | 示例 |
|---|---|---|
| VMX 路径 | 虚拟机 `.vmx` 文件路径。必须是当前正在运行的虚拟机。 | `D:\VMs\Win10\Windows 10.vmx` |
| VM 用户名 | 虚拟机 Windows 登录用户名，用于 `vmrun` 操作文件。 | `h` |
| VM 密码 | 虚拟机 Windows 登录密码。建议不要使用空密码。 | `123456` |
| 宿主机工程路径 | 你在宿主机上编辑的 Keil 工程根目录。 | `C:\Users\Administrator\Desktop\project` |
| VM 工程路径 | 虚拟机里的工程根目录。全量同步会解压到这里，增量同步也会写到这里。 | `C:\Users\h\Desktop\project` |
| `.bin` 相对路径 | 相对于 VM 工程路径的 `.bin` 文件或目录。 | `Output\RL6492\firmware.bin` |
| 固件回传目录 | `.bin` 回传到宿主机的目录。 | `C:\Users\Administrator\Desktop\bin` |

### `.bin` 相对路径怎么填

推荐填写具体 `.bin` 文件：

```text
Output\RL6492\firmware.bin
```

也可以先填写 `.bin` 所在目录：

```text
Output\RL6492
```

如果该目录下只有一个 `.bin`，软件会自动识别。如果有多个 `.bin`，软件会报错并提示你选择具体文件名。

注意：不要填写 VM 里的绝对路径。这里填写的是相对于“VM 工程路径”的相对路径。

## 基本操作流程

1. 启动 VMware Workstation，并打开目标虚拟机桌面。
2. 双击 `VM Sync.exe`。
3. 填写配置项。
4. 点击“保存并检测”。
5. 首次配置工程时，点击“全量同步”，把整个工程复制到虚拟机。
6. 点击“启动”，开始监听宿主机文件变化和虚拟机 `.bin` 输出。
7. 在虚拟机里用 Keil 编译工程。
8. `.bin` 内容发生变化后，软件会自动回传到“固件回传目录”。

## 全量同步和启动同步的区别

### 全量同步

全量同步会把宿主机工程目录下的所有文件打包上传到虚拟机，并解压覆盖到 VM 工程路径。它适合第一次配置、工程结构变动较大、或者虚拟机里的工程缺文件时使用。

全量同步会覆盖虚拟机目录中同名文件，但不会删除虚拟机目录里多出来的文件。

### 启动同步

启动同步后，软件会做两件事：

- 监听宿主机工程文件变化，增量同步到虚拟机。
- 轮询虚拟机 `.bin` 输出文件，检测到内容变化后回传到宿主机。

启动同步时，软件会把虚拟机当前已有的 `.bin` 作为基线，不会立即回传旧文件。

## 常见问题

### 打开后提示找不到 vmrun.exe

请确认已经安装 VMware Workstation。软件会自动探测常见安装路径和 PATH 中的 `vmrun.exe`。

### 提示配置的 VMX 当前未运行

请先在 VMware Workstation 中启动对应虚拟机，并确认配置的 VMX 路径就是这个正在运行的虚拟机。

### 提示 VM 目录下有多个 `.bin`

把 `.bin` 相对路径从目录改成具体文件名，例如：

```text
Output\RL6492\firmware.bin
```

### 启动后没有立刻回传 `.bin`

这是正常行为。软件会忽略启动前虚拟机里已有的旧 `.bin`，只有启动之后 `.bin` 内容发生变化才会回传。

### 关闭窗口后软件还在运行

关闭窗口只会隐藏到系统托盘，同步仍然运行。需要完全退出时，请右键托盘图标，选择“退出”。

## 源码目录说明

源码仓库大致结构如下：

```text
vm-sync-tool/
  main.py                         程序入口，单实例检查，配置加载
  ui.py                           CustomTkinter 界面、日志、托盘
  syncer.py                       同步核心、vmrun 调用、全量同步、.bin 回传
  config_manager.py               config.json 读写和路径规范化
  preflight.py                    保存/启动/同步前的路径和 VM 预检
  vmrun_resolver.py               vmrun.exe 自动探测和运行中 VM 列表解析
  vmrun_probe.py                  手动诊断 vmrun 连接问题的辅助脚本
  test_*.py                       单元和回归测试
  requirements.txt                源码运行依赖
  requirements-dev.txt            打包开发依赖
  dev_start.cmd                   源码开发一键启动脚本
  build_release.ps1               构建文件夹版 exe 的脚本
  VM Sync.spec                    PyInstaller 打包配置
  config.example.json             可公开提交的配置模板
  config.json                     本机真实配置，已被 .gitignore 排除
  dist/                           构建产物，已被 .gitignore 排除
  build/                          构建缓存，已被 .gitignore 排除
```

## 维护开发者：从源码运行

第一次拿到源码后，先安装依赖：

```powershell
python -m pip install -r requirements.txt
```

之后可以直接双击源码根目录下的：

```text
dev_start.cmd
```

这个脚本只存在于源码仓库中，用于开发者本地调试；它不会被复制进 `dist\VM Sync` 发布包。发布包使用者不需要它。

也可以手动运行：

```powershell
python main.py
```

源码运行时读取的是源码根目录下的：

```text
config.json
```

exe 发布包运行时读取的是 exe 同目录下的：

```text
dist\VM Sync\config.json
```

两边配置文件位置不同，这是为了让开发测试和发布包测试互不干扰。

## 维护开发者：运行测试

修改代码后建议运行：

```powershell
python -m unittest discover -v
python -m py_compile main.py config_manager.py syncer.py ui.py preflight.py vmrun_resolver.py test_syncer.py test_ui_full_sync.py test_ui_tray.py test_main_single_instance.py
```

## 维护开发者：打包 exe

第一次打包前安装开发依赖：

```powershell
python -m pip install -r requirements-dev.txt
```

构建文件夹版 exe：

```powershell
powershell -ExecutionPolicy Bypass -File .\build_release.ps1
```

构建完成后，发布包目录为：

```text
dist\VM Sync\
```

把整个 `dist\VM Sync` 文件夹发给同事即可。不要只发单独的 `VM Sync.exe`，文件夹版 exe 需要旁边的 `_internal` 目录。

## GitHub 上传建议

如果要让别人能继续修改源码，应上传源码仓库，而不是只上传 `dist\VM Sync`。

建议提交到 GitHub：

- `*.py`
- `test_*.py`
- `README.md`
- `requirements.txt`
- `requirements-dev.txt`
- `config.example.json`
- `dev_start.cmd`
- `build_release.ps1`
- `VM Sync.spec`
- `packaging_hooks/`

不要提交：

- `config.json`
- `dist/`
- `build/`
- `__pycache__/`
- `vmrun_probe_result.txt`
- 任何包含本机路径、VM 账号或密码的调试文件

这些本机文件已经在 `.gitignore` 中排除。发布给普通使用者时，可以把 `dist\VM Sync` 作为 GitHub Release 附件上传。
