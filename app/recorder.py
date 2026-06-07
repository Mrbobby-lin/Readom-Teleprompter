"""
麦克风录音模块
负责采集音频数据并发送给语音识别引擎
支持蓝牙麦克风（自适应采样率、设备识别）
"""

import re
import struct
import logging
import threading

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)


# 蓝牙设备名特征（用于识别）
BLUETOOTH_PATTERNS = [
    r"bluetooth", r"bth[hw]fenum", r"hands.free", r"air(?:pods?|dots?)",
    r"wh[_-]?1000", r"bt\s*audio", r"sbc\s*codec", r"免提",
    r"蓝牙", r"耳机[\w\d]*$", r"耳麦",
]

# 虚拟/合成设备特征名（没有真实麦克风输入，需要跳过）
VIRTUAL_DEVICE_PATTERNS = [
    r"声音映射器", r"sound\s*mapper",
    r"输入缓冲区", r"input\s*buffer",
    r"立体声混音", r"stereo\s*mix",
    r"wave\s*in", r"cable\s*output", r"vbdos",
    r"virtual", r"loopback", r"what\s*u\s*h(?:ear|ave)",
    r"auxiliary",
]

# 虚拟设备类型标志
DEVICE_VIRTUAL = "virtual"


def detect_device_type(name, channels, rate):
    """检测设备类型: bluetooth / usb / builtin / virtual"""
    name_lower = name.lower()
    name_clean = re.sub(r"[^\w]", "", name_lower)

    # 首先检测是否是虚拟/合成设备（没有真实麦克风输入）
    for pat in VIRTUAL_DEVICE_PATTERNS:
        if re.search(pat, name_lower):
            return DEVICE_VIRTUAL

    # 蓝牙特征检测
    for pat in BLUETOOTH_PATTERNS:
        if re.search(pat, name_lower):
            return "bluetooth"

    # USB 特征
    if any(kw in name_lower for kw in ["usb", "usb audio", "usb mic"]):
        return "usb"

    # Hands-Free 特征（蓝牙免提协议）
    if "hands-free" in name_lower or "hands free" in name_lower:
        return "bluetooth"

    # 8000Hz + 单声道 + 特定命名 → 很可能蓝牙
    if rate == 8000 and channels == 1:
        if any(kw in name_clean for kw in
               ["stereomono", "headset", "headphone"]):
            return "bluetooth"

    return "builtin"


def resample_audio(data, src_rate, dst_rate=16000):
    """
    简单线性重采样音频数据
    将 src_rate 采样率转换为 dst_rate 采样率
    """
    if src_rate == dst_rate or not data:
        return data

    if len(data) % 2 != 0:
        data = data[:-1]

    ratio = dst_rate / src_rate
    sample_count = len(data) // 2
    samples = struct.unpack(f"<{sample_count}h", data)

    dst_len = int(sample_count * ratio)
    resampled = []
    for i in range(dst_len):
        src_pos = i / ratio
        src_idx = int(src_pos)
        frac = src_pos - src_idx
        if src_idx + 1 < sample_count:
            val = int(
                samples[src_idx] * (1 - frac)
                + samples[src_idx + 1] * frac
            )
        else:
            val = samples[src_idx]
        resampled.append(max(-32768, min(32767, val)))

    return struct.pack(f"<{len(resampled)}h", *resampled)


class AudioRecorder(QThread):
    """音频采集线程 - 从麦克风读取音频数据"""

    # 信号: 音频数据就绪 (bytes)，已重采样到 16000Hz
    audio_data_ready = Signal(bytes)
    # 信号: 状态变化 (str)
    status_changed = Signal(str)
    # 信号: 错误信息 (str)
    error_occurred = Signal(str)
    # 信号: 设备信息通知 (dict)
    device_info = Signal(dict)

    # 目标采样率（引擎期望的）
    TARGET_RATE = 16000
    TARGET_CHANNELS = 1
    FORMAT_WIDTH = 2      # 16-bit 采样

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self._paused = False
        self.stream = None
        self.pyaudio_instance = None
        self.device_index = None
        self._device_rate = None   # 设备实际采样率
        self._device_channels = None
        self._device_name = ""
        self._device_type = None   # 设备类型: bluetooth/usb/builtin/virtual
        self._mutex = threading.Lock()

    def set_device(self, device_index):
        """设置麦克风设备"""
        self.device_index = device_index

    def run(self):
        """线程主循环 - 采集音频"""
        self._running = True

        try:
            import pyaudio
        except ImportError:
            self.error_occurred.emit(
                "请安装 PyAudio: pip install pyaudio"
            )
            self._running = False
            return

        try:
            self.pyaudio_instance = pyaudio.PyAudio()

            # 获取设备信息，自适应采样率
            dev_info = self._get_device_info()
            if dev_info:
                self._device_name = dev_info.get("name", "")
                self._device_rate = dev_info.get("rate", self.TARGET_RATE)
                self._device_channels = dev_info.get(
                    "channels", self.TARGET_CHANNELS
                )
                self._device_type = dev_info.get("type")
                self.device_info.emit(dev_info)

            # 对于蓝牙设备：Hands-Free 协议只支持 8000Hz/16000Hz
            # 强制用目标采样率 16000Hz 或 8000Hz，而不是设备报告的 defaultSampleRate
            # （否则蓝牙可能以 44100Hz 打开但实际信号为静音/噪声）
            if self._device_type == "bluetooth":
                target_rate = self.TARGET_RATE  # 先试 16000Hz
                # 备选 8000Hz
                backup_rates = [8000]
                logger.info(
                    f"蓝牙设备强制采样率: 先试 {target_rate}Hz, "
                    f"不行再试 {backup_rates[0]}Hz "
                    f"(原设备报告 {self._device_rate or 'N/A'}Hz)"
                )
            else:
                target_rate = self._device_rate or self.TARGET_RATE
                backup_rates = []

            target_channels = self._device_channels or self.TARGET_CHANNELS

            # 构建尝试列表
            tried_rates = [target_rate]
            if backup_rates:
                tried_rates.extend(backup_rates)
            elif target_rate == 8000:
                tried_rates.append(self.TARGET_RATE)
            elif target_rate != self.TARGET_RATE:
                tried_rates.append(self.TARGET_RATE)

            stream_opened = False
            for rate in tried_rates:
                try:
                    kwargs = {
                        "format": pyaudio.paInt16,
                        "channels": target_channels,
                        "rate": rate,
                        "input": True,
                        "frames_per_buffer": self._calc_chunk_size(rate),
                    }
                    if self.device_index is not None:
                        kwargs["input_device_index"] = self.device_index

                    self.stream = self.pyaudio_instance.open(**kwargs)
                    self._device_rate = rate
                    stream_opened = True
                    logger.info(
                        f"音频设备已打开: {self._device_name} "
                        f"(rate={rate}, channels={target_channels})"
                    )
                    break
                except Exception as e:
                    logger.warning(
                        f"尝试采样率 {rate} 失败: {e}"
                    )

            if not stream_opened:
                raise RuntimeError(f"无法打开音频设备: {self._device_name}")

            self.status_changed.emit("listening")

            # 准备重采样（如果需要）
            needs_resample = self._device_rate != self.TARGET_RATE

            chunk_size = self._calc_chunk_size(self._device_rate)

            # 持续采集
            while self._running:
                with self._mutex:
                    if self._paused:
                        self.status_changed.emit("paused")

                while self._paused and self._running:
                    self.msleep(100)

                if not self._running:
                    break

                if not self._paused:
                    self.status_changed.emit("listening")

                try:
                    data = self.stream.read(
                        chunk_size, exception_on_overflow=False
                    )
                    if data:
                        # 蓝牙设备可能输出立体声数据，混音为单声道
                        if target_channels > 1:
                            data = self._mix_to_mono(
                                data, target_channels
                            )
                        # 重采样到目标采样率
                        if needs_resample:
                            data = resample_audio(
                                data, self._device_rate, self.TARGET_RATE
                            )
                        if data:
                            self.audio_data_ready.emit(data)
                except OSError as e:
                    logger.warning(f"读取音频出错: {e}")
                    self.msleep(10)

        except Exception as e:
            logger.error(f"录音模块出错: {e}")
            self.error_occurred.emit(f"麦克风错误: {e}")
        finally:
            self._cleanup()

    def _get_device_info(self):
        """获取设备详细信息"""
        if not self.pyaudio_instance:
            return None

        try:
            # 如果是 -1（默认设备），自动选择最佳麦克风
            # 优先级：蓝牙(免提) > USB > 内置 > 虚拟(跳过)
            if self.device_index is None or self.device_index < 0:
                found = None
                found_type_rank = -1  # 虚拟=0, 内置=1, USB=2, 蓝牙=3
                type_rank = {"virtual": 0, "builtin": 1, "usb": 2, "bluetooth": 3}

                for i in range(self.pyaudio_instance.get_device_count()):
                    dev = self.pyaudio_instance.get_device_info_by_index(i)
                    if dev.get("maxInputChannels", 0) > 0:
                        name = self._fix_device_name(dev.get("name", ""))
                        channels = int(dev.get("maxInputChannels", 0))
                        rate = int(dev.get("defaultSampleRate", 0))
                        dev_type = detect_device_type(name, channels, rate)

                        # 跳过虚拟设备
                        if dev_type == DEVICE_VIRTUAL:
                            logger.info(f"跳过虚拟设备: [{i}] {name}")
                            continue

                        rank = type_rank.get(dev_type, 1)
                        if rank > found_type_rank:
                            found_type_rank = rank
                            found = dev
                            logger.info(
                                f"候选设备: [{i}] {name} ({rate}Hz, {dev_type})"
                            )

                if found is None:
                    logger.warning("未找到任何可用的物理麦克风设备，回退到默认设备")
                    # 实在没有物理设备，fallback 到第一个输入设备
                    for i in range(self.pyaudio_instance.get_device_count()):
                        dev = self.pyaudio_instance.get_device_info_by_index(i)
                        if dev.get("maxInputChannels", 0) > 0:
                            found = dev
                            break
                if found is None:
                    logger.error("未找到任何输入设备（含虚拟设备）")
                    return None
                info = found
                # 更新设备索引，让 stream 打开正确的物理设备
                self.device_index = info.get("index")
                logger.info(
                    f"自动选择物理麦克风: [{info['index']}] "
                    f"{self._fix_device_name(info.get('name', ''))}"
                )
            else:
                info = self.pyaudio_instance.get_device_info_by_index(
                    self.device_index
                )

            name = self._fix_device_name(info.get("name", ""))
            channels = int(info.get("maxInputChannels", 1))
            rate = int(info.get("defaultSampleRate", 16000))
            dev_type = detect_device_type(name, channels, rate)

            logger.info(
                f"检测到麦克风: [{info.get('index', -1)}] {name} "
                f"(ch={channels}, rate={rate}, type={dev_type})"
            )

            return {
                "index": info.get("index"),
                "name": name,
                "channels": channels,
                "rate": rate,
                "type": dev_type,
            }
        except Exception as e:
            logger.error(f"获取设备信息失败: {e}")
            return None

    def _fix_device_name(self, name):
        """修复设备名编码（处理 Windows 下蓝牙设备名乱码）"""
        if not name:
            return "未知设备"
        # 尝试解码
        try:
            name = name.encode("latin1").decode("utf-8", errors="ignore")
        except Exception:
            pass
        # 清理不可见字符
        name = re.sub(r"[\x00-\x1f]", "", name).strip()
        return name if name else "未知设备"

    def _mix_to_mono(self, data, channels):
        """将多声道音频混音为单声道"""
        if channels <= 1 or not data:
            return data
        if len(data) % (2 * channels) != 0:
            data = data[:-(len(data) % (2 * channels))]

        sample_count = len(data) // 2
        samples = struct.unpack(f"<{sample_count}h", data)
        frame_count = sample_count // channels
        mono = []
        for i in range(frame_count):
            ch_start = i * channels
            ch_values = samples[ch_start:ch_start + channels]
            avg = sum(ch_values) // channels
            mono.append(max(-32768, min(32767, avg)))
        return struct.pack(f"<{len(mono)}h", *mono)

    def _calc_chunk_size(self, rate):
        """根据采样率计算合适的块大小（约 100ms 音频）"""
        return max(160, rate // 10)

    def _cleanup(self):
        """清理资源"""
        if self.stream:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception:
                pass
            self.stream = None

        if self.pyaudio_instance:
            try:
                self.pyaudio_instance.terminate()
            except Exception:
                pass
            self.pyaudio_instance = None

        self.status_changed.emit("idle")

    def pause(self):
        """暂停录音"""
        with self._mutex:
            self._paused = True
        logger.info("录音已暂停")

    def resume(self):
        """继续录音"""
        with self._mutex:
            self._paused = False
        logger.info("录音已继续")

    def stop(self):
        """停止录音"""
        self._running = False
        self._paused = False
        logger.info("录音已停止")

    @property
    def is_paused(self):
        with self._mutex:
            return self._paused

    @property
    def is_active(self):
        return self._running

    @staticmethod
    def list_devices():
        """列出所有可用的音频输入设备（含类型识别）"""
        devices = []
        try:
            import pyaudio
            p = pyaudio.PyAudio()
            for i in range(p.get_device_count()):
                info = p.get_device_info_by_index(i)
                if info.get("maxInputChannels", 0) > 0:
                    name = info.get("name", f"设备 {i}")
                    channels = int(info.get("maxInputChannels", 0))
                    rate = int(info.get("defaultSampleRate", 0))
                    dev_type = detect_device_type(name, channels, rate)

                    # 修复设备名编码
                    try:
                        name = name.encode("latin1").decode(
                            "utf-8", errors="ignore"
                        )
                    except Exception:
                        pass
                    name = re.sub(r"[\x00-\x1f]", "", name).strip()

                    # 设备类型图标
                    type_icons = {
                        "bluetooth": "🔵",
                        "usb": "🔌",
                        "builtin": "💻",
                        "virtual": "🔄",
                    }

                    # 跳过虚拟设备（如 "Microsoft 输入缓冲区"）
                    if dev_type == DEVICE_VIRTUAL:
                        continue

                    devices.append({
                        "index": i,
                        "name": name,
                        "channels": channels,
                        "rate": rate,
                        "type": dev_type,
                        "icon": type_icons.get(dev_type, "🎤"),
                    })
            p.terminate()
        except ImportError:
            pass
        return devices
