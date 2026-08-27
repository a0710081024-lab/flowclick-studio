# FlowClick Studio

一个面向 Windows 的可视化本地自动化工具。你可以把点击、等待、按键、文字输入、OCR 识别、图片识别和循环组合成一连串清晰的步骤，不需要修改 Python 代码。

## 已实现功能

- 可视化步骤列表：添加、编辑、复制、删除、启用/禁用、上移、下移
- 鼠标操作：指定坐标点击、左右键、多次点击、滚轮
- 键盘操作：单键、组合键、自动输入或剪贴板粘贴
- 文字识别：等待指定中英文出现，或识别后点击文字中心
- 图片识别：等待小图片出现，或识别后点击图片中心
- 流程控制：成对循环、超时停止或跳过
- 坐标录制：编辑点击步骤时，3 秒后读取鼠标位置
- 配置管理：每套流程保存为独立 JSON 文件
- 全局快捷键：F8 开始、F9 暂停/继续、F10 停止
- 安全保护：把鼠标快速移到屏幕左上角可触发 PyAutoGUI FailSafe

## 最简单的使用方式

### 使用打包好的 EXE

1. 下载 `FlowClickStudio-windows-x64.zip`。
2. 右键选择“全部解压缩”。
3. 保留整个 `FlowClickStudio` 文件夹，不要只移动其中的 EXE。
4. 双击 `FlowClickStudio.exe`。
5. 如果目标软件以管理员身份运行，FlowClick Studio 也需要右键“以管理员身份运行”。

### 从源码运行

1. 安装 **Python 3.11 64 位**，安装时勾选 `Add Python to PATH`。
2. 双击 `install.bat`，等待依赖安装完成。
3. 双击 `start.bat`。

## 编辑一套操作流程

1. 在“新增操作”中选择类型，点击“添加步骤”。
2. 对坐标点击，可按“3 秒后读取鼠标位置”，然后把鼠标移到目标点。
3. 对 OCR/图片识别，可把识别区域留空以扫描全屏；为了更快更准，建议填写 `x,y,宽,高`。
4. 双击列表中的步骤可重新编辑，使用“上移/下移”调整顺序。
5. 循环必须由“循环开始”和“循环结束”包住需要重复的步骤。
6. 点击“检查流程”，通过后保存并运行。

一个流程文件大致如下：

```json
{
  "format": "flowclick-workflow",
  "version": 1,
  "name": "示例",
  "steps": [
    {"action": "wait", "enabled": true, "params": {"seconds": 2}},
    {"action": "click", "enabled": true, "params": {"x": 820, "y": 460, "clicks": 1, "interval": 0.1, "button": "left"}}
  ]
}
```

平时不需要手写 JSON，程序界面会自动生成。

## OCR 与图片识别

- OCR 使用 RapidOCR + ONNX Runtime，在本地识别中英文，不把截图上传到网络。
- OCR 第一次运行时初始化会比普通点击慢。
- 图片识别使用 OpenCV。建议截取按钮中稳定、有辨识度的小区域，不要截整张屏幕。
- 如果文字或图片始终找不到，可降低最低置信度/相似度，或缩小识别区域。

RapidOCR 官方当前推荐使用 `pip install rapidocr onnxruntime`，默认模型支持中英文识别。

## 生成 Windows EXE

### 在自己的电脑构建

双击 `build.bat`。它会：

1. 安装构建依赖；
2. 运行自动测试；
3. 使用 PyInstaller 生成文件夹版 EXE；
4. 输出 `output\FlowClickStudio-windows-x64.zip`。

### 使用 GitHub Actions

将代码推送到 GitHub 的 `main` 分支后，打开仓库的 **Actions → Build Windows EXE → Run workflow**。完成后从页面底部的 **Artifacts** 下载 `FlowClickStudio-windows-x64`。

文件夹版比强行压成单文件更适合包含 OCR 模型的程序：启动更快，也更容易排查被安全软件误拦截的文件。

## 注意事项

- 自动化操作可能违反部分游戏或软件的使用规则；运行前请确认目标软件允许。
- 开始前先用低次数、长间隔测试坐标。
- F10 是紧急停止键；同时保留鼠标左上角 FailSafe。
- 屏幕缩放、分辨率、窗口位置变化后，应重新录制坐标。
- 目标程序若以管理员身份运行，本程序通常也需要相同权限才能向其发送输入。

## 依赖与依据

- RapidOCR：<https://github.com/RapidAI/RapidOCR>
- PyInstaller：<https://pyinstaller.org/>
