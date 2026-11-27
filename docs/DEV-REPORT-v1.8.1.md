# 专注小蛙 v1.8.1 开发报告：本地存储与多用户档案

> 日期：2026-11-27  
> 仓库：`https://github.com/mujiu07/eeg-focus`  
> 基准：v1.7.0（提交 `8a0559f`）  
> 范围：本地 SQLite、多用户档案、个人数据隔离、旧数据迁移、备份恢复、Session 回收  
> 非范围：桌面封装、安装程序、云端账号、新的校准算法、自适应难度、脑电/计分公式修改

---

## 1. 结果摘要

v1.8.1 把个人档案、校准、游戏历史、逐轮数据、钱包流水、装扮/成就和用户设置从“浏览器 `localStorage` + 内存 Session + `outputs/sessions` JSON”迁移到本机 SQLite 主存储。

- 数据目录不依赖源码工作目录：macOS 实际为 `~/Documents/专注小蛙/`，Windows 通过 Shell API 读取“文档”实际位置（含 OneDrive 重定向）。
- 新增 `web/profiles.html`：首次使用创建档案，之后按头像/昵称选择；支持编辑、删除二次确认、最近使用排序、切换档案。
- 新增 `web/settings.html`：查看数据目录/磁盘/数据库状态、打开文件夹、迁移目录、备份与恢复、隐私说明。
- Session 创建时固定绑定 `user_id`；后端在 `finish`、`calibrate`、`manual`、`stream`、`monitor`、报告读取和导出上校验归属，不能只靠前端隐藏。
- 服务器结算按 `session_id` 幂等写入钱包流水；重复 `finish` 不会重复加积分。
- 已完成 Session 在 900 秒宽限期后被回收，报告仍从 SQLite 读取。
- 测试使用临时目录和虚构档案；本报告不包含真实儿童数据。

## 2. 数据存储架构

```
Documents/（实际系统文档目录，Windows 可能被 OneDrive 重定向）
└── 专注小蛙/
    ├── profiles.db          SQLite：档案、校准、游戏、资产、设置、流水
    ├── settings.json        应用级设置（不含昵称/校准/脑电）
    ├── reports/             本机报告 JSON（数据库为主索引）
    ├── recordings/          经明确授权才写入的原始录制目录（本阶段默认不写）
    └── backups/             SQLite 一致性快照备份
```

实现：`app/storage.py`，API：`app/accounts.py`。

### 2.1 路径选择

1. 测试/便携启动可设置 `FOCUS_FROG_DATA_DIR`，其优先级高于用户指针。
2. 普通启动读取 `platform_config_dir()/location.json` 中的 `data_dir` 指针。
3. 没有指针时使用平台文档目录 + `专注小蛙`。
4. 修改目录时只接受绝对路径；拒绝磁盘根、系统目录、当前目录内部或父目录；目标必须为空且可写。
5. 修改目录要求 `confirm=true`；默认先创建当前库备份，再复制到目标目录，旧目录保留。

本机实际验证路径：

```text
/Users/fan/Documents/专注小蛙
```

**Windows 实机未验收**：代码使用 `SHGetFolderPathW(CSIDL_PERSONAL)` 读取实际文档目录，macOS 使用 `~/Documents`；Windows 的 OneDrive 重定向和中文路径只做了代码层兼容设计，未在本机 Windows 运行。

### 2.2 云同步提示

`cloud_sync_hint()` 会识别 OneDrive、iCloud Drive、Dropbox、Google Drive、坚果云路径，并在设置页显示“可能被云同步”的黄色提示。本阶段**不实现**云同步/上传，也不会静默把数据放到同步目录。用户可以选择非同步的本地目录。

### 2.3 文件权限

- 数据根目录、`reports/`、`recordings/`、`backups/` 尝试设置 `0700`。
- `settings.json`、`profiles.db` 尝试设置 `0600`。
- 权限设置失败不会阻断应用，但状态页仍显示“SQLite 未加密”；不能把文件权限当成加密。

## 3. SQLite 结构

Schema 版本：`1`，记录在 `schema_version`。迁移只执行 `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`，重复启动不覆盖已有数据；未来 Schema 变更应追加迁移函数，不修改既有列语义。

| 表 | 主要字段 | 用途 |
|---|---|---|
| `users` | `user_id`, `nickname`, `avatar`, `created_at`, `last_used_at`, `status`, `is_system`, `wallet_balance`, `wallet_meta` | 个人档案与钱包余额 |
| `calibrations` | `calibration_id`, `user_id`, `session_id`, `kind`, `baseline`, `q10/q50/q90`, `range_low/high`, `calibrated_at_ms`, `method`, `source_info`, `n_frames`, `signal_quality`, `algorithm_version`, `params_version` | 每次校准追加；历史不覆盖；为双基线预留 `kind` |
| `reference_baselines` | `baseline_id`, `user_id`, `label`, `baseline`, `range_low/high`, `valid_from/until`, `source_info`, `algorithm_version`, `is_active` | 长期参考基线预留（本阶段不计算） |
| `sessions` | `session_id`, `user_id`, `started_at/ended_at`, `duration_sec`, `played_sec`, `calibration_id`, `algorithm_version`, `params_json`, `source_json`, `demo`, `total_score`, `wallet_points`, `jumps/successful/missed`, `eeg_base_score`, `actual_score`, `valid_signal_ratio`, `difficulty_snapshot_json`, `report_json`, `finished` | 每局游戏记录；报告快照 |
| `rounds` | `session_id`, `user_id`, `round_no`, `charge_sec`, `reaction_sec`, `potential`, `awarded`, `success`, `multiplier`, `mean_score`, `above_ratio`, `early_taps`, `cooldown_count/sec`, `raw_json` | 逐轮跳跃记录 |
| `difficulty_history` | `user_id`, `session_id`, `config_json`, `reason` | 未来自动难度快照预留 |
| `inventories` | `user_id`, `item_id`, `kind`, `acquired_at`, `equipped`, `metadata_json` | 已购装扮/已解锁内容，跨用户唯一 |
| `wallet_transactions` | `transaction_id`, `user_id`, `amount`, `kind`, `session_id`, `idempotency_key`, `balance_after` | 可追溯积分流水；`idempotency_key` 唯一 |
| `achievements` | `user_id`, `achievement_id`, `unlocked_at`, `seen` | 成就独立存储 |
| `user_settings` | `user_id`, `setting_key`, `value_json` | `bf-checkin`、`bf-outfit.*`、`bf-heart*` 等非表格设置 |
| `recordings` | `recording_id`, `user_id`, `session_id`, `path`, `consent` | 预留录制授权表；本阶段默认不写原始 EEG |
| `legacy_imports` | `import_key`, `kind`, `detail`, `imported_at` | 旧 JSON / 旧 LocalStorage 幂等迁移标记 |

### 3.1 校准双基线预留

`calibrations.kind` 目前写 `daily`，`reference_baselines` 已建立但本阶段不计算长期基线。每一条校准记录保留日期、来源、有效帧、质量、上下限、算法/参数版本；下一次校准只新增行，不更新旧行。

### 3.2 事务与幂等

- 所有关键写入使用 `with self._db()`，异常回滚。
- `PRAGMA foreign_keys = ON`、`busy_timeout = 5000`、WAL。
- 会话积分使用 `wallet_transactions.idempotency_key = session:<session_id>`；重复 `finish` 查重后不再增加钱包。
- 逐轮 `UNIQUE(session_id, round_no)`，重试只更新同一轮。
- 浏览器资产同步使用状态哈希作为幂等键的兜底；同一个快照重复同步不重复入账。

## 4. 多用户档案

### 4.1 页面与交互

`web/profiles.html`：

- 标题：“今天谁来陪小蛙玩？”
- 头像 + 昵称卡片；当前档案有绿色边框和“当前”角标。
- 新建档案：昵称 1–20 字符 + 6 个内置头像。
- 编辑昵称/头像；删除需要两次确认，并提示报告/资产范围及备份残留。
- 最近使用排序；选择档案后加载服务端 bootstrap，再进入原流程。
- 当前有未结束的 `bf-live-session` 时，阻止切换到其他档案。
- 旧版 LocalStorage 数据只在用户明确选择目标档案并确认后导入；不自动分配给所有孩子。

### 4.2 入口

- 首页“开始游戏”“进入脑电校准”在未选择档案时跳转 `profiles.html`。
- 游戏/校准页正常模式要求已有档案；开发者 `?dev=1`、`?test=...` 测试路径保留。
- 首页显示当前档案昵称；点击进入档案管理。
- 数据与隐私设置：`settings.html`。

### 4.3 适用范围

这是**本机多档案隔离**，不是联网身份认证。拥有同一操作系统账户和文件读取权限的人仍可读取 SQLite；本阶段没有登录、云端账户或静态加密。设置页明确显示这一点。

## 5. 用户数据隔离

| 风险 | 实现 |
|---|---|
| A 加载 B 的校准 | 校准按 `user_id` 查询；创建 Session 指定 `calibration_id` 时校验所属档案；前端 bootstrap 只取本人最新校准 |
| A 的游戏记录写入 B | Session 创建时 `user_id` 固定；`finish`/`calibrate`/`stream`/`monitor`/报告/导出都校验 `X-User-Id` 或 SSE `user_id` |
| A 使用 B 的积分 | 钱包余额、流水、`wallet_meta` 均按 `user_id`；结算以 Session 所有者为准 |
| 装扮/成就串档 | `inventories`、`achievements`、`user_settings` 均带 `user_id` |
| 切换用户污染进行中的局 | `bf-live-session` 阻止切换；后端 Session 创建时已固定归属，前端切换不改变归属 |
| 仅靠前端隐藏 | API 返回 403，不依赖页面隐藏；测试覆盖跨用户 finish/report |

## 6. 旧数据迁移

### 6.1 服务端旧 JSON

启动时扫描 `outputs/sessions/*.json`，只把以下旧报告导入：

- `source.name` 为 `hardware` 或 `heart`；
- `demo` 不为真；
- `played_sec > 0`。

回放、演示、0 秒测试报告直接跳过，避免把测试/模拟记录混入档案。导入目标固定为系统历史档案“历史记录（未归属）”，`is_system=1`、状态 `archived`；不自动分配给真实儿童。`legacy_imports.import_key = report:<文件名>` 保证重复启动不重复导入。测试期间可用 `FOCUS_FROG_IMPORT_LEGACY=0` 关闭扫描。

### 6.2 浏览器 LocalStorage

`web/assets/profile-bridge.js` 的 `legacySnapshot()` 读取旧钱包、成就、已购、当前装备、签到、心率/时长设置与校准。`profiles.html` 在用户选择目标档案并二次确认后调用：

```text
POST /api/profiles/{user_id}/import-legacy
```

服务端先创建备份，再写入目标档案；导入键包含目标用户和 payload 哈希，重复导入同一份数据返回 `already_imported=true`。不会复制给其他档案，不会把测试报告导入真实儿童档案。

### 6.3 旧报告读取

- 新报告写入 SQLite `sessions.report_json`，同时写数据目录 `reports/<sid>.json` 供人工查看。
- 报告接口优先读 SQLite；Session 被回收后仍可读。
- 旧 `outputs/sessions` 仅作为兼容回退，不再作为新报告主存储；新报告不再写入源码工作区。

## 7. 备份与恢复

- 备份：`sqlite3.Connection.backup()` 生成一致性快照，随后执行 `PRAGMA integrity_check`。
- 文件名：`profiles-YYYYmmdd-HHMMSS-<label>-<random>.db`，只允许 `backups/` 下的 `.db` 文件恢复。
- 恢复：先验证备份完整性与 `users` 表存在；自动创建 `before-restore` 备份；临时副本再次校验；清理 `-wal/-shm` 后原子替换。
- 目录迁移：先备份，复制到目标空目录，校验后写指针；旧目录保留；失败不删除旧目录。
- “打开数据文件夹”：macOS `open`、Windows `explorer`、Linux `xdg-open`；失败返回 501，不伪造成功。
- 删除档案：数据库级联删除、报告文件、已登记录制文件；**已有备份不自动删除**，界面明确提示备份可能残留。

## 8. 隐私与安全

- 默认仅监听 `127.0.0.1`；无 CORS 中间件，不开放跨源。
- 不新增外部分析/上传服务；背景音乐仍是唯一可选外部请求，不发送档案数据。
- 原始高频 EEG 默认不落盘；`recordings` 表与目录已预留，但没有默认录制流程。
- 日志不输出昵称、校准值、脑电数组；API 错误只返回路径/权限等必要信息。
- 数据目录迁移/删除接口不接受相对路径、根目录、系统目录或当前目录内部路径；删除需 `confirm=true`。
- `settings.json` 不含个人资料；`.gitignore` 新增 `*.db`、`*.sqlite`、`*.db-*` 等，且数据目录默认在仓库外。
- **SQLite 未做静态加密**：文件权限、操作系统账户和磁盘加密是当前边界；报告和设置页均明确说明。不能把“本地 SQLite”等同于“数据库已加密”。

## 9. Session 生命周期

- `SESSION_RETENTION_SEC` 默认 900 秒，集中配置在 `app/server.py`。
- Session 结束先写入报告快照/逐轮/钱包流水，再允许回收。
- 后台每 60 秒调用 `_reap_sessions()`；只回收 `finished=True`、没有监测订阅者、超过 TTL 的会话。
- 活跃 Session 不清理；监测 SSE 断开后 `monitor_clients` 归零。
- 回收调用 `release()`：取消后台任务、停止源、清空 history/监测批次/最新帧；EDF 原始数组置空。
- 报告读取顺序：SQLite → 内存结束态 → 旧 JSON，因此回收不丢历史报告。

## 10. API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/storage/status` | 数据目录、Schema、磁盘、计数、云同步提示、加密状态 |
| POST | `/api/storage/backup` | 创建一致性备份 |
| GET | `/api/storage/backups` | 备份列表 |
| POST | `/api/storage/restore` | 恢复，需要 `confirm=true` |
| POST | `/api/storage/open` | 打开系统文件夹；失败 501 |
| POST | `/api/storage/location` | 迁移/切换数据目录，需确认 |
| GET/POST | `/api/profiles` | 档案列表/新建 |
| PATCH/DELETE | `/api/profiles/{id}` | 编辑/删除（删除需确认） |
| POST | `/api/profiles/{id}/select` | 更新最近使用时间 |
| GET | `/api/profiles/{id}/bootstrap` | 用户、钱包、设置、资产、成就、最新校准、最近局 |
| POST | `/api/profiles/{id}/sync` | 同步浏览器缓存（钱包/资产/成就/设置） |
| POST | `/api/profiles/{id}/import-legacy` | 导入操作者确认的旧 LocalStorage |
| GET | `/api/profiles/{id}/reports` | 该档案历史报告索引 |

会话/报告接口新增 `X-User-Id` 校验；SSE 使用 `?user_id=`，因为浏览器 `EventSource` 不能自定义请求头。

## 11. 测试与验收

新增 `tests/selfcheck_v181.py`：**33 项通过**。

覆盖：

1. 首次创建中文数据目录、SQLite、settings 和三个子目录。
2. 重复启动不覆盖已有数据库。
3. 中文、空格路径。
4. 新建/修改/最近使用档案。
5. 历史校准追加不覆盖；两用户钱包、报告隔离。
6. 重启后数据仍在。
7. 游戏结束写入逐轮 `rounds`。
8. 重复 `finish` 不重复加积分。
9. Session 归属校验；报告 API 跨用户 403。
10. 旧报告迁移幂等。
11. 备份创建与恢复。
12. 不可写目录明确报错。
13. 完成 Session 内存回收；活跃保护由 `finished`/TTL 条件保证。
14. 回收后报告仍可读。
15. 数据目录迁移与旧目录保留。
16. 资产同步与隔离读取。
17. 儿童/开发者页面保持原有隔离。
18. `.gitignore` 防止 SQLite/报告进入 Git。

其他回归：

```text
node tests/selfcheck_round_logic.js       36/36
node tests/selfcheck_ui_static.js         13/13（新增档案/存储/TTL 检查）
python tests/selfcheck_monitor.py          9/9
python tests/selfcheck_score_mapping.py    通过
python tests/selfcheck_denoise.py          14/14
python -m py_compile app/*.py              通过
node --check web/assets/*.js               通过
```

浏览器验证：

- `profiles.html`：两张虚构档案、新建/编辑/删除二次确认、当前档案标记、旧数据提示。
- `settings.html`：数据路径、Schema v1、磁盘、档案/局数/校准计数、备份列表、隐私边界。
- API：`manual` 会话带 `user_id` 结束；跨用户 finish/report 返回 403。

截图：

- `outputs/v1.8.1/profiles.png`
- `outputs/v1.8.1/settings.png`

> 截图使用临时目录与“小宇/小安”虚构档案，不代表真实用户。

## 12. 未完成事项

1. 未做 Windows 实机验收；仅完成代码层路径/Shell API 兼容设计。macOS 实机通过。
2. 未做桌面封装、安装程序、原生文件选择器；“打开文件夹”在 Web 模式依赖本机后端。
3. 未实现 SQLite 静态加密；文件权限/OS 账户/磁盘加密是当前边界。
4. 未实现云同步/云端账号；文档目录可能被 OneDrive/iCloud 同步，只做提示，不上传。
5. 未实现新的游戏化校准、每日双基线计算、自动难度、成长评价算法；仅预留表和快照字段。
6. 未实现真正的原始 EEG 录制流程；`recordings` 表/目录为预留，默认不写。
7. 本地档案隔离不是联网认证；同一 OS 账户仍可读取数据库。
8. 浏览器 LocalStorage 仍作为当前档案的缓存/兼容层；服务端 SQLite 是主存储，但离页同步失败时下一次进入可能丢失最后一次未同步的缓存变化。
9. 旧 JSON 只迁移 `hardware/heart` 且非 demo/非 0 秒报告；回放/测试记录刻意跳过。
10. 未完成多设备/多进程并发压力测试；当前 SQLite WAL + busy_timeout 面向单机本地使用。

## 13. 自主技术决策

| 决策 | 理由 | 代价 |
|---|---|---|
| 标准库 `sqlite3` | 无新增依赖，符合桌面封装方向 | 需要自己维护迁移/事务 |
| 数据根在系统文档目录，指针在平台配置目录 | 支持改目录，同时避免把个人资料写进源码 | 多一个 `location.json` 指针文件 |
| `FOCUS_FROG_DATA_DIR` 优先于指针 | 自动化测试绝不碰真实档案 | 便携启动需显式设置 |
| SQLite 为权威、LocalStorage 为缓存 | 复用现有钱包/成就模块，减少前端大改 | 离页同步失败时有最后一次缓存风险 |
| 服务端按 `session_id` 结算 | 防止重复 finish 加积分 | 游戏结束后需要等待保存响应再显示最终钱包 |
| Session TTL 900 秒 | 兼顾报告读取与内存回收 | 完成 15 分钟内仍驻留内存 |
| 旧 JSON 先进入系统历史档案 | 不猜测归属，不污染真实儿童 | 旧数据需要操作者后续确认归属 |
| 云同步只提示不禁止 | 尊重用户选择 | 用户仍可能把数据放在同步盘 |

## 14. 下一阶段可复用接口

- `storage.add_calibration()`：追加每日校准；`kind` 可扩展为 `daily/reference`。
- `reference_baselines`：长期参考基线；下一步只需增加计算与读取函数。
- `sessions.difficulty_snapshot_json` / `difficulty_history`：自动难度配置快照。
- `storage.bootstrap()` / `sync_state()`：档案加载与资产同步。
- `storage.backup()` / `restore()`：桌面端“导出/恢复”入口。
- `Session.user_id` 与 `_session_for()`：多档案游戏/监测/报告鉴权。
- `reports/<sid>.json` + `sessions.report_json`：成长报告、家长汇总、导出。

---

*本报告只记录实际完成与验证的内容；未运行的平台和未实现的能力均已明确标注。*
