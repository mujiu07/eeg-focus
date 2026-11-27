# v1.9.1 档案加载失败修复报告

日期：2026-11-28
基准版本：v1.9.0
修复版本：v1.9.1
范围：个人档案及直接关联的恢复/迁移路径；不新增功能，不改变游戏、算法、校准或计分。

## 1. 现象与复现

实际页面显示：

- “加载档案失败：Internal Server Error”
- “个人档案——读取档案失败：Internal Server Error”

浏览器实际请求：

```text
GET /api/profiles  ->  500 Internal Server Error
GET /api/profiles/{id}/bootstrap  ->  500 Internal Server Error
```

不是前端提示问题。修复前真实服务日志包含：

```text
File "app/accounts.py", line 125, in profiles
    p["difficulty"] = storage.difficulty_profile(p["user_id"], history_limit=0)
File "app/storage.py", line 1263, in difficulty_profile
    self._ensure_difficulty_profile(conn, str(user_id))
File "app/storage.py", line 1250, in _ensure_difficulty_profile
    conn.execute(
sqlite3.OperationalError: no such table: difficulty_profiles
```

同一时期，实际数据库的健康查询显示：

- 数据目录：`/Users/fan/Documents/专注小蛙/`
- 服务实际数据库：`/Users/fan/Documents/专注小蛙/profiles.db`
- Schema 版本：`4`
- 实际表：缺少 `difficulty_profiles`、`assessments`；旧 `sessions` 也缺少 `purpose/assessment_id`
- 恢复前备份：`profiles-20261128-004608-before-restore-ddca6.db`，Schema 记录为 `[1, 2]`

## 2. 根本原因

根因在 `StorageManager.restore()`，不是档案 JSON 或前端：

1. 用户在应用内恢复了 v1.8.1 时期的 Schema 2 备份。
2. 旧实现只把备份复制/替换为当前 `profiles.db`，然后直接返回成功。
3. 运行中的服务没有在替换后执行 `_migrate()`，也没有校验新库是否具备当前代码要求的表/列。
4. `/api/profiles` 先读取用户列表，再为每个用户调用 `difficulty_profile()`；后者查询 `difficulty_profiles`，旧 Schema 没有该表，于是抛出 `sqlite3.OperationalError`。
5. FastAPI 将未捕获异常返回为 HTTP 500。

这解释了为什么重新启动服务后错误曾短暂消失：服务启动时 `_migrate()` 执行了补表/补列；但“恢复旧备份”这条路径本身仍然是不安全的。

## 3. 修复方案

`app/storage.py` 的 `StorageManager.restore()` 改为：

1. 对来源备份做首次完整性检查，确认是有效数据库。
2. 创建恢复前一致性备份（`before-restore`）。
3. 把来源备份复制到临时文件，绝不先覆盖正式库。
4. 在临时副本上运行 `_migrate()`，补齐旧 Schema 的表、列与索引。
5. 在临时副本上再次执行 `PRAGMA integrity_check`。
6. 校验 `users/sessions/difficulty_profiles/assessments` 四张必要表存在。
7. 执行 WAL checkpoint 并清理临时 sidecar 文件。
8. 校验通过后才原子替换正式 `profiles.db`。
9. 任何迁移/校验失败都删除临时文件，正式库保持不变。

修复没有：

- 删除真实数据库；
- 清空档案或历史；
- 重建用户数据；
- 改数据目录；
- 吞异常或返回空列表假装成功。

## 4. 真实数据保护

修复前已对真实库执行 SQLite 一致性备份：

```text
/Users/fan/Documents/专注小蛙/backups/profiles-20261128-005348-before-v1.9.1-d4ec6d.db
PRAGMA integrity_check = ok
```

备份内记录：3 个档案、6 个 Session、0 个校准、0 个标准评估。未发现 A–E 临时 fixture 档案混入真实库。真实库仍使用原数据目录。

后续所有写入验证都使用真实库副本：

```text
.deepworks/tmp/v191-real-copy/profiles.db
```

没有在真实档案里创建测试昵称、Session、校准、积分或评估。

## 5. 测试与证据

新增 `tests/selfcheck_v191.py`，12 项：

1. 缺少 `difficulty_profiles/assessments` 的旧 Schema 恢复成功。
2. 恢复后 `status()` 可读且 Schema 为 4。
3. 恢复后自动重建必要表。
4. 恢复后补齐 `sessions.purpose/assessment_id`。
5. 旧用户保留且状态正确。
6. 恢复后 `difficulty_profile()` 可读。
7. 与 `/api/profiles` 相同的 handler 不再抛 500。
8. `GET /api/profiles` 返回 200。
9. 本机真实 v1.8.1 Schema 2 备份复制后恢复成功。
10. 真实旧备份恢复后档案可读。
11. 真实库副本可创建/修改/选择/同步档案。
12. 真实库副本成长接口可读。

回归：

- v1.9.0 成长中心：29/29
- v1.8.4：52 Python + 14 单轮 + 17 UI
- v1.8.3：52 Python + 8 单轮
- v1.8.2：35；v1.8.1：33
- 静态 UI、既有单轮、监测、去噪、计分映射全部通过

浏览器实测：

```text
profiles.html title: 选择档案 - 专注小蛙
.profile-card count: 3
body contains 读取档案失败: false
fetch('/api/profiles'): 200
console errors: []
```

修复后截图：`outputs/v1.9.1/profiles-fixed.png`。

## 6. 为什么此前自动化测试没有发现

- v1.8.1 的恢复测试只恢复 **同版本 Schema** 的备份，不会触发缺表。
- v1.9.0 的 A–E fixture 从全新 Schema 4 创建，覆盖业务数据但未覆盖“恢复旧 Schema 后立即读取档案”。
- 此前没有一条测试把“真实历史备份/Schema 2 + restore + /api/profiles”串起来。
- 真实库迁移与 API 服务运行在不同进程中，重启会让 `_migrate()` 掩盖恢复路径的问题。

v1.9.1 将这些路径固定为自动化回归，不再依赖重启后偶然恢复。

## 7. 当前边界

- 该修复只保证应用内恢复备份时先迁移；如果从应用外手动替换 `profiles.db`，仍应重启服务或使用应用内恢复入口。
- SQLite 与报告文件仍未静态加密。
- 前端隐藏/家长确认层不是身份认证。
- 本次未进行真实硬件、真机 Xmuse、儿童可用性或 Windows 验证。
- 恢复会用备份替换当前库；恢复前备份会保留，但不会自动合并两份数据。
