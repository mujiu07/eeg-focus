# 开发报告：v1.8.4 开发者工作台整合与集成验收

> 日期：2026-11-27
> 基准：v1.8.3（`3b4f276`）
> 性质：儿童脑电游戏工程原型；不是临床训练、注意力诊断或治疗效果评价。

## 1. 目标与范围

v1.8.4 把 v1.7.0 的三栏实时监测、v1.8.1 的本地多用户档案、v1.8.2 的每日校准/双基线、v1.8.3 的个体自适应难度整合到**同一开发者工作台**，并增加：

- 运行环境与个人档案面板；
- 校准/长期参考双基线趋势与历史入口；
- 难度历史、当前轮次与下一局控制；
- 基于真实数据依据的瓶颈诊断；
- 蓄力过程统计与时间口径；
- 隔离的标准评估入口与记录；
- JSON/CSV 诊断导出；
- 数据完整性与隔离复核。

明确不修改：

- 核心游戏玩法、脑电特征/模型、校准公式、计分公式、自动难度策略；
- 蓄力速度、黄色区域宽度、点击窗口、子弹时间、积分/商城规则；
- 儿童端页面不新增开发者组件。

## 2. 实际源码核对与整合结论

### 2.1 三栏工作台已有骨架

v1.7.0 已经存在 `web/game.html?dev=1` 的三栏布局：

- 左：原始/处理后多通道波形、窗口、增益、通道开关、暂停；
- 中：现有游戏 Canvas；
- 右：频段、算法、游戏分数、状态、事件。

v1.8.4 没有重做游戏 UI，而是在右栏增加 **概览 / 基线 / 难度 / 诊断 / 评估导出** 五个标签页。中央 Canvas 和左栏始终保留；窄窗口沿用原有侧栏折叠按钮。

### 2.2 新模块

- `app/diagnostics.py`：纯函数诊断、蓄力过程汇总、客户端轮次边界检查；
- `app/dev_export.py`：脱敏 JSON/CSV 诊断导出；
- `web/assets/dev-workbench.js`：标签页、运行时/基线/难度/诊断/评估 API 渲染；
- `web/assets/eeg-monitor.js`：增加 `S_daily`/`S_reference` 双基线绘制与更明确的失败区间；
- `web/game.html`：工作台容器、标准评估横幅、确定性随机源与过程统计回填；
- `app/storage.py`：Schema v4、`assessments`、Session purpose/assessment、逐轮过程列；
- `app/server.py`：工作台/诊断/导出 API、评估入口、完成评估、诊断计算与数据边界检查。

## 3. 开发者工作台

### 3.1 运行环境与档案

工作台显示：

- 当前用户昵称与匿名 `user_id`；
- Session ID、用途（game / assessment）；
- 应用版本、数据库 Schema、数据目录；
- 当前信号源、运行模式、设备/配置指纹、可用通道、采样率；
- 开始时间、运行时长、监测订阅数、服务端 Session 数；
- 真实硬件 / EDF 回放 / 手动模拟 / 仅心率明确区分；
- SQLite 未静态加密提示。

数据来源是同一 Session 的服务端描述与监测批次，不用前端伪造设备信息。

### 3.2 双基线

- 曲线来自同一 `focus_fused` 输出的 `score_of` 与 `score_reference`，使用同一帧时间戳；
- 无效信号区间用底色标记，不跨断流连线，不插值；
- `S_daily` 是当日映射，`S_reference` 是长期参考映射；后者只用于趋势，不参与正式游戏蓄力/计分/商城；
- 原始/平滑游戏分数保留独立可展开图，避免把“平滑前”和“平滑后”混在一条线；
- 显示当日校准有效期限、设备匹配、L/H、样本数、有效采集、信号有效比例；
- 显示长期参考版本、状态、设备、算法版本、协议；
- 历史校准与参考版本放在可展开列表；长期参考通过版本化表追加，不覆盖旧版本。

### 3.3 难度

- 当前系数、自动开关、手动锁定、下一局预定；
- 名义随机范围与安全限制后的实际范围；
- 中位净蓄力、点击成功率、信号比例；
- 最近判定、连续偏高/偏低、策略版本；
- 当前轮次区域、能量、有效蓄力、eval、冷却、提前点击、子弹时间、动画；
- 调整历史含时间、前后系数、Session、指标、校准 ID、策略版本；
- 开启/关闭自动、锁定当前、恢复 1.00；
- 修改只影响下一局，已创建 Session 的快照不回写。

## 4. 瓶颈诊断

### 4.1 九类状态

`diagnose()` 同时返回全部诊断状态（`active` 可为多条），至少覆盖：

1. 设备断流/信号质量不足；
2. 校准无效或设备条件不匹配；
3. 脑电指标长时间低于蓄力条件；
4. 有有效蓄力但蓄力速度过慢；
5. 能量衰减频繁；
6. 提前点击/冷却时间过多；
7. 进入黄色区域但点击成功率低；
8. 已达到最低难度 0.60 仍无法获得适宜反馈；
9. 数据量不足。

每条诊断包含：

- `evidence`：实际阈值与实测值；
- `status`：measured / insufficient / not_applicable / clear；
- `engineering_only=true` 与 `not_medical_advice=true`；
- 明确的工程边界说明。

没有实测数据时只用 `insufficient_data`，不凭空生成原因。

### 4.2 低速场景

v1.8.3 模拟中的低速场景（固定中位约 44.2 s、自适应约 29.3 s、最低难度 0.60）在 v1.8.4 中独立触发：

```text
slow_charge
min_difficulty_still_hard
```

本阶段仅记录，不自动修改蓄力阈值、速度公式或最低难度限制。

## 5. 蓄力过程统计

### 5.1 时间口径

| 字段 | 含义 | 计入 | 不计入 |
|---|---|---|---|
| `charge_sec` | 正式计分用时 | 等待、宽容、衰减、无效点击冷却 | 断流、主动暂停、子弹、跳跃/归位 |
| `eval_sec` | 难度评估净用时 | 等待、宽容、衰减 | 冷却、断流、暂停、子弹、跳跃 |
| `charge_active_sec` | 有效蓄力净时间 | 滞回且高于蓄力零点 | 低于阈值、冷却、断流 |
| `below_threshold_sec` | 低于阈值的非冷却时间 | 宽容期、衰减 | 冷却、断流、暂停 |
| `cooldown_sec` | 无效点击冷却 | CHARGING 冷却段 | eval/有效蓄力 |
| `stale_sec` | 信号异常冻结 | 异常帧 | charge/eval |
| `bullet_sec` | 子弹时间 | 单轮过程观察 | charge/eval |
| `jump_anim_sec` | 跳跃/落地/视角归位 | 单轮过程观察 | charge/eval |
| `paused_sec` | 明确暂停/开局倒数 | 过程观察 | charge/eval |

`charge_active_sec + below_threshold_sec = eval_sec`（在字段完整的新报告中）；`eval_sec` 不是正式计分 `T`。旧报告缺少新字段时保留 `null`，不用减法伪装成实测值。

### 5.2 D 公式复核

`computePotentialScore(distance, chargeSec)` 的 `distance` 来自：

```text
zone.lo - startEnergy
```

不是黄色区域的绝对位置。v1.8.3 低系数 `0.60` 下的 `start_energy=15`、安全下界 `17` 已在 `tests/selfcheck_v184_round.js` 增加边界回归：区域入口必须大于起始能量，D 至少为 2。正式计分公式未改。

### 5.3 数据完整性与客户端边界

- Pydantic 校验非负、上限、`planned_sec/played_sec`；
- `diagnostics.validate_actions()` 检查重复轮次、负时间、`eval_sec > charge_sec`、`eval_sec > active + below`、超长 Session；
- 不一致轮次从分析中排除，并写入报告 `data_quality.warnings`；
- 正式 `score` 仍由原计分链路产生，不在诊断层重算；
- 明确标记 `client_reported=true`，不声称只靠边界检查就实现完整抗篡改。

## 6. 标准评估

### 6.1 入口与协议

- 开发者页/工作台提供“开始 90 秒标准评估”；
- `POST /api/assessments`，内部强制 `purpose=assessment`；
- 默认 `standard_v1`、90 秒、固定难度 `1.00`、固定种子；
- 评估 Session 使用独立 `assessments` 记录，`session_id` 唯一；
- 黄色区域随机序列由服务端 seed 驱动；前端使用 `FocusRound.makeRng(seed)`；
- 评估结束仍走原有报告持久化，但 `purpose=assessment`。

### 6.2 隔离

评估期间：

- 不写个人难度档案、不推进连续判定；
- 不发放商城积分、不解锁成就；
- 不改当日校准、不覆盖长期参考；
- 不计入普通游戏排行；
- 报告以 `assessment_id` 标识，可单独查询。

真实硬件评估要求当日有效校准、有效长期参考与设备/算法兼容；缺失或不兼容返回 409。回放/手动可作为**明确标记的模拟评估**，但不能生成可纵向比较的正式结果。

### 6.3 评估记录

`assessments` 保存：

- 协议版本、计划时长、固定系数、seed、simulation；
- 校准 ID、参考基线 ID、设备快照、参数快照；
- 特征统计、行为统计、完整报告 JSON；
- 开始/结束/状态。

### 6.4 边界

90 秒是待验证的原型参数，不是临床注意力测试标准。本阶段不开发完整成长报告、常模、诊断结论。

## 7. 诊断导出

- 用户主动点击导出，不支持自动上传；
- 支持 JSON 与 CSV；
- 写入本地数据目录 `reports/`；
- 默认不含昵称，`subject.nickname_exported=false`；
- 不导出高频原始脑电数组；`privacy.raw_eeg_exported=false`；
- 内容：软件/算法版本、信号源/设备、校准快照、长期参考、难度快照、Session/逐轮、运行事件、瓶颈诊断、信号质量、异常和中断、隐私标记。

CSV 为“元数据 section/key/value + 逐轮表”两层结构，便于表格软件查看；JSON 保留结构化层级。

## 8. Schema 与 API

### 8.1 Schema v4

- `sessions.purpose`、`sessions.assessment_id`；
- `assessments` 表；
- `rounds` 追加 `eval_sec`、`charge_active_sec`、`below_threshold_sec`、`stale_sec`、`decay_events`、`decay_sec`、`energy_gain`、`energy_loss`、`bullet_sec`、`jump_anim_sec`、`paused_sec`；
- 原有 `_ensure_columns` 原地迁移，不重建用户/历史数据。

### 8.2 API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/dev/workbench` | 工作台运行时、校准/参考、难度、评估、最近报告 |
| GET | `/api/dev/diagnostics/{sid}` | 已完成 Session 诊断与过程统计 |
| POST | `/api/dev/diagnostics/{sid}/export?fmt=json\|csv` | 写本地 reports 并返回下载内容 |
| POST | `/api/assessments` | 创建标准评估 Session |
| GET | `/api/assessments` | 按用户列出评估 |
| GET | `/api/assessments/{id}` | 读取评估与报告 |

## 9. 集成场景与测试

### 9.1 自动化

- `tests/selfcheck_v184.py`：**52 项**（Schema、过程统计、诊断、数据边界、评估隔离、导出、工作台契约、A–I 场景）；
- `tests/selfcheck_v184_round.js`：**14 项**（确定性 seed、过程计时、冷却、D 边界、未完成轮次）；
- `tests/selfcheck_v184_ui.js`：**17 项**（三栏、标签、双基线、评估横幅、儿童隔离、导出脱敏）；
- v1.8.3：52 项；v1.8.2：35 项；v1.8.1：33 项；
- 静态 UI：15 项；单轮 36 项；v1.8.3 单轮 8 项；监测 9 项；
- 去噪与计分映射全部通过；`py_compile`、`node --check`、inline script、`git diff --check` 通过。

### 9.2 场景覆盖

| 场景 | 验证 |
|---|---|
| A 新用户 | 档案、校准、长期参考、游戏、报告、难度 |
| B 同日连续 | 当日校准复用、Session 难度快照 |
| C 跨日 | 校准失效/重校，历史保留 |
| D 多用户 | 校准、积分、难度、评估隔离 |
| E 持续低速 | 难度记录与最低难度仍难诊断 |
| F 设备异常 | 断流/信号质量/校准过期诊断 |
| G 标准评估 | 固定参数、独立记录、不发奖励、不改难度 |
| H 重启 | 档案、校准、难度、评估恢复 |
| I 重复结算 | 报告/积分/难度幂等 |
| J 儿童模式 | 不创建监测/工作台，不订阅额外流 |

### 9.3 真实与模拟边界

- 工作台截图使用临时数据目录、EDF 真实回放与 `seedrpt1` 测试报告 fixture；该报告不是真实儿童记录，仅用于展示诊断/历史布局。
- 标准评估截图通过回放源启动，界面明确显示 `模拟标记：是`；不是真实硬件正式评估。
- 自动化、浏览器验收和 30 分钟稳定性均为本机开发模式；
- 没有真实 Xmuse 真机、儿童受试者或 Windows 实机；
- EDF 回放属于真实数据回放，不等于现场硬件/儿童可用性；
- 模拟评估结果明确标记 `simulation=true`，不进入纵向比较。

## 10. 稳定性测试

本机 28 轮、30 分 29 秒 headless Edge + 手动模拟：

- FPS 60–61，DOM 734 全程不变；
- JS used heap 2–4 MB，total 6–9 MB；
- 服务端 RSS 159–164 MB，后段稳定；
- SQLite Session 记录 0→27；该轮没有点击，所以 `rounds` 为 0；
- 无 `pageerror`；控制台 404 来自测试脚本故意打开不存在的报告 ID，不是工作台请求失败。

原始数据：`outputs/v1.8.4/stability.jsonl`；汇总：`outputs/v1.8.4/stability-summary.json`、`docs/STABILITY-v1.8.4.md`。

## 11. 已知问题与风险

1. `eval_sec`、逐轮点击行为仍由前端状态机上报；服务端只做边界/一致性校验，不逐帧重算，不能声称完整抗篡改。
2. 双基线曲线在回放/测试源中只能使用已有校准与长期参考；没有校准/参考时显示为空，不伪造曲线。
3. 当前标准评估只有 90 秒原型与数据记录，没有常模、完整成长报告或正式评分。
4. 回放/手动的标准评估是模拟评估，不可当作真实硬件纵向结果。
5. 真实硬件评估的参考基线兼容性依赖 device/algorithm 字段；旧数据缺少字段时只能做保守判断。
6. 诊断阈值（85% 信号、45s 活动、4–12s 目标、0.60 最低难度等）是工程参数，不是临床阈值。
7. SQLite 仍未静态加密；导出文件也未加密，依赖文件权限、OS 账户和磁盘加密。
8. 工作台是本地开发工具，不是远程多用户后台；访问边界是回环服务 + `X-User-Id` 归属校验，不是完整的远程认证。
9. 30 分钟稳定性测试验证的是本机 Edge/服务端资源趋势，不等于所有浏览器、真机或长时间临床使用。
10. 低难度安全下界使名义 14.4% 实际抬至 17%，是为了避免零/负蓄力距离；该差异已在报告中保留。

## 12. 自主技术决策

1. **保留 `game.html` 三栏而不是另建工作台页面**：减少重复 UI 和状态分叉；只在右栏加标签，中央游戏不变。
2. **诊断采用纯函数 + 证据列表**：允许同一 Session 多个瓶颈同时成立，不强行归因单一原因。
3. **`eval_sec` 不替换 `charge_sec`**：正式计分口径保持不变；诊断只读过程字段。
4. **标准评估复用同一游戏 Session 链路**：固定 `purpose=assessment` 和快照，避免复制游戏/算法。
5. **评估随机种子服务端生成、前端回放**：保证同一评估的黄色区域序列可追溯；日常游戏仍用随机。
6. **导出写本地 reports 再下载**：满足“用户主动导出、无自动上传”，同时让本地报告目录可见。
7. **Schema v4 原地迁移**：保留 v1.8.1–v1.8.3 历史；不重建表。
8. **回放/手动评估标记模拟**：宁可少一个“正式结果”，不把测试数据包装成真实纵向比较。

## 13. 文件清单

- `app/diagnostics.py`
- `app/dev_export.py`
- `app/storage.py`、`app/server.py`
- `web/game.html`、`web/dev.html`
- `web/assets/dev-workbench.js`、`web/assets/eeg-monitor.js`、`web/assets/focus-round.js`
- `web/assets/eeg-monitor.css`
- `tests/selfcheck_v184.py`、`tests/selfcheck_v184_round.js`、`tests/selfcheck_v184_ui.js`
- `outputs/v1.8.4/workbench-overview.png`
- `outputs/v1.8.4/workbench-baseline.png`
- `outputs/v1.8.4/workbench-difficulty.png`
- `outputs/v1.8.4/workbench-diagnostics.png`
- `outputs/v1.8.4/assessment.png`
- `outputs/v1.8.4/diagnostics-export.example.json`
- `outputs/v1.8.4/diagnostics-export.example.csv`
- `outputs/v1.8.4/stability.jsonl`
- `docs/STABILITY-v1.8.4.md`

## 14. 结论

v1.8.4 已把既有的监测、校准、双基线和难度能力纳入同一开发者工作台，并新增可解释的瓶颈诊断、过程统计、隔离标准评估和本地脱敏导出。它仍是工程原型：功能可观察、参数可追溯、问题可诊断，但尚不能替代临床评估，也不能宣称真机/儿童/Windows 验收完成。

## 15. 实际本机数据迁移

- 实际数据目录：`/Users/fan/Documents/专注小蛙`。
- 迁移后核验：Schema `4`，`users=1`（系统历史档案）、`sessions=6`、`calibrations=0`、`rounds=0`、`assessments=0`；没有把自动化测试档案写入真实目录。
- 迁移采用 `StorageManager` 的原地 `_ensure_columns` + 新表创建；没有重建 `users/sessions/calibrations` 历史表。
- 实际库在首次以 v1.8.4 代码打开时自动迁移；迁移后的回滚备份为 `backups/profiles-20261127-212339-before-v184-2929e.db`（内容为迁移后的 Schema 4，不是迁移前快照）。
- 另有一份 v1.8.3 之前的备份 `backups/profiles-reference-pre-v183-20261127-212345.db`（Schema 2，仅作历史参考；不是 v1.8.4 迁移前快照），以及 v1.8.3 之前已有的备份。
- 由于迁移发生在新代码首次打开，而不能在运行中的旧进程里先拍 Schema 3 快照，本次没有把不存在的“迁移前 Schema 3”文件冒充为备份；后续版本应在启动迁移前显式调用备份。
- 实际服务已重启为 `1.8.4`，`/openapi.json` 同时暴露 `/api/assessments` 与 `/api/dev/workbench`。
