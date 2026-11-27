# 专注小蛙 · 梦境池塘 — 架构设计

> 版本：v1.8.1（2026-11-27）
> 适用代码：`eeg-focus/`（`app/` + `web/`）
> 定位：本地运行的脑电专注游戏 MVP，教学演示用途，不构成注意力评估或医疗诊断。

## 1. 架构总览

```
┌──────────────────────────────────────────────────────────────┐
│ web/（浏览器，零构建：原生 HTML/CSS/JS + Canvas）              │
│  index.html      首页：池塘、天空、当前档案、签到/成就/商城入口   │
│  profiles.html   档案：今天谁来陪小蛙玩？新建/选择/编辑/迁移      │
│  settings.html   设置：数据目录、备份恢复、隐私与存储状态         │
│  calibrate.html  校准：档案 gate、信号源、心率辅助、安静+心算期   │
│  game.html       游戏：档案 gate、3D 感池塘、蓄力→起跳、结算      │
│  report.html     报告：归属读取、曲线回放、PDF/Excel/Word 导出    │
│  dev.html        开发者：无设备试玩、EDF 回放验证、OSC 监视      │
│  assets/  api.js · sky.js/css · music.js + vinyl.css            │
│           eeg-monitor.js/css（开发者三栏监测）                   │
│           hero-pond/hero-water/pond-effects/pond-audio           │
│           achievements(+-cinematic) · dressup · shop · checkin   │
│           wallet · style.css                                     │
└───────────────┬──────────────────────────────────────────────┘
                │ REST / SSE（仅 127.0.0.1 回环）
┌───────────────┴──────────────────────────────────────────────┐
│ app/（FastAPI 后端）                                          │
│  server.py      会话 / 校准 / 报告 / 导出 / 音乐 / 静态托管      │
│  storage.py     SQLite、数据目录、档案/校准/游戏/资产/备份/迁移  │
│  accounts.py    档案与存储 API（bootstrap/sync/backup/location）  │
│  sources.py     信号源：replay · manual · hardware · heart       │
│  xmuse_osc.py   Xmuse OSC/UDP 多端口接收（2 s 出窗）            │
│  focus_engine.py 231 维模型推理 + 4/6 通道频段回退 + EMA        │
│  denoise.py     去噪/去伪迹（硬件源）                            │
│  monitor.py     开发者监测批次序列化（不重复滤波）              │
│  heart.py       心率信号源（hrd/mock/csv）与 EEG 融合            │
│  export.py      报告导出：PDF / Excel / Word / CSV / JSON        │
│  music.py       网易云歌单代理（可选背景音乐）                   │
└───────────────┬──────────────────────────────────────────────┘
                │ 读取
┌───────────────┴──────────────────────────────────────────────┐
│ outputs/models/LogisticRegression.joblib                     │
│   ← scripts/preprocess.py ← scripts/train.py                  │
│   ← data/eegmat/（PhysioNet EEGMAT，36 名被试真实脑电）         │
│ ~/Documents/专注小蛙/（或平台文档目录；可用 FOCUS_FROG_DATA_DIR 覆盖）│
│  profiles.db · settings.json · reports/ · recordings/ · backups/ │
│ outputs/sessions/*.json（仅兼容读取旧报告，新报告不再写入）       │
└──────────────────────────────────────────────────────────────┘
```

## 2. 数据流（专注 → 行动 → 即时反馈）

```
EDF 回放窗口 (2 s × 21 通道)
  → 带通 0.5–45 Hz → 每通道 11 特征（5 绝对功率 + 5 相对功率 + θ/β）
  → LogisticRegression.predict_proba → 专注概率 p
  → EMA 平滑 (α=0.35) → focus 0..1

Xmuse 真机窗口 (2 s × 4/6 通道)
  → 去噪去伪迹（denoise.py：共模/台阶 → 去趋势 → 50 Hz 陷波 → 眨眼/削顶/肌电/坏道 → 慢摆判定 → 质量评分）
  → 伪迹过重（usable=false）→ 该帧不出分，标 reason="artifact"
  → 维度与模型不匹配 → 相对频段功率 β/(θ+α)
  → sigmoid 映射 0..1 → 同一套 EMA 平滑与基线逻辑

心率辅助（仅 macOS，可选）
  → AirPods Pro 3 → hrd → BPM
  → 以校准静息心率与跨度为基准做倒 U 评分：适度激活得分最高，纯心率模式以静息为目标
  → 波动与持续下滑扣分；按权重（默认 0.15）与 EEG focus 融合；心率失效自动退回纯 EEG

仅心率模式
  → 无脑电信号，focus 完全由心率分量驱动（倒 U 峰值在静息；偏离静息或波动变大都会降分）

统一出口
  → 个人基线定标为 20–80 动态分，45/38 分滞回判专注 → 专注时蓄力增长
  → 低于蓄力零点先进入 1.5 s 宽容期，超过后按基准速度 30% 缓慢衰减
  → 每轮唯一金色区域；进入即锁定脑电基础分 B 并触发 2.5 s 子弹时间
  → 前 0.6 s 点击满分，之后最多折损 10%，超过窗口为 0；非金区点击触发 0.5 s 蓄力冷却
  → 本局累计积分 = Σ实际得分 S；商城积分 = max(1, floor(本局积分/30))
  → 前端 rAF 渲染；游戏 SSE 0.5 s/帧；结束后报告落盘
```

### 2.1 v1.7 开发者监测支路

```
Xmuse OSC 窗 / EDF 窗
  → sources.py 在软件处理前复制原始窗 + 样本序号/时间（硬件）
  → ArtifactCleaner（硬件）→ FocusEngine 实际带通与特征
  → FocusEngine.last_debug 保存同一批 processed/powers/relative/ratio
  → Session._publish_monitor 仅在 /monitor 有订阅者时序列化
  → 独立 SSE /api/session/{id}/monitor（不阻塞游戏 SSE）
  → eeg-monitor.js Canvas 环形缓存（有限窗口）
```

- 原始/处理后数组共享采样序号；硬件时间由报文到达时间与配置采样率重建，EDF 用文件内时间；
- 监测客户端不重新执行特征提取，不使用随机/正弦曲线替代脑电；
- 儿童模式不创建 `EEGMonitor`，因此不会订阅该端点；
- 批次只保存在内存有限队列，默认不落盘。

## 3. 前端本地状态（不上传、不联网）

v1.8.1 起，个人档案、校准、游戏/逐轮记录、钱包、装扮、成就和用户设置以本机 SQLite 为主存储；浏览器 `localStorage` 仅作为当前档案缓存与旧版兼容层，没有联网账号体系：

| 键 | 内容 | 写入方 |
|---|---|---|
| `bf-calib` | 校准基线缓存（含时间戳，1 小时有效） | calibrate |
| `bf-sky-mode` | 天空模式（黎明/白天/傍晚/黑夜/跟随系统） | sky.js |
| `bf-music-*` | 播放状态、曲目、音量 | music.js |
| `bf-wallet` | 积分余额、局数、累计入账、消费 | wallet.js |
| `bf-checkin` | 每日签到日期（每天 +2 积分，0 点刷新） | checkin.js |
| `bf-achievements` | 15 枚成就的进度与解锁时间 | achievements.js |
| `bf-owned` / `bf-owned-at` / `bf-outfit` | 已拥有装扮、获得时间、当前穿戴 | dressup/shop |
| `bf-heart*` | 心率开关、静息心率、融合权重 | calibrate/game |

## 4. 校准（P0）

- 默认 40 秒：前 20 秒安静放松，后 20 秒心算任务（可跟随 60 秒引导视频，最长 600 秒）
- 基线 = 校准期专注指数中位数（P50），同时记录 P10/P90 与有效帧数
- 每日校准写入 `calibrations`（按 `user_id`、日期、来源、算法版本追加，不覆盖历史）；前端缓存 `bf-calib-*` 仍用于快速恢复，但服务端记录是权威历史。`reference_baselines` 为长期参考基线预留，本阶段不计算
- 校准失败（无有效帧 / 信号中断）会给出明确提示，不会写入伪基线

## 5. API 一览（v1.7.0）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查 + 模型名 |
| GET | `/api/env` | 平台能力（心率是否可用及原因） |
| GET | `/api/heart/status` | 心率采集状态 |
| POST | `/api/heart/start` | 启动心率（`mock` / `hrd` / `csv`） |
| POST | `/api/heart/stop` | 停止心率采集 |
| GET | `/api/player/replay` | 本机配对 EDF 回放列表（无设备试玩） |
| GET | `/api/player/recent` | 最近一局的可回放报告摘要 |
| GET | `/api/dev/info` | 引擎信息、训练报告、EDF 文件列表、会话 |
| GET | `/api/dev/current` | 当前信号源配置与最近会话 |
| POST | `/api/dev/source` | 切换全局默认信号源（含 OSC 参数） |
| POST | `/api/session` | 创建会话 `{mode, file, baseline, osc_*, heart_*}` |
| GET | `/api/session/{id}/stream` | 游戏分数 SSE（hello / frame / end） |
| GET | `/api/session/{id}/monitor` | 开发者高频监测 SSE（hello / monitor / unavailable / end） |
| POST | `/api/session/{id}/manual` | 手动模式设置专注度 |
| POST | `/api/session/{id}/calibrate` | 采样并建立基线 |
| POST | `/api/session/{id}/finish` | 结束会话，生成报告 |
| GET | `/api/report/{id}` | 读取报告（内存/磁盘） |
| GET/POST | `/api/report/{id}/export/{fmt}` | 导出 `pdf` / `xlsx` / `docx` / `csv` / `json` |
| GET | `/api/music/playlist` | 背景音乐歌单（网易云代理） |
| GET | `/api/music/url/{track_id}` | 单曲播放直链（服务端缓存） |

> v1.4.16 起，`hardware` 会话的 SSE `frame` 新增可选字段 `artifact`（信号质量报告，字段见 `docs/denoise-artifacts.md` §5）；
> `valid=false, reason="artifact"` 表示该窗伪迹过重、不出分且不入 history；`/calibrate` 与 `finish` 的结果新增 `signal_quality`。

## 6. 会话与并发模型

- `_sessions: dict` 全局会话表；每会话独立信号源 + 专注引擎实例（引擎状态重置，避免跨被试污染）
- 后台 asyncio 任务按 0.5 s 步长推进信号源 → 计算 focus → 写入队列（容量 1，丢弃旧帧）+ 历史列表
- SSE 端点从队列取帧；校准端点按时间窗口从历史列表聚合
- 报告快照写入 `sessions.report_json`，并写数据目录 `reports/{id}.json`；同时保留逐轮记录、`focus/focus_fused/score` 与起跳事件。Session 完成 900 秒后回收内存数组，报告仍从 SQLite 读取
- 硬件/仅心率会话互斥：新建硬件会话会自动结束旧的未完成硬件会话，避免 UDP 端口争抢；会话结束释放端口与采集进程

## 7. 关键权衡（MVP 演示定位）

1. **真实数据回放 + 真机双通道**：无硬件时可回放本机配对 EDF 复现端到端"校准→游戏→报告"；hardware 源已通过 Xmuse OSC/UDP 真机接入
2. **单被试基线**：模型对陌生被试仍有区分度（LOSO 验证），但演示时建议校准/游戏用同一被试
3. **数据隐私**：脑电与档案默认全程本地，无联网账号、无上传；数据目录在系统文档目录，SQLite 未加密（文件权限/OS 账户/磁盘加密为边界）；仅可选背景音乐访问网易云。详见 `docs/DEV-REPORT-v1.8.1.md`
4. **前端零构建**：无需 Node/npm，静态托管即可；7 个页面共用一套 `assets/`
5. **成长系统本地化**：积分、签到、商城、装扮、成就都不依赖服务端，断网也能完整使用；清缓存会重置成长进度，需在隐私说明中明示

## 8. 扩展路径

- 真机接入：已实现 `HardwareSource` → `XmuseOSCSource`（OSC/UDP）；后续可补 LSL 与 4 通道专属模型
- 多孩子账号：基线/进度按 profile 分文件保存
- 家长周报：跨会话聚合专注曲线与基线变化趋势
- 试验设计：不同被试/场景下校准-游戏基线的稳定性评估

## 9. 画面动效约定（避免闪烁）

儿童专注场景对闪烁非常敏感，背景元素的任何抖动都会被看成"画面坏了"。以下约定对首页 SVG 与游戏画布同时生效，后续改动必须遵守：

1. **白云只水平缓慢漂移**：不做上下浮动、不叠加随机位移、不在帧内修改透明度。云的透明度只由 `sky.js` 色板里的 `cloud.alpha` 决定。
2. **游戏画布不做 CSS 拉伸重采样**：`game.html` 的 canvas 位图必须按「实际显示宽度 × devicePixelRatio」创建（`fitCanvas()`），逻辑坐标固定 900×460。直接给 900×460 位图套 `width:100%` 会让半透明元素在缓慢移动时逐帧抖动。
3. **亚像素位置要吸附到设备像素**：缓慢移动的大块半透明元素（云、光晕）绘制前把坐标对齐到设备像素网格（`Math.round(v * view.x) / view.x`），只允许整像素移动。
4. **动画时钟用平滑累加值**：不要直接用 `requestAnimationFrame` 的时间戳或 `performance.now()` 驱动位移与明暗；用 `state.clock += clamp(dt)`，避免切后台、掉帧后动画时间跳变。
5. **循环回绕要完全出画**：元素移出屏幕后再从另一侧进入，判定用元素自身的包围盒，不能用固定留白。
6. **天空渐变的颜色过渡交给 `SkyTheme`**：canvas 页面每帧读 `SkyTheme.palette()`，不要在页面里另写一套渐变逻辑；黑夜云朵由 `mixCloud()` 把 alpha 平滑降到 0，不能直接 `if (night) return` 硬切；模式切换走 1.2 s 颜色渐变（`--sky-fade`），不做瞬切。

自测方法：在 100% / 125% / 150% 系统缩放下各看 30 秒游戏画面，白云边缘不应有任何亮度跳变或"沙沙"抖动；切换天空模式时云应连续淡入淡出，而不是突然出现或消失。

## 10. 版本记录要点（与 CHANGELOG 对齐）

| 版本 | 架构层变化 |
|---|---|
| v1.3.x | 天空主题、黑胶唱片机、家长报告、首页与游戏共用环境色 |
| v1.4.0–1.4.1 | 心率辅助闭环（`heart.py`）、一键启动脚本、心率默认关闭 |
| v1.4.2–1.4.4 | 专注判定放宽、走神提示下移、首次上手教学、蓄力节奏调整 |
| v1.4.5–1.4.6 | 本机配对 EDF 无设备试玩、会话隔离与 SSE 自愈 |
| v1.4.7–1.4.13 | 报告导出（`export.py`）、积分钱包、成就、商城、每日签到、装扮与肤色 |
| v1.4.14–1.4.15 | 成就专属装扮、图鉴与获得时间、商城定价改为 5–18 积分、得分即积分 |
| v1.4.16 | Xmuse 去噪与去伪迹（`denoise.py`）：陷波 / 眨眼修复 / 坏道掩码 / 质量门控，校准与游戏共用；帧新增 `artifact`，报告新增 `signal_quality` |
| v1.4.17 | 运动伪迹处理：DC 台阶（sigmoid 基线）、全通道共模减除、0.5–3 Hz 慢摆识别；`artifact` 新增 `motion`；自检扩到 14 项 |
| v1.5.0 | 单轮核心机制独立为 `assets/focus-round.js`：宽容期/衰减、唯一金色区域、2.5 s 子弹时间、归一化脑电基础分、逐轮研究数据；游戏积分与商城货币分离（30:1） |
| v1.6.0 | 金色区域前 0.6 s 满分、之后最多折损 10%；无效点击 0.5 s 冷却；儿童端隐藏实时分数/百分比/潜在分，只显示本局积分与 +N；逐轮新增点击倍率与冷却数据 |
| v1.7.0 | 开发者三栏监测：真实原始/处理后多通道波形、频段与算法中间值、30 s 分数/事件；独立 `/monitor` SSE，儿童模式零订阅；原始窗仅内存有限缓存 |
| v1.8.1 | 本机 SQLite 主存储与多用户档案：数据目录/迁移/备份恢复、后端用户归属、钱包幂等、旧报告/旧 LocalStorage 迁移、Session 900 s 回收 |
