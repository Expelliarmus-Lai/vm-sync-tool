# VM Sync Tool

VM Sync Tool 是一个 Windows 桌面工具，用于在宿主机和 VMware Workstation 虚拟机之间同步 Keil 固件工程。它通过 VMware 的 `vmrun.exe` 和 VMware Tools 操作虚拟机文件，不依赖网络共享或虚拟机网卡。

典型工作流：

1. 在宿主机编辑 Keil 工程源码。
2. 将工程同步到虚拟机。
3. 在虚拟机里用 Keil 编译。
4. 将生成的 `.bin` 固件回传到宿主机。

## 给谁看

这个根目录 `README.md` 是给 GitHub 访客和后续维护开发者看的。它说明项目是什么、源码结构是什么、如何从源码运行和打包。

普通使用者拿到文件夹版发布包后，应阅读发布包里的 `README.md`。发布包 README 由 [docs/USER_GUIDE.md](docs/USER_GUIDE.md) 生成，内容更偏向“如何配置和使用软件”。

## 发布包和源码仓库的区别

| 内容 | 用途 | 是否适合上传 GitHub 源码仓库 |
|---|---|---|
| 源码仓库根目录 | 开发、维护、开源、重新打包 | 是 |
| `dist\VM Sync` | 发给同事直接双击使用 | 不建议作为源码提交 |
| `config.json` | 本机真实配置，含路径/账号/密码 | 否 |
| `config.example.json` | 可公开的配置格式模板 | 是 |

如果你希望别人能修改这个软件源码，应该上传整个源码仓库，而不是只上传 `dist\VM Sync`。只上传 `dist\VM Sync` 更像发布一个可执行软件，别人通常无法正常修改源码。

如果要公开给外部人员使用或二次开发，建议后续补充 `LICENSE` 文件，明确开源授权方式。

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

运行软件的电脑需要已经准备好：

- Windows。
- VMware Workstation。
- 目标虚拟机已经安装 VMware Tools。
- 虚拟机能正常启动并进入 Windows 桌面。
- 虚拟机里已经安装并可使用 Keil MDK。
- 虚拟机 Windows 账户有密码，并且可被 `vmrun -gu/-gp` 登录。

本工具不会安装 VMware、VMware Tools、Keil，也不会创建虚拟机。

## 源码目录说明

```text
vm-sync-tool/
  README.md                       GitHub 首页和开发维护说明
  docs/USER_GUIDE.md              普通使用者说明，构建时复制到发布包
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

## 从源码运行

第一次拿到源码后，安装运行依赖：

```powershell
python -m pip install -r requirements.txt
```

之后可以直接双击源码根目录下的：

```text
dev_start.cmd
```

也可以手动运行：

```powershell
python main.py
```

源码运行时读取的是源码根目录下的 `config.json`。exe 发布包运行时读取的是 exe 同目录下的 `config.json`。这两个位置不同，方便开发测试和发布包测试互不干扰。

## 运行测试

修改代码后建议运行：

```powershell
python -m unittest discover -v
python -m py_compile main.py config_manager.py syncer.py ui.py preflight.py vmrun_resolver.py test_syncer.py test_ui_full_sync.py test_ui_tray.py test_main_single_instance.py
```

## 打包发布版 exe

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

发布包目录应包含：

```text
VM Sync/
  VM Sync.exe
  _internal/
  README.md
  config.example.json
```

其中 `dist\VM Sync\README.md` 来自 [docs/USER_GUIDE.md](docs/USER_GUIDE.md)，是给普通使用者看的说明。不要只发单独的 `VM Sync.exe`，文件夹版 exe 需要旁边的 `_internal` 目录。

## GitHub 上传建议

建议提交：

- `*.py`
- `test_*.py`
- `README.md`
- `docs/USER_GUIDE.md`
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

这些本机文件已经在 `.gitignore` 中排除。发布给普通使用者时，可以把 `dist\VM Sync` 压缩后作为 GitHub Release 附件上传。
