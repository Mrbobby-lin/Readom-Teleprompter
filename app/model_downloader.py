"""
faster-whisper 模型下载器
自动从 HuggingFace 镜像站下载中文语音模型到本地缓存
"""

import os
import logging

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QProgressBar, QMessageBox,
)
from PySide6.QtCore import Qt, QThread, Signal

logger = logging.getLogger(__name__)


# faster-whisper 模型信息
# 下载源使用 HuggingFace 中国镜像站 hf-mirror.com
WHISPER_MODELS = {
    "tiny": {
        "name": "faster-whisper 中文小模型 (75MB)",
        "repo_id": "Systran/faster-whisper-tiny",
        "size_mb": 75,
        "description": "轻量级离线中文识别，日常使用足够，CPU 流畅运行",
    },
    "base": {
        "name": "faster-whisper 中文基础模型 (150MB)",
        "repo_id": "Systran/faster-whisper-base",
        "size_mb": 150,
        "description": "精度更高，推荐有一定内存的设备使用",
    },
}


def get_cache_dir():
    """获取 huggingface 模型缓存目录"""
    default = os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")
    return os.environ.get("HF_HOME") or os.environ.get("XDG_CACHE_HOME") \
        and os.path.join(os.environ["XDG_CACHE_HOME"], "huggingface", "hub") \
        or default


def is_model_available(model_size="tiny"):
    """
    检查 faster-whisper 模型是否已缓存
    检查 huggingface hub 缓存目录中是否存在对应模型文件
    """
    repo_id = f"Systran/faster-whisper-{model_size}"
    # huggingface hub 的缓存命名规则：
    # models--Systran--faster-whisper-tiny
    repo_dir = "models--" + repo_id.replace("/", "--")
    cache_dir = get_cache_dir()
    model_path = os.path.join(cache_dir, repo_dir)

    if os.path.isdir(model_path):
        # 检查是否有实际模型文件（不只是元数据）
        for _, _, files in os.walk(model_path):
            for f in files:
                if f.endswith(".bin") or f.endswith(".safetensors"):
                    return True
    return False


class DownloadThread(QThread):
    """后台模型下载线程"""
    progress = Signal(int, str)    # 进度百分比, 状态文字
    finished = Signal(bool, str)   # 成功/失败, 消息

    def __init__(self, repo_id, model_size="tiny"):
        super().__init__()
        self.repo_id = repo_id
        self.model_size = model_size
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        """执行下载（按策略尝试多个下载源）"""
        # 下载策略列表：先试官方源，再试镜像
        strategies = [
            ("HuggingFace 官方源", ""),
            ("HuggingFace 镜像站 (hf-mirror.com)", "https://hf-mirror.com"),
        ]

        last_error = ""
        for strategy_name, endpoint in strategies:
            if self._cancel:
                self.finished.emit(False, "下载已取消")
                return

            self.progress.emit(10, f"正在连接 {strategy_name}...")

            try:
                # 临时设置下载源
                old_endpoint = os.environ.pop("HF_ENDPOINT", None)
                if endpoint:
                    os.environ["HF_ENDPOINT"] = endpoint

                from huggingface_hub import snapshot_download

                cache_dir = get_cache_dir()

                self.progress.emit(20, "正在下载模型（约 75MB），请稍候...")

                snapshot_download(
                    repo_id=self.repo_id,
                    cache_dir=cache_dir,
                    resume_download=True,
                    local_files_only=False,
                    ignore_patterns=["*.ot", "*.md"],
                )

                if self._cancel:
                    self.finished.emit(False, "下载已取消")
                    return

                self.progress.emit(100, "✅ 模型下载完成！")
                self.finished.emit(True, "")
                return

            except Exception as e:
                last_error = str(e)
                logger.warning(f"{strategy_name} 下载失败: {e}")
                self.progress.emit(10, f"{strategy_name} 失败，尝试其他源...")
            finally:
                # 恢复 endpoint
                if old_endpoint:
                    os.environ["HF_ENDPOINT"] = old_endpoint
                else:
                    os.environ.pop("HF_ENDPOINT", None)

        # 所有源都失败
        error_msg = last_error.lower()
        if "404" in error_msg:
            self.finished.emit(False, f"模型未找到: {self.repo_id}")
        elif "timeout" in error_msg or "timed out" in error_msg:
            self.finished.emit(
                False,
                "连接 HuggingFace 超时。你可以:\n\n"
                "1. 检查网络连接后重试\n"
                "2. 在「设置」中切换到在线模式（百度 API）\n"
                "3. 手动下载模型并放到缓存目录"
            )
        else:
            self.finished.emit(False, f"下载失败:\n{last_error}")


class ModelDownloadDialog(QDialog):
    """模型下载对话框（faster-whisper 版）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("下载离线语音模型")
        self.setMinimumSize(520, 320)
        self.setMaximumSize(600, 420)

        self.download_thread = None
        self.selected_model = "tiny"
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # 标题
        title = QLabel("📥 下载离线语音识别模型")
        title.setStyleSheet(
            "font-size: 20px; font-weight: bold; color: #1565c0;"
        )
        layout.addWidget(title)

        desc = QLabel(
            "使用 faster-whisper 引擎，基于 OpenAI Whisper 架构，\n"
            "中文识别准确率高，CPU 上也能流畅运行。\n"
            "推荐「tiny 小模型」(75MB)，日常使用足够了。"
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size: 14px; color: #616161;")
        layout.addWidget(desc)

        # 模型信息
        self.model_info = QLabel()
        self.model_info.setWordWrap(True)
        self.model_info.setStyleSheet(
            "background-color: #e3f2fd; padding: 12px; "
            "border-radius: 6px; font-size: 13px;"
        )
        self._update_model_info()
        layout.addWidget(self.model_info)

        # 镜像说明
        mirror_note = QLabel(
            "🔗 通过 HuggingFace 中国镜像站 (hf-mirror.com) 下载\n"
            "首次使用需下载模型（之后离线可用）"
        )
        mirror_note.setStyleSheet("color: #757575; font-size: 12px;")
        mirror_note.setWordWrap(True)
        layout.addWidget(mirror_note)

        # 进度条和状态
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(20)
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("就绪，点击下方按钮开始下载")
        self.status_label.setStyleSheet("color: #757575; font-size: 13px;")
        layout.addWidget(self.status_label)

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.cancel_btn = QPushButton("关闭")
        self.cancel_btn.clicked.connect(self._on_cancel)

        self.download_btn = QPushButton("⬇ 下载小模型 (75MB)")
        self.download_btn.setObjectName("primaryBtn")
        self.download_btn.setMinimumWidth(250)
        self.download_btn.clicked.connect(self._start_download)

        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.download_btn)
        layout.addLayout(btn_layout)

    def _update_model_info(self):
        """更新模型信息显示"""
        model = WHISPER_MODELS[self.selected_model]
        self.model_info.setText(
            f"📦 模型: {model['name']}\n"
            f"📏 大小: ~{model['size_mb']}MB\n"
            f"📝 说明: {model['description']}\n"
            f"📂 缓存: {get_cache_dir()}"
        )

    def _start_download(self):
        """开始下载模型"""
        model = WHISPER_MODELS[self.selected_model]

        self.download_btn.setEnabled(False)
        self.cancel_btn.setText("取消下载")

        self.download_thread = DownloadThread(
            model["repo_id"],
            self.selected_model,
        )
        self.download_thread.progress.connect(self._on_progress)
        self.download_thread.finished.connect(self._on_finished)
        self.download_thread.start()

    def _on_progress(self, pct, text):
        """下载进度更新"""
        self.progress_bar.setValue(pct)
        self.status_label.setText(text)

    def _on_finished(self, success, message):
        """下载完成"""
        self.download_btn.setEnabled(True)
        self.cancel_btn.setText("关闭")

        if success:
            QMessageBox.information(
                self, "安装成功",
                "✅ 离线语音模型安装成功！\n\n"
                "现在可以关闭此窗口，使用离线模式了。"
            )
            self.accept()
        else:
            QMessageBox.warning(
                self, "下载失败",
                f"❌ {message}\n\n"
                "你也可以手动下载模型：\n"
                "1. 确保网络连接正常\n"
                "2. 设置镜像: set HF_ENDPOINT=https://hf-mirror.com\n"
                "3. 重新打开程序并下载\n\n"
                "或者在「设置」中切换到在线模式（百度 API）。"
            )
            self.progress_bar.setValue(0)
            self.status_label.setText("就绪，可重新下载或使用在线模式")

    def _on_cancel(self):
        """取消或关闭"""
        if self.download_thread and self.download_thread.isRunning():
            reply = QMessageBox.question(
                self, "确认取消",
                "下载未完成，确定要取消吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.download_thread.cancel()
                self.download_thread.wait(3000)
                self.reject()
        else:
            self.reject()
