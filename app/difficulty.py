"""v1.8.3 个体自适应难度的集中配置与纯函数。

边界：
  * 只生成黄色区域起点的随机范围，不修改脑电映射、蓄力速度、区域宽度、
    子弹时间、点击窗口、冷却、积分或商城公式。
  * 局内由 Session 锁定快照；本模块只做局后指标与局间决策。
  * 所有参数集中在此处，方便工程原型调参；不是医学训练标准。
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Optional

STRATEGY_VERSION = "adaptive_v1"
PARAMS_VERSION = "v1.9.4"

CONFIG: dict[str, Any] = {
    # 难度系数
    "default_factor": 1.00,
    "min_factor": 0.60,
    "max_factor": 1.20,
    "down_multiplier": 0.90,
    "up_multiplier": 1.10,
    # 黄色区域：与 web/assets/focus-round.js 的实际配置核对过。
    # 当前正式游戏每轮使用常规范围 24–55%，宽度 6%，末端上限 92%。
    "zone_base_min": 24.0,
    "zone_base_max": 55.0,
    "zone_width": 6.0,
    "zone_hi_max": 92.0,
    "start_energy": 10.0,
    # 低系数时 24×0.60=14.4 仍高于起始能量 10；
    # 保留 2 个百分点最小距离，防止任何配置下“开局即进入区域”。
    "min_zone_distance": 2.0,
    # 评估门槛
    "suitable_min_sec": 4.0,
    "suitable_max_sec": 12.0,
    "long_wait_sec": 12.0,
    "down_streak": 2,
    "up_streak": 3,
    "up_click_rate": 0.85,
    "behavior_click_rate": 0.85,
    "min_signal_ratio": 0.70,
    "min_planned_sec": 60.0,
    "min_active_sec": 45.0,
    "min_up_rounds": 3,
    "behavior_cooldown_ratio": 0.15,
    # 版本标识
    "strategy_version": STRATEGY_VERSION,
    "params_version": PARAMS_VERSION,
}

DECISIONS = (
    "TOO_HARD", "SUITABLE", "TOO_EASY",
    "INSUFFICIENT_DATA", "SIGNAL_OR_CALIBRATION_CHECK",
    "BEHAVIOR_BOTTLENECK",
)


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def round3(v: float) -> float:
    return round(float(v) * 1000) / 1000


def _num(value: Any, fallback: Optional[float] = None) -> Optional[float]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return fallback
    return v if math.isfinite(v) else fallback


def _clamp_factor(factor: Any) -> float:
    return round3(clamp(_num(factor, CONFIG["default_factor"]),
                        CONFIG["min_factor"], CONFIG["max_factor"]))


def zone_bounds(factor: Any = None, *, first_round: bool = False) -> dict:
    """返回实际可用的黄色区域起点范围。

    ``zone_base_min × factor`` 是名义范围；若低于每轮起始能量 + 最小距离，
    会把下界抬起，保证区域完整、可蓄力且不是开局即进入。宽度始终为 6%。
    """
    f = _clamp_factor(factor)
    base_min = 22.0 if first_round else CONFIG["zone_base_min"]
    base_max = 34.0 if first_round else CONFIG["zone_base_max"]
    nominal_min = base_min * f
    nominal_max = base_max * f
    floor = CONFIG["start_energy"] + CONFIG["min_zone_distance"]
    max_start = min(100.0, CONFIG["zone_hi_max"]) - CONFIG["zone_width"]
    lo_min = max(nominal_min, floor)
    lo_max = max(nominal_max, lo_min)
    lo_max = min(lo_max, max_start)
    lo_min = min(lo_min, lo_max)
    return {
        "factor": f,
        "zone_low_min": round3(lo_min),
        "zone_low_max": round3(lo_max),
        "zone_width": round3(CONFIG["zone_width"]),
        "zone_hi_max": round3(CONFIG["zone_hi_max"]),
        "start_energy": round3(CONFIG["start_energy"]),
        "nominal_low_min": round3(nominal_min),
        "nominal_low_max": round3(nominal_max),
        "clamped": bool(lo_min > nominal_min + 1e-9),
    }


def snapshot(factor: Any = None, *, auto_enabled: bool = True,
             manual_lock: bool = False, calibration_id: Optional[str] = None,
             device_key: Optional[str] = None) -> dict:
    """Session 创建时锁定的难度快照；前端只使用这里的范围。"""
    normal = zone_bounds(factor)
    first = zone_bounds(factor, first_round=True)
    return {
        "factor": normal["factor"],
        "auto_enabled": bool(auto_enabled),
        "manual_lock": bool(manual_lock),
        "zone_low_min": normal["zone_low_min"],
        "zone_low_max": normal["zone_low_max"],
        "zone_width": normal["zone_width"],
        "zone_hi_max": normal["zone_hi_max"],
        "start_energy": normal["start_energy"],
        "nominal_zone_min": normal["nominal_low_min"],
        "nominal_zone_max": normal["nominal_low_max"],
        "zone_range_clamped": normal["clamped"],
        "first_zone_low_min": first["zone_low_min"],
        "first_zone_low_max": first["zone_low_max"],
        "first_zone_width": first["zone_width"],
        "strategy_version": STRATEGY_VERSION,
        "params_version": PARAMS_VERSION,
        "game_params_version": PARAMS_VERSION,
        "calibration_id": calibration_id,
        "device_key": device_key,
    }


def _round_eval_sec(rnd: dict) -> float:
    direct = _num(rnd.get("eval_sec"))
    if direct is not None and direct >= 0:
        return direct
    charge = _num(rnd.get("charge_sec"), 0.0) or 0.0
    cooldown = _num(rnd.get("cooldown_sec"), 0.0) or 0.0
    return max(0.0, charge - cooldown)


def _round_entered(rnd: dict) -> bool:
    return (rnd.get("potential") is not None
            or rnd.get("success") is True
            or _num(rnd.get("zone_lo")) is not None)


def _median(values: Iterable[float]) -> Optional[float]:
    vals = sorted(float(v) for v in values if _num(v) is not None)
    if not vals:
        return None
    n = len(vals)
    mid = n // 2
    if n % 2:
        return vals[mid]
    return (vals[mid - 1] + vals[mid]) / 2.0


def compute_metrics(report: dict) -> dict:
    """从 Session 报告计算难度评估指标。

    ``eval_sec`` 由前端单轮状态机提供：只累计 CHARGING 的有效时间，
    已排除断流、主动暂停、子弹时间、跳跃动画和无效点击冷却；
    但保留等待、宽容期与衰减时间。
    """
    source = report.get("source") or {}
    actions = report.get("actions") or {}
    rounds = [r for r in (actions.get("rounds") or []) if isinstance(r, dict)]
    incomplete = actions.get("incomplete_round") if isinstance(
        actions.get("incomplete_round"), dict) else None

    entered_rounds = [r for r in rounds if _round_entered(r)]
    successful = [r for r in entered_rounds if r.get("success") is True]
    incomplete_entered = bool(incomplete and (
        incomplete.get("entered") or incomplete.get("potential") is not None
        or incomplete.get("phase") == "BULLET_TIME"))
    entered_count = len(entered_rounds) + (1 if incomplete_entered else 0)
    success_count = len(successful)
    click_rate = (success_count / entered_count) if entered_count else None

    eval_values = [_round_eval_sec(r) for r in entered_rounds]
    if incomplete and incomplete_entered:
        eval_values.append(_round_eval_sec(incomplete))
    median_net_charge = _median(eval_values)

    active_sec = sum(_round_eval_sec(r) for r in rounds)
    if incomplete:
        active_sec += _round_eval_sec(incomplete)
    cooldown_sec = sum(max(0.0, _num(r.get("cooldown_sec"), 0.0) or 0.0) for r in rounds)
    if incomplete:
        cooldown_sec += max(0.0, _num(incomplete.get("cooldown_sec"), 0.0) or 0.0)
    cooldown_ratio = (cooldown_sec / active_sec) if active_sec > 0 else 0.0

    n_frames = _num(report.get("n_frames"), 0.0) or 0.0
    n_valid = _num(report.get("n_valid_frames"), 0.0) or 0.0
    signal_ratio = _num(report.get("valid_signal_ratio"))
    if n_frames > 0:
        signal_ratio = round(n_valid / n_frames, 4)
    planned_sec = _num(report.get("planned_sec"), 0.0) or 0.0
    played_sec = _num(report.get("played_sec"), 0.0) or 0.0
    duration_sec = _num(report.get("duration_sec"), 0.0) or 0.0
    source_name = str(source.get("name") or report.get("source_name") or "unknown")
    purpose = str(report.get("purpose") or "game")
    demo = bool(report.get("demo"))
    early_taps = int(_num(actions.get("early_taps"), 0.0) or 0)
    if early_taps <= 0:
        early_taps = sum(int(_num(r.get("early_taps"), 0.0) or 0) for r in rounds)

    incomplete_sec = _round_eval_sec(incomplete) if incomplete else 0.0
    incomplete_gain = max(0.0, _num(incomplete.get("energy_gain"), 0.0) or 0.0) if incomplete else 0.0
    incomplete_charge = max(0.0, _num(incomplete.get("charge_sec"), 0.0) or 0.0) if incomplete else 0.0
    enter_events = len(entered_rounds) + (1 if incomplete_entered else 0)

    metrics = {
        "valid_source": source_name == "hardware",
        "source_name": source_name,
        "purpose": purpose,
        "demo": demo,
        "planned_sec": round(planned_sec, 2),
        "played_sec": round(played_sec, 2),
        "duration_sec": round(duration_sec, 2),
        "active_sec": round(active_sec, 2),
        "signal_ratio": None if signal_ratio is None else round(float(signal_ratio), 4),
        "n_frames": int(n_frames),
        "n_valid_frames": int(n_valid),
        "rounds_total": len(rounds),
        "entered_count": enter_events,
        "success_count": success_count,
        "missed_clicks": max(0, enter_events - success_count),
        "click_rate": None if click_rate is None else round(click_rate, 4),
        "median_net_charge_sec": None if median_net_charge is None else round(median_net_charge, 2),
        "early_taps": early_taps,
        "cooldown_sec": round(cooldown_sec, 2),
        "cooldown_ratio": round(cooldown_ratio, 4),
        "incomplete_count": 1 if incomplete else 0,
        "incomplete_sec": round(incomplete_sec, 2),
        "incomplete_charge_sec": round(incomplete_charge, 2),
        "incomplete_energy_gain": round(incomplete_gain, 3),
        "incomplete_entered": incomplete_entered,
        "long_wait": bool(incomplete and not incomplete_entered
                          and incomplete_sec >= CONFIG["long_wait_sec"]),
    }
    return metrics


def _base_checks(metrics: dict) -> dict:
    signal_ok = (metrics.get("signal_ratio") is not None
                 and metrics["signal_ratio"] >= CONFIG["min_signal_ratio"])
    planned_ok = metrics.get("planned_sec", 0) >= CONFIG["min_planned_sec"]
    active_ok = metrics.get("active_sec", 0) >= CONFIG["min_active_sec"]
    return {
        "signal_ok": bool(signal_ok),
        "planned_ok": bool(planned_ok),
        "active_ok": bool(active_ok),
    }


def classify(metrics: dict) -> str:
    """把指标归入三类难度判定或数据/信号/行为阻塞。"""
    checks = _base_checks(metrics)
    if not metrics.get("valid_source") or metrics.get("demo"):
        return "INSUFFICIENT_DATA"
    if metrics.get("purpose") != "game":
        return "INSUFFICIENT_DATA"
    if not checks["signal_ok"]:
        return "SIGNAL_OR_CALIBRATION_CHECK"
    if not checks["planned_ok"]:
        return "INSUFFICIENT_DATA"

    entered = int(metrics.get("entered_count") or 0)
    median = metrics.get("median_net_charge_sec")
    click_rate = metrics.get("click_rate")
    early = int(metrics.get("early_taps") or 0)
    cooldown_ratio = float(metrics.get("cooldown_ratio") or 0.0)

    # 高频提前点击/冷却不是“蓄力太难”；先识别行为瓶颈，避免错误降难度。
    if early >= 2 and cooldown_ratio >= CONFIG["behavior_cooldown_ratio"]:
        return "BEHAVIOR_BOTTLENECK"

    # 没有进入区域：若没有任何有效能量增长，先检查设备/校准/算法适用性。
    if entered == 0:
        if not checks["active_ok"]:
            if metrics.get("incomplete_energy_gain", 0) <= 0:
                return "SIGNAL_OR_CALIBRATION_CHECK"
            return "INSUFFICIENT_DATA"
        if metrics.get("incomplete_energy_gain", 0) <= 0:
            return "SIGNAL_OR_CALIBRATION_CHECK"
        if metrics.get("long_wait"):
            return "TOO_HARD"
        return "INSUFFICIENT_DATA"

    if not checks["active_ok"]:
        return "INSUFFICIENT_DATA"

    if click_rate is not None and click_rate < CONFIG["behavior_click_rate"] and (
            median is None or median <= CONFIG["suitable_max_sec"]):
        return "BEHAVIOR_BOTTLENECK"

    if median is None:
        return "INSUFFICIENT_DATA"
    if median > CONFIG["suitable_max_sec"]:
        return "TOO_HARD"
    if (median < CONFIG["suitable_min_sec"]
            and click_rate is not None
            and click_rate >= CONFIG["up_click_rate"]
            and entered >= CONFIG["min_up_rounds"]):
        return "TOO_EASY"
    if CONFIG["suitable_min_sec"] <= median <= CONFIG["suitable_max_sec"]:
        return "SUITABLE"
    return "INSUFFICIENT_DATA"


def decide(metrics: dict, *, factor: Any = None, auto_enabled: bool = True,
           manual_lock: bool = False, streak_hard: int = 0,
           streak_easy: int = 0) -> dict:
    """根据已保存的指标计算下一局难度，不产生副作用。"""
    current = _clamp_factor(factor)
    decision = classify(metrics)
    hard = max(0, int(streak_hard or 0))
    easy = max(0, int(streak_easy or 0))
    next_factor = current
    direction = "hold"
    reason = "保持当前难度"
    changed = False

    if decision == "SUITABLE":
        hard = easy = 0
        reason = "当前蓄力难度适宜"
    elif decision == "BEHAVIOR_BOTTLENECK":
        hard = easy = 0
        reason = "主要瓶颈是点击操作，不调整蓄力难度"
    elif decision == "SIGNAL_OR_CALIBRATION_CHECK":
        reason = "信号质量或校准需要检查，不调整难度"
    elif decision == "INSUFFICIENT_DATA":
        reason = "有效数据不足，不调整难度"
    elif decision == "TOO_HARD":
        hard += 1
        easy = 0
        if hard >= CONFIG["down_streak"]:
            proposed = max(CONFIG["min_factor"], current * CONFIG["down_multiplier"])
            if round3(proposed) < current - 1e-9:
                next_factor = round3(proposed)
                direction = "down"
                changed = True
                reason = "连续偏高，降低下一局黄色区域距离"
            else:
                reason = "已达到最低难度，不再降低"
            hard = 0
        else:
            reason = f"连续偏高（{hard}/{CONFIG['down_streak']}），继续观察"
    elif decision == "TOO_EASY":
        easy += 1
        hard = 0
        if easy >= CONFIG["up_streak"]:
            proposed = min(CONFIG["max_factor"], current * CONFIG["up_multiplier"])
            if round3(proposed) > current + 1e-9:
                next_factor = round3(proposed)
                direction = "up"
                changed = True
                reason = "连续偏低，提高下一局黄色区域距离"
            else:
                reason = "已达到最高难度，不再提高"
            easy = 0
        else:
            reason = f"连续偏低（{easy}/{CONFIG['up_streak']}），继续观察"

    if not auto_enabled:
        reason = "自动适配已关闭；仅记录评估指标"
        next_factor = current
        direction = "hold"
        changed = False
    elif manual_lock:
        reason = "已手动锁定难度；仅记录评估指标"
        next_factor = current
        direction = "hold"
        changed = False

    return {
        "decision": decision,
        "current_factor": current,
        "next_factor": round3(next_factor),
        "direction": direction,
        "changed": changed,
        "reason": reason,
        "streak_hard": hard,
        "streak_easy": easy,
        "strategy_version": STRATEGY_VERSION,
        "params_version": PARAMS_VERSION,
    }


def default_snapshot() -> dict:
    return snapshot(CONFIG["default_factor"])


def history_record(*, user_id: str, session_id: Optional[str], calibration_id: Optional[str],
                   before: float, after: float, direction: str, decision: str,
                   reason: str, metrics: dict, source_name: str,
                   created_at: str) -> dict:
    return {
        "user_id": user_id,
        "session_id": session_id,
        "calibration_id": calibration_id,
        "before_factor": round3(before),
        "after_factor": round3(after),
        "direction": direction,
        "decision": decision,
        "reason": reason,
        "metrics": metrics,
        "source": source_name,
        "strategy_version": STRATEGY_VERSION,
        "params_version": PARAMS_VERSION,
        "created_at": created_at,
    }
