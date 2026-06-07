"""
全屏提词主窗口
浅蓝背景，大号文字，语音高亮跟随
"""

import os
import re
import logging

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QPushButton, QLabel, QFrame,
    QToolBar, QProgressBar, QFileDialog, QInputDialog,
    QMessageBox, QApplication, QSizePolicy, QScrollBar,
    QDialog,
)
from PySide6.QtCore import Qt, QTimer, Signal, Slot, QPropertyAnimation, QRect
from PySide6.QtGui import QFont, QAction, QKeySequence, QTextCursor

from .text_manager import TextManager
from .matcher import TextMatcher
from .settings_window import SettingsWindow
from .audio_test_dialog import AudioTestDialog

logger = logging.getLogger(__name__)


class TeleprompterWindow(QMainWindow):
    """Readam Teleprompter 主窗口（全屏）"""

    # 语音命令定义（中文）
    VOICE_COMMANDS = {
        "pause": ["暂停", "停一下", "停", "歇一下"],
        "resume": ["继续", "开始", "恢复"],
        "backward": ["后退", "上一句", "回退", "往前"],
        "forward": ["前进", "下一句", "往后"],
        "stop": ["停止", "结束", "关闭"],
    }

    def __init__(self):
        super().__init__()
        self.setObjectName("mainWindow")

        # 核心模块
        self.text_manager = TextManager()
        self.matcher = TextMatcher(self.text_manager)
        self.speech_engine = None
        self.recorder = None

        # 状态
        self.is_fullscreen = False
        self.is_listening = False
        self.settings = self._default_settings()
        self._controls_visible = True  # 全屏时控件可见性

        # 全屏控件显隐定时器
        self._hide_controls_timer = QTimer()
        self._hide_controls_timer.setSingleShot(True)
        self._hide_controls_timer.setInterval(2500)  # 2.5 秒后隐藏
        self._hide_controls_timer.timeout.connect(self._hide_controls)

        self.setMouseTracking(True)

        # 防抖定时器
        self._update_timer = QTimer()
        self._update_timer.setSingleShot(True)
        self._update_timer.setInterval(100)
        self._update_timer.timeout.connect(self._apply_display_update)

        self._pending_result = None
        self._current_mismatch_ranges = []  # 当前句子的读错位置

        # 构建 UI
        self._setup_ui()
        self._setup_shortcuts()

    def _setup_ui(self):
        """构建全屏提词界面"""
        self.setWindowTitle("Readam Teleprompter")
        self.setMinimumSize(800, 600)

        # 中央控件
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ========== 顶部工具栏（鼠标悬停显示） ==========
        self.top_bar = QFrame()
        self.top_bar.setObjectName("topToolbar")
        self.top_bar.setFixedHeight(50)
        self.top_bar.setStyleSheet("""
            QFrame#topToolbar {
                background-color: rgba(21, 101, 192, 0.9);
                border: none;
            }
        """)

        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(16, 6, 16, 6)

        # 标题
        title_label = QLabel("🎤 Readam Teleprompter")
        title_label.setStyleSheet("color: white; font-size: 16px; font-weight: bold;")
        top_layout.addWidget(title_label)
        top_layout.addSpacing(20)

        # 导入按钮组
        self.import_txt_btn = QPushButton("📄 导入 TXT")
        self.import_txt_btn.setObjectName("toolBtn")
        self.import_txt_btn.clicked.connect(self._import_txt)
        top_layout.addWidget(self.import_txt_btn)

        self.import_docx_btn = QPushButton("📝 导入 Word")
        self.import_docx_btn.setObjectName("toolBtn")
        self.import_docx_btn.clicked.connect(self._import_docx)
        top_layout.addWidget(self.import_docx_btn)

        self.paste_btn = QPushButton("📋 粘贴文本")
        self.paste_btn.setObjectName("toolBtn")
        self.paste_btn.clicked.connect(self._paste_text)
        top_layout.addWidget(self.paste_btn)

        top_layout.addStretch()

        self.settings_btn = QPushButton("⚙ 设置")
        self.settings_btn.setObjectName("toolBtn")
        self.settings_btn.clicked.connect(self._open_settings)
        top_layout.addWidget(self.settings_btn)

        self.test_audio_btn = QPushButton("🎤 音频测试")
        self.test_audio_btn.setObjectName("toolBtn")
        self.test_audio_btn.clicked.connect(self._open_audio_test)
        top_layout.addWidget(self.test_audio_btn)

        self.fullscreen_btn = QPushButton("⛶ 全屏")
        self.fullscreen_btn.setObjectName("toolBtn")
        self.fullscreen_btn.clicked.connect(self._toggle_fullscreen)
        top_layout.addWidget(self.fullscreen_btn)

        main_layout.addWidget(self.top_bar)

        # ========== 文本显示区域 ==========
        self.text_display = QTextEdit()
        self.text_display.setObjectName("scriptDisplay")
        self.text_display.setReadOnly(True)
        self.text_display.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.text_display.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.text_display.setStyleSheet("""
            QTextEdit#scriptDisplay {
                background-color: #e3f2fd;
                border: none;
                padding: 40px 60px;
                font-size: 28px;
                color: #212121;
            }
        """)

        self.text_display.setHtml("")
        main_layout.addWidget(self.text_display, 1)

        # ========== 底部控制栏 ==========
        self.bottom_bar = QFrame()
        self.bottom_bar.setObjectName("bottomBar")
        self.bottom_bar.setStyleSheet("""
            QFrame#bottomBar {
                background-color: rgba(255, 255, 255, 0.95);
                border-top: 1px solid #bbdefb;
            }
        """)

        bottom_layout = QHBoxLayout(self.bottom_bar)
        bottom_layout.setContentsMargins(16, 8, 16, 8)
        bottom_layout.setSpacing(8)

        # 按钮通用样式（全屏和非全屏自适应）
        btn_style_base = """
            QPushButton {
                padding: 8px 14px; font-size: 13px; font-weight: bold;
                border: none; border-radius: 6px;
                min-width: 70px;
            }
        """

        # 左侧: 控制按钮
        self.btn_prev = QPushButton("◀◀")
        self.btn_prev.setObjectName("controlBtn")
        self.btn_prev.setToolTip("后退（←）")
        self.btn_prev.clicked.connect(self._navigate_prev)
        self.btn_prev.setEnabled(False)
        self.btn_prev.setStyleSheet(btn_style_base + """
            QPushButton { background-color: #1976d2; color: white; }
            QPushButton:hover { background-color: #1565c0; }
            QPushButton:disabled { background-color: #b0bec5; color: #eceff1; }
        """)
        bottom_layout.addWidget(self.btn_prev)

        self.btn_toggle = QPushButton("▶ 开始")
        self.btn_toggle.setObjectName("primaryBtn")
        self.btn_toggle.setToolTip("开始/暂停（Space）")
        self.btn_toggle.clicked.connect(self._toggle_listening)
        self.btn_toggle.setMinimumWidth(100)
        self.btn_toggle.setStyleSheet(btn_style_base + """
            QPushButton { background-color: #1565c0; color: white; min-width: 100px; padding: 10px 24px; font-size: 15px; }
            QPushButton:hover { background-color: #0d47a1; }
        """)
        bottom_layout.addWidget(self.btn_toggle)

        self.btn_next = QPushButton("▶▶")
        self.btn_next.setObjectName("controlBtn")
        self.btn_next.setToolTip("前进（→）")
        self.btn_next.clicked.connect(self._navigate_next)
        self.btn_next.setEnabled(False)
        self.btn_next.setStyleSheet(btn_style_base + """
            QPushButton { background-color: #1976d2; color: white; }
            QPushButton:hover { background-color: #1565c0; }
            QPushButton:disabled { background-color: #b0bec5; color: #eceff1; }
        """)
        bottom_layout.addWidget(self.btn_next)

        self.btn_stop = QPushButton("■")
        self.btn_stop.setObjectName("dangerBtn")
        self.btn_stop.setToolTip("停止")
        self.btn_stop.clicked.connect(self._stop_listening)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setStyleSheet(btn_style_base + """
            QPushButton { background-color: #e53935; color: white; }
            QPushButton:hover { background-color: #c62828; }
            QPushButton:disabled { background-color: #b0bec5; color: #eceff1; }
        """)
        bottom_layout.addWidget(self.btn_stop)

        # 中间: 进度条 + 状态
        progress_layout = QVBoxLayout()
        progress_layout.setSpacing(1)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedHeight(10)
        progress_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("💡 请导入或粘贴演讲稿")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("color: #1565c0; font-size: 12px;")
        progress_layout.addWidget(self.status_label)

        bottom_layout.addLayout(progress_layout, 1)

        # 右侧: 文档名
        self.doc_label = QLabel("")
        self.doc_label.setStyleSheet("color: #9e9e9e; font-size: 11px;")
        self.doc_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.doc_label.setMaximumWidth(150)
        bottom_layout.addWidget(self.doc_label)

        main_layout.addWidget(self.bottom_bar)

        # 现在所有控件都已创建，显示占位提示
        self._show_placeholder()

    def _setup_shortcuts(self):
        """设置键盘快捷键"""
        # 空格: 开始/暂停
        space_action = QAction("开始/暂停", self)
        space_action.setShortcut(QKeySequence(Qt.Key.Key_Space))
        space_action.triggered.connect(self._toggle_listening)
        self.addAction(space_action)

        # Escape: 退出全屏
        esc_action = QAction("退出全屏", self)
        esc_action.setShortcut(QKeySequence(Qt.Key.Key_Escape))
        esc_action.triggered.connect(self._exit_fullscreen)
        self.addAction(esc_action)

        # F11: 切换全屏
        f11_action = QAction("切换全屏", self)
        f11_action.setShortcut(QKeySequence(Qt.Key.Key_F11))
        f11_action.triggered.connect(self._toggle_fullscreen)
        self.addAction(f11_action)

        # 方向键
        left_action = QAction("后退", self)
        left_action.setShortcut(QKeySequence(Qt.Key.Key_Left))
        left_action.triggered.connect(self._navigate_prev)
        self.addAction(left_action)

        right_action = QAction("前进", self)
        right_action.setShortcut(QKeySequence(Qt.Key.Key_Right))
        right_action.triggered.connect(self._navigate_next)
        self.addAction(right_action)

    def _default_settings(self):
        """默认设置"""
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

    # ========== 文本导入 ==========

    def _show_placeholder(self):
        """显示占位提示"""
        self.text_display.setHtml("""
            <div style="text-align:center; padding-top:120px; color:#90caf9;">
                <div style="font-size:48px; margin-bottom:20px;">🎤</div>
                <div style="font-size:24px; margin-bottom:12px; color:#64b5f6;">
                    Readam Teleprompter
                </div>
                <div style="font-size:16px; color:#bbdefb;">
                    点击上方工具栏「导入 TXT / Word」或「粘贴文本」开始
                </div>
                <div style="font-size:14px; color:#bbdefb; margin-top:20px;">
                    准备好后，点击底部「▶ 开始」按钮开始朗读
                </div>
            </div>
        """)
        self.progress_bar.setValue(0)
        self.status_label.setText("💡 请导入或粘贴演讲稿")

    def _import_txt(self):
        """导入 TXT 文件"""
        if self.is_listening:
            self._stop_listening()

        filepath, _ = QFileDialog.getOpenFileName(
            self, "导入 TXT 文件", "",
            "文本文件 (*.txt);;所有文件 (*)"
        )
        if not filepath:
            return

        try:
            self.text_manager.load_from_txt(filepath)
            self._on_text_loaded()
        except Exception as e:
            QMessageBox.warning(self, "导入失败", f"无法读取文件:\n{e}")

    def _import_docx(self):
        """导入 Word 文档"""
        if self.is_listening:
            self._stop_listening()

        filepath, _ = QFileDialog.getOpenFileName(
            self, "导入 Word 文档", "",
            "Word 文档 (*.docx);;所有文件 (*)"
        )
        if not filepath:
            return

        try:
            self.text_manager.load_from_docx(filepath)
            self._on_text_loaded()
        except ImportError:
            QMessageBox.warning(
                self, "缺少依赖",
                "请安装 python-docx 库以支持 Word 文档:\n"
                "pip install python-docx"
            )
        except Exception as e:
            QMessageBox.warning(self, "导入失败", f"无法读取文件:\n{e}")

    def _paste_text(self):
        """粘贴文本"""
        if self.is_listening:
            self._stop_listening()

        text, ok = QInputDialog.getMultiLineText(
            self, "粘贴演讲稿", "请将演讲稿粘贴到下方："
        )
        if ok and text.strip():
            self.text_manager.load_from_text(text.strip())
            self._on_text_loaded()

    def _on_text_loaded(self):
        """文本加载完成后的处理"""
        total = self.text_manager.get_sentence_count()
        self.matcher.reset()
        self.matcher.set_total_sentences(total)

        # 更新显示
        self._refresh_display()
        self.progress_bar.setValue(0)

        title = self.text_manager.title or "演讲稿"
        self.doc_label.setText(f"📄 {title}")
        self.status_label.setText(
            f"✅ 已加载 {total} 句，点击「▶ 开始」朗读"
        )

        # 启用按钮
        self.btn_toggle.setEnabled(True)
        self.btn_toggle.setText("▶ 开始")
        self.is_listening = False

        logger.info(f"文本已加载: {title}, {total} 句")

    # ========== 显示更新 ==========

    def _refresh_display(self):
        """刷新文本显示（完整重建 HTML）"""
        if not self.text_manager.has_text():
            self._show_placeholder()
            return

        html_parts = ['<div style="font-size:{}px; line-height:{};">'.format(
            self.settings.get("font_size", 28),
            self.settings.get("line_spacing", 2.0),
        )]

        current_idx = self.matcher.current_sent_idx

        for p in self.text_manager.paragraphs:
            if not p.sentences:
                continue

            html_parts.append('<p style="margin: 0 0 8px 0;">')

            for s in p.sentences:
                if s.s_idx == current_idx or (
                    self.matcher.total_sentences > 1
                    and abs(s.s_idx - current_idx) <= 0
                    and s.s_idx == current_idx
                ):
                    # 当前句子：深蓝背景高亮，读错部分红色
                    if self._current_mismatch_ranges:
                        html_parts.append(
                            self._render_with_mismatch(
                                s.text, self._current_mismatch_ranges
                            )
                        )
                    else:
                        html_parts.append(
                            '<span style="background-color: #1565c0; '
                            'color: #ffffff; padding: 2px 4px; '
                            'border-radius: 4px;">{}</span>'.format(
                                self._escape_html(s.text)
                            )
                        )
                elif s.is_read or (
                    self.matcher.total_sentences > 1
                    and s.s_idx < current_idx
                ):
                    # 已读：灰色
                    html_parts.append(
                        '<span style="color: #9e9e9e;">{}</span>'.format(
                            self._escape_html(s.text)
                        )
                    )
                else:
                    # 未读：黑色
                    html_parts.append(
                        '<span style="color: #212121;">{}</span>'.format(
                            self._escape_html(s.text)
                        )
                    )

            html_parts.append("</p>")

        html_parts.append("</div>")
        self.text_display.setHtml("".join(html_parts))
        self._scroll_to_current()

    def _scroll_to_current(self):
        """滚动到当前句子位置"""
        # 使用 QTextEdit 的 find 功能定位到高亮区域
        cursor = self.text_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self.text_display.setTextCursor(cursor)

        # 向下滚动到高亮文本
        current_text = self.matcher.get_current_text()
        if current_text:
            # 查找当前句子
            found = self.text_display.find(current_text)
            if found:
                # 确保在可视区域中央
                self.text_display.ensureCursorVisible()
                # 额外滚动到居中位置
                sb = self.text_display.verticalScrollBar()
                QTimer.singleShot(50, lambda: self._smooth_scroll(sb))

    def _smooth_scroll(self, scrollbar):
        """平滑滚动到当前行居中"""
        if not scrollbar:
            return
        # 获取光标位置并滚动到可视区域中间
        cursor = self.text_display.textCursor()
        rect = self.text_display.cursorRect(cursor)
        viewport_height = self.text_display.viewport().height()
        target_y = max(0, rect.top() - viewport_height // 3)
        scrollbar.setValue(scrollbar.value() + rect.top() - viewport_height // 3)

    def _apply_display_update(self):
        """应用延迟的显示更新（防抖）"""
        if self._pending_result:
            result = self._pending_result
            self._pending_result = None

            sent_idx = result["sent_idx"]
            progress = result["progress"]
            confidence = result["confidence"]

            # 更新进度条
            self.progress_bar.setValue(int(progress * 100))

            # 更新状态
            if confidence > 0:
                self.status_label.setText(
                    f"🎙 正在朗读... 第 {sent_idx + 1}/{self.matcher.total_sentences} 句"
                )

            # 刷新高亮显示
            self._refresh_display()

    def _render_with_mismatch(self, text, mismatch_ranges):
        """
        渲染带读错标记的句子 HTML
        读错部分显示为红底白字，正确部分为蓝底白字
        """
        escaped = self._escape_html(text)

        if not mismatch_ranges:
            return (
                '<span style="background-color: #1565c0; color: #ffffff; '
                'padding: 2px 4px; border-radius: 4px;">'
                f'{escaped}</span>'
            )

        # 将文本分割为正常段和错读段
        parts = []
        last_end = 0

        for start, end in sorted(mismatch_ranges):
            # 正常部分（蓝底白字）
            if start > last_end:
                normal = escaped[last_end:start]
                if normal:
                    parts.append(
                        '<span style="background-color: #1565c0; color: #ffffff;">'
                        f'{normal}</span>'
                    )
            # 读错部分（红底白字，加粗）
            wrong = escaped[start:end]
            if wrong:
                parts.append(
                    '<span style="background-color: #c62828; color: #ffffff; '
                    'font-weight: bold; border-radius: 2px; padding: 0 1px;">'
                    f'{wrong}</span>'
                )
            last_end = end

        # 剩余正常部分
        if last_end < len(escaped):
            normal = escaped[last_end:]
            if normal:
                parts.append(
                    '<span style="background-color: #1565c0; color: #ffffff;">'
                    f'{normal}</span>'
                )

        return (
            '<span style="padding: 2px 4px; border-radius: 4px; '
            'background-color: #1565c0;">'
            f'{"".join(parts)}</span>'
        )

    def _escape_html(self, text):
        """转义 HTML 特殊字符"""
        text = text.replace("&", "&amp;")
        text = text.replace("<", "&lt;")
        text = text.replace(">", "&gt;")
        text = text.replace('"', "&quot;")
        text = text.replace("'", "&#39;")
        return text

    # ========== 语音识别控制 ==========

    def _toggle_listening(self):
        """切换开始/暂停"""
        if not self.text_manager.has_text():
            QMessageBox.information(self, "提示", "请先导入或粘贴演讲稿")
            return

        if not self.is_listening:
            self._start_listening()
        else:
            if self.recorder and self.recorder.is_paused:
                self._resume_listening()
            else:
                self._pause_listening()

    def _start_listening(self):
        """开始语音识别"""
        # 防止重复启动
        if self.is_listening and self.recorder and self.recorder.is_active:
            return

        # 初始化语音引擎
        if not self._init_speech_engine():
            return

        self.is_listening = True
        self.btn_toggle.setText("⏸ 暂停")
        self.btn_stop.setEnabled(True)
        self.btn_prev.setEnabled(True)
        self.btn_next.setEnabled(True)

        # 禁用导入按钮
        self._set_import_buttons_enabled(False)

        # 启动录音
        self.recorder.start()

        self.status_label.setText("🎙 正在聆听...")
        logger.info("语音识别已启动")

    def _pause_listening(self):
        """暂停语音识别"""
        if self.recorder:
            self.recorder.pause()
        self.btn_toggle.setText("▶ 继续")
        self.status_label.setText("⏸ 已暂停")

    def _resume_listening(self):
        """继续语音识别"""
        if self.recorder:
            self.recorder.resume()
        self.btn_toggle.setText("⏸ 暂停")
        self.status_label.setText("🎙 正在聆听...")

    def _stop_listening(self):
        """停止语音识别"""
        self.is_listening = False
        if self.recorder:
            try:
                self.recorder.stop()
                if not self.recorder.wait(3000):  # 最多等 3 秒
                    logger.warning("录音线程未及时退出")
            except Exception as e:
                logger.warning(f"停止录音时出错: {e}")
            self.recorder = None

        if self.speech_engine:
            try:
                self.speech_engine.cleanup()
            except Exception as e:
                logger.warning(f"清理引擎时出错: {e}")
            self.speech_engine = None

        self._pending_result = None
        self._current_mismatch_ranges = []
        self._update_timer.stop()

        self.btn_toggle.setText("▶ 开始")
        self.btn_stop.setEnabled(False)
        self._set_import_buttons_enabled(True)

        self.status_label.setText("⏹ 已停止")
        logger.info("语音识别已停止")

    def _init_speech_engine(self):
        """初始化语音识别引擎"""
        mode = self.settings.get("recognition_mode", "offline")

        if mode == "offline":
            # 先检查是否有可用模型
            from .model_downloader import is_model_available, ModelDownloadDialog
            if not is_model_available():
                reply = QMessageBox.question(
                    self, "需要下载语音模型",
                    "离线模式需要下载中文语音模型（约 42MB）才能工作。\n\n"
                    "是否现在下载？\n"
                    "（也可选择「在线模式」使用阿里云语音 API）",
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                if reply == QMessageBox.StandardButton.Yes:
                    dialog = ModelDownloadDialog(self)
                    if dialog.exec() != QDialog.DialogCode.Accepted:
                        self.status_label.setText("⏹ 模型未下载，无法启动离线引擎")
                        return False
                else:
                    self.status_label.setText(
                        "💡 可在「设置」中切换到在线模式"
                    )
                    return False

            from .speech.faster_whisper_engine import FasterWhisperEngine
            try:
                self.speech_engine = FasterWhisperEngine(model_size="tiny")
                self.speech_engine.initialize()
                self.status_label.setText("🔊 离线引擎就绪")
            except Exception as e:
                QMessageBox.warning(
                    self, "离线引擎启动失败",
                    f"启动失败: {e}\n\n"
                    "可以尝试在「设置」中切换到在线模式（阿里云语音）。"
                )
                return False
        else:
            from .speech.aliyun_engine import AliyunEngine
            appkey = self.settings.get("aliyun_appkey", "")
            akid = self.settings.get("aliyun_access_key_id", "")
            aksecret = self.settings.get("aliyun_access_key_secret", "")
            if not appkey or not akid or not aksecret:
                QMessageBox.warning(
                    self, "缺少 API Key",
                    "在线模式需要填写阿里云 AppKey、AccessKey ID 和 Secret。\n"
                    "请点击「设置」进行配置。\n"
                    "或在设置中切换到离线模式。"
                )
                return False
            try:
                self.speech_engine = AliyunEngine(appkey, akid, aksecret)
                self.speech_engine.initialize()
                self.status_label.setText("🌐 在线引擎就绪")
            except Exception as e:
                QMessageBox.warning(self, "在线引擎启动失败", str(e))
                return False

        # 初始化录音器
        from .recorder import AudioRecorder
        self.recorder = AudioRecorder()
        self.recorder.set_device(self.settings.get("mic_device", -1))
        self.recorder.audio_data_ready.connect(self._on_audio_data)
        self.recorder.status_changed.connect(self._on_recorder_status)
        self.recorder.error_occurred.connect(self._on_recorder_error)
        self.recorder.device_info.connect(self._on_device_info)

        return True

    def _on_audio_data(self, audio_data):
        """处理音频数据（在后台线程调用，需要尽快返回）"""
        if not self.speech_engine:
            return

        result = self.speech_engine.process_audio(audio_data)
        text = result.get("text", "").strip()
        is_final = result.get("is_final", False)

        if not text:
            return

        # 先检查语音命令
        if self._check_voice_command(text):
            return

        # 交给匹配器
        match_result = self.matcher.match(text)

        # 计算读错位置（当前句子内识别文本与原文的差异）
        if match_result["confidence"] > 0:
            sent_text = match_result.get("text", "")
            if sent_text:
                mismatch_ranges = self.matcher.calc_mismatch(text, sent_text)
                match_result["mismatch_ranges"] = mismatch_ranges
                self._current_mismatch_ranges = mismatch_ranges
            # 新句子时清除旧的读错标记
            if match_result.get("is_new_sentence"):
                self._current_mismatch_ranges = []

        # 只需更新高亮 - 使用防抖
        if match_result["confidence"] > 0:
            self._pending_result = match_result
            self._update_timer.start()

    def _check_voice_command(self, text):
        """检查是否是语音命令"""
        clean = re.sub(r"[^一-鿿]", "", text)

        for cmd, keywords in self.VOICE_COMMANDS.items():
            for keyword in keywords:
                if keyword in clean or keyword in text:
                    logger.info(f"语音命令: {keyword} → {cmd}")
                    if cmd == "pause":
                        self._pause_listening()
                    elif cmd == "resume":
                        self._resume_listening()
                    elif cmd == "backward":
                        self._navigate_prev()
                    elif cmd == "forward":
                        self._navigate_next()
                    elif cmd == "stop":
                        self._stop_listening()
                    return True
        return False

    def _on_recorder_status(self, status):
        """录音器状态变化"""
        pass  # 状态已在其他地方更新

    def _on_recorder_error(self, error_msg):
        """录音器错误"""
        logger.error(f"录音错误: {error_msg}")
        self._stop_listening()
        QMessageBox.warning(self, "麦克风错误", error_msg)

    def _on_device_info(self, info):
        """设备信息回调"""
        dev_type = info.get("type", "未知")
        name = info.get("name", "")
        rate = info.get("rate", 0)
        type_names = {
            "bluetooth": "🔵 蓝牙麦克风",
            "usb": "🔌 USB 麦克风",
            "builtin": "💻 内置麦克风",
        }
        type_str = type_names.get(dev_type, "🎤 麦克风")
        logger.info(f"设备信息: {type_str} - {name} ({rate}Hz)")
        # 在状态栏显示设备信息
        self.status_label.setText(
            f"🎙 {type_str} 已就绪 ({rate/1000:.0f}kHz)"
        )

    # ========== 全屏控制显隐 ==========

    def enterEvent(self, event):
        """鼠标进入窗口：显示控件，重置隐藏计时器"""
        if self.is_fullscreen:
            self._show_controls()
            self._hide_controls_timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        """鼠标离开窗口：快速隐藏控件"""
        if self.is_fullscreen:
            self._hide_controls_timer.stop()
            self._hide_controls()
        super().leaveEvent(event)

    def mouseMoveEvent(self, event):
        """鼠标移动：在顶部/底部区域时显示控件"""
        if self.is_fullscreen:
            pos = event.position().y()
            near_top = pos < 60
            near_bottom = pos > self.height() - 80

            if near_top or near_bottom:
                self._show_controls()
                self._hide_controls_timer.start()
            else:
                # 不在边缘时延迟隐藏
                self._hide_controls_timer.start()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        """点击窗口：切换控件显隐"""
        if self.is_fullscreen:
            # 点击在控件区域则不切换
            pos = event.position().y()
            if pos < 60 or pos > self.height() - 80:
                pass  # 让默认行为处理
            else:
                if self._controls_visible:
                    self._hide_controls()
                else:
                    self._show_controls()
        super().mousePressEvent(event)

    def _show_controls(self):
        """显示顶部和底部控件"""
        if not self._controls_visible and self.is_fullscreen:
            self.top_bar.setVisible(True)
            self.bottom_bar.setVisible(True)
            self._controls_visible = True

    def _hide_controls(self):
        """隐藏顶部和底部控件（全屏时）"""
        if self._controls_visible and self.is_fullscreen and not self._hide_controls_timer.isActive():
            # 如果正在聆听中，保持底部栏可见
            if self.is_listening:
                return
        if self._controls_visible and self.is_fullscreen:
            self.top_bar.setVisible(False)
            self.bottom_bar.setVisible(False)
            self._controls_visible = False

    # ========== 导航 ==========

    def _navigate_prev(self):
        """上一句"""
        if not self.text_manager.has_text():
            return
        new_idx = max(0, self.matcher.current_sent_idx - 1)
        self.matcher.current_sent_idx = new_idx
        self._current_mismatch_ranges = []  # 导航时清除读错标记
        self._refresh_display()
        progress = new_idx / max(1, self.matcher.total_sentences - 1)
        self.progress_bar.setValue(int(progress * 100))

    def _navigate_next(self):
        """下一句"""
        if not self.text_manager.has_text():
            return
        max_idx = self.matcher.total_sentences - 1
        new_idx = min(max_idx, self.matcher.current_sent_idx + 1)
        self.matcher.current_sent_idx = new_idx
        self._current_mismatch_ranges = []  # 导航时清除读错标记
        self._refresh_display()
        progress = new_idx / max(1, max_idx)
        self.progress_bar.setValue(int(progress * 100))

    # ========== 设置 ==========

    def _open_settings(self):
        """打开设置窗口"""
        win = SettingsWindow(self, self.settings)
        win.settings_saved.connect(self._on_settings_saved)
        win.exec()

    def _open_audio_test(self):
        """打开音频测试对话框"""
        dialog = AudioTestDialog(self)
        dialog.show()

    def _on_settings_saved(self, settings):
        """设置已保存"""
        self.settings = settings
        logger.info("设置已更新")

        # 如果正在运行，需要重启
        if self.is_listening:
            self._stop_listening()
            self.status_label.setText("⚙ 设置已更新，点击「开始」重新启动")

        # 更新字体显示
        self._refresh_display()

    # ========== 全屏控制 ==========

    def _toggle_fullscreen(self):
        """切换全屏"""
        if self.is_fullscreen:
            self._exit_fullscreen()
        else:
            self.showFullScreen()
            self.is_fullscreen = True
            self.fullscreen_btn.setText("⛶ 窗口")
            self.top_bar.setFixedHeight(36)
            # 显示控件，开始自动隐藏计时
            self._show_controls()
            self._hide_controls_timer.start()

    def _exit_fullscreen(self):
        """退出全屏"""
        if self.is_fullscreen:
            self.showNormal()
            self.is_fullscreen = False
            self.fullscreen_btn.setText("⛶ 全屏")
            self.top_bar.setFixedHeight(50)
            # 确保控件可见
            self.top_bar.setVisible(True)
            self.bottom_bar.setVisible(True)
            self._controls_visible = True
            self._hide_controls_timer.stop()

    # ========== 辅助 ==========

    def _set_import_buttons_enabled(self, enabled):
        """启用/禁用导入按钮"""
        self.import_txt_btn.setEnabled(enabled)
        self.import_docx_btn.setEnabled(enabled)
        self.paste_btn.setEnabled(enabled)
        self.settings_btn.setEnabled(enabled)

    def closeEvent(self, event):
        """窗口关闭时的清理"""
        self._stop_listening()
        super().closeEvent(event)


# 辅助方法 - 给 matcher 添加获取当前文本功能
def _get_current_text(self):
    """获取当前句子文本（补丁方法）"""
    idx = self.current_sent_idx
    if hasattr(self, 'tm') and 0 <= idx < len(self.tm.sentences):
        return self.tm.sentences[idx].text
    return ""

TextMatcher.get_current_text = _get_current_text
