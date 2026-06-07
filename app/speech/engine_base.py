"""
语音识别引擎接口
所有识别引擎（Vosk、百度等）需实现此接口
"""

from abc import ABC, abstractmethod


class SpeechEngine(ABC):
    """语音识别引擎抽象基类"""

    @abstractmethod
    def initialize(self):
        """初始化引擎（加载模型、建立连接等）"""
        pass

    @abstractmethod
    def process_audio(self, audio_data):
        """
        处理音频数据，返回识别结果
        参数: audio_data - bytes 格式的音频数据
        返回: dict 格式: {"text": str, "is_final": bool}
        """
        pass

    @abstractmethod
    def reset(self):
        """重置引擎状态（开始新的一次识别）"""
        pass

    @abstractmethod
    def cleanup(self):
        """释放资源"""
        pass

    @property
    @abstractmethod
    def name(self):
        """引擎名称"""
        pass

    @property
    @abstractmethod
    def requires_api_key(self):
        """是否需要 API Key"""
        pass
