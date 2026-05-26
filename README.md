# VM Sync Tool

VM Sync Tool 是一个 Windows 桌面工具，用于在宿主机和 VMware 虚拟机之间同步 Keil 固件工程文件。它通过 VMware 的 `vmrun.exe` 和 VMware Tools 操作虚拟机文件，不依赖网络连接，虚拟机网卡可以关闭。

## 适用场景

- 宿主机上编辑固件工程源码。
- 虚拟机里运行 Keil MDK 编译老工程或固定环境工程。
- 编译完成后，把虚拟机里的 `.bin` 固件自动回传到宿主机目录。

## 主要功能

- 自动探测 `vmrun.exe`。
- 检查配置的 VMX 是否为当前正在运行的虚拟机。
- 宿主机工程文件改动后，自动增量同步到虚拟机。
- 支持“全量同步”：把整个工程打包为 zip 上传到虚拟机后解压。
- 自动监听虚拟机里的 `.bin` 输出文件，内容变化后回传到宿主机。
- 启动同步时不会立刻回传虚拟机里已有的旧 `.bin`，只会在启动后检测到新变化时回传。
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

> 注意：本工具不会安装 VMware、VMware Tools、Keil，也不会创建虚拟机。

## 推荐下载方式

如果只是使用软件，请下载发布包里的文件夹版程序：

```text
VM Sync/
  VM Sync.exe
  _internal/
  README.md
  config.example.json
```

双击 `VM Sync.exe` 即可启动，不需要安装 Python，也不需要运行 bat/vbs。

第一次运行时，程序会在 `VM Sync.exe` 同目录生成 `config.json`。这个文件保存你的本机路径、虚拟机路径、VM 用户名和密码。不要把自己的 `config.json` 上传到 GitHub 或发给别人。

## 配置项说明

打开软件后，在配置区域填写以下内容，然后点击“保存并检测”。

| 配置项 | 含义 | 示例 |
|---|---|---|
| VMX 路径 | 虚拟机 `.vmx` 文件路径。必须是当前正在运行的虚拟机。 | `D:\VMs\Win10\Windows 10.vmx` |
| VM 用户名 | 虚拟机 Windows 登录用户名，用于 `vmrun` 操作文件。 | `h` |
| VM 密码 | 虚拟机 Windows 登录密码。建议不要使用空密码。 | `123456` |
| 宿主机工程路径 | 你在宿主机上编辑的工程根目录。 | `C:\Users\Administrator\Desktop\project` |
| VM 工程路径 | 虚拟机里的工程根目录。全量同步会解压到这里，增量同步也会写到这里。 | `C:\Users\h\Desktop\project` |
| `.bin` 相对路径 | 相对于 VM 工程路径的 `.bin` 文件或目录。 | `Output\RL6492\firmware.bin` |
| 固件回传目录 | `.bin` 回传到宿主机的目录。 | `C:\Users\Administrator\Desktop\bin` |

### `.bin` 相对路径怎么填

推荐直接填写具体 `.bin` 文件：

```text
Output\RL6492\firmware.bin
```

也可以先填写 `.bin` 所在目录：

```text
Output\RL6492
```

如果该目录下只有一个 `.bin`，软件会自动识别。如果有多个 `.bin`，软件会报错并提示你选择具体文件名。

## 基本操作流程

1. 启动 VMware Workstation，并打开目标虚拟机桌面。
2. 双击 `VM Sync.exe`。
3. 填写配置项。
4. 点击“保存并检测”。
5. 首次配置工程时，点击“全量同步”，把整个工程复制到虚拟机。
6. 点击“启动”，开始监听宿主机文件变化和虚拟机 `.bin` 输出。
7. 在虚拟机里用 Keil 编译工程。
8. 编译生成的 `.bin` 内容发生变化后，软件会自动回传到“固件回传目录”。

## 全量同步和启动同步的区别

### 全量同步

全量同步会把宿主机工程目录下的所有文件打包上传到虚拟机，并解压覆盖到 VM 工程路径。它适合第一次配置、工程结构变动较大、或者虚拟机里的工程缺文件时使用。

全量同步不会删除虚拟机目录里多出来的文件。

### 启动同步

启动同步后，软件会做两件事：

- 监听宿主机工程文件变化，增量同步到虚拟机。
- 轮询虚拟机 `.bin` 输出文件，检测到内容变化后回传到宿主机。

启动同步时，软件会把虚拟机当前已有的 `.bin` 作为基线，不会立即回传旧文件。

## 常见问题

### 打开后提示找不到 vmrun.exe

请确认已经安装 VMware Workstation。软件会自动探测常见路径和 PATH 中的 `vmrun.exe`。

### 提示配置的 VMX 当前未运行

请先在 VMware Workstation 中启动对应虚拟机，并确认配置的 VMX 路径就是这个正在运行的虚拟机。

### 提示 VM 目录下有多个 `.bin`

把 `.bin` 相对路径从目录改成具体文件名，例如：

```text
Output\RL6492\firmware.bin
```

### 启动后没有立刻回传 `.bin`

这是正常的。软件会忽略启动前虚拟机里已有的旧 `.bin`，只有启动之后 `.bin` 内容发生变化才会回传。

### 关闭窗口后软件还在运行

关闭窗口只会隐藏到系统托盘，同步仍然运行。需要完全退出时，请右键托盘图标，选择“退出”。

## 从源码运行

开发者可以从源码运行：

```powershell
python -m pip install -r requirements.txt
python main.py
```

## 打包 exe

开发者可以使用 PyInstaller 打包文件夹版 exe：

```powershell
python -m pip install -r requirements-dev.txt
powershell -ExecutionPolicy Bypass -File .\build_release.ps1
```

构建完成后，输出目录为：

```text
dist\VM Sync\
```

把整个 `dist\VM Sync` 文件夹发给同事即可。不要只发单独的 `VM Sync.exe`，文件夹版 exe 需要旁边的 `_internal` 目录。

## 后续还能修改吗

可以。exe 是源码的构建产物，不是唯一源文件。后续修改源码后，重新运行打包命令即可生成新的 exe。

## GitHub 注意事项

可以提交到 GitHub 的内容：

- 源码 `.py`
- 测试 `test_*.py`
- `README.md`
- `requirements.txt`
- `requirements-dev.txt`
- `config.example.json`
- `VM Sync.spec`
- `build_release.ps1`

不要提交：

- `config.json`
- `dist/`
- `build/`
- `__pycache__/`
- 本机 VM 探测日志或包含路径/账号的调试文件

这些内容已经在 `.gitignore` 中排除。
