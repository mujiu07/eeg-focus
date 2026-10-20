# Xmuse 脑电波仪硬件接入方案

> 项目：梦境池塘脑波专注游戏 MVP（`eeg-focus/`）
> 状态：方案（未编码）
> 日期：2026-10-20
> 素材来源：设备商 GitHub 组织 `AI-Xmuse`（厦门北洋瑞恒智慧健康有限公司）公开仓库调研结论

---

## 1. 背景与目标

当前 MVP 的信号源为三选一（`app/sources.py`）：

| 信号源 | 现状 |
|---|---|
| `replay` | EDF 真实数据回放（默认演示） |
| `manual` | 滑块手动模拟专注度 |
| `hardware` | **占位**，`start()` 直接抛 `RuntimeError` |

本次目标：把 `hardware` 信号源落地为真实的 **Xmuse 便携式脑电波仪** 接入，
让游戏由真实脑电驱动专注度，替代/补充 EDF 回放演示。

---

## 2. 设备与协议调研结论（基于官方仓库证据）

### 2.1 设备本质

Xmuse 是 **Muse 2 的国产兼容版**（官方仓库同时提到 "Muse 2 和 Muse S 硬件"，协议与通道布局一致）：

- 6 通道 EEG：TP9 / AF7 / AF8 / TP10（4 通道标准位）+ 2 个扩展电极
- 多模态：PPG（光电容积）、陀螺仪、加速度计、磁力计、电池、温度
- 蓝牙连接电脑/手机，官方配套软件 **Xmuse Direct**（科研版，含可视化与数据导出）
- 支持 **LSL** 与 **OSC** 两种实时传输协议，另有 EDF/CSV 离线导出
- 官方提供 Python / MATLAB SDK（Xmuse-ToolBox）与二次开发工具集（Xmuse-Coding）

### 2.2 可获取的信号清单（Xmuse-Connect README 原文整理）

通过 LSL/OSC 协议可实时获取 **20 多种**信号：

- **EEG**：6 通道脑电（4 标准 + 2 扩展）
- **PPG** 光电容积（心率/血氧相关）
- **GYRO** 陀螺仪、**ACC** 加速度计（3 轴）
- **elements 元素信号**：眨眼（blink）、咀嚼（jaw_clench）、触摸额头（touching_forehead）、接触指示、佩戴标识、数据质量判断
- 温度、电池
- **脑波频段功率**（关键！）：α / β / γ / δ / θ 五个频段的**功率谱密度相对值 + 绝对值**

> 注意：官方清单中**没有**现成的 "attention / 专注度 0-100" 信号。
> 专注度必须由我们自行计算——这正是本项目模型链路的用武之地，也是下面方案的核心。

### 2.3 两条实时传输管道（均已由官方代码验证）

#### 管道 A：OSC（Open Sound Control）

- 拓扑：`Xmuse Direct 软件（发） → 本地 UDP 端口（收）`
- 官方 OSC 客户端监听 `127.0.0.1`，示例端口 **8000 / 7000 / 8001 / 8002**
- 已证实的 OSC 地址（从官方游戏/工具源码提取）：

| 地址 | 内容 | 出处 |
|---|---|---|
| `{prefix}/acc` | 加速度计 3 轴（float ×3） | Greedy-Snake-Game/game.py |
| `{prefix}/elements/jaw_clench` | 咀嚼 0/1 | Greedy-Snake-Game/game.py |
| `{prefix}/elements/blink` | 眨眼 | Tank-Game |
| `{prefix}/elements/touching_forehead` | 触摸额头 | Tank-Game |
| `{prefix}/elements/eeg/eeg[0]` | EEG 单通道原始值 | Tank-Game |
| `/8000/eeg` | EEG（prefix 为端口号时的写法） | OSC_client/Server.py |

- `prefix` 由用户在 Xmuse Direct 软件中配置，**可为空**（Tank-Game 明确支持留空，此时地址为 `/elements/...`）
- 官方 OSC 工具用 `dispatcher.map("*")` 通配符接收**所有路径**，说明设备实际推送的地址多于上表

#### 管道 B：LSL（Lab Streaming Layer，科研标准）

- 拓扑：`Xmuse Direct 软件（提供 LSL 流） → pylsl 客户端（订阅）`
- 官方示例（`LSL-singal device.py`）用 `pylsl.resolve_byprop("type", "EEG")` 自动发现流，支持 `EEG / ACC / GYRO / PPG` 等多种 type
- 流信息：`nominal_srate`（约 256 Hz）、`channel_count`（EEG 为 4 或 6）、通道 label 来自流的 XML 描述（官方代码支持从流读取通道名）
- 优势：**时间戳由 LSL 统一协调**，多模态自动对齐；官方工具做了去抖动（线性回归校时）

### 2.4 官方离线预处理口径（Xmuse-ToolBox 预处理工具链）

官方处理管线（与我们的特征链路几乎一致）：

1. 数据清理：仅保留 `timestamps, eeg_1, eeg_2, eeg_3, eeg_4` 四通道
2. 基线校正（减 DC 偏移 / 去基线均值）
3. 带通滤波 **0.1–60 Hz** + 陷波 **49–51 Hz**（50 Hz 工频）
4. 极值修复：±100 µV 外线性插值
5. 标准化（Z-score）
6. 分段 1 s + Welch 法 PSD，频带：Delta 0.5–4 / Theta 4–8 / Alpha 8–12 / Beta1 12–15 / Beta2 15–20 / Gamma1 30–60

---

## 3. 本项目现有链路的接入约束（关键）

### 3.1 现有特征与模型口径（`app/features.py`、`scripts/preprocess.py`）

- 频带：delta 0.5–4 / theta 4–8 / alpha 8–13 / beta 13–30 / gamma 30–45 Hz
- 窗口：**2 s**，Welch 法，每通道 5 绝对功率 + 5 相对功率 + theta/beta 比值 = **11 维/通道**
- 模型：`outputs/models/LogisticRegression.joblib`，`predict_proba[:,1]` → 平滑 → focus 0..1
- 训练数据：EEGMAT 数据集（PhysioNet "EEG During Mental Arithmetic Tasks"）

### 3.2 致命约束：通道数不匹配

- 训练用的 EDF 是 **21 通道**（10-20 系统全通道 + A2-A1 + ECG），500 Hz
- 模型输入维度 = 21 × 11 = **231 维**
- Xmuse 只有 **4（或 6）通道**（TP9/AF7/AF8/TP10 布局）→ 特征维度 44（或 66）维
- **现有 `LogisticRegression.joblib` 无法直接推理 4 通道窗口**（维度不匹配会报错）

结论：接入 Xmuse 必须**要么重训模型，要么绕过模型直接用频带指标**。这是本方案与"换数据源"式接入的最大区别，必须先解决。

### 3.3 现有 `HardwareSource` 接口约定（`app/sources.py`）

实现真实接入时只需满足：

```python
class HardwareSource(EEGSource):
    name = "hardware"
    def start(self): ...          # 建立连接/订阅，阻塞式初始化
    def next_window(self):        # 返回 (seg, meta)
        # seg: (n_ch, n_samples) 原始窗口（2 s）
        # meta: dict, 含 fs 等（Session._run 用 meta.get("fs", source.fs)）
```

下游不用改：`Session._run` 中 `source.name != "manual"` 时走 `engine.update(seg, fs)` → SSE 帧结构不变。

---

## 4. 推荐方案（分两阶段落地）

> 原则：**先打通数据管道拿真实 EEG，再解决专注度算法**；两阶段可独立交付。

### 阶段 1：LSL 管道 + 频带指标直接算专注度（最快可用）

**目标**：让 `hardware` 源跑起来，游戏用真实脑电驱动（约 1–2 天工作量）。

1. **新增依赖**：`pylsl`（仅阶段 1 需要；`python-osc` 是阶段 2 备选）
2. **实现 `HardwareSource`（LSL 版）**：
   - `start()`：`pylsl.resolve_byprop("type", "EEG", timeout=10)` → `StreamInlet`
   - 后台线程循环 `pull_chunk` 累积 2 s 窗口，返回 `(seg, meta)`（fs 取流 nominal_srate，约 256 Hz）
   - 只取前 4 通道（或按通道名映射 TP9/AF7/AF8/TP10）
3. **专注度算法（替代 231 维模型）**：基于官方脑波频段/自算 PSD 的工程指标
   - 首选：自算 `alpha 8–13 / beta 13–30 / theta 4–8` 功率（与 `features.band_power` 完全同口径）
   - 指标候选：
     - `beta / (theta + alpha)`（低 theta、高 beta → 专注，神经工效学常用）
     - `beta_abs / total`（相对 beta 功率）
     - 可结合设备直出的 β 频段相对功率（若 OSC/LSL 提供 brainwaves 流）
   - 经 `min-max` 映射到 0..1 作为 `focus`，并保留现有 `FocusEngine.smooth_focus` 平滑
4. **前端零改动**：SSE 帧、校准、报告流程复用现有实现；dev 页源切换选 "hardware"

### 阶段 2：采集数据重训 4 通道模型（精度提升，可选）

**目标**：复用现有"特征 + LogisticRegression"套路，建立 Xmuse 专属 4 通道专注模型。

1. 数据采集：用 Xmuse 设备按 EEGMAT 实验范式录数据
   - 放松段（静坐闭眼/放松）→ 标签 0
   - 心算任务段（持续减法/乘法）→ 标签 1
   - 每类 ≥ 5 分钟，逐被试；LSL 采集脚本可基于官方 `LSL-singal device.py` 改造（CSV 落盘）
2. 离线预处理：复用官方工具链口径（0.1–60 Hz 带通、陷波、±100 µV 修复、Z-score）
   - **注意**：本项目 `features.bandpass` 是 0.5–45 Hz，与官方 0.1–60 Hz 不同；重训时统一口径即可（建议沿用 `features.py` 现有口径保持一致性）
3. 训练：仿照 `scripts/train.py`，特征 4 通道 × 11 = 44 维，输出 `outputs/models/Xmuse-4ch-LogisticRegression.joblib`
4. `FocusEngine` 增加模型路径参数；`HardwareSource` 走模型推理，`replay` 仍用 231 维模型

### 阶段 2'（备选，零数据成本）：OSC 管道直读设备脑波频段

若厂商确认 OSC 或 LSL 的 **brainwaves 流**（α/β/θ 相对/绝对功率）可用，则：

- `HardwareSource`（OSC 版）订阅 `{prefix}/brain_waves`（待确认地址）或 LSL `type="brainwaves"` 流
- 直接以 `β相对功率` 或 `β/(α+θ)` 为 focus，**连 PSD 都不用自己算**
- 依赖 `python-osc`，官方有现成 `OSC_client` 可参考

---

## 5. 实现路线图（代码级）

```
app/
├── sources.py        # HardwareSource: 阶段1=LSL 订阅；阶段2=OSC 订阅
├── features.py       # 不变（band_power 可复用）
├── focus_engine.py   # 阶段2: 支持 model_path 参数
├── xmuse_source.py   # (新增) LSL/OSC 订阅器：连接、环形缓冲、2s 出窗
└── server.py         # 不变（create_source("hardware") 已接通）
scripts/
├── collect_xmuse.py  # (新增) 阶段2 采集脚本（放松/心算标注录制）
├── train_xmuse.py    # (新增) 4 通道模型训练
web/assets/api.js     # 不变
```

关键实现点：

1. **环形缓冲**：LSL 256 Hz × 2 s = 512 样本/窗；维护 `deque(maxlen=512)`，每满一窗即出（与 STEP 0.5 s 不同——硬件源按"满窗即出"，节奏由设备驱动，SSE 帧率随之变化，前端按帧渲染无碍）
2. **断连处理**：LSL 流丢失 → `start()` 重试/`describe()` 上报 `connected: false`，前端显示未连接（沿用 dev 页现有提示）
3. **通道顺序**：按流内通道 label 映射到 `[TP9, AF7, AF8, TP10]` 固定顺序，避免模型输入错位
4. **信号质量**：官方有"数据质量判断"与"接触指示"信号，接入后可做 `meta["quality"]`，低质量帧前端给提示

---

## 6. 需要厂商确认的事项清单

以下影响方案定型，**建议邮件 `1024@xmuse.cn`（官网）或 `support@xmuse.cn` / `huags@xmuse.cn`（仓库作者）确认**：

| # | 待确认事项 | 为什么重要 | 影响 |
|---|---|---|---|
| 1 | Xmuse Direct 软件是否输出 **brainwaves / 脑波频段功率** 的 OSC 地址？具体地址与字段？ | 决定阶段 2' 是否可行（最省事路线） | 阶段 2' 取舍 |
| 2 | OSC 模式下地址前缀规则与完整地址表（除已发现的 acc / elements/... 外） | 阶段 2' 需要精确地址；通配符实测 | 阶段 2' 实现 |
| 3 | LSL 流名/type 全表（EEG / ACC / GYRO / PPG / elements / brainwaves?）及各自采样率、通道数 | 阶段 1 依赖 LSL 流定义 | 阶段 1 细节 |
| 4 | Xmuse Direct 连接流程：是否必须蓝牙配对后软件推流？有无 API 直达设备（不经 Direct）？ | 决定产品使用流程（是否要求用户开 Direct） | 产品化 |
| 5 | 2 个扩展电极的通道名/位置；能否只输出 4 通道 | 模型通道对齐 | 阶段 2 采集 |
| 6 | 设备采样率确认（256 Hz?）与数据单位（µV?） | 特征口径一致性 | 全阶段 |
| 7 | 儿童佩戴的舒适度/尺寸建议、最小年龄限制 | 产品约束（儿童友好） | 产品化 |

> 若厂商回复明确支持 brainwaves OSC 地址（事项 1），阶段 2' 可直接替代阶段 1 的 PSD 自算，是成本最低的方案。

---

## 7. 风险与备选

| 风险 | 影响 | 缓解 |
|---|---|---|
| 厂商脑波频段流不可用 | 阶段 2' 落空 | 阶段 1 自算 PSD（无依赖，必成） |
| LSL 时间戳抖动/丢包 | focus 抖动 | 官方去抖动参考；`smooth_focus` 已有 |
| 通道顺序与 EDF 不一致 | 阶段 2 模型错位 | 按 label 映射 + 采集时记录 |
| 蓝牙连接不稳定 | 断流 | 重连 + 前端"未连接"提示 |
| 现有 21 通道模型无法复用 | 阶段 1 不走模型 | 频带指标替代（已设计） |

---

## 8. 交付顺序建议

1. （0.5 天）采购/借到 Xmuse 设备 + 装 Xmuse Direct，人工验证 OSC/LSL 推流，抓一份真实地址表 → **同时发厂商确认邮件**
2. （1–2 天）阶段 1：`HardwareSource(LSL)` + 频带指标，dev 页真机联调
3. （按需）阶段 2：采集 + 重训 4 通道模型
4. （按需）阶段 2'：若厂商确认 brainwaves 流，简化实现

---

## 附：调研证据出处（均为官方仓库，克隆于 2026-10-20）

- 组织：`https://github.com/AI-Xmuse`
- `Xmuse-ToolBox/Python-ToolBox/Xmuse-Connect/README.md`：信号清单、协议总述
- `Xmuse-ToolBox/Python-ToolBox/Xmuse-Connect/LSL/LSL-singal device.py`：LSL 订阅与采集参考
- `Xmuse-ToolBox/Python-ToolBox/Xmuse-Connect/OSC/OSC-single decice.py`：OSC 通配符接收参考
- `Xmuse-ToolBox/Python-ToolBox/预处理工具链-V1.0/`：离线处理口径、频带定义
- `Xmuse-Coding/OSC_client/Server.py`：`/8000/eeg` 监听示例
- `Xmuse-Coding/Pylsl/`：LSL 流发现/信息解析参考
- `Xmuse-Coding/Xmuse_OSC_For_Plenty_Machine_Recording/`：多端口 OSC 采集参考
- `Xmuse-Brain-Game/`（Greedy-Snake / Tank / Gomoku 等）：OSC 地址实证
