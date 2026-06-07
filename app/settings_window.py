"""
设置窗口
麦克风选择、识别方式、字体大小、API Key 等配置
"""

import logging

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QLineEdit, QPushButton, QSlider,
    QRadioButton, QButtonGroup, QGroupBox,
    QFormLayout, QWidget, QTabWidget, QMessageBox,
    QCheckBox, QFrame
)
from PySide6.QtCore import Qt, Signal, QSettings
from PySide6.QtGui import QFont

logger = logging.getLogger(__name__)


class SettingsWindow(QDialog):
    """设置对话框"""

    # 设置已保存信号
    settings_saved = Signal(dict)

    def __init__(self, parent=None, current_settings=None):
        super().__init__(parent)
        self.setWindowTitle("提词器设置")
        self.setObjectName("settingsDialog")
        self.setMinimumSize(520, 480)
        self.setMaximumSize(600, 600)

        self.settings = current_settings or self._load_defaults()
        self.mic_devices = []

        self._setup_ui()
        self._load_settings()

    def _setup_ui(self):
        """构建界面"""
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 20, 24, 20)

        # 标题区域
        header = QFrame()
        header.setStyleSheet("""
            QFrame {
                background-color: #e3f2fd;
                border-radius: 8px;
                padding: 12px;
            }
        """)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 8, 16, 8)
        title = QLabel("⚙ 设置")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #0d47a1;")
        header_layout.addWidget(title)
        subtitle = QLabel("配置麦克风、语音识别和显示选项")
        subtitle.setStyleSheet("font-size: 13px; color: #1976d2;")
        header_layout.addWidget(subtitle)
        header_layout.addStretch()
        layout.addWidget(header)

        # 使用 Tab 控件分组
        tabs = QTabWidget()
        tabs.setTabPosition(QTabWidget.TabPosition.North)
        tabs.setDocumentMode(True)

        # ===== 标签页1: 语音 =====
        speech_tab = QWidget()
        speech_layout = QVBoxLayout(speech_tab)
        speech_layout.setSpacing(16)

        # 麦克风选择
        mic_group = QGroupBox("🎙 麦克风")
        mic_layout = QFormLayout(mic_group)

        self.mic_combo = QComboBox()
        self.mic_combo.setMinimumWidth(300)
        self.refresh_mic_btn = QPushButton("刷新")
        self.refresh_mic_btn.setObjectName("toolBtn")
        self.refresh_mic_btn.setFixedWidth(60)
        self.refresh_mic_btn.clicked.connect(self._refresh_mic_list)

        mic_select_layout = QHBoxLayout()
        mic_select_layout.addWidget(self.mic_combo, 1)
        mic_select_layout.addWidget(self.refresh_mic_btn)

        mic_layout.addRow("输入设备:", mic_select_layout)
        speech_layout.addWidget(mic_group)

        # 识别方式
        recog_group = QGroupBox("🎯 语音识别方式")
        recog_layout = QVBoxLayout(recog_group)
        recog_layout.setSpacing(8)

        self.recog_group = QButtonGroup(self)

        self.radio_offline = QRadioButton("离线模式（faster-whisper）- 无需网络")
        self.radio_online = QRadioButton("在线模式（百度语音）- 需网络和 API Key")
        self.radio_offline.setChecked(True)

        self.recog_group.addButton(self.radio_offline, 0)
        self.recog_group.addButton(self.radio_online, 1)

        recog_layout.addWidget(self.radio_offline)
        recog_layout.addWidget(self.radio_online)

        # 百度 API Key 输入
        api_group = QWidget()
        api_layout = QFormLayout(api_group)
        api_layout.setContentsMargins(0, 8, 0, 0)

        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText("请输入百度 API Key")
        self.secret_key_input = QLineEdit()
        self.secret_key_input.setPlaceholderText("请输入百度 Secret Key")

        api_layout.addRow("API Key:", self.api_key_input)
        api_layout.addRow("Secret Key:", self.secret_key_input)

        api_note = QLabel(
            "💡 申请地址: console.bce.baidu.com → 语音技术 → 创建应用\n"
            "免费额度：每天 50000 次调用"
        )
        api_note.setStyleSheet("color: #757575; font-size: 12px;")
        api_note.setWordWrap(True)

        recog_layout.addWidget(api_group)
        recog_layout.addWidget(api_note)
        speech_layout.addWidget(recog_group)
        speech_layout.addStretch()

        tabs.addTab(speech_tab, "🎤 语音")

        # ===== 标签页2: 显示 =====
        display_tab = QWidget()
        display_layout = QVBoxLayout(display_tab)
        display_layout.setSpacing(16)

        # 字体大小
        font_group = QGroupBox("📝 文字显示")
        font_layout = QFormLayout(font_group)

        font_size_layout = QHBoxLayout()
        self.font_size_slider = QSlider(Qt.Orientation.Horizontal)
        self.font_size_slider.setRange(16, 64)
        self.font_size_slider.setValue(28)
        self.font_size_label = QLabel("28px")
        self.font_size_label.setMinimumWidth(40)

        font_size_layout.addWidget(self.font_size_slider, 1)
        font_size_layout.addWidget(self.font_size_label)
        self.font_size_slider.valueChanged.connect(
            lambda v: self.font_size_label.setText(f"{v}px")
        )
        font_layout.addRow("字号:", font_size_layout)

        # 行间距
        line_spacing_layout = QHBoxLayout()
        self.line_spacing_slider = QSlider(Qt.Orientation.Horizontal)
        self.line_spacing_slider.setRange(12, 40)  # 1.2x - 4.0x
        self.line_spacing_slider.setValue(20)
        self.line_spacing_label = QLabel("2.0x")
        self.line_spacing_label.setMinimumWidth(40)

        line_spacing_layout.addWidget(self.line_spacing_slider, 1)
        line_spacing_layout.addWidget(self.line_spacing_label)
        self.line_spacing_slider.valueChanged.connect(
            lambda v: self.line_spacing_label.setText(f"{v/10:.1f}x")
        )
        font_layout.addRow("行距:", line_spacing_layout)
        display_layout.addWidget(font_group)

        # 自动全屏
        behavior_group = QGroupBox("⚡ 行为")
        behavior_layout = QVBoxLayout(behavior_group)
        self.auto_fullscreen = QCheckBox("启动后自动全屏")
        behavior_layout.addWidget(self.auto_fullscreen)
        display_layout.addWidget(behavior_group)
        display_layout.addStretch()

        tabs.addTab(display_tab, "📖 显示")

        layout.addWidget(tabs, 1)

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #e0e0e0; color: #424242;
                border: none; border-radius: 6px; padding: 10px 24px;
                font-size: 14px; font-weight: bold;
            }
            QPushButton:hover { background-color: #bdbdbd; }
        """)
        self.cancel_btn.clicked.connect(self.reject)

        self.save_btn = QPushButton("💾 保存设置")
        self.save_btn.setObjectName("primaryBtn")
        self.save_btn.setStyleSheet("""
            QPushButton {
                background-color: #1976d2; color: white;
                border: none; border-radius: 6px; padding: 10px 28px;
                font-size: 14px; font-weight: bold;
            }
            QPushButton:hover { background-color: #1565c0; }
        """)
        self.save_btn.clicked.connect(self._save_settings)

        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.save_btn)
        layout.addLayout(btn_layout)

    def _refresh_mic_list(self):
        """刷新麦克风列表（蓝牙/USB/内置 分类显示）"""
        self.mic_combo.clear()
        self.mic_combo.addItem("🎤 系统默认麦克风", -1)

        try:
            from app.recorder import AudioRecorder
            devices = AudioRecorder.list_devices()
            self.mic_devices = devices

            # 按类型分组显示
            type_order = {"bluetooth": "🔵 蓝牙设备", "usb": "🔌 USB 设备", "builtin": "💻 内置设备"}
            grouped = {"bluetooth": [], "usb": [], "builtin": []}

            for dev in devices:
                dev_type = dev.get("type", "builtin")
                if dev_type not in grouped:
                    dev_type = "builtin"
                grouped[dev_type].append(dev)

            # 设备类型标签
            dev_type_count = sum(1 for g in grouped.values() if g)
            if dev_type_count > 1:
                # 多个类型 → 加分隔标签
                for dtype in ["bluetooth", "usb", "builtin"]:
                    devs = grouped[dtype]
                    if not devs:
                        continue
                    self.mic_combo.addItem(f"── {type_order[dtype]} ──", -2)
                    self._add_devices_to_combo(devs)
            else:
                # 单一类型 → 直接列
                for devs in grouped.values():
                    self._add_devices_to_combo(devs)

        except Exception as e:
            logger.warning(f"获取麦克风列表失败: {e}")
            self.mic_combo.addItem("⚠️ 无法枚举设备", -2)

    def _add_devices_to_combo(self, devices):
        """将设备列表添加到下拉框"""
        for dev in devices:
            icon = dev.get("icon", "🎤")
            name = dev.get("name", f"设备 {dev['index']}")
            channels = dev.get("channels", 0)
            rate = dev.get("rate", 0)
            label = f"{icon} {name}  ({rate/1000:.0f}kHz, {channels}ch)"
            self.mic_combo.addItem(label, dev["index"])

    def _load_settings(self):
        """加载当前设置到界面"""
        # 麦克风
        self._refresh_mic_list()
        mic_idx = self.settings.get("mic_device", -1)
        for i in range(self.mic_combo.count()):
            if self.mic_combo.itemData(i) == mic_idx:
                self.mic_combo.setCurrentIndex(i)
                break

        # 识别方式
        if self.settings.get("recognition_mode") == "online":
            self.radio_online.setChecked(True)
        else:
            self.radio_offline.setChecked(True)

        # API Key
        self.api_key_input.setText(self.settings.get("api_key", ""))
        self.secret_key_input.setText(self.settings.get("secret_key", ""))

        # 显示
        self.font_size_slider.setValue(self.settings.get("font_size", 28))
        self.line_spacing_slider.setValue(
            int(self.settings.get("line_spacing", 2.0) * 10)
        )
        self.auto_fullscreen.setChecked(
            self.settings.get("auto_fullscreen", False)
        )

    def _save_settings(self):
        """保存设置"""
        # 验证
        if self.radio_online.isChecked():
            if not self.api_key_input.text().strip():
                QMessageBox.warning(
                    self, "提示",
                    "在线模式需要填写百度 API Key。\n"
                    "如果暂时没有，请先选择离线模式。"
                )
                return
            if not self.secret_key_input.text().strip():
                QMessageBox.warning(
                    self, "提示",
                    "请填写百度 Secret Key。"
                )
                return

        self.settings = {
            "mic_device": self.mic_combo.currentData(),
            "mic_device_name": self.mic_combo.currentText(),
            "recognition_mode": "online" if self.radio_online.isChecked() else "offline",
            "api_key": self.api_key_input.text().strip(),
            "secret_key": self.secret_key_input.text().strip(),
            "font_size": self.font_size_slider.value(),
            "line_spacing": round(self.line_spacing_slider.value() / 10, 1),
            "auto_fullscreen": self.auto_fullscreen.isChecked(),
        }

        self.settings_saved.emit(self.settings)
        self.accept()

    def _load_defaults(self):
        """加载默认设置"""
        return {
            "mic_device": -1,
            "mic_device_name": "系统默认",
            "recognition_mode": "offline",
            "api_key": "",
            "secret_key": "",
            "font_size": 28,
            "line_spacing": 2.0,
            "auto_fullscreen": False,
        }
