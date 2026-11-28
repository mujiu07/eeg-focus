"""v1.9.0 成长中心的数据聚合与口径层。

原则：
* 只读取本地 SQLite / 已保存报告，不伪造历史；
* 缺失值保留 None，不用 0 代替；
* 模拟、EDF 回放和真实硬件记录分开统计；
* 标准评估只有条件完全一致且质量合格时才进入同一趋势段；
* 不输出医学诊断或“注意力提升百分比”。
"""
from __future__ import annotations

import math
import statistics
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import diagnostics
from .storage import StorageError, storage

FORMAL_SOURCE_NAMES = {"hardware", "heart"}
MIN_VALID_SIGNAL_RATIO = diagnostics.MIN_SIGNAL_RATIO
GROWTH_VERSION = "1.9.0"

KIND_LABELS = {
    "formal_game": "正式游戏",
    "assessment": "标准评估",
    "assessment_simulation": "模拟标准评估",
    "simulation": "模拟试玩",
    "replay": "EDF 回放",
    "calibration": "校准教学",
    "other": "其他记录",
}
SOURCE_LABELS = {
    "hardware": "真实 EEG 硬件",
    "heart": "心率模式（无 EEG）",
    "manual": "手动模拟",
    "replay": "EDF 回放",
    "demo": "演示模式",
}

METRIC_DEFINITIONS: Dict[str, Dict[str, str]] = {
    "formal_game_count": {"label": "正式游戏次数", "denominator": "所选日期内的正式游戏 Session", "unit": "次"},
    "play_seconds": {"label": "实际游戏时长", "denominator": "正式游戏 played_sec 之和", "unit": "秒"},
    "effective_signal_seconds": {"label": "有效信号采集时长", "denominator": "正式游戏时长 × 该局有效帧比例；无 EEG 的局不计入", "unit": "秒"},
    "usage_days": {"label": "累计使用天数", "denominator": "正式游戏、真实标准评估、有效校准所在的本地日期去重", "unit": "天"},
    "successful_jumps": {"label": "成功跳跃次数", "denominator": "正式游戏逐轮 success 次数之和", "unit": "次"},
    "zone_entries": {"label": "黄色区域进入次数", "denominator": "完成轮次 + 已进入但未完成的轮次", "unit": "次"},
    "click_success_rate": {"label": "点击成功率", "denominator": "成功跳跃 ÷（成功跳跃 + 未成功完成跳跃）", "unit": "比例"},
    "reaction_median": {"label": "点击反应时间中位数", "denominator": "仅成功跳跃且 reaction_sec > 0 的轮次", "unit": "秒"},
    "early_taps": {"label": "提前点击次数", "denominator": "正式游戏 actions.early_taps 之和", "unit": "次"},
    "net_charge_median": {"label": "净蓄力用时中位数", "denominator": "仅完整轮次的 eval_sec；未完成轮次单列", "unit": "秒"},
    "valid_signal_ratio": {"label": "有效信号比例", "denominator": "有效帧数 ÷ 总帧数（正式硬件游戏汇总）", "unit": "比例"},
    "score": {"label": "历史游戏积分", "denominator": "正式游戏 total_score 之和；不是商城余额", "unit": "分"},
    "assessment_reference": {"label": "S_reference", "denominator": "标准评估报告 reference_score_mean；长期参考映射后的任务指标", "unit": "分"},
    "assessment_pre_map": {"label": "映射前算法输出", "denominator": "标准评估报告 focus_mean（0–1 原始任务输出）", "unit": "0–1"},
}

LIMITATIONS = [
    "本报告是本地游戏与任务记录的确定性统计，不是临床注意力评估，不能用于诊断或治疗结论。",
    "长时趋势只使用满足设备、算法、映射、参考基线、评估协议和任务参数条件一致的标准评估；条件变化会分段。",
    "有效信号比例不足 85% 的记录会保留在历史列表中，但不参与趋势计算。",
    "模拟试玩、EDF 回放和无设备试玩不会进入真实 EEG 成长趋势。",
    "当前 SQLite 数据库和导出文件尚未静态加密；所有个人数据仅保存在本机数据目录。",
    "报告不包含原始高频 EEG 波形；如未来需要科研级原始数据，应另建受控导出流程。",
    "点击反应时间、反应成功等行为指标来自前端状态机上报，服务端只做边界与一致性检查，不等同于防篡改认证。",
]


def _f(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) else None


def _i(value: Any) -> Optional[int]:
    n = _f(value)
    return int(round(n)) if n is not None else None


def _round(value: Optional[float], digits: int = 3) -> Optional[float]:
    return None if value is None else round(float(value), digits)


def _median(values: Iterable[Optional[float]]) -> Optional[float]:
    clean = [float(v) for v in values if _f(v) is not None]
    return round(statistics.median(clean), 3) if clean else None


def _sum_known(values: Iterable[Optional[float]]) -> Tuple[Optional[float], int]:
    clean = [float(v) for v in values if _f(v) is not None]
    return (round(sum(clean), 3), 0) if clean else (None, 0)


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _tz(tz_offset_min: Optional[int]) -> Optional[timezone]:
    if tz_offset_min is None:
        return None
    try:
        # JS getTimezoneOffset(): 中国为 -480，对应 UTC+8。
        return timezone(timedelta(minutes=-int(tz_offset_min)))
    except (TypeError, ValueError, OverflowError):
        return None


def _parse_dt(value: Any, tz_offset_min: Optional[int] = None) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        try:
            dt = datetime.fromtimestamp(float(value) / (1000.0 if float(value) > 10_000_000_000 else 1.0), tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None
    elif isinstance(value, datetime):
        dt = value
    else:
        raw = str(value).strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return None
    if dt.tzinfo is None:
        # 旧数据/测试数据可能没有时区；按本机本地时间解释。
        dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
    target = _tz(tz_offset_min)
    return dt.astimezone(target) if target else dt.astimezone()


def _date_key(value: Any, tz_offset_min: Optional[int] = None) -> Optional[str]:
    dt = _parse_dt(value, tz_offset_min)
    return dt.date().isoformat() if dt else None


def _time_label(value: Any, tz_offset_min: Optional[int] = None) -> Optional[str]:
    dt = _parse_dt(value, tz_offset_min)
    return dt.strftime("%Y-%m-%d %H:%M") if dt else None


def _date_label(value: Any, tz_offset_min: Optional[int] = None) -> Optional[str]:
    dt = _parse_dt(value, tz_offset_min)
    return dt.strftime("%Y-%m-%d") if dt else None


def _range_label(preset: str, start: Optional[str], end: Optional[str]) -> str:
    if preset == "7d":
        return "近 7 天"
    if preset == "14d":
        return "近 14 天"
    if preset == "30d":
        return "近 30 天"
    if preset == "all":
        return "全部记录"
    return f"{start or '不限'} 至 {end or '不限'}"


def resolve_range(preset: Optional[str] = None, start: Optional[str] = None,
                  end: Optional[str] = None, tz_offset_min: Optional[int] = None) -> Dict[str, Any]:
    preset = (preset or "7d").strip().lower()
    if preset not in ("7d", "14d", "30d", "all", "custom"):
        raise ValueError("日期范围必须是 7d、14d、30d、all 或 custom")
    tz = _tz(tz_offset_min)
    today = datetime.now(tz).date() if tz else datetime.now().astimezone().date()
    start_date: Optional[date] = None
    end_date: Optional[date] = today
    if preset in ("7d", "14d", "30d"):
        days = {"7d": 7, "14d": 14, "30d": 30}[preset]
        start_date = today - timedelta(days=days - 1)
    elif preset == "all":
        start_date = None
    else:
        if not start or not end:
            raise ValueError("自定义范围必须提供 start 和 end（YYYY-MM-DD）")
        try:
            start_date = date.fromisoformat(str(start)[:10])
            end_date = date.fromisoformat(str(end)[:10])
        except ValueError as exc:
            raise ValueError("日期格式应为 YYYY-MM-DD") from exc
        if start_date > end_date:
            raise ValueError("开始日期不能晚于结束日期")
        if (end_date - start_date).days > 3660:
            raise ValueError("单次导出的日期范围不能超过 10 年")
    return {
        "preset": preset,
        "start": start_date.isoformat() if start_date else None,
        "end": end_date.isoformat() if end_date else None,
        "label": _range_label(preset, start_date.isoformat() if start_date else None,
                              end_date.isoformat() if end_date else None),
        "tz_offset_min": tz_offset_min,
    }


def _in_range(value: Any, date_range: Dict[str, Any]) -> bool:
    key = _date_key(value, date_range.get("tz_offset_min"))
    if key is None:
        return False
    start = date_range.get("start")
    end = date_range.get("end")
    return (start is None or key >= start) and (end is None or key <= end)


def _source_name(item: Dict[str, Any]) -> str:
    source = _safe_dict(item.get("source"))
    if not source:
        source = _safe_dict(item.get("report", {}).get("source"))
    return str(source.get("name") or "unknown")


def _classify(item: Dict[str, Any], assessment_map: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    purpose = str(item.get("purpose") or item.get("report", {}).get("purpose") or "game")
    demo = bool(item.get("demo") or item.get("report", {}).get("demo"))
    source = _source_name(item)
    assessment = assessment_map.get(str(item.get("session_id") or "")) or {}
    simulation = bool(assessment.get("simulation")) if assessment else False
    if purpose == "assessment":
        sim = simulation or demo or source in ("manual", "replay")
        kind = "assessment_simulation" if sim else "assessment"
    elif purpose == "calibration":
        kind = "calibration"
    elif demo:
        kind = "simulation"
    elif source == "replay":
        kind = "replay"
    elif source == "manual":
        kind = "simulation"
    elif source in FORMAL_SOURCE_NAMES:
        kind = "formal_game"
    else:
        kind = "other"
    return {
        "kind": kind,
        "kind_label": KIND_LABELS.get(kind, "其他记录"),
        "source_name": source,
        "source_label": SOURCE_LABELS.get(source, source or "未知来源"),
        "is_formal": kind == "formal_game",
        "is_real_use": kind in ("formal_game", "assessment"),
        "is_simulation": kind in ("assessment_simulation", "simulation", "replay"),
        "eeg_available": kind in ("formal_game", "assessment") and source == "hardware",
        "demo": demo,
        "purpose": purpose,
    }


def _reaction_values(rounds: List[dict]) -> List[float]:
    values = []
    for row in rounds:
        if not isinstance(row, dict) or not row.get("success"):
            continue
        value = _f(row.get("reaction_sec"))
        if value is not None and value > 0:
            values.append(value)
    return values


def _eval_values(rounds: List[dict]) -> List[float]:
    values = []
    for row in rounds:
        if not isinstance(row, dict):
            continue
        value = _f(row.get("eval_sec"))
        if value is not None and value > 0:
            values.append(value)
    return values


def _report_metrics(report: Dict[str, Any]) -> Dict[str, Any]:
    report = _safe_dict(report)
    actions = _safe_dict(report.get("actions"))
    rounds = [r for r in _safe_list(actions.get("rounds")) if isinstance(r, dict)]
    incomplete = _safe_dict(actions.get("incomplete_round"))
    success = _i(actions.get("successful_jumps"))
    missed = _i(actions.get("missed_jumps"))
    if success is None and rounds:
        success = sum(1 for r in rounds if r.get("success"))
    if missed is None and rounds and success is not None:
        missed = max(0, len(rounds) - success)
    zone_entries = None
    if rounds:
        zone_entries = len(rounds) + (1 if incomplete.get("entered") else 0)
    elif success is not None and missed is not None:
        zone_entries = success + missed
    click_denominator = None
    if success is not None and missed is not None:
        click_denominator = success + missed
    click_rate = (round(success / click_denominator, 3)
                  if success is not None and click_denominator else None)
    reactions = _reaction_values(rounds)
    evals = _eval_values(rounds)
    early = _i(actions.get("early_taps"))
    if early is None and rounds:
        early = sum(_i(r.get("early_taps")) or 0 for r in rounds)
    n_frames = _i(report.get("n_frames")) or _i(report.get("total_frames"))
    n_valid = _i(report.get("n_valid_frames")) or _i(report.get("valid_frames"))
    valid_ratio = _f(report.get("valid_signal_ratio"))
    if valid_ratio is None and n_frames and n_valid is not None:
        valid_ratio = n_valid / n_frames
    low_quality = valid_ratio is not None and valid_ratio < MIN_VALID_SIGNAL_RATIO
    quality_status = str(_safe_dict(report.get("data_quality")).get("status") or "")
    if quality_status in ("invalid", "low", "poor"):
        low_quality = True
    # 0 是合法值：只有字段缺失时才回退，不能把 0 秒/0 分误判为缺失。
    played_sec = _f(report.get("played_sec"))
    if played_sec is None:
        played_sec = _f(report.get("duration_sec"))
    score = _i(report.get("score"))
    if score is None:
        score = _i(report.get("total_score"))
    return {
        "played_sec": played_sec,
        "score": score,
        "successful_jumps": success,
        "missed_jumps": missed,
        "zone_entries": zone_entries,
        "click_denominator": click_denominator,
        "click_success_rate": click_rate,
        "reaction_median": _median(reactions),
        "reaction_count": len(reactions),
        "early_taps": early,
        "net_charge_median": _median(evals),
        "net_charge_count": len(evals),
        "incomplete_round": incomplete or None,
        "incomplete_rounds": 1 if incomplete else 0,
        "rounds_count": len(rounds),
        "n_frames": n_frames,
        "n_valid_frames": n_valid,
        "valid_signal_ratio": _round(valid_ratio, 3),
        "low_quality": bool(low_quality),
        "_reaction_values": reactions,
        "_eval_values": evals,
    }


def _assessment_row_summary(rec: Dict[str, Any], tz_offset_min: Optional[int] = None) -> Dict[str, Any]:
    report = _safe_dict(rec.get("report"))
    features = _safe_dict(rec.get("features")) or _safe_dict(report.get("features"))
    behavior = _safe_dict(rec.get("behavior")) or _safe_dict(report.get("behavior"))
    metrics = _report_metrics(report)
    ref = _safe_dict(report.get("reference_snapshot"))
    cal = _safe_dict(report.get("calibration_snapshot"))
    device = _safe_dict(rec.get("device"))
    params = _safe_dict(rec.get("params"))
    simulated = bool(rec.get("simulation"))
    status = str(rec.get("status") or "")
    ref_score = _f(features.get("reference_score_mean"))
    if ref_score is None:
        ref_score = _f(features.get("score_mean"))
    pre_map = _f(features.get("focus_mean"))
    if pre_map is None:
        pre_map = _f(features.get("focus_fused_mean"))
    valid_ratio = _f(metrics.get("valid_signal_ratio"))
    if valid_ratio is None:
        valid_ratio = _f(rec.get("valid_signal_ratio"))
    low_quality = bool(metrics.get("low_quality")) or (valid_ratio is not None and valid_ratio < MIN_VALID_SIGNAL_RATIO)
    conditions = _conditions(rec, report, ref, cal, device, params)
    reasons = []
    if status != "completed":
        reasons.append("评估未完成")
    if simulated:
        reasons.append("模拟/回放评估不进入真实趋势")
    if low_quality:
        reasons.append("有效信号比例低于 85%")
    if conditions["missing"]:
        reasons.append("缺少可比条件：" + "、".join(conditions["missing"]))
    if not conditions["key"]:
        reasons.append("缺少完整的设备/算法/映射/参考条件")
    comparable = bool(not reasons and conditions["key"])
    date_value = rec.get("ended_at") or rec.get("started_at") or rec.get("created_at")
    return {
        "assessment_id": rec.get("assessment_id"),
        "session_id": rec.get("session_id"),
        "date": _date_label(date_value, tz_offset_min),
        "date_key": _date_key(date_value, tz_offset_min),
        "started_at": rec.get("started_at"),
        "ended_at": rec.get("ended_at"),
        "status": status,
        "status_label": "已完成" if status == "completed" else ("进行中" if status == "started" else status),
        "simulation": simulated,
        "source_label": "模拟评估" if simulated else "真实硬件标准评估",
        "protocol_version": rec.get("protocol_version"),
        "planned_sec": _f(rec.get("planned_sec")),
        "fixed_factor": _f(rec.get("fixed_factor")),
        "seed": rec.get("seed"),
        "device_key": device.get("device_key"),
        "reference_baseline_id": rec.get("reference_baseline_id") or ref.get("id"),
        "reference_version": ref.get("version"),
        "algorithm_version": conditions["values"].get("algorithm_version"),
        "mapping_version": conditions["values"].get("mapping_version"),
        "reference_score": _round(ref_score, 3),
        "pre_map_score": _round(pre_map, 3),
        "mapped_score": _round(_f(features.get("score_mean")), 3),
        "click_success_rate": metrics.get("click_success_rate"),
        "reaction_median": metrics.get("reaction_median"),
        "net_charge_median": metrics.get("net_charge_median"),
        "valid_signal_ratio": _round(valid_ratio, 3),
        "low_quality": low_quality,
        "comparable": comparable,
        "comparison_reasons": reasons,
        "conditions": conditions["values"],
        "condition_key": conditions["key"],
        "condition_label": conditions["label"],
        "report_available": bool(report),
        "behavior": {
            "successful_jumps": behavior.get("successful_jumps", metrics.get("successful_jumps")),
            "zone_entries": behavior.get("zone_entries", metrics.get("zone_entries")),
            "click_success_rate": behavior.get("click_success_rate", metrics.get("click_success_rate")),
        },
    }


def _conditions(rec: Dict[str, Any], report: Dict[str, Any], ref: Dict[str, Any],
                cal: Dict[str, Any], device: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    algorithms = (report.get("algorithm_version"), ref.get("algorithm_version"),
                  cal.get("algorithm_version"))
    mappings = (report.get("mapping_version"), ref.get("mapping_version"),
                cal.get("mapping_version"))
    algorithm = next((str(v) for v in algorithms if v), None)
    mapping = next((str(v) for v in mappings if v), None)
    device_key = device.get("device_key") or ref.get("device_key") or cal.get("device_key")
    reference_id = rec.get("reference_baseline_id") or report.get("reference_baseline_id") or ref.get("id")
    reference_version = ref.get("version")
    protocol = rec.get("protocol_version")
    planned = _f(rec.get("planned_sec"))
    fixed = _f(rec.get("fixed_factor"))
    difficulty = _safe_dict(params.get("difficulty")) or _safe_dict(report.get("difficulty_snapshot"))
    game_params = _safe_dict(params.get("game"))
    difficulty_params = difficulty.get("params_version")
    difficulty_strategy = difficulty.get("strategy_version")
    game_params_version = (game_params.get("params_version")
                           or difficulty.get("game_params_version")
                           or difficulty_params
                           or "legacy")
    start_energy = _f(game_params.get("start_energy"))
    if start_energy is None:
        start_energy = _f(difficulty.get("start_energy"))
    if start_energy is None:
        # v1.8.3/v1.8.4 旧评估可能没有显式 start_energy；按当时真实值 15% 处理。
        # 新服务端始终盖章 10%，因此旧记录与新记录仍会分段。
        start_energy = 15.0
    values = {
        "device_key": device_key,
        "algorithm_version": algorithm,
        "mapping_version": mapping,
        "reference_baseline_id": reference_id,
        "reference_version": reference_version,
        "protocol_version": protocol,
        "planned_sec": planned,
        "fixed_factor": fixed,
        "difficulty_params_version": difficulty_params,
        "difficulty_strategy_version": difficulty_strategy,
        "game_params_version": game_params_version,
        "start_energy": start_energy,
    }
    required = ("device_key", "algorithm_version", "mapping_version",
                "reference_baseline_id", "reference_version", "protocol_version",
                "planned_sec", "fixed_factor", "game_params_version", "start_energy")
    missing = [k for k in required if values.get(k) in (None, "")]
    key = None
    if not missing:
        key = "|".join(str(values[k]) for k in required)
    label_parts = []
    if device_key:
        label_parts.append(f"设备 {str(device_key)[:30]}")
    if algorithm:
        label_parts.append(f"算法 {algorithm}")
    if mapping:
        label_parts.append(f"映射 {mapping}")
    if reference_version:
        label_parts.append(f"参考 {reference_version}")
    if protocol:
        label_parts.append(f"协议 {protocol}")
    if start_energy is not None:
        label_parts.append(f"起始蓄力 {start_energy:g}%")
    return {"values": values, "missing": missing, "key": key,
            "label": " · ".join(label_parts) or "条件不完整"}


def _make_session_calc(item: Dict[str, Any], assessment_map: Dict[str, Dict[str, Any]],
                       tz_offset_min: Optional[int] = None) -> Dict[str, Any]:
    report = _safe_dict(item.get("report"))
    kind = _classify(item, assessment_map)
    metrics = _report_metrics(report)
    date_value = item.get("started_at") or report.get("created_at") or item.get("created_at")
    return {
        "session_id": item.get("session_id"),
        "assessment_id": item.get("assessment_id"),
        "date": _date_label(date_value, tz_offset_min),
        "date_key": _date_key(date_value, tz_offset_min),
        "started_at": item.get("started_at"),
        "ended_at": item.get("ended_at"),
        "duration_sec": _f(item.get("duration_sec")),
        "played_sec": metrics.get("played_sec"),
        "score": metrics.get("score"),
        "wallet_points": _i(item.get("wallet_points")),
        "finished": bool(item.get("finished")),
        "kind": kind["kind"],
        "kind_label": kind["kind_label"],
        "source_label": kind["source_label"],
        "source_name": kind["source_name"],
        "demo": kind["demo"],
        "is_formal": kind["is_formal"],
        "eeg_available": kind["eeg_available"],
        "is_simulation": kind["is_simulation"],
        "metrics": metrics,
        "low_quality": bool(metrics.get("low_quality")),
        "diagnostics": _safe_dict(report.get("diagnostics")),
        "difficulty": _safe_dict(report.get("difficulty_snapshot")),
        "calibration": _safe_dict(report.get("calibration_snapshot")),
        "reference": _safe_dict(report.get("reference_snapshot")),
    }


def _load_sessions(uid: str, tz_offset_min: Optional[int] = None) -> Tuple[List[Dict[str, Any]],
                                                                          List[Dict[str, Any]]]:
    assessments = storage.assessments(uid, 200)
    assessment_map = {str(a.get("session_id")): a for a in assessments if a.get("session_id")}
    sessions = []
    for item in storage.list_sessions(uid, 2000):
        sessions.append(_make_session_calc(item, assessment_map, tz_offset_min))
    return sessions, assessments


def _aggregate_sessions(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    successes = [r["metrics"].get("successful_jumps") for r in rows]
    missed = [r["metrics"].get("missed_jumps") for r in rows]
    zone_entries = [r["metrics"].get("zone_entries") for r in rows]
    reactions: List[float] = []
    evals: List[float] = []
    for row in rows:
        reactions.extend(row["metrics"].get("_reaction_values") or [])
        evals.extend(row["metrics"].get("_eval_values") or [])
    success_total, _ = _sum_known(successes)
    missed_total, _ = _sum_known(missed)
    sample_denominator = ((success_total or 0) + (missed_total or 0)
                          if success_total is not None and missed_total is not None else None)
    click_rate = (round((success_total or 0) / sample_denominator, 3)
                  if sample_denominator else None)
    frame_pairs = [(r["metrics"].get("n_valid_frames"), r["metrics"].get("n_frames"))
                   for r in rows
                   if r["metrics"].get("n_valid_frames") is not None
                   and r["metrics"].get("n_frames")]
    n_frames = sum(int(pair[1]) for pair in frame_pairs)
    n_valid = sum(int(pair[0]) for pair in frame_pairs)
    valid_ratio = (n_valid / n_frames) if n_frames else None
    durations = [r["metrics"].get("played_sec") for r in rows]
    duration_total, _ = _sum_known(durations)
    signal_secs = []
    for row in rows:
        if not row.get("eeg_available"):
            continue
        ratio = row["metrics"].get("valid_signal_ratio")
        dur = row["metrics"].get("played_sec")
        if ratio is not None and dur is not None:
            signal_secs.append(dur * ratio)
    signal_total, _ = _sum_known(signal_secs)
    return {
        "sessions": len(rows),
        "play_seconds": duration_total,
        "effective_signal_seconds": _round(signal_total, 1),
        "successful_jumps": int(success_total) if success_total is not None else None,
        "missed_jumps": int(missed_total) if missed_total is not None else None,
        "zone_entries": int(sum(v for v in zone_entries if v is not None)) if any(v is not None for v in zone_entries) else None,
        "click_denominator": int(sample_denominator) if sample_denominator is not None else None,
        "click_success_rate": click_rate,
        "reaction_median": _round(_median(reactions), 3),
        "reaction_count": len(reactions),
        "early_taps": int(sum(r["metrics"]["early_taps"] for r in rows
                              if r["metrics"].get("early_taps") is not None)) if any(
            r["metrics"].get("early_taps") is not None for r in rows) else None,
        "net_charge_median": _round(_median(evals), 3),
        "net_charge_count": len(evals),
        "incomplete_rounds": sum(int(r["metrics"].get("incomplete_rounds") or 0) for r in rows),
        "valid_signal_ratio": _round(valid_ratio, 3),
        "low_quality_sessions": sum(1 for r in rows if r.get("low_quality")),
        "score": int(sum(r["score"] for r in rows if r.get("score") is not None)) if any(
            r.get("score") is not None for r in rows) else None,
    }


def _daily_rows(rows: List[Dict[str, Any]], date_range: Dict[str, Any]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        key = row.get("date_key")
        if key and _in_range(row.get("started_at"), date_range):
            grouped.setdefault(key, []).append(row)
    if date_range.get("start") and date_range.get("end"):
        start = date.fromisoformat(date_range["start"])
        end = date.fromisoformat(date_range["end"])
        keys = [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]
        if len(keys) > 370:
            keys = sorted(grouped)
    else:
        keys = sorted(grouped)
    out = []
    for key in keys:
        group = grouped.get(key, [])
        agg = _aggregate_sessions(group)
        out.append({
            "date": key,
            "sessions": agg["sessions"],
            "played_sec": agg["play_seconds"],
            "successful_jumps": agg["successful_jumps"],
            "zone_entries": agg["zone_entries"],
            "click_success_rate": agg["click_success_rate"],
            "reaction_median": agg["reaction_median"],
            "net_charge_median": agg["net_charge_median"],
            "valid_signal_ratio": agg["valid_signal_ratio"],
            "low_quality_sessions": agg["low_quality_sessions"],
            "has_data": bool(group),
        })
    return out


def _difficulty_view(uid: str, date_range: Dict[str, Any]) -> Dict[str, Any]:
    # 只读：不能因为查看成长报告就为老用户创建难度档。
    with storage.lock, storage._db() as conn:
        row = conn.execute("SELECT * FROM difficulty_profiles WHERE user_id = ?", (str(uid),)).fetchone()
    profile = storage._difficulty_row(row) if row else None
    history = storage.difficulty_history(uid, 200)
    points = []
    for row in reversed(history):
        value = row.get("created_at") or row.get("updated_at")
        if not _in_range(value, date_range):
            continue
        points.append({
            "date": _date_label(value, date_range.get("tz_offset_min")),
            "before": row.get("before_factor"),
            "after": row.get("after_factor"),
            "direction": row.get("direction"),
            "decision": row.get("decision"),
            "reason": row.get("reason") or row.get("decision"),
        })
    return {
        "current_factor": profile.get("factor") if profile else None,
        "current_label": (f"{float(profile['factor']):.2f}" if profile and profile.get("factor") is not None else None),
        "auto_enabled": bool(profile.get("auto_enabled")) if profile else None,
        "manual_lock": bool(profile.get("manual_lock")) if profile else None,
        "strategy_version": profile.get("strategy_version") if profile else None,
        "points": points,
    }


def _calibration_view(uid: str, date_range: Dict[str, Any]) -> Dict[str, Any]:
    records = storage.calibration_history(uid, 200)
    selected = [r for r in records if _in_range(r.get("calibrated_at"), date_range)]
    latest = selected[0] if selected else None
    return {
        "count": len(selected),
        "last": ({
            "calibration_id": latest.get("calibration_id"),
            "date": _time_label(latest.get("calibrated_at"), date_range.get("tz_offset_min")),
            "source": latest.get("source_name"),
            "valid": latest.get("is_valid"),
            "status": latest.get("status"),
            "device_key": latest.get("device_key"),
            "reference_baseline_id": latest.get("reference_baseline_id"),
        } if latest else None),
    }


def _assessment_segments(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_key: Dict[str, List[Dict[str, Any]]] = {}
    for item in items:
        key = item.get("condition_key")
        if item.get("comparable") and key:
            by_key.setdefault(key, []).append(item)
    groups = []
    for key, rows in by_key.items():
        rows.sort(key=lambda r: r.get("date") or "")
        segments = []
        for metric in ("reference_score", "pre_map_score", "click_success_rate",
                       "reaction_median", "net_charge_median", "valid_signal_ratio"):
            points = [{"date": r.get("date"), "value": r.get(metric),
                       "assessment_id": r.get("assessment_id")}
                      for r in rows if r.get(metric) is not None]
            if points:
                first = points[0]["value"]
                last = points[-1]["value"]
                change = round(last - first, 3) if len(points) >= 2 else None
                segments.append({
                    "metric": metric, "label": METRIC_DEFINITIONS.get(
                        {"reference_score": "assessment_reference",
                         "pre_map_score": "assessment_pre_map",
                         "click_success_rate": "click_success_rate",
                         "reaction_median": "reaction_median",
                         "net_charge_median": "net_charge_median",
                         "valid_signal_ratio": "valid_signal_ratio"}.get(metric, metric),
                        {}).get("label", metric),
                    "points": points,
                    "first": first,
                    "last": last,
                    "change": change,
                    "trend_available": len(points) >= 2,
                })
        groups.append({
            "key": key,
            "label": rows[0].get("condition_label"),
            "conditions": rows[0].get("conditions"),
            "records": rows,
            "count": len(rows),
            "trend_available": len(rows) >= 2,
            "trend_note": ("可比较趋势" if len(rows) >= 2 else "仅 1 次有效评估，不计算趋势"),
            "series": segments,
        })
    groups.sort(key=lambda g: g["records"][0].get("date") or "")
    previous = None
    for group in groups:
        notes = []
        if previous:
            a = previous.get("conditions") or {}
            b = group.get("conditions") or {}
            labels = {
                "device_key": "设备配置变化",
                "algorithm_version": "脑电算法版本变化",
                "mapping_version": "映射版本变化",
                "reference_baseline_id": "长期参考基线变化",
                "reference_version": "长期参考基线版本变化",
                "protocol_version": "评估协议变化",
                "planned_sec": "评估时长变化",
                "fixed_factor": "任务难度参数变化",
                "difficulty_params_version": "难度参数版本变化",
                "game_params_version": "玩法参数版本变化",
                "start_energy": "起始蓄力变化",
            }
            for key_name, label in labels.items():
                if a.get(key_name) == b.get(key_name):
                    continue
                if key_name == "reference_version" and a.get("reference_baseline_id") != b.get("reference_baseline_id"):
                    continue
                notes.append(label)
        group["segment_reason"] = "；".join(notes) if notes else ("首段" if previous is None else "条件相同")
        previous = group
    return {
        "segments": groups,
        "comparable_count": sum(g["count"] for g in groups),
        "trend_count": sum(1 for g in groups if g["trend_available"]),
        "policy": "仅同一用户、同一设备配置、算法、映射、长期参考基线、评估协议和任务参数一致，且质量合格的标准评估才同段比较。",
        "seed_policy": "评估 seed 仅记录随机任务序列；同协议下不要求 seed 相同，避免把正常随机差异误判为条件变化。",
    }


def _assessment_section(uid: str, date_range: Dict[str, Any]) -> Dict[str, Any]:
    items_all = []
    for rec in storage.assessments(uid, 200):
        value = rec.get("ended_at") or rec.get("started_at") or rec.get("created_at")
        if not _in_range(value, date_range):
            continue
        items_all.append(_assessment_row_summary(rec, date_range.get("tz_offset_min")))
    items_all.sort(key=lambda r: r.get("ended_at") or r.get("started_at") or "")
    trend = _assessment_segments(items_all)
    return {
        "items": items_all,
        "real_count": sum(1 for r in items_all if not r.get("simulation")),
        "simulation_count": sum(1 for r in items_all if r.get("simulation")),
        "completed_count": sum(1 for r in items_all if r.get("status") == "completed"),
        "trend": trend,
    }


def _usage(uid: str, sessions: List[Dict[str, Any]], assessments: List[Dict[str, Any]],
           date_range: Dict[str, Any]) -> Dict[str, Any]:
    formal = [r for r in sessions if r.get("is_formal") and _in_range(r.get("started_at"), date_range)]
    real_assessments = [r for r in assessments
                        if not r.get("simulation") and _in_range(
                            r.get("ended_at") or r.get("started_at"), date_range)]
    calibration = _calibration_view(uid, date_range)
    all_real_dates = {r.get("date_key") for r in formal if r.get("date_key")}
    all_real_dates.update(r.get("date") for r in real_assessments if r.get("date"))
    for item in storage.calibration_history(uid, 200):
        if _in_range(item.get("calibrated_at"), date_range):
            key = _date_key(item.get("calibrated_at"), date_range.get("tz_offset_min"))
            if key:
                all_real_dates.add(key)
    agg = _aggregate_sessions(formal)
    session_kinds = {}
    for row in sessions:
        if _in_range(row.get("started_at"), date_range):
            session_kinds[row.get("kind")] = session_kinds.get(row.get("kind"), 0) + 1
    last_candidates = []
    for row in formal:
        if row.get("started_at"):
            last_candidates.append(row.get("started_at"))
    for row in real_assessments:
        last_candidates.append(row.get("ended_at") or row.get("started_at"))
    if calibration.get("last"):
        last_candidates.append(calibration["last"].get("date"))
    last_use = max(last_candidates, key=lambda x: _parse_dt(x) or datetime.min.replace(tzinfo=timezone.utc)) if last_candidates else None
    return {
        "usage_days": len(all_real_dates),
        "formal_game_count": len(formal),
        "play_seconds": agg["play_seconds"],
        "effective_signal_seconds": agg["effective_signal_seconds"],
        "last_use": _time_label(last_use, date_range.get("tz_offset_min")),
        "calibration_count": calibration["count"],
        "assessment_count": len(real_assessments),
        "simulation_count": sum(1 for row in sessions if row.get("is_simulation")
                                and _in_range(row.get("started_at"), date_range))
                             + sum(1 for row in assessments if row.get("simulation")
                                   and _in_range(row.get("ended_at") or row.get("started_at"), date_range)),
        "category_counts": {
            "formal_game": len(formal),
            "calibration": calibration["count"],
            "assessment": len(real_assessments),
            "assessment_simulation": sum(1 for row in assessments if row.get("simulation")
                                          and _in_range(row.get("ended_at") or row.get("started_at"), date_range)),
            "simulation": sum(1 for row in sessions if row.get("kind") == "simulation"
                              and _in_range(row.get("started_at"), date_range)),
            "replay": sum(1 for row in sessions if row.get("kind") == "replay"
                          and _in_range(row.get("started_at"), date_range)),
            "other": sum(1 for row in sessions if row.get("kind") == "other"
                         and _in_range(row.get("started_at"), date_range)),
        },
        "session_kinds": session_kinds,
        "calibration_last": calibration.get("last"),
    }


def _session_public(row: Dict[str, Any]) -> Dict[str, Any]:
    metrics = row.get("metrics") or {}
    return {
        "session_id": row.get("session_id"),
        "assessment_id": row.get("assessment_id"),
        "date": row.get("date"),
        "date_key": row.get("date_key"),
        "started_at": row.get("started_at"),
        "ended_at": row.get("ended_at"),
        "duration_sec": row.get("duration_sec"),
        "played_sec": metrics.get("played_sec"),
        "score": metrics.get("score"),
        "kind": row.get("kind"),
        "kind_label": row.get("kind_label"),
        "source_label": row.get("source_label"),
        "eeg_available": row.get("eeg_available"),
        "low_quality": row.get("low_quality"),
        "metrics": {k: v for k, v in metrics.items() if not k.startswith("_")},
        "difficulty": row.get("difficulty"),
        "reference": row.get("reference"),
    }


def _build_milestones(sessions: List[Dict[str, Any]], assessments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    formal = sorted([r for r in sessions if r.get("is_formal") and r.get("date_key")],
                    key=lambda r: r.get("date_key") or "")
    milestones = []
    if formal:
        milestones.append({"id": "first_game", "label": "第一次和小蛙一起跳荷叶", "date": formal[0]["date"]})
    jumps = 0
    play = 0.0
    for row in formal:
        jumps += int(row["metrics"].get("successful_jumps") or 0)
        play += float(row["metrics"].get("played_sec") or 0)
        if jumps >= 100 and not any(m["id"] == "jumps_100" for m in milestones):
            milestones.append({"id": "jumps_100", "label": "累计成功跳跃 100 次", "date": row["date"]})
        if jumps >= 500 and not any(m["id"] == "jumps_500" for m in milestones):
            milestones.append({"id": "jumps_500", "label": "累计成功跳跃 500 次", "date": row["date"]})
        if play >= 3600 and not any(m["id"] == "play_60m" for m in milestones):
            milestones.append({"id": "play_60m", "label": "累计游玩 60 分钟", "date": row["date"]})
    if len(formal) >= 10:
        milestones.append({"id": "games_10", "label": "完成 10 次正式游戏", "date": formal[9]["date"]})
    completed_assessments = [a for a in assessments
                             if a.get("status") == "completed" and not a.get("simulation")]
    if completed_assessments:
        milestones.append({"id": "first_assessment", "label": "第一次完成标准评估",
                          "date": completed_assessments[0].get("date")})
    return milestones[-8:]


def _bootstrap_assets(uid: str) -> Dict[str, Any]:
    # 只读资产查询；不要调用 bootstrap（它会为老用户创建难度档）。
    try:
        with storage.lock, storage._db() as conn:
            owned = [r["item_id"] for r in conn.execute(
                "SELECT item_id FROM inventories WHERE user_id = ? AND kind = 'shop'",
                (str(uid),),
            ).fetchall()]
            rows = conn.execute(
                "SELECT achievement_id, unlocked_at, seen FROM achievements WHERE user_id = ?",
                (str(uid),),
            ).fetchall()
    except Exception:
        return {"owned": [], "achievements": []}
    achievements = [str(row["achievement_id"]) for row in rows if row["achievement_id"]]
    return {"owned": [str(x) for x in owned if x], "achievements": achievements}


def build_diary(uid: str, tz_offset_min: Optional[int] = None) -> Dict[str, Any]:
    storage.ensure_user(uid)
    sessions, raw_assessments = _load_sessions(uid, tz_offset_min)
    formal = [r for r in sessions if r.get("is_formal")]
    formal.sort(key=lambda r: r.get("date_key") or "")
    all_agg = _aggregate_sessions(formal)
    range_7 = resolve_range("7d", tz_offset_min=tz_offset_min)
    recent = _daily_rows(formal, range_7)
    recent_sessions = [r for r in formal if _in_range(r.get("started_at"), range_7)][-5:]
    assessments = []
    for rec in raw_assessments:
        assessments.append(_assessment_row_summary(rec, tz_offset_min))
    assessments.sort(key=lambda item: item.get("date") or "")
    achievements = _bootstrap_assets(uid)
    return {
        "version": GROWTH_VERSION,
        "user": {"nickname": (storage.get_user(uid) or {}).get("nickname") or "小蛙朋友"},
        "summary": {
            "play_days": len({r.get("date_key") for r in formal if r.get("date_key")}),
            "play_seconds": all_agg["play_seconds"],
            "successful_jumps": all_agg["successful_jumps"],
            "score": all_agg["score"],
            "formal_games": all_agg["sessions"],
        },
        "recent": recent,
        "recent_sessions": [_session_public(r) for r in recent_sessions],
        "owned": achievements["owned"],
        "achievements": achievements["achievements"],
        "milestones": _build_milestones(formal, assessments),
        "has_data": bool(formal),
        "notes": [
            "小蛙只展示陪你玩过的真实游戏记录，不展示脑电分数。",
            "数据不足时不会用 0 代替缺失内容。",
        ],
    }


def build_report(uid: str, date_range: Dict[str, Any]) -> Dict[str, Any]:
    user = storage.get_user(uid)
    if not user:
        raise StorageError("个人档案不存在")
    sessions, raw_assessments = _load_sessions(uid, date_range.get("tz_offset_min"))
    assessment_section = _assessment_section(uid, date_range)
    formal = [r for r in sessions if r.get("is_formal") and _in_range(r.get("started_at"), date_range)]
    formal.sort(key=lambda r: r.get("started_at") or "")
    behavior = _aggregate_sessions(formal)
    usage = _usage(uid, sessions, assessment_section["items"], date_range)
    daily = _daily_rows(formal, date_range)
    difficulty = _difficulty_view(uid, date_range)
    if not formal and not assessment_section["items"]:
        difficulty["current_factor"] = None
        difficulty["current_label"] = None
    quality = {
        "sessions_total": len(formal),
        "sessions_low_quality": sum(1 for r in formal if r.get("low_quality")),
        "sessions_missing_rounds": sum(1 for r in formal if not r["metrics"].get("rounds_count")),
        "sessions_missing_reaction": sum(1 for r in formal if not r["metrics"].get("reaction_count")),
        "sessions_missing_net_charge": sum(1 for r in formal if not r["metrics"].get("net_charge_count")),
        "assessment_uncomparable": sum(1 for a in assessment_section["items"]
                                        if not a.get("comparable")),
        "assessment_simulation": assessment_section["simulation_count"],
    }
    has_data = bool(formal or assessment_section["items"] or usage["calibration_count"])
    report = {
        "version": GROWTH_VERSION,
        "report_kind": "parent_growth",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        # 报告只需要显示称呼；不把本地 user_id 写入可下载报告。
        "user": {"nickname": user.get("nickname") or "小蛙朋友"},
        "range": date_range,
        "scope": {
            "data_dir": "本地 SQLite（未在报告中暴露绝对路径）",
            "storage": "SQLite / 本地报告文件",
            "encrypted": False,
            "cloud_upload": False,
            "raw_eeg_included": False,
        },
        "has_data": has_data,
        "usage": usage,
        "behavior": behavior,
        "daily": daily,
        "sessions": [_session_public(r) for r in formal],
        "assessments": assessment_section,
        "difficulty": difficulty,
        "quality": quality,
        "data_quality": {
            "low_signal_threshold": MIN_VALID_SIGNAL_RATIO,
            "notes": [
                "低质量记录保留在历史列表，但不参与标准评估趋势。",
                "未完成蓄力轮次不进入净蓄力中位数，单列计数。",
                "缺失指标显示“数据不足”，不以 0 代替。",
            ],
        },
        "definitions": METRIC_DEFINITIONS,
        "limitations": LIMITATIONS,
        "narrative": _narrative(has_data, usage, behavior, assessment_section, quality),
        "comparison_policy": assessment_section["trend"]["policy"],
    }
    return report


def _narrative(has_data: bool, usage: Dict[str, Any], behavior: Dict[str, Any],
               assessments: Dict[str, Any], quality: Dict[str, Any]) -> List[str]:
    if not has_data:
        return ["所选日期范围内没有可统计的正式游戏、校准或标准评估记录。",
                "不生成虚假历史，也不以 0 代替缺失数据。"]
    lines = []
    lines.append(f"所选范围内有 {usage['formal_game_count']} 次正式游戏，"
                 f"累计游戏时长 {round((usage['play_seconds'] or 0) / 60, 1)} 分钟。")
    if behavior.get("click_success_rate") is not None:
        lines.append(f"成功跳跃 {behavior.get('successful_jumps')} 次，"
                     f"点击成功率 {round(behavior['click_success_rate'] * 100, 1)}%"
                     f"（分母为成功与未成功完成跳跃之和）。")
    else:
        lines.append("点击成功率缺少有效分母，显示为数据不足。")
    lines.append(f"标准评估完成 {assessments['completed_count']} 次，"
                 f"其中模拟/回放 {assessments['simulation_count']} 次。")
    if quality.get("assessment_uncomparable"):
        lines.append(f"有 {quality['assessment_uncomparable']} 次评估因条件或质量原因不参与趋势比较。")
    if quality.get("sessions_low_quality"):
        lines.append(f"有 {quality['sessions_low_quality']} 次正式游戏被标记为低信号质量，保留记录但不进入脑电趋势。")
    lines.append("以上是游戏与任务记录的描述性统计，不是临床注意力评价或治疗效果结论。")
    return lines


def build_session_detail(uid: str, session_id: str, include_rounds: bool = False,
                         tz_offset_min: Optional[int] = None) -> Dict[str, Any]:
    report = storage.load_report(session_id, uid)
    if report is None:
        raise StorageError("历史游戏报告不存在")
    owner = storage.report_owner(session_id)
    if owner and str(owner) != str(uid):
        raise StorageError("无权访问其他用户的报告")
    sessions, _ = _load_sessions(uid, tz_offset_min)
    match = next((r for r in sessions if str(r.get("session_id")) == str(session_id)), None)
    if match is None:
        # 已回收 Session 仍应能从报告本身读取；构造最小元信息。
        item = {"session_id": session_id, "report": report,
                "started_at": report.get("created_at"), "ended_at": report.get("created_at"),
                "finished": True, "purpose": report.get("purpose"),
                "demo": report.get("demo"), "source": report.get("source")}
        match = _make_session_calc(item, {}, tz_offset_min)
    metrics = match.get("metrics") or {}
    diag = match.get("diagnostics") or diagnostics.diagnose(report)
    rounds = []
    if include_rounds:
        actions = _safe_dict(report.get("actions"))
        rounds = [r for r in _safe_list(actions.get("rounds")) if isinstance(r, dict)]
        incomplete = _safe_dict(actions.get("incomplete_round"))
        if incomplete:
            incomplete = dict(incomplete)
            incomplete["_incomplete"] = True
            rounds = rounds + [incomplete]
    data = {
        "session_id": session_id,
        "date": match.get("date"),
        "date_key": match.get("date_key"),
        "duration_sec": match.get("duration_sec"),
        "played_sec": metrics.get("played_sec"),
        "score": metrics.get("score"),
        "kind": match.get("kind"),
        "kind_label": match.get("kind_label"),
        "source_label": match.get("source_label"),
        "eeg_available": match.get("eeg_available"),
        "low_quality": match.get("low_quality"),
        "metrics": {k: v for k, v in metrics.items() if not k.startswith("_")},
        "difficulty": match.get("difficulty"),
        "calibration": match.get("calibration"),
        "reference": match.get("reference"),
        "diagnostics": diag,
        "assessment": report.get("assessment") if isinstance(report.get("assessment"), dict) else None,
        "storage": "sqlite",
        "rounds_available": bool(_safe_list(_safe_dict(report.get("actions")).get("rounds"))),
        "rounds": rounds,
        "definitions": METRIC_DEFINITIONS,
        "limitations": LIMITATIONS,
    }
    return data


def export_metadata(report: Dict[str, Any], fmt: str) -> Dict[str, str]:
    import re
    nick = str(_safe_dict(report.get("user")).get("nickname") or "小蛙朋友")
    safe_nick = re.sub(r'[\\/:*?"<>|]+', "_", nick).strip()[:20] or "小蛙朋友"
    date_range = _safe_dict(report.get("range"))
    start = date_range.get("start") or "全部"
    end = date_range.get("end") or "今天"
    ext = {"pdf": "pdf", "xlsx": "xlsx", "json": "json", "csv": "csv"}[fmt]
    return {
        "filename": f"专注小蛙_成长报告_{safe_nick}_{start}_{end}.{ext}",
        "media_type": {"pdf": "application/pdf",
                       "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       "json": "application/json; charset=utf-8",
                       "csv": "text/csv; charset=utf-8"}[fmt],
    }
