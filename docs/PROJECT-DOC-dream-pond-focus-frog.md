# 专注小蛙 · 梦境池塘 — 项目主文档

> 文档类型：Proposal + MVP PRD + Technical Design + AI Workflow（四合一，对应课程 Project Documentation Guidelines Part 1–4）
> 游戏名：专注小蛙 · 梦境池塘（Dream Pond Focus Frog）
> 代码版本：v1.7.0（2026-11-27）
> 仓库：`eeg-focus/`（GitHub: `mujiu07/eeg-focus`）
> 说明：本文件是评审入口；更细的架构、技术栈、隐私与硬件内容见 `docs/` 下对应文档。

---

## 1. Proposal（项目提案）

### 1.1 要解决的真实问题

ADHD 儿童注意力维持困难、缺乏对自身专注状态的觉察；传统训练枯燥、容易脱落。市面上的脑电产品大多停留在"测注意力"——显示一个数值或驱动一个炫酷效果，孩子没有内在动机去维持专注。

本项目的假设是：把"专注"变成完成游戏动作的**必要条件**，形成"专注 → 行动 → 即时反馈"的闭环，比单纯显示分数更接近神经反馈训练的原理，也更容易向家长解释"孩子在练什么"。

**现有证据与边界（诚实标注）：**

| 证据类型 | 现状 |
|---|---|
| 竞品桌面调研 | 已整理 6 个竞品（EndeavorRx、宇构智核、Muse、中电云脑、Guardians DTx、朋睿），见 `PRD-brain-focusing-game-MVP.md` |
| 课程/领域背景 | 课程大纲要求真实项目交付；ADHD 数字治疗监管逐步明确 |
| 真实用户访谈 | **尚未完成**（软启动计划中的 5–10 个家庭内测未执行） |
| 临床有效性 | **不声称**；本 MVP 是教学演示与机制验证，不是医疗器械 |

### 1.2 利益相关者

| 角色 | 关心什么 | 在本项目中的体现 |
|---|---|---|
| ADHD 儿童（直接用户） | 好玩、不枯燥、立刻有反馈 | 池塘、青蛙、跳跃、成就动画、装扮 |
| 家长（间接用户） | 孩子是否在练、有没有变化、数据是否安全 | 「给家长的话」、报告导出、隐私说明 |
| 康复/教育人员 | 报告是否可读、能否二次分析 | Excel/CSV 导出、有效数据占比 |
| 课程评审 | 过程可追溯、AI 合规、个人贡献 | `EVIDENCE`、`AI-USAGE-LOG`、`REFLECTION` |
| 开发者（团队 2 人） | 可维护、可复现、能持续迭代 | 零构建前端、单一服务、清晰模块边界 |

### 1.3 范围与可行性

**MVP 范围内：**

- 脑电校准与个人基线（P0）
- 专注映射"蓄力→起跳"（P0）
- 三种（现为四种）信号源：EDF 回放 / 手动 / Xmuse 真机 / 仅心率
- 报告页与家长可读的总结、PDF/Excel/Word 导出
- 支撑留存的轻量成长系统：积分、签到、成就、商城、装扮
- 全站天空主题、动态池塘、可选背景音乐、游戏时长选择

**明确不做：**

- 医疗诊断、处方、疗效承诺
- 账号体系、云端同步、多孩子档案（路线图）
- 移动端适配（仅桌面浏览器）
- 产品内 AI 功能（AI 仅用于辅助开发）

**可行性判断：**

| 维度 | 判断 | 依据 |
|---|---|---|
| 技术 | 可行 | FastAPI + 原生前端已跑通；Xmuse OSC 已实测 |
| 算法 | 有限可行 | EEGMAT 模型 LOSO 准确率 0.729；4 通道设备走频段回退，只表达相对变化 |
| 数据 | 可行 | PhysioNet 公开数据 + 本机 EDF 回放，无需自采即可演示 |
| 成本 | 可行 | 本地运行、无云服务；月运营成本接近 0（仅可选音乐联网） |
| 合规 | 需谨慎 | 儿童敏感数据 → 全程本地；对外文案统一"教学映射/非诊断" |

---

## 2. MVP PRD（摘要）

> 完整需求与验收口径见 `PRD-brain-focusing-game-MVP.md`；本节只保留执行所需的摘要。

### 2.1 目标用户与场景

- **主要用户**：6–12 岁、注意力维持困难的儿童（通用描述，不做诊断筛选）
- **使用场景**：家中安静环境，家长陪同；单次 1–10 分钟（可选自定义至 60 分钟，默认 3 分钟）
- **前置条件**：桌面浏览器；有 Xmuse 则用真机，没有则用回放/手动/仅心率

### 2.2 核心工作流

```
首页（选天空/时长）
  → 校准（40 s：安静 20 s + 心算 20 s；可跟 60 s 视频）
  → 生成个人基线（1 小时有效，存本机）
  → 游戏（专注→蓄力→起跳；中断暂停）
  → 结算（得分入积分；可能解锁成就/装扮）
  → 报告（曲线回放 + 给家长的话 + 导出）
  → 首页成长入口（签到/成就/商城/装扮）
```

### 2.3 业务规则（当前实现）

| 规则 | 取值 | 位置 |
|---|---|---|
| 校准时长 | 默认 40 s，可跟 60 s 视频，最长 600 s | `web/calibrate.html` |
| 基线 | 校准期 focus 中位数（P50），另记 P10/P90 | `app/server.py` `/calibrate` |
| 基线有效期 | 1 小时（`localStorage: bf-calib`） | `web/assets/api.js` |
| 专注判定 | 平滑后 45/38 分滞回；高于蓄力零点 42 分才蓄力 | `web/game.html`、`assets/focus-round.js` |
| 宽容与衰减 | 低于阈值 1.5 s 内不掉进度，超过后按基准速度 30% 衰减至 0 | `assets/focus-round.js` |
| 金色区域 | 每轮随机生成一次，进入后锁定脑电基础分 | `assets/focus-round.js` |
| 子弹时间 | 固定 2.5 s 穿过区域，所有玩家窗口一致 | `assets/focus-round.js` |
| 计分 | 基础分 `B=round(20+80×T_ref/(T+T_ref))`；实际积分 `S=round(B×M(t))`，前 0.6 s 满分、之后最多折损 10%，超时 0 分 | `assets/focus-round.js` |
| 无效点击 | 非金色区域点击触发 0.5 s 蓄力冷却；不扣分、不清空，冷却计入本轮用时 | `assets/focus-round.js` |
| 信号中断 | 蓄力、衰减、冷却、单轮计时与子弹时间全部暂停 | `web/game.html` |
| 积分 | 本局累计积分按 30:1 折算（有得分至少 1 积分），一局结束一次性入账 | `web/assets/wallet.js` |
| 签到 | 每天 +2 积分，本机 0 点刷新 | `web/assets/checkin.js` |
| 商城 | 装扮 5–18 积分；成就专属不售卖 | `web/assets/shop.js`、`dressup.js` |
| 成就 | 4 组 15 枚：首次校准、单局 1/3/5/10 分钟、累计 30/60/150/300/600 分钟、连续 3/5/7/15/30 天 | `web/assets/achievements.js` |
| 数据边界 | 脑电/报告/成长数据均在本机；仅可选音乐联网 | `docs/usage-and-privacy.md` §6 |

### 2.4 可测试的验收标准

| # | 验收标准 | 当前状态 | 验证方式 |
|---|---|---|---|
| AC1 | 无设备时可通过 EDF 回放完成校准→游戏→报告 | 通过 | 手动 E2E + 本地会话 JSON |
| AC2 | 校准失败（无有效帧）不会写入基线并给出提示 | 通过 | 断流场景手动验证 |
| AC3 | 基线 1 小时内刷新页面无需重新校准，超时后引导重校 | 通过 | 篡改 `bf-calib` 时间戳验证 |
| AC4 | 专注高于蓄力零点可蓄力；短暂走神进度保持，超过 1.5 s 才缓慢衰减；信号异常/暂停冻结（v1.6.0） | 通过 | `node tests/selfcheck_round_logic.js` + 手动滑块 |
| AC5 | 开发者三栏监测显示真实原始/处理后波形、频段、算法、分数与事件；儿童模式零订阅（v1.7.0） | 通过（无真机） | `tests/selfcheck_monitor.py`、`tests/selfcheck_ui_static.js`、Playwright |
| AC5 | 蓄力越快脑电基础分越高；前 0.6 s 点击满分、之后最多折损 10%，错过 0 分；提前点击触发 0.5 s 冷却；积分按 30:1 折算 | 通过 | 模拟脑电回归 + `bf-wallet` 检查 |
| AC6 | 信号中断时蓄力与计时暂停，不产生伪得分 | 通过 | 关闭 OSC 推流验证 |
| AC7 | 报告包含曲线、有效数据占比与「给家长的话」 | 通过 | report 页 + 会话 JSON |
| AC8 | PDF / Excel / Word / CSV / JSON 可导出且中文正常 | 通过（依赖齐全时） | 本机导出实测 |
| AC9 | 成就解锁只播一次，刷新后不重复播报 | 通过 | `bf-ach-pending` 清空验证 |
| AC10 | 装扮/商城购买扣积分且刷新后保留 | 通过 | `bf-wallet` / `bf-owned` 验证 |
| AC11 | Android/iOS 手机端不作为支持范围，布局不崩即可 | 部分通过 | 窄屏手动检查 |
| AC12 | 全站不加载外部静态资源；断网（除音乐）可玩 | 通过 | DevTools Network 检查 |

> 未完成项：真实儿童用户的可用性测试、长时间连续使用稳定性、4 通道模型精度验证。

---

## 3. Technical Design（技术设计）

### 3.1 系统架构（摘要）

```
浏览器（5 页面 + assets/*，零构建）
   │ REST + SSE（127.0.0.1）
FastAPI（server.py）
   ├─ sources.py：replay / manual / hardware / heart
   ├─ xmuse_osc.py：UDP 7000/8000 → 2 s 窗
   ├─ focus_engine.py：231 维模型 / β/(θ+α) 回退 / EMA
   ├─ heart.py：hrd 心率与融合
   ├─ export.py：PDF / XLSX / DOCX / CSV / JSON
   └─ music.py：网易云代理（可选）
   │
outputs/models/*.joblib ← scripts/preprocess.py + train.py ← data/eegmat/
outputs/sessions/*.json（本地报告）
```

完整图与 API 表见 `ARCHITECTURE.md`。

### 3.2 技术选型与权衡

| 选择 | 理由 | 代价 |
|---|---|---|
| FastAPI + SSE | 单进程即可承载 REST/SSE/静态资源；Python 与算法同栈 | 无多用户并发设计（本地单人足够） |
| 原生 HTML/CSS/JS + Canvas | 零构建、儿童场景秒开、无 CDN | 没有组件化框架，代码组织靠约定 |
| LogisticRegression（231 维） | 小样本、可解释、训练快 | 泛化有限；跨被试波动大（Subject02 仅 0.32） |
| 频段回退 `β/(θ+α)` | 4/6 通道设备无需重训即可玩 | 只表达相对变化，不是临床分数 |
| 基线=个人中位数 | 简单、可解释、家长能理解 | 受校准状态影响；1 小时有效期是折中 |
| localStorage 成长系统 | 无账号、无上传、断网可用 | 换设备/清缓存即丢失；无跨端同步 |
| 报告导出在本机 | 隐私；家长可直接拿走文件 | 依赖 reportlab/openpyxl/python-docx |
| OSC 而非 LSL | Xmuse Direct 原生支持，Windows 部署简单 | 无科研级时间戳；后续可补 LSL |

### 3.3 模块与接口

| 模块 | 职责 | 关键接口 |
|---|---|---|
| `app/server.py` | 会话生命周期、校准、报告、导出、静态托管 | `POST /api/session`、`/calibrate`、`/finish`、`GET /api/report/{id}` |
| `app/sources.py` | 信号源抽象与工厂 | `start()` / `next_window()` / `stop()` |
| `app/xmuse_osc.py` | OSC 接收、环形缓冲、质量/电量 | `next_window()`、`describe()` |
| `app/focus_engine.py` | 特征→模型/回退→EMA | `update(seg, fs)`、`describe()` |
| `app/heart.py` | hrd/mock/csv 心率与融合 | `start/stop/status`、`snapshot()` |
| `app/export.py` | 报告渲染为文件 | `render_pdf/xlsx/docx/csv/json` |
| `web/assets/api.js` | REST/SSE 封装与自愈 | `API.get/post`、`openStream` |
| `web/assets/wallet.js` | 积分账本 | `settleRound/add/spend` |
| `web/assets/achievements.js` | 成就判定与播报队列 | `record*`、`pending` |
| `web/assets/dressup.js` | 装扮数据、图鉴、穿戴 | `owned/equip`、`ITEMS` |

### 3.4 数据与状态

**服务端（本机文件）：**

- `outputs/models/LogisticRegression.joblib`：模型
- `outputs/sessions/{id}.json`：每局逐帧 focus、`focus_fused`、`score`、起跳事件、校准信息
- `outputs/train_report.md`：模型指标与逐被试准确率

**浏览器（localStorage）：**

| 键 | 内容 | 是否可清 |
|---|---|---|
| `bf-calib` | 基线 + 时间戳（1 h） | 可，清后需重校 |
| `bf-wallet` | 积分/局数/累计/消费 | 可，清后成长进度归零 |
| `bf-checkin` | 签到日期 | 可 |
| `bf-achievements` | 解锁状态、进度、时间 | 可 |
| `bf-owned` / `bf-owned-at` / `bf-outfit` | 已购装扮、获得时间、穿戴 | 可 |
| `bf-sky-mode` / `bf-music-*` / `bf-heart*` | 偏好与心率参数 | 可 |

### 3.5 测试与验证策略

| 层级 | 方法 | 现状 |
|---|---|---|
| 模型离线 | LOSO 交叉验证、逐被试准确率 | 已产出 `train_report.md` |
| 服务接口 | 手动 E2E：创建会话→校准→游戏→报告→导出 | 已跑通（58 份本地会话 JSON） |
| 硬件 | OSC 探针 + 合成报文 + 成人试戴 | 合成链路通过；儿童真机未测 |
| 前端 | DevTools Network/Console、多缩放比例检查 | 已验证无外链；DPI 抖动已修复 |
| 回归 | 按 `CHANGELOG` 版本逐项手测 | 每次发布手测，未自动化 |
| 用户 | 家庭内测问卷 | **未开始** |

---

## 4. AI Workflow / Agent Setup（AI 协作约定）

> 本节是"可执行的仓库级 AI 使用说明"，不是泛泛的提示词合集。

### 4.1 给 AI 编码助手的项目指令

1. **先读后写**：改动前先读 `README.md`、`CHANGELOG.md`、本文件与相关模块；不要凭猜测改行为
2. **保持零构建**：不引入 npm/打包器/前端框架；新增前端能力放进 `web/assets/`
3. **隐私红线**：不新增任何把脑电、报告、成长数据发往外部的调用；唯一允许的公网访问是可选背景音乐
4. **表述红线**：不写"诊断/治疗/提升注意力"等疗效表述；统一用"脑波分数（教学映射）"
5. **本地数据**：新增持久化状态优先用 `localStorage`，并在 `usage-and-privacy.md` §6 登记键名
6. **SSE 契约**：帧字段只增不改；分隔符兼容 `\r?\n\r?\n`
7. **版本纪律**：行为变化要更新 `CHANGELOG.md` 与受影响文档；不静默改默认值（尤其 OSC 端口）

### 4.2 上下文管理

- 长期上下文：`README.md`（能力与启动）、`docs/ARCHITECTURE.md`（结构）、`docs/tech-stack.md`（选型）、`docs/xmuse-hardware-integration.md`（硬件证据）
- 会话内上下文：先定位模块，再读该模块与相邻测试/文档；避免整库通读
- 交付前：用 `CHANGELOG` 对照实际改动，防止"文档写了、代码没做"

### 4.3 工具使用与验证约定

| 场景 | 约定 |
|---|---|
| 运行服务 | `uvicorn app.server:app --host 127.0.0.1 --port 8000`；先确认端口未被占用 |
| 无设备验证 | 首页 Konami 码进入开发者模式，选「无设备试玩 · 1 分钟」 |
| 硬件联调 | 先跑 `scripts/xmuse_osc_probe.py`，再看校准页/开发者页 |
| 报告验证 | 查看 `outputs/sessions/{id}.json` 的帧数、有效帧、起跳事件 |
| 导出验证 | 逐个格式下载并打开，检查中文与曲线 |
| 隐私验证 | DevTools Network 确认无外部请求（音乐关闭时） |
| 变更记录 | 提交信息写清版本与范围；`CHANGELOG` 与文档同步 |

### 4.4 AI 合规

- 产品内**无 AI 功能**；AI 仅用于辅助开发（代码、文案、文档）
- AI 使用记录见 `AI-USAGE-LOG-dream-pond-focus-frog.md`：可核验的提交/测试证据优先；早期未留存原始 prompt 的条目已明确标注
- 不把用户/儿童数据输入外部 AI；开发期也不上传 `outputs/sessions/` 与 `data/`

---

## 5. 与课程阶段的对应

| 阶段 | 交付物 | 本仓库对应 |
|---|---|---|
| Stage 1 Project Initiation | Proposal + MVP PRD | 本文件 §1–2、`PRD-brain-focusing-game-MVP.md` |
| Stage 2 MVP Sprint | 可运行 MVP + 技术设计 | `app/`、`web/`、本文件 §3、`ARCHITECTURE.md` |
| Stage 3 User Validation | 用户验证报告 | `EVIDENCE-dream-pond-focus-frog.md` §3（待补真实用户） |
| Stage 4 Iterative Development | Beta + 更新文档 | `CHANGELOG.md`、`VIBE-CODING-dream-pond-focus-frog.md` |
| Stage 5 Demo Day | 演示材料 | `EVIDENCE-dream-pond-focus-frog.md` §5 |
| Stage 6 Reflection & Archiving | 反思 + AI 审计 + 贡献 | `REFLECTION-dream-pond-focus-frog.md` |

---

*文档创建：2026-11-17（基于 v1.4.15 代码与仓库历史整理）*
*维护：随版本发布同步更新；不确定的数字一律标注"待验证"*
