#!/usr/bin/env python3
"""v1.9.4 体验修复静态与存储回归（不触碰真实数据目录）。

覆盖：
  * daily_v3 协议与旧 daily_v2 的不可比边界；
  * 刺激条件/教学事件写入校准记录，Schema 4 不变，旧长期参考不被覆盖；
  * 平静池塘、确认跳跃、防连点、子弹时间渐变、开始动画小蛙；
  * 开发者顶部栏宽度收口、家长中心留白、头像统一、逐件定价。
"""
from __future__ import annotations

import re
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import calibration as ce  # noqa: E402
from app import difficulty, growth  # noqa: E402
from app.storage import StorageManager, SCHEMA_VERSION  # noqa: E402

passed = []
fails = []


def check(name, cond, detail=""):
    if cond:
        passed.append(name)
        print(f"PASS {name}")
    else:
        fails.append(name)
        print(f"FAIL {name}" + (f" — {detail}" if detail else ""))


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def main():
    tmp = Path(tempfile.mkdtemp(prefix="focus-frog-v194-"))
    store = StorageManager(tmp)

    # ---- 协议与可比性 ----
    check("协议版本为 daily_v3", ce.PROTOCOL_VERSION == "daily_v3", ce.PROTOCOL_VERSION)
    check("刺激条件定义为低刺激睁眼池塘",
          ce.STIMULUS_CONDITION.get("natural_stage") == "fixed_low_stimulation_pond"
          and ce.STIMULUS_CONDITION.get("natural_eyes") == "open"
          and ce.STIMULUS_CONDITION.get("video") == "none"
          and ce.STIMULUS_CONDITION.get("not_strict_resting_eeg") is True)

    at = 1_800_000_000_000
    today = ce.local_date(at, -480)
    dev = "hardware|7000,8000|256|"
    base = {"is_valid": True, "kind": "daily", "source_name": "hardware",
            "device_key": dev, "calibration_date": today, "at": at,
            "range": {"low": .3, "high": .7}}
    v3 = dict(base, id="v3", protocol_version="daily_v3")
    v2 = dict(base, id="v2", protocol_version="daily_v2")
    check("daily_v3 当日校准可复用",
          ce.daily_status([v3], now_ms=at + 1000, mode="hardware",
                          device=dev, tz_offset_min=-480)["valid"])
    check("daily_v2 不与 v3 混算",
          not ce.daily_status([v2], now_ms=at + 1000, mode="hardware",
                              device=dev, tz_offset_min=-480)["valid"])

    # ---- Schema 与记录 ----
    check("Schema 仍为 4", SCHEMA_VERSION == 4 and store.status()["schema_version"] == 4)
    u = store.create_user("v194", "frog")["user_id"]
    v2cal = store.add_calibration(u, {
        "baseline": .5, "range": {"low": .3, "high": .7},
        "quantiles": {"q15": .3, "q50": .5, "q85": .7},
        "protocol_version": "daily_v2", "mapping_version": "map_v2", "status": "ok",
        "calibration_date": today, "timezone_offset_min": -480,
        "device_key": dev, "effective_sec": 60,
    }, source={"name": "hardware", "osc_ports": "7000,8000", "osc_fs": 256})
    ref_before = store.reference_baseline(u)
    check("旧协议校准保留为历史记录", v2cal["protocol_version"] == "daily_v2")

    v3cal = store.add_calibration(u, {
        "baseline": .6, "range": {"low": .4, "high": .8},
        "quantiles": {"q15": .4, "q50": .6, "q85": .8},
        "protocol_version": "daily_v3", "mapping_version": "map_v2", "status": "ok",
        "calibration_date": today, "timezone_offset_min": -480,
        "device_key": dev, "effective_sec": 60,
    }, source={"name": "hardware", "osc_ports": "7000,8000", "osc_fs": 256,
               "stimulus_condition": ce.STIMULUS_CONDITION,
               "tutorial_events": [{"in_zone": True, "accepted": True, "demo": False}]})
    ref_after = store.reference_baseline(u)
    check("v3 校准写入协议版本", v3cal["protocol_version"] == "daily_v3")
    check("刺激条件与教学事件随记录保存",
          (v3cal["source"].get("stimulus_condition") or {}).get("version") == "calm_pond_open_eyes_v1"
          and len(v3cal["source"].get("tutorial_events") or []) == 1)
    check("旧长期参考不被静默覆盖", ref_before and ref_after and ref_before["id"] == ref_after["id"])
    with sqlite3.connect(store.db_path) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(calibrations)").fetchall()}
    check("未为元数据新增数据库列", "stimulus_json" not in cols and "protocol_version" in cols)

    # ---- 页面静态契约 ----
    cal = read("web/calibrate.html")
    check("平静阶段不再使用外部视频", "relax.mp4" not in cal and "<video" not in cal)
    check("平静画面使用池塘 canvas", 'id="calm-pond"' in cal and "assets/calm-pond.js" in cal)
    check("平静文案与需求一致",
          "陪小蛙休息一会儿。自然呼吸，放松身体，轻轻看着小蛙，不需要按任何按钮。" in cal)
    check("教学按钮统一为确认跳跃", "确认跳跃" in cal and "点一下，陪小蛙起跳" not in cal)
    check("教学使用预设进度且不依赖基线",
          "TUT_PRESET" in cal and "zoneLo: 58" in cal and "chargePerSec: 26" in cal)
    check("教学防连点/长按/按键重复",
          "tapLockSec" in cal and "e.repeat" in cal and "tutLockUntil" in cal)
    check("教学明确连续点击不加分", "连续点击都<b>不会提高脑电分数</b>" in cal or "连续点击不会提高脑电分数" in cal)
    check("校准音乐暂停与恢复", "pauseMusicForCalibration" in cal and "restoreMusicAfterCalibration" in cal)
    check("提交 daily_v3 与刺激/教学上下文",
          'protocol: "daily_v3"' in cal and "stimulus_condition" in cal and "teaching: state.teaching" in cal)

    game = read("web/game.html")
    check("子弹时间 250ms 渐变",
          "bulletDim" in game and "dt / 0.25" in game and "createRadialGradient" in game)
    check("开始动画小蛙不再因 window.PondEffects 静默缺失",
          'const PE = window.PondEffects || (typeof PondEffects !== "undefined"' in game
          and "PE.paintFrog(c, shapes, mouth)" in game)
    check("子弹时间不改变 2.5s 窗口", "bulletTimeSec: 2.5" in read("web/assets/focus-round.js"))

    monitor_css = read("web/assets/eeg-monitor.css")
    check("开发者顶部栏限制 1120px 并居中",
          "max-width: 1120px" in monitor_css and "justify-self: center" in monitor_css)

    growth_css = read("web/assets/growth.css")
    check("家长中心 20px 间距与图表留白",
          "#parent-content" in growth_css and "gap: 20px" in growth_css
          and "padding: 18px 20px 20px" in growth_css)

    profiles = read("web/profiles.html")
    avatars_js = read("web/assets/avatars.js")
    check("头像统一容器与九宫格图片",
          "avatar-badge" in profiles and "AvatarArt" in profiles and "avatar-img" in profiles)
    check("九张头像素材与旧 ID 兼容",
          all((ROOT / "web/assets/avatars" / f"avatar_{i:02d}.png").exists() for i in range(1, 10))
          and all(x in avatars_js for x in ["frog", "tadpole", "lotus", "fish", "dragonfly", "snail"]))

    dressup = read("web/assets/dressup.js")
    check("商城改为逐件定价而非统一倍率", "PRICE_MULT" not in dressup and "逐件定价" in dressup)
    prices = [int(m.group(1)) for m in re.finditer(r'id:\s*"[^"]+",.*?price:\s*(\d+)', dressup, re.S)]
    check("所有可购买价格落在 24–240", prices and min(prices) == 24 and max(prices) == 240,
          f"{min(prices) if prices else None}-{max(prices) if prices else None}")
    entry = [p for p in prices if p <= 60]
    normal = [p for p in prices if 60 < p <= 95]
    rare = [p for p in prices if 95 < p <= 150]
    special = [p for p in prices if p > 150]
    check("价格形成四档差异", len(entry) >= 15 and len(normal) >= 10 and len(rare) >= 6 and len(special) >= 3,
          f"{len(entry)}/{len(normal)}/{len(rare)}/{len(special)}")

    # ---- v1.9.4 补充：10% 起点、难度安全与标准评估条件 ----
    check("服务端起始蓄力同步为 10%", difficulty.CONFIG["start_energy"] == 10.0)
    low = difficulty.zone_bounds(0.6)
    first_low = difficulty.zone_bounds(0.6, first_round=True)
    check("最低难度金区仍高于 10% 起点 2 个百分点",
          low["zone_low_min"] >= 12.0 and first_low["zone_low_min"] >= 12.0,
          (low, first_low))
    base_rec = {"protocol_version": "standard_v1", "planned_sec": 90,
                "fixed_factor": 1.0, "reference_baseline_id": "ref-1",
                "device_key": "dev-1"}
    report = {"algorithm_version": "algo-v1", "mapping_version": "map-v2"}
    ref = {"version": 1, "reference_baseline_id": "ref-1", "device_key": "dev-1"}
    old_cond = growth._conditions(base_rec, report, ref, {}, {"device_key": "dev-1"}, {
        "difficulty": {"params_version": "v1.8.3", "game_params_version": "v1.8.3",
                       "strategy_version": "adaptive_v1", "start_energy": 15.0}})
    new_cond = growth._conditions(base_rec, report, ref, {}, {"device_key": "dev-1"}, {
        "difficulty": {"params_version": "v1.9.4", "game_params_version": "v1.9.4",
                       "strategy_version": "adaptive_v1", "start_energy": 10.0}})
    check("15% 与 10% 评估记录不进入同一趋势条件",
          old_cond["key"] and new_cond["key"] and old_cond["key"] != new_cond["key"],
          (old_cond, new_cond))
    check("评估条件显式记录起始蓄力与玩法参数版本",
          new_cond["values"]["start_energy"] == 10.0
          and new_cond["values"]["game_params_version"] == "v1.9.4"
          and "起始蓄力 10%" in new_cond["label"], new_cond)

    server = read("app/server.py")
    check("工作台 report.assessment=null 防御",
          "report_meta" in server and "assessment_meta" in server)
    check("版本号已提升到 1.9.5", 'version="1.9.5"' in server)

    print()
    print(f"{len(passed)} passed, {len(fails)} failed")
    if fails:
        print("failed:", ", ".join(fails))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
