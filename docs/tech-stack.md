# 梦境池塘 技术栈

> 项目：`eeg-focus/`（脑波专注游戏 MVP）
> 日期：2026-11-12
> 相关：接入方案与排障见 `docs/xmuse-hardware-integration.md`

---

## 1. 总览

| 层 | 技术 | 版本 | 职责 |
|---|---|---|---|
| 前端 | HTML + CSS + 原生 JavaScript（零构建） | — | 5 个页面 + `assets/` 公共层 |
| 服务 | FastAPI | 0.128.8 | REST 接口 + 静态托管 |
| 服务 | uvicorn | 0.39.0 | ASGI 服务器（`127.0.0.1:8000`） |
| 实时通道 | sse-starlette（SSE 事件流） | 3.3.0 | 会话实时数据推送（`EventSourceResponse`） |
| 算法 | numpy | 2.0.2 | 数值/窗口/功率谱计算 |
| 算法 | scipy | 1.13.1 | 滤波（butter/bandpass）、Welch PSD |
| 算法 | scikit-learn | ≥1.6,<1.7 | 模型（`LogisticRegression`） |
| 算法 | joblib | 1.5.3 | 模型序列化（`*.joblib`） |
| 数据 | pyedflib / edfio | 0.1.42 / — | EDF 脑电文件读取（回放源；3.13+ 自动用 edfio） |
| 数据 | pandas | 2.3.3 | 训练数据表格处理 |
| 硬件接入 | python-osc | ≥1.8,<2.0 | Xmuse OSC/UDP 多端口接收（`app/xmuse_osc.py`） |
| 音乐（可选） | urllib（标准库） | — | 网易云歌单/直链代理（`app/music.py`） |
| 运行 | Python | 3.10+ | 解释器（`.venv/`、`.venv-win/`） |

---

## 2. 前端：纯原生 Web，零构建

**无 `package.json`、无 npm、无框架、无打包**——这是刻意的产品约束：

- 5 个页面：`index.html`（入口）、`calibrate.html`（校准）、`game.html`（游戏）、`report.html`（报告）、`dev.html`（联调/监视）
- 公共层：
  - `assets/api.js`：REST + SSE 封装，含 6s 无数据自愈重连（最多 4 次）与 `onStatus("live"/"reconnecting")`
  - `assets/style.css`：梦境池塘视觉与通用组件
  - `assets/sky.css` + `assets/sky.js`：全站天空模式（黎明/白天/傍晚/黑夜/跟随系统时间），按日出日落估算自动切换，`localStorage` 跨页保存
  - `assets/music.js` + `assets/vinyl.css`：黑胶唱片机播放器，结构由脚本注入，跨页保留曲目与进度
  - `assets/hero-pond.js`：首页动态池塘（青蛙跳跃、荷叶弹簧、水花、鱼群）
- 数据通道：浏览器 `EventSource` 消费 SSE
- 适用人群（儿童）要求低刺激、无安装、秒开 → 原生方案零依赖、零构建开销

---

## 3. 后端：FastAPI + SSE 事件流

- **REST**：
  - `POST /api/session`（创建会话，支持基线/OSC 参数）
  - `POST /api/session/{id}/calibrate`、`POST /api/session/{id}/manual`、`POST /api/session/{id}/finish`
  - `GET /api/report/{id}`、`GET /api/health`、`GET /api/dev/info`、`GET /api/dev/current`、`POST /api/dev/source`
  - `GET /api/music/playlist`、`GET /api/music/url/{track_id}`
- **实时**：`GET /api/session/{id}/stream` → `EventSourceResponse`，帧结构：
  - 首帧 `hello`（元信息），随后每 0.5 s 一帧 `frame`（`t`、`focus`、`raw` 等）
  - **分隔符为 CRLF `\r\n\r\n`**（uvicorn/sse-starlette 行为，测试脚本必须兼容 `\r?\n\r?\n`）
- 会话模型：`Session` 内存态（`_sessions` 字典），`start()` 内 EDF 加载走线程池（`run_in_executor`）避免阻塞事件循环
- 信号源抽象：`EEGSource.start() + next_window() -> (seg, meta) + stop()`，三实现：
  - `EDFReplaySource`（循环回放）
  - `ManualSource`（滑块）
  - `HardwareSource` → `XmuseOSCSource`（真机 OSC/UDP）
- **硬件会话互斥**：创建新的 hardware 会话时会自动结束旧的未完成硬件会话，避免 UDP 7000/8000 端口争抢；会话结束调用 `stop()` 释放端口
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
- 模型：`outputs/models/LogisticRegression.joblib`，训练自 EEGMAT 数据集（PhysioNet）
- **通道数自适应**（`app/focus_engine.py`）：
  - 输入维度与模型 `n_features_in_` 一致 → 走模型推理
  - 不一致（如 Xmuse 4/6 通道）或推理抛 `ValueError` → 自动回退频段指标
  - 回退公式：相对频段功率比 `beta / (theta + alpha)`，经 `sigmoid(2.5 × (ratio − 0.70))` 映射到 0..1，再做 EMA 平滑
  - `FocusEngine.describe()` 通过 `active_mode`（`model` / `band`）对外暴露当前模式，开发者页可见
- 语义边界：频段指标只保证游戏内"相对变化"可校准，**不是临床注意力分数**

---

## 5. 硬件接入：Xmuse OSC/UDP（已实现）

| 项 | 实现 |
|---|---|
| 传输 | UDP + OSC（`python-osc` 的 `ThreadingOSCUDPServer` + 默认 handler） |
| 默认端口 | `7000`（Xmuse Direct 默认）、`8000`（官方示例默认），可多端口同时监听 |
| 地址匹配 | 最后一个路径段为 `eeg` 且不含 `/elements/`，兼容 `/eeg`、`/8000/eeg`、`/muse/eeg` |
| 窗口 | 2 s 环形缓冲，步长 0.5 s（与 `features.py` 训练口径一致） |
| 采样率 | OSC 报文不带采样率，默认按 256 Hz（`XMUSE_OSC_FS` 可覆盖） |
| 通道 | 4/6 通道自动推断，名称 `TP9/AF7/AF8/TP10/AUX1/AUX2`；`XMUSE_OSC_CHANNELS` 可固定 |
| 元数据 | 同时接收 `/elements/is_good`（质量）、`/batt`（电量），`describe()` 上报 packets/samples/年龄/连接状态 |
| 配置 | `XMUSE_OSC_HOST` / `XMUSE_OSC_PORTS` / `XMUSE_OSC_FS` / `XMUSE_OSC_CHANNELS`，或页面/接口参数 |
| 探针 | `scripts/xmuse_osc_probe.py`（抓包确认地址与端口） |

LSL 管道（阶段 1 原方案）暂未落地，当前采用 OSC/UDP；若后续需要科研级时间戳可再补 LSL 订阅。

---

## 6. 背景音乐代理（可选，`app/music.py`）

- 浏览器无法直接播放网易云歌单（需签名、版权校验与登录态），由服务端代取
- 曲目列表：登录时 `/api/playlist/track/all` 取全量；未登录回退 `/api/v6/playlist/detail`（前 10 首）
- 播放直链：`/api/song/enhance/player/url`，进程内缓存 8 分钟（网易直链约 20 分钟过期）
- 可播放性探测：并发（≤6）逐首取直链，过滤版权受限/下架曲目，保持歌单原顺序
- 登录态：`NCM_COOKIE` 环境变量或 `data/music_cookie.txt`；歌单 ID 用 `NCM_PLAYLIST_ID` 覆盖
- 依赖：仅标准库 `urllib`，不新增第三方包
- 安全：cookie 文件与 `*.cookie`、`.env` 均在 `.gitignore` 中

---

## 7. 数据流

```
[Xmuse 设备] --蓝牙--> [Xmuse Direct] --OSC/UDP 127.0.0.1:7000/8000--> [xmuse_osc.py]
        [EDF 文件] ---------------------------> [EDFReplaySource]
        [滑块输入] ---------------------------> [ManualSource]
                            ↓
                sources.next_window() → (seg, meta)
                            ↓
        features.prepare_signal → window_to_features → 模型 / 频段回退
                            ↓
        Session._run → SSE (EventSourceResponse) → EventSource(前端)
                            ↓
        dev/game 页面按帧渲染 focus；finish 后报告落盘

[浏览器 music.js] --/api/music/*--> [app/music.py] --HTTPS--> music.163.com
        （仅背景音乐走公网，不携带脑电数据）
```

---

## 8. 版本与依赖管理

`requirements.txt` 已包含服务运行依赖（fastapi、uvicorn、sse-starlette、joblib、pydantic）与硬件依赖 `python-osc`，新环境可一键安装。

- `scikit-learn` 锁定 `<1.7`，避免模型序列化/推理行为在次版本间漂移
- EDF 读取：Python 3.13+ 无 pyedflib 预编译轮子，`app/sources.py` 自动回退 `edfio`
- Windows 使用 `start.ps1` 创建 `.venv-win`；macOS/Linux 使用 `.venv`

如需完全可复现的锁定版本，可在目标环境执行：

```bash
.venv/bin/pip freeze > requirements.lock.txt
```

---

## 9. 选型原则（约束清单）

1. **零构建**：前端无 npm/打包，打开即用
2. **脑电本地**：无外部 AI 服务、脑电数据不出本机；仅可选背景音乐联网
3. **儿童友好**：低刺激视觉、无账号、数据不出本机
4. **可复现**：依赖收敛到 venv + requirements
5. **接入可逆**：`hardware` 源失败时回退 `replay`/`manual`，SSE 帧结构不变；通道不匹配时算法自动回退频段指标
