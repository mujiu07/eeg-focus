"""denoise 模块自检：合成 Xmuse 4 通道信号，验证去噪/去伪迹是否生效。

不依赖 pytest，直接 python 运行，失败会抛 AssertionError。
"""
import sys
import os
import numpy as np
from scipy import signal as sg

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "eeg-focus"))

from app import denoise
from app import features

FS = 256.0
N = int(2.0 * FS)
CH = ["TP9", "AF7", "AF8", "TP10"]


def synth(seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(N) / FS
    seg = np.zeros((4, N))
    # 背景：alpha 10 Hz + beta 20 Hz + 少量 1/f 噪声
    for i in range(4):
        seg[i] = (12.0 * np.sin(2 * np.pi * 10 * t + i)
                  + 6.0 * np.sin(2 * np.pi * 20 * t + 2 * i)
                  + rng.normal(0, 2.0, N))
    return seg, t


def add_line_noise(seg, amp=60.0, hz=50.0):
    t = np.arange(seg.shape[1]) / FS
    return seg + amp * np.sin(2 * np.pi * hz * t + 0.3)


def add_blink(seg, t, center=1.0, width=0.12, amp=180.0, chans=(1, 2)):
    """在 AF7/AF8 上叠加一个眨眼：高斯包络的低频脉冲（和真实眨眼形状接近）。"""
    env = np.exp(-0.5 * ((t - center) / width) ** 2)
    for i in chans:
        seg[i] += amp * env
    return seg


def band_power(x, fs, lo, hi):
    b = features.bandpass(x[None, :], fs, low=lo, high=hi)
    return float(np.mean(b ** 2))


def main():
    ok = []

    # --- 1. 干净信号：应该判 good，且 usable ---
    clean, t = synth()
    c = denoise.ArtifactCleaner(fs=FS)
    out, rep = c.process(clean, ch_names=CH)
    print("[1] clean ->", rep["level"], rep["flags"], rep["score"])
    assert rep["usable"], "干净信号应判可用"
    assert rep["level"] == "good", f"干净信号应 good，实际 {rep['level']}"
    assert out.shape == clean.shape
    ok.append("clean")

    # --- 2. 工频陷波：50 Hz 功率应下降一个数量级以上 ---
    noisy = add_line_noise(clean, amp=60.0)
    p_before = band_power(noisy[1], FS, 48.0, 52.0)
    c2 = denoise.ArtifactCleaner(fs=FS)
    out2, rep2 = c2.process(noisy, ch_names=CH)
    p_after = band_power(out2[1], FS, 48.0, 52.0)
    atten = 10 * np.log10(p_before / max(p_after, 1e-12))
    print(f"[2] notch 50Hz: {atten:.1f} dB 抑制, level={rep2['level']}")
    assert atten > 20, f"陷波抑制不足: {atten:.1f} dB"
    ok.append("notch")

    # --- 3. 眨眼：应检出、显著压低幅值，且不破坏 alpha/beta 功率 ---
    blink = add_blink(clean.copy(), t, center=1.0, amp=180.0)
    raw_peak = float(np.max(np.abs(blink[1])))
    c3 = denoise.ArtifactCleaner(fs=FS)
    out3, rep3 = c3.process(blink, ch_names=CH)
    fixed_peak = float(np.max(np.abs(out3[1])))
    print(f"[3] blink: raw_peak={raw_peak:.1f} -> {fixed_peak:.1f}, "
          f"count={rep3['blink_count']}, flags={rep3['flags']}")
    assert rep3["blink_count"] >= 1, "未检出眨眼"
    assert fixed_peak < raw_peak * 0.65, f"眨眼幅值压制不足: {fixed_peak:.1f}"
    assert rep3["usable"], "单个眨眼修复后应仍可用"

    # 修复不得伤到真实脑电：alpha / beta 功率变化应 < 15%
    def _bp(x, lo, hi):
        f, p = sg.welch(x, fs=FS, nperseg=256)
        m = (f >= lo) & (f <= hi)
        return float(np.trapezoid(p[m], f[m]))

    for band_name, lo, hi in (("alpha", 8, 13), ("beta", 13, 30)):
        before = _bp(blink[1], lo, hi)
        after = _bp(out3[1], lo, hi)
        dev = abs(after - before) / before
        print(f"    {band_name}: {before:.1f} -> {after:.1f} ({dev*100:.1f}%)")
        assert dev < 0.15, f"{band_name} 功率被眨眼修复破坏: {dev*100:.1f}%"
    ok.append("blink")

    # --- 4. 削顶：大幅值段应被插值，且不判死 ---
    rail = clean.copy()
    rail[0, 200:240] = 400.0
    c4 = denoise.ArtifactCleaner(fs=FS)
    out4, rep4 = c4.process(rail, ch_names=CH)
    peak4 = float(np.max(np.abs(out4[0])))
    print(f"[4] rail: peak={peak4:.1f}, flags={rep4['flags']}, level={rep4['level']}")
    assert "rail" in rep4["flags"], "未检出削顶"
    assert peak4 < 100.0, f"削顶段未被插值修复: {peak4:.1f}"
    ok.append("rail")

    # --- 5. 电极脱落（恒定段）：应判不可用 ---
    flat = clean.copy()
    flat[3, :] = 0.0
    c5 = denoise.ArtifactCleaner(fs=FS)
    _, rep5 = c5.process(flat, ch_names=CH)
    print(f"[5] flatline: flags={rep5['flags']}, usable={rep5['usable']}")
    assert "flatline" in rep5["flags"], "未检出脱落通道"
    assert not rep5["usable"], "整路脱落应判不可用"
    ok.append("flatline")

    # --- 6. 肌电：35-45Hz 强噪声应被识别 ---
    emg = clean.copy()
    rng = np.random.default_rng(3)
    hi = rng.normal(0, 60.0, N)
    b, a = sg.butter(4, [35, 45], btype="bandpass", fs=FS)
    hi = sg.filtfilt(b, a, hi)
    emg[1] += hi
    c6 = denoise.ArtifactCleaner(fs=FS)
    _, rep6 = c6.process(emg, ch_names=CH)
    print(f"[6] emg: ratio={rep6['emg_ratio']}, flags={rep6['flags']}")
    assert "emg" in rep6["flags"], "未检出肌电"
    ok.append("emg")

    # --- 7. ADC 量级（非 µV）：不应把正常信号全判坏 ---
    adc = clean * 200.0
    c7 = denoise.ArtifactCleaner(fs=FS)
    _, rep7 = c7.process(adc, ch_names=CH)
    print(f"[7] adc-scale: unit={rep7['unit']}, level={rep7['level']}, flags={rep7['flags']}")
    assert rep7["unit"] == "auto", "未识别 ADC 量级"
    assert rep7["level"] != "poor", "ADC 量级不应判 poor"
    ok.append("unit-adaptive")

    # --- 8. 跨窗眨眼：眨眼横跨窗口边界也要检出 ---
    long = np.concatenate([clean, clean], axis=1)
    # 在第一个窗口末尾 0.05s 处放一个眨眼，使其大部分落在第二个窗口
    t_long = np.arange(long.shape[1]) / FS
    long = add_blink(long, t_long, center=1.95, amp=200.0)
    c8 = denoise.ArtifactCleaner(fs=FS)
    c8.process(long[:, :N], ch_names=CH)          # 第一窗
    _, rep8 = c8.process(long[:, N:2 * N], ch_names=CH)  # 第二窗
    print(f"[8] cross-window blink: count={rep8['blink_count']}, flags={rep8['flags']}")
    assert rep8["blink_count"] >= 1, "跨窗眨眼漏检"
    ok.append("cross-window")

    # --- 9. 特征口径不变：清洗后仍可走 features.prepare_signal ---
    feats = features.window_to_features(features.prepare_signal(out3, FS), FS)
    print(f"[9] feature dim={feats.shape[0]}, finite={np.isfinite(feats).all()}")
    assert feats.shape[0] == 4 * len(features.FEAT_NAMES)
    assert np.isfinite(feats).all()
    ok.append("features-compatible")

    # --- 11. 运动：DC 台阶（可修，且不得把专注分抬高）---
    def _focus_ratio(x):
        th = band_power(x, FS, 4.0, 8.0)
        al = band_power(x, FS, 8.0, 13.0)
        be = band_power(x, FS, 13.0, 30.0)
        return be / (th + al + 1e-12)

    base_ratio = _focus_ratio(clean[1])
    step_sig = clean.copy()
    step_sig[1, N // 2:] += 50.0          # 电极极化突变后的新基线
    c11 = denoise.ArtifactCleaner(fs=FS)
    out11, rep11 = c11.process(step_sig, ch_names=CH)
    edge = int(0.25 * FS)
    left = float(np.median(out11[1, N // 2 - edge:N // 2]))
    right = float(np.median(out11[1, N // 2 + edge:N // 2 + 2 * edge]))
    r11 = _focus_ratio(out11[1])
    print(f"[11] motion-step: flags={rep11['flags']}, usable={rep11['usable']}, "
          f"residual={abs(right - left):.1f} uV, beta/(theta+alpha) "
          f"{base_ratio:.2f}->{r11:.2f}")
    assert rep11["usable"], "50 uV 台阶应可修复"
    assert abs(right - left) < 30.0, f"台阶残留过大: {abs(right - left):.1f}"
    assert r11 < base_ratio * 1.25, "台阶修复后专注分被虚高"
    ok.append("motion-step")

    # --- 12. 运动：大幅台阶 → 不可信，拒绝出分 ---
    big = clean.copy()
    big[1, N // 2:] += 200.0
    c12 = denoise.ArtifactCleaner(fs=FS)
    _, rep12 = c12.process(big, ch_names=CH)
    print(f"[12] motion-severe: flags={rep12['flags']}, usable={rep12['usable']}")
    assert "motion" in rep12["flags"], "200 uV 台阶未被识别为运动"
    assert not rep12["usable"], "大幅台阶不应出分"
    ok.append("motion-severe")

    # --- 13. 运动：0.5-3 Hz 慢摆 → 与 theta 重叠，只能拒绝 ---
    sway = clean.copy()
    sway[1] += 100.0 * np.sin(2 * np.pi * 0.8 * t)
    c13 = denoise.ArtifactCleaner(fs=FS)
    _, rep13 = c13.process(sway, ch_names=CH)
    print(f"[13] motion-sway: flags={rep13['flags']}, motion={rep13['motion']}")
    assert "motion" in rep13["flags"], "慢摆未被识别"
    assert not rep13["usable"], "慢摆不应出分"
    assert not rep13["motion"]["repaired"], "慢摆不应被强行修复（会削掉 theta）"
    ok.append("motion-sway")

    # --- 14. 运动：全通道共模偏移 → 可减除 ---
    cm_sig = clean.copy()
    cm_sig[:, N // 2:] += 150.0
    before = float(np.sqrt(np.mean(np.median(cm_sig, axis=0) ** 2)))
    c14 = denoise.ArtifactCleaner(fs=FS)
    out14, rep14 = c14.process(cm_sig, ch_names=CH)
    after = float(np.sqrt(np.mean(np.median(out14, axis=0) ** 2)))
    print(f"[14] motion-common: flags={rep14['flags']}, usable={rep14['usable']}, "
          f"common {before:.1f}->{after:.1f} uV")
    assert rep14["usable"], "共模偏移应可修复"
    assert after < before * 0.6, f"共模减除不足: {before:.1f}->{after:.1f}"
    ok.append("motion-common")

    # --- 10. 汇总 ---
    print("[10] summary =", c3.summary())
    ok.append("summary")

    print("\n全部通过:", ", ".join(ok))


if __name__ == "__main__":
    main()
