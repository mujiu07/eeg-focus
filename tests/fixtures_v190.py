"""v1.9.0 验收用的 A–E 虚构档案生成器。

绝不使用真实数据目录。调用方必须传入临时目录。
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from app import diagnostics, difficulty
from app.storage import StorageManager

DEVICE = "xmuse:4ch:fs256:demo"


def _now_local() -> datetime:
    return datetime.now().astimezone()


def _local_iso(dt: datetime) -> str:
    return dt.astimezone().isoformat(timespec="seconds")


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _rounds(count: int, success: int, low_quality: bool = False) -> list[dict]:
    rows = []
    for i in range(count):
        ok = i < success
        rows.append({
            "round": i + 1,
            "entered": True,
            "success": ok,
            "reaction_sec": round(0.72 + (i % 5) * 0.09, 3) if ok else None,
            "charge_sec": round(7.8 + (i % 4) * 0.6, 3),
            "charge_active_sec": round(6.2 + (i % 3) * 0.4, 3),
            "below_threshold_sec": round(1.0 + (i % 3) * 0.2, 3),
            "eval_sec": round(6.9 + (i % 4) * 0.5, 3),
            "early_taps": 0 if i % 7 else 1,
            "cooldown_sec": 0.0 if i % 7 else 0.4,
            "stale_sec": 0.0,
            "decay_events": 0,
            "decay_sec": 0.0,
            "energy_gain": 7.0,
            "energy_loss": 0.0,
            "bullet_sec": 0.0,
            "jump_anim_sec": 0.8,
            "paused_sec": 0.0,
            "potential": 60 + i,
            "mean_score": 54.0 if not low_quality else 42.0,
        })
    return rows


def _report(
    *,
    uid: str,
    sid: str,
    when: datetime,
    score: Optional[int],
    success: int,
    rounds_count: int,
    source: str = "hardware",
    demo: bool = False,
    purpose: str = "game",
    valid_ratio: Optional[float] = 0.94,
    focus_mean: float = 0.61,
    reference_score: float = 54.0,
    score_mean: float = 52.0,
    difficulty_factor: float = 1.0,
    calibration: Dict[str, Any],
    reference: Dict[str, Any],
    include_rounds: bool = True,
    assessment: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    low = valid_ratio is not None and valid_ratio < diagnostics.MIN_SIGNAL_RATIO
    rounds = _rounds(rounds_count, success, low) if include_rounds else []
    played = 180.0 + rounds_count * 9.0
    return {
        "session_id": sid,
        "created_at": _local_iso(when),
        "duration_sec": played,
        "played_sec": played,
        "planned_sec": 180.0,
        "score": score,
        "purpose": purpose,
        "demo": demo,
        "source": {"name": source, "device_key": DEVICE, "mode": source},
        "algorithm_version": "focus_engine_v1.8.2",
        "n_frames": 1800,
        "n_valid_frames": None if valid_ratio is None else round(1800 * valid_ratio),
        "valid_signal_ratio": valid_ratio,
        "focus_mean": focus_mean,
        "reference_score_mean": reference_score,
        "score_mean": score_mean,
        "score_min": 30,
        "score_max": 72,
        "score_range": {"low": 30, "high": 72},
        "baseline": 0.5,
        "signal_quality": {"usable_ratio": valid_ratio},
        "data_quality": {"status": "low" if low else "ok"},
        "actions": {
            "timed_jumps": success,
            "successful_jumps": success,
            "missed_jumps": max(0, rounds_count - success),
            "early_taps": sum(1 for r in rounds if r.get("early_taps")),
            "rounds": rounds,
            "incomplete_round": None,
        },
        "charge_process": diagnostics.charge_process({"actions": {"rounds": rounds}}),
        "difficulty_snapshot": {
            "factor": difficulty_factor,
            "strategy_version": difficulty.STRATEGY_VERSION,
            "params_version": difficulty.PARAMS_VERSION,
        },
        "calibration_snapshot": {
            "id": calibration.get("id"),
            "status": calibration.get("status", "ok"),
            "device_key": calibration.get("device_key") or DEVICE,
            "algorithm_version": calibration.get("algorithm_version") or "focus_engine_v1.8.2",
            "mapping_version": calibration.get("mapping_version") or "v1",
        },
        "reference_snapshot": {
            "id": reference.get("id"),
            "version": reference.get("version"),
            "label": reference.get("label"),
            "device_key": reference.get("device_key") or DEVICE,
            "algorithm_version": reference.get("algorithm_version") or "focus_engine_v1.8.2",
            "mapping_version": reference.get("mapping_version") or "v1",
        },
        "reference_baseline_id": reference.get("id"),
        "assessment": assessment,
        "assessment_id": (assessment or {}).get("assessment_id"),
    }


def _fix_session_dates(store: StorageManager, sid: str, when: datetime, played: float) -> None:
    with store._db() as conn:
        conn.execute(
            "UPDATE sessions SET started_at=?, ended_at=?, created_at=?, duration_sec=?, played_sec=? "
            "WHERE session_id=?",
            (_local_iso(when), _local_iso(when + timedelta(seconds=played)), _local_iso(when),
             played, played, sid),
        )


def _add_cal(store: StorageManager, uid: str, when: datetime) -> Dict[str, Any]:
    return store.add_calibration(
        uid,
        {
            "baseline": 0.52,
            "quantiles": {"q15": 0.36, "q50": 0.52, "q85": 0.69},
            "range": {"low": 0.36, "high": 0.69},
            "n_frames": 900,
            "effective_sec": 30.0,
            "elapsed_sec": 30.0,
            "protocol_version": "daily_v2",
            "mapping_version": "v1",
            "algorithm_version": "focus_engine_v1.8.2",
            "device_key": DEVICE,
            "status": "ok",
            "is_valid": True,
            "signal_quality": {"usable_ratio": 0.96},
            "stages": {"natural": 30, "teaching": 30},
            "calibrated_at_ms": _ms(when),
            "timezone_offset_min": -480,
        },
        source={"name": "hardware", "device_key": DEVICE, "mode": "hardware"},
        kind="daily",
    )


def _add_game(store: StorageManager, uid: str, when: datetime, n: int, *,
              score: Optional[int], success: int, rounds_count: int,
              valid_ratio: Optional[float] = 0.94, source: str = "hardware",
              demo: bool = False, factor: float = 1.0,
              calibration: Dict[str, Any], reference: Dict[str, Any],
              include_rounds: bool = True) -> str:
    sid = "s_" + uid[-6:] + "_" + when.strftime("%m%d%H%M") + "_" + str(n)
    rep = _report(uid=uid, sid=sid, when=when, score=score, success=success,
                  rounds_count=rounds_count, source=source, demo=demo,
                  valid_ratio=valid_ratio, difficulty_factor=factor,
                  calibration=calibration, reference=reference,
                  include_rounds=include_rounds)
    store.persist_session(rep, uid, calibration.get("id"))
    _fix_session_dates(store, sid, when, rep["played_sec"])
    return sid


def _add_assessment(store: StorageManager, uid: str, when: datetime, n: int, *,
                    simulation: bool = False, valid_ratio: float = 0.94,
                    calibration: Dict[str, Any], reference: Dict[str, Any]) -> str:
    sid = "s_" + uid[-6:] + "_asm_" + when.strftime("%m%d") + "_" + str(n)
    aid = "asm_" + uid[-6:] + "_" + when.strftime("%m%d") + "_" + str(n)
    protocol = "standard_v1"
    seed = "seed" + str(n)
    assessment_meta = {
        "assessment_id": aid,
        "protocol_version": protocol,
        "planned_sec": 90.0,
        "fixed_factor": 1.0,
        "seed": seed,
        "simulation": simulation,
    }
    rep = _report(uid=uid, sid=sid, when=when, score=None, success=7, rounds_count=8,
                  source="manual" if simulation else "hardware", demo=simulation,
                  purpose="assessment", valid_ratio=valid_ratio,
                  focus_mean=0.58 + n * 0.01, reference_score=54.0 + n * 0.8,
                  score_mean=52.0 + n * 0.5, calibration=calibration,
                  reference=reference, assessment=assessment_meta)
    store.create_assessment(
        uid, sid, protocol_version=protocol, planned_sec=90.0, seed=seed,
        simulation=simulation, calibration_id=calibration.get("id"),
        reference_baseline_id=reference.get("id"),
        device={"device_key": DEVICE, "mode": "manual" if simulation else "hardware"},
        params={"protocol_version": protocol, "planned_sec": 90.0, "fixed_factor": 1.0,
                "difficulty": rep["difficulty_snapshot"]},
    )
    rep["assessment_id"] = aid
    store.persist_session(rep, uid, calibration.get("id"))
    store.complete_assessment(sid, rep)
    _fix_session_dates(store, sid, when, rep["played_sec"])
    with store._db() as conn:
        conn.execute(
            "UPDATE assessments SET started_at=?, ended_at=?, created_at=? WHERE session_id=?",
            (_local_iso(when), _local_iso(when + timedelta(seconds=90)), _local_iso(when), sid),
        )
    return sid


def _difficulty_history(store: StorageManager, uid: str, points: list[tuple[datetime, float, float, str]]) -> None:
    store.difficulty_profile(uid)
    for when, before, after, reason in points:
        with store._db() as conn:
            conn.execute(
                "INSERT INTO difficulty_history(user_id,session_id,config_json,reason,created_at,"
                "before_factor,after_factor,direction,decision,metrics_json,calibration_id,"
                "strategy_version,params_version,source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (uid, None, "{}", reason, _local_iso(when), before, after,
                 "up" if after > before else "down", "AUTO_ADJUST", "{}", None,
                 difficulty.STRATEGY_VERSION, difficulty.PARAMS_VERSION, "hardware"),
            )
    with store._db() as conn:
        conn.execute("UPDATE difficulty_profiles SET factor=?, updated_at=? WHERE user_id=?",
                     (points[-1][2] if points else 1.0, _local_iso(_now_local()), uid))


def _assets(store: StorageManager, uid: str, *, wallet: int, owned: list[str], achievements: list[str]) -> None:
    unlocked = {item: _ms(_now_local() - timedelta(days=3)) for item in achievements}
    store.sync_state(uid, {
        "wallet": {"points": wallet, "rounds": 20, "jumps": 180, "spent": 12},
        "owned": owned,
        "achievements": {"unlocked": unlocked},
    })


def build_fixture(root: Path) -> Dict[str, Any]:
    root = Path(root)
    if root.exists():
        # 只清理明确的临时测试目录；调用方负责传入临时路径。
        shutil.rmtree(root)
    store = StorageManager(root)
    # 固定在当天中午，避免测试在午夜前后运行时 7/30 天边界漂移。
    now = _now_local().replace(hour=12, minute=0, second=0, microsecond=0)
    users = {}
    for key, nickname in (("A", "新朋友小芽"), ("B", "小满"), ("C", "小禾"),
                          ("D", "小石"), ("E", "小雨")):
        users[key] = store.create_user(nickname, "frog")["user_id"]

    a = users["A"]
    b = users["B"]
    c = users["C"]
    d = users["D"]
    e = users["E"]

    # B：30 天历史，5 次同一条件评估。
    b_cal = _add_cal(store, b, now - timedelta(days=32))
    b_ref = store.reference_baseline(b)
    for i in range(30):
        when = now - timedelta(days=29 - i, hours=(i % 3) + 1)
        _add_game(store, b, when, i + 1, score=48 + (i % 8) * 4,
                  success=5 + (i % 3), rounds_count=8, valid_ratio=0.93 + (i % 3) * 0.01,
                  factor=0.95 + (i % 4) * 0.02, calibration=b_cal, reference=b_ref)
    for i, days in enumerate((4, 8, 13, 20, 26)):
        _add_assessment(store, b, now - timedelta(days=days, hours=2), i + 1,
                        calibration=b_cal, reference=b_ref)
    _difficulty_history(store, b, [
        (now - timedelta(days=23), 1.0, 0.9, "连续 2 局反馈偏难，难度下调 10%"),
        (now - timedelta(days=12), 0.9, 0.95, "连续 3 局反馈偏易，难度上调 10%"),
        (now - timedelta(days=3), 0.95, 0.9, "连续 2 局反馈偏难，难度下调 10%"),
    ])
    _assets(store, b, wallet=286, owned=["hat-leaf", "face-star", "neck-scarf"],
            achievements=["focus-1", "focus-2", "focus-3", "doctor-1", "spirit-1"])

    # C：中途更换长期参考基线，历史必须分两段。
    c_cal_old = _add_cal(store, c, now - timedelta(days=25))
    c_ref_old = store.reference_baseline(c)
    _add_assessment(store, c, now - timedelta(days=22, hours=2), 1,
                    calibration=c_cal_old, reference=c_ref_old)
    _add_assessment(store, c, now - timedelta(days=18, hours=3), 2,
                    calibration=c_cal_old, reference=c_ref_old)
    c_cal_new = _add_cal(store, c, now - timedelta(days=12))
    c_ref_new = store.add_reference_baseline(c, c_cal_new["id"], "更换设备后的长期参考")
    _add_assessment(store, c, now - timedelta(days=8, hours=2), 3,
                    calibration=c_cal_new, reference=c_ref_new)
    _add_assessment(store, c, now - timedelta(days=3, hours=3), 4,
                    calibration=c_cal_new, reference=c_ref_new)
    for i in range(5):
        _add_game(store, c, now - timedelta(days=20 - i * 4, hours=1), i + 1,
                  score=54 + i, success=6, rounds_count=8, factor=1.0,
                  calibration=c_cal_old if i < 3 else c_cal_new,
                  reference=c_ref_old if i < 3 else c_ref_new)
    _assets(store, c, wallet=92, owned=["hat-leaf"], achievements=["focus-1", "doctor-1"])

    # D：低质量、缺失逐轮、模拟试玩、EDF 回放、模拟评估。
    d_cal = _add_cal(store, d, now - timedelta(days=6))
    d_ref = store.reference_baseline(d)
    _add_game(store, d, now - timedelta(days=5, hours=3), 1, score=30, success=2,
              rounds_count=4, valid_ratio=0.52, calibration=d_cal, reference=d_ref)
    _add_game(store, d, now - timedelta(days=4, hours=4), 2, score=None, success=0,
              rounds_count=0, valid_ratio=None, calibration=d_cal, reference=d_ref,
              include_rounds=False)
    _add_game(store, d, now - timedelta(days=3, hours=5), 3, score=20, success=1,
              rounds_count=3, valid_ratio=0.95, source="replay", demo=False,
              calibration=d_cal, reference=d_ref)
    _add_game(store, d, now - timedelta(days=2, hours=6), 4, score=12, success=1,
              rounds_count=3, valid_ratio=0.95, source="manual", demo=True,
              calibration=d_cal, reference=d_ref)
    _add_assessment(store, d, now - timedelta(days=1, hours=2), 1, simulation=True,
                    calibration=d_cal, reference=d_ref)
    _assets(store, d, wallet=20, owned=[], achievements=["focus-1"])

    # E：另一个独立档案，验证隔离。
    e_cal = _add_cal(store, e, now - timedelta(days=9))
    e_ref = store.reference_baseline(e)
    for i in range(4):
        _add_game(store, e, now - timedelta(days=6 - i, hours=2), i + 1,
                  score=70 + i, success=7, rounds_count=8, factor=1.0,
                  calibration=e_cal, reference=e_ref)
    _assets(store, e, wallet=160, owned=["face-star"], achievements=["focus-2"])

    manifest = {
        "version": "1.9.0-fixture",
        "root": str(root),
        "generated_at": _local_iso(now),
        "users": {key: {"user_id": uid, "nickname": store.get_user(uid)["nickname"]}
                  for key, uid in users.items()},
        "references": {
            "B": {"id": b_ref["id"], "version": b_ref["version"]},
            "C_old": {"id": c_ref_old["id"], "version": c_ref_old["version"]},
            "C_new": {"id": c_ref_new["id"], "version": c_ref_new["version"]},
        },
    }
    (root / "fixture.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    import sys
    target = Path(sys.argv[1] if len(sys.argv) > 1 else ".deepworks/tmp/v190-fixture")
    print(json.dumps(build_fixture(target), ensure_ascii=False, indent=2))
