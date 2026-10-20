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
import time
import uuid
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
from sse_starlette.sse import EventSourceResponse

from .focus_engine import FocusEngine, features
from . import sources

ROOT = os.path.join(os.path.dirname(__file__), "..")
WEB_DIR = os.path.join(ROOT, "web")
SESSIONS_DIR = os.path.join(ROOT, "outputs", "sessions")

app = FastAPI(title="Brain-Focusing Game MVP", version="0.1.0")

# ---------------------------------------------------------------------------
# 全局状态
# ---------------------------------------------------------------------------
DEFAULT_SOURCE_CONFIG = {"mode": "replay", "file": None}
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
        self.engine = _engine
        self.created_at = time.time()
        self.finished_at = None
        self.history = []            # [{t, raw, focus, meta}]
        self.baseline = None
        self.baseline_quantiles = None
        self.calibration = None      # {duration, n, mean, ...}
        self.finished = False
        self.stats = {}
        self._queue = asyncio.Queue(maxsize=1)
        self._task = None

    async def start(self):
        # 预热模型状态
        self.engine.reset()
        # EDF 读取+滤波耗时数秒，在线程池执行，避免阻塞事件循环
        # （否则刚创建会话时 SSE 连接会长时间收不到任何帧）
        if self.source.name == "replay":
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self.source.start)
        self._task = asyncio.create_task(self._run())

    async def _run(self):
        while not self.finished:
            t0 = time.time()
            try:
                seg, meta = self.source.next_window()
                if self.source.name == "manual":
                    raw = meta.get("focus", 0.5)
                    focus = raw
                else:
                    raw, focus = self.engine.update(seg, meta.get("fs", self.source.fs))
                entry = {"t": round(time.time() - self.created_at, 2),
                         "raw": round(float(raw), 3),
                         "focus": round(float(focus), 3),
                         "meta": meta}
                self.history.append(entry)
                if len(self.history) > 30000:
                    self.history = self.history[-10000:]
                try:
                    self._queue.put_nowait(entry)
                except asyncio.QueueFull:
                    try:
                        self._queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                    self._queue.put_nowait(entry)
            except Exception as e:  # noqa: BLE001
                entry = {"t": round(time.time() - self.created_at, 2),
                         "raw": 0.5, "focus": 0.5,
                         "meta": {"source": self.source.name, "error": str(e)}}
                self.history.append(entry)
                try:
                    self._queue.put_nowait(entry)
                except asyncio.QueueFull:
                    pass
            await asyncio.sleep(max(0.05, sources.STEP_SEC - (time.time() - t0)))

    async def finish(self, score=None, played_sec=None, notes=None):
        if self.finished:
            return self
        self.finished = True
        self.finished_at = time.time()
        focuses = [e["focus"] for e in self.history]
        raws = [e["raw"] for e in self.history]
        dur = self.finished_at - self.created_at
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
            "focus_mean": round(float(np_mean(focuses)), 3) if focuses else None,
            "focus_max": round(float(max(focuses)), 3) if focuses else None,
            "focus_min": round(float(min(focuses)), 3) if focuses else None,
            "above_baseline_ratio": (round(float(sum(f >= (self.baseline or 0) for f in focuses)) / len(focuses), 3)
                                      if focuses and self.baseline is not None else None),
            "curve": [{"t": e["t"], "focus": e["focus"], "raw": e["raw"]} for e in self.history[::2]],
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
    mode: str = "replay"          # replay | manual | hardware
    file: Optional[str] = None    # replay 模式下的 EDF 文件路径


class CalibrateStart(BaseModel):
    duration: float = 20.0        # 校准采样秒数


class ManualSet(BaseModel):
    focus: float = 0.5


class SessionFinish(BaseModel):
    score: Optional[int] = None
    played_sec: Optional[float] = None
    notes: Optional[str] = None


class SourceSwitch(BaseModel):
    mode: str = "replay"
    file: Optional[str] = None


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"status": "ok", "model": _engine.describe()["model"]}


@app.get("/api/dev/info")
def dev_info():
    return {
        "engine": _engine.describe(),
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
    _source_config = {"mode": body.mode, "file": body.file}
    return {"ok": True, "source_config": _source_config}


@app.post("/api/session")
async def create_session(body: SessionCreate):
    config = {"mode": body.mode, "file": body.file}
    try:
        source = sources.create_source(config)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"信号源创建失败: {e}")
    if source.name == "hardware":
        raise HTTPException(400, "真实硬件头环尚未接入（MVP 演示请使用 replay/manual）")
    s = Session(source, config)
    _sessions[s.id] = s
    await s.start()
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
    duration = max(3.0, min(body.duration, 60.0))
    t_start = time.time()
    # 等待校准采样窗口结束，期间保持队列消费，避免阻塞后台任务
    deadline = time.time() + duration
    while time.time() < deadline and not s.finished:
        await asyncio.sleep(0.2)
    # 取校准期间产生的 focus
    frames = [e for e in s.history
              if e["t"] <= duration + 0.5]
    focuses = [e["focus"] for e in frames]
    raws = [e["raw"] for e in frames]
    if not focuses:
        raise HTTPException(500, "校准期间未采集到足够信号帧")
    focuses = sorted(focuses)
    n = len(focuses)
    q10, q50, q90 = (focuses[int(n * 0.1)], focuses[int(n * 0.5)], focuses[int(n * 0.9)])
    s.baseline = round(q50, 3)
    s.baseline_quantiles = {"q10": round(q10, 3), "q50": round(q50, 3), "q90": round(q90, 3)}
    s.calibration = {
        "duration_sec": round(duration, 1),
        "n_frames": n,
        "baseline": s.baseline,
        "focus_mean": round(float(np_mean(raws)), 3),
        "quantiles": s.baseline_quantiles,
    }
    return {"ok": True, "baseline": s.baseline, "calibration": s.calibration}


@app.get("/api/session/{sid}/stream")
async def stream(sid: str):
    s = _sessions.get(sid)
    if not s:
        raise HTTPException(404, "会话不存在")
    async def gen():
        yield {"event": "hello", "data": json.dumps({"session_id": s.id,
                                                      "source": s.source.describe(),
                                                      "baseline": s.baseline})}
        while not s.finished:
            try:
                entry = await asyncio.wait_for(s._queue.get(), timeout=2.0)
                payload = dict(entry)
                payload["baseline"] = s.baseline
                payload["calibration"] = s.calibration
                yield {"event": "frame", "data": json.dumps(payload)}
            except asyncio.TimeoutError:
                if s.finished:
                    break
                continue
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
# 静态前端
# ---------------------------------------------------------------------------
if os.path.isdir(WEB_DIR):
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")


@app.get("/api/dev/current")
def dev_current():
    """当前全局源配置 + 最近会话（供开发者页）。"""
    recent = list(_sessions.values())[-5:] if _sessions else []
    return {
        "source_config": _source_config,
        "recent_sessions": [s.to_public() for s in recent],
    }
