"""
EEG 信号源抽象层
================
MVP 阶段的三种信号源:
  1. replay   : 从 EEGMAT 真实 EDF 数据按滑动窗口回放（真实脑电驱动，默认演示模式）
  2. manual   : 手动模拟专注度（滑块控制，用于演示机制/无数据环境）
   3. hardware : Xmuse 脑电波仪，通过 OSC/UDP 实时接收（见 app/xmuse_osc.py）

每个源的产出: next_window() -> (seg, meta)
  seg : (n_ch, n_samples) 2 秒窗口的原始脑电信号（未滤波）
  meta: dict(源信息, 文件, 进度, 标签等)

注意: 特征提取前统一做带通滤波，与训练口径一致。
"""

import glob
import re
import os

import numpy as np

try:  # 首选 pyedflib；Python 3.13+ 无预编译轮子时回退到纯 Python 的 edfio
    import pyedflib
except ImportError:  # pragma: no cover - 取决于运行环境
    pyedflib = None

from . import features

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
EDF_DIR = os.path.join(DATA_DIR, "eegmat")

STEP_SEC = 0.5  # 回放窗口滑动步长（模拟近实时，2s 窗口重叠 1.5s）


def read_edf(path):
    """读取 EDF 文件 -> (signals, ch_names, fs)。

    signals: (n_ch, n_samples) 物理量（uV）；ch_names: 通道名列表；fs: 采样率。
    优先使用 pyedflib；不可用时使用纯 Python 的 edfio（API 与结果口径一致）。
    """
    if pyedflib is not None:
        with pyedflib.EdfReader(path) as f:
            ch_names = list(f.getSignalLabels())
            fs = float(f.getSampleFrequency(0))
            n_samples = int(f.getFileDuration() * fs)
            signals = np.zeros((len(ch_names), n_samples))
            for i in range(len(ch_names)):
                signals[i] = f.readSignal(i)
        return signals, ch_names, fs

    import edfio
    edf = edfio.read_edf(path)
    signals = np.array([s.data for s in edf.signals], dtype=float)
    ch_names = list(edf.labels)
    fs = float(edf.signals[0].sampling_frequency)
    return signals, ch_names, fs


class EEGSource:
    """基类。"""

    name = "base"
    label = "基类"

    def __init__(self):
        self._filtered = None  # 滤波后的信号 (n_ch, n_samples)
        self.fs = None
        self.ch_names = None

    def start(self):
        raise NotImplementedError

    def next_window(self):
        """返回 (seg, meta)。seg 为未滤波原始窗口，meta 为源信息。"""
        raise NotImplementedError

    def describe(self):
        return {"name": self.name, "label": self.label}

    def stop(self):
        """释放连接/端口。默认无资源需要释放。"""
        return None


class EDFReplaySource(EEGSource):
    """从 EDF 文件回放真实脑电数据。循环播放。"""

    name = "replay"
    label = "EDF 真实数据回放"

    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path
        self._raw = None
        self._idx = 0
        self._n_windows = 0

    def _load(self):
        signals, ch_names, fs = read_edf(self.file_path)
        self.fs = fs
        self.ch_names = ch_names
        self._raw = signals
        n_samples = signals.shape[1]
        win = int(features.WINDOW_SEC * fs)
        step = int(STEP_SEC * fs)
        self._n_windows = (n_samples - win) // step + 1
        if self._n_windows < 1:
            raise ValueError("EDF 录制长度不足一个回放窗口")
        self._win = win
        self._step = step
        self._idx = 0

    def start(self):
        self._load()
        return self

    def next_window(self):
        if self._raw is None:
            self.start()
        idx = self._idx % self._n_windows
        self._idx += 1
        s = idx * self._step
        seg = self._raw[:, s:s + self._win]
        progress = idx / self._n_windows
        return seg, {
            "source": self.name,
            "file": os.path.basename(self.file_path),
            "window": idx,
            "n_windows": self._n_windows,
            "progress": progress,
        }

    def describe(self):
        d = super().describe()
        d["file"] = os.path.basename(self.file_path) if self.file_path else None
        return d


class HeartSource(EEGSource):
    """仅心率: 不接脑电，专注度完全由心率推导（放松/冥想类玩法）。

    本身不产出脑电窗口；server 的会话循环识别到该源时跳过特征提取，
    直接用心率分量作为本帧专注度。
    """

    name = "heart"
    label = "仅心率（无需脑电设备）"

    def __init__(self):
        super().__init__()
        self._n = 0

    def next_window(self):
        self._n += 1
        return None, {"source": self.name, "window": self._n, "progress": 0.0}

    def describe(self):
        return {"name": self.name, "label": self.label, "heart_only": True}


class ManualSource(EEGSource):
    """手动模拟: 用户/前端滑块直接控制专注度 (0..1)，不经过模型。"""

    name = "manual"
    label = "手动模拟（演示机制）"

    def __init__(self):
        super().__init__()
        self._focus = 0.3

    def set_focus(self, value):
        self._focus = float(np.clip(value, 0.0, 1.0))

    def next_window(self):
        # 返回一个象征性的单通道窗口，避免引擎层报错；focus 由 get_manual_focus 覆盖
        fs = 500.0
        n = int(features.WINDOW_SEC * fs)
        seg = np.zeros((1, n))
        return seg, {
            "source": self.name,
            "focus": self._focus,
            "window": 0,
            "n_windows": 0,
            "progress": 0.0,
        }


class HardwareSource(EEGSource):
    """Xmuse 脑电波仪接入：通过 OSC/UDP 接收 Xmuse Direct 推送的脑电。

    默认同时监听 UDP 7000（Xmuse Direct 默认）与 8000（官方示例默认），
    地址匹配 /eeg、/7000/eeg、/8000/eeg 等以 /eeg 结尾的路径。
    端口/采样率/通道数可通过 config 或环境变量覆盖：

      XMUSE_OSC_HOST / XMUSE_OSC_PORTS / XMUSE_OSC_FS / XMUSE_OSC_CHANNELS
    """

    name = "hardware"
    label = "Xmuse 脑电波仪（OSC/UDP）"

    def __init__(self, config=None):
        super().__init__()
        self.config = config or {}
        self._impl = None

    def start(self):
        from .xmuse_osc import XmuseOSCSource

        self._impl = XmuseOSCSource(
            host=self.config.get("osc_host") or os.getenv("XMUSE_OSC_HOST"),
            ports=self.config.get("osc_ports") or os.getenv("XMUSE_OSC_PORTS"),
            fs=self.config.get("osc_fs") or os.getenv("XMUSE_OSC_FS"),
            channels=self.config.get("osc_channels") or os.getenv("XMUSE_OSC_CHANNELS"),
        )
        self._impl.start()
        self.fs = self._impl.fs
        self.ch_names = list(self._impl.ch_names)
        return self

    def next_window(self):
        if self._impl is None:
            self.start()
        seg, meta = self._impl.next_window()
        self.fs = meta.get("fs", self.fs)
        self.ch_names = meta.get("ch_names") or self.ch_names
        return seg, meta

    def describe(self):
        d = super().describe()
        if self._impl is not None:
            d.update(self._impl.describe())
        else:
            d.update({
                "connected": False,
                "transport": "OSC/UDP",
                "ports": [],
                "osc_ports": self.config.get("osc_ports") or os.getenv("XMUSE_OSC_PORTS", "7000,8000"),
            })
        return d

    def stop(self):
        if self._impl is not None:
            self._impl.stop()


def list_edf_files():
    """列出可回放的 EDF 文件（按 Subject/段 组织）。"""
    directory = os.environ.get("EEG_FOCUS_EDF_DIR") or EDF_DIR
    files = sorted(glob.glob(os.path.join(directory, "Subject*_?.edf")))
    out = []
    for fp in files:
        base = os.path.basename(fp)
        match = re.fullmatch(r"(Subject[0-9]+)_([12])\.edf", base)
        if not match or not os.path.isfile(fp):
            continue
        subj, seg = match.groups()
        seg_name = "放松(背景)" if seg == "1" else "心算专注"
        out.append({
            "path": fp,
            "subject": subj,
            "segment": int(seg),
            "segment_name": seg_name,
            "label": f"{subj} {seg_name}",
        })
    return out


def create_source(config):
    """根据配置创建信号源。
    config: {"mode": "replay"|"manual"|"hardware", "file": 可选 EDF 路径}
    """
    mode = config.get("mode", "replay")
    if mode == "replay":
        fp = config.get("file")
        if fp and not os.path.isfile(fp):
            raise ValueError("选定的 EDF 文件已不可用，请重新选择信号源")
        if not fp:
            # 默认: 选取放松段 (Subject05_1 等), 保证演示平稳
            files = list_edf_files()
            rel = [f for f in files if f["segment"] == 1]
            if rel:
                fp = rel[0]["path"]
            elif files:
                fp = files[0]["path"]
            else:
                raise RuntimeError("未找到可回放的 EDF 数据")
        return EDFReplaySource(fp)
    if mode == "manual":
        return ManualSource()
    if mode == "heart":
        return HeartSource()
    if mode == "hardware":
        return HardwareSource(config)
    raise ValueError(f"未知信号源模式: {mode}")
