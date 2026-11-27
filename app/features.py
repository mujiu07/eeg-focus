"""
专注引擎的特征提取模块
=====================
与 scripts/preprocess.py 保持完全一致的特征口径，供实时推理使用。

特征: 每通道 5 频段绝对/相对功率 + theta/beta 比值 (共 n_ch * 11 维)
频段: delta 0.5-4, theta 4-8, alpha 8-13, beta 13-30, gamma 30-45 Hz
窗口: 2 秒
"""

import numpy as np
from scipy import signal

# numpy >= 2.0 移除了 np.trapz，统一指向 np.trapezoid（旧版本回退到 np.trapz）
_trapz = getattr(np, "trapezoid", None) or np.trapz

BANDS = {
    "delta": (0.5, 4.0),
    "theta": (4.0, 8.0),
    "alpha": (8.0, 13.0),
    "beta": (13.0, 30.0),
    "gamma": (30.0, 45.0),
}

WINDOW_SEC = 2.0
LOWPASS_HZ = 45.0
HIGHPASS_HZ = 0.5

BAND_NAMES = list(BANDS.keys())
FEAT_NAMES = (
    [f"{b}_abs" for b in BAND_NAMES]
    + [f"{b}_rel" for b in BAND_NAMES]
    + ["theta_beta_ratio"]
)


def bandpass(signals, fs, low=HIGHPASS_HZ, high=LOWPASS_HZ, order=4):
    """对每个通道做带通滤波。signals: (n_ch, n_samples)。"""
    b, a = signal.butter(order, [low, high], btype="bandpass", fs=fs)
    return signal.filtfilt(b, a, signals, axis=1)


def band_power(x, fs):
    """计算一个窗口 (n_ch, n_samples) 各频段的绝对功率 (uV^2)。"""
    win = np.hanning(x.shape[1])
    xw = x * win
    freqs, psd = signal.welch(xw, fs=fs, nperseg=min(x.shape[1], 512))
    out = {}
    total = _trapz(psd, freqs, axis=1) + 1e-12
    for name, (lo, hi) in BANDS.items():
        idx = (freqs >= lo) & (freqs <= hi)
        out[name] = _trapz(psd[:, idx], freqs[idx], axis=1)
    return out, total


def window_to_feature_details(seg, fs):
    """单个窗口 -> (特征向量, 可追溯的中间结果)。

    监测面板读取这里返回的同一批 powers/relative/ratio，避免为了展示
    再执行一套滤波器或特征提取，保证展示值与模型实际输入完全一致。
    """
    powers, total = band_power(seg, fs)
    rel = {b: powers[b] / total for b in BAND_NAMES}
    abs_pow = np.concatenate([powers[b] for b in BAND_NAMES])
    rel_pow = np.concatenate([rel[b] for b in BAND_NAMES])
    ratio = powers["theta"] / (powers["beta"] + 1e-12)
    details = {
        "powers": powers,
        "total_power": total,
        "relative": rel,
        "theta_beta_ratio": ratio,
        "bands": dict(BANDS),
    }
    return np.concatenate([abs_pow, rel_pow, ratio]), details


def window_to_features(seg, fs):
    """单个窗口 (n_ch, n_samples) -> 特征向量 (n_feat,)。"""
    feats, _ = window_to_feature_details(seg, fs)
    return feats


def prepare_signal(signals, fs):
    """对整段信号做带通滤波（推理前的固定预处理）。"""
    return bandpass(signals, fs)
