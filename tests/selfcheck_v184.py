#!/usr/bin/env python3
"""v1.8.4 开发者工作台、瓶颈诊断、标准评估与隔离验收。

所有写入都在临时目录，不触碰真实个人档案。
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
TMP = Path(tempfile.mkdtemp(prefix="专注小蛙 v184 "))
DATA = TMP / "专注 小蛙"
os.environ["HOME"] = str(TMP / "home")
(TMP / "home").mkdir()
os.environ["FOCUS_FROG_DATA_DIR"] = str(DATA)
os.environ["FOCUS_FROG_IMPORT_LEGACY"] = "0"
os.environ["FOCUS_FROG_SESSION_TTL_SEC"] = "0"
sys.path.insert(0, str(ROOT))

from app import calibration as ce  # noqa: E402
from app import dev_export  # noqa: E402
from app import diagnostics  # noqa: E402
from app import difficulty as diff  # noqa: E402
from app import server as srv  # noqa: E402
from app.storage import StorageManager  # noqa: E402

passed = []


def check(name, condition, detail=""):
    if not condition:
        raise AssertionError(f"{name} 失败 {detail}")
    passed.append(name)
    print(f"PASS {name}")


def rnd(sec=8.0, *, factor=1.0, success=True, cooldown=0.0, active=None,
        below=None, decay=0.0, energy_gain=4.0, energy_loss=0.0, early=0,
        click_rate=None, zone=30.0, mean_score=55.0):
    ev = float(sec)
    active = ev if active is None else float(active)
    below = 0.0 if below is None else float(below)
    return {
        "round": 1, "eval_sec": ev, "charge_sec": ev + cooldown,
        "charge_active_sec": active, "below_threshold_sec": below,
        "cooldown_sec": cooldown, "decay_sec": decay, "decay_events": 1 if decay else 0,
        "energy_gain": energy_gain, "energy_gain_total": energy_gain,
        "energy_loss": energy_loss, "energy_net": energy_gain - energy_loss,
        "zone_lo": zone, "zone_hi": zone + 6, "zone_width": 6,
        "potential": 60, "awarded": 55 if success else 0, "success": success,
        "difficulty_factor": factor, "early_taps": early, "mean_score": mean_score,
        "reaction_sec": 0.2 if success else None, "multiplier": 1 if success else 0,
    }


def report(sid, *, factor=1.0, rounds=None, source="hardware", signal=.98,
           planned=90, played=90, purpose="game", cal_status="ok",
           device="hw|1", demo=False, incomplete=None, early=0):
    rounds = rounds or []
    cal = {"id": "cal-test", "status": cal_status, "device_key": device,
           "range": {"low": .3, "high": .7}, "effective_sec": 60,
           "n_frames": 240, "algorithm_version": "focus_engine_v1.8.2"}
    return {
        "session_id": sid, "purpose": purpose, "demo": demo,
        "source": {"name": source, "label": source}, "planned_sec": planned,
        "played_sec": played, "duration_sec": played,
        "n_frames": 600, "n_valid_frames": int(600 * signal), "valid_signal_ratio": signal,
        "calibration_id": "cal-test", "calibration_snapshot": cal,
        "device_key": device, "difficulty_snapshot": diff.snapshot(factor),
        "score_mean": 55, "above_mid_ratio": .6,
        "actions": {"early_taps": early, "rounds": rounds,
                    "incomplete_round": incomplete},
    }


def calibration(user_id: str, m: StorageManager, *, device="hardware|7000,8000||"):
    return m.add_calibration(user_id, {
        "baseline": .5, "range": {"low": .3, "high": .7},
        "quantiles": {"q15": .3, "q85": .7}, "n_frames": 240,
        "protocol_version": ce.PROTOCOL_VERSION, "status": "ok",
        "calibration_date": ce.local_date(int(time.time() * 1000), -480),
        "timezone_offset_min": -480, "device_key": device, "effective_sec": 60,
    }, source={"name": "hardware", "osc_ports": "7000,8000", "osc_fs": 256})


def main():
    m = StorageManager(DATA)
    check("Schema v4", m.status()["schema_version"] >= 4, m.status())
    with sqlite3.connect(DATA / "profiles.db") as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        session_cols = {r[1] for r in conn.execute("PRAGMA table_info(sessions)")}
        round_cols = {r[1] for r in conn.execute("PRAGMA table_info(rounds)")}
    check("评估表存在", "assessments" in tables, tables)
    check("Session purpose/assessment 列存在", {"purpose", "assessment_id"} <= session_cols, session_cols)
    check("蓄力过程列存在", {"eval_sec", "charge_active_sec", "energy_loss", "jump_anim_sec"} <= round_cols, round_cols)

    # 1. 蓄力过程统计：明确分母，不把冷却混入 eval
    rounds = [
        rnd(8, cooldown=2, active=6, below=2, energy_gain=8, energy_loss=1),
        rnd(10, cooldown=1, active=8, below=2, energy_gain=10, energy_loss=2),
        rnd(12, cooldown=0, active=9, below=3, energy_gain=12, energy_loss=0),
    ]
    r = report("proc-1", rounds=rounds)
    proc = diagnostics.charge_process(r)
    check("charge_sec 汇总含冷却", proc["charge_sec"] == 33, proc)
    check("eval_sec 汇总不含冷却", proc["eval_sec"] == 30, proc)
    check("有效蓄力与低于阈值分母", proc["charge_active_sec"] == 23 and proc["below_threshold_sec"] == 7, proc)
    check("能量增长/损失为累计值", proc["energy_gain_total"] == 30 and proc["energy_loss"] == 3, proc)
    check("过程比值可解释", proc["cooldown_ratio_of_charge"] == round(3 / 33, 4), proc)

    # 2. 诊断多条件与最低难度
    slow = report("slow-min", factor=.6, rounds=[rnd(20, factor=.6) for _ in range(6)])
    d = diagnostics.diagnose(slow)
    ids = {x["id"] for x in d["active"]}
    check("低速场景触发慢蓄力", "slow_charge" in ids, d)
    check("最低难度仍难触发独立诊断", "min_difficulty_still_hard" in ids, d)
    check("诊断不是医学结论", d["engineering_only"] and d["not_medical_advice"], d)

    behavior = report("behavior", rounds=[
        rnd(8, success=False, cooldown=3, decay=3, early=1, mean_score=20),
        rnd(8, success=False, cooldown=3, decay=3, early=1, mean_score=20),
        rnd(8, success=False, cooldown=3, decay=3, early=1, mean_score=20),
    ], early=3)
    bd = diagnostics.diagnose(behavior)
    bids = {x["id"] for x in bd["active"]}
    check("点击失败/冷却/衰减可同时成立",
          {"zone_click_miss", "early_tap_cooldown", "frequent_decay"} <= bids, bd)
    noisy = report("noisy", signal=.5, rounds=[rnd(8) for _ in range(3)])
    nd = diagnostics.diagnose(noisy)
    check("低信号率触发设备诊断", "signal_dropout" in {x["id"] for x in nd["active"]}, nd)
    badcal = report("badcal", cal_status="invalid", rounds=[rnd(8) for _ in range(3)])
    cd = diagnostics.diagnose(badcal)
    check("校准无效触发校准诊断", "calibration_invalid" in {x["id"] for x in cd["active"]}, cd)
    empty = diagnostics.diagnose(report("empty", rounds=[]))
    check("无数据只报告数据不足", "insufficient_data" in {x["id"] for x in empty["active"]}, empty)

    # 3. 客户端数据边界/一致性
    bad = {"rounds": [{"round": 1, "eval_sec": 8, "charge_sec": 10},
                      {"round": 1, "eval_sec": 8, "charge_sec": 10},
                      {"round": 2, "eval_sec": 8, "charge_sec": 10}]}
    q = diagnostics.validate_actions(bad, 90, 90)
    check("重复轮次被排除并记录", q["dropped_rounds"] >= 1 and any("重复" in x for x in q["warnings"]), q)
    q2 = diagnostics.validate_actions({"rounds": [{"round": 2, "eval_sec": 99, "charge_sec": 8}]}, 90, 90)
    check("eval 大于 charge 被排除", q2["accepted_rounds"] == [], q2)

    # 4. 难度公式边界：D 是从起始能量到金色区域入口的距离
    snap06 = diff.snapshot(.6)
    check("最低难度安全下界 12%", snap06["zone_low_min"] >= 12, snap06)
    check("安全下界高于起始蓄力 2 个百分点",
          snap06["zone_low_min"] >= diff.CONFIG["start_energy"] + 2, snap06)
    p1 = diff.snapshot(1.0)
    check("标准难度黄色区域 24–55", p1["zone_low_min"] == 24 and p1["zone_low_max"] == 55, p1)

    # 5. 标准评估存储隔离
    u1 = m.create_user("小评估", "frog")
    u2 = m.create_user("另一人", "fish")
    cal = calibration(u1["user_id"], m)
    ref = m.reference_baseline(u1["user_id"])
    check("有效校准建立长期参考", bool(ref), ref)
    before_wallet = m.wallet(u1["user_id"])
    before_factor = m.difficulty_profile(u1["user_id"])["factor"]
    a = m.create_assessment(u1["user_id"], "asm-session-1", planned_sec=90,
                            seed="seed-1", simulation=False, calibration_id=cal["id"],
                            reference_baseline_id=ref["id"], device={"device_key": "hardware|7000,8000||"})
    check("评估记录创建", a["assessment_id"].startswith("asm_") and a["status"] == "running", a)
    rep = report("asm-session-1", purpose="assessment", factor=1.0, rounds=[rnd(8) for _ in range(3)])
    rep["assessment_id"] = a["assessment_id"]
    rep["assessment"] = {"protocol_version": "standard_v1", "planned_sec": 90, "seed": "seed-1", "simulation": False}
    rep["user_id"] = u1["user_id"]
    m.persist_session(rep, u1["user_id"])
    done = m.complete_assessment("asm-session-1", rep)
    check("评估完成并保存行为特征", done["status"] == "completed" and done["behavior"]["rounds"] == 3, done)
    check("评估不发商城积分", m.wallet(u1["user_id"]) == before_wallet, m.wallet(u1["user_id"]))
    check("评估不改个人难度", m.difficulty_profile(u1["user_id"])["factor"] == before_factor)
    check("评估不写难度历史", len(m.difficulty_history(u1["user_id"])) == 0, m.difficulty_history(u1["user_id"]))
    done2 = m.complete_assessment("asm-session-1", report("asm-session-1", purpose="assessment"))
    check("评估完成幂等", done2["status"] == "completed" and done2["behavior"]["rounds"] == 3, done2)
    check("评估历史按用户隔离", len(m.assessments(u2["user_id"])) == 0)

    # 6. 导出脱敏与格式
    payload = dev_export.build_payload(rep, user_id=u1["user_id"], runtime={"version": "1.8.4"})
    raw = dev_export.to_json_bytes(payload).decode("utf-8")
    check("导出不含昵称", "小评估" not in raw and payload["subject"]["nickname_exported"] is False, raw[:200])
    check("导出不含原始高频波形", payload["privacy"]["raw_eeg_exported"] is False
          and "raw" not in payload, payload["privacy"])
    check("JSON 导出含诊断与逐轮", "diagnostics" in payload and "rounds" in payload)
    csv_text = dev_export.to_csv_bytes(payload).decode("utf-8-sig")
    check("CSV 导出含元数据和逐轮", "section,key,value" in csv_text and "round_no" in csv_text, csv_text[:120])

    # 7. 多用户/重启/API 评估
    m2 = StorageManager(DATA)
    check("重启后评估可读取", m2.assessment(a["assessment_id"], u1["user_id"])["status"] == "completed")
    check("重启后个人档案仍在", m2.get_user(u1["user_id"])["nickname"] == "小评估")

    class FakeHardware(srv.sources.ManualSource):
        name = "hardware"

        def start(self): return None

        def stop(self): return None

    async def api_assessment():
        old = srv.sources.create_source
        srv.sources.create_source = lambda cfg: FakeHardware()
        try:
            body = srv.AssessmentCreate(
                mode="hardware", user_id=u1["user_id"], calibration_id=cal["id"],
                device_key="hardware|7000,8000||", timezone_offset_min=-480,
                planned_sec=90, simulation=False,
            )
            created = await srv.create_assessment(body)
            check("API 标准评估返回固定难度 1.00", created["difficulty"]["factor"] == 1.0, created)
            check("API 标准评估返回评估 ID", bool(created["assessment_id"]), created)
            sid = created["session_id"]
            body2 = srv.SessionFinish(
                score=0, played_sec=90, planned_sec=90,
                actions=srv.GameActions(timed_jumps=0, automatic_jumps=0,
                                        rounds=[srv.RoundRecord(round=1, eval_sec=8, charge_sec=8)]),
            )
            fin = await srv.finish_session(sid, body2, x_user_id=u1["user_id"])
            check("API 评估结束不发放积分", fin["earned_points"] == 0, fin)
            check("API 评估报告带诊断", "diagnostics" in fin["report"], fin["report"].keys())
            check("API 评估不进入难度", fin["difficulty"].get("reason") == "assessment_isolated", fin["difficulty"])
            return sid
        finally:
            srv.sources.create_source = old

    asyncio.run(api_assessment())

    # 8. 工作台数据契约
    wb = srv._workbench_payload(user_id=u1["user_id"], session_id=None)
    check("工作台包含运行环境与 Schema", wb["app"]["version"] and wb["app"]["schema_version"] >= 4, wb["app"])
    check("工作台区分真实/模拟源", wb["runtime"]["source_is_real"] in (True, False), wb["runtime"])
    check("工作台含难度历史与双基线入口", "difficulty" in wb and "calibration" in wb, wb.keys())
    check("工作台含评估与脱敏标记", "assessment" in wb and wb["raw_wave_exported"] is False)

    # 9. 场景化回归（A/B/C/D/E/F/G/H/I）
    check("场景A 新用户默认难度", m.difficulty_profile(u2["user_id"])["factor"] == 1.0)
    check("场景B 同日校准有效", m.calibration_status(u1["user_id"], mode="hardware",
          device="hardware|7000,8000||", tz_offset_min=-480)["valid"] is True)
    old_day = m.calibration_status(u1["user_id"], mode="hardware",
                                   device="hardware|7000,8000||",
                                   tz_offset_min=-480, now_ms=int(time.time() * 1000) + 86400000)
    check("场景C 跨日校准失效", old_day["valid"] is False, old_day)
    check("场景D 多用户评估隔离", m.assessments(u2["user_id"]) == [])
    check("场景E 最低难度仍难诊断",
          "min_difficulty_still_hard" in {x["id"] for x in diagnostics.diagnose(slow)["active"]})
    check("场景F 信号异常诊断",
          "signal_dropout" in {x["id"] for x in diagnostics.diagnose(noisy)["active"]})
    check("场景G 评估硬隔离", m.wallet(u1["user_id"]) == before_wallet)
    m3 = StorageManager(DATA)
    check("场景H 重启恢复评估", m3.assessment(a["assessment_id"], u1["user_id"]) is not None)
    check("场景I 重复评估完成不变", m3.complete_assessment("asm-session-1", rep)["behavior"]["rounds"] == 3)

    print(f"\n{len(passed)} 项 v1.8.4 验收通过")


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
