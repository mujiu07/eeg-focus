#!/usr/bin/env python3
"""v1.9.1 回归：旧 Schema 备份恢复后档案接口不得 500。

覆盖：
- 恢复缺少 difficulty_profiles / assessments 的旧库后自动迁移；
- 恢复后直接调用与 `/api/profiles` 相同的后端路径；
- 可选：用真实库副本做写入测试（只复制，不碰真实文件）。
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = Path(tempfile.mkdtemp(prefix="专注小蛙-v191-"))
os.environ["FOCUS_FROG_DATA_DIR"] = str(TMP / "global-test")
os.environ["FOCUS_FROG_IMPORT_LEGACY"] = "0"
os.environ["FOCUS_FROG_SESSION_TTL_SEC"] = "0"
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app import accounts  # noqa: E402
from app import growth  # noqa: E402
from app.server import app  # noqa: E402
from app.storage import StorageManager  # noqa: E402

checks = []
REAL_BACKUP = Path("/Users/fan/Documents/专注小蛙/backups/profiles-before-v1.8.3-20261127-210046.db")
REAL_COPY = Path("/Users/fan/Documents/专注小蛙/backups/profiles-20261128-005348-before-v1.9.1-d4ec6d.db")


def check(name, cond, detail=""):
    checks.append((name, bool(cond), detail))
    print(("[OK] " if cond else "[FAIL] ") + name + ((" " + str(detail)) if not cond else ""))
    if not cond:
        raise AssertionError(name)


def _copy_as_restore_source(store: StorageManager, source: Path) -> str:
    name = "legacy-" + source.name
    shutil.copy2(source, store.backups_dir / name)
    return name


def _make_old_schema(root: Path) -> tuple[StorageManager, Path]:
    """Create a v1.8.1-shaped copy by removing v1.8.2+ tables."""
    base = StorageManager(root)
    child = base.create_user("旧库孩子", "frog")
    with sqlite3.connect(str(base.db_path)) as conn:
        conn.execute("DROP TABLE IF EXISTS difficulty_profiles")
        conn.execute("DROP TABLE IF EXISTS assessments")
        conn.execute("DELETE FROM schema_version WHERE version >= 3")
    legacy = root / "legacy.db"
    with sqlite3.connect(str(base.db_path)) as src, sqlite3.connect(str(legacy)) as dst:
        src.backup(dst)
    return base, legacy


def main():
    # 1) 模拟旧 Schema 恢复：恢复前没有 difficulty_profiles / assessments。
    old_root = TMP / "old-schema"
    _base, legacy = _make_old_schema(old_root)
    restore_root = TMP / "restore-target"
    store = StorageManager(restore_root)
    source_name = _copy_as_restore_source(store, legacy)
    result = store.restore(source_name, confirm=True)
    check("旧 Schema 恢复返回成功", result.get("ok") and result.get("schema_version") == 4, result)
    status = store.status()
    check("恢复后状态可读", status.get("ok") and status.get("schema_version") >= 4, status)
    with sqlite3.connect(str(store.db_path)) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        cols = {r[1] for r in conn.execute("PRAGMA table_info(sessions)")}
    check("恢复后重建必要表", {"difficulty_profiles", "assessments"} <= tables, tables)
    check("恢复后补齐会话列", {"purpose", "assessment_id"} <= cols, cols)
    child = next(u for u in store.list_users() if u["nickname"] == "旧库孩子")
    check("恢复后保留旧用户", child["status"] == "active", child)
    check("恢复后难度档案可读", store.difficulty_profile(child["user_id"])["factor"] == 1.0)

    # 2) 走与 /api/profiles 相同的函数路径，并实际请求 API。
    old_storage = accounts.storage
    accounts.storage = store
    try:
        payload = accounts.profiles()
        check("profile handler 不再抛 500", any(p["user_id"] == child["user_id"] for p in payload["profiles"]))
        client = TestClient(app)
        response = client.get("/api/profiles")
        check("GET /api/profiles 返回 200", response.status_code == 200, response.text[:300])
    finally:
        accounts.storage = old_storage

    # 3) 真实历史备份（只读复制）恢复；不存在则明确跳过而不伪装通过。
    if REAL_BACKUP.is_file():
        real_store = StorageManager(TMP / "real-old-restore")
        name = _copy_as_restore_source(real_store, REAL_BACKUP)
        result = real_store.restore(name, confirm=True)
        check("真实 v1.8.1 备份恢复后 Schema 4", result.get("ok") and real_store.status().get("schema_version") == 4, result)
        check("真实旧备份恢复后档案可读", isinstance(real_store.list_users(), list))
    else:
        print("[SKIP] 未找到本机真实 v1.8.1 备份；旧 Schema 合成用例已通过")

    # 4) 用真实数据库副本做写入测试；绝不写真实路径。
    if REAL_COPY.is_file():
        copy_store = StorageManager(TMP / "real-write-copy")
        # 把真实副本放入临时 store 的正常位置，模拟真实运行库。
        shutil.copy2(REAL_COPY, copy_store.db_path)
        copy_store = StorageManager(TMP / "real-write-copy")
        u = copy_store.create_user("副本测试", "frog")
        copy_store.update_user(u["user_id"], nickname="副本昵称", avatar="fish")
        copy_store.touch_user(u["user_id"])
        copy_store.sync_state(u["user_id"], {
            "settings": {"theme": "pond"},
            "wallet": {"points": 7, "rounds": 1, "jumps": 3, "spent": 0},
            "owned": ["hat-leaf"],
            "achievements": {"unlocked": {"focus-1": 1}},
        })
        boot = copy_store.bootstrap(u["user_id"])
        check("真实库副本写入/读取", boot["user"]["nickname"] == "副本昵称"
              and boot["wallet"]["points"] == 7 and "hat-leaf" in boot["owned"])
        old_growth_storage = growth.storage
        growth.storage = copy_store
        try:
            diary = growth.build_diary(u["user_id"])
        finally:
            growth.storage = old_growth_storage
        check("真实库副本成长接口可读", diary["summary"]["play_seconds"] is None)
    else:
        print("[SKIP] 未找到本机真实库一致性副本；合成旧库已覆盖恢复回归")

    print(f"\n{len(checks)} 项 v1.9.1 档案恢复验收通过")
    if len(checks) < 8:
        raise AssertionError("验收项过少")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
