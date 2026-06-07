<p align="center">
  <h1 align="center">🎤 Readom Teleprompter</h1>
  <p align="center">读到哪里，Highlight 到哪里。Windows 桌面语音提词器。</p>
  <p align="center">
    <strong>中文</strong> · <a href="#features">Features</a> · <a href="#quick-start">Quick Start</a> · <a href="#usage">Usage</a>
  </p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.9%2B-blue" alt="Python 3.9+">
  <img src="https://img.shields.io/badge/UI-PySide6-green" alt="PySide6">
  <img src="https://img.shields.io/badge/ASR-faster--whisper-orange" alt="faster-whisper">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License">
</p>

---

## ✨ Features

- **🎙 语音驱动高亮** — 对着麦克风朗读，文字自动高亮跟踪当前位置
- **📄 多格式导入** — 支持 `.txt`、`.docx`（Word）、手动粘贴
- **🔊 双模式识别** — 离线模式（faster-whisper）/ 在线模式（百度语音 API）
- **🎯 读错标红** — 朗读错误或遗漏的文字以红底标记，一目了然
- **📊 音频测试** — 内置麦克风电平表，实时查看信号强度
- **🗣 语音命令** — 说"暂停""继续""后退"，全程无需动手
- **🖥 全屏沉浸** — 护眼浅蓝背景，大号清晰字体，自适应布局
- **⌨ 快捷键** — 空格启停、方向键翻页、F11 全屏
- **📈 进度追踪** — 进度条显示阅读进度
- **🧠 防跳变** — 智能匹配算法，防止高亮位置跳动

## 🚀 Quick Start

### 方式一：从源码运行

```bash
# 1. 克隆仓库
git clone https://github.com/Mrbobby-lin/Readom-Teleprompter.git
cd Readom-Teleprompter

# 2. 安装依赖
pip install -r requirements.txt

# 3. 运行
python main.py
```

首次使用离线模式时，程序会自动下载 faster-whisper tiny 模型（~75MB）。

### 方式二：自行打包

```bash
pip install pyinstaller
python package.py
# 产物在 dist/语音提词器.exe
```

## 🎯 Usage

### 基本流程

```
1. 打开软件 → 2. 导入演讲稿 → 3. 点击「▶ 开始」→ 4. 开始朗读
```

### 快捷键

| 按键 | 功能 |
|------|------|
| `Space` | 开始 / 暂停 |
| `←` `→` | 后退 / 前进一句 |
| `F11` | 切换全屏 |
| `Esc` | 退出全屏 |

### 语音命令

朗读时说出以下词语即可控制：

| 你说 | 效果 |
|------|------|
| "暂停" / "停一下" | 暂停跟踪 |
| "继续" / "开始" | 恢复跟踪 |
| "后退" / "上一句" | 跳到上一句 |
| "前进" / "下一句" | 跳到下一句 |
| "停止" / "结束" | 停止识别 |

### 设置说明

点击顶部「⚙ 设置」进入设置：

- **🎙 麦克风**：选择输入设备，支持自动检测蓝牙/USB/内置麦克风
- **🎯 识别方式**：
  - **离线模式**（faster-whisper）：无需网络，首次自动下载模型（~75MB），CPU 流畅运行
  - **在线模式**（百度语音）：需申请免费 API Key，识别更准
- **📝 字体**：调整字号和行间距

### 音频测试

点击工具栏「🎤 音频测试」打开测试面板：
- 选择麦克风设备
- 实时显示 RMS / 峰值电平
- 快速诊断麦克风是否正常工作

## 🛠 Technical Stack

| 组件 | 技术 |
|------|------|
| UI 框架 | PySide6 (Qt6) |
| 离线语音 | faster-whisper (CTranslate2 + INT8) |
| 在线语音 | 百度语音 API |
| 音频采集 | PyAudio |
| 文档解析 | python-docx |

## ⚙️ Requirements

- Python 3.9+
- Windows 10/11（推荐）
- 麦克风（内置 / USB / 蓝牙均可）

## 🔧 Troubleshooting

**Q: 语音识别不准确？**
A: 建议在安静环境下使用。在线模式（百度语音）比离线模式准确。可尝试调整麦克风位置或使用音频测试功能检查信号强度。

**Q: 读错标红怎么用？**
A: 朗读时，识别结果与原文不匹配的部分会自动以红底白字显示。朗读正确的部分保持蓝底白字。

**Q: 音频测试电平无波动？**
A: 检查系统声音设置中麦克风是否被禁用或静音。尝试切换不同设备。蓝牙麦克风请在设置中手动选择。

**Q: 蓝牙麦克风没声音？**
A: 蓝牙 Hands-Free 协议需要强制 16000Hz 采样率。确保在「设置」中手动选择蓝牙设备。如果仍不行，尝试在 Windows 声音设置中禁用手持电话免提模式。

**Q: 文字匹配老是跳？**
A: 系统有防跳变机制。如果频繁跳动，可放慢语速，或使用手动按钮控制。

## 📄 License

MIT
