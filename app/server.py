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
from copy import copy
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
from sse_starlette.sse import EventSourceResponse

from .focus_engine import FocusEngine, features
from . import sources
from .heart import heart

# 心率采集链路依赖 macOS 专属的 AirPods 心率进程（hrd），其他系统没有对应实现，
# 因此不暴露这块功能：接口直接拒绝，前端也不渲染入口。
HEART_SUPPORTED = platform.system() == "Darwin"
HEART_UNSUPPORTED_REASON = "心率采集依赖 macOS 的 AirPods 心率进程，当前系统不支持"
from .music import music

ROOT = os.path.join(os.path.dirname(__file__), "..")
WEB_DIR = os.path.join(ROOT, "web")
SESSIONS_DIR = os.path.join(ROOT, "outputs", "sessions")

app = FastAPI(title="Brain-Focusing Game MVP", version="0.1.0")

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


# ---------------------------------------------------------------------------
# 会话
# ---------------------------------------------------------------------------
class Session:
    def __init__(self, source, config):
        self.id = uuid.uuid4().hex[:8]
        self.source = source
        self.config = config
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
        v = 20.0 + 60.0 * (float(x) - lo) / (hi - lo)
        return round(max(0.0, min(100.0, v)), 1)

    def raw50(self):
        """50 分线对应的原始专注值，用于 focused 判定与报告基线。"""
        return round((self.score_low + self.score_high) / 2.0, 3)

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
                if self.source.name == "manual":
                    raw = meta.get("focus", 0.5)
                    focus = raw
                else:
                    raw, focus = self.engine.update(seg, meta.get("fs", self.source.fs))
                entry = {"t": round(time.time() - self.created_at, 2),
                         "raw": round(float(raw), 3),
                         "focus": round(float(focus), 3),
                         "valid": True,
                         "meta": meta}
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
                self._publish_frame(entry)
            except Exception as e:  # noqa: BLE001
                if self.finished:
                    break
                entry = {"t": round(time.time() - self.created_at, 2),
                         "raw": None, "focus": None, "valid": False,
                         "meta": {"source": self.source.name, "error": str(e)}}
                self._publish_frame(entry)
            await asyncio.sleep(max(0.05, sources.STEP_SEC - (time.time() - t0)))

    def _publish_frame(self, entry):
        self.history.append(entry)
        if len(self.history) > 30000:
            self.history = self.history[-10000:]
        self._latest_frame = entry
        ready = self._frame_ready
        self._frame_ready = asyncio.Event()
        ready.set()

    async def finish(self, score=None, played_sec=None, notes=None):
        if self.finished:
            return self
        self.finished = True
        self._frame_ready.set()
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
        hr_vals = [e["hr"]["bpm"] for e in valid
                   if e.get("hr") and e["hr"].get("valid") and e["hr"].get("bpm") is not None]
        n_invalid = len(self.history) - len(valid)
        dur = self.finished_at - self.created_at
        hr_summary = heart.summary()
        hr_summary["n_frames"] = len(hr_vals)
        hr_summary["coverage"] = round(len(hr_vals) / len(valid), 3) if valid else 0.0
        self.stats = {
            "session_id": self.id,
            "created_at": datetime.fromtimestamp(self.created_at).isoformat(timespec="seconds"),
            "duration_sec": round(dur, 1),
            "played_sec": played_sec,
            "score": score,
            "notes": notes,
            "source": self.source.describe(),
            "baseline": self.baseline,
            "calibration": self.calibration,
            "n_frames": len(self.history),
            "n_valid_frames": len(valid),
            "n_invalid_frames": n_invalid,
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
            "heart": hr_summary,
            "hr_curve": heart.curves(self._mono0),
            "curve": [{"t": e["t"], "focus": e["focus"], "raw": e["raw"],
                       "focus_fused": e.get("focus_fused"),
                       "score": self.score_of(e.get("focus_fused")
                                              if e.get("focus_fused") is not None else e.get("focus"))}
                      for e in valid[::2]],
        }
        if self._task:
            self._task.cancel()
        return self

    def to_public(self):
        return {
            "id": self.id,
            "source": self.source.describe(),
            "baseline": self.baseline,
            "calibration": self.calibration,
            "created_at": self.created_at,
        }


def np_mean(xs):
    import numpy as np
    return np.mean(xs)


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------
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


class HeartStart(BaseModel):
    mode: str = "mock"                   # mock | hrd | csv
    hrd_path: Optional[str] = None
    csv_path: Optional[str] = None
    fps: float = 10.0
    rest_bpm: Optional[float] = None
    weight: Optional[float] = None


class CalibrateStart(BaseModel):
    duration: float = 20.0        # 校准采样秒数
    video_full: bool = False      # true = 整段视频当校准，不分“放松/心算”两段


class ManualSet(BaseModel):
    focus: float = 0.5


class SessionFinish(BaseModel):
    score: Optional[int] = None
    played_sec: Optional[float] = None
    notes: Optional[str] = None


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
    # 非 macOS 没有心率采集实现：忽略心率源，纯心率玩法退回脑电回放。
    if not HEART_SUPPORTED:
        if body.heart_mode and body.heart_mode != "off":
            body.heart_mode = "off"
        if body.mode == "heart":
            body.mode = "replay"
    # 仅心率模式没有脑电信号，必须接一个心率源；未显式指定时默认 AirPods 自动读取。
    if body.mode == "heart" and (not body.heart_mode or body.heart_mode == "off"):
        body.heart_mode = "hrd"
    config = {
        "mode": body.mode,
        "file": body.file,
        "osc_host": body.osc_host,
        "osc_ports": body.osc_ports,
        "osc_fs": body.osc_fs,
        "osc_channels": body.osc_channels,
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
    # 游戏会话由前端带着校准基线创建（校准会话本身在后面 /calibrate 里写入），
    # 否则报告页拿不到基线，橙色虚线与"高于基线占比"都会是空值。
    if body.baseline is not None:
        try:
            b = float(body.baseline)
        except (TypeError, ValueError):
            b = None
        if b is not None and 0.0 <= b <= 1.0:
            s.baseline = round(b, 3)
    # 动态定标区间：校准页算好后随会话带过来，游戏/报告都用同一套 20–80 映射。
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
    except Exception as e:  # noqa: BLE001 - 端口占用/依赖缺失时给出可读错误
        _sessions.pop(s.id, None)
        raise HTTPException(400, f"信号源启动失败: {e}")
    return {"session_id": s.id, "source": source.describe()}


@app.post("/api/session/{sid}/manual")
def set_manual(sid: str, body: ManualSet):
    s = _sessions.get(sid)
    if not s:
        raise HTTPException(404, "会话不存在")
    if s.source.name != "manual":
        raise HTTPException(400, "当前会话不是手动模拟模式")
    s.source.set_focus(body.focus)
    return {"ok": True}


@app.post("/api/session/{sid}/calibrate")
async def calibrate(sid: str, body: CalibrateStart):
    s = _sessions.get(sid)
    if not s:
        raise HTTPException(404, "会话不存在")
    duration = max(3.0, min(float(body.duration), 600.0))
    t_start = time.time()
    # 采样窗口从会话创建时开始计时：前端倒计时结束（t>=duration）后才发起请求，
    # 这里只补足尚未采满的剩余时间，避免再等满整个 duration 造成长时间空档。
    remaining = duration - (time.time() - s.created_at)
    if remaining > 0 and not s.finished:
        await asyncio.sleep(min(remaining, duration))
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
    MIN_SPAN = 0.10

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
    # 用校准期的心率跨度校准倒 U 尺度：跨度越小，说明这个人对任务的心率反应越平
    hr_bpms = [e["hr"]["bpm"] for e in frames if e.get("hr") and e["hr"].get("bpm")]
    if len(hr_bpms) >= 4:
        ordered = sorted(hr_bpms)
        lo_bpm = ordered[int(len(ordered) * 0.1)]
        hi_bpm = ordered[int(len(ordered) * 0.9)]
        heart.set_span(max(6.0, hi_bpm - lo_bpm))

    return {"ok": True, "baseline": s.baseline, "calibration": s.calibration,
            "score_range": {"low": s.score_low, "high": s.score_high},
            "heart": hr_sum,
            "hr_span": round(heart._hr_span, 2)}


@app.get("/api/session/{sid}/stream")
async def stream(sid: str):
    s = _sessions.get(sid)
    if not s:
        raise HTTPException(404, "会话不存在")
    async def gen():
        yield {"event": "hello", "data": json.dumps({"session_id": s.id,
                                                      "source": s.source.describe(),
                                                      "baseline": s.baseline})}
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
            payload["score_low"] = s.score_low
            payload["score_high"] = s.score_high
            yield {"event": "frame", "data": json.dumps(payload)}
        yield {"event": "end", "data": json.dumps({"session_id": s.id})}

    return EventSourceResponse(gen())


@app.post("/api/session/{sid}/finish")
async def finish_session(sid: str, body: SessionFinish):
    s = _sessions.get(sid)
    if not s:
        raise HTTPException(404, "会话不存在")
    await s.finish(score=body.score, played_sec=body.played_sec, notes=body.notes)
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    with open(os.path.join(SESSIONS_DIR, f"{s.id}.json"), "w", encoding="utf-8") as f:
        json.dump(s.stats, f, ensure_ascii=False, indent=2)
    return {"ok": True, "report": s.stats}


@app.get("/api/report/{sid}")
def get_report(sid: str):
    s = _sessions.get(sid)
    if not s or not s.finished:
        # 尝试从磁盘读
        p = os.path.join(SESSIONS_DIR, f"{sid}.json")
        if os.path.exists(p):
            return json.load(open(p, encoding="utf-8"))
        raise HTTPException(404, "报告不存在或会话未结束")
    return s.stats


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


@app.get("/api/dev/current")
def dev_current():
    """当前全局源配置 + 最近会话（供开发者页）。"""
    recent = list(_sessions.values())[-5:] if _sessions else []
    return {
        "source_config": _source_config,
        "recent_sessions": [s.to_public() for s in recent],
    }


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
