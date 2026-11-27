# 专注小蛙 v1.8.2 开发报告：每日游戏化校准与双基线

> 日期：2026-11-27  
> 仓库：`https://github.com/mujiu07/eeg-focus`  
> 基准：v1.8.1（提交 `a729df9`）  
> 协议：`daily_v2`；映射：`map_v2`  
> 范围：每日校准、自然观察 + 教学、双基线、Session 锁定、Schema v2  
> 非范围：自动难度、黄色区域自适应、新蓄力/计分公式、完整成长报告、桌面安装包、云同步、新玩法

---

## 1. 结果摘要

v1.8.2 在 v1.8.1 的 SQLite 与多档案基础上，把校准从“约 1 小时的旧基线”改为：

1. **每日首次真实硬件 EEG 游戏前必须完成当日校准**；同日、同设备、4 小时内可复用。
2. **每日校准阶段化**：设备/信号检查 → 自然观察 30 秒 → 游戏教学 30 秒 → 结果；不以页面停留时间代替有效采集时间。
3. **每日校准和长期参考基线分离**：每日校准驱动游戏，长期参考只做后台趋势；每日不会覆盖长期版本。
4. **正式游戏锁定**：服务端在创建 Session 时重新校验并锁定 `calibration_id`、L/H 和参考快照；游戏中调用校准接口直接 409。
5. **Schema v2 原地迁移**：保留 v1.8.1 用户、钱包、装扮、游戏历史；新增校准状态/设备指纹/阶段统计/双快照列。

本机验证是 **模拟/开发模式 + 现有测试**，不是儿童或真机临床验证。

## 2. 校准流程

### 2.1 阶段一：设备与信号检查

儿童端先等待真实有效帧。硬件默认 15 秒、心率默认 26 秒没有有效帧则给出设备提示，不把设备问题描述为注意力不足。

提示使用：

> 准备好啦，我们先陪小蛙坐一会儿。

### 2.2 阶段二：自然观察

- 目标 **30 秒有效数据**；`valid=false` 或 `focus=null` 的帧不进入统计。
- 不显示实时分数、百分制、上下限、频段或波形。
- 不播放旧放松视频；画面保持池塘/小蛙的安静视觉。
- 有效时间按有效帧时间戳估计，不按页面停留时间。
- 最长等待 75 秒；低于 20 秒有效数据则失败并提示重试，不生成虚假校准。

### 2.3 阶段三：游戏教学

- 目标 **30 秒有效数据**。
- 校准页内嵌轻量蓄力教学：绿色蓄力条、随机黄色区域、点击/回车/触摸；记录点击时刻与蓄力值。
- 不启动正式游戏计分、不发商城币、不计成就；点击早晚都没有惩罚。
- **实现说明**：本次没有启动完整 `game.html` 的 3D 池塘结算链路，而是在校准页复用“蓄力条/黄色区域/点击兑现”的基本交互语义。这是为了让校准页能保持低认知负荷并直接采集阶段边界；完整游戏物理和计分未改。报告中不把它描述成真实正式游戏。
- 有效时间、样本和统计仍由服务端按历史帧重新计算；前端事件只用于交互记录，不改变 EEG 参考统计。

### 2.4 阶段四：结果

儿童端只显示：

> 小蛙准备好啦！  
> ✓ 今日有效

不显示 L/H、分位、分数高低或与他人比较。家长/开发者可在档案页、开发者监测中查看详情。

## 3. 参数配置

实现位置：`app/calibration.py` 的 `CONFIG`；前端阶段显示常量在 `web/calibrate.html` 的 `STAGE_CFG`（仅显示，最终门槛在服务端）。

| 参数 | 默认值 | 说明 |
|---|---:|---|
| 自然观察目标 | 30 s | 有效采集，不是页面停留 |
| 游戏教学目标 | 30 s | 有效采集 |
| 单阶段最长等待 | 75 s | 允许信号波动后继续 |
| 单阶段最低有效时间 | 20 s | 不足则拒绝保存 |
| 单阶段最低样本 | 30 | 防止低采样率伪造 |
| 低/高端分位 | P15 / P85 | 两阶段等权抽稀后计算 |
| 低/高端映射分 | 20 / 80 | 游戏驱动 `S_daily` |
| 最小映射跨度 | 0.10 | 沿用 v1.8.1；不足时围绕中点扩张并标记 `stretched` |
| 每日有效期 | 4 h | 同日、同设备、有效记录；跨日强制重校 |
| 阶段等权上限 | 240 帧/阶段 | 防止某一阶段靠样本量主导 |
| 信号可用率门槛 | 50% | 低于则拒绝保存 |
| 长期基线自动覆盖 | 禁止 | 只能显式版本化新增 |

这些是工程原型配置，不是临床 ADHD 训练标准。

## 4. 当日校准算法

代码：`app/calibration.py::compute_daily_range()`。

1. 从每个阶段只取 `valid` 且 `focus` 非空的帧。
2. 阶段统计分别记录 `n / n_invalid / effective_sec / q15 / q50 / q85 / mean / min / max`。
3. 两阶段各抽稀到最多 240 个样本（阶段等权），合并后取 P15/P85。
4. 不使用单帧最小/最大值，不把教学阶段强行标成高分。
5. 记录阶段均值差 `stage_contrast`：
   - `|contrast| < 0.02` → `flat`（只记录，不诊断异常）；
   - 正/负 → `tutorial_higher` / `natural_higher`。
6. 若 `high-low < 0.10`：
   - 围绕中点扩到 0.10；
   - `range_quality="stretched"`，前台明确提示；
   - 不静默伪装成灵敏区间。

游戏驱动公式保持原样：

```text
S_daily = clip(20 + 60 × (x - L_daily) / (H_daily - L_daily), 0, 100)
```

- `x` 仍来自原 EEG 算法/融合链路，没有修改底层特征算法。
- `L_daily/H_daily` 是当日校准的 P15/P85。
- 信号质量、平滑、融合逻辑保持原有实现。

## 5. 双基线

### 5.1 当日校准

每次通过门槛的硬件校准写一条 `calibrations`：

- `calibration_id / user_id / session_id`
- `calibration_date / calibrated_at / timezone_offset_min`
- `source_name / source_info / device_key`
- `protocol_version=daily_v2 / mapping_version=map_v2`
- `range_low/range_high / q10/q50/q90`（q10/q90 列兼容，v2 实际为 P15/P85）
- `stages_json / effective_sec / elapsed_sec / n_frames / signal_quality`
- `status=ok|stretched|legacy|... / is_valid`
- `reference_baseline_id`

同日可有多条记录；服务端取同日期、同信号源、同设备、未过期的最新有效记录。

### 5.2 长期参考基线

- 首个通过质量检查的**真实硬件**每日校准自动建立 `reference_baselines` v1，标记 `is_initial=1`。
- 回放、手动、合成 OSC、仅心率、demo 不会建立真实长期参考。
- 每日校准只写 `calibrations`，不会自动改动已存在的参考基线。
- 显式 `POST /api/profiles/{user_id}/reference-baselines` 可从某个有效硬件校准建立新版本（v2、v3…）；旧版本保留并将 `is_active=0 / status=superseded`。
- 参考基线记录设备、算法、协议、映射、阶段统计和来源，便于判断跨设备/算法可比性；本版本不会自动合并不可比数据。

### 5.3 两套映射

同一份有效 `x`：

- `S_daily`：`Session.score_of(x)`，用于蓄力/判定/得分。
- `S_reference`：`Session.score_reference(x)`，仅写入 SSE 监测、报告曲线和汇总。

`S_reference` **不参与** `FocusRound`、得分、钱包、商城、成就。报告保留 `reference_score_mean/max/min`、曲线 `reference_score` 和两份快照。

## 6. 每日状态、失效与锁定

### 6.1 当日复用条件

同时满足：

- 同一 `user_id`；
- 同一本地日期；
- 同一 `source_name` + `device_key`；
- `is_valid=1`；
- 未超过 4 小时；
- `kind=daily`（测试/回放记录不参与）。

### 6.2 重新校准

以下情况由状态接口返回 `date_changed / expired / device_changed / missing`，游戏入口要求重校：

- 跨本地日期；
- 超过 4 小时；
- 更换设备/端口/采样配置；
- 重新佩戴、长时间中断、用户主动重校；
- 校准记录无效或不足。

短暂波动/单局表现下降不触发自动重算。

### 6.3 正式游戏锁定

- `POST /api/session` 的 `purpose=game` + `mode=hardware`：无当日有效校准时返回 **409 `daily_calibration_required`**。
- 有校准时，服务端用 `calibration_status` 选出的记录覆盖前端传来的旧 `score_low/score_high`，并把 `calibration_id` 固定到 Session。
- Session 创建时读取当前长期参考，写入 `reference_snapshot`。
- `POST /api/session/{sid}/calibrate` 对 `purpose=game` 返回 **409**；正式游戏期间不能在后台重新校准。
- 前端 game 捕获 409，提示“今天还没有完成校准”并跳回校准页。

## 7. 数据结构与迁移

Schema 版本：`2`。

### 7.1 新增/补充列

`calibrations`：

- `calibration_date`、`timezone_offset_min`、`device_key`
- `protocol_version`、`mapping_version`
- `stages_json`、`effective_sec`、`elapsed_sec`
- `status`、`reference_baseline_id`

`reference_baselines`：

- `version`、`q15`、`q85`、`n_frames`
- `protocol_version`、`mapping_version`、`device_key`、`stages_json`
- `is_initial`、`status`、`superseded_by`

`sessions`：

- `reference_baseline_id`
- `calibration_snapshot_json`
- `reference_snapshot_json`

### 7.2 迁移方式

- 不重建表；`_migrate()` 在 v1.8.1 数据库上执行 `PRAGMA table_info` + `ALTER TABLE ADD COLUMN`。
- 先写 v2 版本记录，再保留 v1 版本记录；新数据库同时有 1/2 版本。
- 原有 users/wallet/inventories/achievements/sessions/rounds 不删除、不覆盖。
- 备份/恢复仍使用 v1.8.1 的一致性快照；v2 迁移后可正常备份。

## 8. API

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/profiles/{user_id}/calibration-status?mode=hardware&device=...&tz_offset_min=...` | 当日状态、原因、记录 |
| GET | `/api/profiles/{user_id}/reference-baselines` | 当前/历史长期参考 |
| POST | `/api/profiles/{user_id}/reference-baselines` | 从有效硬件校准显式建新版本 |
| POST | `/api/session` | `purpose=game|calibration`；硬件游戏每日门槛 |
| POST | `/api/session/{sid}/calibrate` | `daily_v2` 阶段窗口/统计；游戏 Session 409 |
| GET | `/api/session/{sid}/stream` | 增加 `daily_score` / `reference_score` / 校准/参考 id |
| GET | `/api/session/{sid}/monitor` | 监测批次增加当日/参考映射字段 |

## 9. 信号源隔离

| 信号源 | 每日硬件门槛 | 可建长期参考 | 保存校准 |
|---|---|---|---|
| Xmuse hardware | 是 | 是（首个有效硬件） | `kind=daily` |
| EDF replay | 否 | 否 | `kind=test` |
| 手动模拟 | 否 | 否 | `kind=test` |
| 合成 OSC | 作为 hardware 时会受硬件门槛 | 仅有效硬件；合成数据需开发者明确验证 | 视来源 |
| 仅心率 | 否（不是 EEG） | 否 | `kind=test` |

测试/回放不会覆盖真实每日校准，也不会创建真实儿童长期参考。仅心率不会伪装成 EEG。

## 10. 验证

新增 `tests/selfcheck_v182.py`：**35 项通过**。覆盖：

- 配置 30/30/P15/P85；
- 两阶段统计与有效时长；
- 阶段反差只记录、不强制；
- 极窄跨度保护；样本不足拒绝；
- 当天复用、跨设备、超时、跨日；
- 首个硬件校准建 v1 参考；每日不覆盖；显式 v2 并保留 v1；
- 回放不建参考；
- 用户隔离；
- 无当日校准硬件游戏 409；
- 正式游戏锁定量程/参考快照；
- Session 报告保存双映射与两份快照；
- 新协议阶段窗口/有效时长/保存/参考；
- 正式游戏内校准 409；
- v1.8.1 数据库原地迁移到 v2，保留用户/钱包。

其他回归：

```text
tests/selfcheck_v181.py       33/33
selfcheck_ui_static.js        14/14
selfcheck_round_logic.js      36/36
selfcheck_monitor.py           9/9
selfcheck_denoise.py           14/14
selfcheck_score_mapping.py    通过
python -m py_compile app/*.py 通过
node --check assets            通过
```

截图（Calibrate 流程使用开发者手动模拟，不是儿童真机）：

- `outputs/v1.8.2/profiles.png`
- `outputs/v1.8.2/calibrate-idle.png`
- `outputs/v1.8.2/calibrate-natural.png`
- `outputs/v1.8.2/calibrate-tutorial.png`
- `outputs/v1.8.2/calibrate-done.png`

## 11. 未完成事项

1. **未用真实 Xmuse/儿童验证**：所有阶段截图用开发者手动模拟；真机采样率、电极接触和儿童可用性未验收。
2. **未启动完整 3D 跳跃游戏作为教学**：当前是校准页内嵌轻量蓄力条/黄色区域/点击；正式游戏物理与计分未改。
3. **未做自动难度、黄色区域距离自适应、新蓄力/计分公式**。
4. **长期参考 v1 不是临床稳定能力基线**；只是首个有效真实硬件校准，不能宣传为 ADHD/注意力诊断。
5. 未做完整的跨设备/跨算法可比性自动判断；显式建新版本时由操作者负责检查来源。
6. 未做桌面安装包、云同步；SQLite 未静态加密。
7. 未新增原始高频 EEG 永久保存。
8. Windows 未实机验收；macOS 路径/浏览器流程通过。
9. “重新佩戴”无法由软件自动检测，依赖用户主动重校或设备指纹变化；文档/界面提示。
10. 校准教学点击只记录交互日志，不参与 EEG 分位；未做点击窗口的额外伪迹建模（依赖现有去伪迹/valid 帧）。

## 12. 自主技术决策

| 决策 | 理由 | 代价 |
|---|---|---|
| 每日 P15/P85，阶段等权 | 不让教学样本量或高/低标签主导 | 阶段差异大时仍可能区间偏宽；记录 contrast |
| 4 小时 + 本地日期 | 让同日连续游戏而不过度复用旧状态 | 长时中断需重校 |
| 服务端重算阶段有效时间 | 防止只靠页面计时/伪造 | 需要同步历史帧窗口 |
| 首个真实硬件校准自动建 v1 | 满足“首次通过质量检查”的初始参考 | v1 不代表长期稳定能力 |
| 每日校准不自动更新参考 | 保留长期变化 | 参考会逐渐变旧，需要显式版本化 |
| Session 创建时锁定量程/参考 | 正式游戏不可偷偷重算 | 中途换设备需结束本局 |
| 校准页轻量教学 | 低认知负荷、阶段边界清晰 | 没有完整游戏物理；报告明确标注 |
| Schema 原地 ALTER | 不重建、不丢 v1.8.1 数据 | 需要保留兼容列/迁移测试 |

## 13. 关键文件

- `app/calibration.py`
- `app/storage.py`
- `app/accounts.py`
- `app/server.py`
- `web/calibrate.html`
- `web/game.html`
- `web/profiles.html`
- `web/assets/api.js`
- `web/assets/profile-bridge.js`
- `web/assets/eeg-monitor.js`
- `tests/selfcheck_v182.py`
- `docs/DEV-REPORT-v1.8.2.md`
