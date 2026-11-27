#!/usr/bin/env python3
"""v1.8.2 每日游戏化校准、双基线、Session 锁定与迁移验收。

所有数据都在临时目录；不触碰 Documents 下的真实档案。
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="专注小蛙 v182 "))
DATA = TMP / "专注 小蛙"
os.environ["HOME"] = str(TMP / "home")
(TMP / "home").mkdir()
os.environ["FOCUS_FROG_DATA_DIR"] = str(DATA)
os.environ["FOCUS_FROG_IMPORT_LEGACY"] = "0"
os.environ["FOCUS_FROG_SESSION_TTL_SEC"] = "0"
sys.path.insert(0, str(ROOT))

from app import server as srv  # noqa: E402
from app import calibration as ce  # noqa: E402
from app.sources import ManualSource  # noqa: E402
from app.storage import StorageManager  # noqa: E402

passed = []


def check(name, condition, detail=""):
    if not condition:
        raise AssertionError(f"{name} 失败 {detail}")
    passed.append(name)
    print(f"PASS {name}")


def frame(t, x):
    return {"t": t, "raw": x, "focus": x, "focus_fused": x, "valid": True}


def natural_frames(n=120, start=0.0):
    return [frame(start + i * .25, .28 + .12 * (i % 20) / 19.0) for i in range(n)]


def tutorial_frames(start=30.0, n=120):
    return [frame(start + i * .25, .34 + .16 * (i % 20) / 19.0) for i in range(n)]


class FakeHardware:
    name = "hardware"

    def describe(self):
        return {"name": "hardware", "osc_ports": "7000,8000", "osc_fs": 256}

    def artifact_summary(self):
        return {"usable_ratio": .94, "blink_frame_ratio": .03, "level": "good"}

    def stop(self):
        pass


def main():
    m = StorageManager(DATA)
    check("Schema v2+", m.status()["schema_version"] >= 2, str(m.status()))
    check("配置集中且默认 30/30/P15/P85",
          ce.CONFIG["natural_sec"] == 30 and ce.CONFIG["tutorial_sec"] == 30
          and ce.CONFIG["p_low"] == .15 and ce.CONFIG["p_high"] == .85)

    # 统计：两阶段等权，不把教学阶段强行定义为高分。
    computed = ce.compute_daily_range(natural_frames(), tutorial_frames())
    check("两阶段生成 L/H", computed["range"]["low"] < computed["range"]["high"], computed["range"])
    check("阶段统计与有效时长独立",
          computed["stages"]["natural"]["n"] == 120
          and computed["stages"]["tutorial"]["n"] == 120
          and computed["effective_sec"] >= 55)
    check("阶段反差只记录不强制",
          computed["stage_contrast_label"] in ("tutorial_higher", "natural_higher", "flat"))

    flat = [frame(i * .25, .5) for i in range(120)]
    narrow = ce.compute_daily_range(flat, flat)
    check("极小跨度过窄被标记且保留最小跨度",
          narrow["range_quality"] == "stretched"
          and narrow["range"]["high"] - narrow["range"]["low"] >= ce.CONFIG["min_span"] - 1e-6)

    try:
        ce.compute_daily_range(natural_frames(10), tutorial_frames(n=10))
        check("样本不足拒绝生成", False)
    except ce.CalibrationDataError:
        check("样本不足拒绝生成", True)

    # 日期/TTL/设备状态。
    at = 1_800_000_000_000
    today = ce.local_date(at, -480)
    daily = [{"id": "c1", "is_valid": True, "kind": "daily", "source_name": "hardware",
              "protocol_version": "daily_v2",
              "device_key": "hardware|7000,8000|256|", "calibration_date": today,
              "at": at, "range": {"low": .3, "high": .7}}]
    st = ce.daily_status(daily, now_ms=at + 1000, mode="hardware",
                         device="hardware|7000,8000|256|", tz_offset_min=-480)
    check("当天同设备校准可复用", st["valid"] and st["calibration"]["id"] == "c1", st)
    st2 = ce.daily_status(daily, now_ms=at + 1000, mode="hardware",
                          device="hardware|7001,8001|256|", tz_offset_min=-480)
    check("设备变化需要重校", not st2["valid"] and st2["reason"] == "device_changed", st2)
    st3 = ce.daily_status(daily, now_ms=at + ce.CONFIG["daily_ttl_sec"] * 1000 + 1,
                          mode="hardware", device="hardware|7000,8000|256|", tz_offset_min=-480)
    check("超时需要重校", not st3["valid"] and st3["reason"] == "expired", st3)
    legacy = [{"id": "old", "is_valid": True, "kind": "daily", "source_name": "hardware",
               "at": at, "range": {"low": .3, "high": .7}}]
    check("v1.8.1 旧校准不被当作今日校准",
          not ce.daily_status(legacy, now_ms=at + 1000, mode="hardware",
                              device="hardware|7000,8000|256|", tz_offset_min=-480)["valid"])

    u1 = m.create_user("小宇", "frog")
    u2 = m.create_user("小安", "fish")
    c1 = m.add_calibration(u1["user_id"], {
        "baseline": .5, "range": {"low": .3, "high": .7},
        "quantiles": {"q15": .3, "q50": .5, "q85": .7}, "n_frames": 240,
        "protocol_version": "daily_v2", "mapping_version": "map_v2",
        "status": "ok", "calibration_date": "2026-11-27",
        "timezone_offset_min": -480, "device_key": "hardware|7000,8000|256|",
        "effective_sec": 60, "stages": {"natural": {"n": 120}, "tutorial": {"n": 120}},
    }, source={"name": "hardware", "osc_ports": "7000,8000", "osc_fs": 256})
    check("首次硬件校准建立 v1 长期参考", bool(c1.get("reference_baseline_id")), c1)
    ref1 = m.reference_baseline(u1["user_id"])
    check("长期参考不覆盖且为初始标记", ref1["version"] == "v1" and ref1["is_initial"], ref1)
    c2 = m.add_calibration(u1["user_id"], {
        "baseline": .6, "range": {"low": .4, "high": .8},
        "quantiles": {"q15": .4, "q50": .6, "q85": .8}, "n_frames": 240,
        "protocol_version": "daily_v2", "mapping_version": "map_v2", "status": "ok",
        "calibration_date": "2026-11-27", "timezone_offset_min": -480,
        "device_key": "hardware|7000,8000|256|", "effective_sec": 60,
    }, source={"name": "hardware", "osc_ports": "7000,8000", "osc_fs": 256})
    ref_after_daily = m.reference_baseline(u1["user_id"])
    check("每日校准不覆盖长期参考", ref_after_daily["id"] == ref1["id"] and c2["id"] != c1["id"])
    ref2 = m.add_reference_baseline(u1["user_id"], c2["id"], "第二次参考")
    check("显式建立 v2 并保留 v1", ref2["version"] == "v2"
          and len(m.reference_baselines(u1["user_id"])) == 2, m.reference_baselines(u1["user_id"]))
    check("历史参考仍可追溯", any(x["version"] == "v1" and not x["is_active"]
                                  for x in m.reference_baselines(u1["user_id"])))

    test_cal = m.add_calibration(u1["user_id"], {
        "baseline": .5, "range": {"low": .2, "high": .8},
        "quantiles": {"q15": .2, "q85": .8}, "n_frames": 50,
        "protocol_version": "daily_v2", "status": "ok",
    }, source={"name": "replay"}, kind="test")
    check("回放校准不建立真实参考",
          test_cal.get("reference_baseline_id") is None
          and len(m.reference_baselines(u1["user_id"])) == 2)

    st4 = m.calibration_status(u1["user_id"], mode="hardware",
                               device="hardware|7000,8000|256|", tz_offset_min=-480,
                               now_ms=int(c2["at"]) + 1000)
    check("数据库当天状态可查询", st4["valid"] and st4["calibration"]["id"] == c2["id"], st4)
    st5 = m.calibration_status(u1["user_id"], mode="hardware",
                               device="hardware|9999||", tz_offset_min=-480,
                               now_ms=int(c2["at"]) + 1000)
    check("状态识别设备变化", not st5["valid"] and st5["reason"] == "device_changed", st5)
    check("不同用户校准隔离",
          m.calibration_history(u2["user_id"]) == [] and m.reference_baseline(u2["user_id"]) is None)

    # 正式游戏：无当天硬件校准必须 409；有校准后锁定量程与参考快照。
    async def gate():
        try:
            await srv.create_session(srv.SessionCreate(
                mode="hardware", user_id=u2["user_id"], purpose="game",
                device_key="hardware|7000,8000|256|", timezone_offset_min=-480))
            return None
        except Exception as exc:  # HTTPException
            return getattr(exc, "status_code", None)

    check("无当日校准拒绝正式硬件开局", asyncio.run(gate()) == 409)
    daily2 = m.add_calibration(u2["user_id"], {
        "baseline": .52, "range": {"low": .31, "high": .71},
        "quantiles": {"q15": .31, "q85": .71}, "n_frames": 240,
        "protocol_version": "daily_v2", "status": "ok",
        "calibration_date": ce.local_date(int(time.time() * 1000), -480),
        "timezone_offset_min": -480, "device_key": "hardware|7000,8000|256|",
        "effective_sec": 60,
    }, source={"name": "hardware", "osc_ports": "7000,8000", "osc_fs": 256})
    async def game_flow():
        old_create = srv.sources.create_source
        srv.sources.create_source = lambda cfg: ManualSource()
        try:
            created = await srv.create_session(srv.SessionCreate(
                mode="hardware", user_id=u2["user_id"], purpose="game",
                device_key="hardware|7000,8000|256|", timezone_offset_min=-480,
                calibration_id=daily2["id"], score_low=.1, score_high=.9))
            s = srv._sessions[created["session_id"]]
            check("正式游戏锁定服务端当日量程",
                  s.calibration_id == daily2["id"] and s.score_low == .31 and s.score_high == .71)
            check("正式游戏携带长期参考快照", s.reference_baseline_id is not None)
            s.history = natural_frames()
            await s.finish(score=60, played_sec=10, demo=True)
            m.persist_session(s.stats, user_id=u2["user_id"], calibration_id=s.calibration_id)
            report = m.load_report(s.id, u2["user_id"])
            check("Session 报告保存双映射与快照",
                  report.get("reference_score_mean") is not None
                  and report.get("reference_snapshot", {}).get("id") == s.reference_snapshot["id"])
        finally:
            srv.sources.create_source = old_create

    asyncio.run(game_flow())

    # 新协议校准端点：阶段窗口、质量控制、保存与参考。
    u3 = m.create_user("小禾", "lotus")
    asyncio.set_event_loop(asyncio.new_event_loop())
    s3 = srv.Session(FakeHardware(), {"user_id": u3["user_id"], "purpose": "calibration"})
    s3.created_at = time.time() - 70
    s3.history = natural_frames() + tutorial_frames()
    srv._sessions[s3.id] = s3
    body = srv.CalibrateStart(
        duration=60, protocol="daily_v2", elapsed_sec=60,
        stage_windows={"natural": {"start": 0, "end": 30}, "tutorial": {"start": 30, "end": 60}},
        tutorial_events=[{"t": 32, "charge": 50, "zone_lo": 40, "zone_hi": 60}],
        device_key="hardware|7000,8000|256|", timezone_offset_min=-480,
    )
    out = asyncio.run(srv.calibrate(s3.id, body, x_user_id=u3["user_id"]))
    check("新协议四阶段结果有效",
          out["status"] == "ok" and out["stages"]["natural"]["n"] == 120
          and out["stages"]["tutorial"]["n"] == 120, out)
    check("新协议保存每日校准和初始长期参考",
          bool(out["calibration_id"]) and bool(out["reference_baseline"]["id"]),
          out.get("reference_baseline"))
    check("校准结果含有效时长与阶段统计",
          out["effective_sec"] >= 55 and out["stages"]["natural"]["n"] == 120)
    # 教学点击是前端交互日志，不改变脑电统计；阶段样本仍只来自有效帧。
    check("教学点击不改变脑电参考统计",
          out["stages"]["tutorial"]["n"] == 120 and out["calibration"]["n_frames"] == 240)

    # Session 双映射：同一 x，S_daily 与 S_reference 分别计算，参考不参与 daily。
    asyncio.set_event_loop(asyncio.new_event_loop())
    s4 = srv.Session(FakeHardware(), {"user_id": u3["user_id"]})
    s4.apply_calibration(out["calibration"], out["reference_baseline"])
    x_mid = (s4.score_low + s4.score_high) / 2
    daily_score = s4.score_of(x_mid)
    ref_score = s4.score_reference(x_mid)
    check("日映射与参考映射分离", daily_score == 50.0 and ref_score is not None,
          f"{daily_score}/{ref_score}")
    s4.reference_low, s4.reference_high = .1, .9
    check("参考映射变化不影响日驱动分数", s4.score_of(x_mid) == daily_score)
    srv._sessions[s4.id] = s4
    try:
        asyncio.run(srv.calibrate(s4.id, body, x_user_id=u3["user_id"]))
        locked = False
    except Exception as exc:
        locked = getattr(exc, "status_code", None) == 409
    check("正式游戏期间禁止重新校准", locked)

    # 报告落库列（双快照）。
    with sqlite3.connect(DATA / "profiles.db") as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(sessions)").fetchall()}
    check("Session 双快照列存在",
          {"reference_baseline_id", "calibration_snapshot_json", "reference_snapshot_json"} <= cols)

    # v1.8.1 -> v1.8.2 原地迁移：保留旧用户/钱包，补齐新列，不重建表。
    legacy_dir = TMP / "v181_db"
    legacy_dir.mkdir()
    shutil.copy2(DATA / "profiles.db", legacy_dir / "profiles.db")
    with sqlite3.connect(legacy_dir / "profiles.db") as conn:
        for table, cols in {
            "calibrations": ["calibration_date", "timezone_offset_min", "device_key",
                             "protocol_version", "mapping_version", "stages_json",
                             "effective_sec", "elapsed_sec", "status", "reference_baseline_id"],
            "reference_baselines": ["version", "q15", "q85", "n_frames", "protocol_version",
                                    "mapping_version", "device_key", "stages_json", "is_initial",
                                    "status", "superseded_by"],
            "sessions": ["reference_baseline_id", "calibration_snapshot_json", "reference_snapshot_json"],
        }.items():
            current = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            for col in cols:
                if col in current:
                    conn.execute(f"ALTER TABLE {table} DROP COLUMN {col}")
        conn.execute("DELETE FROM schema_version WHERE version = 2")
    migrated = StorageManager(legacy_dir)
    check("v1.8.1 数据库原地迁移到 v2+", migrated.status()["schema_version"] >= 2)
    check("迁移保留旧用户与钱包",
          migrated.get_user(u1["user_id"]) is not None
          and migrated.wallet(u1["user_id"])["points"] >= 0)
    with sqlite3.connect(legacy_dir / "profiles.db") as conn:
        cols2 = {r[1] for r in conn.execute("PRAGMA table_info(calibrations)").fetchall()}
    check("迁移补齐校准新列", {"calibration_date", "device_key", "stages_json"} <= cols2)

    print(f"\n{len(passed)} 项 v1.8.2 验收通过")


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
