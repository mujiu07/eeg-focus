"""
Brain-Focusing Game MVP 后端服务
===============================
FastAPI 应用，提供:
  - 专注引擎会话流 (SSE): 实时推送专注指数
  - 校准 API: 建立个人专注基线阈值
  - 会话/报告 API: 保存每局结果与专注曲线
  - 开发者 API: 模型信息、信号源切换
  - 静态托管 web/ 前端页面

启动:  uvicorn app.server:app --port 8000   (工作目录: eeg-focus)
"""

import asyncio
import json
import os
import platform
import time
import uuid
from collections import deque
from copy import copy
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, NonNegativeInt
from typing import Optional
from sse_starlette.sse import EventSourceResponse

from .focus_engine import FocusEngine, features
from . import export as report_export
from . import sources
from . import monitor as monitor_data
from .heart import heart
from .accounts import router as accounts_router
from .growth_api import router as growth_router
from .storage import StorageError, storage
from . import difficulty
from . import diagnostics
from . import dev_export
from . import calibration as calib_engine

# 心率采集链路依赖 macOS 专属的 AirPods 心率进程（hrd），其他系统没有对应实现，
# 因此不暴露这块功能：接口直接拒绝，前端也不渲染入口。
HEART_SUPPORTED = platform.system() == "Darwin"
HEART_UNSUPPORTED_REASON = "心率采集依赖 macOS 的 AirPods 心率进程，当前系统不支持"
from .music import music

ROOT = os.path.join(os.path.dirname(__file__), "..")
WEB_DIR = os.path.join(ROOT, "web")
SESSIONS_DIR = os.path.join(ROOT, "outputs", "sessions")

app = FastAPI(title="Brain-Focusing Game MVP", version="1.9.4")

# 已完成会话在内存中保留的宽限时间；报告/逐轮数据先写入 SQLite，
# 到期后释放 EDF 原始数组和监测批次，历史报告仍可从数据库读取。
SESSION_RETENTION_SEC = float(os.environ.get("FOCUS_FROG_SESSION_TTL_SEC", "900"))

# ---------------------------------------------------------------------------
# 全局状态
# ---------------------------------------------------------------------------
DEFAULT_SOURCE_CONFIG = {
    "mode": "replay",
    "file": None,
    "osc_host": None,
    "osc_ports": None,
    "osc_fs": None,
    "osc_channels": None,
}
_engine = FocusEngine()
_sessions: dict[str, "Session"] = {}
_source_config = dict(DEFAULT_SOURCE_CONFIG)


def _reap_sessions():
    """回收已结束且超过宽限期的内存会话；历史报告已在 SQLite 中。"""
    now = time.time()
    removed = 0
    for sid, session in list(_sessions.items()):
        if not session.finished or session.monitor_clients > 0:
            continue
        finished_at = session.finished_at or now
        if now - finished_at < SESSION_RETENTION_SEC:
            continue
        try:
            session.release()
        except Exception:
            pass
        _sessions.pop(sid, None)
        removed += 1
    return removed


async def _session_reaper():
    while True:
        await asyncio.sleep(60)
        try:
            _reap_sessions()
        except Exception:
            pass


@app.on_event("startup")
async def _startup_local_data():
    # v1.8.1：旧 outputs/sessions JSON 只迁移到“历史记录（未归属）”系统档案，
    # 不自动分配给孩子档案，避免测试/回放记录污染真实用户。
    if os.environ.get("FOCUS_FROG_IMPORT_LEGACY", "1") != "0":
        try:
            storage.import_legacy_reports(Path(SESSIONS_DIR))
        except Exception:
            pass
    asyncio.create_task(_session_reaper())


def _session_for(sid: str, user_id: Optional[str] = None, require_user: bool = False):
    session = _sessions.get(sid)
    if not session:
        raise HTTPException(404, "会话不存在")
    owner = getattr(session, "user_id", None)
    if owner and user_id != owner:
        raise HTTPException(403, "无权访问其他用户的会话")
    if require_user and owner and not user_id:
        raise HTTPException(403, "缺少用户归属")
    return session


def _check_report_owner(report: dict, user_id: Optional[str]):
    owner = report.get("user_id")
    if owner and user_id != owner:
        raise HTTPException(403, "无权访问其他用户的报告")


# ---------------------------------------------------------------------------
# 会话
# ---------------------------------------------------------------------------
class Session:
    def __init__(self, source, config):
        self.id = uuid.uuid4().hex[:8]
        self.source = source
        self.config = config
        self.user_id = config.get("user_id") if isinstance(config, dict) else None
        self.calibration_id = config.get("calibration_id") if isinstance(config, dict) else None
        self.purpose = (config.get("purpose") or "game") if isinstance(config, dict) else "game"
        self.assessment = config.get("assessment") if isinstance(config, dict) else None
        self.assessment_id = config.get("assessment_id") if isinstance(config, dict) else None
        self.reference_baseline_id = config.get("reference_baseline_id") if isinstance(config, dict) else None
        self.calibration_snapshot = None
        self.reference_snapshot = None
        self.difficulty_snapshot = difficulty.default_snapshot()
        self.reference_low = 0.35
        self.reference_high = 0.75
        # 模型只加载一次，每个会话独立维护平滑和回退状态。
        self.engine = copy(_engine)
        self.created_at = time.time()
        self._mono0 = time.monotonic()   # 心率曲线的时间原点（单调钟）
        self.finished_at = None
        self.history = []            # [{t, raw, focus, meta}]
        self.baseline = None
        self.baseline_quantiles = None
        self.calibration = None      # {duration, n, mean, ...}
        self.finished = False
        self.stats = {}
        self._frame_ready = asyncio.Event()
        self._latest_frame = None
        self._task = None
        # v1.7 开发者监测：独立于低频游戏 SSE 的高频窗口流。
        # 只有存在监测订阅者时才构造/保存批次；儿童模式不订阅就不会产生这份数据。
        self._monitor_event = asyncio.Event()
        self._monitor_latest = None
        self._monitor_batches = deque(maxlen=12)
        self._monitor_seq = 0
        self.monitor_clients = 0
        # 动态定标：校准得到"最放松 / 最专注"两端，映射到 20–80 分。
        # 未校准（或旧前端不带区间）时用 0.35/0.75 兜底，50 分线仍是 0.55，与旧基线一致。
        self.score_low = 0.35
        self.score_high = 0.75

    def score_of(self, x):
        """把引擎输出的 0–1 专注值映射成 20–80 的动态分（越界钳到 0–100）。"""
        if x is None:
            return None
        lo, hi = self.score_low, self.score_high
        if hi - lo < 1e-6:
            hi = lo + 0.15
        low_score = float(calib_engine.CONFIG["low_score"])
        high_score = float(calib_engine.CONFIG["high_score"])
        v = low_score + (high_score - low_score) * (float(x) - lo) / (hi - lo)
        return round(max(0.0, min(100.0, v)), 1)

    def score_reference(self, x):
        """长期参考映射：后台趋势记录，绝不参与蓄力/得分/商城。"""
        if x is None or self.reference_low is None or self.reference_high is None:
            return None
        lo, hi = self.reference_low, self.reference_high
        if hi - lo < 1e-6:
            hi = lo + 0.15
        v = calib_engine.CONFIG["low_score"] + (
            calib_engine.CONFIG["high_score"] - calib_engine.CONFIG["low_score"]
        ) * (float(x) - lo) / (hi - lo)
        return round(max(0.0, min(100.0, v)), 1)

    def raw50(self):
        """50 分线对应的原始专注值，用于 focused 判定与报告基线。"""
        return round((self.score_low + self.score_high) / 2.0, 3)

    def apply_difficulty(self, snapshot: Optional[dict]) -> None:
        """锁定本局黄色区域范围；局内任何实时表现都不得改动它。"""
        if snapshot:
            self.difficulty_snapshot = dict(snapshot)

    def apply_calibration(self, cal: Optional[dict], reference: Optional[dict] = None) -> None:
        """固定本局使用的当日校准与长期参考快照。"""
        if cal:
            self.calibration_id = cal.get("id")
            self.calibration = cal
            self.calibration_snapshot = cal
            rng = cal.get("range") or {}
            if rng.get("low") is not None and rng.get("high") is not None:
                self.score_low = round(float(rng["low"]), 4)
                self.score_high = round(float(rng["high"]), 4)
            if cal.get("baseline") is not None:
                self.baseline = round(float(cal["baseline"]), 4)
        if reference:
            self.reference_baseline_id = reference.get("id")
            self.reference_snapshot = reference
            rng = reference.get("range") or {}
            if rng.get("low") is not None and rng.get("high") is not None:
                self.reference_low = round(float(rng["low"]), 4)
                self.reference_high = round(float(rng["high"]), 4)

    async def start(self):
        # 预热模型状态
        self.engine.reset()
        # EDF 读取+滤波耗时数秒，在线程池执行，避免阻塞事件循环
        # （否则刚创建会话时 SSE 连接会长时间收不到任何帧）
        # hardware 只做端口绑定，也放到线程池，避免绑定异常卡住事件循环。
        if self.source.name in ("replay", "hardware"):
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self.source.start)
        self._task = asyncio.create_task(self._run())

    async def _run(self):
        loop = asyncio.get_running_loop()
        while not self.finished:
            t0 = time.time()
            try:
                if self.source.name == "hardware":
                    # next_window 会阻塞等待 OSC 窗口，必须放线程池，
                    # 否则整个 FastAPI 事件循环会被卡住。
                    seg, meta = await loop.run_in_executor(None, self.source.next_window)
                else:
                    seg, meta = self.source.next_window()
                if self.finished:
                    break
                # 只复制未处理窗口，绝不在这里做第二次滤波；监测使用原始数组，
                # 处理后数组将在 FocusEngine 实际算完后从 last_debug 读取。
                raw_mon = (self.source.take_monitor_window()
                           if self.source.name in ("hardware", "replay") else None)
                if self.source.name == "heart":
                    # 仅心率模式：不经过 EEG 模型，专注度直接取心率分量。
                    snap = heart.snapshot()
                    if not (snap["valid"] and snap["bpm"] is not None):
                        entry = {"t": round(time.time() - self.created_at, 2),
                                 "raw": None, "focus": None, "valid": False,
                                 "meta": {"source": "heart", "error": "等待心率读数"},
                                 "hr": snap, "focus_fused": None}
                    else:
                        # 仅心率玩法：静息=0.5，放慢呼吸降心率才能拉高专注指数。
                        comp = round(heart.focus_component(snap["bpm"], target_delta=0.0), 3)
                        entry = {"t": round(time.time() - self.created_at, 2),
                                 "raw": comp, "focus": comp, "valid": True,
                                 "meta": meta, "hr": snap,
                                 "hr_focus": comp, "focus_fused": comp}
                    self._publish_frame(entry)
                    await asyncio.sleep(max(0.05, sources.STEP_SEC - (time.time() - t0)))
                    continue
                artifact = meta.get("artifact") if isinstance(meta, dict) else None
                if self.source.name == "manual":
                    raw = meta.get("focus", 0.5)
                    focus = raw
                elif artifact is not None and not artifact.get("usable", True):
                    raw = focus = None
                else:
                    # 去噪模块给出的坏道掩码：被剔除的通道不参与频段平均
                    mask = artifact.get("channel_mask") if artifact else None
                    raw, focus = self.engine.update(
                        seg, meta.get("fs", self.source.fs), channel_mask=mask)

                if focus is None:
                    # 伪迹过重（电极脱落 / 连续眨眼 / 强肌电）：本窗不出分。
                    # 不能把脏窗口写进 history，否则校准基线和报告曲线都会被拉偏。
                    entry = {"t": round(time.time() - self.created_at, 2),
                             "raw": None, "focus": None, "valid": False,
                             "reason": "artifact", "meta": meta,
                             "artifact": artifact, "focus_fused": None,
                             "hr": heart.snapshot()}
                    self._safe_publish_monitor(raw_mon, meta, artifact, None, None, None, entry)
                    self._publish_frame(entry)
                    await asyncio.sleep(max(0.05, sources.STEP_SEC - (time.time() - t0)))
                    continue

                entry = {"t": round(time.time() - self.created_at, 2),
                         "raw": round(float(raw), 3),
                         "focus": round(float(focus), 3),
                         "valid": True,
                         "meta": meta}
                if artifact is not None:
                    entry["artifact"] = artifact
                # 心率是低采样率辅助信号：只在读数新鲜时按权重修正专注分，
                # 过期/未接入时 focus_fused 与纯 EEG 结果完全一致。
                snap = heart.snapshot()
                entry["hr"] = snap
                if snap["valid"] and snap["bpm"] is not None:
                    comp = heart.focus_component(snap["bpm"])
                    w = float(snap["weight"])
                    entry["hr_focus"] = round(comp, 3)
                    entry["focus_fused"] = round((1.0 - w) * float(focus) + w * comp, 3)
                else:
                    entry["focus_fused"] = round(float(focus), 3)
                self._safe_publish_monitor(
                    raw_mon, meta, artifact,
                    getattr(self.engine, "last_debug", None),
                    entry.get("score") if "score" in entry else self.score_of(
                        entry.get("focus_fused") if entry.get("focus_fused") is not None
                        else entry.get("focus")),
                    entry.get("focus_fused"), entry)
                self._publish_frame(entry)
            except Exception as e:  # noqa: BLE001
                if self.finished:
                    break
                entry = {"t": round(time.time() - self.created_at, 2),
                         "raw": None, "focus": None, "valid": False,
                         "meta": {"source": self.source.name, "error": str(e)}}
                self._publish_frame(entry)
            await asyncio.sleep(max(0.05, sources.STEP_SEC - (time.time() - t0)))

    def _safe_publish_monitor(self, *args):
        """监测序列化失败不能影响游戏控制链路；失败只丢弃该监测批次。"""
        try:
            self._publish_monitor(*args)
        except Exception:  # noqa: BLE001
            pass

    def _publish_monitor(self, raw_mon, meta, artifact, debug, score, fused, entry):
        """把当前窗口整理为开发者监测批次；无订阅者时直接返回。"""
        if self.monitor_clients <= 0 or self.source.name not in ("hardware", "replay"):
            return
        sample_meta = dict((raw_mon or {}).get("meta") or {})
        raw = (raw_mon or {}).get("raw")
        if not sample_meta:
            sample_meta = dict((meta or {}).get("monitor") or {})
        if raw is None and self.source.name == "replay":
            # 回放源在 next_window 中已保存原始窗；这里不合成波形。
            return
        if raw is None and debug is None:
            return
        fs = (meta or {}).get("fs") or self.source.fs
        n = int(sample_meta.get("n") or (raw.shape[1] if raw is not None and getattr(raw, "ndim", 0) == 2 else 0))
        if not n:
            return
        if sample_meta.get("t0") is None:
            # 兼容没有逐样本时间戳的旧源：只把窗口终点对齐到当前会话时间，
            # 明确标记为 session_clock，不把浏览器到达时间伪装成硬件时间。
            t1 = float((entry or {}).get("t") or 0.0)
            sample_meta.update({
                "n": n, "fs": fs,
                "t0": max(0.0, t1 - n / float(fs or 1.0)), "t1": t1,
                "time_basis": "session_clock",
                "timestamp_note": "该信号源没有逐样本时间戳；按窗口终点推算",
            })
        processed = debug.get("processed") if debug else None
        self._monitor_seq += 1
        batch = monitor_data.build_batch(
            seq=self._monitor_seq, session_id=self.id,
            source_name=self.source.name, source_desc=self.source.describe(),
            raw=raw, processed=processed, sample_meta=sample_meta,
            artifact=artifact, debug=debug, score=score, fused=fused,
            baseline=self.baseline,
            score_range={"low": self.score_low, "high": self.score_high},
            fs=fs, ch_names=self.source.ch_names or sample_meta.get("ch_names"),
            t_offset=self.created_at,
        )
        batch["calibration"] = {
            "id": self.calibration_id,
            "low": self.score_low,
            "high": self.score_high,
            "status": (self.calibration_snapshot or {}).get("status") or "legacy",
            "reference_baseline_id": self.reference_baseline_id,
            "reference_version": (self.reference_snapshot or {}).get("version"),
            "effective_sec": (self.calibration_snapshot or {}).get("effective_sec"),
            "stage_samples": (self.calibration_snapshot or {}).get("stage_samples"),
            "daily_score": score,
            "reference_score": self.score_reference(fused),
        }
        batch["difficulty"] = self.difficulty_snapshot
        if self.source.name == "replay":
            batch["replay"] = {
                "window": (meta or {}).get("window"),
                "n_windows": (meta or {}).get("n_windows"),
                "progress": (meta or {}).get("progress"),
            }
        self._monitor_latest = batch
        self._monitor_batches.append(batch)
        ready = self._monitor_event
        self._monitor_event = asyncio.Event()
        ready.set()

    def _publish_frame(self, entry):
        self.history.append(entry)
        if len(self.history) > 30000:
            self.history = self.history[-10000:]
        self._latest_frame = entry
        ready = self._frame_ready
        self._frame_ready = asyncio.Event()
        ready.set()

    async def finish(self, score=None, played_sec=None, notes=None, actions=None, demo=False,
                     planned_sec=None):
        if self.finished:
            return self
        self.finished = True
        self._frame_ready.set()
        self._monitor_event.set()
        self.finished_at = time.time()
        # 释放硬件源占用的 UDP 端口，避免下一局 hardware 会话绑定失败
        if self.source.name == "hardware":
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self.source.stop)
            except Exception:  # noqa: BLE001 - 释放失败不影响报告
                pass
        # 报告统计只使用有效帧（异常帧 focus=None/valid=False，不得进入均值与曲线）
        valid = [e for e in self.history if e.get("valid")]
        focuses = [e["focus"] for e in valid]
        raws = [e["raw"] for e in valid]
        fused = [e.get("focus_fused") for e in valid if e.get("focus_fused") is not None]
        scores = [self.score_of(e.get("focus_fused") if e.get("focus_fused") is not None else e.get("focus"))
                  for e in valid]
        scores = [x for x in scores if x is not None]
        reference_scores = [self.score_reference(e.get("focus_fused") if e.get("focus_fused") is not None else e.get("focus"))
                            for e in valid]
        reference_scores = [x for x in reference_scores if x is not None]
        hr_vals = [e["hr"]["bpm"] for e in valid
                   if e.get("hr") and e["hr"].get("valid") and e["hr"].get("bpm") is not None]
        n_invalid = len(self.history) - len(valid)
        dur = self.finished_at - self.created_at
        hr_summary = heart.summary()
        hr_summary["n_frames"] = len(hr_vals)
        hr_summary["coverage"] = round(len(hr_vals) / len(valid), 3) if valid else 0.0
        # v1.8.4：客户端逐轮数据先做边界/一致性检查；异常轮次不参与自动难度。
        data_quality = diagnostics.validate_actions(actions, planned_sec, played_sec)
        if actions:
            actions = dict(actions)
            actions["rounds"] = data_quality["accepted_rounds"]
            actions["incomplete_round"] = data_quality["accepted_incomplete"]
        self.stats = {
            "session_id": self.id,
            "created_at": datetime.fromtimestamp(self.created_at).isoformat(timespec="seconds"),
            "duration_sec": round(dur, 1),
            "played_sec": played_sec,
            "score": score,
            "notes": notes,
            "actions": actions,
            "data_quality": data_quality,
            "demo": demo,
            "purpose": self.purpose,
            "planned_sec": planned_sec,
            "source": self.source.describe(),
            # 去噪/去伪迹的会话级汇总：有效窗占比、眨眼帧占比、参数快照。
            # replay/manual/heart 源没有清洗器，写 None，前端按「未启用」处理。
            "signal_quality": (
                self.source.artifact_summary()
                if hasattr(self.source, "artifact_summary") else None),
            "n_artifact_frames": sum(
                1 for e in self.history if e.get("reason") == "artifact"),
            "baseline": self.baseline,
            "calibration": self.calibration,
            "calibration_status": (self.calibration_snapshot or {}).get("status") or "legacy",
            "n_frames": len(self.history),
            "n_valid_frames": len(valid),
            "n_invalid_frames": n_invalid,
            "valid_signal_ratio": (round(len(valid) / len(self.history), 4)
                                   if self.history else None),
            "focus_mean": round(float(np_mean(focuses)), 3) if focuses else None,
            "focus_max": round(float(max(focuses)), 3) if focuses else None,
            "focus_min": round(float(min(focuses)), 3) if focuses else None,
            "focus_fused_mean": round(float(np_mean(fused)), 3) if fused else None,
            "above_baseline_ratio": (round(float(sum(f >= (self.baseline or 0) for f in focuses)) / len(focuses), 3)
                                      if focuses and self.baseline is not None else None),
            "score_mean": round(float(np_mean(scores)), 1) if scores else None,
            "score_max": round(float(max(scores)), 1) if scores else None,
            "score_min": round(float(min(scores)), 1) if scores else None,
            "above_mid_ratio": (round(float(sum(x >= 50 for x in scores)) / len(scores), 3)
                                if scores else None),
            "score_range": {"low": self.score_low, "high": self.score_high},
            "reference_score_range": {"low": self.reference_low, "high": self.reference_high},
            "reference_score_mean": round(float(np_mean(reference_scores)), 1) if reference_scores else None,
            "reference_score_max": round(float(max(reference_scores)), 1) if reference_scores else None,
            "reference_score_min": round(float(min(reference_scores)), 1) if reference_scores else None,
            "reference_baseline_id": self.reference_baseline_id,
            "device_key": self.config.get("device_key") if isinstance(self.config, dict) else None,
            "calibration_snapshot": self.calibration_snapshot,
            "reference_snapshot": self.reference_snapshot,
            "difficulty_snapshot": self.difficulty_snapshot,
            "assessment_id": self.assessment_id,
            "assessment": self.assessment,
            "heart": hr_summary,
            "hr_curve": heart.curves(self._mono0),
            "curve": [{"t": e["t"], "focus": e["focus"], "raw": e["raw"],
                       "focus_fused": e.get("focus_fused"),
                       "score": self.score_of(e.get("focus_fused")
                                              if e.get("focus_fused") is not None else e.get("focus")),
                       "reference_score": self.score_reference(e.get("focus_fused")
                                              if e.get("focus_fused") is not None else e.get("focus"))}
                      for e in valid[::2]],
        }
        self.stats["user_id"] = self.user_id
        self.stats["calibration_id"] = self.calibration_id
        try:
            metrics = difficulty.compute_metrics(self.stats)
            self.stats["charge_process"] = diagnostics.charge_process(self.stats)
            self.stats["diagnostics"] = diagnostics.diagnose(self.stats, metrics)
        except Exception as exc:  # 诊断不能阻止已经生成的正式报告落库
            self.stats["diagnostics"] = {"items": [], "active": [],
                                         "summary": "诊断计算失败", "error": str(exc),
                                         "engineering_only": True}
            self.stats["charge_process"] = diagnostics.charge_process(self.stats)
        if self._task:
            self._task.cancel()
        return self

    def release(self):
        """释放已完成会话占用的内存；不删除已持久化的报告。"""
        try:
            if self._task:
                self._task.cancel()
        except Exception:
            pass
        try:
            self.source.stop()
        except Exception:
            pass
        self.history.clear()
        self._monitor_batches.clear()
        self._latest_frame = None
        self._monitor_latest = None
        if isinstance(getattr(self.source, "_raw", None), object):
            try:
                self.source._raw = None
            except Exception:
                pass

    def to_public(self):
        return {
            "id": self.id,
            "source": self.source.describe(),
            "baseline": self.baseline,
            "calibration": self.calibration,
            "created_at": self.created_at,
            "user_id": self.user_id,
            "calibration_id": self.calibration_id,
            "purpose": self.purpose,
            "assessment": self.assessment,
            "assessment_id": self.assessment_id,
            "reference_baseline_id": self.reference_baseline_id,
            "calibration_snapshot": self.calibration_snapshot,
            "reference_snapshot": self.reference_snapshot,
            "difficulty": self.difficulty_snapshot,
            "finished": self.finished,
            "monitor_clients": self.monitor_clients,
            "monitor_available": self.source.name in ("hardware", "replay"),
        }


def np_mean(xs):
    import numpy as np
    return np.mean(xs)


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------
class AssessmentConfig(BaseModel):
    protocol_version: str = "standard_v1"
    planned_sec: float = Field(default=90.0, ge=30.0, le=180.0)
    seed: Optional[str] = Field(default=None, max_length=128)
    simulation: bool = False


class SessionCreate(BaseModel):
    mode: str = "replay"          # replay | manual | hardware | heart（仅心率）
    file: Optional[str] = None    # replay 模式下的 EDF 文件路径
    baseline: Optional[float] = None     # 游戏会话沿用校准页算出的个人基线
    osc_host: Optional[str] = None       # hardware: Xmuse OSC 监听地址
    osc_ports: Optional[str] = None      # hardware: 如 "7000,8000"
    osc_fs: Optional[float] = None       # hardware: 采样率（默认 256）
    osc_channels: Optional[int] = None   # hardware: 0=自动
    heart_mode: Optional[str] = None     # 心率源: off | mock | hrd | csv
    heart_rest_bpm: Optional[float] = None   # 静息心率基线（校准页采集）
    heart_weight: Optional[float] = None     # 心率融合权重（0..0.5，默认 0.15）
    score_low: Optional[float] = None        # 校准得到的“最放松”端（对应 20 分）
    score_high: Optional[float] = None       # 校准得到的“最专注”端（对应 80 分）
    user_id: Optional[str] = None            # v1.8.1：档案归属
    calibration_id: Optional[str] = None     # v1.8.1：使用的校准记录
    purpose: str = "game"                   # game | calibration
    device_key: Optional[str] = None        # v1.8.2：设备/信号源指纹
    timezone_offset_min: Optional[int] = None  # v1.8.2：浏览器本地时区偏移
    assessment: Optional[AssessmentConfig] = None  # v1.8.4：标准评估参数


class AssessmentCreate(SessionCreate):
    """独立入口；服务端强制 purpose=assessment。"""
    purpose: str = "assessment"
    protocol_version: str = "standard_v1"
    planned_sec: float = Field(default=90.0, ge=30.0, le=180.0)
    seed: Optional[str] = Field(default=None, max_length=128)
    simulation: bool = False


class HeartStart(BaseModel):
    mode: str = "mock"                   # mock | hrd | csv
    hrd_path: Optional[str] = None
    csv_path: Optional[str] = None
    fps: float = 10.0
    rest_bpm: Optional[float] = None
    weight: Optional[float] = None


class CalibrateStart(BaseModel):
    duration: float = 20.0        # 校准采样秒数（新协议为实际经过秒数）
    video_full: bool = False      # legacy：整段视频当校准
    protocol: str = "legacy"      # v1.8.2：daily_v2；v1.9.4：daily_v3
    stage_windows: Optional[dict] = None
    tutorial_events: list[dict] = Field(default_factory=list)
    # v1.9.4：实际刺激条件与教学元数据，随校准记录保存，不参与计分。
    stimulus_condition: Optional[dict] = None
    teaching: Optional[dict] = None
    device_key: Optional[str] = None
    timezone_offset_min: Optional[int] = None
    elapsed_sec: Optional[float] = None


class ManualSet(BaseModel):
    focus: float = 0.5


class JumpEvent(BaseModel):
    t: float = Field(ge=0, allow_inf_nan=False)
    timed: bool
    award: Optional[NonNegativeInt] = None
    potential: Optional[NonNegativeInt] = None
    multiplier: Optional[float] = Field(default=None, ge=0, le=1)


class RoundRecord(BaseModel):
    """单轮研究数据：只做记录，不参与临床判断。"""
    round: Optional[NonNegativeInt] = None
    charge_sec: Optional[float] = Field(default=None, ge=0)
    eval_sec: Optional[float] = Field(default=None, ge=0)
    difficulty_factor: Optional[float] = Field(default=None, ge=0.6, le=1.2)
    zone_width: Optional[float] = Field(default=None, ge=0, le=100)
    zone_lo: Optional[float] = Field(default=None, ge=0, le=100)
    zone_hi: Optional[float] = Field(default=None, ge=0, le=100)
    t_ref: Optional[float] = Field(default=None, ge=0)
    potential: Optional[NonNegativeInt] = None
    awarded: Optional[NonNegativeInt] = None
    success: Optional[bool] = None
    reaction_sec: Optional[float] = Field(default=None, ge=0)
    # v1.6：点击时机倍率（1=满分宽容期，0=超时/错过）
    multiplier: Optional[float] = Field(default=None, ge=0, le=1)
    mean_score: Optional[float] = Field(default=None, ge=0, le=100)
    above_ratio: Optional[float] = Field(default=None, ge=0, le=1)
    decay_events: Optional[NonNegativeInt] = None
    decay_sec: Optional[float] = Field(default=None, ge=0)
    stale_sec: Optional[float] = Field(default=None, ge=0)
    early_taps: Optional[NonNegativeInt] = None
    cooldown_count: Optional[NonNegativeInt] = None
    cooldown_sec: Optional[float] = Field(default=None, ge=0)
    energy_gain: Optional[float] = Field(default=None, ge=0)
    energy_gain_total: Optional[float] = Field(default=None, ge=0)
    energy_loss: Optional[float] = Field(default=None, ge=0)
    energy_net: Optional[float] = None
    charge_active_sec: Optional[float] = Field(default=None, ge=0)
    below_threshold_sec: Optional[float] = Field(default=None, ge=0)
    stale_sec: Optional[float] = Field(default=None, ge=0)
    bullet_sec: Optional[float] = Field(default=None, ge=0)
    jump_anim_sec: Optional[float] = Field(default=None, ge=0)
    paused_sec: Optional[float] = Field(default=None, ge=0)


class IncompleteRound(BaseModel):
    """本局结束时尚未完成的一轮；只作为观察下限，不伪装成完整蓄力。"""
    round: Optional[NonNegativeInt] = None
    phase: Optional[str] = None
    entered: Optional[bool] = None
    charge_sec: Optional[float] = Field(default=None, ge=0)
    eval_sec: Optional[float] = Field(default=None, ge=0)
    zone_lo: Optional[float] = Field(default=None, ge=0, le=100)
    zone_hi: Optional[float] = Field(default=None, ge=0, le=100)
    energy: Optional[float] = Field(default=None, ge=0, le=100)
    start_energy: Optional[float] = Field(default=None, ge=0, le=100)
    energy_gain: Optional[float] = Field(default=None, ge=0)
    potential: Optional[NonNegativeInt] = None
    cooldown_sec: Optional[float] = Field(default=None, ge=0)
    energy_loss: Optional[float] = Field(default=None, ge=0)
    charge_active_sec: Optional[float] = Field(default=None, ge=0)
    below_threshold_sec: Optional[float] = Field(default=None, ge=0)
    stale_sec: Optional[float] = Field(default=None, ge=0)
    bullet_sec: Optional[float] = Field(default=None, ge=0)
    jump_anim_sec: Optional[float] = Field(default=None, ge=0)
    paused_sec: Optional[float] = Field(default=None, ge=0)
    ended_reason: Optional[str] = None


class GameActions(BaseModel):
    timed_jumps: NonNegativeInt
    automatic_jumps: NonNegativeInt
    targets_shown: Optional[NonNegativeInt] = None
    targets_hit: Optional[NonNegativeInt] = None
    # v1.5：主动完美起跳 / 错过金色区域 / 提前点击，以及逐轮研究数据
    successful_jumps: Optional[NonNegativeInt] = None
    missed_jumps: Optional[NonNegativeInt] = None
    early_taps: Optional[NonNegativeInt] = None
    # v1.6：无效点击冷却汇总
    cooldown_count: Optional[NonNegativeInt] = None
    cooldown_sec: Optional[float] = Field(default=None, ge=0)
    rounds: Optional[list[RoundRecord]] = Field(default=None, max_length=2000)
    incomplete_round: Optional[IncompleteRound] = None
    jumps: Optional[list[JumpEvent]] = Field(default=None, max_length=3600)
    game_process: Optional[dict] = None


class SessionFinish(BaseModel):
    actions: Optional[GameActions] = None
    demo: bool = False
    score: Optional[int] = Field(default=None, ge=0, le=1000000)
    played_sec: Optional[float] = Field(default=None, ge=0, le=7200)
    planned_sec: Optional[float] = Field(default=None, ge=0, le=7200)
    notes: Optional[str] = Field(default=None, max_length=2000)


class ExportRequest(BaseModel):
    """导出时前端把页面上「给家长的话」纯文本一起送来，保证文件与屏幕一致。"""
    parent_note: Optional[str] = Field(default=None, max_length=20000)


class SourceSwitch(BaseModel):
    mode: str = "replay"
    file: Optional[str] = None
    osc_host: Optional[str] = None
    osc_ports: Optional[str] = None
    osc_fs: Optional[float] = None
    osc_channels: Optional[int] = None


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
def _engine_info():
    latest = next(reversed(_sessions.values()), None)
    return (latest.engine if latest else _engine).describe()


@app.get("/api/health")
def health():
    eng = _engine_info()
    return {"status": "ok", "model": eng["model"], "engine_mode": eng["active_mode"],
            "heart": heart.snapshot()}


@app.get("/api/heart/status")
def heart_status():
    snap = heart.snapshot()
    # 顺便给出当前心率分量，便于调试算法（不改变 snapshot 的既有契约）
    snap["hr_focus"] = round(heart.focus_component(), 3) if snap.get("valid") else None
    return snap


@app.get("/api/env")
def env_info():
    """前端据此决定是否渲染心率相关入口。"""
    return {
        "platform": platform.system().lower(),
        "heart_supported": HEART_SUPPORTED,
        "heart_reason": None if HEART_SUPPORTED else HEART_UNSUPPORTED_REASON,
    }


@app.post("/api/heart/start")
def heart_start(body: HeartStart):
    if not HEART_SUPPORTED:
        raise HTTPException(400, HEART_UNSUPPORTED_REASON)
    try:
        snap = heart.start(mode=body.mode, hrd_path=body.hrd_path,
                           csv_path=body.csv_path, fps=body.fps,
                           rest_bpm=body.rest_bpm, weight=body.weight)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"心率源启动失败: {e}")
    return {"ok": True, "heart": snap}


@app.post("/api/heart/stop")
def heart_stop():
    heart.stop()
    return {"ok": True, "heart": heart.snapshot()}


@app.get("/api/player/replay")
def player_replay():
    return {"edf_files": sources.list_edf_files()}


@app.get("/api/player/recent")
def player_recent(request: Request):
    user_id = request.query_params.get("user_id") or request.headers.get("x-user-id")
    if user_id:
        try:
            rows = storage.list_sessions(user_id, 6)
        except StorageError:
            rows = []
        reports = []
        for row in rows:
            report = row.get("report") or {}
            if not report.get("played_sec") or report.get("demo"):
                continue
            reports.append({
                "session_id": row["session_id"],
                "source": row.get("source") or report.get("source") or {},
                "score": row.get("total_score"),
                "played_sec": row.get("played_sec") or report.get("played_sec"),
            })
            if len(reports) == 3:
                break
        return {"reports": reports}
    # 兼容 v1.7 旧页面的未归属历史入口；新流程始终带 user_id。
    reports = []
    files = sorted(Path(SESSIONS_DIR).glob("*.json"), key=os.path.getmtime, reverse=True)
    for path in files:
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not report.get("played_sec") or report.get("demo"):
            continue
        if (report.get("source") or {}).get("name") not in ("hardware", "heart"):
            continue
        reports.append({
            key: report.get(key) for key in ("session_id", "source", "score", "played_sec")
        })
        if len(reports) == 3:
            break
    return {"reports": reports}


@app.get("/api/dev/info")
def dev_info():
    return {
        "engine": _engine_info(),
        "model_report": _read_train_report(),
        "source_config": _source_config,
        "edf_files": sources.list_edf_files(),
        "sessions": {k: v.to_public() for k, v in _sessions.items()},
    }


def _read_train_report():
    p = os.path.join(ROOT, "outputs", "train_report.md")
    if os.path.exists(p):
        return open(p, encoding="utf-8").read()
    return None


@app.post("/api/dev/source")
def dev_switch_source(body: SourceSwitch):
    global _source_config
    if body.mode not in ("replay", "manual", "hardware"):
        raise HTTPException(400, "mode 必须是 replay/manual/hardware")
    _source_config = {
        "mode": body.mode,
        "file": body.file,
        "osc_host": body.osc_host,
        "osc_ports": body.osc_ports,
        "osc_fs": body.osc_fs,
        "osc_channels": body.osc_channels,
    }
    return {"ok": True, "source_config": _source_config}


@app.post("/api/session")
async def create_session(body: SessionCreate):
    _reap_sessions()
    # 非 macOS 没有心率采集实现；纯心率玩法不能改用一段录好的脑电。
    if not HEART_SUPPORTED:
        if body.heart_mode and body.heart_mode != "off":
            body.heart_mode = "off"
        if body.mode == "heart":
            raise HTTPException(400, "当前系统不支持仅心率模式，请连接 Xmuse 使用脑电模式。")
    # 仅心率模式没有脑电信号，必须接一个心率源；未显式指定时默认 AirPods 自动读取。
    if body.mode == "heart" and (not body.heart_mode or body.heart_mode == "off"):
        body.heart_mode = "hrd"
    user_id = (body.user_id or "").strip() or None
    purpose = (body.purpose or "game").strip()
    if purpose not in ("game", "calibration", "assessment"):
        raise HTTPException(400, "purpose 必须是 game、calibration 或 assessment")
    if user_id:
        try:
            storage.ensure_user(user_id)
        except StorageError as exc:
            raise HTTPException(400, str(exc))
    calibration_id = (body.calibration_id or "").strip() or None
    if calibration_id and not user_id:
        raise HTTPException(400, "指定校准记录时必须同时指定 user_id")
    if calibration_id and user_id:
        try:
            if not storage.get_calibration(user_id, calibration_id):
                raise HTTPException(403, "校准记录不属于当前档案")
        except StorageError as exc:
            raise HTTPException(400, str(exc))
    # v1.8.2/v1.8.4：真实 EEG 正式游戏与真实标准评估必须拥有当天有效校准。
    # 校准会话本身不拦截；测试/回放/手动/仅心率也不被这条规则误伤。
    daily = None
    dev_key = body.device_key or calib_engine.device_key(body.mode, {
        "osc_ports": body.osc_ports, "osc_fs": body.osc_fs, "osc_channels": body.osc_channels,
    })
    is_assessment = purpose == "assessment"
    assessment_cfg = (body.assessment.model_dump() if body.assessment
                      else {"protocol_version": "standard_v1", "planned_sec": 90.0,
                            "seed": None, "simulation": body.mode != "hardware"})
    assessment_id = None
    reference_for_assessment = None
    if is_assessment:
        # 标准评估只允许固定难度与固定协议；随机种子由服务端生成/回显。
        if body.mode == "hardware":
            if not user_id:
                raise HTTPException(400, "真实硬件标准评估必须指定 user_id")
            reference_for_assessment = storage.reference_baseline(user_id)
            if not reference_for_assessment:
                raise HTTPException(409, "assessment_reference_required: 缺少长期参考基线，不能生成可纵向比较的结果")
            ref_device = reference_for_assessment.get("device_key")
            if ref_device and dev_key and str(ref_device) != str(dev_key):
                raise HTTPException(409, "assessment_reference_incompatible: 长期参考基线与当前设备不匹配")
            # 校准/算法兼容性在 daily 查询后再次检查，避免把不兼容结果标成可纵向比较。
        assessment_cfg["simulation"] = bool(assessment_cfg.get("simulation")
                                            or body.mode != "hardware")
        # v1.9.4：起始蓄力从 15% 改为 10%，标准评估的玩法参数随之变化。
        # 服务端盖章，避免客户端旧缓存把不同任务参数误标为同一条件。
        assessment_cfg["game_params_version"] = difficulty.PARAMS_VERSION
        assessment_cfg["start_energy"] = difficulty.CONFIG["start_energy"]
        assessment_cfg["seed"] = assessment_cfg.get("seed") or uuid.uuid4().hex[:12]
        assessment_id = "asm_" + uuid.uuid4().hex[:12]
    if user_id and purpose in ("game", "assessment") and body.mode == "hardware":
        daily = storage.calibration_status(user_id, mode=body.mode, device=dev_key,
                                            tz_offset_min=body.timezone_offset_min)
        if not daily.get("valid"):
            raise HTTPException(
                409,
                "daily_calibration_required: " + str(daily.get("status_text") or "今日尚未校准"),
            )
        calibration_id = (daily.get("calibration") or {}).get("id") or calibration_id
    if is_assessment and body.mode == "hardware" and reference_for_assessment:
        ref_algo = reference_for_assessment.get("algorithm_version")
        cal_algo = (daily.get("calibration") or {}).get("algorithm_version") if daily else None
        if ref_algo and cal_algo and str(ref_algo) != str(cal_algo):
            raise HTTPException(409, "assessment_reference_incompatible: 长期参考基线与当前算法不匹配")
    config = {
        "mode": body.mode,
        "file": body.file,
        "osc_host": body.osc_host,
        "osc_ports": body.osc_ports,
        "osc_fs": body.osc_fs,
        "osc_channels": body.osc_channels,
        "user_id": user_id,
        "calibration_id": calibration_id,
        "purpose": purpose,
        "assessment": assessment_cfg if is_assessment else None,
        "assessment_id": assessment_id,
        "device_key": dev_key,
        "timezone_offset_min": body.timezone_offset_min,
    }
    # 心率源：会话请求里声明了就自动接入；同一模式已在运行则复用，保留已采集样本。
    if body.heart_mode and body.heart_mode != "off":
        cur = heart.snapshot()
        try:
            # 模式相同但抓取线程已退出（例如 hrd 找不到窗口）时也要重启，否则新会话拿不到心率。
            if cur["mode"] != body.heart_mode or not cur.get("running"):
                heart.start(mode=body.heart_mode,
                            rest_bpm=body.heart_rest_bpm,
                            weight=body.heart_weight)
            else:
                if body.heart_rest_bpm is not None:
                    heart.set_rest(body.heart_rest_bpm)
                if body.heart_weight is not None:
                    heart.set_weight(body.heart_weight)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"心率源启动失败: {e}")
    try:
        # 兜底：同一时间只保留一个硬件会话，避免新旧会话争抢 UDP 7000/8000。
        # 正常流程校准页会先 finish 旧会话；这里防止前端异常/直接刷新导致端口占用。
        if config["mode"] == "hardware":
            for old in list(_sessions.values()):
                if old.source.name == "hardware" and not old.finished:
                    try:
                        await old.finish(notes="replaced-by-new-hardware-session")
                    except Exception:  # noqa: BLE001
                        pass
        source = sources.create_source(config)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"信号源创建失败: {e}")
    s = Session(source, config)
    # v1.8.3：真实硬件正式游戏在创建时锁定难度；测试/回放/手动仍用 1.00，
    # 并且结算时不会写入真实儿童难度档案。
    if user_id and purpose == "game" and body.mode == "hardware":
        try:
            s.apply_difficulty(storage.begin_difficulty_session(
                user_id, calibration_id=calibration_id, device_key=dev_key))
        except StorageError as exc:
            raise HTTPException(500, f"读取难度档案失败：{exc}")
    # 游戏会话使用服务端当日校准记录，而不是信任前端缓存里的旧区间。
    if user_id and purpose in ("game", "assessment"):
        try:
            cal = (daily or {}).get("calibration") if daily else None
            if not cal and calibration_id:
                cal = storage.get_calibration(user_id, calibration_id)
            if cal:
                ref_to_apply = (reference_for_assessment if is_assessment and reference_for_assessment
                                else storage.reference_baseline(user_id))
                s.apply_calibration(cal, ref_to_apply)
        except StorageError:
            pass
    elif user_id and purpose == "calibration":
        s.calibration_id = None
    # 否则报告页拿不到基线，橙色虚线与"高于基线占比"都会是空值。
    if body.baseline is not None and not s.calibration_snapshot:
        try:
            b = float(body.baseline)
        except (TypeError, ValueError):
            b = None
        if b is not None and 0.0 <= b <= 1.0:
            s.baseline = round(b, 3)
    # 旧前端兼容：没有服务端校准时才使用前端区间；有校准记录时已固定为记录值。
    if not s.calibration_snapshot:
        try:
            lo = float(body.score_low) if body.score_low is not None else None
            hi = float(body.score_high) if body.score_high is not None else None
        except (TypeError, ValueError):
            lo = hi = None
        if lo is not None and hi is not None and 0.0 <= lo < hi <= 1.0:
            s.score_low, s.score_high = round(lo, 3), round(hi, 3)
            if body.baseline is None:
                s.baseline = s.raw50()
    _sessions[s.id] = s
    try:
        await s.start()
        if is_assessment:
            row = storage.create_assessment(
                user_id, s.id, protocol_version=str(assessment_cfg.get("protocol_version") or "standard_v1"),
                planned_sec=float(assessment_cfg.get("planned_sec") or 90),
                seed=assessment_cfg.get("seed"), simulation=bool(assessment_cfg.get("simulation")),
                calibration_id=s.calibration_id,
                reference_baseline_id=getattr(s, "reference_baseline_id", None),
                device={"device_key": dev_key, "mode": body.mode,
                        "source": source.describe(), "osc_ports": body.osc_ports,
                        "osc_fs": body.osc_fs, "osc_channels": body.osc_channels},
                params={"difficulty": s.difficulty_snapshot, "protocol": assessment_cfg,
                        "game": {"params_version": difficulty.PARAMS_VERSION,
                                 "start_energy": difficulty.CONFIG["start_energy"]}},
            )
            s.assessment_id = row["assessment_id"]
            s.assessment = dict(assessment_cfg)
            assessment_id = row["assessment_id"]
    except StorageError as e:
        try:
            await s.finish(notes="assessment-record-failed")
        except Exception:
            pass
        _sessions.pop(s.id, None)
        raise HTTPException(500, f"标准评估记录创建失败：{e}")
    except Exception as e:  # noqa: BLE001 - 端口占用/依赖缺失时给出可读错误
        _sessions.pop(s.id, None)
        raise HTTPException(400, f"信号源启动失败: {e}")
    return {"session_id": s.id, "source": source.describe(),
            "difficulty": s.difficulty_snapshot, "assessment_id": assessment_id,
            "assessment": s.assessment if is_assessment else None}


@app.post("/api/assessments")
async def create_assessment(body: AssessmentCreate):
    """标准评估入口：固定 1.00、固定协议、隔离奖励与个人难度。"""
    body.purpose = "assessment"
    if body.assessment is None:
        body.assessment = AssessmentConfig(
            protocol_version=body.protocol_version,
            planned_sec=body.planned_sec,
            seed=body.seed,
            simulation=body.simulation,
        )
    return await create_session(body)


@app.get("/api/assessments")
def list_assessments(user_id: Optional[str] = Query(None), limit: int = Query(20, ge=1, le=100)):
    if not user_id:
        raise HTTPException(400, "列出评估必须指定 user_id")
    try:
        return {"assessments": storage.assessments(user_id, limit)}
    except StorageError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/assessments/{assessment_id}")
def get_assessment(assessment_id: str, user_id: Optional[str] = Query(None)):
    if not user_id:
        raise HTTPException(400, "读取评估必须指定 user_id")
    try:
        item = storage.assessment(assessment_id, user_id)
    except StorageError as exc:
        raise HTTPException(403, str(exc))
    if not item:
        raise HTTPException(404, "评估记录不存在")
    return {"assessment": item}


@app.post("/api/session/{sid}/manual")
def set_manual(sid: str, body: ManualSet, x_user_id: Optional[str] = Header(None, alias="X-User-Id")):
    s = _session_for(sid, x_user_id)
    if s.source.name != "manual":
        raise HTTPException(400, "当前会话不是手动模拟模式")
    s.source.set_focus(body.focus)
    return {"ok": True}


@app.post("/api/session/{sid}/calibrate")
async def calibrate(sid: str, body: CalibrateStart,
                    x_user_id: Optional[str] = Header(None, alias="X-User-Id")):
    s = _session_for(sid, x_user_id)
    if s.purpose != "calibration":
        raise HTTPException(409, "正式游戏期间禁止重新校准；请结束本局后重新校准")
    duration = max(3.0, min(float(body.duration), 600.0))
    t_start = time.time()
    # 采样窗口从会话创建时开始计时：前端倒计时结束（t>=duration）后才发起请求，
    # 这里只补足尚未采满的剩余时间，避免再等满整个 duration 造成长时间空档。
    remaining = duration - (time.time() - s.created_at)
    if remaining > 0 and not s.finished:
        await asyncio.sleep(min(remaining, duration))

    # v1.8.2：自然观察 + 游戏教学两阶段。阶段边界由儿童端上报，但有效样本、
    # 有效秒数和统计均由服务端按历史帧重新计算，不能只信页面停留时间。
    if body.protocol == calib_engine.PROTOCOL_VERSION and body.stage_windows:
        windows = body.stage_windows or {}
        try:
            nw = windows.get("natural") or {}
            tw = windows.get("tutorial") or {}
            n0, n1 = float(nw["start"]), float(nw["end"])
            t0, t1 = float(tw["start"]), float(tw["end"])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(422, "校准阶段窗口不完整")
        if not (0 <= n0 < n1 <= t0 < t1):
            raise HTTPException(422, "校准阶段窗口顺序不合法")
        if t1 - n0 > 180:
            raise HTTPException(422, "校准阶段总时长过长")
        natural = [e for e in s.history if n0 <= float(e.get("t") or 0) < n1]
        tutorial = [e for e in s.history if t0 <= float(e.get("t") or 0) < t1]
        sq = s.source.artifact_summary() if hasattr(s.source, "artifact_summary") else None
        try:
            computed = calib_engine.compute_daily_range(natural, tutorial, signal_quality=sq)
        except calib_engine.CalibrationDataError as exc:
            raise HTTPException(422, str(exc))
        actual_elapsed = max(float(body.elapsed_sec or 0), time.time() - s.created_at)
        stages = computed["stages"]
        status = computed["range_quality"]
        # v1.9.4：把实际刺激条件与教学操作一并记录。它们是上下文，不是“已证实专注”
        # 的证据，也不进入任何计分或难度计算。
        stimulus = body.stimulus_condition or dict(calib_engine.STIMULUS_CONDITION)
        tutorial_events = list(body.tutorial_events or [])[:200]
        teaching = body.teaching or {
            "mode": "preset_demo_then_guided_charge",
            "confirmation_button": "确认跳跃",
            "events": len(tutorial_events),
        }
        result = {
            **computed,
            "stimulus_condition": stimulus,
            "teaching": teaching,
            "tutorial_events": tutorial_events,
            "duration_sec": round(min(actual_elapsed, 600.0), 1),
            "elapsed_sec": round(min(actual_elapsed, 600.0), 1),
            "n_frames": computed.get("n_total_valid") or 0,
            "baseline": round((computed["range"]["low"] + computed["range"]["high"]) / 2.0, 4),
            "stage_effective_sec": {k: stages[k]["effective_sec"] for k in stages},
            "stage_samples": {k: stages[k]["n"] for k in stages},
            "signal_quality": sq,
            "status": status,
            "quality_warning": status != "ok",
            "uses_fused": True,
            "heart_only": s.source.name == "heart",
            "source_name": s.source.name,
            "device_key": body.device_key or calib_engine.device_key(
                s.source.name, s.source.describe()),
            "timezone_offset_min": body.timezone_offset_min,
        }
        s.score_low = computed["range"]["low"]
        s.score_high = computed["range"]["high"]
        s.baseline = result["baseline"]
        s.calibration = result
        s.calibration_snapshot = result
        s.calibration_id = None
        reference = None
        if s.user_id:
            try:
                # source_info 是设备/记录上下文；把刺激条件与教学事件附在这里，
                # 避免为了新增元数据改动 Schema 4 的列结构。
                source_info = dict(s.source.describe() or {})
                source_info["stimulus_condition"] = stimulus
                source_info["tutorial_events"] = tutorial_events
                source_info["teaching"] = teaching
                saved_cal = storage.add_calibration(
                    s.user_id,
                    {
                        **result,
                        "calibrated_at_ms": int(time.time() * 1000),
                        "algorithm_version": "focus_engine_v1.8.2",
                        "status": status,
                        "kind": "daily" if s.source.name == "hardware" else "test",
                    },
                    session_id=s.id,
                    source=source_info,
                    kind="daily" if s.source.name == "hardware" else "test",
                )
                s.calibration_id = saved_cal["id"]
                s.calibration["calibration_id"] = saved_cal["id"]
                s.calibration_snapshot = saved_cal
                result["calibration_id"] = saved_cal["id"]
                result["calibration_date"] = saved_cal.get("calibration_date")
                result["device_key"] = saved_cal.get("device_key") or result.get("device_key")
                result["reference_baseline_id"] = saved_cal.get("reference_baseline_id")
                if s.source.name == "hardware":
                    reference = storage.reference_baseline(s.user_id)
                    s.reference_baseline_id = saved_cal.get("reference_baseline_id") or (
                        reference or {}).get("id")
                    s.reference_snapshot = reference
                    if reference and reference.get("protocol_version") and (
                            reference["protocol_version"] != calib_engine.PROTOCOL_VERSION):
                        # 旧协议长期参考保留，不覆盖、不混算；仅提示可以建立新版参考。
                        result["reference_compat"] = {
                            "compatible": False,
                            "reference_protocol": reference["protocol_version"],
                            "current_protocol": calib_engine.PROTOCOL_VERSION,
                            "note": "长期参考来自旧版校准协议，已保留但不会与本次校准混算。",
                        }
            except StorageError as exc:
                raise HTTPException(500, f"校准记录保存失败：{exc}")
        return {"ok": True, "baseline": s.baseline, "calibration": result,
                "score_range": computed["range"], "stages": stages,
                "effective_sec": computed["effective_sec"], "status": status,
                "calibration_id": s.calibration_id,
                "reference_baseline": reference,
                "signal_quality": sq}

    # 取校准期间产生的有效帧（异常帧不含 focus，须排除；frames 按时间 t 递增）
    frames = [e for e in s.history
              if e["t"] <= duration + 0.5 and e.get("valid", True) and e["focus"] is not None]
    # 仅心率模式：心率更新稀疏，20 秒内可能还没写入历史帧，用当前读数兜底，
    # 否则校准会直接失败（纯心率玩法没有脑电帧可以等）。
    if not frames and s.source.name == "heart":
        snap = heart.snapshot()
        if snap["valid"] and snap["bpm"] is not None:
            comp = round(heart.focus_component(snap["bpm"], target_delta=0.0), 3)
            frames = [{"t": 0.0, "raw": comp, "focus": comp, "valid": True}]
    if not frames:
        raise HTTPException(500, "校准期间未采集到足够信号帧")
    # 心率样本：仅心率模式的分数直接依赖 rest_bpm，必须先定 rest 再算基线。
    hr_sum = heart.summary()
    hr_sum["used_as_rest"] = False
    if hr_sum.get("n", 0) >= 3:
        heart.set_rest(hr_sum["mean"])
        hr_sum["used_as_rest"] = True
        if s.source.name == "heart":
            # 用新的静息心率重算已记录帧（frames 与 s.history 是同一批对象引用），
            # 否则基线来自旧 rest、游戏来自新 rest，两者对不上。
            for e in frames:
                bpm = (e.get("hr") or {}).get("bpm")
                if bpm is None:
                    continue
                c = round(heart.focus_component(bpm, target_delta=0.0), 3)
                e["focus"] = c
                e["raw"] = c
                e["focus_fused"] = c

    n = len(frames)
    raws = [e["raw"] for e in frames if e["raw"] is not None]
    # ---- 动态定标：把“最放松”定为 20 分、“最专注”定为 80 分 ----
    # 校准分两段：前半段闭眼放松，后半段心算任务。放松段取偏低分位当低端、
    # 任务段取偏高分位当高端，分数随这个人自己的动态范围走，而不是所有人套同一个基线。
    half_t = duration / 2.0
    MIN_SPAN = float(calib_engine.CONFIG["min_span"])

    def _pick(vals, p):
        if len(vals) < 3:
            return None
        vals = sorted(vals)
        i = min(len(vals) - 1, max(0, int(round(len(vals) * p))))
        return float(vals[i])

    # 定标输入优先用融合分：心率新鲜时它已按权重修正，纯心率模式下本身就等于心率值，
    # 所以同一套 20/80 逻辑对脑电和心跳都成立，不需要两套阈值。
    def _val(e):
        v = e.get("focus_fused")
        return float(v) if v is not None else float(e["focus"])

    vals_all = [_val(e) for e in frames]
    relax = [_val(e) for e in frames if e["t"] < half_t]
    task = [_val(e) for e in frames if e["t"] >= half_t]

    if body.video_full or duration >= 60:
        # 整段视频当校准：视频自带引导，不假设“前半放松、后半心算”，
        # 直接取全程分位作为“相对最放松 / 相对最专注”两端。
        low = _pick(vals_all, 0.15)
        high = _pick(vals_all, 0.85)
        range_mode = "video_full"
    else:
        low = _pick(relax, 0.3)
        high = _pick(task, 0.7)
        range_mode = "two_phase"

    if low is None or high is None:
        low = _pick(vals_all, 0.1)
        high = _pick(vals_all, 0.9)

    # quality 与 mode 分开记：mode 说“怎么分段”，quality 说“这个区间可不可信”
    range_quality = "ok"
    if low is None or high is None:
        low, high = 0.35, 0.75
        range_mode = "default"
        range_quality = "default"
    elif high - low < MIN_SPAN:
        # 区分度不足（视频太平/一直放松）：再拉一次全窗分位，并标记需要重做校准
        low = _pick(vals_all, 0.1)
        high = _pick(vals_all, 0.9)
        range_quality = "stretched"
    # 最小跨度保护：区间太窄（例如模型输出挤在 0–0.08）时，60 分的映射会把噪声
    # 放大成每次呼吸都跳十几分，分数就没意义了。这里围绕中点扩到至少 MIN_SPAN。
    low = max(0.0, min(0.9, low))
    high = min(1.0, max(low, high))
    if high - low < MIN_SPAN:
        mid = (low + high) / 2.0
        low = max(0.0, mid - MIN_SPAN / 2.0)
        high = min(1.0, low + MIN_SPAN)
        if high - low < MIN_SPAN:
            low = max(0.0, high - MIN_SPAN)

    s.score_low = round(low, 3)
    s.score_high = round(high, 3)
    s.baseline = s.raw50()
    s.baseline_quantiles = {"q10": round(low, 3), "q50": s.baseline, "q90": round(high, 3)}
    s.calibration = {
        "duration_sec": round(duration, 1),
        "n_frames": n,
        "baseline": s.baseline,
        "focus_mean": round(float(np_mean(raws)), 3) if raws else None,
        "quantiles": s.baseline_quantiles,
        "range": {"low": s.score_low, "high": s.score_high},
        "relax_focus": round(float(np_mean(relax)), 3) if relax else None,
        "task_focus": round(float(np_mean(task)), 3) if task else None,
        "range_mode": range_mode,
        "range_quality": range_quality,
        "uses_fused": True,
        "heart_frames": sum(1 for e in frames if e.get("hr")),
        "heart_only": s.source.name == "heart",
    }
    # 校准期间的去噪质量：把"这组基线是在什么信号质量下算出来的"一并留在结果里，
    # 报告页与前端据此提示"这次校准信号不稳，建议重做"。
    sq = (s.source.artifact_summary()
          if hasattr(s.source, "artifact_summary") else None)
    if sq:
        s.calibration["signal_quality"] = sq
        if sq.get("usable_ratio", 1.0) < 0.6:
            s.calibration["quality_warning"] = True
    # 用校准期的心率跨度校准倒 U 尺度：跨度越小，说明这个人对任务的心率反应越平
    hr_bpms = [e["hr"]["bpm"] for e in frames if e.get("hr") and e["hr"].get("bpm")]
    if len(hr_bpms) >= 4:
        ordered = sorted(hr_bpms)
        lo_bpm = ordered[int(len(ordered) * 0.1)]
        hi_bpm = ordered[int(len(ordered) * 0.9)]
        heart.set_span(max(6.0, hi_bpm - lo_bpm))

    # v1.8.1：每次校准追加一条记录，旧记录永不覆盖。开发者测试会话也可能
    # 没有 user_id，这种情况保留旧前端缓存行为，不写入个人档案。
    if s.user_id:
        try:
            saved_cal = storage.add_calibration(
                s.user_id,
                {
                    **s.calibration,
                    "calibrated_at_ms": int(time.time() * 1000),
                    "algorithm_version": "focus_engine_v1.8.1",
                },
                session_id=s.id,
                source=s.source.describe(),
            )
            s.calibration_id = saved_cal["id"]
            s.calibration["calibration_id"] = saved_cal["id"]
        except StorageError as exc:
            raise HTTPException(500, f"校准记录保存失败：{exc}")

    return {"ok": True, "baseline": s.baseline, "calibration": s.calibration,
            "score_range": {"low": s.score_low, "high": s.score_high},
            "heart": hr_sum,
            "signal_quality": sq,
            "calibration_id": s.calibration_id,
            "hr_span": round(heart._hr_span, 2)}


@app.get("/api/session/{sid}/stream")
async def stream(sid: str, request: Request):
    user_id = request.query_params.get("user_id") or request.headers.get("x-user-id")
    s = _session_for(sid, user_id)
    async def gen():
        yield {"event": "hello", "data": json.dumps({"session_id": s.id,
                                                      "source": s.source.describe(),
                                                      "baseline": s.baseline,
                                                      "purpose": s.purpose,
                                                      "calibration_id": s.calibration_id,
                                                      "reference_baseline_id": s.reference_baseline_id,
                                                      "difficulty": s.difficulty_snapshot})}
        last_frame = None
        while not s.finished:
            entry = s._latest_frame
            if entry is last_frame:
                await s._frame_ready.wait()
                continue
            last_frame = entry
            payload = dict(entry)
            payload["baseline"] = s.baseline
            payload["calibration"] = s.calibration
            payload["score"] = s.score_of(
                payload.get("focus_fused") if payload.get("focus_fused") is not None else payload.get("focus"))
            # 监测曲线需要同一条真实链路的前/后分数：原始模型输出与 EMA 平滑输出，
            # 都走同一个 score_of，不在前端重新映射。
            payload["score_raw"] = s.score_of(payload.get("raw"))
            payload["score_smooth"] = s.score_of(payload.get("focus"))
            payload["score_low"] = s.score_low
            payload["score_high"] = s.score_high
            payload["daily_score"] = payload["score"]
            payload["reference_score"] = s.score_reference(
                payload.get("focus_fused") if payload.get("focus_fused") is not None else payload.get("focus"))
            payload["calibration_id"] = s.calibration_id
            payload["calibration_status"] = (s.calibration_snapshot or {}).get("status") or "legacy"
            payload["reference_baseline_id"] = s.reference_baseline_id
            payload["reference_version"] = (s.reference_snapshot or {}).get("version")
            payload["difficulty"] = s.difficulty_snapshot
            yield {"event": "frame", "data": json.dumps(payload)}
        yield {"event": "end", "data": json.dumps({"session_id": s.id})}

    return EventSourceResponse(gen())


@app.get("/api/session/{sid}/monitor")
async def monitor_stream(sid: str, request: Request):
    """开发者高频监测流：与游戏分数 SSE 分离，避免波形阻塞控制帧。

    只有该端点被订阅时才捕获/序列化窗口；儿童模式不会请求它。
    数据只保存在内存中的有限队列里，不新增原始脑电持久化。
    """
    user_id = request.query_params.get("user_id") or request.headers.get("x-user-id")
    s = _session_for(sid, user_id)
    available = s.source.name in ("hardware", "replay")
    s.monitor_clients += 1

    async def gen():
        seen = -1
        try:
            yield {"event": "hello", "data": json.dumps({
                "session_id": s.id,
                "available": available,
                "source": s.source.describe(),
                "source_name": s.source.name,
                "fs": s.source.fs,
                "ch_names": list(s.source.ch_names or []),
                "sample_rate_note": (
                    "Xmuse OSC 未携带采样率，使用配置值；不是实测值"
                    if s.source.name == "hardware"
                    else ("EDF 文件采样率" if s.source.name == "replay"
                          else "当前模式无脑电采样")),
                "time_basis": (
                    "device_packet_arrival" if s.source.name == "hardware"
                    else ("edf_file" if s.source.name == "replay" else "session_clock")),
                "monitor_history_batches": len(s._monitor_batches),
            })}
            if not available:
                yield {"event": "unavailable", "data": json.dumps({
                    "reason": "当前信号源没有脑电采样数据",
                    "source_name": s.source.name,
                })}
            # 补发最近几批，方便刷新页面后立即看到上下文；客户端按 seq 去重。
            for batch in list(s._monitor_batches):
                seen = max(seen, int(batch["seq"]))
                yield {"event": "monitor", "id": str(batch["seq"]),
                       "data": json.dumps(batch, ensure_ascii=False)}
            while not s.finished:
                batch = s._monitor_latest
                if batch is not None and int(batch["seq"]) != seen:
                    seen = int(batch["seq"])
                    yield {"event": "monitor", "id": str(batch["seq"]),
                           "data": json.dumps(batch, ensure_ascii=False)}
                    continue
                event = s._monitor_event
                try:
                    await asyncio.wait_for(event.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    pass
            yield {"event": "end", "data": json.dumps({"session_id": s.id})}
        finally:
            s.monitor_clients = max(0, s.monitor_clients - 1)

    return EventSourceResponse(gen())


@app.post("/api/session/{sid}/finish")
async def finish_session(sid: str, body: SessionFinish,
                         x_user_id: Optional[str] = Header(None, alias="X-User-Id")):
    s = _session_for(sid, x_user_id)
    await s.finish(
        score=body.score, played_sec=body.played_sec, notes=body.notes,
        actions=body.actions.model_dump(exclude_none=True) if body.actions else None,
        demo=body.demo, planned_sec=body.planned_sec,
    )
    wallet = None
    earned = 0
    difficulty_result = {"applied": False, "reason": "no_user"}
    assessment_result = None
    try:
        saved = storage.persist_session(
            s.stats, user_id=s.user_id, calibration_id=s.calibration_id,
        )
        wallet, earned = saved.get("wallet"), saved.get("earned_points", 0)
        # 标准评估不写个人难度、不发商城积分；只完成独立评估记录。
        if s.purpose == "assessment":
            assessment_result = storage.complete_assessment(s.id, s.stats)
            difficulty_result = {"applied": False, "reason": "assessment_isolated"}
        else:
            # 只有报告成功落库后才评估下一局；record_difficulty 以 session_id 幂等。
            difficulty_result = storage.record_difficulty(s.stats, s.user_id)
    except StorageError as exc:
        # 游戏结果已经生成；明确报错，不静默假装已经结算。
        raise HTTPException(500, f"本局记录保存失败：{exc}")
    # 兼容旧版本的 outputs/sessions 仅供本地旧报告迁移读取；新报告以 SQLite 为主。
    # 不再重复写入仓库目录，避免个人数据出现在源码工作区。
    return {"ok": True, "report": s.stats, "wallet": wallet, "earned_points": earned,
            "user_id": s.user_id, "difficulty": difficulty_result,
            "assessment": assessment_result}


@app.get("/api/report/{sid}")
def get_report(sid: str, request: Request):
    user_id = request.query_params.get("user_id") or request.headers.get("x-user-id")
    return _load_report(sid, user_id)


# ---------------------------------------------------------------------------
# 报告导出：PDF / Excel / Word / CSV / JSON + 分享链接
# ---------------------------------------------------------------------------
def _load_report(sid: str, user_id: Optional[str] = None) -> dict:
    """优先读 SQLite 已完成记录；会话被 TTL 回收后仍可读取。"""
    try:
        stored = storage.load_report(sid, user_id)
    except StorageError as exc:
        raise HTTPException(403, str(exc))
    if stored:
        return stored
    s = _sessions.get(sid)
    if s and s.finished:
        _check_report_owner(s.stats, user_id)
        return s.stats
    # 旧版本 outputs/sessions 仅作兼容；新报告不会写入这里。
    p = os.path.join(SESSIONS_DIR, f"{sid}.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            report = json.load(f)
        _check_report_owner(report, user_id)
        return report
    raise HTTPException(404, "报告不存在或会话未结束")


async def _export_response(sid: str, fmt: str, body: Optional[ExportRequest],
                           user_id: Optional[str] = None):
    report = _load_report(sid, user_id)
    parent_note = body.parent_note if body else None
    try:
        payload, filename, media_type = report_export.export_report(report, fmt, parent_note)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except report_export.ExportUnavailable as exc:
        raise HTTPException(501, str(exc))
    except Exception as exc:  # noqa: BLE001 - 导出失败要给出可读原因，不返回 500 空响应
        raise HTTPException(500, f"导出 {fmt.upper()} 失败：{exc}")
    headers = {"Content-Disposition": report_export.content_disposition(filename)}
    return Response(content=payload, media_type=media_type, headers=headers)


@app.get("/api/report/{sid}/export/{fmt}")
async def export_report_get(sid: str, fmt: str, request: Request):
    user_id = request.query_params.get("user_id") or request.headers.get("x-user-id")
    return await _export_response(sid, fmt, None, user_id)


@app.post("/api/report/{sid}/export/{fmt}")
async def export_report_post(sid: str, fmt: str, request: Request,
                             body: Optional[ExportRequest] = None):
    user_id = request.query_params.get("user_id") or request.headers.get("x-user-id")
    return await _export_response(sid, fmt, body, user_id)


# ---------------------------------------------------------------------------
# 背景音乐（网易云歌单代理）
# ---------------------------------------------------------------------------
@app.get("/api/music/playlist")
def music_playlist(refresh: bool = False):
    """歌单曲目列表（按歌单顺序），带登录 cookie 时返回全量曲目。"""
    try:
        return music.playlist(refresh=refresh)
    except Exception as e:
        raise HTTPException(502, f"歌单获取失败：{e}")


@app.get("/api/music/url/{track_id}")
def music_track_url(track_id: str):
    """取单曲播放直链（服务端缓存，直链本身有时效）。"""
    try:
        return music.url_for(track_id)
    except Exception as e:
        raise HTTPException(502, str(e))


def _iso_seconds(value):
    try:
        return datetime.fromtimestamp(float(value)).astimezone().isoformat(timespec="seconds")
    except (TypeError, ValueError, OSError):
        return None


def _small_report(report: Optional[dict]) -> Optional[dict]:
    if not report:
        return None
    metrics = {}
    try:
        metrics = difficulty.compute_metrics(report)
    except Exception:
        pass
    diag = report.get("diagnostics") or diagnostics.diagnose(report, metrics)
    return {
        "session_id": report.get("session_id"),
        "user_id": report.get("user_id"),
        "created_at": report.get("created_at"),
        "purpose": report.get("purpose") or "game",
        "assessment_id": report.get("assessment_id"),
        "planned_sec": report.get("planned_sec"),
        "played_sec": report.get("played_sec"),
        "duration_sec": report.get("duration_sec"),
        "score": report.get("score"),
        "demo": report.get("demo"),
        "source": report.get("source"),
        "score_mean": report.get("score_mean"),
        "above_mid_ratio": report.get("above_mid_ratio"),
        "valid_signal_ratio": report.get("valid_signal_ratio"),
        "metrics": metrics,
        "charge_process": report.get("charge_process") or diagnostics.charge_process(report),
        "diagnostics": diag,
        "difficulty_snapshot": report.get("difficulty_snapshot"),
        "data_quality": report.get("data_quality"),
        "calibration_id": report.get("calibration_id"),
        "reference_baseline_id": report.get("reference_baseline_id"),
        "assessment": report.get("assessment"),
    }


def _assessment_eligibility(user_id: Optional[str], mode: str, device: Optional[str],
                            tz_offset_min: Optional[int] = None, simulation: bool = False) -> dict:
    reasons = []
    comparable = False
    daily = None
    reference = None
    if not user_id:
        reasons.append("未选择个人档案")
    if mode != "hardware":
        reasons.append("当前不是真实硬件 EEG；只能生成明确标记的模拟评估")
        simulation = True
    if user_id:
        try:
            daily = storage.calibration_status(user_id, mode=mode, device=device,
                                                tz_offset_min=tz_offset_min)
            reference = storage.reference_baseline(user_id)
        except StorageError as exc:
            reasons.append(str(exc))
    if mode == "hardware" and user_id:
        if not daily or not daily.get("valid"):
            reasons.append("缺少当日有效校准")
        if not reference:
            reasons.append("缺少长期参考基线")
        elif device and reference.get("device_key") and str(reference["device_key"]) != str(device):
            reasons.append("长期参考基线与当前设备不匹配")
        elif daily and reference.get("algorithm_version"):
            cal = daily.get("calibration") or {}
            if cal.get("algorithm_version") and cal["algorithm_version"] != reference["algorithm_version"]:
                reasons.append("长期参考基线与当前算法不匹配")
        comparable = not reasons
    return {
        "eligible": bool(user_id) and (mode != "hardware" or comparable),
        "comparable": comparable,
        "simulation": bool(simulation or mode != "hardware"),
        "reasons": reasons,
        "daily": daily,
        "reference": reference,
        "protocol": {"version": "standard_v1", "planned_sec": 90, "fixed_factor": 1.0,
                     "game_params_version": difficulty.PARAMS_VERSION,
                     "start_energy": difficulty.CONFIG["start_energy"]},
    }


def _workbench_payload(*, user_id: Optional[str], session_id: Optional[str],
                       tz_offset_min: Optional[int] = None) -> dict:
    active = None
    if session_id:
        active = _session_for(session_id, user_id, require_user=bool(user_id))
    elif user_id:
        owned = [s for s in _sessions.values() if s.user_id == user_id and not s.finished]
        active = owned[-1] if owned else None
    report = None
    if active and active.finished:
        report = active.stats or None
    elif user_id:
        # 活动 Session 期间仍展示最近一份已完成报告，便于对照诊断；
        # 不把进行中的前端状态伪装成已完成结果。
        try:
            recent = storage.list_sessions(user_id, 1)
            report = recent[0].get("report") if recent else None
        except StorageError:
            report = None
    runtime_source = (active.source.describe() if active else
                      (report or {}).get("source") or {})
    source_name = str(runtime_source.get("name") or (report or {}).get("source", {}).get("name") or "—")
    purpose = (active.purpose if active else (report or {}).get("purpose") or "game")
    device = active.config.get("device_key") if active else (report or {}).get("device_key")
    started = active.created_at if active else None
    elapsed = None
    if active and not active.finished:
        elapsed = round(time.time() - active.created_at, 1)
    elif (report or {}).get("duration_sec") is not None:
        elapsed = report.get("duration_sec")
    calib_snapshot = (active.calibration_snapshot if active else
                      (report or {}).get("calibration_snapshot") or (report or {}).get("calibration"))
    ref_snapshot = (active.reference_snapshot if active else (report or {}).get("reference_snapshot"))
    diff_snapshot = (active.difficulty_snapshot if active else (report or {}).get("difficulty_snapshot"))
    user = None
    if user_id:
        try:
            user = storage.get_user(user_id)
        except StorageError:
            user = None
    status = storage.status()
    daily = None
    cal_history = []
    ref_history = []
    diff_profile = None
    diff_history = []
    if user_id:
        try:
            # 回放/测试会复用一条硬件校准；状态仍按该校准的硬件设备与应用条件检查，
            # 不把回放源误标成“今日硬件校准失效”。
            daily_mode = "hardware" if source_name == "replay" else source_name
            daily_device = (calib_snapshot or {}).get("device_key") or device
            daily = storage.calibration_status(user_id, mode=daily_mode,
                                                device=daily_device, tz_offset_min=tz_offset_min)
            cal_history = storage.calibration_history(user_id, 12)
            ref_history = storage.reference_baselines(user_id)
            diff_profile = storage.difficulty_profile(user_id, history_limit=20)
            diff_history = storage.difficulty_history(user_id, 20)
        except StorageError:
            pass
    # report.assessment 可能显式为 null（例如演示局）；不能用 None.get 再取子字段。
    report_meta = report if isinstance(report, dict) else {}
    assessment_meta = report_meta.get("assessment") if isinstance(report_meta.get("assessment"), dict) else {}
    assessment = _assessment_eligibility(
        user_id, source_name, device, tz_offset_min,
        simulation=bool(report_meta.get("demo") or assessment_meta.get("simulation")))
    recent_assessments = []
    if user_id:
        try:
            recent_assessments = storage.assessments(user_id, 8)
        except StorageError:
            recent_assessments = []
    # 工作台只暴露最近评估摘要，避免把整份逐轮报告塞进每 3 秒轮询。
    recent_assessments = [{
        "assessment_id": a["assessment_id"], "session_id": a["session_id"],
        "status": a["status"], "simulation": a["simulation"],
        "protocol_version": a["protocol_version"], "planned_sec": a["planned_sec"],
        "fixed_factor": a["fixed_factor"], "seed": a["seed"],
        "started_at": a["started_at"], "ended_at": a["ended_at"],
    } for a in recent_assessments]
    latest = _small_report(report)
    if latest and not latest.get("diagnostics"):
        latest["diagnostics"] = diagnostics.diagnose(report or {}, latest.get("metrics"))
    return {
        "ok": True,
        "app": {"name": "专注小蛙", "version": app.version,
                "schema_version": status.get("schema_version"), "encrypted": False},
        "storage": {"data_dir": status.get("data_dir"), "counts": status.get("counts"),
                    "scope_note": status.get("scope_note")},
        "user": ({"user_id": user.get("user_id"), "nickname": user.get("nickname"),
                  "avatar": user.get("avatar"), "status": user.get("status")} if user else None),
        "runtime": {
            "session_id": active.id if active else (report or {}).get("session_id"),
            "purpose": purpose,
            "mode": source_name,
            "source": runtime_source,
            "device_key": device,
            "device": runtime_source.get("device") or runtime_source.get("address"),
            "channels": runtime_source.get("channels") or (active.source.ch_names if active else []),
            "fs": runtime_source.get("fs") or (getattr(active.source, "fs", None) if active else None),
            "started_at": _iso_seconds(started) if started else (report or {}).get("created_at"),
            "elapsed_sec": elapsed,
            "monitor_clients": active.monitor_clients if active else 0,
            "source_is_real": source_name == "hardware",
            "session_count": len(_sessions),
            "assessment": active.assessment if active else (report or {}).get("assessment"),
        },
        "calibration": {
            "current": calib_snapshot,
            "daily": daily,
            "history": cal_history,
            "reference": ref_snapshot or (ref_history[0] if ref_history else None),
            "reference_history": ref_history,
        },
        "difficulty": {
            "profile": diff_profile,
            "history": diff_history,
            "snapshot": diff_snapshot,
        },
        "assessment": {**assessment, "recent": recent_assessments},
        "latest_report": latest,
        "diagnostics": (latest or {}).get("diagnostics") if latest else None,
        "raw_wave_exported": False,
    }


@app.get("/api/dev/workbench")
def dev_workbench(session_id: Optional[str] = Query(None),
                  user_id: Optional[str] = Query(None),
                  tz_offset_min: Optional[int] = Query(None),
                  x_user_id: Optional[str] = Header(None, alias="X-User-Id")):
    uid = (user_id or x_user_id or "").strip() or None
    try:
        return _workbench_payload(user_id=uid, session_id=session_id,
                                  tz_offset_min=tz_offset_min)
    except HTTPException:
        raise
    except StorageError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/dev/diagnostics/{sid}")
def dev_diagnostics(sid: str, user_id: Optional[str] = Query(None),
                    x_user_id: Optional[str] = Header(None, alias="X-User-Id")):
    uid = (user_id or x_user_id or "").strip() or None
    report = _load_report(sid, uid)
    metrics = difficulty.compute_metrics(report)
    return {
        "ok": True,
        "session_id": sid,
        "diagnostics": report.get("diagnostics") or diagnostics.diagnose(report, metrics),
        "charge_process": report.get("charge_process") or diagnostics.charge_process(report),
        "metrics": metrics,
        "rounds": diagnostics.summarize_rounds(report),
        "assessment": report.get("assessment"),
        "privacy": {"raw_eeg_exported": False, "nickname_exported": False},
    }


@app.post("/api/dev/diagnostics/{sid}/export")
def dev_export_diagnostics(sid: str, fmt: str = Query("json"),
                           user_id: Optional[str] = Query(None),
                           x_user_id: Optional[str] = Header(None, alias="X-User-Id")):
    uid = (user_id or x_user_id or "").strip() or None
    report = _load_report(sid, uid)
    runtime = _workbench_payload(user_id=uid, session_id=None).get("app", {})
    payload = dev_export.build_payload(report, user_id=uid, runtime=runtime)
    fmt = "csv" if str(fmt).lower() == "csv" else "json"
    item = dev_export.write_export(storage.reports_dir, sid, fmt, payload)
    return {
        "ok": True, "format": fmt, "filename": item["filename"],
        "path": item["path"], "media_type": item["media_type"],
        "content": item["content"].decode("utf-8-sig" if fmt == "csv" else "utf-8"),
        "raw_eeg_exported": False, "nickname_exported": False,
    }


@app.get("/api/dev/current")
def dev_current():
    """当前全局源配置 + 最近会话（供开发者页）。"""
    recent = list(_sessions.values())[-5:] if _sessions else []
    return {
        "source_config": _source_config,
        "recent_sessions": [s.to_public() for s in recent],
    }


app.include_router(accounts_router)
app.include_router(growth_router)


# ---------------------------------------------------------------------------
# 静态前端（必须最后挂载，否则会抢先匹配 /api/* 路由）
# ---------------------------------------------------------------------------
if os.path.isdir(WEB_DIR):
    # no-cache：开发迭代频繁，确保浏览器每次刷新拿到最新页面（API 响应不动）
    @app.middleware("http")
    async def no_cache_static(request, call_next):
        response = await call_next(request)
        if not request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
