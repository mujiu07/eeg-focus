"""v1.8.4 开发者结构化诊断导出。

默认只导出低频分数、逐轮行为、校准/参考/难度快照和诊断结果；
不导出高频原始脑电数组，不包含用户昵称。导出必须由用户主动调用，
写入本地数据目录的 reports/，不自动上传。
"""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from . import diagnostics

EXPORT_VERSION = "dev_diagnostics_v1"


def _f(value: Any) -> Optional[float]:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if n == n else None


def _safe_source(source: Optional[dict]) -> dict:
    src = dict(source or {})
    file_value = src.get("file")
    if file_value:
        src["file"] = Path(str(file_value)).name
    return src


def build_payload(report: Optional[dict], *, user_id: Optional[str] = None,
                  runtime: Optional[dict] = None) -> dict:
    report = report or {}
    metrics = {}
    try:
        from . import difficulty
        metrics = difficulty.compute_metrics(report)
    except Exception:
        metrics = {}
    diag = report.get("diagnostics") or diagnostics.diagnose(report, metrics)
    process = report.get("charge_process") or diagnostics.charge_process(report)
    actions = report.get("actions") or {}
    payload = {
        "export_version": EXPORT_VERSION,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "software": {
            "app": "专注小蛙",
            "version": (runtime or {}).get("version") or "unknown",
            "schema_version": (runtime or {}).get("schema_version"),
            "algorithm_version": report.get("algorithm_version"),
            "difficulty_strategy": (report.get("difficulty_snapshot") or {}).get("strategy_version"),
            "assessment": report.get("assessment"),
        },
        "subject": {
            "anonymous_user_id": user_id or report.get("user_id"),
            "nickname_exported": False,
            "note": "默认不导出昵称；只保留本地匿名档案 ID。",
        },
        "session": {
            "session_id": report.get("session_id"),
            "purpose": report.get("purpose") or "game",
            "assessment_id": report.get("assessment_id"),
            "created_at": report.get("created_at"),
            "duration_sec": report.get("duration_sec"),
            "played_sec": report.get("played_sec"),
            "planned_sec": report.get("planned_sec"),
            "score": report.get("score"),
            "demo": bool(report.get("demo")),
            "source": _safe_source(report.get("source")),
        },
        "calibration": {
            "calibration_id": report.get("calibration_id"),
            "status": (report.get("calibration_snapshot") or {}).get("status")
            or report.get("calibration_status"),
            "snapshot": report.get("calibration_snapshot") or report.get("calibration"),
        },
        "reference": {
            "reference_baseline_id": report.get("reference_baseline_id"),
            "snapshot": report.get("reference_snapshot"),
            "range": report.get("reference_score_range"),
        },
        "difficulty": report.get("difficulty_snapshot") or {},
        "metrics": metrics,
        "charge_process": process,
        "diagnostics": diag,
        "rounds": diagnostics.summarize_rounds(report, limit=2000),
        "incomplete_round": actions.get("incomplete_round"),
        "game_process": actions.get("game_process") or {},
        "signal_quality": report.get("signal_quality"),
        "signal_counts": {
            "n_frames": report.get("n_frames"),
            "n_valid_frames": report.get("n_valid_frames"),
            "n_invalid_frames": report.get("n_invalid_frames"),
            "valid_signal_ratio": report.get("valid_signal_ratio"),
        },
        "runtime": runtime or {},
        "privacy": {
            "raw_eeg_exported": False,
            "nickname_exported": False,
            "uploaded": False,
        },
    }
    return payload


def to_json_bytes(payload: dict) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def to_csv_bytes(payload: dict) -> bytes:
    """两层 CSV：session/诊断元数据 + 逐轮表；浏览器/表格软件均可读。"""
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["section", "key", "value"])
    for section in ("software", "subject", "session", "calibration", "reference",
                    "difficulty", "metrics", "charge_process", "diagnostics",
                    "signal_quality", "signal_counts", "privacy", "game_process"):
        value = payload.get(section)
        if isinstance(value, dict):
            for key, item in value.items():
                writer.writerow([section, key, _scalar(item)])
        else:
            writer.writerow([section, "", _scalar(value)])
    writer.writerow([])
    rows = payload.get("rounds") or []
    if rows:
        header = list(rows[0].keys())
        writer.writerow(header)
        for row in rows:
            writer.writerow([_scalar(row.get(k)) for k in header])
    return out.getvalue().encode("utf-8-sig")


def filename_for(session_id: str, fmt: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]", "", str(session_id or "session"))[:24] or "session"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"diagnostics-{safe}-{stamp}.{'csv' if fmt == 'csv' else 'json'}"


def write_export(reports_dir: Path, session_id: str, fmt: str, payload: dict) -> dict:
    fmt = "csv" if str(fmt).lower() == "csv" else "json"
    name = filename_for(session_id, fmt)
    content = to_csv_bytes(payload) if fmt == "csv" else to_json_bytes(payload)
    reports_dir.mkdir(parents=True, exist_ok=True)
    dest = reports_dir / name
    dest.write_bytes(content)
    return {"filename": name, "path": str(dest), "content": content,
            "media_type": "text/csv; charset=utf-8" if fmt == "csv" else "application/json; charset=utf-8"}
