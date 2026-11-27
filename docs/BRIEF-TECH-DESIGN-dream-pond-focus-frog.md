# 专注小蛙 · 梦境池塘 — 简要技术设计（Brief Tech Design）

> 游戏名：专注小蛙 · 梦境池塘（Dream Pond Focus Frog）
> 适用代码：`main` @ `v1.8.4`（开发者工作台/诊断/标准评估；历史基线 v1.8.3/v1.8.2/v1.8.1/v1.7.0）
> 说明：本文是**一页可读的技术设计摘要**，用于评审与新人上手；完整细节见 `ARCHITECTURE.md` / `tech-stack.md` / `DECISIONS-AND-VERIFICATION-dream-pond-focus-frog.md`。
> 版本元数据：`app/server.py` 的 FastAPI `version` 已同步为 `1.8.3`。

---

## 1. 一句话

一个**本地运行**的脑波专注游戏：实时把 EEG（或回放/手动/心率）映射为 0–1 专注值，校准出个人基线后，专注才能蓄力、起跳；结束后生成本地报告与可导出文件，成长数据只存浏览器。

## 2. 目标与非目标

**目标**

- 证明"专注 → 行动 → 即时反馈"闭环可跑通、可解释、可演示
- 无设备也能完整走通（回放/手动/仅心率），有 Xmuse 时用真机
- 脑电与会话数据不出本机；报告、积分、成就等都能离线使用

**非目标**

- 不提供诊断、治疗或疗效承诺；分数只表达相对变化
- 不做账号、云端同步、多孩子档案
- 不做移动端原生 App；不支持多用户并发

## 3. 约束（设计前提）

| 约束 | 影响 |
|---|---|
| 儿童敏感数据 | 无外部 AI、无统计 SDK、无 CDN；仅可选音乐联网 |
| 零构建前端 | 不引入 npm/打包器；页面直接由 FastAPI 静态托管 |
| 单机单会话 | 内存会话表即可；不做分布式与持久队列 |
| 消费级硬件 | 4/6 通道设备走频段回退，不假设 21 通道 |
| 演示优先 | 失败必须可降级、可解释，不能卡死在硬件上 |

## 4. 组件与职责

| 层 | 组件 | 职责 | 关键接口 |
|---|---|---|---|
| 浏览器 | 7 个页面 `index/profiles/settings/calibrate/game/report/dev` | 首页、档案、数据设置、校准、玩法、报告、联调 | — |
| 浏览器 | `assets/api.js` | REST + SSE 封装，6 s 无数据自愈重连 | `openStream` |
| 浏览器 | `assets/wallet/checkin/achievements/shop/dressup` | 成长系统（SQLite 权威 + localStorage 缓存） | `settleRound` / `Wallet.replace` / `record*` / `owned` |
| 浏览器 | `assets/sky.js`、`music.js`、`hero-*`、`pond-*` | 天空、音乐、首页池塘与音效 | `SkyTheme.palette()` |
| 服务 | `app/server.py` | 会话生命周期、校准、报告、导出、静态托管、用户归属/TTL | `POST /api/session`、`/calibrate`、`/finish` |
| 服务 | `app/storage.py` / `app/accounts.py` | SQLite 档案/校准/游戏/资产、备份迁移与存储 API | `/api/profiles/*`、`/api/storage/*` |
| 服务 | `app/calibration.py` | 每日 P15/P85、阶段有效时间、日状态/双基线 | `/api/session` 硬件门槛、`/calibration-status` |
| 服务 | `app/difficulty.py` | 黄色区域起点范围、净蓄力指标、连续局间判定 | `/api/profiles/{id}/difficulty`、Session `difficulty` 快照 |
| 服务 | `app/sources.py` | 信号源抽象与工厂 | `start()` / `next_window()` / `stop()` |
| 服务 | `app/xmuse_osc.py` | OSC/UDP 接收、环形缓冲、质量/电量 | `next_window()` |
| 服务 | `app/focus_engine.py` | 特征→模型/频段回退→EMA | `update(seg, fs)` |
| 服务 | `app/heart.py` | 心率采集与融合 | `snapshot()` |
| 服务 | `app/export.py` | PDF/XLSX/DOCX/CSV/JSON | `export_report` |
| 服务 | `app/music.py` | 网易云代理（可选） | `/api/music/*` |

## 5. 关键流程

**校准（40 s）**

```
选择信号源 → POST /api/session → POST /calibrate {duration}
  → 采样 20 s 安静 + 20 s 心算 → 聚合 focus
  → 写 localStorage bf-calib（P50 + P10/P90 + 时间戳，1 h 有效）
  → 同时回传 score_low / score_high（映射 20–80 分）
```

**游戏**

```
GET /api/session/{id}/stream (SSE, 0.5 s/帧)
  → 前端渲染 focus / 分数 / 心率
  → 分数高于 42 分：蓄力上升（45 分亮专注灯，38 分熄灭）；短暂低于：宽容 1.5 s；持续低于：缓慢衰减；断流：暂停
  → 每轮唯一金色区域 → 进入锁定 20–100 脑电基础分 → 2.5 s 子弹时间
  → 前 0.6 s 点击满分、之后最多折损 10%；未点击：普通跳跃 0 分；提前点击 0.5 s 冷却（v1.6.0）
  → POST /finish {score, played_sec, actions}
```

**报告与成长**

```
校准：自然 30s + 教学 30s 有效帧 → 当日 L/H + 长期参考 v1；Session 创建锁定
服务端写 profiles.db 的 sessions/report_json + 数据目录 reports/{id}.json（curve、逐轮、统计）
  → report.html 按 user_id 读取 + 生成「给家长的话」
  → 导出：本机生成 PDF/XLSX/DOCX/CSV/JSON
  → 服务端按 session_id 幂等入账钱包；前端 Wallet.replace 同步；成就/商城/装扮按 user_id 存 SQLite
```

## 6. 算法要点

- **EDF/21 通道**：2 s 窗，每通道 11 特征（5 绝对 + 5 相对 + θ/β），231 维 → LogisticRegression → EMA（α=0.35）
- **Xmuse/4–6 通道**：维度不匹配时回退 `β/(θ+α)`，`sigmoid(2.5 × (ratio − 0.70))`，再 EMA
- **分数映射**：`score = 20 + 60 × (focus − low) / (high − low)`，钳到 0–100；未校准时 `low=0.35, high=0.75`（50 分线 = 0.55）
- **两套阈值要分清**：报告 `above_mid_ratio` 以 50 分为“高于基线”线；游戏蓄力零点为 42 分（45 分亮灯 / 38 分熄灭，v1.4.2 放宽）
- **心率融合**：`focus_fused = (1−w) × focus + w × heart_component`，`w` 默认 0.15（0–0.5）
  - 心率分量：以校准静息为基准、跨度默认 12 BPM（6–80）；目标为静息 +45% 跨度的高斯倒 U；波动与下滑扣分
  - 仅心率模式的目标为静息本身（`target_delta=0`）：稳态下静息附近最高，偏离静息或波动变大都会降分（见 V-017）
- **去噪去伪迹**（`app/denoise.py`，仅 hardware 源，v1.4.16）：
  - 去趋势 → 50 Hz 陷波 → 眨眼（80 µV / 0.5–8 Hz ×2 减除）/ 削顶（≤0.3 s 插值）/ 肌电（35–45 Hz）/ 坏道（MAD 上下限）/ 设备 `is_good` 检测 → 0–1 质量评分
  - 坏道以 `channel_mask` 排除而非置零参与平均；单位自适应（`median(|x|)>500` 视为 ADC 计数）
  - **不改特征口径**：不做 0.5–45 Hz 带通，仍由 `features.prepare_signal` 完成
- **失效策略**：心率缺失/过期 → 退回纯 EEG；模型不可用 → 频段回退；信号中断 → 帧 `valid=false`；伪迹过重 → 帧 `valid=false, reason="artifact"`（不出分、不入 history）

## 7. 接口契约（摘要）

| 契约 | 约定 |
|---|---|
| SSE | 首帧 `hello`；之后 `frame`，**CRLF `\r\n\r\n`**；字段只增不改 |
| `frame` | `t`、`raw`、`focus`、`valid`、`focus_fused`、`score`、`baseline`、`score_low/high`、可选 `hr`、可选 `artifact`（hardware 源质量报告） |
| 报告 | 同时兼容旧字段：无 `score` 时退回 `focus_fused`（再退回 `focus`）× 100 |
| 导出 | `pdf` / `xlsx` / `docx` / `csv` / `json`；缺依赖只影响对应格式 |
| 静态资源 | 非 `/api/` 响应 `Cache-Control: no-cache` |

## 8. 数据与状态

| 位置 | 内容 | 是否入库 |
|---|---|---|
| `outputs/models/*.joblib` | 模型 | 是 |
| `专注小蛙/profiles.db` | 档案、校准、游戏/逐轮、钱包、成就、装扮、设置 | 否（仓库外） |
| `专注小蛙/reports/*.json` | 每局报告可读副本 | 否（仓库外） |
| `专注小蛙/backups/*.db` | 一致性备份 | 否（仓库外） |
| `outputs/sessions/*.json` | 旧报告兼容读取 | 否（`.gitignore`，隐私） |
| `data/eegmat/` | 公开 EDF 数据副本 | 本地 |
| 浏览器 `localStorage` | 当前档案缓存、基线缓存、天空/音乐/心率偏好 | 否 |
| `data/music_cookie.txt` | 可选音乐凭据 | 否（忽略） |

## 9. 失败模式与降级

| 失败 | 表现 | 降级 |
|---|---|---|
| 无模型文件 | 启动即报错 | 无（需重新训练/放入模型） |
| Xmuse 断流/端口占用 | 无帧或连接失败 | 诊断提示 → 回放/手动 |
| 心率不可用 | 选项置灰 | 纯 EEG 或仅心率不可用 |
| 导出依赖缺失 | 单格式 500/提示 | 其他格式可用 |
| 音乐接口失败 | 唱片机静音 | 不影响游戏 |
| SSE 断开 | 页面无数据 | 6 s 自愈重连，最多 4 次 |
| 信号伪迹过重 | 眨眼/电极晃动/肌电导致窗不可用 | 该帧 `valid=false, reason="artifact"`，游戏保持上一帧，报告与校准剔除 |

## 10. 验证入口

- 决策与验证流水：`DECISIONS-AND-VERIFICATION-dream-pond-focus-frog.md`
- 测试用例与证据：`EVIDENCE-dream-pond-focus-frog.md`
- 架构细节与动效约定：`ARCHITECTURE.md`
- 依赖、算法、硬件、导出：`tech-stack.md`

## 11. 已知风险

1. **模型泛化**：LOSO 准确率 0.729，最低被试 0.320；跨被试演示需重新校准，不能把分数当能力
2. **4 通道精度**：频段回退只保证相对变化，未做用户级验证
3. **成长系统动机**：签到/连续打卡/商城的长期效果与伦理边界无证据
4. **本地数据易失**：清缓存即失去积分、成就、装扮；已在隐私说明中明示
5. **版本元数据**：FastAPI 应用版本已在 v1.4.16 同步为 `1.4.16`（V-018 修复 V-014）；发布时仍须同时更新 tag / CHANGELOG / `FastAPI(version=...)` 三处

---

*文档创建：2026-11-17*
*维护：接口、算法常数、数据位置变化时必须同步本文与 `ARCHITECTURE.md`*
