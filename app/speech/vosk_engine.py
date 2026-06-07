"""
Vosk 离线语音识别引擎
使用 Vosk 轻量模型，无需网络连接，适合中文离线识别
"""

import os
import json
import logging
from .engine_base import SpeechEngine

logger = logging.getLogger(__name__)


class VoskEngine(SpeechEngine):
    """Vosk 离线语音识别引擎"""

    def __init__(self, model_path=None):
        self.model = None
        self.recognizer = None
        self.model_path = model_path or self._find_model()
        self._is_ready = False

    def _find_model(self):
        """自动查找模型目录"""
        # 在 resources/ 下找 vosk-model 目录
        base_dir = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        resources_dir = os.path.join(base_dir, "resources")
        if os.path.isdir(resources_dir):
            for item in os.listdir(resources_dir):
                if item.startswith("vosk-model"):
                    return os.path.join(resources_dir, item)
        return None

    @property
    def name(self):
        return "Vosk 离线识别"

    @property
    def requires_api_key(self):
        return False

    def initialize(self):
        """初始化 Vosk 模型"""
        try:
            from vosk import Model, KaldiRecognizer
        except ImportError:
            raise ImportError(
                "请安装 Vosk: pip install vosk\n"
                "并下载中文模型放在 resources/vosk-model-* 目录"
            )

        if not self.model_path or not os.path.isdir(self.model_path):
            raise FileNotFoundError(
                f"找不到 Vosk 模型目录: {self.model_path}\n"
                f"请从 https://alphacephei.com/vosk/models 下载中文模型，\n"
                f"解压到 resources/ 目录下"
            )

        logger.info(f"正在加载 Vosk 模型: {self.model_path}")
        self.model = Model(self.model_path)
        # 16000 Hz, 16-bit mono PCM
        self.recognizer = KaldiRecognizer(self.model, 16000)
        self.recognizer.SetWords(True)
        self._is_ready = True
        logger.info("Vosk 模型加载完成")

    def process_audio(self, audio_data):
        """
        处理音频数据，返回识别结果
        audio_data: bytes, 16000Hz 16-bit mono PCM
        """
        if not self._is_ready or not self.recognizer:
            return {"text": "", "is_final": False}

        try:
            if self.recognizer.AcceptWaveform(audio_data):
                # 最终结果（一句话说完）
                result = json.loads(self.recognizer.Result())
                text = result.get("text", "").strip()
                return {"text": text, "is_final": True}
            else:
                # 部分结果（还在说）
                result = json.loads(self.recognizer.PartialResult())
                text = result.get("partial", "").strip()
                return {"text": text, "is_final": False}
        except Exception as e:
            logger.error(f"Vosk 识别出错: {e}")
            return {"text": "", "is_final": False}

    def reset(self):
        """重置识别器"""
        if self._is_ready and self.model:
            from vosk import KaldiRecognizer
            self.recognizer = KaldiRecognizer(self.model, 16000)
            self.recognizer.SetWords(True)

    def cleanup(self):
        """释放资源"""
        self.model = None
        self.recognizer = None
        self._is_ready = False
