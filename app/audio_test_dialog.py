"""
音频测试对话框
实时显示麦克风输入电平，帮助诊断音频设备问题
"""

import logging
import numpy as np

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton,
    QLabel, QFrame, QGroupBox, QGridLayout,
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QFont

from .recorder import AudioRecorder

logger = logging.getLogger(__name__)


class LevelMeter(QFrame):
    """音频电平指示器 - 自定义 VU 电平表"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(100)
        self.setMaximumHeight(140)
        self._rms = 0.0
        self._peak = 0.0
        self._peak_hold = 0

    def set_level(self, max_val, rms_val):
        """更新电平值 (0.0 ~ 1.0)"""
        # 放大低电平信号使其更可见
        gain = 3.0
        self._rms = min(1.0, rms_val * gain)
        self._peak = max(self._peak, min(1.0, max_val * gain * 0.5))
        if self._peak > 0.01:
            self._peak_hold = 20  # 帧数保持
        elif self._peak_hold > 0:
            self._peak_hold -= 1
        else:
            self._peak = max(0.0, self._peak - 0.005)  # 缓慢衰减
        self.update()

    def paintEvent(self, event):
        """绘制电平表"""
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()

        # 背景
        p.fillRect(0, 0, w, h, QColor("#fafafa"))
        p.setPen(QPen(QColor("#e0e0e0"), 1))
        p.drawRect(0, 0, w - 1, h - 1)

        bar_w = w - 20
        bar_x = 10

        # ====== RMS 电平条（上） ======
        rms_h = h // 3 - 10
        rms_y = 10
        fill_w = int(bar_w * min(1.0, max(self._rms, 0.001) * 1.5))

        # 渐变颜色
        if fill_w > 0:
            if self._rms < 0.4:
                color = QColor("#4caf50")  # 绿
            elif self._rms < 0.7:
                color = QColor("#ff9800")  # 橙
            else:
                color = QColor("#f44336")  # 红
            p.fillRect(bar_x, rms_y, fill_w, rms_h, color)

        p.setPen(QColor("#424242"))
        p.drawText(bar_x, rms_y + rms_h + 14, f"RMS 电平: {self._rms:.4f}")

        # ====== Peak 电平条（下） ======
        peak_h = h // 3 - 10
        peak_y = rms_y + rms_h + 22
        fill_w2 = int(bar_w * min(1.0, max(self._peak, 0.001) * 1.5))

        if fill_w2 > 0:
            if self._peak < 0.3:
                color = QColor("#a5d6a7")
            elif self._peak < 0.6:
                color = QColor("#ffcc80")
            else:
                color = QColor("#ef9a9a")
            p.fillRect(bar_x, peak_y, fill_w2, peak_h, color)

        # 峰值保持线（红色竖线）
        peak_x = bar_x + int(bar_w * min(1.0, self._peak * 1.5))
        p.setPen(QPen(QColor("#d32f2f"), 2))
        p.drawLine(peak_x, peak_y, peak_x, peak_y + peak_h)

        p.setPen(QColor("#424242"))
        p.drawText(bar_x, peak_y + peak_h + 14, f"峰值电平: {self._peak:.4f}")

        # 刻度线
        p.setPen(QPen(QColor("#bdbdbd"), 1, Qt.PenStyle.DotLine))
        for pct in [0.25, 0.5, 0.75]:
            x = bar_x + int(bar_w * pct)
            p.drawLine(x, 5, x, h - 5)

        # 标签
        p.setPen(QColor("#9e9e9e"))
        p.setFont(QFont("Microsoft YaHei", 8))
        p.drawText(bar_x, h - 3, "弱")
        p.drawText(bar_x + bar_w // 4 - 10, h - 3, "中")
        p.drawText(bar_x + bar_w // 2 - 10, h - 3, "强")
        p.drawText(bar_x + int(bar_w * 0.75) - 10, h - 3, "饱和")
        p.drawText(bar_x + bar_w - 30, h - 3, "削波")


class AudioTestDialog(QDialog):
    """音频测试对话框 - 诊断麦克风信号"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🎤 音频测试")
        self.setMinimumSize(520, 460)
        self.setModal(False)

        self._recorder = None
        self._last_levels = {"max": 0.0, "rms": 0.0}
        self._update_timer = QTimer()
        self._update_timer.setInterval(80)  # ~12fps UI 更新
        self._update_timer.timeout.connect(self._refresh_meter)

        self._setup_ui()
        self._refresh_device_list()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # 设备选择行
        sel_layout = QHBoxLayout()
        sel_layout.addWidget(QLabel("🎙 麦克风:"))
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(320)
        sel_layout.addWidget(self.device_combo)
        self.refresh_btn = QPushButton("🔄")
        self.refresh_btn.setToolTip("刷新设备列表")
        self.refresh_btn.setFixedSize(36, 36)
        self.refresh_btn.clicked.connect(self._refresh_device_list)
        sel_layout.addWidget(self.refresh_btn)
        layout.addLayout(sel_layout)

        # 电平表
        self.level_meter = LevelMeter()
        layout.addWidget(self.level_meter)

        # 设备信息
        info_group = QGroupBox("设备信息")
        info_grid = QGridLayout(info_group)
        fields = [
            ("name", "设备名称"),
            ("rate", "采样率"),
            ("channels", "声道数"),
            ("type", "设备类型"),
            ("status", "状态"),
        ]
        self._info_labels = {}
        for i, (key, label) in enumerate(fields):
            info_grid.addWidget(QLabel(f"{label}:"), i, 0)
            lbl = QLabel("-")
            lbl.setStyleSheet("font-weight: bold; color: #1565c0;")
            info_grid.addWidget(lbl, i, 1)
            self._info_labels[key] = lbl
        layout.addWidget(info_group)

        # 控制按钮
        self.toggle_btn = QPushButton("🎤 开始测试")
        self.toggle_btn.setObjectName("testMicBtn")
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setStyleSheet("""
            QPushButton#testMicBtn {
                padding: 12px 24px; font-size: 15px; font-weight: bold;
                background-color: #1565c0; color: white; border: none;
                border-radius: 8px; min-height: 40px;
            }
            QPushButton#testMicBtn:hover { background-color: #0d47a1; }
            QPushButton#testMicBtn:checked {
                background-color: #e53935;
            }
        """)
        self.toggle_btn.toggled.connect(self._on_test_toggle)
        layout.addWidget(self.toggle_btn)

        # 诊断提示
        hint = QLabel(
            "💡 对着麦克风说话，观察电平条是否有波动。\n"
            "   · 电平有波动 → 麦克风正常工作\n"
            "   · 电平无波动 → 麦克风未连接或设备选择错误\n"
            "   · 电平值极低 → 尝试切换不同设备或检查驱动"
        )
        hint.setStyleSheet("color: #757575; font-size: 12px; padding: 8px 4px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

    def _refresh_device_list(self):
        """刷新设备下拉列表"""
        self.device_combo.clear()
        devices = AudioRecorder.list_devices()
        for dev in devices:
            icon = dev.get("icon", "🎤")
            label = f"[{dev['index']}] {icon} {dev['name']} ({dev['rate']}Hz, {dev['type']})"
            self.device_combo.addItem(label, dev)
        if not devices:
            self.device_combo.addItem("⚠ 未找到麦克风设备")

    def _on_test_toggle(self, checked):
        """开始/停止测试"""
        if checked:
            self._start_test()
        else:
            self._stop_test()

    def _start_test(self):
        """启动录音测试"""
        dev_data = self.device_combo.currentData()
        if not dev_data:
            self.toggle_btn.setChecked(False)
            return

        self._recorder = AudioRecorder(self)
        self._recorder.set_device(dev_data["index"])
        self._recorder.audio_data_ready.connect(self._on_audio_chunk)
        self._recorder.status_changed.connect(self._on_status)
        self._recorder.device_info.connect(self._on_device_info)
        self._recorder.start()

        self.toggle_btn.setText("🔴 停止测试")
        self._update_timer.start()

        # 显示设备信息
        self._on_device_info(dev_data)

    def _stop_test(self):
        """停止录音测试"""
        self._update_timer.stop()
        if self._recorder:
            self._recorder.stop()
            self._recorder.wait(2000)
            self._recorder = None

        self.toggle_btn.setText("🎤 开始测试")
        self._info_labels["status"].setText("已停止")
        self.level_meter.set_level(0, 0)

    def _on_audio_chunk(self, data):
        """接收音频数据块 - 只计算电平不阻塞"""
        if len(data) >= 2:
            samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
            abs_vals = np.abs(samples)
            self._last_levels["max"] = float(np.max(abs_vals)) / 32768.0
            self._last_levels["rms"] = float(np.sqrt(np.mean(samples ** 2))) / 32768.0

    def _on_status(self, status):
        self._info_labels["status"].setText(status)

    def _on_device_info(self, info):
        if info:
            self._info_labels["name"].setText(info.get("name", "-"))
            self._info_labels["rate"].setText(f"{info.get('rate', '-')} Hz")
            self._info_labels["channels"].setText(str(info.get("channels", "-")))
            self._info_labels["type"].setText(info.get("type", "-"))

    def _refresh_meter(self):
        """定时刷新电平显示"""
        self.level_meter.set_level(
            self._last_levels["max"], self._last_levels["rms"]
        )

    def closeEvent(self, event):
        """关闭时清理"""
        self._stop_test()
        super().closeEvent(event)
