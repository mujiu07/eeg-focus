"""
EEGMAT 数据集预处理脚本
======================
PhysioNet "EEG During Mental Arithmetic Tasks" (eegmat v1.0.0)

数据说明（官方文档）:
  - 每名被试 2 个 EDF 文件:
      SubjectXX_1.edf  背景记录（任务前，放松状态） -> 标签 0
      SubjectXX_2.edf  心算任务期间记录（专注状态） -> 标签 1
  - 每段 60 秒, 已由作者做 ICA 伪迹去除
  - 电极按国际 10-20 系统放置, 23 通道 Neurocom EEG 系统

输出:
  data/processed/features.npz 包含:
    X        特征矩阵 (n_samples, n_features)
    y        标签 (0=放松, 1=专注)
    subjects 被试编号 (n_samples,)
    fs       采样率
    ch_names 使用的通道名
    feat_names 特征名
"""

import os
import glob
import numpy as np
import pyedflib
from scipy import signal

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
EDF_DIR = os.path.join(DATA_DIR, "eegmat")
OUT_DIR = os.path.join(DATA_DIR, "processed")

# 频段定义 (Hz)
BANDS = {
    "delta": (0.5, 4.0),
    "theta": (4.0, 8.0),
    "alpha": (8.0, 13.0),
    "beta": (13.0, 30.0),
    "gamma": (30.0, 45.0),
}

WINDOW_SEC = 2.0        # 切片窗口长度
FS_DEFAULT = 512        # 默认采样率（以实际文件为准）
LOWPASS_HZ = 45.0       # 低通截止（保留 EEG 主要频带）
HIGHPASS_HZ = 0.5       # 高通截止


def read_edf(path):
    """读取 EDF 文件, 返回 (signals, ch_names, fs)。signals: (n_ch, n_samples)。"""
    with pyedflib.EdfReader(path) as f:
        ch_names = f.getSignalLabels()
        n_ch = len(ch_names)
        fs = f.getSampleFrequency(0)
        signals = np.zeros((n_ch, int(f.getFileDuration() * int(fs))))
        for i in range(n_ch):
            signals[i] = f.readSignal(i)
    return signals, ch_names, fs


def bandpass(signals, fs, low=HIGHPASS_HZ, high=LOWPASS_HZ, order=4):
    """对每个通道做带通滤波。"""
    b, a = signal.butter(order, [low, high], btype="bandpass", fs=fs)
    return signal.filtfilt(b, a, signals, axis=1)


def band_power(x, fs):
    """计算一个窗口 (n_ch, n_samples) 各频段的绝对功率 (uV^2)。"""
    win = np.hanning(x.shape[1])
    xw = x * win
    freqs, psd = signal.welch(xw, fs=fs, nperseg=min(x.shape[1], 512))
    out = {}
    total = np.trapz(psd, freqs, axis=1, ) + 1e-12
    for name, (lo, hi) in BANDS.items():
        idx = (freqs >= lo) & (freqs <= hi)
        out[name] = np.trapz(psd[:, idx], freqs[idx], axis=1)
    return out, total


def extract_features(signals, fs):
    """滑窗切分 + 特征提取。返回 (features, feat_names, n_windows)。

    特征设计: 每通道 5 个频段绝对功率 + 相对功率 + theta/beta 比值。
    """
    n_ch, n_samples = signals.shape
    step = int(WINDOW_SEC * fs)
    n_windows = (n_samples - step) // step + 1

    band_names = list(BANDS.keys())
    feat_names = []
    for b in band_names:
        feat_names.append(f"{b}_abs")
    for b in band_names:
        feat_names.append(f"{b}_rel")
    feat_names.append("theta_beta_ratio")
    n_feat = n_ch * len(feat_names)

    features = np.zeros((n_windows, n_feat))
    for w in range(n_windows):
        seg = signals[:, w * step:(w + 1) * step]
        powers, total = band_power(seg, fs)
        rel = {b: powers[b] / total for b in band_names}
        abs_pow = np.concatenate([powers[b] for b in band_names])
        rel_pow = np.concatenate([rel[b] for b in band_names])
        ratio = powers["theta"] / (powers["beta"] + 1e-12)
        features[w] = np.concatenate([abs_pow, rel_pow, ratio])
    return features, feat_names, n_windows


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    files_1 = sorted(glob.glob(os.path.join(EDF_DIR, "Subject*_1.edf")))
    files_2 = sorted(glob.glob(os.path.join(EDF_DIR, "Subject*_2.edf")))
    print(f"找到 {len(files_1)} 个背景文件, {len(files_2)} 个任务文件")

    assert len(files_1) == len(files_2), "背景/任务文件数量不一致"

    all_X, all_y, all_subj = [], [], []
    fs_used, ch_names_used = None, None

    for f1, f2 in zip(files_1, files_2):
        subj_id = int(os.path.basename(f1).split("_")[0].replace("Subject", ""))
        for path, label in [(f1, 0), (f2, 1)]:
            signals, ch_names, fs = read_edf(path)
            if fs_used is None:
                fs_used = fs
                ch_names_used = ch_names
            # 带通滤波
            signals = bandpass(signals, fs)
            features, feat_names, n_win = extract_features(signals, fs)
            all_X.append(features)
            all_y.append(np.full(n_win, label))
            all_subj.append(np.full(n_win, subj_id))
            print(f"  Subject{subj_id:02d} label={label}: {n_win} 窗口 "
                  f"({WINDOW_SEC}s x {n_win} = {WINDOW_SEC*n_win}s), fs={fs}")

    X = np.vstack(all_X)
    y = np.concatenate(all_y)
    subjects = np.concatenate(all_subj)

    np.savez(
        os.path.join(OUT_DIR, "features.npz"),
        X=X, y=y, subjects=subjects,
        fs=fs_used, ch_names=np.array(ch_names_used),
        feat_names=np.array(feat_names),
    )
    print(f"\n完成: X={X.shape}, 正样本(y=1)={y.sum()}, 负样本={y.size-y.sum()}")
    print(f"通道({len(ch_names_used)}): {ch_names_used}")
    print(f"特征({len(feat_names)}/通道): {feat_names}")
    print(f"保存到: {os.path.join(OUT_DIR, 'features.npz')}")


if __name__ == "__main__":
    main()
