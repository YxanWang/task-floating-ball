# 任务悬浮球

一个轻量的 Windows 桌面悬浮清单。流动的水球始终置顶，显示当前任务数量；鼠标移上去展开任务，移开后收起，适合随手记录和清理待办。

**[下载 Windows 版](https://github.com/YxanWang/task-floating-ball/releases/latest)**：在最新发布中下载 `task-floating-ball.exe`，放入有写入权限的文件夹，双击即可使用。

## 为什么做这个小工具

现在我经常让 AI 并行处理不同的事情。我需要一个简单、看得见的小队列，提醒自己当前有哪些任务在并行推进，以及还有哪些事需要跟进。

对我来说，许多现有的清单产品功能偏重，而我的需求很小：随手记下一件事，抬眼就能看到手头的任务，完成后把它移除。

于是做了这个小工具，让当前任务和待办安静地待在桌面一角。需要时展开看一眼，忙起来就收成一颗小水滴，尽量少占空间、少打断思路。希望它足够简洁，让我把注意力留给正在做的事。

## 使用方式

- 拖动小球调整位置。
- 拖近屏幕外沿并松手，会收成贴边小水滴；悬停展开，移开后收回。把水滴拖离边缘，或右键选择“取消贴边”，可恢复普通小球。
- 悬停小球展开清单，点击小球固定或取消固定清单。
- 在底部输入内容，按 Enter 添加任务。
- 双击任务文字编辑，按 Enter 或移开焦点保存，按 Esc 取消编辑。
- 悬停任务行后点击 `×` 删除；把文字清空并保存也会删除。
- 右键小球可固定显示、调整外观或退出程序。

## 水球外观

右键小球打开外观设置，点击深海、月白、琥珀按钮切换主题，将直径调整为 40–80 像素，设置 30%–100% 的透明度，并开关代表任务的环绕光点。数值越低，界面越透明；100% 保留原本的材质效果。透明度同时作用于小球、贴边水滴和任务清单，设置窗口自身保持清晰可见。设置窗口可拖动顶部移动，点击右上角关闭或“完成”收起。默认使用 40 像素、100% 透明度设置的琥珀主题并显示光点；光点随任务增删同步变化，外观设置会保存供下次启动使用。

主题会同时应用到球体、任务清单、右键菜单和外观设置窗口。深海使用蓝绿色，月白使用浅底深色文字，琥珀使用暖棕色；切换后立即生效。

**任务删除后立即永久移除，没有撤销或已完成任务归档。**

程序在同一 Windows 登录会话中只运行一个界面实例，重复启动会唤出已有窗口。命令行操作可以在界面运行时使用，任务变更会自动刷新。

## 从源码运行

面向 Windows 10/11，开发环境使用 Python 3.12。以下命令在项目根目录的 PowerShell 中执行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe task_floating_ball.py
```

如果已经启用了对应的 Python 环境，也可以直接运行：

```powershell
python task_floating_ball.py
```

## 命令行

```powershell
python task_floating_ball.py add "整理本周笔记"
python task_floating_ball.py list
python task_floating_ball.py del 1
```

`del` 使用 `list` 显示的序号，从 1 开始；删除前可以先查看清单。命令行与界面使用同一份本地任务数据。

## 本地数据

- `tasks.json` 保存任务。
- `config.json` 保存小球位置和外观设置。

源码运行时，数据位于项目根目录；打包运行时，数据位于 exe 所在目录。相应文件会在需要保存时生成，因此应把程序放在有写入权限的文件夹中。迁移或备份时，复制这两个文件即可。

真实任务、位置配置、exe 和构建产物已由 `.gitignore` 排除。仓库保留源码、图标、构建脚本和测试。发布可执行文件时，可将打包后的程序作为 GitHub Releases 附件上传。

## 打包

在 Windows 中安装构建依赖，再指定用于构建的 Python：

```powershell
python -m pip install -r requirements-dev.txt
./build.ps1 -Python (Get-Command python).Source
```

也可以明确指定虚拟环境：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
./build.ps1 -Python .\.venv\Scripts\python.exe
```

输出为项目根目录下的 `任务悬浮球.exe`，双击即可启动。

通过 PowerShell 启动界面时，使用默认窗口模式或 `-WindowStyle Normal`。不要使用 `-WindowStyle Hidden`：它可能让设置窗口被 Windows 隐藏，而小球仍然可见。

需要先验收候选版本时，可添加 `-OutputDirectory .build/candidate`，将 exe 输出到独立目录。

## 验证

单元测试使用临时数据目录：

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
python -m unittest discover -s tests -v
```

GitHub Actions 在 Windows、Python 3.12 和 Qt `offscreen` 模式下运行单元测试，并通过 `TASK_FLOATING_BALL_SKIP_NATIVE_TESTS=1` 跳过两项依赖交互桌面的原生菜单测试。本地默认仍运行这两项测试；界面布局和打包依赖需在 Windows 桌面环境中单独验收。

构建完成后，运行实际 exe 验收：

```powershell
python tests/verify_release.py --exe "./任务悬浮球.exe" --out .build/release-check
```

`--out` 必须是尚不存在的目录。验收会使用隔离任务数据，检查启动、任务操作、外观设置、四边贴边与拖离、重复启动、退出和重启，并输出 JSON 报告和截图。修改代码后重新构建，再对新的 exe 验收。

## 代码结构

```text
task_floating_ball.py       # 程序入口
task_ball/
  settings.py              # 应用标识与界面样式
  storage.py               # 数据路径、任务校验和文件读写
  cli.py                   # 命令行操作
  appearance.py            # 外观配置读取、校验和保存
  themes.py                # 清单、菜单和设置窗口的统一主题配色
  docking.py               # 多屏工作区与四边停靠位置计算
  dock_handle.py           # 贴边水滴绘制与鼠标交互
  appearance_dialog.py     # 外观设置对话框
  water_ball.py            # 水球绘制与环绕光点
  widgets.py               # 小球、任务行与面板组件
  window.py                # 主窗口与交互协调
  app.py                   # 应用启动和退出
  single_instance.py       # Windows 单实例控制
  verification.py          # 打包程序内的验收步骤
assets/app_icon.ico        # 程序图标
tests/                     # 自动测试与 exe 验收脚本
build.ps1                  # Windows 构建脚本
```

调整功能时尽量在相应模块中修改，保持入口简短。涉及窗口关闭、单实例或打包方式的变更，需要同时通过单元测试和实际 exe 验收。
