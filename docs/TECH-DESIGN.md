# 技术设计：专注判定、蓄力与单轮计分

> 面向本仓库维护者的判定链路说明。系统结构、选型、数据模型与完整实测记录见工作区 `docs/Tech Design.md`；本文只收录“专注 → 分数 → 蓄力 → 子弹时间 → 跳跃 → 计分”这条链路上容易被误读、且改动风险最高的部分。
> 最后更新：2026-11-28（v1.9.1）

## 1. 判定链路

每 0.5 s 一帧，链路如下：

1. `sources.next_window()`：2 s 窗（`WINDOW_SEC=2`），步长 `STEP_SEC=0.5`
2. `features.extract()`：带通 0.5–45 Hz + Welch PSD → 每通道 11 维
3. `FocusEngine.update()`：`LogisticRegression.predict_proba` → `EMA_ALPHA=0.35` → `focus ∈ [0,1]`
4. `Session.score_of(focus)`：按校准区间映射为 20–80 动态分
5. `web/game.html`：平滑 → 45/38 分滞回 → 蓄力速度 / 宽容期 / 衰减 / 无效点击冷却
6. `web/assets/focus-round.js`：唯一金色区域 → 子弹时间 → 锁定脑电基础得分 → 按点击时机兑现 / 错过归零
7. **v1.7 监测支路**：`Session._publish_monitor()` 仅在开发者订阅 `/monitor` 时读取同一窗口的原始副本、`FocusEngine.last_debug` 与游戏状态；不参与上述控制链

| 参数 | 值 | 位置 | 作用 |
|---|---|---|---|
| `WINDOW_SEC` | 2 s | `app/features.py` | 单次推理窗口 |
| `STEP_SEC` | 0.5 s | `app/sources.py` | 帧节拍（2 帧/秒） |
| `EMA_ALPHA` | 0.35 | `app/focus_engine.py` | 概率平滑，抑制单窗抖动 |
| 分数映射 | `20 + 60·(focus−low)/(high−low)`，clamp 0–100 | `Session.score_of` | 个人定标，避免绝对阈值 |
| `MIN_SPAN` | 0.10 | `Session.calibrate` | 区间过窄时扩窗，防止噪声被放大成满格 |
| 专注滞回 | 进 45 / 出 38 | `web/game.html` | 阈值附近不反复启停 |
| 蓄力零点 `chargeZeroScore` | 42 分 | `focus-round.js` | 低于此分蓄力速度为 0，绝不出现负增益 |
| 蓄力增益 `chargeGainPerScoreSec` | 0.16 /(分·秒) | `focus-round.js` | `speed = max(0,(score−42)×0.16)` |
| 基准蓄力速度 `V_ref` | 3.68 %/s（分数 65） | `focus-round.js` | 计分归一化与衰减基准 |
| 宽容期 `graceSec` | 1.5 s | `focus-round.js` | 短暂走神不掉进度 |
| 衰减速度 `decayRatio` | `V_ref × 0.30` = 1.104 %/s | `focus-round.js` | 超过宽容期后缓慢回落 |
| 起始蓄力 `startEnergy` | 15 | `focus-round.js` | 每轮统一起点 |
| 金色区域宽度 `zoneWidth` | 6 % | `focus-round.js` | 固定宽度，位置随机 |
| 金色区域位置 | 24–55 %（首轮 22–34 %） | `focus-round.js` | 避免过长等待，同时保留随机性 |
| 子弹时间 `bulletTimeSec` | 2.5 s | `focus-round.js` | 所有玩家一致的点击窗口 |
| 满分宽容期 `fullScoreGraceSec` | 0.6 s | `focus-round.js` | 进入区域后前 0.6 s 点击不折损 |
| 最大时机折损 `maxTimingLoss` | 10 % | `focus-round.js` | 窗口末尾最低约 90% 基础分 |
| 无效点击冷却 `invalidTapCooldownSec` | 0.5 s | `focus-round.js` | 非金色区域点击暂停蓄力增长 |
| 成功反馈时长 `gainCueSec` | 1.0 s | `focus-round.js` | 青蛙附近 “+N” 的显示时间 |
| 脑电基础分 | `B = round(20 + 80×T_ref/(T+T_ref))` | `focus-round.js` | 蓄力越快基础分越高 |
| 实际积分 | `S = round(B × M(t))` | `focus-round.js` | 点击时机决定最终兑现 |
| 积分折算 `pointsDivisor` | 30 | `focus-round.js` | 商城积分 = `max(1, floor(本局积分/30))`（有得分时） |
| 断流判定 | 3 s 无有效帧 | `web/game.html` | 冻结蓄力、衰减、冷却、单轮计时与子弹时间 |
| 难度系数 | 0.60–1.20，默认 1.00 | `app/difficulty.py` | 只缩放黄色区域起点；Session 创建时锁定 |
| 净蓄力评估 `eval_sec` | 排除冷却/断流/暂停/子弹/跳跃 | `focus-round.js` | 仅用于局间难度判定，不替换计分 `T` |

所有可调参数集中在 `web/assets/focus-round.js` 的 `CONFIG`，真机测试只需改这一处；`web/game.html` 不重复写数值。`validateConfig()` 负责合法性检查（例如满分宽容期必须短于子弹时间），`normalizeConfig()` 把非法值收敛到安全范围。

## 2. 分数映射：为什么不能用绝对阈值

历史问题：早期实现直接以 `focus > 0.012` 作为触发条件。0.012 恰是某次 4 s 校准得到的 P50，而不是一个可推广的工作点，导致条件几乎恒真——0.25、0.5 乃至 0.05 都能蓄力，任何微弱信号都会攒满触发跳跃。

当前实现：

- `low/high` 取校准窗的 P10/P90，映射到 20–80 分；
- 区间跨度小于 `MIN_SPAN=0.10` 时，围绕中点扩展窗口，避免“窄区间放大噪声”；
- 校准返回 `range_quality ∈ {ok, stretched, default}`；`stretched/default` 时校准页提示“区分度偏低，建议重做”（只提示，不阻断）。

低基线实测（`q10/q50/q90 = 0.006/0.012/0.021`）扩窗后区间为 `[0, 0.10]`：

| focus | 映射分数 | 是否达到 45 分蓄力线 |
|---|---|---|
| 0.012（基线本身） | 27.2 | 否 |
| 0.021（q90） | 32.6 | 否 |
| 0.042 | 45.2 | 刚好越过 |
| 0.05 | 50.0 | 是 |
| 0.25 / 0.5 | 100（封顶） | 是（远高于个人基线的异常高值） |

结论：基线值本身不再触发；未校准的兜底区间 `[0.35, 0.75]` 下，0.5 也只有 42.5 分。

## 3. 蓄力、宽容期、衰减与无效点击冷却

- **正常蓄力**：`speed = max(0,(scoreSmooth−42)×0.16)` %/s，并钳制在 0–100。分数低于 42、或滞回在 38–45 之间时，公式可能算出负值；`max(0,…)` 修复了旧版“非预期负增益”路径。
- **有效蓄力条件**：`focused`（45/38 滞回）且 `scoreSmooth > 42`。只满足滞回、但分数已低于零点时不蓄力，进入宽容期。
- **宽容期**：连续低于条件不足 1.5 s 时只停止增长，能量保持不变。
- **衰减**：连续低于条件达到 1.5 s 后，以 `V_ref×0.30 = 1.104 %/s` 缓慢下降；重新达标立即停止衰减并恢复蓄力。能量最低到 0，不产生负值，也不清空历史积分。
- **进入金色区域后**：`phase = BULLET_TIME`，不再执行任何蓄力或衰减逻辑，能量只按固定子弹速度前进。
- **无效点击冷却**：正常蓄力阶段点击时，触发 0.5 s 冷却；冷却期间暂停能量增长，但**不额外衰减**、不清空进度、不扣分、不跳跃。冷却时间计入本轮 `T`，因此提前点击会间接降低基础分。冷却中再次点击不叠加、不延长；冷却结束后的独立无效点击可重新触发。冷却期间能量不会进入金色区域。
- **本轮计分 T**：从本轮开始累计，包含正常蓄力、低于阈值等待、宽容期、衰减、无效点击冷却；不包含信号异常、主动暂停、子弹时间、跳跃动画与视角平移。
- **本轮净蓄力 `eval_sec`**：v1.8.3 为局间难度另算，排除无效点击冷却，但保留等待/宽容/衰减；两者不可互换。
- **输入层防重复**：只认新的 `pointerdown`；键盘 `keydown` 忽略 `event.repeat`；长按不会自动起跳。动画、暂停、结算期间的点击直接忽略，不触发奖励或惩罚。

## 4. 金色区域、子弹时间与计分

### 4.1 每轮唯一区域

每轮开始时用 `zoneLoMin..zoneLoMax` 随机一次起点，宽度固定 6%，本轮内**不再重掷**。错过窗口后不会在蓄力条后方生成第二个区域，也不会继续等待蓄满；下一轮 `RESET` 时才重新随机。当前正式游戏构造未启用代码中的 first-round 分支，实际每轮使用服务端锁定的常规范围（默认 24–55%）；字段保留但不覆盖标准配置。

### 4.2 进入即锁定脑电基础分

首次 `energy >= zone.lo` 时：

1. 把能量精确钳到区域起点，防止大帧间隔越过整段；
2. 停止本轮蓄力计时；
3. 用 `D = zone.lo − startEnergy`、`T = 本轮有效用时` 计算并锁定**脑电基础分 B**；
4. 进入 `BULLET_TIME`，此后脑电分数、点击反应时间和信号波动都不再改写 B。

```
T_ref = D / V_ref
B = round(20 + 80 × T_ref / (T + T_ref))
```

- `T → 0` 时 B 封顶 100；`T → ∞` 时 B 趋近 20；
- `D=0`、`T` 异常、除零等情况回落到 20，且最终 clamp 到 `[20,100]`；
- 由于 `T_ref` 与 `D` 成正比，相同平均蓄力速度下，不同随机位置得到近似相同的 B（随机位置公平性；模拟极差 0 分）。

### 4.3 子弹时间与点击时机

- 固定 2.5 s 穿过整个区域：`slowSpeed = zoneWidth / bulletTimeSec = 6 / 2.5 = 2.4 %/s`。
- 窗口与玩家蓄力速度无关；慢速玩家和快速玩家都获得同样的 2.5 s 点击时间。
- 前 0.6 s 为满分宽容期；之后线性下降，窗口结束前最多折损 10%。
- 子弹时间内不再要求维持脑电阈值，点击造成的脑电波动也不影响已锁定的 B。
- 每个玩家每轮只触发一次；信号异常/暂停时 `bulletElapsed` 冻结，恢复后继续剩余窗口，而不是重新计时。
- 视觉：金色区域左深右浅渐变 + 轻微发光、蓄力条减速、青蛙压低身体呈蓄势姿态、背景轻微压暗；无倒计时、无公式、无倍率、无大面积粒子。

点击时机倍率：

```
M(t) = 1                                  0 ≤ t ≤ G
M(t) = 1 − R × (t − G) / (W − G)          G < t < W
M(t) = 0                                  t ≥ W
S = round(B × M(t))
```

默认 `G=0.6 s`、`W=2.5 s`、`R=0.10`。`B=76` 时：0.2/0.6 s → 76，1.0 s → 74，1.5 s → 72，2.0 s → 70，2.4 s → 69，超时 → 0。

> 点击时机是行为响应指标，不直接定义为真实注意力水平；脑电蓄力仍是主要计分依据。

### 4.4 点击与结算

| 输入 | 结果 |
|---|---|
| 正常蓄力阶段点击 | 触发 0.5 s 冷却；只累加 `early_taps`/`cooldown_count`，不扣分、不清空蓄力、不跳跃、无失败特效 |
| 冷却中再次点击 | 不叠加、不延长冷却；只累加提前点击次数 |
| 子弹时间内首次点击 | 按反应时间计算 M 和 S，完美跳跃；`settled=true`，后续输入忽略 |
| 子弹时间结束未点击 | 立即普通跳跃，`awarded=0`；不补区域、不等待 100%、不播庆祝反馈、不显示 +0 |
| 动画/平移/暂停/结算期间点击 | 忽略；不触发奖励或惩罚 |
| 长按 / 按键重复 | 只认第一次有效输入，重复事件不会再次结算 |

每轮只在 `finishRound()`（视角归位后）写一条记录，因此不存在重复入账或跨轮计时污染。

## 5. 单轮状态机

```
CHARGING ──进入金色区域──> BULLET_TIME ──点击──> JUMP_SUCCESS ─┐
    ^  │                         │                              │
    │  └─无效点击→冷却0.5s─┐      └──2.5 s 未点击──> JUMP_MISSED ─┤
    │                    │                                      │
    └──────────────────── RESET（动画结束、生成新区域）<─────────┘
```

- 冷却不是独立 `phase`，而是 `CHARGING` 内的子状态：暂停增长但继续计时，避免动画/状态机分叉。
- `PAUSED` 作为覆盖态实现：信号异常/主动暂停时冻结能量、衰减、冷却倒计时、单轮计时与子弹时间，恢复后回到原状态；不单独改写 `phase`。
- 动画期间 `phase` 保持 `JUMP_SUCCESS/JUMP_MISSED`，核心模块 `update()` 直接返回，不产生蓄力或第二次结算。
- `RESET` 只在 `pendingSettle` 与 `settling` 全部结束后执行，避免动画时间污染下一轮 `T`。

## 6. 异常与断流

| 情况 | 当前行为 |
|---|---|
| 单帧被伪迹门控（`usable=false`） | `focus = null`、`valid = false`；前端标记 stale，冻结蓄力、衰减、冷却、计时与子弹时间；恢复后继续，不把异常当走神 |
| 采样/推理异常 | `focus = null`、`valid = false`、`meta.error` 带原因，循环继续，不中断游戏 |
| 断流超过 3 s | 冻结蓄力、衰减、冷却、单轮计时与子弹时间；提示“正在等待信号，计时已暂停” |
| 信号恢复 | 收到有效帧后清除 stale，从冻结处继续，不把异常时长算作走神 |
| 校准窗口无帧 | 返回 500「校准期间未采集到足够信号帧」 |

> 设备异常只影响可用性，不判定为玩家注意力不足。异常时长单独记录在每轮 `stale_sec`，不进入 `T`、不触发衰减或冷却惩罚。

## 7. 数据记录与积分经济

每轮记录在 `actions.rounds`（后端 `RoundRecord`）：

`charge_sec`、`zone_lo`、`zone_hi`、`t_ref`、`potential`（脑电基础分 B）、`awarded`（实际积分 S）、`success`、`reaction_sec`、`multiplier`、`mean_score`、`above_ratio`、`decay_events`、`decay_sec`、`stale_sec`、`early_taps`、`cooldown_count`、`cooldown_sec`。

会话级汇总：`successful_jumps`、`missed_jumps`、`early_taps`、`cooldown_count`、`cooldown_sec`；报告页/导出另外计算金色时机命中率、每轮平均脑电基础分与每轮平均实际得分。

这些字段用于游戏平衡与研究分析，**不**等同于临床注意力水平，也不产生诊断/治疗结论。

积分经济：

- 儿童端只显示**本局累计积分**与成功后的 “+N”，不显示实时脑电分、蓄力百分比、潜在分或百分制评价；结算卡片单独显示“商城积分 +N”，避免与游戏积分同名；
- 报告/导出区分：脑电基础分 B（单轮 20–100）、实际积分 S（单轮 0–100）、本局累计积分、历史累计积分、商城可消费货币；
- 商城积分按 `max(1, floor(本局累计积分 / 30))` 折算（有得分时），例如 600 → 20 积分；
- 旧钱包余额、历史会话 JSON、成就阈值（均按游玩时长/打卡）保持不变，不清空、不迁移；
- 换算比例在 `CONFIG.pointsDivisor` 中集中配置。

当前模拟（90 s、点击 0.3 s）下，稳定 65 分的基础分约 60、实际积分约 60；稳定 100 分的基础分约 77。有效基础分范围约 29–77，高分段存在自然压缩（85→72、90→74、100→77），这是原公式饱和特性，不据此认定“玩家表现不足”。若后续要提高高分段区分度，优先做参数对比实验（例如调整 `vRefScore`），不直接乘倍数或强行拉满 100。

## 8. 回归自测

```bash
cd eeg-focus
node tests/selfcheck_round_logic.js        # 单轮机制：36 项，模拟脑电
node tests/selfcheck_ui_static.js          # 儿童端/监测静态检查：10 项
node tests/score_distribution.js           # 得分分布、时机折损、随机位置公平性
python tests/selfcheck_monitor.py          # v1.7 真实窗口/时间/特征/单位：9 项
python tests/selfcheck_score_mapping.py    # 分数映射：既有回归
python tests/selfcheck_denoise.py          # 去噪：既有回归
```

`selfcheck_round_logic.js` 覆盖：速度区分度、随机位置归一化、宽容期、衰减精度、间歇蓄力、唯一区域、子弹时间等长、点击时机满分/单调下降/最多折损、成功只结算一次、错过 0 分、提前点击冷却、冷却不叠加、冷却计时、冷却期间不衰减/不进入区域、异常与暂停冻结、长按/重复防刷、低帧率、多轮状态污染、数据字段与积分折算。

`selfcheck_ui_static.js` 防止儿童端重新出现实时分数/百分比/潜在分/“+0”，并检查报告与导出字段。

## 9. 已知取舍

- **显式冷却与宽容期的交互**：冷却期间低专注时间仍累计 `belowSec`，但不衰减；冷却结束后若已超过 1.5 s，会立即开始正常衰减。这是“冷却不额外惩罚，但也不掩盖真实低专注”的折中。
- **极低专注下的子弹速度**：`slowSpeed=2.4 %/s` 低于基准速度 3.68 %/s；但刚过蓄力零点（约 42–48 分）时，玩家正常蓄力速度可能低于 2.4 %/s，此时子弹时间不会更慢。该区间本身已接近得分下限，若真机反馈明显，应优先调 `zoneWidth`、`bulletTimeSec` 或蓄力增益，而不是放宽判定。
- **高分段压缩**：原公式在高分端趋于饱和，模拟有效范围约 29–77；这是保留既有脑电计分曲线的结果，不在本轮擅自替换公式。
- **主动暂停**：核心模块支持 `paused` 输入，但当前儿童端没有暂停按钮；仅信号异常会触发冻结。
- **低基线的相对性**：基线 0.012 的受试者在 0.05 即得 50 分，这是“相对个人”的正常结果；若校准区分度不足，应通过 `range_quality` 提示重做，而不是放宽判定。
- **真机未验证**：所有分布均为模拟脑电；Xmuse 真机、儿童受试者与低端平板帧率仍需实机验收。
- **监测批次节拍**：现有信号源 0.5 s 出一窗，监测也沿用该真实节拍，而非为了界面流畅伪造 100–200 ms 的新测量；波形绘制 30 FPS 不等于采样率。
- **21 通道回放带宽**：EDF 21 ch × 500 Hz × 原始+处理后两个数组，单批 JSON 约 0.3–0.4 MB；仅本机开发者模式使用，未做压缩/降采样传输。真机 4/6 ch 明显更小。
- **波形幅度自适应**：Canvas 为每个通道按当前窗 P95 自动定标并保留最小/最大值绘制；极端削顶仍可能超过可视区，需结合原始单位与质量标记判断，不能据此诊断。

## 10. v1.7 开发者实时监测数据链

### 10.1 数据阶段与真实性

| 数据 | 来源 | 是否真实 | 说明 |
|---|---|---|---|
| 原始 EEG | `sources.py` 在 `ArtifactCleaner` 之前复制 `seg` | 硬件/EDF 真实窗口 | 不来自分数反推，不随机生成 |
| 处理后 EEG | `FocusEngine.last_debug["processed"]` | 算法实际输入 | 与 `predict_proba`/`β/(θ+α)` 用的是同一个 `seg_f` |
| 频段功率 | `last_debug["powers"]/["relative"]` | 算法实际特征 | 硬件 4/6 通道走相对频段指标；EDF 走模型特征 |
| 平滑前后 | `FocusEngine.update()` 的 `raw/smooth` | 实际值 | 不使用前端另算 |
| 游戏分数 | `Session.score_of()` + 游戏 SSE | 实际值 | 与 HUD 同一映射 |
| 游戏事件 | 前端游戏状态机调用 `monitor.event()` | 实际事件 | 使用 `state.signalTime` + 帧间增量 |

原始/处理后共享同一窗口的 `sample_seq0/1`、`t0/t1`、`fs`，前端按 `sample_seq` 去重；断流缺号会留下 `sampleGaps` 并在图上标灰，不插值、不补 0。

### 10.2 时间基准

- **Xmuse**：OSC 报文没有逐样本硬件时间戳。`xmuse_osc.py` 在接收线程中以报文到达时间终点、配置采样率反推每个样本时间，并保存窗口快照；字段明确写 `time_basis="device_packet_arrival"`。
- **EDF**：使用文件内采样时间，`time_basis="edf_file"`，前端持续标注“历史 EDF 回放”。
- **游戏事件**：前端使用最近一帧后端 `t` 加 `performance.now()` 增量，不使用浏览器收到 SSE 的时间作为采集时间。
- **延迟展示**：状态栏的“最近数据”显示服务器会话语义时间与浏览器收到批次后的年龄；“实际采样率”在 Xmuse 下明确标为配置值，不是实测值。

### 10.3 传输与性能保护

- `GET /api/session/{sid}/monitor` 独立于游戏 `/stream`；只有该端点被订阅时才构造监测批次。
- 批次 0.5 s 一次，与现有 `STEP_SEC` 一致；不将 30 FPS 绘制称为采样率。
- Session 只保留最多 12 批内存历史；前端 `waveBatches` 按 12.5 s 裁剪、事件最多 240 条、频段/分数历史 30–32 s；页面隐藏/折叠时停止无效绘制。
- 原始/处理后数组只在内存；不写 `outputs/sessions`、不调用外部分析服务。

### 10.4 频段与单位口径

- 频段边界直接来自 `app/features.py`：δ 0.5–4、θ 4–8、α 8–13、β 13–30、γ 30–45 Hz。
- 现有 `band_power` 的相对功率分母是**同一窗 Welch PSD 全频段总功率（0–Nyquist）**，不是 0.5–45 Hz 频段和；面板按实际分母显示，避免误读。
- Xmuse OSC 原始数值的单位不由协议保证；去噪模块按幅值稳健推断，面板显示“µV（幅值推断）”或“设备原始单位”，不强行标 μV。EDF 显示“EDF 物理量”。

### 10.5 模式行为

| 模式 | 波形/频段 | 分数曲线/事件 | 标记 |
|---|---|---|---|
| Xmuse 真机 | 有原始/处理后 | 有 | 真机；无真机时不得称已验证 |
| EDF 回放 | 有真实历史窗口 | 有 | 历史回放 + 进度 |
| 手动试玩 | 明确“无脑电采样” | 有模拟游戏分数 | 模拟游戏 |
| 仅心率 | 明确“无脑电采样” | 有真实心率驱动分数 | 心率 |


## 11. v1.8.1 本地存储与档案边界

详细实现、Schema、API 与测试见 `docs/DEV-REPORT-v1.8.1.md`。这里只记录维护者最容易改错的部分。

### 11.1 主存储与缓存

- 权威数据：SQLite `profiles.db`（`app/storage.py`），默认在系统文档目录 `专注小蛙/`；`FOCUS_FROG_DATA_DIR` 只用于测试/便携启动。
- 浏览器 `localStorage` 的 `bf-*` 是当前档案缓存与旧版兼容层，不是多用户权威存储；页面隐藏时 `profile-bridge.js` 调 `/api/profiles/{id}/sync`。
- 数据目录指针是平台配置目录的 `location.json`，不是数据目录内的文件；避免迁移时把指针一起搬走。

### 11.2 归属校验

- `Session` 创建时写 `user_id`，之后不因前端切换档案而改变。
- 正常模式 API 用 `X-User-Id`；`EventSource` 的 `/stream`、`/monitor` 用 `?user_id=`。
- `finish`、`calibrate`、`manual`、报告读取/导出必须通过 `_session_for(sid, user_id)`；跨用户返回 403。
- 前端 gate 只是体验层，不能替代后端校验。

### 11.3 结算与回收

- 结算幂等键：`wallet_transactions.idempotency_key = session:<sid>`；重复 `finish` 不得重复加积分。
- 游戏页收到最终钱包后 `Wallet.replace(...)`，不要在游戏结束事件里再次本地加积分。
- 完成 Session 默认保留 900 s；只有 `finished=True`、`monitor_clients=0` 且超过 TTL 才释放内存。报告优先读 SQLite，回收后仍可访问。
- 校准追加写入 `calibrations`；`kind=daily` 为当前每日校准，`reference_baselines` 为后续长期基线，当前不计算。

### 11.4 迁移与备份

- 旧 `outputs/sessions` 仅导入 `hardware/heart`、非 demo、`played_sec > 0` 的报告；导入系统历史档案，不猜真实儿童归属。
- 旧 LocalStorage 必须由操作者选择目标档案并确认，导入前备份；不要自动复制给所有档案。
- 备份用 SQLite `backup()` 一致性快照；恢复前自动 `before-restore` 备份。数据库、报告、备份是不同的数据，删除档案不自动删除备份。


## 12. v1.8.2 每日校准与双基线实现

完整报告：`docs/DEV-REPORT-v1.8.2.md`。

### 12.1 阶段与有效时间

- 阶段：设备/信号检查 → `natural` 30s → `tutorial` 30s → 计算。
- 校准页只发阶段窗口和点击事件；服务端从 `Session.history` 按窗口重新过滤 `valid` 帧，`effective_seconds()` 用有效帧时间戳估计有效秒数。
- 样本 `<30` 或有效 `<20s`，或硬件 `artifact_summary.usable_ratio <0.50` → `CalibrationDataError`，API 422，不写有效校准。
- 两阶段各抽稀至最多 240 帧后合并，P15/P85 为 L/H；不按“自然=低、教学=高”强推。
- `range_quality=stretched` 时保留 0.10 最小跨度并显式提示；不静默放大。

### 12.2 日状态和锁定

- `calibration_date` + `timezone_offset_min` + `device_key` + `source_name` + `is_valid` + 4h TTL。
- 硬件 game 创建 Session：`calibration_status()` 有效 → 记录 id；无效 → 409。
- Session 使用记录中的 L/H，忽略前端 `score_low/high`；`purpose=game` 调 `/calibrate` → 409。
- `Session.apply_calibration()` 同时写入 `calibration_snapshot` 与 `reference_snapshot`；`S_reference` 只写统计/曲线。

### 12.3 参考基线与 Schema v2

- 首个 `source_name=hardware` 且 `status in (ok, stretched)` 的校准自动建 `reference_baselines` v1（`is_initial=1`）。
- 每日校准不会改动已有 active 参考；`POST /reference-baselines` 显式版本化，旧记录 `superseded` 保留。
- Schema v2 使用 `_ensure_columns()` + `ALTER TABLE ADD COLUMN` 原地补列；不重建 users/sessions/inventories。
- 新增字段见报告 §7；迁移测试在 `tests/selfcheck_v182.py`。


## 13. v1.8.3 自适应难度实现

完整报告：`docs/DEV-REPORT-v1.8.3.md`。

### 13.1 范围与 Session 锁定

- 参数集中 `app/difficulty.py`；默认 1.00，范围 0.60–1.20；只缩放黄色区域起点。
- `zone_low_min/max = 24/55 × factor`，宽度仍 6%，末端 ≤92%；系数 0.60 时名义 14.4% 低于起始能量 15%，实际下界抬至 17% 并保留 `nominal_zone_min` 审计。
- `POST /api/session` 对真实硬件正式游戏读取 `difficulty_profiles`，返回 `difficulty` 快照；游戏页重新建立 `RoundEngine`。当前 Session 不再读取个人档变化。

### 13.2 净蓄力与未完成轮次

- `RoundEngine` 新增 `evalSec`：只在 CHARGING 有效帧累计，排除断流、暂停、子弹时间、跳跃动画和无效点击冷却；等待/宽容/衰减仍计入。
- `chargeSec` 保持原计分口径（含冷却），不能把 `eval_sec` 替换进计分公式。
- 结束时仍在 CHARGING/BULLET_TIME 时 `pendingRound("time_up")` 上报 `incomplete_round`；包含 `eval_sec`、能量增长、区域、是否进入和结束原因。未完成轮次不进入完整轮次中位数。

### 13.3 局间判定

- 服务端在报告成功保存后调用 `storage.record_difficulty()`；以 `difficulty_history.session_id` 唯一索引保证重复 finish 不重复调整。
- 中位净值 >12s 连续 2 局 → ×0.90；<4s/点击≥85%/进入≥3 连续 3 局 → ×1.10；4–12s 保持。
- 信号 <70%、活动 <45s、计划 <60s、无有效能量、点击/乱序瓶颈均不调整；`BEHAVIOR_BOTTLENECK` 不处理子弹时间/点击窗口。
- 重新校准、换设备、改策略、手动改档清空连续计数但保留系数；自动关闭时仍写最近指标。

### 13.4 Schema v3 与 API

- 新增 `difficulty_profiles` 和扩展 `difficulty_history`；`SCHEMA_VERSION=3`，`_ensure_columns()` + `ALTER TABLE` 原地迁移。
- `GET/POST /api/profiles/{id}/difficulty`；手动设置只对下一局生效，旧 Session 快照不变。
- 真实硬件、`purpose=game`、非 demo 才写档案；replay/manual/heart/test 返回 source isolation，不写真实儿童档案。

### 13.5 计分与经济边界

- `B=round(20+80×T_ref/(T+T_ref))`、`S=round(B×M)` 未改；`D` 用实际区域距离。
- 难度降低会增加可完成次数，累计积分/商城货币可能增加；不能把累计积分当脑电表现改善证据。
- 固定种子模拟见 `scripts/simulate_v183.py` 和 `outputs/v1.8.3/simulation.json`。


## 14. v1.8.4 开发者工作台、诊断与标准评估

### 14.1 工作台边界

- `game.html?dev=1` 保留 v1.7.0 三栏；右栏新增 `概览/基线/难度/诊断/评估导出` 标签页。
- `DevWorkbench` 只在 `developerRun && EEGMonitor` 之后实例化；儿童模式不请求 `/api/dev/workbench`，也不建立额外 SSE。
- 游戏 Canvas 不被抽屉覆盖；窄屏沿用原有左右侧栏收起按钮。

### 14.2 双基线

- `scorePoints` 同时保存 `daily`（`f.score`/`daily_score`）与 `reference`（`f.reference_score`），两者来自同一 `focus_fused` 与同一帧时间戳。
- 曲线用断开段表示无效信号/数据缺口；不插值、不把缺失段连成直线。
- 原始/平滑游戏分数另图展示；长期参考不参与蓄力/得分/商城。

### 14.3 过程统计与诊断

| 字段 | 口径 |
|---|---|
| `charge_sec` | 正式计分，含冷却；不含断流/暂停/子弹/跳跃 |
| `eval_sec` | 评估净用时，不含冷却/断流/暂停/子弹/跳跃 |
| `charge_active_sec` | 有效蓄力 |
| `below_threshold_sec` | 低于阈值的非冷却时间 |
| `energy_gain_total/energy_loss` | 累计正增益/衰减 |
| `bullet_sec/jump_anim_sec/paused_sec` | 过程观察 |

- `diagnostics.charge_process()` 只汇总报告字段；缺失字段保留 `null`，不用减法伪造。
- `diagnostics.diagnose()` 返回 9 类可并存的工程状态及证据；`insufficient_data` 在数据不足时优先提示，不输出医学结论。
- `diagnostics.validate_actions()` 检查重复轮次、负时间、`eval_sec > charge_sec`、`eval_sec > active + below`、Session 时长；异常轮次不参与难度，正式计分链路不重算。

### 14.4 标准评估

- `POST /api/assessments` → `purpose=assessment`、`standard_v1`、90s、固定 1.00、服务端 seed；前端 `FocusRound.makeRng(seed)` 复现黄色区域序列。
- `assessments` 保存协议/参数/校准/参考/设备/特征/行为/报告；`session_id` 唯一、完成幂等。
- 真实硬件要求当日有效校准 + 长期参考 + 设备/算法兼容；回放/手动明确 `simulation`，不产生可纵向比较结果。
- 评估不写难度、不发积分/成就、不改校准/参考；本阶段不做完整成长报告。

### 14.5 导出

- JSON/CSV 由用户主动调用，写数据目录 `reports/`；不含昵称与原始高频 EEG，不自动上传。
- 导出使用 `data_quality`、`charge_process`、`diagnostics` 与服务端运行时快照；浏览器另行下载同一内容。

### 14.6 Schema v4

- `SCHEMA_VERSION=4`；新增 `assessments`、`sessions.purpose/assessment_id`、`rounds` 过程列。
- 仍使用 `_ensure_columns()` 原地 `ALTER TABLE`；迁移不重建用户/历史表。


## 15. v1.9.0 成长中心口径（实现约束）

### 9.1 记录分类

- 正式游戏：`purpose=game`、`demo=0`、`source.name in {hardware, heart}`；
- 标准评估：`purpose=assessment` 且 `assessment.simulation=0`；
- 模拟/回放：`demo=1`、`source.name in {manual, replay}` 或 `assessment.simulation=1`；
- 校准教学：来自 `calibrations`，不当作游戏局数。

### 9.2 缺失与分母

- 不用 0 代替缺失指标；无有效分母时显示“数据不足”；
- 点击成功率 = 成功 ÷（成功 + 未成功完成）；
- 反应时间中位数只取成功且有 `reaction_sec > 0` 的轮次；
- 净蓄力中位数只取完整轮次的 `eval_sec`；未完成轮次单列；
- 有效信号比例只在同时有 `n_valid_frames` 和 `n_frames` 的正式硬件局上汇总。

### 9.3 标准评估条件键

同段比较要求 `device_key`、`algorithm_version`、`mapping_version`、`reference_baseline_id/version`、`protocol_version`、`planned_sec`、`fixed_factor` 和难度参数版本一致；当前没有跨设备兼容映射，因此不同设备键直接分段。seed 不作为条件键，只记录随机任务序列；同一协议下不同 seed 属于正常差异。

### 9.4 导出

`growth.build_report()` 为唯一数据源；`growth_export.build_pdf/xlsx/json/csv()` 不得各自重新计算指标。PDF/Excel 写出到 `reports/` 的临时文件，完成后原子替换；没有记录时返回 409，不生成空白文件。PDF 使用本机中文字体回退，测试以 pypdf 检查页数与中文文本；Excel 以 openpyxl 检查工作表。
