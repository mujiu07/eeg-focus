# Xmuse 去噪与去伪迹流程

> 项目：专注小蛙 · 梦境池塘（`eeg-focus/`）
> 模块：`app/denoise.py`（新增），接入 `app/sources.py`、`app/focus_engine.py`、`app/server.py`
> 适用范围：**Xmuse 硬件源**（校准页与游戏页共用同一套处理）；EDF 回放与手动模式不经过本模块

---

## 1. 为什么需要这一步

Xmuse 是 Muse 2 的国产兼容设备，参数决定了它的噪声画像：

| 项目 | 取值 | 对信号处理的影响 |
|---|---|---|
| 通道 | 4 路（TP9 / AF7 / AF8 / TP10），可扩到 6 路（+AUX1 / AUX2） | 通道少，单路坏道不能简单丢弃，需要掩码排除而非置零 |
| 采样率 | 256 Hz（Nyquist 128 Hz） | 50 Hz 陷波余量充足；眨眼检测用 1–8 Hz 足够 |
| 电极 | 前额 + 耳后**干电极**，无导电膏 | 接触阻抗高，慢漂移、电极松动、下颌肌电都常见 |
| 关键污染 | AF7/AF8 紧邻眼睛 | **眨眼是最大干扰源**，幅值常为 β 波的 10 倍以上 |
| 幅值单位 | 设计为 µV，但个别固件可能直推 ADC 计数 | 需要单位自适应，否则所有绝对阈值失效 |
| 自带质量 | `/elements/is_good`（0–1） | 作为辅助降级信号，不单独判死 |

原链路只有一层 `0.5–45 Hz` 带通 + EMA 平滑。带通能压工频尾巴，但**拦不住眨眼**：一个 150 µV 的眨眼会让整窗 PSD 抬升，专注分瞬间冲高，而游戏会把它读成"孩子突然很专注"。

---

## 2. 处理流程（每个 2 s 窗口，0.5 s 步长）

```
OSC 原始窗口 (n_ch, 512)
   │
   ├─ 0. 输入体检      形状 / NaN / 恒定段 / 单位判定
   ├─ 1. 通道清理      去线性趋势 → 50 Hz 零相位陷波
   ├─ 2. 伪迹检测      眨眼 / 削顶饱和 / 肌电 / 坏道 / 设备 is_good
   ├─ 3. 伪迹修复      眨眼带通减除、削顶线性插值、坏道掩码
   ├─ 4. 质量评分      0–1 分 + flags + 中文提示 + usable 判定
   └─ 5. 输出          清洗信号（**未带通**）+ 结构化报告
```

### 2.1 通道清理

1. **去线性趋势**（`scipy.signal.detrend`）：先去掉 2 s 内的慢漂移，避免后续滤波在窗口两端摆出假低频。
2. **50 Hz 陷波**（`iirnotch`, Q=30, `filtfilt` 零相位）：Xmuse 干电极对工频敏感；陷波中心必须离 Nyquist 足够远（fs 过小时自动跳过）。
   - `EEG_NOTCH_HZ=50`（默认），可填 `60` 或 `off`。

### 2.2 伪迹检测

| 伪迹 | 判据 | 默认阈值 | 依据 |
|---|---|---|---|
| 眨眼 | 1–8 Hz 带通定边界 + **原始幅值**确认 | 80 µV | 干电极上一个典型眨眼 80–300 µV；带通会把幅值砍半，所以幅值判定必须回到原始信号 |
| 削顶 / 饱和 | 幅值过阈 **或** 一阶差分过阈 | 180 µV / 60 µV·sample⁻¹ | 正常脑电峰峰值多在 ±150 µV 内；差分判据抓"幅值没到轨但斜率断崖"的 AB 型饱和 |
| 肌电 | 35–45 Hz 能量占比 **且** 该频段 RMS 双条件 | 45% 且 15 µV | 单看占比会把正常 γ 误判；双条件更稳 |
| 坏道 | 稳健标准差（MAD×1.4826）过低或过高 | < 0.5 µV / > 150 µV | 过低=电极脱落/短接，过高=接触不良 |
| 设备质量 | `/elements/is_good` | < 0.5 | 只降级不判死，避免固件口径差异误伤 |

**跨窗眨眼**：清洗器保存上一窗尾部 0.5 s 拼到当前窗前再做检测。否则一个正好压在窗口边界的眨眼，会被切成两半、各自峰值不过阈值而漏检。

### 2.3 伪迹修复

- **眨眼**：对 `0.5–8 Hz` 分量按汉宁窗在事件段内渐进减除，**迭代 2 次**。
  - 为什么不减更宽的频带：实测 `0.5–15 Hz` 会把 alpha 一起削掉约 20%，而 `0.5–8 Hz` 迭代 2 次能在**不改变 alpha/beta 功率**的前提下把幅值压低约 55%。
  - 为什么不用插值：插值会把该段真实脑电一起抹掉，反而系统性压低 β 占比。
  - 只减前额通道（AF7/AF8）：TP9/TP10 上几乎没有眨眼，硬减会挖出凹陷。
- **削顶**：单段 ≤ 0.3 s 才做线性插值；更长的段认为不是瞬时饱和（电极抖动/脱落），放弃修复并把该通道当坏道。
- **坏道**：信号置 0 防止异常值进入 PSD，真正的"不参与平均"由 `report.channel_mask` 交给引擎执行。

> 若一窗内眨眼超过 3 次或占比超过 60%，不再修复，直接判 `usable=false`——修完也不可信，且会吃掉过多脑电。

### 2.4 质量评分与门控

```
score = 1.0
        −0.60 nan        −0.50 flatline     −0.25 × 坏道数
        −0.20 rail       −0.10 × 眨眼数     −0.45 眨眼过多
        −0.30 emg        −0.20 设备质量低
```

- `score ≥ 0.75` → `good`（绿）；`≥ 0.45` → `fair`（黄）；否则 `poor`（红）
- `usable = false` 的硬条件：可用通道 < 2、眨眼过多、NaN、整窗恒定
- 中文提示按"最需要用户处理"的顺序挑一条（脱落 → 接触 → 眨眼 → 肌电 → 工频）

### 2.5 单位自适应

若 `median(|x|) > 500 µV`，判定固件推的是 ADC 计数，所有绝对阈值改按稳健标准差倍数重算：

| 阈值 | µV 模式 | ADC 模式 |
|---|---|---|
| rail | 180 | 8 σ |
| blink | 80 | 5 σ |
| 坏道上限 | 150 | 12 σ |
| 一阶差分 | 60 | 1.2 σ |

这样"换固件不换行为"。报告里 `unit` 字段会标 `uV` / `auto` / `unknown`。

---

## 3. 与训练口径的关系（重要约束）

`clean_window` **不做 0.5–45 Hz 带通**。带通仍然由 `features.prepare_signal` 完成，因此：

- 模型输入的特征口径与 `scripts/preprocess.py` 完全一致，**不需要重训**
- 去噪只做"去趋势 + 陷波 + 伪迹修复"，属于在原始信号上加的分量，不是替换特征链路

这与 `docs/xmuse-hardware-integration.md` §10.3 的变更守则一致。

---

## 4. 接入点

| 位置 | 改动 |
|---|---|
| `app/sources.py` → `HardwareSource` | `next_window()` 内调用 `ArtifactCleaner.process()`，清洗结果替换窗口，报告写入 `meta["artifact"]`；新增 `artifact_summary()` |
| `app/focus_engine.py` | `update/compute_raw/_band_focus` 新增 `channel_mask` 参数：坏道不参与频段平均 |
| `app/server.py` → `Session._run` | `meta["artifact"]["usable"] == False` 时输出 `valid=False, reason="artifact"` 的帧，**不进入 history**，避免污染校准基线与报告曲线 |
| `app/server.py` → `/calibrate` | 校准结果写入 `calibration.signal_quality`；`usable_ratio < 0.6` 时标记 `quality_warning` |
| `app/server.py` → `finish` | 报告新增 `signal_quality`、`n_artifact_frames` |
| `web/calibrate.html` | 校准过程中显示实时质量徽章；完成后显示"可用比例 / 眨眼占比"，质量差时建议重做 |
| `web/game.html` | HUD 新增质量圆点；**伪迹帧不打断游戏**（保持上一帧分数），只降级指示；真断流仍由 3 s 看门狗兜底 |

### 为什么伪迹帧不暂停游戏

原逻辑里任何 `valid=false` 都会进入 `state.stale`，暂停计时并提示"信号中断"。对一个每 0.5 s 出一帧的硬件链路，孩子眨一次眼就可能暂停一次，体验会碎掉。因此：

- **伪迹窗** → 保持上一帧分数继续玩，质量点变黄/红
- **真正断流**（3 s 无帧）→ 才暂停计时

---

## 5. 参数速查（环境变量）

| 变量 | 默认 | 说明 |
|---|---|---|
| `EEG_NOTCH_HZ` | `50` | 工频；`60` 或 `off` |
| `EEG_NOTCH_Q` | `30` | 陷波 Q 值 |
| `EEG_RAIL_UV` | `180` | 削顶幅值阈值 |
| `EEG_SAT_UV` | `260` | 饱和阈值（记录用） |
| `EEG_DIFF_UV` | `60` | 一阶差分阈值 |
| `EEG_BLINK_UV` | `80` | 眨眼幅值阈值 |
| `EEG_BLINK_REPAIR_ITERS` | `2` | 眨眼减除迭代次数 |
| `EEG_EMG_RATIO` | `0.45` | 肌电高频占比阈值 |
| `EEG_EMG_RMS_UV` | `15` | 肌电高频 RMS 阈值 |
| `EEG_BAD_STD_MAX_UV` | `150` | 坏道标准差上限 |
| `EEG_DEVICE_Q_MIN` | `0.5` | 设备 is_good 下限 |

前端每帧收到的 `artifact` 报告字段：

```json
{
  "usable": true, "level": "good", "score": 0.9,
  "flags": ["blink"], "hint": "检测到眨眼，已自动修复",
  "n_ch": 4, "channels_ok": 4,
  "blink_count": 1, "blink_ratio": 0.084, "fixed_blinks": 1,
  "emg_ratio": 0.055, "emg_rms": 0.47, "rail_ratio": 0.0,
  "device_quality": null, "unit": "uV",
  "channel_mask": [true, true, true, true]
}
```

---

## 6. 验证证据

### 6.1 单元自检 `tests/selfcheck_denoise.py`

合成 4 通道 256 Hz 信号（alpha 10 Hz + beta 20 Hz + 噪声），逐项注入伪迹：

| 用例 | 结果 |
|---|---|
| 干净信号 | `good`，score 1.0 |
| 50 Hz 工频 +60 µV | 陷波抑制 **20.3 dB** |
| 眨眼 180 µV | 峰值 **196 → 60.9 µV**；alpha 仅降 5.5%，**beta 降 0.1%** |
| 削顶 400 µV | 峰值 **→ 60.7 µV**，判 `rail` |
| 单路电极脱落 | 判 `flatline` + `bad_channel`，`usable=false` |
| 35–45 Hz 肌电 | 判 `emg`，ratio 0.985 |
| ×200 ADC 量级 | `unit=auto`，仍判 `good`（不误伤） |
| 跨窗眨眼 | 第二窗仍检出（count≥1） |
| 特征兼容 | 44 维特征、全部有限 |

### 6.2 端到端 `tests/e2e_hardware_denoise.py`

合成 OSC（UDP 17000，8 样本/包）→ uvicorn → 真实 HTTP/SSE：

```
describe.denoise = {enabled: true, notch_hz: [50.0], blink_repair_band: [0.5, 8.0], blink_repair_iters: 2}
artifact = {usable: true, level: "good", score: 0.9, flags: ["blink"],
            blink_count: 1, rail_ratio: 0.0, channel_mask: [true×4]}
calibration.signal_quality = {frames: 7, usable: 7, usable_ratio: 1.0,
                              blink_frame_ratio: 1.0, rail_frames: 0}
report.signal_quality     = 同上
```

---

## 7. 已知局限

1. **眨眼残留约 45%**：带通减除取不到眨眼的高频边沿。但实测 alpha/beta 功率不受影响，对专注分无害；追求更彻底只能上 ICA/ASR，4 通道下收益有限。
2. **肌电不可逆**：只检测不修复，强肌电窗口直接判不可用。
3. **坏道不插值**：4/6 通道空间太稀疏，插值缺乏依据，因此选择掩码排除。
4. **跨窗历史仅 0.5 s**：更长的事件（如持续眼动）仍可能被切分。
5. **未在真机上标定**：阈值来自 Muse 系干电极公开资料与合成信号，接入真机后建议用 `scripts/xmuse_osc_probe.py` 采一段静息数据复核 `median(|x|)` 与眨眼幅值分布，再决定是否微调 `EEG_*` 变量。
