# 梦境池塘 技术栈

> 项目：`eeg-focus/`（脑波专注游戏 MVP）
> 日期：2026-10-20
> 相关：接入方案见 `docs/xmuse-hardware-integration.md`

---

## 1. 总览

| 层 | 技术 | 版本 | 职责 |
|---|---|---|---|
| 前端 | HTML + CSS + 原生 JavaScript（零构建） | — | 5 个页面 + `assets/api.js` 封装 |
| 服务 | FastAPI | 0.128.8 | REST 接口 + 静态托管 |
| 服务 | uvicorn | 0.39.0 | ASGI 服务器（`127.0.0.1:8000`） |
| 实时通道 | sse-starlette（SSE 事件流） | 3.3.0 | 会话实时数据推送（`EventSourceResponse`） |
| 算法 | numpy | 2.0.2 | 数值/窗口/功率谱计算 |
| 算法 | scipy | 1.13.1 | 滤波（butter/bandpass）、Welch PSD |
| 算法 | scikit-learn | 1.6.1 | 模型（`LogisticRegression`） |
| 算法 | joblib | 1.5.3 | 模型序列化（`*.joblib`） |
| 数据 | pyedflib | 0.1.42 | EDF 脑电文件读取（回放源） |
| 数据 | pandas | 2.3.3 | 训练数据表格处理 |
| 运行 | Python | 3.9.6（venv） | 解释器（`.venv/`） |
| 硬件接入（阶段 1） | pylsl | 待装 | LSL 流订阅（Xmuse 真机数据） |
| 硬件接入（备选） | python-osc | 待装 | OSC 消息接收（Xmuse Direct → UDP） |

---

## 2. 前端：纯原生 Web，零构建

**无 `package.json`、无 npm、无框架、无打包**——这是刻意的产品约束：

- 5 个页面：`index.html`（入口）、`calibrate.html`（校准）、`game.html`（游戏）、`report.html`（报告）、`dev.html`（联调/监视）
- 公共层：`assets/api.js`（REST + SSE 封装，含自愈重连）、`assets/style.css`（梦境池塘视觉）
- 数据通道：浏览器 `EventSource` 消费 SSE；`api.js` 的 `API.stream()` 返回 `{ close(), state }`，带 6s 无数据自愈重连（最多 4 次）与 `onStatus("live"/"reconnecting")` 回调
- 适用人群（儿童）要求低刺激、无安装、秒开 → 原生方案零依赖、零构建开销

---

## 3. 后端：FastAPI + SSE 事件流

- **REST**：`POST /api/session`（创建会话）、`POST /api/calibrate`（校准）、`GET /api/health`、`GET /api/state`
- **实时**：`GET /api/session/{id}/stream` → `EventSourceResponse`，帧结构：
  - 首帧 `hello`（元信息），随后每 0.5 s 一帧 `frame`（`t`、`focus`、`raw` 等）
  - **分隔符为 CRLF `\r\n\r\n`**（uvicorn/sse-starlette 行为，测试脚本必须兼容 `\r?\n\r?\n`）
- 会话模型：`Session` 内存态（`_sessions` 字典），`start()` 内 EDF 加载走线程池（`run_in_executor`）避免阻塞事件循环
- 信号源抽象：`EEGSource.start() + next_window() -> (seg, meta)`，三实现 `ReplaySource / ManualSource / HardwareSource`（硬件为占位，待 Xmuse 接入）

---

## 4. 算法与模型链路

```
原始窗口(2s) → bandpass 0.5–45Hz → Welch PSD
  → 每通道 11 特征（5 频带绝对 + 5 频带相对 + theta/beta 比值）
  → LogisticRegression.predict_proba[:,1] → 平滑 → focus 0..1
```

- 频带：delta 0.5–4 / theta 4–8 / alpha 8–13 / beta 13–30 / gamma 30–45 Hz
- 窗口：2 s；EDF 回放源 21 通道 × 11 = **231 维**特征输入
- 模型：`outputs/models/LogisticRegression.joblib`，训练自 EEGMAT 数据集（PhysioNet）
- **Xmuse 接入约束**：真机仅 4（+2）通道 → 231 维模型不可直接复用；阶段 1 用频带指标（如 β/(θ+α)）替代模型，阶段 2 重训 4 通道模型（44 维）——详见接入方案文档

---

## 5. 硬件接入新增技术栈（Xmuse）

| 阶段 | 依赖 | 用途 | 出处 |
|---|---|---|---|
| 阶段 1 | `pylsl` | `resolve_byprop("type","EEG")` 订阅真机 EEG 流 | 官方 `LSL-singal device.py` |
| 阶段 2' | `python-osc` | UDP 监听 Xmuse Direct 推流（`{prefix}/...`） | 官方 `OSC_client`、Greedy-Snake |
| 阶段 2 | （沿用现有 numpy/scipy/sklearn） | 4 通道数据采集 + 重训模型 | `scripts/` 新增脚本 |

选型理由：官方 SDK 原生支持 LSL 与 OSC 两条管道（LSL 是科研标准，带统一时间戳，优先）；OSC 为游戏对接常用路径，作为备选与厂商确认项（brainwaves 地址待确认）。

---

## 6. 数据流

```
[Xmuse 设备] --蓝牙--> [Xmuse Direct] --LSL/OSC--> [xmuse_source.py]
        [EDF 文件] ---------------------------> [ReplaySource]
        [滑块输入] ---------------------------> [ManualSource]
                            ↓
                sources.next_window() → (seg, meta)
                            ↓
        features.prepare_signal → window_to_features → model/focus
                            ↓
        Session._run → SSE (EventSourceResponse) → EventSource(前端)
                            ↓
        dev/game 页面按帧渲染 focus
```

---

## 7. 版本管理现状与整改建议

**现状问题**：`requirements.txt` 只记录了 5 个算法依赖，**缺少服务运行依赖**（`fastapi`、`uvicorn`、`sse-starlette`、`joblib`、`pydantic`）——新环境无法一键复现服务。建议：

```bash
/Users/fan/脑机/eeg-focus/.venv/bin/pip freeze > /Users/fan/脑机/eeg-focus/requirements.lock.txt
```

并把缺失项补进 `requirements.txt`（或改用 lock 文件交付）。Python 3.9.6 为系统自带版本（macOS），若需升级可另建 `python3.11` venv。

---

## 8. 选型原则（约束清单）

1. **零构建**：前端无 npm/打包，打开即用
2. **纯本地**：无外部 AI 服务、无云依赖（MVP 阶段无 AI）
3. **儿童友好**：低刺激视觉、无账号、数据不出本机
4. **可复现**：依赖收敛到 venv + requirements（待补全）
5. **接入可逆**：`hardware` 源失败时回退 `replay`/`manual`，SSE 帧结构不变
