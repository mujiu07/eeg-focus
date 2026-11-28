#!/usr/bin/env python3
"""v1.8.3 个体自适应难度、指标、持久化与隔离验收。

所有写入都在临时 HOME/数据目录，不触碰 Documents 下的真实档案。
"""
from __future__ import annotations

import asyncio
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="专注小蛙 v183 "))
DATA = TMP / "专注 小蛙"
os.environ["HOME"] = str(TMP / "home")
(TMP / "home").mkdir()
os.environ["FOCUS_FROG_DATA_DIR"] = str(DATA)
os.environ["FOCUS_FROG_IMPORT_LEGACY"] = "0"
os.environ["FOCUS_FROG_SESSION_TTL_SEC"] = "0"
sys.path.insert(0, str(ROOT))

from app import difficulty as diff  # noqa: E402
from app import calibration as ce  # noqa: E402
from app import server as srv  # noqa: E402
from app.storage import StorageManager  # noqa: E402

passed = []


def check(name, condition, detail=""):
    if not condition:
        raise AssertionError(f"{name} 失败 {detail}")
    passed.append(name)
    print(f"PASS {name}")


def rnd(sec, *, success=True, cooldown=0.0, zone=30.0, potential=60):
    return {
        "round": 1, "eval_sec": sec, "charge_sec": sec + cooldown,
        "cooldown_sec": cooldown, "zone_lo": zone, "zone_hi": zone + 6,
        "zone_width": 6, "potential": potential, "success": success,
        "difficulty_factor": 1.0,
    }


def report(sid, snap, *, rounds, signal=.98, planned=60, played=60,
           incomplete=None, early=0, source="hardware", demo=False):
    total = sum(float(r.get("eval_sec") or 0) for r in rounds)
    if incomplete:
        total += float(incomplete.get("eval_sec") or 0)
    return {
        "session_id": sid, "purpose": "game", "demo": demo,
        "source": {"name": source}, "planned_sec": planned, "played_sec": played,
        "duration_sec": 60, "n_frames": 600, "n_valid_frames": int(600 * signal),
        "valid_signal_ratio": signal, "calibration_id": (snap or {}).get("calibration_id"),
        "difficulty_snapshot": snap or diff.snapshot(1.0),
        "actions": {
            "early_taps": early,
            "rounds": rounds,
            "incomplete_round": incomplete,
        },
    }


def main():
    m = StorageManager(DATA)
    check("Schema v3", m.status()["schema_version"] >= 3, m.status())

    # 1. 范围与参数
    z = diff.zone_bounds(1.0)
    check("默认黄色区域 24–55%", z["zone_low_min"] == 24 and z["zone_low_max"] == 55, z)
    check("黄色区域宽度固定 6", all(diff.zone_bounds(f)["zone_width"] == 6
                                  for f in (.6, .8, 1, 1.2)))
    z06 = diff.zone_bounds(.6)
    check("最低难度不产生零距离/负距离",
          z06["zone_low_min"] >= diff.CONFIG["start_energy"] + diff.CONFIG["min_zone_distance"], z06)
    check("最低系数保留名义 14.4 记录", z06["nominal_low_min"] == 14.4, z06)
    for f in (.6, .8, 1.0, 1.1, 1.2):
        zz = diff.zone_bounds(f)
        check(f"区域 {f} 完整且不超 92%", zz["zone_low_min"] + zz["zone_width"] <= 92.001, zz)
    check("难度上下限可收敛",
          diff.snapshot(9.0)["factor"] == 1.2 and diff.snapshot(.01)["factor"] == .6)

    # 2. 指标：净蓄力排除冷却，未完成轮次不伪装成完整轮次
    r = report("metric-1", diff.snapshot(1.0), rounds=[
        rnd(15, cooldown=5), rnd(8), rnd(8), rnd(8), rnd(8), rnd(8)
    ])
    mt = diff.compute_metrics(r)
    check("净蓄力评估排除冷却", mt["active_sec"] == 55 and mt["cooldown_sec"] == 5, mt)
    check("中位净蓄力按进入区域轮次", mt["median_net_charge_sec"] == 8, mt)
    check("点击成功率和错过次数", mt["click_rate"] == 1.0 and mt["missed_clicks"] == 0, mt)
    inc = {"eval_sec": 50, "charge_sec": 52, "zone_lo": 50, "zone_hi": 56,
           "entered": False, "energy_gain": 8, "ended_reason": "time_up"}
    mi = diff.compute_metrics(report("metric-2", diff.snapshot(1.0), rounds=[], incomplete=inc))
    check("未完成轮次被识别", mi["incomplete_count"] == 1 and mi["incomplete_sec"] == 50, mi)
    check("未完成轮次保留观察下限", mi["long_wait"] and mi["incomplete_energy_gain"] == 8, mi)
    check("无完整轮次不等同于空数据", mi["active_sec"] == 50, mi)
    check("长时间无进入但有能量增长判定 TOO_HARD",
          diff.classify(mi) == "TOO_HARD", mi)

    # 3. 分类与连续调整
    too_hard = report("hard-1", diff.snapshot(1.0), rounds=[rnd(13), rnd(13), rnd(13), rnd(13)])
    check("中位 >12 判定 TOO_HARD", diff.classify(diff.compute_metrics(too_hard)) == "TOO_HARD")
    easy_rounds = [rnd(3, success=True) for _ in range(15)]
    too_easy = report("easy-1", diff.snapshot(1.0), rounds=easy_rounds)
    check("中位 <4 且点击稳定判定 TOO_EASY", diff.classify(diff.compute_metrics(too_easy)) == "TOO_EASY")
    suitable = report("suit-1", diff.snapshot(1.0), rounds=[rnd(8) for _ in range(6)])
    check("4–12 秒判定 SUITABLE", diff.classify(diff.compute_metrics(suitable)) == "SUITABLE")
    short = report("short-1", diff.snapshot(1.0), rounds=[rnd(8)])
    check("活动不足不推进", diff.classify(diff.compute_metrics(short)) == "INSUFFICIENT_DATA")
    noisy = report("noise-1", diff.snapshot(1.0), rounds=[rnd(8) for _ in range(6)], signal=.5)
    check("信号不足不推进", diff.classify(diff.compute_metrics(noisy)) == "SIGNAL_OR_CALIBRATION_CHECK")
    no_energy = report("noenergy-1", diff.snapshot(1.0), rounds=[], incomplete={
        "eval_sec": 60, "charge_sec": 60, "entered": False, "energy_gain": 0})
    check("没有有效蓄力先查信号/校准",
          diff.classify(diff.compute_metrics(no_energy)) == "SIGNAL_OR_CALIBRATION_CHECK")
    click_bad = report("click-1", diff.snapshot(1.0), rounds=[
        rnd(3, success=(i % 3 == 0)) for i in range(15)
    ])
    check("点击瓶颈不降低蓄力难度",
          diff.classify(diff.compute_metrics(click_bad)) == "BEHAVIOR_BOTTLENECK")
    click_spam = report("spam-1", diff.snapshot(1.0), rounds=[
        rnd(5, success=True) for _ in range(10)
    ], early=6)
    click_spam["actions"]["rounds"][0]["cooldown_sec"] = 10
    check("高频乱点不误判蓄力偏难",
          diff.classify(diff.compute_metrics(click_spam)) == "BEHAVIOR_BOTTLENECK")

    u1 = m.create_user("小宇", "frog")
    u2 = m.create_user("小安", "fish")
    check("新用户默认难度 1.00", m.difficulty_profile(u1["user_id"])["factor"] == 1.0)
    snap = m.begin_difficulty_session(u1["user_id"], calibration_id="c1", device_key="hw|1")
    check("Session 快照携带范围与版本",
          snap["zone_low_min"] == 24 and snap["strategy_version"] == diff.STRATEGY_VERSION, snap)

    d1 = m.record_difficulty(report("hard-a", snap, rounds=[rnd(13), rnd(13), rnd(13), rnd(13)]),
                             u1["user_id"])
    check("第一次偏高只累计不调整", d1["decision"] == "TOO_HARD" and d1["next_factor"] == 1.0, d1)
    snap2 = m.begin_difficulty_session(u1["user_id"], calibration_id="c1", device_key="hw|1")
    d2 = m.record_difficulty(report("hard-b", snap2, rounds=[rnd(13), rnd(13), rnd(13), rnd(13)]),
                             u1["user_id"])
    check("连续两局偏高降低 10%", d2["applied"] and d2["next_factor"] == .9, d2)
    check("调整后计数清零", d2["streak_hard"] == 0 and d2["streak_easy"] == 0, d2)

    u3 = m.create_user("小禾", "lotus")
    snap3 = m.begin_difficulty_session(u3["user_id"], calibration_id="c3", device_key="hw|2")
    easy_rep = report("easy-a", snap3, rounds=[rnd(3) for _ in range(15)])
    e1 = m.record_difficulty(easy_rep, u3["user_id"])
    e2 = m.record_difficulty(report("easy-b", snap3, rounds=[rnd(3) for _ in range(15)]), u3["user_id"])
    e3 = m.record_difficulty(report("easy-c", snap3, rounds=[rnd(3) for _ in range(15)]), u3["user_id"])
    check("连续三局偏低提高 10%", e1["next_factor"] == 1.0 and e2["next_factor"] == 1.0
          and e3["applied"] and e3["next_factor"] == 1.1, (e1, e2, e3))
    check("连续偏低计数清零", e3["streak_easy"] == 0, e3)

    # 4. 幂等、隔离、手动控制、校准重置
    dup = m.record_difficulty(easy_rep, u3["user_id"])
    check("重复结算不重复调整", dup.get("duplicate") and dup["applied"] is False
          and m.difficulty_profile(u3["user_id"])["factor"] == 1.1, dup)
    n_before = len(m.difficulty_history(u3["user_id"]))
    m.record_difficulty(report("replay-x", snap3, rounds=[rnd(3) for _ in range(15)],
                               source="replay"), u3["user_id"])
    m.record_difficulty(report("manual-x", snap3, rounds=[rnd(3) for _ in range(15)],
                               source="manual"), u3["user_id"])
    check("回放/手动不写真实难度档案",
          m.difficulty_profile(u3["user_id"])["factor"] == 1.1
          and len(m.difficulty_history(u3["user_id"])) == n_before)

    # 手动锁定只影响下一局：旧 Session 快照不变，新 Session 读取新系数。
    s_old = m.begin_difficulty_session(u1["user_id"], calibration_id="c1", device_key="hw|1")
    m.set_difficulty(u1["user_id"], factor=.8)
    check("手动改档立即持久化", m.difficulty_profile(u1["user_id"])["factor"] == .8)
    check("旧 Session 快照不回溯", s_old["factor"] == .9, s_old)
    s_new = m.begin_difficulty_session(u1["user_id"], calibration_id="c1", device_key="hw|1")
    check("下一局使用手动难度", s_new["factor"] == .8, s_new)

    # 关闭自动：仍记录指标，但不改系数。
    m.set_difficulty(u1["user_id"], auto_enabled=False)
    lock_before = m.difficulty_profile(u1["user_id"])["factor"]
    locked = m.record_difficulty(report("off-1", s_new, rounds=[rnd(3) for _ in range(15)]),
                                 u1["user_id"])
    check("关闭自动后难度固定且记录评估",
          locked["decision"] == "TOO_EASY" and not locked["applied"]
          and m.difficulty_profile(u1["user_id"])["factor"] == lock_before, locked)
    m.set_difficulty(u1["user_id"], auto_enabled=True)
    m.set_difficulty(u1["user_id"], reset=True)
    check("恢复标准 1.00", m.difficulty_profile(u1["user_id"])["factor"] == 1.0)

    # 重新校准 / 更换设备重置连续计数，但保留系数。
    m.set_difficulty(u1["user_id"], factor=.9)
    m.begin_difficulty_session(u1["user_id"], calibration_id="cal-a", device_key="hw|1")
    m.record_difficulty(report("reset-hard-1", m.begin_difficulty_session(
        u1["user_id"], calibration_id="cal-a", device_key="hw|1"),
        rounds=[rnd(13), rnd(13), rnd(13), rnd(13)]), u1["user_id"])
    p_before = m.difficulty_profile(u1["user_id"])
    m.begin_difficulty_session(u1["user_id"], calibration_id="cal-b", device_key="hw|1")
    p_after = m.difficulty_profile(u1["user_id"])
    check("重新校准重置连续计数", p_before["streak_hard"] >= 0
          and p_after["streak_hard"] == 0 and p_after["factor"] == p_before["factor"],
          (p_before, p_after))

    # 交替高低表现不能来回调整。
    u5 = m.create_user("小满", "snail")
    begin5 = m.begin_difficulty_session(u5["user_id"], calibration_id="cal-alt", device_key="hw|alt")
    m.record_difficulty(report("alt-hard", begin5,
        rounds=[rnd(13), rnd(13), rnd(13), rnd(13)]), u5["user_id"])
    m.record_difficulty(report("alt-suit", begin5, rounds=[rnd(8) for _ in range(6)]), u5["user_id"])
    alt = m.record_difficulty(report("alt-hard-2", begin5,
        rounds=[rnd(13), rnd(13), rnd(13), rnd(13)]), u5["user_id"])
    check("交替高低表现不会频繁调整", alt["next_factor"] == 1.0 and alt["decision"] == "TOO_HARD", alt)

    # 用户隔离与重启持久化
    check("不同用户难度隔离", m.difficulty_profile(u2["user_id"])["factor"] == 1.0)
    m2 = StorageManager(DATA)
    check("重启后恢复个人难度", m2.difficulty_profile(u1["user_id"])["factor"] == p_after["factor"])

    # Session 报告保存实际快照；数据库迁移列存在。
    stored_report = report("db-session", diff.snapshot(.8), rounds=[rnd(8) for _ in range(6)])
    stored_report["user_id"] = u1["user_id"]
    m.persist_session(stored_report, u1["user_id"])
    loaded = m.load_report("db-session", u1["user_id"])
    check("Session 报告保留难度快照", loaded.get("difficulty_snapshot", {}).get("factor") == .8,
          loaded.get("difficulty_snapshot"))
    with sqlite3.connect(DATA / "profiles.db") as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(difficulty_history)").fetchall()}
        pcols = {r[1] for r in conn.execute("PRAGMA table_info(difficulty_profiles)").fetchall()}
    check("难度历史列完整",
          {"before_factor", "after_factor", "direction", "decision", "metrics_json"} <= cols, cols)
    check("难度个人档案列完整",
          {"factor", "auto_enabled", "manual_lock", "streak_hard", "streak_easy"} <= pcols, pcols)

    # API：有当天校准后创建 Session，返回值锁定难度快照。
    u4 = m.create_user("小舟", "fish")
    cal = m.add_calibration(u4["user_id"], {
        "baseline": .5, "range": {"low": .3, "high": .7},
        "quantiles": {"q15": .3, "q85": .7}, "n_frames": 240,
        "protocol_version": ce.PROTOCOL_VERSION, "status": "ok",
        "calibration_date": ce.local_date(int(__import__("time").time() * 1000), -480),
        "timezone_offset_min": -480, "device_key": "hw|api", "effective_sec": 60,
    }, source={"name": "hardware", "osc_ports": "7000,8000", "osc_fs": 256})

    async def api_smoke():
        old = srv.sources.create_source
        srv.sources.create_source = lambda cfg: srv.sources.ManualSource()
        try:
            created = await srv.create_session(srv.SessionCreate(
                mode="hardware", user_id=u4["user_id"], purpose="game",
                device_key="hw|api", timezone_offset_min=-480,
                calibration_id=cal["id"],
            ))
            check("API 返回锁定难度", created["difficulty"]["strategy_version"] == diff.STRATEGY_VERSION)
            check("API Session 锁定默认 1.00", created["difficulty"]["factor"] == 1.0)
            s = srv._sessions[created["session_id"]]
            check("API Session 保存难度快照",
                  s.difficulty_snapshot["zone_low_min"] == 24
                  and s.difficulty_snapshot["zone_low_max"] == 55)
            return created
        finally:
            srv.sources.create_source = old

    asyncio.run(api_smoke())

    # 结束 API：只有落库后才评估，重复 finish 不重复调整。
    class FakeHardware(srv.sources.ManualSource):
        name = "hardware"

        def start(self):
            return None

        def stop(self):
            return None

    async def finish_smoke():
        old = srv.sources.create_source
        srv.sources.create_source = lambda cfg: FakeHardware()
        try:
            created = await srv.create_session(srv.SessionCreate(
                mode="hardware", user_id=u4["user_id"], purpose="game",
                device_key="hw|api", timezone_offset_min=-480,
                calibration_id=cal["id"],
            ))
            sid = created["session_id"]
            body = srv.SessionFinish(
                score=0, played_sec=60, planned_sec=60,
                actions=srv.GameActions(timed_jumps=0, automatic_jumps=0, rounds=[]),
            )
            first = await srv.finish_session(sid, body, x_user_id=u4["user_id"])
            second = await srv.finish_session(sid, body, x_user_id=u4["user_id"])
            check("结束 API 返回难度判定", "difficulty" in first)
            check("重复结束不重复调整", second["difficulty"].get("duplicate") is True, second)
            return first
        finally:
            srv.sources.create_source = old

    asyncio.run(finish_smoke())

    print(f"\n{len(passed)} 项 v1.8.3 验收通过")


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
