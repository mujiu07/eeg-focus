#!/usr/bin/env python3
"""v1.8.3 自适应难度工程模拟（固定随机种子）。

这不是儿童实验，也不替代真实 Xmuse 采集；它用与
web/assets/focus-round.js 相同的蓄力/区域/基础分公式做可重复的工程对照。
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import difficulty as diff  # noqa: E402

FR_CONFIG = {
    "chargeZeroScore": 42.0,
    "chargeGainPerScoreSec": 0.16,
    "vRefScore": 65.0,
    "startEnergy": 15.0,
    "scoreBase": 20.0,
    "scoreSpan": 80.0,
}

PROFILES = [
    {"key": "slow", "label": "稳定低速蓄力", "score": 44.0, "click": 0.95, "early": 0.0, "signal": 0.98},
    {"key": "fast", "label": "稳定高效蓄力", "score": 100.0, "click": 0.95, "early": 0.0, "signal": 0.98},
    {"key": "click", "label": "蓄力正常、点击较低", "score": 80.0, "click": 0.42, "early": 0.0, "signal": 0.98},
    {"key": "spam", "label": "高频提前点击", "score": 80.0, "click": 0.90, "early": 8.0, "signal": 0.98},
    {"key": "longwait", "label": "长时间无法进入区域", "score": 43.0, "click": 0.95, "early": 0.0, "signal": 0.98},
    {"key": "noenergy", "label": "没有有效蓄力", "score": 42.0, "click": 0.95, "early": 0.0, "signal": 0.98},
    {"key": "noisy", "label": "设备频繁断流", "score": 80.0, "click": 0.95, "early": 0.0, "signal": 0.50},
]


def speed_for(score: float) -> float:
    return max(0.0, (score - FR_CONFIG["chargeZeroScore"]) * FR_CONFIG["chargeGainPerScoreSec"])


def potential(distance: float, charge: float) -> int:
    vref = speed_for(FR_CONFIG["vRefScore"])
    tref = distance / vref if vref > 0 else 0
    if tref <= 0:
        return 20
    return max(20, min(100, round(FR_CONFIG["scoreBase"]
                                   + FR_CONFIG["scoreSpan"] * tref / (charge + tref))))


def simulate_game(factor: float, profile: dict, rng: random.Random, *, seed: int) -> dict:
    bounds = diff.zone_bounds(factor)
    speed = speed_for(profile["score"])
    rounds = []
    incomplete = None
    elapsed = 0.0
    early = 0
    cooldown = 0.0
    while elapsed < 60.0:
        lo = rng.uniform(bounds["zone_low_min"], bounds["zone_low_max"])
        distance = max(0.0, lo - FR_CONFIG["startEnergy"])
        if speed <= 0:
            incomplete = {
                "round": len(rounds) + 1, "phase": "CHARGING", "entered": False,
                "eval_sec": 60.0, "charge_sec": 60.0, "zone_lo": lo,
                "zone_hi": lo + bounds["zone_width"], "energy": FR_CONFIG["startEnergy"],
                "start_energy": FR_CONFIG["startEnergy"], "energy_gain": 0.0,
                "cooldown_sec": 0.0, "ended_reason": "time_up",
            }
            break
        charge = distance / speed
        if elapsed + charge > 60.0:
            remaining = max(0.0, 60.0 - elapsed)
            incomplete = {
                "round": len(rounds) + 1, "phase": "CHARGING", "entered": False,
                "eval_sec": round(remaining, 3), "charge_sec": round(remaining, 3),
                "zone_lo": round(lo, 3), "zone_hi": round(lo + bounds["zone_width"], 3),
                "energy": round(FR_CONFIG["startEnergy"] + speed * remaining, 3),
                "start_energy": FR_CONFIG["startEnergy"],
                "energy_gain": round(speed * remaining, 3),
                "cooldown_sec": 0.0, "ended_reason": "time_up",
            }
            break
        success = rng.random() < profile["click"]
        award = potential(distance, charge) if success else 0
        rounds.append({
            "round": len(rounds) + 1, "eval_sec": round(charge, 3),
            "charge_sec": round(charge, 3), "cooldown_sec": 0.0,
            "zone_lo": round(lo, 3), "zone_hi": round(lo + bounds["zone_width"], 3),
            "zone_width": bounds["zone_width"], "potential": potential(distance, charge),
            "success": success, "awarded": award,
        })
        if profile["early"] > 0 and rng.random() < 0.25:
            early += int(profile["early"])
            cooldown += 0.5
        # 估算正式游戏中的跳跃动画/点击/转场占时；评估时间不包含这些。
        elapsed += charge + 0.8
    active = sum(float(r.get("eval_sec") or 0) for r in rounds)
    if incomplete:
        active += float(incomplete.get("eval_sec") or 0)
    return {
        "seed": seed,
        "rounds": rounds,
        "incomplete": incomplete,
        "planned_sec": 60.0,
        "played_sec": 60.0,
        "active_sec": round(active, 3),
        "signal": profile["signal"],
        "early": early,
        "cooldown": round(cooldown, 3),
    }


def report_from_game(game: dict, factor: float, sid: str) -> dict:
    return {
        "session_id": sid, "purpose": "game", "demo": False,
        "source": {"name": "hardware"}, "planned_sec": game["planned_sec"],
        "played_sec": game["played_sec"], "duration_sec": 60,
        "n_frames": 600, "n_valid_frames": int(600 * game["signal"]),
        "valid_signal_ratio": game["signal"], "calibration_id": "sim-cal",
        "difficulty_snapshot": diff.snapshot(factor),
        "actions": {
            "rounds": game["rounds"], "incomplete_round": game["incomplete"],
            "early_taps": game["early"],
        },
    }


def summarize(games: list[dict], decisions: list[dict]) -> dict:
    rounds = [r for g in games for r in g["rounds"]]
    entered = len(rounds)
    success = sum(1 for r in rounds if r["success"])
    evals = sorted(float(r["eval_sec"]) for r in rounds)
    median = (evals[len(evals)//2] if len(evals) % 2
              else (evals[len(evals)//2 - 1] + evals[len(evals)//2]) / 2) if evals else None
    total_score = sum(int(r["awarded"] or 0) for r in rounds)
    points = sum(max(1, int(r["awarded"] or 0) // 30) if (r["awarded"] or 0) > 0 else 0
                 for r in rounds)
    return {
        "games": len(games),
        "entered": entered,
        "success": success,
        "click_rate": round(success / entered, 4) if entered else None,
        "median_net_charge_sec": round(median, 3) if median is not None else None,
        "avg_single_score": round(total_score / entered, 2) if entered else None,
        "total_game_score": total_score,
        "mall_points": points,
        "decision_counts": {d: sum(1 for x in decisions if x["decision"] == d)
                            for d in diff.DECISIONS},
    }


def run_profile(profile: dict, adaptive: bool, count: int = 10) -> tuple[list[dict], list[dict], float]:
    rng = random.Random(f"v183:{profile['key']}:{'adaptive' if adaptive else 'fixed'}")
    factor = diff.CONFIG["default_factor"]
    streak_hard = streak_easy = 0
    games, decisions = [], []
    for i in range(count):
        game = simulate_game(factor, profile, rng, seed=i + 1)
        rep = report_from_game(game, factor, f"{profile['key']}-{i+1}")
        metrics = diff.compute_metrics(rep)
        plan = diff.decide(metrics, factor=factor, auto_enabled=True,
                           streak_hard=streak_hard, streak_easy=streak_easy)
        game["factor"] = factor
        game["metrics"] = metrics
        game["plan"] = plan
        games.append(game)
        decisions.append(plan)
        if adaptive:
            factor = plan["next_factor"]
            streak_hard, streak_easy = plan["streak_hard"], plan["streak_easy"]
    return games, decisions, factor


def compact_series(games: list[dict]) -> list[dict]:
    return [{
        "factor": game["factor"],
        "median_net_charge_sec": game["metrics"].get("median_net_charge_sec"),
        "entered": game["metrics"].get("entered_count"),
        "success": game["metrics"].get("success_count"),
        "score": sum(int(r.get("awarded") or 0) for r in game["rounds"]),
        "incomplete": bool(game.get("incomplete")),
        "decision": game["plan"].get("decision"),
        "next_factor": game["plan"].get("next_factor"),
    } for game in games]


def main() -> None:
    result = {"config": diff.CONFIG, "profiles": {}}
    for profile in PROFILES:
        fixed_games, fixed_dec, _ = run_profile(profile, False)
        adaptive_games, adaptive_dec, final_factor = run_profile(profile, True)
        result["profiles"][profile["key"]] = {
            "label": profile["label"],
            "fixed": summarize(fixed_games, fixed_dec),
            "adaptive": summarize(adaptive_games, adaptive_dec),
            "adaptive_final_factor": final_factor,
            "fixed_series": compact_series(fixed_games),
            "adaptive_series": compact_series(adaptive_games),
        }
    out = ROOT / "outputs" / "v1.8.3"
    out.mkdir(parents=True, exist_ok=True)
    (out / "simulation.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("| 场景 | 模式 | 最终难度 | 中位净蓄力 | 进入/成功 | 点击率 | 平均单次 | 累计积分 | 商城积分 |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for profile in PROFILES:
        item = result["profiles"][profile["key"]]
        for mode in ("fixed", "adaptive"):
            s = item[mode]
            label = "固定" if mode == "fixed" else "自适应"
            factor = 1.0 if mode == "fixed" else item["adaptive_final_factor"]
            print(f"| {profile['label']} | {label} | {factor:.3f} | "
                  f"{s['median_net_charge_sec'] if s['median_net_charge_sec'] is not None else '—'} | "
                  f"{s['entered']} / {s['success']} | "
                  f"{s['click_rate'] if s['click_rate'] is not None else '—'} | "
                  f"{s['avg_single_score'] if s['avg_single_score'] is not None else '—'} | "
                  f"{s['total_game_score']} | {s['mall_points']} |")
    print(f"\n模拟结果已写入 {out / 'simulation.json'}")


if __name__ == "__main__":
    main()
