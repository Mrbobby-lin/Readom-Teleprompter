"""
阿里云语音识别引擎（在线）
需要用户申请阿里云智能语音交互 AppKey
申请地址: https://nls.console.aliyun.com/
免费额度：每月 20000 次调用
"""

import json
import time
import uuid
import hmac
import hashlib
import base64
import logging
from urllib.parse import quote, urlencode

import requests

from .engine_base import SpeechEngine

logger = logging.getLogger(__name__)


class AliyunEngine(SpeechEngine):
    """阿里云语音在线识别引擎（一句话识别 REST API）"""

    # 阿里云 API 地址
    GATEWAY_HOST = "nls-gateway-cn-shanghai.aliyuncs.com"
    ASR_PATH = "/stream/v1/asr"

    def __init__(self, appkey="", access_key_id="", access_key_secret=""):
        self.appkey = appkey
        self.access_key_id = access_key_id
        self.access_key_secret = access_key_secret
        self._is_ready = False
        self._audio_buffer = b""
        self._max_buffer_size = 16000 * 60  # 最多缓存 60 秒音频

    @property
    def name(self):
        return "阿里云在线识别"

    @property
    def requires_api_key(self):
        return True

    def set_api_key(self, appkey, access_key_id, access_key_secret):
        """设置 API Key"""
        self.appkey = appkey
        self.access_key_id = access_key_id
        self.access_key_secret = access_key_secret

    def initialize(self):
        """初始化：验证配置是否完整"""
        if not self.appkey:
            raise ValueError(
                "请先在设置中填写阿里云 AppKey\n"
                "申请地址: https://nls.console.aliyun.com/"
            )
        if not self.access_key_id or not self.access_key_secret:
            raise ValueError(
                "请先在设置中填写 AccessKey ID 和 AccessKey Secret\n"
                "获取地址: https://ram.console.aliyun.com/manage/ak"
            )
        self._is_ready = True
        logger.info("阿里云引擎初始化完成")

    def process_audio(self, audio_data):
        """
        处理音频数据
        阿里云一句话识别 API，累积 ~1.5 秒音频后发送
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

    def _sign(self, method, query_params):
        """
        阿里云 API 签名（Signature v1）
        https://help.aliyun.com/document_detail/31952.html
        """
        # 参数按字典序排序
        sorted_params = sorted(query_params.items(), key=lambda x: x[0])

        # 构造规范化查询字符串
        canonical_query = "&".join(
            f"{quote(k, safe='')}={quote(str(v), safe='')}"
            for k, v in sorted_params
        )

        # string_to_sign = HTTPMethod + "&" + 路径编码 + "&" + 查询字符串编码
        string_to_sign = (
            method.upper()
            + "&"
            + quote(self.ASR_PATH, safe="")
            + "&"
            + quote(canonical_query, safe="")
        )

        # HMAC-SHA1 签名
        key = (self.access_key_secret + "&").encode("utf-8")
        signature = base64.b64encode(
            hmac.new(key, string_to_sign.encode("utf-8"), hashlib.sha1).digest()
        ).decode("utf-8")

        return signature

    def _recognize(self, audio_data):
        """
        发送音频到阿里云一句话识别 REST API
        """
        # 构建公共请求参数
        params = {
            "AccessKeyId": self.access_key_id,
            "appkey": self.appkey,
            "format": "pcm",
            "sample_rate": 16000,
            "enable_punctuation_prediction": "true",
            "enable_inverse_text_normalization": "true",
            "SignatureMethod": "HMAC-SHA1",
            "SignatureNonce": str(uuid.uuid4()),
            "SignatureVersion": "1.0",
            "Timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "version": "1.0",
        }

        # 计算签名
        signature = self._sign("POST", params)
        params["Signature"] = signature

        # 构造 URL
        url = f"https://{self.GATEWAY_HOST}{self.ASR_PATH}"

        try:
            resp = requests.post(
                url,
                params=params,
                data=bytes(audio_data),
                headers={"Content-Type": "application/octet-stream"},
                timeout=10,
            )
            result = resp.json()
            status = result.get("status", -1)

            if status == 20000000:
                # 识别成功
                text = result.get("result", "").strip()
                self._audio_buffer = b""  # 清空缓存
                if text:
                    logger.info(f"✅ 阿里云识别结果: {text}")
                    return {"text": text, "is_final": True}
                return {"text": "", "is_final": False}
            else:
                logger.warning(
                    f"阿里云 API 返回错误: status={status}, message={result.get('message', '')}"
                )
                return {"text": "", "is_final": False}

        except requests.RequestException as e:
            logger.error(f"阿里云 API 请求失败: {e}")
            return {"text": "", "is_final": False}
        except json.JSONDecodeError as e:
            logger.error(f"阿里云 API 返回格式错误: {e}")
            return {"text": "", "is_final": False}
        except Exception as e:
            logger.error(f"阿里云识别异常: {e}")
            return {"text": "", "is_final": False}

    def reset(self):
        """重置音频缓存"""
        self._audio_buffer = b""

    def cleanup(self):
        """释放资源"""
        self._audio_buffer = b""
        self._is_ready = False
