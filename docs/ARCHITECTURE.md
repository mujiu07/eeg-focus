# 专注小蛙 MVP - 技术设计（简明版）

## 架构总览

```
┌────────────────────────────────────────────┐
│  web/（浏览器）                             │
│  首页 · 校准页 · 游戏页(Canvas) · 报告页 · 开发者页 │
│  原生 HTML/CSS/JS，SSE 接收专注指数，rAF 渲染 │
└───────────────┬────────────────────────────┘
                │ REST / SSE
┌───────────────┴────────────────────────────┐
│  app/（FastAPI 后端）                       │
│  sources.py   信号源抽象（replay/manual/hardware）│
│  xmuse_osc.py Xmuse OSC/UDP 多端口接收       │
│  focus_engine.py  模型推理 / 频段回退 + EMA  │
│  music.py     网易云歌单代理（可选背景音乐）  │
│  server.py    会话管理/校准/报告/音乐/静态托管│
└───────────────┬────────────────────────────┘
                │ 读取
┌───────────────┴────────────────────────────┐
│  outputs/models/LogisticRegression.joblib  │
│  ← scripts/train.py ← scripts/preprocess.py│
│  ← data/eegmat/（PhysioNet EEGMAT 真实脑电）│
└────────────────────────────────────────────┘
```

## 数据流（核心：专注 → 行动 → 即时反馈）

```
EDF 信号窗口 (2s × 21通道)
  → 带通滤波 0.5-45Hz（与训练一致）
  → 频段特征 (11 维/通道)
  → LogisticRegression.predict_proba → 专注概率 p
  → EMA 平滑 (α=0.35) → 专注指数 focus
  → 游戏逻辑: focus ≥ 基线 → 蓄力 +Δ；focus < 基线 → 蓄力 -Δ
  → 蓄满 100 → 青蛙跳荷叶 +1 分

Xmuse 真机窗口 (2s × 4/6通道)
  → 维度与模型不匹配 → 相对频段功率 beta/(theta+alpha)
  → sigmoid 映射 0..1 → 同一套 EMA 平滑与基线逻辑
```

## 校准（P0）

- 采样时长：20 秒（演示可调 3-60s）
- 基线 = 采样期专注指数中位数（P50），另记 P10/P90
- 校准期专注指数曲线与基线可视化呈现给用户/家长

## API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查 + 模型名 |
| GET | `/api/dev/info` | 引擎信息、训练报告、EDF 文件列表、会话 |
| GET | `/api/dev/current` | 当前信号源配置与最近会话 |
| POST | `/api/dev/source` | 切换全局默认信号源（含 OSC 参数） |
| POST | `/api/session` | 创建会话 `{mode, file, baseline, osc_*}` |
| GET | `/api/session/{id}/stream` | SSE 推流（hello/frame/end） |
| POST | `/api/session/{id}/manual` | 手动模式设置专注度 |
| POST | `/api/session/{id}/calibrate` | 采样并建立基线 |
| POST | `/api/session/{id}/finish` | 结束会话，生成报告 |
| GET | `/api/report/{id}` | 读取报告（内存/磁盘） |
| GET | `/api/music/playlist` | 背景音乐歌单（网易云代理） |
| GET | `/api/music/url/{track_id}` | 单曲播放直链（服务端缓存） |

## 会话与并发模型

- `_sessions: dict` 全局会话表；每会话独立信号源 + 专注引擎实例（引擎状态重置避免跨被试污染）
- 后台 asyncio 任务按 0.5s 步长推进信号源 → 计算 focus → 写入队列（容量 1，丢弃旧帧）+ 历史列表
- SSE 端点从队列取帧；校准端点按时间窗口从历史列表聚合
- 报告落盘 `outputs/sessions/{id}.json`

## 关键权衡（MVP 演示定位）

1. **真实数据回放 + 真机双通道**：无硬件时可回放 EDF 复现端到端"校准→游戏→报告"；hardware 源已通过 Xmuse OSC/UDP 真机接入
2. **单被试基线**：模型对陌生被试仍有区分度（LOSO 验证），但演示时建议校准/游戏用同一被试文件
3. **数据隐私**：脑电全程本地，无账号、无上传（儿童敏感数据合规，符合 PRD）；仅可选背景音乐访问网易云
4. **前端零构建**：无需 Node/npm，静态托管即可；性能满足桌面浏览器 <3s 加载

## 扩展路径

- 真机接入：已实现 `HardwareSource` → `XmuseOSCSource`（OSC/UDP）；后续可补 LSL 与 4 通道模型
- 多孩子账号：基线/进度按 profile 分文件保存
- 家长周报：跨会话聚合专注曲线与基线变化趋势
- 试验设计：不同被试/场景下校准-游戏基线的稳定性评估
