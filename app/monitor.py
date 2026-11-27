"""开发者实时监测数据的纯函数工具。

这里只负责把 Session 已经算完的窗口/特征整理成可 JSON 化的批量数据；
不重新采样、不重新滤波、不生成任何演示波形。
"""

from __future__ import annotations

import numpy as np

from . import features


def _mean_values(value):
    """把 (n_ch,) 或标量整理成 Python float；缺测返回 None。"""
    if value is None:
        return None
    arr = np.asarray(value, dtype=float)
    if arr.size == 0:
        return None
    v = float(np.mean(arr))
    return round(v, 6) if np.isfinite(v) else None


def band_rows(debug: dict | None) -> list[dict]:
    """按算法实际频段顺序返回功率/相对功率，不做前端插值。"""
    if not debug:
        return [{
            "name": name, "range": list(features.BANDS[name]),
            "abs": None, "rel": None, "available": False,
        } for name in features.BAND_NAMES]
    powers = debug.get("powers") or {}
    relative = debug.get("relative") or {}
    rows = []
    for name in features.BAND_NAMES:
        abs_v = _mean_values(powers.get(name))
        rel_v = _mean_values(relative.get(name))
        rows.append({
            "name": name,
            "range": list(features.BANDS[name]),
            "abs": abs_v,
            "rel": rel_v,
            "available": abs_v is not None and rel_v is not None,
        })
    return rows


def algorithm_payload(debug: dict | None, *, score: float | None,
                      fused: float | None, baseline: float | None,
                      score_range: dict) -> dict:
    """只整理实际中间结果，字段缺失就保持 None。"""
    if not debug:
        return {
            "available": False,
            "mode": None,
            "relative": {}, "powers": {}, "ratio": None,
            "sigmoid": None, "probability": None,
            "raw_focus": None, "smooth_focus": None,
            "game_score": score, "fused_focus": fused,
            "baseline": baseline, "score_range": score_range,
        }
    powers = debug.get("powers") or {}
    relative = debug.get("relative") or {}
    return {
        "available": True,
        "mode": debug.get("mode"),
        "relative": {k: _mean_values(v) for k, v in relative.items()},
        "powers": {k: _mean_values(v) for k, v in powers.items()},
        "ratio": _mean_values(debug.get("ratio")),
        "sigmoid": debug.get("sigmoid"),
        "probability": debug.get("probability"),
        "band_focus": debug.get("band_focus"),
        "raw_focus": debug.get("raw_focus"),
        "smooth_focus": debug.get("smooth_focus"),
        "ema_alpha": debug.get("ema_alpha"),
        "game_score": score,
        "fused_focus": fused,
        "baseline": baseline,
        "score_range": score_range,
    }


def serialise_window(arr, *, digits: int = 4):
    """把 (n_ch, n_samples) 转成 JSON 数组；空值显式返回 None。"""
    if arr is None:
        return None
    a = np.asarray(arr, dtype=float)
    if a.ndim != 2 or a.shape[0] == 0 or a.shape[1] == 0:
        return None
    # 保留 4 位小数，足够显示微伏级波形，同时明显减少 5/10 秒缓存带宽。
    # NaN/Inf 不能补 0 冒充正常采样：保留为 JSON null，前端按缺测跳过。
    a = np.round(a, digits)
    return [[None if not np.isfinite(v) else float(v) for v in row] for row in a]


def unit_label(source_name: str, artifact: dict | None) -> tuple[str, str]:
    """返回 (显示单位, 可信度)。不能把未确认的 OSC 数值冒充 μV。"""
    if source_name == "replay":
        return "EDF 物理量", "file"
    raw_unit = (artifact or {}).get("unit")
    if raw_unit == "uV":
        return "µV（幅值推断）", "inferred"
    if raw_unit == "auto":
        return "设备原始单位", "unknown"
    return "未确认", "unknown"


def build_batch(*, seq: int, session_id: str, source_name: str, source_desc: dict,
                raw, processed, sample_meta: dict, artifact: dict | None,
                debug: dict | None, score: float | None, fused: float | None,
                baseline: float | None, score_range: dict, fs: float | None,
                ch_names: list[str] | None, t_offset: float = 0.0) -> dict:
    """构造一个监测批次。

    原始/处理后数组使用同一组样本序号与时间窗口；processed 必须是
    FocusEngine 实际输入，不能在这里另外滤波。
    """
    meta = sample_meta or {}
    raw_a = np.asarray(raw) if raw is not None else None
    proc_a = np.asarray(processed) if processed is not None else None
    n = int(meta.get("n") or (raw_a.shape[1] if raw_a is not None and raw_a.ndim == 2 else 0))
    fs_v = float(meta.get("fs") or fs or 0.0) or None
    unit, confidence = unit_label(source_name, artifact)
    names = list(ch_names or meta.get("ch_names") or [])
    if raw_a is not None and raw_a.ndim == 2 and raw_a.shape[0] > len(names):
        names = names + [f"CH{i + 1}" for i in range(len(names), raw_a.shape[0])]
    if raw_a is not None and proc_a is not None and raw_a.shape != proc_a.shape:
        # 形状不一致说明不是同一窗口，宁可只显示原始/不显示，也不能错位成“处理后”。
        proc_a = None
    channel_mask = (artifact or {}).get("channel_mask")
    channels = []
    for i, name in enumerate(names):
        ok = True
        if isinstance(channel_mask, list) and i < len(channel_mask):
            ok = bool(channel_mask[i])
        channels.append({"name": str(name), "ok": ok})
    # hardware 的绝对时间转为会话相对时间；EDF 保持文件内时间。
    t0 = meta.get("t0")
    t1 = meta.get("t1")
    if t0 is not None and source_name == "hardware":
        t0 = float(t0) - float(t_offset)
        t1 = float(t1) - float(t_offset)
    return {
        "seq": int(seq),
        "session_id": session_id,
        "source": source_desc,
        "source_name": source_name,
        "fs": fs_v,
        "ch_names": names,
        "channels": channels,
        "unit": unit,
        "unit_confidence": confidence,
        "sample_seq0": meta.get("seq0"),
        "sample_seq1": meta.get("seq1"),
        "t0": None if t0 is None else round(float(t0), 4),
        "t1": None if t1 is None else round(float(t1), 4),
        "n": n,
        "time_basis": meta.get("time_basis") or "session_clock",
        "timestamp_note": meta.get("timestamp_note"),
        "raw": serialise_window(raw_a),
        "processed": serialise_window(proc_a),
        "quality": artifact,
        "bands": band_rows(debug),
        # 现有 features.band_power 的分母是 Welch 全频段总功率（0–Nyquist），
        # 不是 0.5–45 Hz 频段和；监测面板必须显示真实口径。
        "relative_power": {
            "denominator": "welch_total_power",
            "range_hz": [0.0, round((fs_v or 0.0) / 2.0, 3)] if fs_v else None,
            "note": "相对功率 = 各频段绝对功率 / 同一窗 Welch 总功率；分母覆盖 0–Nyquist",
        },
        "algorithm": algorithm_payload(
            debug, score=score, fused=fused, baseline=baseline,
            score_range=score_range),
    }
