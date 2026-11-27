#!/usr/bin/env python3
"""v1.8.1 本地存储、档案隔离、迁移、备份与 Session 回收验收。

只使用临时目录和虚构昵称，不触碰 Documents 下的真实档案。
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="专注小蛙 档案测试 "))
DATA = TMP / "专注 小蛙"
# 隔离平台配置目录中的 location.json；测试迁移目录时绝不能改写真实用户指针
os.environ["HOME"] = str(TMP / "home")
(TMP / "home").mkdir()
os.environ["FOCUS_FROG_DATA_DIR"] = str(DATA)
os.environ["FOCUS_FROG_IMPORT_LEGACY"] = "0"
os.environ["FOCUS_FROG_SESSION_TTL_SEC"] = "0"
sys.path.insert(0, str(ROOT))

from app import server as srv  # noqa: E402
from app.sources import ManualSource  # noqa: E402
from app.storage import StorageError, StorageManager  # noqa: E402

PORT = 8094
BASE = f"http://127.0.0.1:{PORT}"
passed = []


def check(name, condition, detail=""):
    if not condition:
        raise AssertionError(f"{name} 失败 {detail}")
    passed.append(name)
    print(f"PASS {name}")


def http(path, method="GET", body=None, uid=None, expect_error=False):
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if uid:
        headers["X-User-Id"] = uid
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode() or "{}")
            return resp.status, payload
    except urllib.error.HTTPError as exc:
        payload = json.loads(exc.read().decode() or "{}")
        if not expect_error:
            raise
        return exc.code, payload


def wait_server():
    for _ in range(80):
        try:
            with urllib.request.urlopen(BASE + "/api/health", timeout=1) as r:
                if r.status == 200:
                    return
        except Exception:
            time.sleep(0.15)
    raise RuntimeError("测试服务没有启动")


def start_server():
    env = os.environ.copy()
    env["FOCUS_FROG_DATA_DIR"] = str(DATA)
    env["FOCUS_FROG_IMPORT_LEGACY"] = "0"
    env["FOCUS_FROG_SESSION_TTL_SEC"] = "0"
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.server:app", "--host", "127.0.0.1",
         "--port", str(PORT), "--log-level", "warning"],
        cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def user(uid):
    with sqlite3.connect(DATA / "profiles.db") as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute("SELECT * FROM users WHERE user_id = ?", (uid,)).fetchone()


def main():
    m = StorageManager(DATA)
    check("测试隔离平台配置目录", str(m.pointer_path).startswith(str(TMP)), str(m.pointer_path))
    check("首次启动创建中文数据目录", DATA.is_dir())
    check("首次启动创建 SQLite 与 settings", (DATA / "profiles.db").is_file() and (DATA / "settings.json").is_file())
    check("目录结构包含 reports/recordings/backups",
          all((DATA / n).is_dir() for n in ("reports", "recordings", "backups")))
    check("Schema 版本记录", m.status()["schema_version"] == 1)

    u1 = m.create_user("小宇", "frog")
    u2 = m.create_user("小安", "fish")
    m.touch_user(u1["user_id"])
    check("创建并记住最近档案", m.list_users()[0]["user_id"] == u1["user_id"])
    m2 = StorageManager(DATA)
    check("重复启动不覆盖数据库", m2.get_user(u1["user_id"])["nickname"] == "小宇")

    m.update_user(u1["user_id"], nickname="小宇改", avatar="lotus")
    check("修改昵称与头像", m.get_user(u1["user_id"])["avatar"] == "lotus")
    check("含中文和空格路径", " " in str(DATA) and "专注" in str(DATA))

    c1 = m.add_calibration(u1["user_id"], {
        "baseline": .55, "range": {"low": .35, "high": .75},
        "quantiles": {"q10": .35, "q50": .55, "q90": .75}, "n_frames": 20,
    }, source={"name": "hardware"})
    c2 = m.add_calibration(u1["user_id"], {
        "baseline": .62, "range": {"low": .4, "high": .8},
        "quantiles": {"q10": .4, "q50": .62, "q90": .8}, "n_frames": 25,
    }, source={"name": "hardware"})
    check("历史校准不覆盖", c1["id"] != c2["id"] and m.latest_calibration(u1["user_id"])["baseline"] == .62)

    report = {
        "session_id": "sess_v181_a", "created_at": "2026-11-27T10:00:00+08:00",
        "played_sec": 60, "duration_sec": 60, "score": 90, "demo": False,
        "source": {"name": "hardware"}, "n_frames": 10, "n_valid_frames": 9,
        "actions": {"timed_jumps": 1, "successful_jumps": 1, "missed_jumps": 0,
                    "rounds": [{"round": 1, "success": True, "awarded": 90, "charge_sec": 5.0}]},
    }
    first = m.persist_session(report, u1["user_id"], c2["id"])
    second = m.persist_session(report, u1["user_id"], c2["id"])
    check("游戏结束保存逐轮数据",
          sqlite3.connect(DATA / "profiles.db").execute("SELECT COUNT(*) FROM rounds WHERE session_id='sess_v181_a'").fetchone()[0] == 1)
    check("重复结算不重复加积分",
          first["wallet"]["points"] == second["wallet"]["points"] == 3,
          f"{first} {second}")

    try:
        m.load_report("sess_v181_a", u2["user_id"])
        check("报告跨用户隔离", False)
    except StorageError:
        check("报告跨用户隔离", True)
    check("不同用户钱包独立", m.wallet(u1["user_id"])["points"] == 3 and m.wallet(u2["user_id"])["points"] == 0)

    sync = m.sync_state(u1["user_id"], {
        "settings": {"bf-checkin": {"lastDate": "2026-11-27"}},
        "wallet": {"points": 10, "rounds": 2, "jumps": 10, "spent": 0},
        "owned": ["hat-grad"], "achievements": {"unlocked": {"first": 1700000000000}},
    })
    check("商城/装扮/成就绑定档案",
          sync["wallet"]["points"] == 10 and "hat-grad" in sync["owned"] and "first" in sync["achievements"])

    backup = m.backup("acceptance")
    check("数据库一致性备份", (DATA / "backups" / backup["filename"]).is_file())
    m.create_user("临时删除对象", "snail")
    m.restore(backup["filename"], confirm=True)
    check("备份恢复后回到快照", not any(u["nickname"] == "临时删除对象" for u in m.list_users()))

    old_dir = TMP / "旧报告"
    old_dir.mkdir()
    (old_dir / "old.json").write_text(json.dumps({
        "session_id": "old_v181", "score": 30, "played_sec": 60,
        "source": {"name": "hardware"}, "actions": {"rounds": []},
    }), encoding="utf-8")
    n1 = m.import_legacy_reports(old_dir)
    n2 = m.import_legacy_reports(old_dir)
    check("旧报告迁移幂等", n1 == 1 and n2 == 0, f"{n1}/{n2}")

    block = TMP / "blocked"
    block.mkdir()
    os.chmod(block, 0)
    try:
        bad = StorageManager(block / "data")
        check("不可写目录明确报错", bool(bad.error), bad.error)
    finally:
        os.chmod(block, 0o700)

    # Session TTL：活跃不清理；完成后释放内存，报告仍可从 SQLite 读取。
    async def session_ttl():
        source = ManualSource()
        s = srv.Session(source, {"user_id": u1["user_id"], "calibration_id": c2["id"]})
        await s.start()
        await asyncio.sleep(1.2)
        await s.finish(score=60, played_sec=1, actions={"rounds": []}, demo=False)
        m.persist_session(s.stats, u1["user_id"], c2["id"])
        srv._sessions[s.id] = s
        srv.SESSION_RETENTION_SEC = 0
        s.finished_at = time.time() - 100
        removed = srv._reap_sessions()
        return s.id, removed

    sid, removed = asyncio.run(session_ttl())
    check("完成 Session 回收内存", sid not in srv._sessions and removed >= 1)
    check("回收后报告仍可读取", bool(m.load_report(sid, u1["user_id"])))

    # 数据目录迁移到中文空格目录，旧目录保留。
    moved = TMP / "迁 移目录"
    result = m.set_data_dir(str(moved), confirm=True, migrate=True)
    check("修改数据目录并保留旧目录",
          result["migrated"] and (moved / "profiles.db").is_file() and (DATA / "profiles.db").is_file())
    check("迁移后档案仍在", StorageManager(moved).get_user(u1["user_id"]) is not None)

    # API：必须真正验证 user_id 与 Session 的归属，而不只靠前端隐藏。
    proc = start_server()
    try:
        wait_server()
        status, payload = http("/api/profiles")
        check("档案 API 列表", status == 200 and len(payload["profiles"]) >= 2)
        status, payload = http(f"/api/profiles/{u1['user_id']}/bootstrap")
        check("档案 bootstrap", status == 200 and payload["wallet"]["points"] >= 10)

        status, payload = http("/api/session", "POST", {
            "mode": "manual", "user_id": u1["user_id"], "baseline": .62,
            "calibration_id": c2["id"],
        })
        session_id = payload["session_id"]
        time.sleep(1.1)
        status, payload = http(f"/api/session/{session_id}/finish", "POST",
                               {"score": 90, "played_sec": 2}, uid=u1["user_id"])
        check("API 保存本局并返回钱包", status == 200 and payload["wallet"] is not None)
        status, _ = http(f"/api/session/{session_id}/finish", "POST",
                         {"score": 90, "played_sec": 2}, uid="u_other", expect_error=True)
        check("Session 归属校验", status == 403)
        status, _ = http(f"/api/session/{session_id}/finish", "POST",
                         {"score": 90, "played_sec": 2}, uid=u1["user_id"])
        check("API 重复结算不重复", status == 200)
        status, _ = http(f"/api/report/{session_id}", uid="u_other", expect_error=True)
        check("报告 API 归属校验", status == 403)
        status, _ = http(f"/api/report/{session_id}", uid=u1["user_id"])
        check("报告 API 本人可读", status == 200)

        status, _ = http(f"/api/profiles/{u1['user_id']}/sync", "POST",
                         {"owned": ["hat-grad", "cape-red"], "settings": {"bf-checkin": {"x": 1}}},
                         uid=u1["user_id"])
        check("资产 API 写入", status == 200)
        status, payload = http(f"/api/profiles/{u1['user_id']}/bootstrap")
        check("资产 API 隔离读取", "cape-red" in payload["owned"])
    finally:
        proc.terminate()
        proc.wait(timeout=10)

    # 真实数据不进入 Git 的检查在测试后由 shell 再执行，此处只校验目录规则。
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    check("Git 忽略本地数据/报告", "outputs/sessions" in gitignore or "*.db" in gitignore)
    print(f"\n{len(passed)} 项 v1.8.1 验收通过")


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
