#!/usr/bin/env python3
"""
🎤 语音提词器 - 入口文件
运行: python main.py
打包: python package.py
"""

import sys
import os
import re
import logging

# 确保能找到 app 包
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont
from app.main_window import TeleprompterWindow


class GbkSafeHandler(logging.StreamHandler):
    """Windows 控制台安全的日志处理器（GBK 编码容错）"""

    def emit(self, record):
        try:
            msg = self.format(record)
            try:
                self.stream.write(msg + self.terminator)
            except UnicodeEncodeError:
                # GBK 编码无法表示的字符用 ? 替换
                encoded = msg.encode("gbk", errors="replace").decode("gbk")
                self.stream.write(encoded + self.terminator)
            self.flush()
        except Exception:
            self.handleError(record)


def setup_logging():
    """配置日志"""
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    os.makedirs(log_dir, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(
                os.path.join(log_dir, "teleprompter.log"),
                encoding="utf-8",
            ),
            GbkSafeHandler(sys.stdout),
        ],
    )


def load_stylesheet(app):
    """加载 QSS 样式表"""
    style_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "resources", "style.qss",
    )
    if os.path.exists(style_path):
        with open(style_path, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())
    else:
        logging.warning(f"样式表未找到: {style_path}")


def main():
    """程序入口"""
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("=" * 40)
    logger.info("语音提词器 启动")
    logger.info("=" * 40)

    app = QApplication(sys.argv)
    app.setApplicationName("语音提词器")
    app.setOrganizationName("Teleprompter")

    # 设置中文字体
    font = QFont("Microsoft YaHei", 10)
    app.setFont(font)

    # 加载样式
    load_stylesheet(app)

    # 创建主窗口
    window = TeleprompterWindow()
    window.show()

    # 如果设置中开启了自动全屏
    if window.settings.get("auto_fullscreen", False):
        window._toggle_fullscreen()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
