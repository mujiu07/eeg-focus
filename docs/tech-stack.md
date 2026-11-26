# 专注小蛙 · 梦境池塘 — 技术栈

> 项目：`eeg-focus/`（脑波专注游戏 MVP）
> 版本：v1.4.17（2026-11-19）
> 相关：接入方案与排障见 `docs/xmuse-hardware-integration.md`；架构见 `docs/ARCHITECTURE.md`

---

## 1. 总览

| 层 | 技术 | 声明版本（`requirements.txt`） | 职责 |
|---|---|---|---|
| 前端 | HTML + CSS + 原生 JavaScript（零构建） | — | 5 个页面 + `assets/` 公共层与成长系统 |
| 服务 | FastAPI | `>=0.115,<1.0` | REST 接口 + 静态托管 |
| 服务 | uvicorn | `>=0.30,<1.0` | ASGI 服务器（`127.0.0.1:8000`） |
| 实时通道 | sse-starlette | `>=2.1,<4.0` | 会话实时数据推送（`EventSourceResponse`） |
| 算法 | numpy | `>=2.0` | 数值/窗口/功率谱计算 |
| 算法 | scipy | `>=1.13` | 滤波（butter/bandpass/iirnotch）、Welch PSD、伪迹修复 |
| 算法 | scikit-learn | `>=1.6,<1.7` | 模型（`LogisticRegression`） |
| 算法 | joblib | `>=1.4` | 模型序列化（`*.joblib`） |
| 数据 | pandas | `>=2.2` | 训练数据表格处理 |
| 数据 | pyedflib / edfio | `>=0.1.42`（<3.13） / `>=0.4`（≥3.13） | EDF 脑电文件读取 |
| 硬件接入 | python-osc | `>=1.8,<2.0` | Xmuse OSC/UDP 多端口接收（`app/xmuse_osc.py`） |
| 报告导出 | reportlab / openpyxl / python-docx | `>=4.2` / `>=3.1` / `>=1.1` | PDF / Excel / Word 导出（`app/export.py`） |
| 音乐（可选） | urllib（标准库） | — | 网易云歌单/直链代理（`app/music.py`） |
| 心率（可选） | subprocess + 标准库 | — | `hrd` 读取 AirPods Pro 3 心率（`app/heart.py`，仅 macOS） |
| 运行 | Python | 3.10+ | 解释器（`.venv/`、`.venv-win/`） |

> 上表是仓库声明的依赖范围；实际安装版本由 `pip` 解析。若复现模型推理，优先在干净 venv 中按 `requirements.txt` 安装，避免 `scikit-learn` 跨次版本导致的模型兼容问题。

---

## 2. 前端：纯原生 Web，零构建

**无 `package.json`、无 npm、无框架、无打包**——这是刻意的产品约束：

- 5 个页面：`index.html`（首页）、`calibrate.html`（校准）、`game.html`（游戏）、`report.html`（报告）、`dev.html`（联调/监视）
- 游戏核心逻辑：
  - `assets/focus-round.js`：不依赖 DOM 的单轮状态机（蓄力 → 宽容期/衰减 → 唯一金色区域 → 子弹时间 → 潜在得分/点击结算），参数集中在 `CONFIG`，浏览器与 Node 测试共用
- 视觉与环境层：
  - `assets/style.css`：梦境池塘视觉与通用组件
  - `assets/sky.css` + `assets/sky.js`：全站天空模式（黎明/白天/傍晚/黑夜/跟随系统时间），按日出日落估算自动切换，`localStorage` 跨页保存；模式切换走 1.2 s 颜色渐变；`sky.js` 导出 `window.SkyTheme` 色板，首页 SVG 与游戏 Canvas 共用同一套天空 / 水面 / 远山 / 日月星配色
  - `assets/hero-pond.js`、`hero-water.js`、`pond-effects.js`、`pond-audio.js`：首页动态池塘（青蛙跳跃、荷叶弹簧、水花、鱼群、环境音效），游戏落地水花与转场卡片复用 `PondEffects`
  - `assets/music.js` + `assets/vinyl.css`：黑胶唱片机，结构由脚本注入，跨页保留曲目与进度
- 成长系统（全部本地 `localStorage`，无服务端）：
  - `achievements.js` + `achievements.css` + `achievement-cinematic.js/.css`：15 枚成就、解锁动画与待播队列
  - `wallet.js`：积分钱包（表现分按 30:1 折算，一局结束一次性入账）
  - `checkin.js` + `checkin.css`：每日签到（+2 积分，0 点刷新）
  - `shop.js` + `shop.css`：积分商城（装扮 5–18 积分）
  - `dressup.js` + `dressup.css`：图鉴 / 装扮 / 商城三页，肤色、头饰、面饰、手持等自由搭配，同一类别同时只穿一件
- 数据通道：浏览器 `EventSource` 消费 SSE；`assets/api.js` 封装 REST + SSE，含 6 s 无数据自愈重连（最多 4 次）与 `onStatus("live"/"reconnecting")`

适用人群（儿童）要求低刺激、无安装、秒开 → 原生方案零依赖、零构建开销。

---

## 3. 后端：FastAPI + SSE 事件流

- **REST**（完整列表见 `docs/ARCHITECTURE.md` §5）：
  - 会话：`POST /api/session`、`/manual`、`/calibrate`、`/finish`
  - 报告：`GET /api/report/{id}`、`GET|POST /api/report/{id}/export/{fmt}`
  - 平台：`GET /api/health`、`/api/env`、`/api/heart/status`、`POST /api/heart/start|stop`
  - 回放：`GET /api/player/replay`、`/api/player/recent`
  - 开发：`GET /api/dev/info`、`/api/dev/current`、`POST /api/dev/source`
  - 音乐：`GET /api/music/playlist`、`/api/music/url/{track_id}`
- **实时**：`GET /api/session/{id}/stream` → `EventSourceResponse`，帧结构：
  - 首帧 `hello`（元信息），随后每 0.5 s 一帧 `frame`（`t`、`focus`、`raw`、`focus_fused`、`score` 等）
  - **分隔符为 CRLF `\r\n\r\n`**（uvicorn/sse-starlette 行为，测试脚本必须兼容 `\r?\n\r?\n`）
- 会话模型：`Session` 内存态（`_sessions` 字典），`start()` 内 EDF 加载走线程池（`run_in_executor`）避免阻塞事件循环
- 信号源抽象：`EEGSource.start() + next_window() -> (seg, meta) + stop()`，四实现：
  - `EDFReplaySource`（循环回放；支持本机配对文件夹）
  - `ManualSource`（滑块）
  - `HardwareSource` → `XmuseOSCSource`（真机 OSC/UDP）
  - `HeartSource`（仅心率；无脑电时也能玩）
- **硬件/心率会话互斥**：创建新的硬件会话会自动结束旧的未完成硬件会话，避免 UDP 7000/8000 端口争抢；会话结束调用 `stop()` 释放端口与采集进程
- 静态资源：非 `/api/` 响应统一 `Cache-Control: no-cache`，开发时刷新即生效

---

## 4. 算法与模型链路

```
原始窗口(2s) → bandpass 0.5–45Hz → Welch PSD
  → 每通道 11 特征（5 频带绝对 + 5 频带相对 + theta/beta 比值）
  → LogisticRegression.predict_proba[:,1] → EMA 平滑 → focus 0..1
```

- 频带：delta 0.5–4 / theta 4–8 / alpha 8–13 / beta 13–30 / gamma 30–45 Hz
- 窗口：2 s；EDF 回放源 21 通道 × 11 = **231 维**特征输入
- 模型：`outputs/models/LogisticRegression.joblib`，训练自 EEGMAT 数据集（PhysioNet，36 名被试、4338 个 2 s 窗口）
- 团队自述指标（LOSO 按被试划分）：准确率 0.729 / 平衡准确率 0.640 / ROC-AUC 0.731；逐被试结果波动较大，不能当作临床指标
- **通道数自适应**（`app/focus_engine.py`）：
  - 输入维度与模型 `n_features_in_` 一致 → 走模型推理
  - 不一致（如 Xmuse 4/6 通道）或推理抛 `ValueError` → 自动回退频段指标
  - 回退公式：相对频段功率比 `beta / (theta + alpha)`，经 `sigmoid(2.5 × (ratio − 0.70))` 映射到 0..1，再做 EMA 平滑
  - `FocusEngine.describe()` 通过 `active_mode`（`model` / `band`）对外暴露当前模式，开发者页可见
- **心率融合**（`app/heart.py`，仅 macOS）：
  - 心率为独立 2 s 帧，`hrd` 真实数据 10–20 s 才更新一次，只在数值变化或可用时参与
  - 以校准静息心率为基准，跨度取校准得到的"静息→任务"差值（默认 12 BPM，可设 6–80）；目标为静息之上约 45% 跨度，做高斯倒 U 评分（适度激活得分最高），波动与持续下滑扣分
  - 仅心率模式把目标设为静息本身（`target_delta=0`），不依赖脑电
  - 融合权重默认 0.15（`heart_weight` 0–0.5 可调），心率缺失/过期自动退回纯 EEG
- **去噪与去伪迹**（`app/denoise.py`，v1.4.16 起，仅 `hardware` 源）：
  - 每 2 s 窗口：去线性趋势 → 50 Hz 零相位陷波（Q=30）→ 眨眼 / 削顶 / 肌电 / 坏道 / 设备质量检测 → 修复 → 0–1 质量评分
  - 眨眼：1–8 Hz 定边界 + **原始幅值**确认（默认 80 µV），`0.5–8 Hz` 分量迭代 2 次减除；实测峰值 196→61 µV，alpha −5.5%、beta −0.1%
  - 削顶：单段 ≤0.3 s 线性插值；坏道：掩码排除（不插值、不置零参与平均）
  - 跨窗：拼接上一窗尾部 0.5 s，避免压在窗口边界的眨眼被切半漏检
  - 运动伪迹：DC 台阶用 sigmoid 跃变基线减除（去趋势前，否则会被藏进低频）；全通道共模减 80%；0.5–3 Hz 慢摆与 θ 重叠，只识别不修复，直接拒绝出分
  - 单位自适应：`median(|x|) > 500` 判为 ADC 计数，绝对阈值改按稳健标准差倍数
  - **不做 0.5–45 Hz 带通**：带通仍由 `features.prepare_signal` 完成，模型口径不变、无需重训
  - 阈值全部可用 `EEG_*` 环境变量覆盖，流程与证据见 `docs/denoise-artifacts.md`
- 语义边界：频段指标只保证游戏内"相对变化"可校准，**不是临床注意力分数**

---

## 5. 硬件接入：Xmuse OSC/UDP（已实现）

| 项 | 实现 |
|---|---|
| 传输 | UDP + OSC（`python-osc` 的 `ThreadingOSCUDPServer` + 默认 handler） |
| 默认端口 | `7000`（Xmuse Direct 默认）、`8000`（官方示例默认），可多端口同时监听 |
| 地址匹配 | 最后一个路径段为 `eeg` 且不含 `/elements/`，兼容 `/eeg`、`/8000/eeg`、`/muse/eeg` |
| 窗口 | 2 s 环形缓冲，步长 0.5 s（与训练口径一致） |
| 采样率 | OSC 报文不带采样率，默认按 256 Hz（`XMUSE_OSC_FS` 可覆盖） |
| 通道 | 4/6 通道自动推断，名称 `TP9/AF7/AF8/TP10/AUX1/AUX2`；`XMUSE_OSC_CHANNELS` 可固定 |
| 元数据 | 同时接收 `/elements/is_good`（质量）、`/batt`（电量），`describe()` 上报 packets/samples/年龄/连接状态 |
| 配置 | `XMUSE_OSC_HOST` / `XMUSE_OSC_PORTS` / `XMUSE_OSC_FS` / `XMUSE_OSC_CHANNELS`，或页面/接口参数 |
| 探针 | `scripts/xmuse_osc_probe.py`（抓包确认地址与端口） |

LSL 管道（阶段 1 原方案）暂未落地，当前采用 OSC/UDP；若后续需要科研级时间戳可再补 LSL 订阅。

---

## 6. 报告导出（`app/export.py`，v1.4.7 起）

| 格式 | 生成 | 内容 |
|---|---|---|
| PDF | reportlab | A4 排版 + 概览 + 专注曲线；优先嵌入系统中文字体（Windows 微软雅黑/黑体、macOS PingFang、Linux Noto CJK），兜底 `STSong-Light` |
| XLSX | openpyxl | 概览表 + 逐点曲线 + 起跳事件 + 折线图 |
| DOCX | python-docx | 概览表 + 给家长的话 |
| CSV / JSON | 标准库 | 逐点数据 / 原始报告 |

- 导出完全在本机服务完成，不经过第三方或云端；浏览器直接下载到默认目录，不额外写 `outputs/`
- 依赖缺失时只有对应格式不可用，报告页其余功能不受影响

---

## 7. 背景音乐代理（可选，`app/music.py`）

- 浏览器无法直接播放网易云歌单（需签名、版权校验与登录态），由服务端代取
- 曲目列表：登录时 `/api/playlist/track/all` 取全量；未登录回退 `/api/v6/playlist/detail`（前 10 首）
- 播放直链：`/api/song/enhance/player/url`，进程内缓存 8 分钟（网易直链约 20 分钟过期）
- 可播放性探测：并发（≤6）逐首取直链，过滤版权受限/下架曲目，保持歌单原顺序
- 登录态：`NCM_COOKIE` 环境变量或 `data/music_cookie.txt`；歌单 ID 用 `NCM_PLAYLIST_ID` 覆盖
- 依赖：仅标准库 `urllib`，不新增第三方包
- 安全：cookie 文件与 `*.cookie`、`.env` 均在 `.gitignore` 中

---

## 8. 数据流

```
[Xmuse 设备] --蓝牙--> [Xmuse Direct] --OSC/UDP 127.0.0.1:7000/8000--> [xmuse_osc.py]
        [EDF 文件] ---------------------------> [EDFReplaySource]
        [滑块输入] ---------------------------> [ManualSource]
        [AirPods Pro 3] --hrd--> [heart.py] --> 心率分量（仅 macOS）
                            ↓
                sources.next_window() → (seg, meta)
                            ↓
        [hardware] denoise.clean_window → 清洗信号 + artifact 质量报告
                            ↓
        features.prepare_signal → window_to_features → 模型 / 频段回退
                            ↓
        Session._run → SSE (EventSourceResponse) → EventSource(前端)
                            ↓
        dev/game 页面按帧渲染 focus；finish 后报告落盘，report 页导出

[浏览器 music.js] --/api/music/*--> [app/music.py] --HTTPS--> music.163.com
        （仅背景音乐走公网，不携带脑电数据）
```

---

## 9. 版本与依赖管理

- `requirements.txt` 已包含服务运行依赖与硬件依赖 `python-osc`；报告导出依赖 `reportlab` / `openpyxl` / `python-docx`
- `scikit-learn` 锁定 `<1.7`，避免模型序列化/推理行为在次版本间漂移
- EDF 读取：Python 3.13+ 无 pyedflib 预编译轮子，`app/sources.py` 自动回退 `edfio`
- Windows 使用 `start.ps1` 创建 `.venv-win`；macOS/Linux 使用 `.venv`
- 启动脚本（`start.command` / `start.bat`）会在首次运行时建环境、装依赖，之后直接启动；已在运行时只打开页面

如需完全可复现的锁定版本，可在目标环境执行：

```bash
.venv/bin/pip freeze > requirements.lock.txt
```

---

## 10. 选型原则（约束清单）

1. **零构建**：前端无 npm/打包，打开即用
2. **脑电本地**：无外部 AI 服务、脑电数据不出本机；仅可选背景音乐联网
3. **儿童友好**：低刺激视觉、无账号、数据不出本机
4. **成长系统可离线**：积分/签到/商城/装扮/成就全部 localStorage，断网可用；清缓存即重置（隐私说明已明示）
5. **可复现**：依赖收敛到 venv + requirements；模型指标可追溯到 `outputs/train_report.md`
6. **接入可逆**：`hardware` / `heart` 源失败时回退 `replay` / `manual`，SSE 帧结构与报告格式不变；通道不匹配时算法自动回退频段指标
