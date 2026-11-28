"""v1.8.2 每日游戏化校准的纯函数与集中配置。

边界：
  * 不修改底层 EEG 特征算法；只把有效特征值映射成游戏分。
  * 自然观察/教学阶段等权合并，不用“教学一定更高”的先验。
  * 统计值、最小跨度和样本门槛集中在这里，便于测试和后续调参。
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

PROTOCOL_VERSION = "daily_v3"
MAPPING_VERSION = "map_v2"

# v1.9.4：平静阶段改为固定低刺激动态池塘（睁眼观察），不再播放外部视频。
# 这里只描述刺激条件，不改变特征、去噪、分位数或映射算法。
STIMULUS_CONDITION = {
    "version": "calm_pond_open_eyes_v1",
    "natural_stage": "fixed_low_stimulation_pond",
    "natural_eyes": "open",
    "video": "none",
    "background_music": "paused_then_restored",
    "tutorial": "preset_demo_then_guided_charge",
    "not_strict_resting_eeg": True,
}

CONFIG: dict[str, Any] = {
    "natural_sec": 30.0,
    "tutorial_sec": 30.0,
    "max_stage_sec": 75.0,
    "min_effective_sec": 20.0,
    "min_stage_samples": 30,
    "max_stage_samples": 240,
    "p_low": 0.15,
    "p_high": 0.85,
    "low_score": 20.0,
    "high_score": 80.0,
    "min_span": 0.10,
    "daily_ttl_sec": 4 * 60 * 60,
    "protocol_version": PROTOCOL_VERSION,
    "mapping_version": MAPPING_VERSION,
    "low_quality_usable_ratio": 0.50,
}

STAGE_LABELS = {"natural": "自然观察", "tutorial": "游戏教学"}


class CalibrationDataError(ValueError):
    """有效数据不足或阶段数据不可用于建立校准。"""


def _finite(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def percentile(values: Iterable[float], p: float) -> float:
    """线性插值分位数；不直接取瞬时最小/最大值。"""
    vals = sorted(v for v in (_finite(x) for x in values) if v is not None)
    if not vals:
        raise CalibrationDataError("没有有效样本")
    p = max(0.0, min(1.0, float(p)))
    pos = (len(vals) - 1) * p
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(vals[lo])
    frac = pos - lo
    return float(vals[lo] * (1.0 - frac) + vals[hi] * frac)


def effective_seconds(times_ms: Iterable[float]) -> float:
    """由有效帧时间戳估计有效采集秒数，不把无效空档算进去。

    采用相邻有效帧的中位间隔；单个间隔最多计 1 秒，避免卡顿/断流被当成
    连续采集。最后一帧补半个中位间隔，保守估计。
    """
    ts = sorted(float(t) for t in times_ms if _finite(t) is not None)
    if not ts:
        return 0.0
    if len(ts) == 1:
        return 0.0
    gaps = [b - a for a, b in zip(ts, ts[1:]) if b > a]
    if not gaps:
        return 0.0
    gaps.sort()
    median = gaps[len(gaps) // 2]
    total = sum(min(g, 1.0) for g in gaps if g <= max(2.0, median * 4))
    return round(min(total + median / 2.0, ts[-1] - ts[0] + median), 2)


def stage_summary(entries: list[dict], stage: str) -> dict:
    vals = []
    times = []
    artifact_frames = 0
    for e in entries:
        if not e.get("valid", True) or e.get("focus") is None:
            artifact_frames += 1
            continue
        x = e.get("focus_fused") if e.get("focus_fused") is not None else e.get("focus")
        x = _finite(x)
        if x is None:
            artifact_frames += 1
            continue
        vals.append(x)
        times.append(e.get("t"))
    if not vals:
        raise CalibrationDataError(f"{STAGE_LABELS.get(stage, stage)}没有有效脑电样本")
    return {
        "stage": stage,
        "label": STAGE_LABELS.get(stage, stage),
        "n": len(vals),
        "n_invalid": artifact_frames,
        "effective_sec": effective_seconds(times),
        "q15": round(percentile(vals, CONFIG["p_low"]), 4),
        "q50": round(percentile(vals, 0.50), 4),
        "q85": round(percentile(vals, CONFIG["p_high"]), 4),
        "mean": round(sum(vals) / len(vals), 4),
        "min": round(min(vals), 4),
        "max": round(max(vals), 4),
    }


def _cap_equal(vals: list[float], cap: int) -> list[float]:
    """阶段等权：超过上限时均匀抽稀，防止某一阶段靠样本量主导区间。"""
    if len(vals) <= cap:
        return vals
    step = len(vals) / float(cap)
    return [vals[min(len(vals) - 1, int(i * step))] for i in range(cap)]


def compute_daily_range(natural_entries: list[dict], tutorial_entries: list[dict],
                        *, signal_quality: Optional[dict] = None) -> dict:
    """根据两个阶段的有效帧生成当日 L/H 与阶段统计。

    正式游戏使用 L/H 的 P15/P85 映射；不把阶段标签当成高/低先验。
    """
    natural = stage_summary(natural_entries, "natural")
    tutorial = stage_summary(tutorial_entries, "tutorial")

    for stage in (natural, tutorial):
        if stage["n"] < CONFIG["min_stage_samples"]:
            raise CalibrationDataError(
                f"{stage['label']}有效样本不足（{stage['n']} < {CONFIG['min_stage_samples']}）")
        if stage["effective_sec"] < CONFIG["min_effective_sec"]:
            raise CalibrationDataError(
                f"{stage['label']}有效采集不足（{stage['effective_sec']:.1f}s < {CONFIG['min_effective_sec']:.0f}s）")

    sq = signal_quality or {}
    usable = _finite(sq.get("usable_ratio"))
    if usable is not None and usable < CONFIG["low_quality_usable_ratio"]:
        raise CalibrationDataError(
            f"信号可用率不足（{usable:.0%} < {CONFIG['low_quality_usable_ratio']:.0%}），请调整电极后重试")

    vals_n = []
    vals_t = []
    for e in natural_entries:
        x = e.get("focus_fused") if e.get("focus_fused") is not None else e.get("focus")
        x = _finite(x)
        if e.get("valid", True) and x is not None:
            vals_n.append(x)
    for e in tutorial_entries:
        x = e.get("focus_fused") if e.get("focus_fused") is not None else e.get("focus")
        x = _finite(x)
        if e.get("valid", True) and x is not None:
            vals_t.append(x)

    # 两个阶段等权抽稀，避免时长/帧率不同造成单阶段主导。
    cap = int(CONFIG["max_stage_samples"])
    pooled = _cap_equal(vals_n, cap) + _cap_equal(vals_t, cap)
    low = percentile(pooled, CONFIG["p_low"])
    high = percentile(pooled, CONFIG["p_high"])
    range_quality = "ok"
    if high - low < CONFIG["min_span"]:
        # 保留 v1.8.1 的最小跨度保护，但标记出来；不静默伪装成灵敏区间。
        mid = (low + high) / 2.0
        low = max(0.0, mid - CONFIG["min_span"] / 2.0)
        high = min(1.0, low + CONFIG["min_span"])
        if high - low < CONFIG["min_span"]:
            low = max(0.0, high - CONFIG["min_span"])
        range_quality = "stretched"

    low = round(max(0.0, min(0.9, low)), 4)
    high = round(min(1.0, max(low, high)), 4)
    contrast = tutorial["mean"] - natural["mean"]
    if abs(contrast) < 0.02:
        contrast_label = "flat"
    elif contrast > 0:
        contrast_label = "tutorial_higher"
    else:
        contrast_label = "natural_higher"

    return {
        "range": {"low": low, "high": high},
        "quantiles": {"q15": round(percentile(pooled, CONFIG["p_low"]), 4),
                      "q50": round(percentile(pooled, 0.50), 4),
                      "q85": round(percentile(pooled, CONFIG["p_high"]), 4)},
        "range_quality": range_quality,
        "stage_contrast": round(contrast, 4),
        "stage_contrast_label": contrast_label,
        "stages": {"natural": natural, "tutorial": tutorial},
        "n_frames": len(pooled),
        "n_total_valid": len(vals_n) + len(vals_t),
        "effective_sec": round(natural["effective_sec"] + tutorial["effective_sec"], 2),
        "min_span": CONFIG["min_span"],
        "protocol_version": PROTOCOL_VERSION,
        "mapping_version": MAPPING_VERSION,
    }


def local_date(ms: int, tz_offset_min: Optional[int] = None) -> str:
    """把毫秒时间戳转成指定时区的本地日期。"""
    if tz_offset_min is None:
        return datetime.fromtimestamp(ms / 1000).astimezone().date().isoformat()
    tz = timezone(timedelta(minutes=-int(tz_offset_min)))
    return datetime.fromtimestamp(ms / 1000, tz=tz).date().isoformat()


def device_key(mode: str, source: Optional[dict] = None) -> str:
    """信号源/设备配置指纹；用于判断当天校准是否还适用。"""
    src = source or {}
    if mode == "hardware":
        ports = src.get("osc_ports") or ""
        fs = src.get("osc_fs") or ""
        channels = src.get("osc_channels") or ""
        return f"hardware|{ports}|{fs}|{channels}"
    return str(mode or "unknown")


def daily_status(calibrations: list[dict], *, now_ms: int, mode: str = "hardware",
                 device: Optional[str] = None, tz_offset_min: Optional[int] = None) -> dict:
    """从历史校准中选出今天仍可用的一条。"""
    today = local_date(now_ms, tz_offset_min)
    key = device or device_key(mode)
    ttl_ms = int(CONFIG["daily_ttl_sec"] * 1000)
    candidates = []
    for c in calibrations:
        if not c.get("is_valid", True):
            continue
        if c.get("kind", "daily") != "daily":
            continue
        # v1.8.1 的旧校准没有日期/协议，不得当成 v1.8.2 的“今日校准”。
        if c.get("protocol_version") != PROTOCOL_VERSION or not c.get("calibration_date"):
            continue
        if c.get("source_name") and c["source_name"] != mode:
            # 旧记录可能没有 source_name；有值时必须是同一信号源
            continue
        if c.get("calibration_date") and c["calibration_date"] != today:
            continue
        if c.get("device_key") and key and c["device_key"] != key:
            continue
        if c.get("at") and now_ms - int(c["at"]) > ttl_ms:
            continue
        if c.get("at") and int(c["at"]) > now_ms + 5 * 60 * 1000:
            continue
        candidates.append(c)
    chosen = max(candidates, key=lambda c: int(c.get("at") or 0)) if candidates else None
    if not chosen:
        latest = max(calibrations, key=lambda c: int(c.get("at") or 0)) if calibrations else None
        reason = "missing"
        if latest:
            if latest.get("calibration_date") and latest["calibration_date"] != today:
                reason = "date_changed"
            elif key and latest.get("device_key") and latest["device_key"] != key:
                reason = "device_changed"
            elif latest.get("at") and now_ms - int(latest["at"]) > ttl_ms:
                reason = "expired"
        return {"date": today, "valid": False, "reason": reason, "calibration": None,
                "ttl_sec": CONFIG["daily_ttl_sec"], "device_key": key}
    return {"date": today, "valid": True, "reason": "ok", "calibration": chosen,
            "ttl_sec": CONFIG["daily_ttl_sec"], "device_key": key,
            "expires_at": int(chosen.get("at") or 0) + ttl_ms}


def status_text(status: dict) -> str:
    if status.get("valid"):
        return "今日校准有效"
    return {
        "date_changed": "今日尚未校准",
        "expired": "校准已过期，需要重新校准",
        "device_changed": "设备/信号源已变化，需要重新校准",
        "missing": "今日尚未校准",
    }.get(status.get("reason"), "需要重新校准")
