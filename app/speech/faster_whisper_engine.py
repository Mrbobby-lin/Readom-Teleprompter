"""
faster-whisper 离线语音识别引擎
使用 CTranslate2 加速的 Whisper 模型（比原版快 4-5 倍）
支持中文离线识别，CPU 上也能流畅运行
模型大小：tiny=75MB / base=150MB / small=500MB
推荐使用 tiny 模型，日常使用足够
"""

import os
import time
import struct
import threading
import numpy as np
import logging

from .engine_base import SpeechEngine

logger = logging.getLogger(__name__)


# 调试：当信号强但持续无识别结果时，转储 WAV
_DEBUG_DUMP_DIR = None
_debug_dump_counter = 0
_debug_silent_streak = 0


def _ensure_debug_dump_dir():
    """确保调试音频转储目录存在"""
    global _DEBUG_DUMP_DIR
    if _DEBUG_DUMP_DIR is None:
        _DEBUG_DUMP_DIR = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "..", "logs", "audio_debug"
        )
        _DEBUG_DUMP_DIR = os.path.abspath(_DEBUG_DUMP_DIR)
        os.makedirs(_DEBUG_DUMP_DIR, exist_ok=True)
    return _DEBUG_DUMP_DIR


def _dump_audio_wav(audio_array, prefix="debug"):
    """
    将 numpy float32 音频数组保存为 WAV 文件（用于调试）
    参数: audio_array = [-1, 1] float32, 16000Hz
    """
    global _debug_dump_counter
    dump_dir = _ensure_debug_dump_dir()
    timestamp = time.strftime("%H%M%S")
    _debug_dump_counter += 1
    filename = f"{prefix}_{timestamp}_{_debug_dump_counter}.wav"
    filepath = os.path.join(dump_dir, filename)

    # 保存为 WAV
    try:
        import wave
        # 转回 int16
        int16_data = (audio_array * 32767).astype(np.int16)
        with wave.open(filepath, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(16000)
            wf.writeframes(int16_data.tobytes())
        logger.info(f"🔊 调试音频已保存: {filepath} ({len(int16_data)/16000:.1f}s)")
        return filepath
    except Exception as e:
        logger.warning(f"保存调试音频失败: {e}")
        return None


class FasterWhisperEngine(SpeechEngine):
    """
    faster-whisper 离线语音识别引擎

    由于 Whisper 模型不是流式的，需要在内部缓冲音频到一定长度
    后再送识别。每次识别完后保留少量重叠音频，避免截断句子。
    """

    # 缓冲目标：2 秒 @ 16000Hz 16-bit mono = 32000 字节
    BUFFER_TARGET = 32000
    # 重叠保留：0.5 秒 = 8000 字节
    BUFFER_OVERLAP = 8000
    # 最大缓冲：防止异常堆积（10 秒）
    BUFFER_MAX = 160000

    def __init__(self, model_size="tiny", download_root=None):
        """
        Args:
            model_size: "tiny"(75MB) / "base"(150MB) / "small"(500MB)
            download_root: 模型缓存目录，None=使用 huggingface 默认缓存
        """
        self.model_size = model_size
        self.download_root = download_root
        self.model = None
        self._audio_buffer = bytearray()
        self._is_ready = False
        self._processing = False  # 防止并发处理和 UI 卡死
        self._lock = threading.Lock()  # 确保 _processing 线程安全

    @property
    def name(self):
        return f"离线引擎 (faster-whisper {self.model_size})"

    @property
    def requires_api_key(self):
        return False

    def initialize(self):
        """初始化 faster-whisper 模型"""
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise ImportError(
                "请安装 faster-whisper:\n"
                "  pip install faster-whisper\n\n"
                "国内用户推荐使用清华源加速:\n"
                "  pip install faster-whisper -i https://pypi.tuna.tsinghua.edu.cn/simple"
            )

        # 不强制设置 HF_ENDPOINT
        # huggingface_hub 会自动选择合适的下载源
        # 国内用户可通过环境变量手动设置镜像:
        #   set HF_ENDPOINT=https://hf-mirror.com

        logger.info(
            f"正在加载 faster-whisper 模型 [{self.model_size}]..."
        )

        # 加载模型
        # compute_type="int8" 使用 INT8 量化，CPU 上快 4-5 倍
        # 如果模型未缓存，会自动从 HuggingFace 下载（~75MB）
        self.model = WhisperModel(
            self.model_size,
            device="cpu",
            compute_type="int8",
            download_root=self.download_root,
            local_files_only=False,
        )

        self._is_ready = True
        self._audio_buffer.clear()
        logger.info(
            f"faster-whisper 模型 [{self.model_size}] 加载完成"
        )

    def process_audio(self, audio_data):
        """
        处理音频数据（缓冲到一定长度后送识别）

        Args:
            audio_data: bytes, 16000Hz 16-bit mono PCM

        Returns:
            dict: 包含识别结果的字典
                - text: 识别文字（空字符串表示还在缓冲中）
                - is_final: 当前片段是否识别完成
        """
        if not self._is_ready or not self.model:
            return {"text": "", "is_final": False}

        # 正在处理上一段音频时，只缓冲不识别（防止 UI 卡死堆积）
        with self._lock:
            if self._processing:
                self._audio_buffer.extend(audio_data)
                if len(self._audio_buffer) > self.BUFFER_MAX:
                    self._audio_buffer = self._audio_buffer[-self.BUFFER_TARGET:]
                return {"text": "", "is_final": False}

        # 追加到缓冲区
        self._audio_buffer.extend(audio_data)

        # 限制最大长度，防止无限堆积
        if len(self._audio_buffer) > self.BUFFER_MAX:
            self._audio_buffer = self._audio_buffer[-self.BUFFER_TARGET:]

        # 缓冲未满时不识别
        if len(self._audio_buffer) < self.BUFFER_TARGET:
            return {"text": "", "is_final": False}

        # 开始识别
        try:
            # 转换为 float32 numpy 数组
            # faster-whisper 需要 [-1, 1] 范围的 float32
            buffer_bytes = bytes(self._audio_buffer[:self.BUFFER_TARGET])
            audio_array = (
                np.frombuffer(buffer_bytes, dtype=np.int16)
                .astype(np.float32) / 32768.0
            )

            # 检查音频信号强度（用于调试）
            audio_max = np.max(np.abs(audio_array))
            audio_rms = np.sqrt(np.mean(audio_array ** 2))
            logger.debug(
                f"音频信号: max={audio_max:.4f}, rms={audio_rms:.4f}, "
                f"buffer_size={len(self._audio_buffer)}"
            )

            # 信号等级报告
            if audio_max < 0.001:
                logger.warning("⚠ 音频信号极弱（<0.001），请检查麦克风是否正常工作")
            elif audio_max < 0.01:
                logger.info(f"📢 音频信号较弱 ({audio_max:.4f})，请靠近麦克风或调高音量")
            elif audio_max < 0.1:
                logger.info(f"📢 音频信号正常 ({audio_max:.4f})，继续识别中...")
            else:
                logger.info(f"📢 音频信号良好 ({audio_max:.4f})")

            # 标记开始处理（防止并发）
            with self._lock:
                self._processing = True

            # 执行语音识别
            # 关闭 VAD filter，让 Whisper 直接处理所有音频
            # （DJI Mic 2 等蓝牙麦克风的音频 VAD 可能无法正确识别）
            segments, info = self.model.transcribe(
                audio_array,
                language="zh",
                task="transcribe",
                vad_filter=False,
                beam_size=5,
                best_of=5,
                condition_on_previous_text=False,
            )

            # 收集识别结果
            text_parts = []
            segment_count = 0
            for segment in segments:
                segment_count += 1
                text = segment.text.strip()
                if text:
                    text_parts.append(text)
                    logger.debug(f"  segment[{segment_count}]: {text[:50]}")
                else:
                    logger.debug(f"  segment[{segment_count}]: (空)")

            full_text = "".join(text_parts)

            # 保留尾部音频用于下个片段的重叠
            if len(self._audio_buffer) > self.BUFFER_OVERLAP:
                self._audio_buffer = self._audio_buffer[-self.BUFFER_OVERLAP:]
            else:
                self._audio_buffer.clear()

            if full_text:
                logger.info(f"✅ 识别结果: {full_text}")
                with self._lock:
                    self._processing = False
                return {"text": full_text, "is_final": True}
            else:
                # 调试：信号强但无结果 -> 转储 WAV 检查
                global _debug_silent_streak
                if audio_max > 0.05:
                    _debug_silent_streak += 1
                    if _debug_silent_streak >= 3:  # 连续 3 次信号强无结果
                        _debug_silent_streak = 0
                        _dump_audio_wav(audio_array, prefix="nostt")
                else:
                    _debug_silent_streak = 0

                logger.info(f"⏳ 处理完成，当前无有效识别（段数={segment_count}, 信号={audio_max:.4f})")
                with self._lock:
                    self._processing = False
                return {"text": "", "is_final": False}

        except Exception as e:
            logger.error(f"faster-whisper 识别出错: {e}")
            # 清空缓冲区，避免被坏数据卡死
            self._audio_buffer.clear()
            with self._lock:
                self._processing = False
            return {"text": "", "is_final": False}

    def reset(self):
        """重置引擎状态（新一段话开始前调用）"""
        self._audio_buffer.clear()

    def cleanup(self):
        """释放模型资源"""
        self.model = None
        self._audio_buffer.clear()
        self._is_ready = False
