"""v1.8.4 开发者瓶颈诊断与蓄力过程统计。

这是工程诊断，不是医学评估：
  * 只解释现有状态机与已上报数据为什么没有产生适宜反馈；
  * 不输出 ADHD、临床注意力或治疗效果结论；
  * 不修改计分、蓄力速度、黄色区域宽度或难度策略。

时间口径（由前端单轮状态机上报，服务端只做边界/一致性检查）：
  charge_sec        正式计分用时：等待 + 宽容 + 衰减 + 无效点击冷却；
                    不含断流、主动暂停、子弹时间、跳跃/归位动画。
  eval_sec          难度评估净用时 = charge_active_sec + below_threshold_sec；
                    不含冷却、断流、暂停、子弹/跳跃。
  charge_active_sec 处于有效蓄力（滞回 + 高于蓄力零点）的时间。
  below_threshold_sec 未处于有效蓄力但非冷却的时间；宽容期和衰减都包含在这里。
  cooldown_sec      无效点击冷却持续时间。
  stale_sec         信号异常导致的冻结时间。
  bullet_sec        子弹时间。
  jump_anim_sec     跳跃、落地、视角归位动画。
  paused_sec        主动暂停/开局倒数等明确暂停时间。
"""
from __future__ import annotations

from statistics import median
from typing import Any, Optional

SMOOTH_TARGET_MIN_SEC = 4.0
SMOOTH_TARGET_MAX_SEC = 12.0
MIN_SIGNAL_RATIO = 0.85
MIN_ACTIVE_SEC = 45.0
MIN_PLANNED_SEC = 60.0
MIN_COMPLETE_ROUNDS = 2
MIN_DIFFICULTY = 0.60
COOLDOWN_WARN_RATIO = 0.15
DECAY_WARN_RATIO = 0.20
EARLY_TAP_WARN = 2
CLICK_RATE_WARN = 0.85

DIAGNOSTIC_LABELS = {
    "signal_dropout": "设备断流或信号质量不足",
    "calibration_invalid": "校准无效或设备条件不匹配",
    "eeg_below_charge": "脑电指标长时间低于蓄力条件",
    "slow_charge": "有效蓄力但蓄力速度过慢",
    "frequent_decay": "能量衰减频繁，净蓄力速度降低",
    "early_tap_cooldown": "提前点击及冷却时间过多",
    "zone_click_miss": "进入黄色区域但点击成功率低",
    "min_difficulty_still_hard": "已达到最低难度仍无法获得适宜反馈",
    "insufficient_data": "数据量不足，暂时无法判断",
}

TARGETS = {
    "smooth_charge_sec": [SMOOTH_TARGET_MIN_SEC, SMOOTH_TARGET_MAX_SEC],
    "min_signal_ratio": MIN_SIGNAL_RATIO,
    "min_active_sec": MIN_ACTIVE_SEC,
    "min_planned_sec": MIN_PLANNED_SEC,
    "min_complete_rounds": MIN_COMPLETE_ROUNDS,
    "min_difficulty": MIN_DIFFICULTY,
}


def _f(value: Any) -> Optional[float]:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if n == n and abs(n) != float("inf") else None


def _r(value: Optional[float], digits: int = 3) -> Optional[float]:
    return None if value is None else round(float(value), digits)


def _sum_fields(rows: list[dict], key: str) -> tuple[float, bool]:
    total = 0.0
    present = False
    for row in rows:
        if not isinstance(row, dict):
            continue
        v = _f(row.get(key))
        if v is not None and v >= 0:
            total += v
            present = True
    return total, present


def charge_process(report: Optional[dict]) -> dict:
    """汇总完整轮次和未完成轮次的蓄力过程；不伪造缺失字段。"""
    report = report or {}
    actions = report.get("actions") or {}
    rounds = [r for r in (actions.get("rounds") or []) if isinstance(r, dict)]
    incomplete = actions.get("incomplete_round") if isinstance(actions.get("incomplete_round"), dict) else None
    rows = rounds + ([incomplete] if incomplete else [])
    keys = (
        "charge_sec", "eval_sec", "charge_active_sec", "below_threshold_sec",
        "cooldown_sec", "stale_sec", "bullet_sec", "jump_anim_sec",
        "paused_sec", "decay_sec", "energy_gain", "energy_gain_total",
        "energy_loss", "energy_net",
    )
    sums: dict[str, Optional[float]] = {}
    present: dict[str, bool] = {}
    for key in keys:
        value, found = _sum_fields(rows, key)
        # v1.8.3 报告没有 charge_active_sec / energy_loss 等字段；保持 null，
        # 不用 charge_sec 减冷却去伪装成实测值。
        sums[key] = _r(value) if found else None
        present[key] = found
    events, events_present = _sum_fields(rows, "decay_events")
    # decay_events 是整数计数，单独保留整数语义
    events_i = int(events) if events_present else None
    energy_gain = sums.get("energy_gain")
    energy_gain_total = sums.get("energy_gain_total") or energy_gain
    energy_loss = sums.get("energy_loss")
    energy_net = sums.get("energy_net")
    if energy_net is None and energy_gain_total is not None and energy_loss is not None:
        energy_net = _r(energy_gain_total - energy_loss)
    round_elapsed = None
    if all(sums.get(k) is not None for k in ("charge_sec", "stale_sec", "bullet_sec", "jump_anim_sec", "paused_sec")):
        round_elapsed = _r(sum(float(sums[k] or 0) for k in
                               ("charge_sec", "stale_sec", "bullet_sec", "jump_anim_sec", "paused_sec")))
    eval_sec = sums.get("eval_sec")
    charge_sec = sums.get("charge_sec")
    cooldown_sec = sums.get("cooldown_sec")
    active_sec = sums.get("charge_active_sec")
    below_sec = sums.get("below_threshold_sec")
    decay_sec = sums.get("decay_sec")
    stale_sec = sums.get("stale_sec")
    return {
        "rounds_total": len(rounds),
        "complete_rounds": len(rounds),
        "incomplete_count": 1 if incomplete else 0,
        "available": bool(rows),
        "charge_sec": charge_sec,
        "eval_sec": eval_sec,
        "charge_active_sec": active_sec,
        "below_threshold_sec": below_sec,
        "cooldown_sec": cooldown_sec,
        "stale_sec": stale_sec,
        "bullet_sec": sums.get("bullet_sec"),
        "jump_anim_sec": sums.get("jump_anim_sec"),
        "paused_sec": sums.get("paused_sec"),
        "decay_sec": decay_sec,
        "decay_events": events_i,
        "energy_gain": energy_gain,
        "energy_gain_total": energy_gain_total,
        "energy_loss": energy_loss,
        "energy_net": energy_net,
        "round_elapsed_sec": round_elapsed,
        "active_ratio_of_eval": _r(active_sec / eval_sec, 4) if active_sec is not None and eval_sec and eval_sec > 0 else None,
        "below_ratio_of_eval": _r(below_sec / eval_sec, 4) if below_sec is not None and eval_sec and eval_sec > 0 else None,
        "cooldown_ratio_of_charge": _r(cooldown_sec / charge_sec, 4) if cooldown_sec is not None and charge_sec and charge_sec > 0 else None,
        "decay_ratio_of_eval": _r(decay_sec / eval_sec, 4) if decay_sec is not None and eval_sec and eval_sec > 0 else None,
        "missing_fields": [k for k, ok in present.items() if not ok],
        "definitions": {
            "charge_sec": "正式计分用时，含等待/宽容/衰减/冷却，不含断流/暂停/子弹/跳跃",
            "eval_sec": "难度评估净用时，不含冷却/断流/暂停/子弹/跳跃",
            "charge_active_sec": "处于有效蓄力（滞回且高于蓄力零点）的时间",
            "below_threshold_sec": "低于蓄力条件的非冷却时间，含宽容期和衰减",
            "cooldown_sec": "无效点击冷却时间",
            "stale_sec": "信号异常冻结时间",
            "bullet_sec": "子弹时间",
            "jump_anim_sec": "跳跃/落地/视角归位动画",
            "paused_sec": "明确主动暂停/开局倒数",
            "round_elapsed_sec": "上述互斥状态之和；旧报告缺字段时为 null，不用估算代替",
        },
        "client_reported": True,
        "note": "逐轮行为由客户端状态机上报；服务端只做边界与一致性检查，不声称完整抗篡改。",
    }


def _item(key: str, active: bool, evidence: dict, *, status: str = "measured",
          detail: str = "") -> dict:
    return {
        "id": key,
        "label": DIAGNOSTIC_LABELS[key],
        "active": bool(active),
        "status": status if active else ("not_applicable" if status == "not_applicable" else "clear"),
        "evidence": evidence,
        "summary": detail or DIAGNOSTIC_LABELS[key],
        "engineering_only": True,
    }


def validate_actions(actions: Optional[dict], planned_sec: Any = None,
                     played_sec: Any = None) -> dict:
    """客户端逐轮数据的边界/一致性检查；只影响分析与难度评估，不重算正式计分。"""
    actions = actions or {}
    planned = _f(planned_sec) or 0.0
    played = _f(played_sec) or 0.0
    errors = []
    warnings = []
    if played > 7200:
        errors.append("played_sec 超过 2 小时")
    if planned > 0 and played > planned + 300:
        errors.append("played_sec 明显超过 planned_sec + 5 分钟")
    if planned > 0 and played > planned * 2 + 300:
        errors.append("played_sec 与 planned_sec 不一致")
    rounds = [r for r in (actions.get("rounds") or []) if isinstance(r, dict)]
    accepted = []
    seen = set()
    for idx, rnd in enumerate(rounds):
        r = dict(rnd)
        rno = r.get("round", idx)
        try:
            rno_i = int(rno)
        except (TypeError, ValueError):
            warnings.append(f"第 {idx + 1} 轮 round_no 非整数，已排除")
            continue
        if rno_i in seen:
            warnings.append(f"重复轮次 {rno_i}，保留第一条")
            continue
        charge = _f(r.get("charge_sec"))
        ev = _f(r.get("eval_sec"))
        active = _f(r.get("charge_active_sec"))
        below = _f(r.get("below_threshold_sec"))
        cooldown = _f(r.get("cooldown_sec"))
        if any(v is not None and v < 0 for v in (charge, ev, active, below, cooldown)):
            warnings.append(f"第 {idx + 1} 轮存在负时间，已排除")
            continue
        if charge is not None and ev is not None and ev > charge + 0.75:
            warnings.append(f"第 {idx + 1} 轮 eval_sec 大于 charge_sec，已排除")
            continue
        if ev is not None and active is not None and below is not None and ev > active + below + 0.75:
            warnings.append(f"第 {idx + 1} 轮 eval_sec 与有效/低于阈值时间不一致，已排除")
            continue
        if charge is not None and max(planned, played, 60) and charge > max(planned, played, 60) + 120:
            warnings.append(f"第 {idx + 1} 轮 charge_sec 超出 Session 时间边界，已排除")
            continue
        seen.add(rno_i)
        if len(accepted) >= 2000:
            warnings.append("轮次超过 2000，截断")
            break
        accepted.append(r)
    inc = actions.get("incomplete_round")
    accepted_inc = inc if isinstance(inc, dict) else None
    if accepted_inc:
        ev = _f(accepted_inc.get("eval_sec"))
        charge = _f(accepted_inc.get("charge_sec"))
        if ev is not None and charge is not None and ev > charge + 0.75:
            warnings.append("未完成轮次 eval_sec 大于 charge_sec，已排除")
            accepted_inc = None
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "accepted_rounds": accepted,
        "accepted_incomplete": accepted_inc,
        "dropped_rounds": len(rounds) - len(accepted),
        "client_reported": True,
        "boundary_note": "只做边界与一致性检查，不等于逐帧抗篡改；正式 score 由现有计分链路计算，不在此重算。",
    }


def diagnose(report: Optional[dict], metrics: Optional[dict] = None) -> dict:
    """返回所有诊断状态（active=False 也保留），允许多个 active 同时成立。"""
    report = report or {}
    if not metrics:
        try:
            from . import difficulty
            metrics = difficulty.compute_metrics(report)
        except Exception:
            metrics = {}
    metrics = metrics or {}
    actions = report.get("actions") or {}
    rounds = [r for r in (actions.get("rounds") or []) if isinstance(r, dict)]
    inc = actions.get("incomplete_round") if isinstance(actions.get("incomplete_round"), dict) else None
    process = charge_process(report)
    source = report.get("source") or {}
    source_name = str(source.get("name") or "")
    purpose = str(report.get("purpose") or "game")
    planned = _f(report.get("planned_sec")) or 0.0
    active_sec = _f(metrics.get("active_sec")) or 0.0
    signal_ratio = _f(metrics.get("signal_ratio"))
    valid_frames = int(metrics.get("n_valid_frames") or 0)
    total_frames = int(metrics.get("n_frames") or 0)
    complete = len(rounds)
    entered = int(metrics.get("entered_count") or 0)
    median_charge = _f(metrics.get("median_net_charge_sec"))
    click_rate = _f(metrics.get("click_rate"))
    early = int(metrics.get("early_taps") or 0)
    cooldown_ratio = _f(process.get("cooldown_ratio_of_charge")) or _f(metrics.get("cooldown_ratio")) or 0.0
    decay_ratio = _f(process.get("decay_ratio_of_eval")) or 0.0
    decay_events = int(process.get("decay_events") or 0)
    factor = _f((report.get("difficulty_snapshot") or {}).get("factor"))
    cal = report.get("calibration_snapshot") or report.get("calibration") or {}
    cal_status = str(cal.get("status") or report.get("calibration_status") or "")
    device = report.get("device_key")
    cal_device = cal.get("device_key")
    quality = report.get("signal_quality") or {}
    usable = _f(quality.get("usable_ratio"))
    incomplete_sec = _f((inc or {}).get("charge_sec")) or 0.0
    incomplete_eval = _f((inc or {}).get("eval_sec")) or 0.0
    incomplete_gain = _f((inc or {}).get("energy_gain")) or 0.0
    long_wait = bool(metrics.get("long_wait"))
    score_mean = _f(report.get("score_mean"))
    above_mid = _f(report.get("above_mid_ratio"))
    if score_mean is None:
        vals = [_f(r.get("mean_score")) for r in rounds if _f(r.get("mean_score")) is not None]
        if vals:
            score_mean = sum(vals) / len(vals)

    low_signal = signal_ratio is not None and signal_ratio < MIN_SIGNAL_RATIO
    low_quality = usable is not None and usable < 0.50
    stale = (_f(process.get("stale_sec")) or 0.0) >= 3.0
    invalid_ratio = (1.0 - signal_ratio) if signal_ratio is not None else None
    signal_active = bool(low_signal or low_quality or stale
                         or (total_frames >= 20 and valid_frames == 0))

    calibration_missing = not cal or not cal.get("id")
    calibration_invalid = cal_status in {"invalid", "failed", "legacy", "unknown"} and bool(cal)
    device_mismatch = bool(device and cal_device and str(device) != str(cal_device))
    real_calibration_scope = source_name == "hardware" and purpose in {"game", "assessment"}
    calibration_active = bool(real_calibration_scope and (calibration_missing or calibration_invalid or device_mismatch))

    eeg_low = bool((score_mean is not None and score_mean < 45.0)
                   or (above_mid is not None and above_mid < 0.20))
    slow = bool(median_charge is not None and median_charge > SMOOTH_TARGET_MAX_SEC)
    slow_incomplete = bool(median_charge is None and long_wait and incomplete_gain > 0
                           and incomplete_eval > SMOOTH_TARGET_MAX_SEC)
    decay = bool(decay_ratio >= DECAY_WARN_RATIO or decay_events >= 2)
    early_active = bool(early >= EARLY_TAP_WARN or cooldown_ratio >= COOLDOWN_WARN_RATIO)
    click_miss = bool(entered > 0 and click_rate is not None and click_rate < CLICK_RATE_WARN)
    min_still_hard = bool(factor is not None and factor <= MIN_DIFFICULTY + 1e-9
                          and (slow or slow_incomplete or long_wait))
    insufficient = bool(complete < MIN_COMPLETE_ROUNDS or active_sec < MIN_ACTIVE_SEC
                        or planned < MIN_PLANNED_SEC or valid_frames < 20
                        or (inc and not rounds and incomplete_eval < MIN_ACTIVE_SEC))
    if source_name not in {"hardware", "replay", "manual", "heart"}:
        insufficient = True

    items = [
        _item("signal_dropout", signal_active, {
            "signal_ratio": signal_ratio, "valid_frames": valid_frames,
            "total_frames": total_frames, "stale_sec": process.get("stale_sec"),
            "usable_ratio": usable, "threshold_signal_ratio": MIN_SIGNAL_RATIO,
            "threshold_usable_ratio": 0.50,
        }, status="measured" if total_frames else "not_applicable",
            detail="信号有效率低于工程阈值，先检查设备、电极和采集链路；不能把断流当作走神。"),
        _item("calibration_invalid", calibration_active, {
            "calibration_id": cal.get("id"), "status": cal_status,
            "device_key": device, "calibration_device_key": cal_device,
            "missing": calibration_missing, "device_mismatch": device_mismatch,
            "scope": "hardware game/assessment" if real_calibration_scope else "not_applicable",
        }, status="measured" if real_calibration_scope else "not_applicable",
            detail="当日校准缺失/失效或设备指纹不匹配；请重新完成有效的当日校准。"),
        _item("eeg_below_charge", eeg_low, {
            "score_mean": score_mean, "above_mid_ratio": above_mid,
            "active_sec": active_sec, "threshold_score": 45.0,
            "threshold_above_mid_ratio": 0.20,
        }, status="measured" if score_mean is not None or above_mid is not None else "not_applicable",
            detail="现有实际算法输出长期低于蓄力条件；先核对校准与信号，不要用诊断替代计分。"),
        _item("slow_charge", slow or slow_incomplete, {
            "median_net_charge_sec": median_charge,
            "incomplete_eval_sec": incomplete_eval,
            "target_max_sec": SMOOTH_TARGET_MAX_SEC,
            "entered_count": entered,
            "incomplete_energy_gain": incomplete_gain,
        }, status="measured" if median_charge is not None or incomplete_eval else "insufficient",
            detail="有效蓄力存在，但净蓄力用时超过当前工程设计目标 4–12 秒。"),
        _item("frequent_decay", decay, {
            "decay_events": decay_events, "decay_sec": process.get("decay_sec"),
            "eval_sec": process.get("eval_sec"), "decay_ratio": decay_ratio,
            "energy_loss": process.get("energy_loss"),
            "threshold_ratio": DECAY_WARN_RATIO,
        }, status="measured" if process.get("eval_sec") is not None else "insufficient",
            detail="低于蓄力条件后进入衰减的比例偏高，净蓄力速度被反复抵消。"),
        _item("early_tap_cooldown", early_active, {
            "early_taps": early, "cooldown_count": metrics.get("cooldown_count"),
            "cooldown_sec": process.get("cooldown_sec"),
            "cooldown_ratio": cooldown_ratio,
            "threshold_early_taps": EARLY_TAP_WARN,
            "threshold_ratio": COOLDOWN_WARN_RATIO,
        }, status="measured" if process.get("charge_sec") is not None else "insufficient",
            detail="提前点击或冷却占比偏高，属于操作瓶颈；不要用降低蓄力难度掩盖。"),
        _item("zone_click_miss", click_miss, {
            "entered_count": entered, "success_count": metrics.get("success_count"),
            "missed_clicks": metrics.get("missed_clicks"), "click_rate": click_rate,
            "threshold_click_rate": CLICK_RATE_WARN,
        }, status="measured" if entered else "not_applicable",
            detail="已经进入黄色区域，但点击成功率偏低。"),
        _item("min_difficulty_still_hard", min_still_hard, {
            "factor": factor, "min_factor": MIN_DIFFICULTY,
            "median_net_charge_sec": median_charge,
            "long_wait": long_wait, "target_max_sec": SMOOTH_TARGET_MAX_SEC,
        }, status="measured" if factor is not None else "insufficient",
            detail="已达到最低难度 0.60，但净蓄力仍超过目标；本阶段只记录，不自动改蓄力公式。"),
        _item("insufficient_data", insufficient, {
            "complete_rounds": complete, "active_sec": active_sec,
            "planned_sec": planned, "valid_frames": valid_frames,
            "minimum_rounds": MIN_COMPLETE_ROUNDS,
            "minimum_active_sec": MIN_ACTIVE_SEC,
            "minimum_planned_sec": MIN_PLANNED_SEC,
        }, status="insufficient" if insufficient else "measured",
            detail="有效轮次或有效采集不足，暂不下结论；先完成更长的有效游戏。"),
    ]
    active = [x for x in items if x["active"]]
    if not active:
        summary = "未发现达到工程阈值的明确瓶颈；继续观察数据量与信号质量。"
    else:
        summary = "；".join(x["label"] for x in active)
    return {
        "items": items,
        "active": active,
        "summary": summary,
        "engineering_only": True,
        "not_medical_advice": True,
        "targets": TARGETS,
        "client_reported_fields": ["actions.rounds", "actions.incomplete_round"],
        "limitations": [
            "诊断基于前端单轮状态机与后端统计，不等于临床注意力评估。",
            "服务端目前不做逐帧行为重算，不能声称完整抗篡改。",
            "不自动修改蓄力阈值、速度公式或最低难度限制。",
        ],
    }


def summarize_rounds(report: Optional[dict], limit: int = 40) -> list[dict]:
    """给工作台/导出用的逐轮数据；只保留可解释的有限字段。"""
    report = report or {}
    actions = report.get("actions") or {}
    out = []
    for r in (actions.get("rounds") or [])[:limit]:
        if not isinstance(r, dict):
            continue
        item = {k: r.get(k) for k in (
            "charge_sec", "eval_sec", "charge_active_sec",
            "below_threshold_sec", "cooldown_sec", "stale_sec", "bullet_sec",
            "jump_anim_sec", "paused_sec", "energy_gain", "energy_loss",
            "decay_sec", "decay_events", "zone_lo", "zone_hi", "zone_width",
            "potential", "awarded", "success", "click_rate", "reaction_sec",
            "multiplier", "early_taps", "cooldown_count",
        ) if k in r}
        item["round_no"] = r.get("round")
        out.append(item)
    return out


def median_or_none(values: list[Any]) -> Optional[float]:
    vals = [_f(v) for v in values]
    vals = [v for v in vals if v is not None]
    return _r(median(vals), 2) if vals else None
