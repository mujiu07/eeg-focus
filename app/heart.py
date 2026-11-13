"""
心率信号源
==========
为专注检测引入一路低采样率生理辅助信号（AirPods Pro 3 心率）。

三种来源：
  mock : 本地模拟心率（无需硬件，用于开发与自动化测试）
  hrd  : 调用现成的 hrd 工具读取 iPhone 镜像里的训练心率，解析其 stdout
  csv  : 跟随一个已由外部进程写入的 hrd CSV（只读，不接管进程）

设计约束：
- 心率更新远慢于 2 秒一帧的 EEG（hrd 实测 10–20 秒才输出一次新读数），因此它
  只做“辅助修正”，不主导专注分；缺失/过期时自动退回纯 EEG 结果。
- 每个读数都带时间戳，超过 STALE_SEC 未更新即视为 stale，不参与融合。
- 子进程有最长运行时长，stop() 会结束自己启动的整个进程组，避免残留。
"""

import math
import os
import re
import signal
import subprocess
import threading
import time
from collections import deque

# 现成 hrd 工具的默认位置（只读调用，不修改该目录）
HRD_DEFAULT = (
    "/Users/fan/Documents/deepseek-harness/default-workspace/"
    "09_2026-11-13_AirPods心率监测/bin/hrd"
)

# 超过该秒数没有新读数即视为过期。hrd 只在数值变化时输出，静息状态下
# 可能几十秒没有新行，所以进程存活时额外放宽（见 STALE_SEC_ALIVE）。
STALE_SEC = 45.0
STALE_SEC_ALIVE = 120.0
# 心率高于静息值多少 BPM 时，“平静/专注”分量降到最低
REST_SPAN_BPM = 25.0
# 生理合理范围，超出视为误识别
MIN_BPM = 30.0
MAX_BPM = 230.0
# 单次启动的最长运行时长，防止 hrd 常驻
MAX_RUNTIME_SEC = 900.0
# 融合权重：心率分量占最终专注分的比例（EEG 仍是主体）
DEFAULT_WEIGHT = 0.15

_BPM_RE = re.compile(r"(?:BPM|bpm)[=:\s]+([0-9]+(?:\.[0-9]+)?)")


class HeartRateMonitor:
    """单例式心率监测器，线程安全。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._samples = deque(maxlen=1200)   # [(monotonic_ts, bpm)]
        self._mode = "off"
        self._source_path = None
        self._rest_bpm = 70.0
        self._hr_span = 12.0     # 校准得到的“静息→任务”心率跨度（BPM）
        self._weight = DEFAULT_WEIGHT
        self._enabled = False
        self._last_error = None
        self._started_at = None
        self._stop_evt = threading.Event()
        self._thread = None
        self._proc = None
        self._lock_path = None

    # ------------------------------------------------------------------ 状态
    def _now(self):
        return time.monotonic()

    def _push(self, bpm):
        try:
            bpm = float(bpm)
        except (TypeError, ValueError):
            return False
        if not (MIN_BPM <= bpm <= MAX_BPM):
            return False
        with self._lock:
            self._samples.append((self._now(), bpm))
        return True

    def snapshot(self):
        """返回当前心率状态，供 SSE 帧与前端使用。"""
        with self._lock:
            mode = self._mode
            rest = self._rest_bpm
            weight = self._weight
            err = self._last_error
            bpm = None
            age = None
            if self._samples:
                ts, val = self._samples[-1]
                bpm = round(float(val), 1)
                age = round(self._now() - ts, 1)
            # hrd 抓取进程仍存活时，说明监测在继续、只是数值没变，放宽有效期。
            proc = self._proc
            alive = proc is not None and proc.poll() is None
            limit = STALE_SEC_ALIVE if (mode == "hrd" and alive) else STALE_SEC
            th = self._thread
            running = mode != "off" and th is not None and th.is_alive()
        valid = bool(self._enabled and bpm is not None and age is not None and age <= limit)
        return {
            "mode": mode,
            "bpm": bpm if valid else None,
            "valid": valid,
            "age_sec": age,
            "rest_bpm": round(float(rest), 1),
            "weight": round(float(weight), 3),
            "running": running,
            "error": err,
        }

    # ------------------------------------------------------------ 生理特征
    def _window(self, window_sec):
        now = self._now()
        with self._lock:
            return [(t, float(v)) for t, v in self._samples if now - t <= window_sec]

    def features(self, window_sec=60.0):
        """最近窗口内的心率特征：均值、波动、趋势，供打分与报告解释。"""
        pts = self._window(window_sec)
        if not pts:
            return None
        vals = [v for _, v in pts]
        n = len(vals)
        mean = sum(vals) / n
        sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / n) if n > 1 else 0.0
        slope = 0.0
        if n >= 3:
            t0 = pts[0][0]
            xs = [t - t0 for t, _ in pts]
            mx = sum(xs) / n
            den = sum((x - mx) ** 2 for x in xs)
            if den > 1e-6:
                slope = sum((x - mx) * (v - mean) for x, (_, v) in zip(xs, pts)) / den
        age = self._now() - pts[-1][0]
        return {
            "bpm": round(vals[-1], 1),
            "mean": round(mean, 2),
            "sd": round(sd, 2),
            "slope": round(slope, 3),
            "n": n,
            "age_sec": round(age, 1),
            "span": round(self._hr_span, 2),
        }

    def focus_component(self, bpm=None, target_delta=None, window_sec=60.0):
        """心率 → 0..1 的“生理投入”分量。

        机制：久坐认知任务里，适度的心率上升 + 较低的心率波动，通常对应更高的
        任务投入（认知负荷会带来轻度交感激活、HRV 下降）。但它不是“越低越专注”，
        而且个体差异很大，所以这里做三件事：

          1. 用个人静息与校准跨度归一，不套全人群常数；
          2. 倒 U：偏离目标越远分越低——过高是紧张/刚活动，过低是困倦；
          3. 数据稀疏时向 0.5 收缩，避免几个读数就给出极端分。

        target_delta: 期望高于静息的 BPM。默认取 45% 校准跨度；
                      纯心率玩法传 0（目标就是静息本身）。
        """
        f = self.features(window_sec)
        if f is None:
            if bpm is None:
                return None
            f = {"mean": float(bpm), "sd": 0.0, "slope": 0.0, "n": 1, "age_sec": 0.0}

        rest = self._rest_bpm
        span = max(6.0, float(self._hr_span))
        target = 0.45 * span if target_delta is None else float(target_delta)

        delta = f["mean"] - rest
        # 高斯倒 U：目标是“适度激活”，两侧都掉分，比线性衰减更平滑
        sigma = max(4.0, 0.45 * span)
        activation = math.exp(-(((delta - target) / sigma) ** 2))
        # 波动越大越不稳定；这能捕捉到“数值尚可但坐不住”的状态
        stability = max(0.0, 1.0 - min(1.0, f["sd"] / 3.5))
        # 持续下滑是疲劳/走神的信号，比单点数值更可信
        penalty = min(0.7, max(0.0, -f["slope"]) * 1.5) if f["slope"] < 0 else 0.0

        raw = 0.55 * activation + 0.25 * stability + 0.20 * (1.0 - penalty)

        conf = min(1.0, f["n"] / 8.0)
        if f["age_sec"] > STALE_SEC:
            conf *= 0.5
        val = 0.5 + (raw - 0.5) * max(0.0, min(1.0, conf))
        return float(max(0.05, min(0.95, val)))

    def set_span(self, bpm_span):
        """设置校准得到的“静息→任务”心率跨度，用于倒 U 的尺度。"""
        with self._lock:
            self._hr_span = float(max(6.0, min(80.0, float(bpm_span))))
        return round(self._hr_span, 2)

    # ------------------------------------------------------------------ 控制
    def set_rest(self, bpm):
        """设置静息心率基线（校准页采集后写入）。"""
        with self._lock:
            self._rest_bpm = float(max(35.0, min(180.0, float(bpm))))
        return round(self._rest_bpm, 1)

    def set_weight(self, weight):
        """设置心率融合权重（0..0.5，EEG 仍为主体）。"""
        with self._lock:
            self._weight = float(max(0.0, min(0.5, float(weight))))
        return round(self._weight, 3)

    def start(self, mode="mock", hrd_path=None, csv_path=None, fps=10,
              rest_bpm=None, weight=None):
        self.stop()
        if mode not in ("mock", "hrd", "csv"):
            raise ValueError("mode 必须是 mock/hrd/csv")
        with self._lock:
            self._mode = mode
            self._last_error = None
            self._samples.clear()
            if rest_bpm is not None:
                self._rest_bpm = float(max(35.0, min(180.0, float(rest_bpm))))
            if weight is not None:
                self._weight = float(max(0.0, min(0.5, float(weight))))
            self._started_at = self._now()
            self._source_path = csv_path or hrd_path
        self._stop_evt.clear()
        self._enabled = True

        if mode == "mock":
            self._thread = threading.Thread(target=self._run_mock, name="hr-mock", daemon=True)
        elif mode == "csv":
            if not csv_path or not os.path.exists(csv_path):
                self._enabled = False
                raise FileNotFoundError(f"CSV 不存在: {csv_path}")
            self._thread = threading.Thread(
                target=self._run_csv, args=(csv_path,), name="hr-csv", daemon=True)
        else:
            path = hrd_path or HRD_DEFAULT
            if not os.path.exists(path):
                self._enabled = False
                raise FileNotFoundError(f"hrd 不存在: {path}")
            self._thread = threading.Thread(
                target=self._run_hrd, args=(path, float(fps)), name="hr-hrd", daemon=True)
        self._thread.start()
        return self.snapshot()

    def stop(self):
        self._stop_evt.set()
        proc = self._proc
        self._proc = None
        if proc is not None:
            _kill_tree(proc)
        th = self._thread
        self._thread = None
        if th is not None and th.is_alive():
            th.join(timeout=3.0)
        with self._lock:
            self._enabled = False
            if self._mode != "off":
                self._mode = "off"
        return True

    # ------------------------------------------------------------------ 采集
    def _run_mock(self):
        """模拟：围绕静息心率做缓慢波动，偶尔有一次短时升高。"""
        t0 = self._now()
        while not self._stop_evt.is_set():
            t = self._now() - t0
            if t > MAX_RUNTIME_SEC:
                break
            rest = self._rest_bpm
            bpm = rest + 6.0 * math.sin(t / 9.0) + 3.0 * math.sin(t / 2.3) + 1.2 * math.sin(t / 0.7)
            if int(t) % 47 in (0, 1, 2):      # 周期性轻微升高，模拟紧张/分心
                bpm += 7.0
            self._push(bpm)
            self._stop_evt.wait(2.0)

    def _run_csv(self, path):
        """跟随外部写入的 CSV：只读，不改文件。"""
        pos = 0
        try:
            pos = os.path.getsize(path)
        except OSError:
            pos = 0
        t0 = self._now()
        while not self._stop_evt.is_set():
            if self._now() - t0 > MAX_RUNTIME_SEC:
                break
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    f.seek(pos)
                    chunk = f.read()
                    pos = f.tell()
                for line in chunk.splitlines():
                    parts = line.strip().split(",")
                    if len(parts) >= 2:
                        self._push(parts[1])
            except OSError as exc:
                with self._lock:
                    self._last_error = f"读取 CSV 失败: {exc}"
            self._stop_evt.wait(0.5)

    def _run_hrd(self, path, fps):
        """运行 hrd 子进程并解析其 stdout。异常退出时有限次重启。"""
        csv_path = _unique_csv()
        attempts = 0
        t0 = self._now()
        while not self._stop_evt.is_set() and attempts < 3:
            if self._now() - t0 > MAX_RUNTIME_SEC:
                break
            attempts += 1
            cmd = [path, "run", "--auto", "--fps", str(int(fps)), "--csv", csv_path]
            try:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1, start_new_session=True,
                )
            except Exception as exc:  # noqa: BLE001 - 任何启动失败都要回传给前端
                with self._lock:
                    self._last_error = f"启动 hrd 失败: {exc}"
                break
            self._proc = proc
            self._lock_path = csv_path
            for line in proc.stdout or []:
                if self._stop_evt.is_set():
                    break
                m = _BPM_RE.search(line)
                if m:
                    self._push(m.group(1))
                else:
                    low = line.lower()
                    if any(k in low for k in ("error", "unavailable", "tcc",
                                              "no capturable window",
                                              "calibration found no")):
                        with self._lock:
                            self._last_error = line.strip()[:200]
            try:
                code = proc.wait(timeout=2.0)
            except Exception:  # noqa: BLE001
                code = proc.poll()
            self._proc = None
            if self._stop_evt.is_set():
                break
            if code not in (0, None):
                with self._lock:
                    if not self._last_error:
                        self._last_error = f"hrd 退出码 {code}"
                self._stop_evt.wait(min(5.0, 1.5 * attempts))

    def summary(self):
        """会话报告用的心率统计。"""
        with self._lock:
            vals = [v for _, v in self._samples]
            rest = self._rest_bpm
            mode = self._mode
        if not vals:
            return {"n": 0, "mean": None, "min": None, "max": None,
                    "rest_bpm": round(rest, 1), "mode": mode}
        f = self.features(120.0) or {}
        return {
            "n": len(vals),
            "mean": round(sum(vals) / len(vals), 1),
            "min": round(min(vals), 1),
            "max": round(max(vals), 1),
            "sd": f.get("sd"),
            "slope": f.get("slope"),
            "span": f.get("span"),
            "rest_bpm": round(rest, 1),
            "mode": mode,
        }

    def curves(self, t0_mono):
        """输出 (相对秒数, bpm) 曲线点，供报告使用。t0_mono 为会话开始的单调钟时刻。"""
        with self._lock:
            data = list(self._samples)
        out = []
        for ts, val in data:
            rel = ts - t0_mono
            if rel >= 0:
                out.append({"t": round(rel, 1), "bpm": round(float(val), 1)})
        return out


# ---------------------------------------------------------------------- 工具
def _kill_tree(proc):
    try:
        if os.name == "posix":
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        else:
            proc.terminate()
        proc.wait(timeout=3.0)
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


def _unique_csv():
    d = os.path.join(os.path.dirname(__file__), "..", "outputs", "heart")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"hr-{time.strftime('%Y%m%d-%H%M%S')}.csv")


# 全局单例
heart = HeartRateMonitor()
