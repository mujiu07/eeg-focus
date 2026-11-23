"""
EEG 去噪 / 去伪迹
=================
面向 **Xmuse 头戴式脑电波仪** 的实时信号净化，服务于校准与游戏两条链路。

设备约束（决定每一个阈值取值的依据）
------------------------------------
* 通道：4 路（TP9 / AF7 / AF8 / TP10），可扩展到 6 路（+AUX1 / AUX2）
* 采样率：256 Hz（Nyquist 128 Hz）
* 电极：前额 + 耳后 **干电极**，无导电膏，接触阻抗高、易受眼动/肌电污染
* 幅值：设计上按 µV 解释；但不同版本 OSC 固件可能直接推 ADC 计数，
  因此本模块带 **单位自适应**：检测到非 µV 量级时改用稳健统计阈值
* 信噪特点：AF7/AF8 紧邻眼睛 → 眨眼是最大干扰源（幅值常为 β 波的 10 倍以上）；
  TP9/TP10 在耳后 → 对眨眼不敏感，但对下颌肌电和电极松动敏感

处理流程（每个 2 s 窗口，0.5 s 步长）
-------------------------------------
  0. 输入体检      形状/NaN/恒定段/单位判定
  1. 通道清理      去线性趋势 → 50 Hz 陷波（零相位）
  2. 伪迹检测      眨眼 / 削顶饱和 / 肌电 / 坏道 / 设备 is_good
  3. 伪迹修复      眨眼用 1–8 Hz 分量回归减除；削顶段线性插值；坏道剔除
  4. 质量评分      0–1 分 + flags + 中文提示；决定这一帧能不能出分
  5. 输出          清洗后信号（**仍保持未带通状态**）+ 结构化报告

重要约定
--------
``clean_window`` **不改变特征口径**：它只做去趋势、陷波和伪迹修复，
0.5–45 Hz 带通仍由 ``features.prepare_signal`` 完成，因此
模型与 ``scripts/preprocess.py`` 的训练口径完全一致。
"""

from __future__ import annotations

import os

import numpy as np
from scipy import signal

from . import features

# ---------------------------------------------------------------------------
# 参数（都可用环境变量覆盖，方便真机现场调）
# ---------------------------------------------------------------------------
# 削顶 / 饱和：Xmuse 干电极正常脑电峰峰值多在 ±150 µV 内，超过即高度可疑
RAIL_UV = float(os.getenv("EEG_RAIL_UV", "180"))
SAT_UV = float(os.getenv("EEG_SAT_UV", "260"))
# 眨眼：AF7/AF8 上一个典型眨眼在 80–300 µV，80 µV 能覆盖小眨眼
BLINK_UV = float(os.getenv("EEG_BLINK_UV", "80"))
# 眨眼修复：只减 0.5–8 Hz 分量，迭代 2 次
# （实测 0.5–15 Hz 会把 alpha 一起削掉 ~20%，不可接受；
#   而 2 次迭代在不影响 alpha/beta 的前提下能把残留再压低约 20%）
BLINK_REPAIR_BAND = (0.5, 8.0)
BLINK_REPAIR_ITERS = int(os.getenv("EEG_BLINK_REPAIR_ITERS", "2"))
# 总开关：验收/对照用。off 时 HardwareSource 完全跳过去噪（默认 on）
ENABLED = os.getenv("EEG_DENOISE", "1").strip().lower() not in ("0", "off", "false", "no")

# 眨眼事件时长范围（秒）：短于此是尖刺，长于此更像慢漂移
BLINK_MIN_SEC = 0.04
BLINK_MAX_SEC = 0.70
# 一窗内眨眼太多就不再修复，直接判不可信（修复会吃掉过多脑电）
BLINK_MAX_COUNT = 3
BLINK_MAX_RATIO = 0.60
# 肌电：35–45 Hz（γ 尾段）能量占比 + 该频段 RMS 双条件，避免把正常 γ 当肌电
EMG_BAND = (35.0, 45.0)
EMG_RATIO_MAX = float(os.getenv("EEG_EMG_RATIO", "0.45"))
EMG_RMS_UV = float(os.getenv("EEG_EMG_RMS_UV", "15"))
# 坏道：稳健标准差过低=电极脱落/短接，过高=接触不良
BAD_STD_MIN_UV = 0.5
BAD_STD_MAX_UV = float(os.getenv("EEG_BAD_STD_MAX_UV", "150"))
# 设备自带 is_good（0–1），低于该值只降级不直接判死
DEVICE_Q_MIN = float(os.getenv("EEG_DEVICE_Q_MIN", "0.5"))
# 工频：中国 50 Hz；填 "off" 关闭，填 60 适配北美
NOTCH_HZ = os.getenv("EEG_NOTCH_HZ", "50").strip().lower()
NOTCH_Q = float(os.getenv("EEG_NOTCH_Q", "30"))
# 跨窗检测：把上一窗尾部拼进来，避免眨眼正好跨在窗口边界时漏检
PAD_SEC = 0.5
# 一阶差分削顶判据（µV/sample）：防止 AB 型饱和（幅值没到轨但斜率炸了）
DIFF_UV = float(os.getenv("EEG_DIFF_UV", "60"))

# --- 运动伪迹（头动 / 线缆晃动 / 电极相对位移）---
# 台阶：相邻 0.25 s 段中位数的跳变，对应电极极化突变
MOTION_STEP_UV = float(os.getenv("EEG_MOTION_STEP_UV", "60"))
MOTION_STEP_MILD_UV = float(os.getenv("EEG_MOTION_STEP_MILD_UV", "25"))
# 慢摆：0.5–3 Hz 的「持续高幅」占比。与 theta 重叠，只能检测不能修。
# 用持续性而不是能量占比：眨眼在 0.5–3 Hz 也有能量，但只持续 0.2–0.5 s，
# 而运动摆动会占满整窗。占比阈值用于报告，持续性阈值用于判定。
MOTION_SWING_RMS_UV = float(os.getenv("EEG_MOTION_SWING_RMS_UV", "45"))
MOTION_SWING_FRAC = float(os.getenv("EEG_MOTION_SWING_FRAC", "0.5"))
MOTION_SWING_RATIO = float(os.getenv("EEG_MOTION_SWING_RATIO", "0.55"))
# 共模：全通道同向偏移（整体头动），可减除
MOTION_COMMON_UV = float(os.getenv("EEG_MOTION_COMMON_UV", "55"))
# 台阶修复的基线限幅：超过这个幅度就不再尝试"修"，而是判不可用
MOTION_REPAIR_MAX_UV = float(os.getenv("EEG_MOTION_REPAIR_MAX_UV", "120"))

# 前额通道名关键字：眨眼检测优先用这些通道
FRONTAL_KEYS = ("af7", "af8", "fp1", "fp2", "f7", "f8", "afp")

LEVEL_GOOD, LEVEL_FAIR, LEVEL_POOR = "good", "fair", "poor"

# 中文提示：前端直接展示，避免在 JS 里再写一套判断
_HINTS = {
    "good": "信号良好",
    "fair": "信号一般，仍可继续",
    "poor": "信号质量差，请稍作调整",
    "blink": "检测到眨眼，已自动修复",
    "blink_severe": "眨眼过多，请尽量放松面部、少眨眼",
    "rail": "信号含饱和跳变，已插值修复",
    "emg": "肌肉紧张干扰，请放松下颌",
    "bad_channel": "电极接触不良，请调整头带位置",
    "flatline": "未见脑电波动，请检查电极是否贴合头皮",
    "low_device_quality": "设备报告接触质量偏低，请压紧头带",
    "motion": "检测到头部或身体运动，本帧不出分",
    "motion_fixed": "检测到轻微运动漂移，已修正基线",
    "nan": "信号出现空值，已丢弃该帧",
}


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
def _robust_std(x):
    """MAD 推导的稳健标准差，对眨眼/尖刺不敏感（σ≈1.4826·MAD）。"""
    if x.size == 0:
        return 0.0
    med = float(np.median(x))
    mad = float(np.median(np.abs(x - med)))
    return 1.4826 * mad


def _notch_freqs():
    """解析陷波频率；非法值/关闭时返回空列表。"""
    if NOTCH_HZ in ("off", "0", "none", ""):
        return []
    out = []
    for item in NOTCH_HZ.replace(";", ",").split(","):
        try:
            hz = float(item.strip())
        except ValueError:
            continue
        if hz > 0:
            out.append(hz)
    return out


def _apply_notch(x, fs):
    """零相位 IIR 陷波。x: (n_ch, n_samples)。fs 太小时自动跳过。"""
    freqs = _notch_freqs()
    if not freqs or x.shape[1] < 32:
        return x
    nyq = fs / 2.0
    y = x
    for hz in freqs:
        # 陷波中心必须离 Nyquist 足够远，否则数字滤波器退化
        if hz >= nyq * 0.85:
            continue
        try:
            b, a = signal.iirnotch(hz, NOTCH_Q, fs=fs)
            y = signal.filtfilt(b, a, y, axis=1)
        except (ValueError, np.linalg.LinAlgError):  # pragma: no cover - 数值兜底
            continue
    return y


def _band(x, fs, lo, hi, order=4):
    """零相位带通，仅供检测/修复使用（不影响最终特征口径）。

    同时接受 1D (n,) 与 2D (n_ch, n_samples)，返回形状与输入一致。
    """
    arr = np.asarray(x, dtype=float)
    one_d = arr.ndim == 1
    if one_d:
        arr = arr[None, :]
    nyq = fs / 2.0
    hi = min(float(hi), nyq * 0.95)
    if hi <= lo or arr.shape[1] < 32:
        out = np.zeros_like(arr)
        return out[0] if one_d else out
    b, a = signal.butter(order, [lo, hi], btype="bandpass", fs=fs)
    out = signal.filtfilt(b, a, arr, axis=1)
    return out[0] if one_d else out


def _thresholds(seg):
    """按信号量级决定阈值。

    Xmuse 正常推 µV；若某些固件直接推 ADC 计数，绝对 µV 阈值会全部误判。
    这里用稳健标准差做兜底，保证「换单位不换行为」。
    """
    finite = seg[np.isfinite(seg)]
    if finite.size == 0:
        return {"rail": RAIL_UV, "sat": SAT_UV, "blink": BLINK_UV,
                "emg_rms": EMG_RMS_UV, "bad_std_max": BAD_STD_MAX_UV,
                "diff": DIFF_UV, "motion_step": MOTION_STEP_UV,
                "motion_step_mild": MOTION_STEP_MILD_UV,
                "motion_common": MOTION_COMMON_UV,
                "motion_swing_rms": MOTION_SWING_RMS_UV,
                "unit": "unknown", "median_abs": 0.0}
    med_abs = float(np.median(np.abs(finite)))
    # 正常 EEG 的 |x| 中位数极少超过 500 µV（即使含眨眼）；
    # 超过说明固件推的是 ADC 计数而非 µV，此时绝对 µV 阈值全部失效。
    if med_abs <= 500.0:
        return {"rail": RAIL_UV, "sat": SAT_UV, "blink": BLINK_UV,
                "emg_rms": EMG_RMS_UV, "bad_std_max": BAD_STD_MAX_UV,
                "diff": DIFF_UV, "motion_step": MOTION_STEP_UV,
                "motion_step_mild": MOTION_STEP_MILD_UV,
                "motion_common": MOTION_COMMON_UV,
                "motion_swing_rms": MOTION_SWING_RMS_UV,
                "unit": "uV", "median_abs": med_abs}
    # 明显不是 µV 量级：所有绝对阈值按稳健统计倍数重算，不做单位假设
    sigma = _robust_std(finite)
    sigma = sigma if sigma > 0 else max(med_abs, 1.0)
    return {"rail": 8.0 * sigma, "sat": 12.0 * sigma, "blink": 5.0 * sigma,
            "emg_rms": 1.5 * sigma, "bad_std_max": 12.0 * sigma,
            "diff": 1.2 * sigma, "motion_step": 3.0 * sigma,
            "motion_step_mild": 1.5 * sigma, "motion_common": 2.5 * sigma,
            "motion_swing_rms": 5.5 * sigma,
            "unit": "auto", "median_abs": med_abs}


def _pick_frontal(ch_names, n_ch):
    """挑出眨眼检测通道。

    优先按通道名（AF7/AF8/FP1/FP2…）；没有名字时按 Xmuse 默认顺序
    [TP9, AF7, AF8, TP10] 取 index 1/2。都没有就退回全部通道。
    """
    idx = []
    if ch_names:
        for i, name in enumerate(ch_names):
            low = str(name).lower()
            if any(k in low for k in FRONTAL_KEYS):
                idx.append(i)
    if not idx and n_ch >= 3:
        idx = [1, 2]  # Xmuse 4/6 通道默认布局
    if not idx:
        idx = list(range(n_ch))
    return [i for i in idx if 0 <= i < n_ch]


# ---------------------------------------------------------------------------
# 眨眼检测与修复
# ---------------------------------------------------------------------------
def detect_blinks(raw_front, x_bp, fs, thr):
    """在前额通道上找眨眼事件。

    raw_front : (n_front, n_samples) 原始幅值（用于阈值确认，单位 µV 语义）
    x_bp      : (n_front, n_samples) 1–8 Hz 带通信号（用于定位事件边界）
    thr       : 原始幅值阈值（µV）

    为什么要两路信号：带通会削掉眨眼约一半幅值，若直接拿带通峰值对 µV 阈值，
    80 µV 的小眨眼会被漏检；而只用原始信号又分不清眨眼与慢漂移。
    因此边界用带通定（形状干净），幅值用原始信号确认（量纲准确）。

    返回 [(start, end), ...]（样本下标，含端点）。
    """
    if x_bp.size == 0 or raw_front.size == 0:
        return []
    n = x_bp.shape[1]
    min_len = max(2, int(BLINK_MIN_SEC * fs))
    max_len = max(min_len, int(BLINK_MAX_SEC * fs))
    # 带通幅值约为原始幅值的一半，边界阈值取 0.45 倍即可覆盖小眨眼
    edge_thr = thr * 0.45

    events = []
    for ch in range(x_bp.shape[0]):
        amp = np.abs(x_bp[ch])
        mask = amp > edge_thr
        if not mask.any():
            continue
        edges = np.diff(np.concatenate(([0], mask.astype(np.int8), [0])))
        starts = np.flatnonzero(edges == 1)
        ends = np.flatnonzero(edges == -1) - 1
        raw_amp = np.abs(raw_front[ch]) if ch < raw_front.shape[0] else amp
        for s, e in zip(starts, ends):
            length = e - s + 1
            if length < min_len or length > max_len:
                continue
            # 原始幅值必须真的越过阈值，否则只是缓慢起伏
            if float(raw_amp[s:e + 1].max()) < thr:
                continue
            events.append((int(s), int(e)))

    if not events:
        return []
    # 合并重叠/相邻事件（两个通道检到同一个眨眼）
    events.sort()
    merged = [list(events[0])]
    for s, e in events[1:]:
        if s <= merged[-1][1] + int(0.05 * fs):
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    # 合并后仍过长的（多个眨眼连成一片）按最大时长截断处理
    out = []
    for s, e in merged:
        while e - s + 1 > max_len:
            out.append((s, s + max_len - 1))
            s += max_len
        out.append((s, min(e, n - 1)))
    return [(s, e) for s, e in out if e > s]


def repair_blinks(raw, events, fs, channels=None):
    """把眨眼成分从原始信号里减掉（迭代带通减除）。

    眨眼能量集中在 0.5–8 Hz；对该频段分量按汉宁窗在事件段内渐进减去，
    既能压掉大幅瞬态，又不会在段首尾留下阶跃。迭代 2 次可以把
    「带通只能取到部分眨眼能量」造成的残留再压低一档。

    实测取舍（256 Hz / 2 s 窗口 / 合成眨眼）：
      * 0.5–8 Hz ×2  → 幅值降约 55%，alpha/beta 功率不变（推荐）
      * 0.5–15 Hz    → 幅值降更多，但 alpha 被连带削掉 ~20%（不采用）

    channels 为参与减除的通道下标（默认全部）。TP9/TP10 上几乎没有眨眼，
    硬减反而会挖出凹陷，所以只减前额通道。
    返回 (修复后信号, 修复的事件数)。
    """
    if not events or raw.size == 0:
        return raw, 0
    ch_idx = list(range(raw.shape[0])) if channels is None else list(channels)
    ch_idx = [i for i in ch_idx if 0 <= i < raw.shape[0]]
    if not ch_idx:
        return raw, 0

    out = raw.copy()
    pad = max(2, int(0.10 * fs))
    n = out.shape[1]
    lo, hi = BLINK_REPAIR_BAND

    for _ in range(max(1, BLINK_REPAIR_ITERS)):
        # 每轮都在「当前残差」上重新取带通，相当于对减除结果再做一次校正
        cur = _band(out[ch_idx], fs, lo, hi, order=4)
        for s, e in events:
            a = max(0, s - pad)
            b = min(n - 1, e + pad)
            if b - a + 1 < 3:
                continue
            # 汉宁窗：段中权重 1、两端 0，保证与周围信号平滑衔接
            w = np.hanning(b - a + 3)[1:-1]
            out[ch_idx, a:b + 1] = out[ch_idx, a:b + 1] - cur[:, a:b + 1] * w[None, :]
    return out, len(events)


# ---------------------------------------------------------------------------
# 削顶 / 饱和修复
# ---------------------------------------------------------------------------
def _rail_mask(x, thr, diff_thr=None):
    """幅值过阈 + 一阶差分过阈（AB 型饱和：幅值没到轨但斜率断崖）。"""
    mask = np.abs(x) >= thr
    if x.size > 1:
        d = DIFF_UV if diff_thr is None else diff_thr
        mask |= np.abs(np.diff(x, prepend=x[:1])) >= d
    return mask


def _interp_rail(x, mask, fs):
    """对饱和段做线性插值。返回 (新信号, 是否修复成功)。

    单段超过 0.3 s 认为不是瞬时饱和（电极抖动/脱落），插值会伪造脑电，
    此时放弃修复，交给上层判坏道。
    """
    if not mask.any():
        return x, True
    max_len = max(4, int(0.30 * fs))
    n = x.size
    idx = np.arange(n)
    edges = np.diff(np.concatenate(([0], mask.astype(np.int8), [0])))
    starts = np.flatnonzero(edges == 1)
    ends = np.flatnonzero(edges == -1) - 1
    good = ~mask
    if good.sum() < 8:
        return x, False
    out = x.copy()
    for s, e in zip(starts, ends):
        if e - s + 1 > max_len:
            return x, False
        # 只插值被标掉的样本，两侧好样本保留原值作为锚点
        out[s:e + 1] = np.interp(idx[s:e + 1], idx[good], x[good])
    return out, True


# ---------------------------------------------------------------------------
# 肌电检测
# ---------------------------------------------------------------------------
def _emg_metrics(x, fs):
    """返回 (高频 RMS, 高频能量占比)。x: 单通道。"""
    if x.size < 64:
        return 0.0, 0.0
    hi_lo, hi_hi = EMG_BAND
    hi = _band(x[None, :], fs, hi_lo, hi_hi, order=4)[0]
    full = _band(x[None, :], fs, 1.0, min(45.0, fs / 2 * 0.95), order=4)[0]
    rms_hi = float(np.sqrt(np.mean(hi ** 2)))
    rms_full = float(np.sqrt(np.mean(full ** 2)))
    ratio = rms_hi / (rms_full + 1e-12)
    return rms_hi, ratio


# ---------------------------------------------------------------------------
# 运动伪迹：检测 + 有限修复
# ---------------------------------------------------------------------------
def _step_metric(x, ch_ok, fs):
    """窗口首尾 0.25 s 的中位数差，即「持续偏移」。

    必须是首尾差而不是相邻段差：眨眼是脉冲（上去再回零），首尾都干净；
    电极位移后基线整体平移，首尾差就是真实台阶幅度。
    """
    n_ch, n = x.shape
    idx = [i for i in range(n_ch) if ch_ok[i]] or list(range(n_ch))
    edge = max(4, int(0.25 * fs))
    if n <= 2 * edge:
        return 0.0
    step = 0.0
    for i in idx:
        head = x[i, :edge]
        tail = x[i, -edge:]
        delta = abs(float(np.median(tail)) - float(np.median(head)))
        if delta <= 0.0:
            continue
        # 段内离散度接近或超过台阶幅度，说明这一段是脉冲/摆动而不是
        # 平稳的基线平移（典型反例：眨眼正好压在窗口边缘）。
        # 这种通道的台阶判据不可信，跳过，交给眨眼/慢摆/削顶去判。
        if _robust_std(head) > 0.45 * delta or _robust_std(tail) > 0.45 * delta:
            continue
        step = max(step, delta)
    return step


def _swing_metric(x, ch_ok, fs, thr):
    """0.5–3 Hz 的慢摆指标，返回 (能量占比, 持续高幅占比)。

    用「持续性」而不是纯能量：眨眼在 0.5–3 Hz 也有能量，但只持续 0.2–0.5 s，
    而运动摆动会占满整窗。判定用占比，能量比只写进报告。
    """
    n_ch, n = x.shape
    idx = [i for i in range(n_ch) if ch_ok[i]] or list(range(n_ch))
    lo = _band(x[idx], fs, 0.5, 3.0, order=4)
    full = _band(x[idx], fs, 0.5, min(45.0, fs / 2 * 0.95), order=4)
    # 0.6 s 滑动窗：比 0.25 s 稳定，0.5–3 Hz 的摆动几乎整窗都在阈值以上；
    # 眨眼的能量只集中在 0.2–0.5 s，占比自然低，两者能区分开。
    w = max(3, int(0.6 * fs))
    ratio, frac = 0.0, 0.0
    for j in range(lo.shape[0]):
        p_lo = float(np.mean(lo[j] ** 2))
        p_full = float(np.mean(full[j] ** 2)) + 1e-12
        if p_full > 1e-6:
            ratio = max(ratio, p_lo / p_full)
        rms = np.sqrt(np.convolve(lo[j] ** 2, np.ones(w) / w, mode="same"))
        frac = max(frac, float(np.mean(rms > thr["motion_swing_rms"])))
    return ratio, frac


def _remove_step_baseline(x, ch_ok, fs, thr):
    """减掉由分段中位数构造的低频基线，消除 DC 台阶和慢漂移。

    基线由 0.25 s 段中位数线性插值而来，主要能量在 2 Hz 以下；
    只在检测到台阶时逐通道应用，不改动 0.5–45 Hz 特征带的主体。
    """
    n_ch, n = x.shape
    edge = max(4, int(0.25 * fs))
    if n <= 2 * edge:
        return x, []
    out = x.copy()
    repaired = False
    win = max(8, int(0.1 * fs))
    k = n // win
    ramp = max(1.0, 0.05 * fs)   # 0.05 s 过渡：把阶跃换成平滑跃变，避免新的高频冲击
    for i in range(n_ch):
        if not ch_ok[i]:
            continue
        hs = x[i, :edge]
        ts = x[i, -edge:]
        delta = float(np.median(ts)) - float(np.median(hs))
        if abs(delta) <= thr["motion_step_mild"]:
            continue
        if _robust_std(hs) > 0.45 * abs(delta) or _robust_std(ts) > 0.45 * abs(delta):
            continue
        # 定位跳变点：0.1 s 段中位数变化最大的地方
        if k >= 2:
            med = np.array([np.median(x[i, j * win:(j + 1) * win]) for j in range(k)])
            at = (int(np.argmax(np.abs(np.diff(med)))) + 1) * win
        else:
            at = n // 2
        # 用 sigmoid 构造跃变基线：左侧减 0、右侧减 delta
        w = 1.0 / (1.0 + np.exp(-(np.arange(n) - at) / ramp))
        base = np.clip(delta * w, -MOTION_REPAIR_MAX_UV, MOTION_REPAIR_MAX_UV)
        out[i] = x[i] - base
        repaired = True
    return out, (["step"] if repaired else [])


def _remove_common(x, ch_ok, thr):
    """减掉通道共模分量（整体头动 / 参考电极位移）。

    只有共模显著大于通道间残差时才动手，避免误伤真实的同步脑电；
    保留 20% 是保守选择。返回 (信号, common_rms)；未触发时 common_rms 为 0。
    """
    idx = [i for i in range(x.shape[0]) if ch_ok[i]]
    if len(idx) < 2:
        return x, 0.0
    cm = np.median(x[idx], axis=0)
    c_rms = float(np.sqrt(np.mean(cm ** 2)))
    resid = float(np.median([np.sqrt(np.mean((x[i] - cm) ** 2)) for i in idx]))
    if c_rms <= thr["motion_common"] or c_rms <= resid * 1.2:
        return x, 0.0
    out = x.copy()
    out[idx] = x[idx] - 0.8 * cm
    return out, c_rms


# ---------------------------------------------------------------------------
# 主入口：有状态清洗器
# ---------------------------------------------------------------------------
class ArtifactCleaner:
    """有状态的窗口清洗器：一个会话一个实例。

    保存上一窗的原始尾部，用于跨窗眨眼检测（眨眼横跨 2 s 窗口边界时，
    单窗检测会各看到半个、峰值不过阈值而漏检）。
    """

    def __init__(self, fs=256.0, window_sec=features.WINDOW_SEC):
        self.fs = float(fs) if fs and fs > 0 else 256.0
        self.window_sec = float(window_sec)
        self._pad = max(1, int(PAD_SEC * self.fs))
        self._prev_tail = None
        self.reset()

    def reset(self):
        self._prev_tail = None
        # 会话级累计统计（报告用）
        self.stats = {
            "frames": 0, "usable": 0, "blink_events": 0,
            "blink_frames": 0, "rail_frames": 0, "emg_frames": 0,
            "bad_channel_frames": 0, "motion_frames": 0,
        }

    # -- 内部 ------------------------------------------------------------
    def _extend(self, seg):
        """把上一窗尾部拼到当前窗前面，返回 (拼接信号, 当前窗起始下标)。"""
        if self._prev_tail is None or self._prev_tail.shape[0] != seg.shape[0]:
            return seg, 0
        tail = self._prev_tail[:, -self._pad:]
        if tail.shape[1] == 0:
            return seg, 0
        return np.concatenate([tail, seg], axis=1), tail.shape[1]

    def _remember(self, tail):
        """保存本窗尾部（修复前、已去趋势+陷波），供下一窗跨窗眨眼检测。"""
        self._prev_tail = tail.copy()

    # -- 主流程 ----------------------------------------------------------
    def process(self, seg, ch_names=None, device_quality=None):
        """清洗一个窗口。

        seg: (n_ch, n_samples) 原始窗口
        返回 (clean_seg, report)；report 可直接放进 SSE 帧给前端。
        """
        arr = np.asarray(seg, dtype=float)
        if arr.ndim != 2 or arr.shape[0] == 0 or arr.shape[1] == 0:
            return arr, self._report(False, LEVEL_POOR, 0.0, ["nan"],
                                     hint=_HINTS["nan"], n_ch=0)

        n_ch, n_samples = arr.shape
        fs = self.fs
        self.stats["frames"] += 1

        # --- 0. 输入体检 ---------------------------------------------
        flags = []
        usable = True
        if not np.isfinite(arr).all():
            flags.append("nan")
            arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
            usable = False

        if n_samples < 32:
            flags.append("nan")
            return arr, self._report(False, LEVEL_POOR, 0.0, flags,
                                     hint="窗口过短，无法分析", n_ch=n_ch)

        thr = _thresholds(arr)
        work = arr.copy()

        # --- 0.5 粗运动：共模 + 台阶（必须在 detrend 之前）-----------
        # 线性去趋势会把一个阶跃变成一条大斜率：首尾差被抵消，台阶反而
        # 被"藏"进低频，之后再想修就分不清它和真实慢波了。
        # 所以这两步要放在最前面，用原始信号的段中位数判定。
        stds0 = np.array([_robust_std(work[i]) for i in range(n_ch)])
        ch_ok0 = (stds0 >= BAD_STD_MIN_UV) & (stds0 <= thr["bad_std_max"])
        # 先减共模：整体头动会让所有通道同时抬高，若先判台阶会误判成"不可修"
        work, common_rms = _remove_common(work, ch_ok0, thr)
        motion_repaired = ["common"] if common_rms > 0 else []
        motion_severe = False
        step_uv = _step_metric(work, ch_ok0, fs)
        if step_uv > thr["motion_step"]:
            motion_severe = True          # 太大，不接受"修"，直接拒绝出分
        elif step_uv > thr["motion_step_mild"]:
            work, rep_list = _remove_step_baseline(work, ch_ok0, fs, thr)
            motion_repaired += rep_list

        # --- 1. 通道清理：去线性趋势 + 陷波 ---------------------------
        # detrend 先做：2 s 内的慢漂移会让后面的 filtfilt 在两端摆出假低频
        work = signal.detrend(work, axis=1, type="linear")
        work = _apply_notch(work, fs)

        # --- 2. 伪迹检测 ---------------------------------------------
        # 2.1 恒定段 / 坏道
        stds = np.array([_robust_std(work[i]) for i in range(n_ch)])
        flat = stds < BAD_STD_MIN_UV
        noisy = stds > thr["bad_std_max"]
        bad = flat | noisy
        ch_ok = ~bad

        if flat.any():
            flags.append("flatline")
        if bad.any():
            flags.append("bad_channel")
            self.stats["bad_channel_frames"] += 1

        # 2.2 削顶 / 饱和（只统计，修复在下面）
        rails = [_rail_mask(work[i], thr["rail"], thr["diff"]).any() for i in range(n_ch)]
        if any(rails):
            flags.append("rail")
            self.stats["rail_frames"] += 1

        # 2.3 眨眼（跨窗检测）
        frontal = _pick_frontal(ch_names, n_ch)
        ext, offset = self._extend(work)
        # 下一窗的历史段取「修复前」的同阶段信号，保持跨窗拼接的量纲一致
        tail_next = work[:, -self._pad:].copy()
        n_ext = ext.shape[1]
        ext_bp = _band(ext[frontal], fs, 1.0, 8.0, order=4)
        events = detect_blinks(ext[frontal], ext_bp, fs, thr["blink"])
        # 只保留与当前窗有交集的眨眼事件
        cur = [(s, e) for s, e in events if e >= offset and s <= n_ext - 1]
        cur = [(max(0, s - offset), min(n_samples - 1, e - offset)) for s, e in cur]
        cur = [(s, e) for s, e in cur if e > s]
        blink_ratio = sum(e - s + 1 for s, e in cur) / float(n_samples)
        if cur:
            self.stats["blink_events"] += len(cur)
            self.stats["blink_frames"] += 1

        # 2.4 肌电（在前额通道判，TP9/TP10 也有下颌串扰，取全部通道的最大值）
        emg_rms, emg_ratio = 0.0, 0.0
        for i in range(n_ch):
            if bad[i]:
                continue
            r, ratio = _emg_metrics(work[i], fs)
            emg_rms = max(emg_rms, r)
            emg_ratio = max(emg_ratio, ratio)
        emg_hit = emg_ratio > EMG_RATIO_MAX and emg_rms > thr["emg_rms"]
        if emg_hit:
            flags.append("emg")
            self.stats["emg_frames"] += 1

        # 2.5 设备自带质量（可选）
        device_q = None
        if device_quality is not None:
            try:
                device_q = float(device_quality)
            except (TypeError, ValueError):
                device_q = None
        if device_q is not None and device_q < DEVICE_Q_MIN:
            flags.append("low_device_quality")

        # --- 3. 修复 -------------------------------------------------
        # 3.1 眨眼：太多就不修（修完也不可信，且会削掉脑电）
        fixed_blinks = 0
        severe_blink = False
        if cur:
            if len(cur) > BLINK_MAX_COUNT or blink_ratio > BLINK_MAX_RATIO:
                severe_blink = True
                flags.append("blink_severe")
            else:
                # 在拼接信号上做修复，再截回当前窗：跨窗眨眼（一半落在上一窗）
                # 也能被完整扣除，不会只减掉半个波形
                ext_events = [(s + offset, e + offset) for s, e in cur]
                repaired_ext, fixed_blinks = repair_blinks(
                    ext, ext_events, fs, channels=frontal)
                work = repaired_ext[:, offset:offset + n_samples].copy()
                flags.append("blink")

        # --- 3.15 运动慢摆（在眨眼修复后测，避免眨眼能量干扰）-------
        # 0.5–3 Hz 与 theta 重叠：减它会削掉 θ，让 β/(θ+α) 虚高，
        # 所以慢摆只能识别、不能修——识别到就直接拒绝出分。
        swing_ratio, swing_frac = _swing_metric(work, ch_ok, fs, thr)
        if swing_frac > MOTION_SWING_FRAC:
            motion_severe = True
        motion = {
            "step_uv": round(step_uv, 1),
            "swing_ratio": round(swing_ratio, 3),
            "swing_frac": round(swing_frac, 3),
            "common_rms": round(common_rms, 1),
            "severity": "severe" if motion_severe else ("mild" if motion_repaired else "none"),
            "repaired": motion_repaired,
        }
        if motion_severe:
            flags.append("motion")
            self.stats["motion_frames"] += 1
        elif motion_repaired:
            flags.append("motion_fixed")

        # 3.2 削顶：逐通道插值
        for i in range(n_ch):
            if bad[i]:
                continue
            mask = _rail_mask(work[i], thr["rail"], thr["diff"])
            if not mask.any():
                continue
            fixed, ok = _interp_rail(work[i], mask, fs)
            if ok:
                work[i] = fixed
            else:
                # 插值不可信 → 这一路当坏道处理
                bad[i] = True
                ch_ok[i] = False
                if "bad_channel" not in flags:
                    flags.append("bad_channel")

        # 3.3 坏道：幅值置 0，避免异常值进入 PSD；
        #     真正的「不参与频率平均」由 report.channel_mask 交给引擎执行
        if bad.any():
            work[bad] = 0.0

        self._remember(tail_next)  # 供下一窗跨窗检测

        # --- 4. 质量评分 ---------------------------------------------
        channels_ok = int(ch_ok.sum())
        score = 1.0
        if "nan" in flags:
            score -= 0.6
        if "flatline" in flags:
            score -= 0.5
        if "bad_channel" in flags:
            # 按坏道比例扣分：4 通道坏 1 路还能撑，坏 2 路就不行了
            score -= 0.25 * (n_ch - channels_ok)
        if "rail" in flags:
            score -= 0.20
        if "blink" in flags:
            score -= 0.10 * min(len(cur), 3)
        if severe_blink:
            score -= 0.45
        if "emg" in flags:
            score -= 0.30
        if "low_device_quality" in flags:
            score -= 0.20
        if "motion" in flags:
            score -= 0.55
        elif "motion_fixed" in flags:
            score -= 0.15
        score = float(np.clip(score, 0.0, 1.0))

        # 硬性失效条件：没有可用通道，或眨眼看不住
        if channels_ok < max(1, min(2, n_ch)):
            usable = False
        if severe_blink:
            usable = False
        if "nan" in flags or "flatline" in flags:
            usable = False
        if "motion" in flags:
            usable = False

        if not flags:
            flags = ["ok"]
        level = LEVEL_GOOD if score >= 0.75 else (LEVEL_FAIR if score >= 0.45 else LEVEL_POOR)
        if not usable and level == LEVEL_GOOD:
            level = LEVEL_FAIR

        # 提示语：按「最需要用户处理」的顺序挑一条
        hint = _HINTS[level] if level != LEVEL_GOOD else _HINTS["good"]
        for key in ("flatline", "bad_channel", "motion", "blink_severe", "emg",
                    "low_device_quality", "rail", "blink", "motion_fixed"):
            if key in flags:
                hint = _HINTS[key]
                break

        if usable:
            self.stats["usable"] += 1

        report = self._report(
            usable, level, score, flags, hint=hint, n_ch=n_ch,
            channels_ok=channels_ok, blink_count=len(cur),
            blink_ratio=round(blink_ratio, 3), emg_ratio=round(emg_ratio, 3),
            emg_rms=round(emg_rms, 2),
            rail_ratio=round(float(np.mean([r for r in rails])) if rails else 0.0, 3),
            device_quality=device_q, unit=thr["unit"],
            fixed_blinks=fixed_blinks, channel_mask=ch_ok.tolist(),
            motion=motion,
        )
        return work, report

    # -- 报告 -------------------------------------------------------------
    def _report(self, usable, level, score, flags, hint="", n_ch=0,
                channels_ok=None, blink_count=0, blink_ratio=0.0,
                emg_ratio=0.0, emg_rms=0.0, rail_ratio=0.0,
                device_quality=None, unit="uV", fixed_blinks=0,
                channel_mask=None, motion=None):
        return {
            "usable": bool(usable),
            "level": level,
            "score": round(float(score), 2),
            "flags": list(flags),
            "hint": hint,
            "n_ch": int(n_ch),
            "channels_ok": int(channels_ok if channels_ok is not None else n_ch),
            "blink_count": int(blink_count),
            "blink_ratio": float(blink_ratio),
            "fixed_blinks": int(fixed_blinks),
            "emg_ratio": float(emg_ratio),
            "emg_rms": float(emg_rms),
            "rail_ratio": float(rail_ratio),
            "device_quality": device_quality,
            "unit": unit,
            "motion": motion or {"severity": "none"},
            "channel_mask": list(channel_mask) if channel_mask is not None
                            else [True] * int(n_ch),
        }

    def summary(self):
        """会话结束时的伪迹汇总（写进报告）。"""
        frames = max(1, self.stats["frames"])
        return {
            **self.stats,
            "usable_ratio": round(self.stats["usable"] / frames, 3),
            "blink_frame_ratio": round(self.stats["blink_frames"] / frames, 3),
            "notch_hz": _notch_freqs(),
            "params": {
                "blink_uv": BLINK_UV,
                "rail_uv": RAIL_UV,
                "emg_ratio_max": EMG_RATIO_MAX,
                "device_q_min": DEVICE_Q_MIN,
                "sat_uv": SAT_UV,
                "diff_uv": DIFF_UV,
                "blink_repair_band": list(BLINK_REPAIR_BAND),
                "blink_repair_iters": BLINK_REPAIR_ITERS,
                "motion_step_uv": MOTION_STEP_UV,
                "motion_common_uv": MOTION_COMMON_UV,
                "motion_swing_ratio": MOTION_SWING_RATIO,
                "motion_swing_rms_uv": MOTION_SWING_RMS_UV,
                "motion_swing_frac": MOTION_SWING_FRAC,
            },
        }


# ---------------------------------------------------------------------------
# 无状态便捷函数（脚本 / 测试用）
# ---------------------------------------------------------------------------
def clean_window(seg, fs=256.0, ch_names=None, device_quality=None):
    """一次性清洗（内部新建清洗器，不保留跨窗状态）。

    实时链路请用 ``ArtifactCleaner`` 实例，才能获得跨窗眨眼检测。
    """
    cleaner = ArtifactCleaner(fs=fs)
    return cleaner.process(seg, ch_names=ch_names, device_quality=device_quality)
