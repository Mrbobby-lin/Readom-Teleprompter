"""
百度语音识别引擎（在线）
需要用户申请百度语音 API Key
"""

import json
import base64
import logging
import threading
from .engine_base import SpeechEngine

logger = logging.getLogger(__name__)


class BaiduEngine(SpeechEngine):
    """百度语音在线识别引擎"""

    # 百度语音识别 REST API
    TOKEN_URL = "https://aip.baidubce.com/oauth/2.0/token"
    ASR_URL = "https://vop.baidu.com/server_api"

    def __init__(self, api_key="", secret_key=""):
        self.api_key = api_key
        self.secret_key = secret_key
        self.access_token = None
        self.token_lock = threading.Lock()
        self._is_ready = False
        self._audio_buffer = b""
        self._max_buffer_size = 16000 * 60  # 最多缓存 60 秒音频

    @property
    def name(self):
        return "百度在线识别"

    @property
    def requires_api_key(self):
        return True

    def set_api_key(self, api_key, secret_key):
        """设置 API Key"""
        self.api_key = api_key
        self.secret_key = secret_key
        self.access_token = None

    def initialize(self):
        """初始化：获取 access token"""
        if not self.api_key or not self.secret_key:
            raise ValueError(
                "请先在设置中填写百度语音 API Key 和 Secret Key\n"
                "申请地址: https://console.bce.baidu.com/ai/#/ai/speech/overview"
            )
        self._get_access_token()
        self._is_ready = True

    def _get_access_token(self):
        """获取百度 API access token"""
        import requests
        with self.token_lock:
            params = {
                "grant_type": "client_credentials",
                "client_id": self.api_key,
                "client_secret": self.secret_key,
            }
            try:
                resp = requests.get(self.TOKEN_URL, params=params, timeout=5)
                result = resp.json()
                if "access_token" in result:
                    self.access_token = result["access_token"]
                    logger.info("百度 API token 获取成功")
                else:
                    raise RuntimeError(
                        f"获取百度 token 失败: {result.get('error_description', '未知错误')}"
                    )
            except requests.RequestException as e:
                raise RuntimeError(f"网络请求失败: {e}")

    def process_audio(self, audio_data):
        """
        处理音频数据
        百度 API 需要累积一定长度的音频（推荐 1-2 秒）再发送
        """
        if not self._is_ready:
            return {"text": "", "is_final": False}

        # 累积音频数据
        self._audio_buffer += audio_data

        # 限制缓存大小
        if len(self._audio_buffer) > self._max_buffer_size:
            self._audio_buffer = self._audio_buffer[-self._max_buffer_size:]

        # 音频达到 1.5 秒左右再发送（16000Hz * 16bit = 32000 bytes/秒）
        if len(self._audio_buffer) < 48000:  # 约 1.5 秒
            return {"text": "", "is_final": False}

        # 发送识别请求
        return self._recognize(self._audio_buffer)

    def _recognize(self, audio_data):
        """发送音频到百度 API 识别"""
        import requests

        # 准备音频数据
        audio_base64 = base64.b64encode(audio_data).decode("utf-8")

        # 构建请求
        payload = {
            "format": "pcm",
            "rate": 16000,
            "channel": 1,
            "cuid": "teleprompter_pc",
            "token": self.access_token,
            "dev_pid": 1537,  # 1537 表示普通话(中文)
            "speech": audio_base64,
            "len": len(audio_data),
        }

        headers = {"Content-Type": "application/json"}

        try:
            resp = requests.post(
                self.ASR_URL, json=payload, headers=headers, timeout=10
            )
            result = resp.json()

            if result.get("err_no") == 0:
                # 识别成功
                text = "".join(result.get("result", []))
                self._audio_buffer = b""  # 清空缓存
                return {"text": text, "is_final": True}
            elif result.get("err_no") == 3301:  # token 过期
                self._get_access_token()
                return {"text": "", "is_final": False}
            else:
                logger.warning(
                    f"百度 API 返回错误: {result.get('err_no')} - "
                    f"{result.get('err_msg')}"
                )
                return {"text": "", "is_final": False}

        except requests.RequestException as e:
            logger.error(f"百度 API 请求失败: {e}")
            return {"text": "", "is_final": False}

    def reset(self):
        """重置音频缓存"""
        self._audio_buffer = b""

    def cleanup(self):
        """释放资源"""
        self._audio_buffer = b""
        self._is_ready = False
