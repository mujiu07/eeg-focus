# Xmuse 脑电波仪硬件接入方案

> 项目：梦境池塘脑波专注游戏 MVP（`eeg-focus/`）
> 状态：**已实现（OSC/UDP 多端口接收 + 4 通道频段回退）**
> 日期：2026-11-12（原方案 2026-10-20）
> 素材来源：设备商 GitHub 组织 `AI-Xmuse`（厦门北洋瑞恒智慧健康有限公司）公开仓库 + 本机 Xmuse Lab 1.5.8 / Xmuse Direct 1.5.11 安装目录调研
>
> **端口默认值：UDP `7000` + `8000`。修改前必读 §2.3.1。**

---

## 1. 背景与目标

当前 MVP 的信号源为三选一（`app/sources.py`）：

| 信号源 | 现状 |
|---|---|
| `replay` | EDF 真实数据回放（默认演示） |
| `manual` | 滑块手动模拟专注度 |
| `hardware` | **已接入**：Xmuse OSC/UDP 实时脑电（`app/xmuse_osc.py`） |

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
- **Xmuse Direct 默认值（本机 1.5.11 二进制证据）**：`DefaultIPAddress = 127.0.0.1`、`DefaultUdpPort = 7000`
  （`Xmuse Direct.dll` 资源字符串中 `DefaultIPAddress / DefaultUdpPort / CustomPrefix` 与 `127.0.0.1 / 7000` 相邻）
- 官方代码/示例还使用 **8000 / 8001 / 8002**：`/8000/eeg`（OSC_client/Server.py）、多设备 8001/8002（Plenty Machine Recording）；ToolBox 单设备示例同样默认 7000（详见 §2.3.1）
- 因此本项目默认**同时监听 UDP 7000 与 8000**，可用 `XMUSE_OSC_PORTS` 追加 8001/8002
- **端口冲突说明**：本项目的网页服务是 **TCP 8000**，OSC 是 **UDP 8000**，协议不同，可同时占用
- 地址前缀（prefix）在 Xmuse Direct 中可配置，留空时是 `/eeg`，填端口号时是 `/7000/eeg` 或 `/8000/eeg`
- 接收器只匹配“最后一段为 `eeg`”的地址，因此 `/eeg`、`/7000/eeg`、`/8000/eeg`、`/muse/eeg` 都能收；
  会排除 `/elements/eeg/eeg[0]` 这类单通道镜像
- 已证实的 OSC 地址（从官方游戏/工具源码提取）：

| 地址 | 内容 | 出处 |
|---|---|---|
| `{prefix}/acc` | 加速度计 3 轴（float ×3） | Greedy-Snake-Game/game.py |
| `{prefix}/elements/jaw_clench` | 咀嚼 0/1 | Greedy-Snake-Game/game.py |
| `{prefix}/elements/blink` | 眨眼 | Tank-Game |
| `{prefix}/elements/touching_forehead` | 触摸额头 | Tank-Game |
| `{prefix}/elements/eeg/eeg[0]` | EEG 单通道原始值 | Tank-Game |
| `/8000/eeg` | EEG（prefix 为端口号时的写法） | OSC_client/Server.py |
| `/7000/eeg` | EEG（Xmuse Direct 默认端口 7000 + 端口前缀） | Xmuse Direct 默认值推导 |

- `prefix` 由用户在 Xmuse Direct 软件中配置，**可为空**（Tank-Game 明确支持留空，此时地址为 `/elements/...`）
- 官方 OSC 工具用 `dispatcher.map("*")` 通配符接收**所有路径**，说明设备实际推送的地址多于上表

#### 2.3.1 端口选择决策记录（默认 7000/8000，修改需附证据）

> **结论：本项目默认同时监听 UDP `7000` 与 `8000`。这是交叉验证后的结果，不是随手取的，也不是只照搬某一个官方示例。**
>
> 任何成员若要把默认值改成单一端口（例如只留 `8000` 或只留 `7000`），必须在本节补充证据，并同步更新代码、探针与测试；否则视为回归，Review 不予合并。

**证据链**

| 来源 | 具体证据 | 端口 |
|---|---|---|
| 本机 Xmuse Direct 1.5.11 | `Xmuse Direct.dll` 资源字符串 `DefaultIPAddress = 127.0.0.1`、`DefaultUdpPort = 7000` | `7000` |
| AI-Xmuse / ToolBox 单设备 | `Python-ToolBox/Xmuse-Connect/OSC/OSC-single decice.py`：`ip default="127.0.0.1"`、`port default=7000` | `7000` |
| AI-Xmuse / ToolBox 多设备 | 同目录 `OSC-multi device.py`：第一台 `7000`、第二台 `8001` | `7000` / `8001` |
| AI-Xmuse / Coding OSC 客户端 | `OSC_client/Server.py` 前缀 `/8000` 并监听 `8000`；`OSC_client/config.py` 连接 `127.0.0.1:8000` | `8000` |
| AI-Xmuse / Coding 多机录制 | `Xmuse_OSC_For_Plenty_Machine_Recording/main.py`：默认 `[8001, 8002]` | `8001` / `8002` |

**为什么不是只监听 8000**

- 本机 Xmuse Direct 的实际默认是 `7000`，ToolBox 单设备示例也是 `7000`；只监听 `8000` 会让“按默认值连接”的用户完全收不到数据。
- `8000` 是 Xmuse-Coding 示例的口径，而且该示例把端口号写进了 OSC 前缀（`/8000/eeg`），不是所有用户都会这样配置。

**为什么不是只监听 7000**

- 用户按 Xmuse-Coding 示例配置成 `8000` 时，只监听 `7000` 会完全收不到。
- 本项目网页服务是 **TCP 8000**，OSC 是 **UDP 8000**，协议不同，可以同时占用，不存在端口冲突。

**实现不变量**

- Python 默认值：`app/xmuse_osc.py` 的 `DEFAULT_PORTS = "7000,8000"`。
- 页面/环境变量覆盖：`XMUSE_OSC_PORTS=7000,8000,8001,8002`。
- 地址只要求最后一段为 `eeg`，因此 `/eeg`、`/7000/eeg`、`/8000/eeg` 都接收；同时排除 `/elements/eeg/eeg[0]` 这类单通道镜像。
- 修改默认端口时，必须同步更新：`app/xmuse_osc.py`、`app/server.py` 默认参数、`start.ps1`、`scripts/xmuse_osc_probe.py` 示例、本文件本节与 `CHANGELOG.md`。

**变更守则（Review 必查）**

1. 先在真机 Xmuse Direct 设置页确认实际 UDP 端口与前缀，不要只看某个仓库示例。
2. 运行 `scripts/xmuse_osc_probe.py`，把 `packets / port / address / channels` 输出贴到提交说明或 PR。
3. 若只是“看到某个官方示例用 8000”就想删掉 7000，不予合并。
4. 若确需修改默认值，必须附：设备型号、Xmuse Direct 版本、操作系统、探针日志，并更新 `CHANGELOG.md` 与版本 tag。

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

### 3.4 本次已落地实现（2026-11-12）

| 文件 | 改动 |
|---|---|
| `app/xmuse_osc.py` | **新增**：多端口 OSC/UDP 接收器，2 s 窗 / 0.5 s 步长，自动识别 4/6 通道与批量报文，输出质量/电量/断流诊断 |
| `app/sources.py` | `HardwareSource` 由占位改为真实 OSC 源；`create_source("hardware")` 传递 `osc_*` 配置 |
| `app/focus_engine.py` | 4/6 通道（如 Xmuse）自动切换 `β / (θ + α)` 频段指标；21 通道回放仍走原 231 维模型 |
| `app/server.py` | 放开 hardware 会话；新增 `osc_host / osc_ports / osc_fs / osc_channels` 参数；阻塞接收放入线程池；会话结束释放 UDP 端口，并兜底保证同一时间只有一个硬件会话 |
| `web/dev.html`、`web/calibrate.html`、`web/game.html` | 增加“Xmuse 脑电波仪（OSC/UDP）”选项、OSC 端口输入，并在校准→游戏之间沿用硬件模式 |
| `scripts/xmuse_osc_probe.py` | **新增**：端口探针，实测 Xmuse Direct 到底推到哪个 UDP 端口/OSC 地址 |
| `requirements.txt` | 新增 `python-osc>=1.8,<2.0`；`scikit-learn` 固定 `<1.7` 以匹配已训练模型 |

**实测结果（合成 OSC）**：4 通道 / 512 样本窗口正确产出；端口识别 17000、地址 `/17000/eeg`；HTTP 全链路（创建会话 → 校准 → 报告）通过，`n_valid_frames=4`、基线 0.98。

---

## 4. 推荐方案（历史设计，已按 OSC 路线落地）

> 实际落地选择了 **OSC** 而不是 LSL：Xmuse Direct 默认就提供 OSC 输出（127.0.0.1:7000），
> 不需要额外的 `pylsl` 原生库，Windows 部署更简单；LSL 方案保留为后续多模态对齐的备选。

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
├── sources.py        # HardwareSource: 真实 OSC 源；replay/manual 不变
├── features.py       # 不变（band_power 复用）
├── focus_engine.py   # 231 维模型 + 4/6 通道 β/(θ+α) 自动回退
├── xmuse_osc.py      # (新增) 多端口 OSC/UDP 接收器：环形缓冲、2s 出窗
└── server.py         # hardware 会话、osc_* 参数、线程池隔离阻塞接收
scripts/
├── xmuse_osc_probe.py # (新增) 端口/地址探针（先跑它再联调）
└── ...                # collect_xmuse.py / train_xmuse.py 仍为阶段 2 可选
web/
├── dev.html          # 硬件模式 + OSC 端口输入
├── calibrate.html    # 硬件模式 + 端口
└── game.html         # 沿用校准时的硬件模式
```

关键实现点：

1. **环形缓冲**：256 Hz × 2 s = 512 样本/窗；`deque(maxlen=512)`，每累计 0.5 s 产出一次重叠窗口，节奏由设备报文驱动
2. **断连处理**：`next_window()` 超时抛出带诊断的中文错误（已收报文数、最近报文年龄、监听端口）；`describe()` 上报 `connected: false`
3. **通道顺序**：默认 `[TP9, AF7, AF8, TP10, AUX1, AUX2]`；收到首包后按实际通道数截断/补齐
4. **信号质量**：订阅 `*/elements/is_good` 作为 `meta["quality"]`，订阅 `*/batt` 作为 `meta["battery"]`
5. **多端口**：7000/8000 可同时监听；多设备时用 `XMUSE_OSC_PORTS=7000,8000,8001,8002`

---

## 6. 需要厂商确认的事项清单

以下影响方案定型，**建议邮件 `1024@xmuse.cn`（官网）或 `support@xmuse.cn` / `huags@xmuse.cn`（仓库作者）确认**：

| # | 待确认事项 | 为什么重要 | 影响 |
|---|---|---|---|
| 1 | Xmuse Direct 软件是否输出 **brainwaves / 脑波频段功率** 的 OSC 地址？ | 决定是否可省掉自算 PSD | 目前未发现该地址，已按自算 PSD 落地 |
| 2 | OSC 完整地址表（除 eeg / acc / elements 外） | 当前只消费 `/eeg` 与 elements 质量信号 | 已满足专注度需求 |
| 3 | LSL 流名/type 全表（EEG / ACC / GYRO / PPG / elements / brainwaves?） | LSL 为后续备选 | 暂不影响 |
| 4 | Xmuse Direct 连接流程：是否必须蓝牙配对后软件推流？ | 决定产品使用流程 | 当前要求用户开 Direct |
| 5 | 2 个扩展电极的通道名/位置；能否只输出 4 通道 | 模型通道对齐 | 已支持 4/6 通道自适应 |
| 6 | 设备采样率确认（256 Hz?）与数据单位（µV?） | 特征口径一致性 | 默认 256 Hz，可用 `XMUSE_OSC_FS` 覆盖 |
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

1. ~~（0.5 天）采购/借到 Xmuse 设备 + 装 Xmuse Direct，人工验证 OSC/LSL 推流~~ → 已完成端口/协议调研，并实现端口探针
2. ~~（1–2 天）阶段 1：`HardwareSource` + 频带指标，dev 页真机联调~~ → 已改为 OSC 实现并通过合成数据 E2E
3. （按需）阶段 2：采集 + 重训 4 通道模型
4. （按需）阶段 2'：若厂商确认 brainwaves 流，简化实现

---

## 9. 真机联调步骤（Windows）

1. 打开 **Xmuse Direct**，蓝牙连接 Xmuse 设备，确认波形正常。
2. 在 Xmuse Direct 中添加 **OSC 输出**：
   - IP：`127.0.0.1`
   - UDP 端口：`7000`（默认；也可用 8000）
   - 前缀：留空（地址为 `/eeg`）或填端口号（地址为 `/7000/eeg`）
3. 在 `eeg-focus` 目录先跑端口探针，确认真的有报文进来：

   ```powershell
   .\.venv-win\Scripts\python.exe scripts\xmuse_osc_probe.py
   ```

   正常会看到 `packets=... port=7000 address=/7000/eeg channels=4`。
4. 双击 `start.ps1` 启动网页服务（HTTP TCP 8000）。
5. 打开 `http://127.0.0.1:8000/calibrate.html`，信号源选 **Xmuse 脑电波仪（OSC/UDP）**，
   端口填 `7000,8000`，按页面提示完成放松校准，然后进入游戏。
6. 若 7000 被其它软件占用，探针会报绑定失败；用 `XMUSE_OSC_PORTS` 或页面端口框改成空闲端口，
   并在 Xmuse Direct 里填同一个端口。

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
