"""Xmuse 硬件链路端到端验证（合成 OSC + 真实 HTTP/SSE）。

覆盖：创建 hardware 会话 → 去噪/去伪迹 → SSE 帧带 artifact → 校准 →
报告带 signal_quality。

运行：
    .venv-win\\Scripts\\python.exe tests\\e2e_hardware_denoise.py
"""
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request

import numpy as np
from pythonosc.osc_message_builder import OscMessageBuilder

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PY = sys.executable
HTTP_PORT = 8011
OSC_PORT = 17000
FS = 256


# --------------------------------------------------------------------------
# OSC 发送：模拟 Xmuse Direct 往 UDP 17000 推 /eeg
# --------------------------------------------------------------------------
class OscFeeder(threading.Thread):
    def __init__(self, port=OSC_PORT, fs=FS, chunk=8):
        super().__init__(daemon=True)
        self.port = port
        self.fs = fs
        self.chunk = chunk
        self.stop_flag = threading.Event()
        self.sent = 0
        self._t = 0.0  # 连续时间轴，保证波形相位连续

    def run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        rng = np.random.default_rng(7)
        while not self.stop_flag.is_set():
            n = self.chunk
            t = (self._t + np.arange(n)) / self.fs
            self._t += n
            # 4 通道背景：alpha 10 Hz + beta 20 Hz + 噪声（µV 量级）
            data = np.zeros((4, n))
            for i in range(4):
                data[i] = (10 * np.sin(2 * np.pi * 10 * t + i)
                           + 6 * np.sin(2 * np.pi * 20 * t + 2 * i)
                           + rng.normal(0, 2.0, n))
            # 每 1.5 s 一个眨眼。必须用「绝对样本号」算包络，
            # 否则跨包拼接处会出现 150 µV 阶跃，被削顶检测当成饱和（测试器自身的坑）
            idx = self._t + np.arange(n)
            period = int(1.5 * self.fs)
            center = (idx // period) * period + period // 2
            dist = idx - center
            keep = np.abs(dist) < period // 2
            env = np.where(keep, np.exp(-0.5 * (dist / (0.09 * self.fs)) ** 2), 0.0)
            data[1] += 150 * env
            data[2] += 150 * env

            # Xmuse 的报文是「每个样本 4 个通道」的顺序，服务端按 n_ch=4 切块
            b = OscMessageBuilder(address="/eeg")
            for k in range(n):
                for i in range(4):
                    b.add_arg(float(data[i, k]))
            sock.sendto(b.build().dgram, ("127.0.0.1", self.port))
            self.sent += n
            time.sleep(0.01)  # 8 样本/10ms ≈ 800 样本/秒（约 3 倍速），包体小且窗口不被覆盖


# --------------------------------------------------------------------------
# HTTP 工具
# --------------------------------------------------------------------------
def post(path, payload):
    req = urllib.request.Request(
        f"http://127.0.0.1:{HTTP_PORT}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def get(path, timeout=10):
    with urllib.request.urlopen(f"http://127.0.0.1:{HTTP_PORT}{path}", timeout=timeout) as r:
        return json.loads(r.read().decode())


def read_frames(sid, want=4, timeout=25):
    """读 SSE，收集 want 个 frame 事件后主动断开。"""
    frames = []
    req = urllib.request.Request(f"http://127.0.0.1:{HTTP_PORT}/api/session/{sid}/stream")
    start = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for raw in r:
            if time.time() - start > timeout:
                break
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            try:
                payload = json.loads(line[5:].strip())
            except ValueError:
                continue
            if "t" not in payload:
                continue  # hello 事件
            frames.append(payload)
            if len(frames) >= want:
                break
    return frames


def wait_ready(max_sec=40):
    deadline = time.time() + max_sec
    while time.time() < deadline:
        try:
            get("/api/dev/current", timeout=2)
            return True
        except Exception:
            time.sleep(0.4)
    return False


def main():
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen(
        [PY, "-m", "uvicorn", "app.server:app", "--host", "127.0.0.1",
         "--port", str(HTTP_PORT), "--log-level", "warning"],
        cwd=ROOT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    feeder = None
    try:
        print("启动服务…")
        if not wait_ready():
            out = proc.stdout.read().decode("utf-8", "replace") if proc.stdout else ""
            raise RuntimeError(f"服务未就绪\n{out}")

        feeder = OscFeeder()
        feeder.start()
        print(f"OSC 推流中：udp://127.0.0.1:{OSC_PORT}")

        info = post("/api/session", {
            "mode": "hardware", "osc_ports": str(OSC_PORT), "osc_fs": FS,
        })
        sid = info["session_id"]
        print("会话:", sid)
        assert info["source"].get("denoise", {}).get("enabled"), "describe 未标记去噪"
        print("  describe.denoise =", info["source"]["denoise"])

        frames = read_frames(sid, want=4)
        print(f"收到 {len(frames)} 帧")
        assert frames, "没有收到 SSE 帧"
        valid = [f for f in frames if f.get("valid")]
        assert valid, f"全部帧无效: {[f.get('reason') for f in frames]}"
        art = valid[0].get("artifact")
        print("  artifact =", json.dumps(art, ensure_ascii=False))
        assert art is not None, "SSE 帧里没有 artifact 报告"
        for key in ("usable", "level", "score", "flags", "channel_mask"):
            assert key in art, f"artifact 缺少字段 {key}"
        assert len(art["channel_mask"]) == 4

        cal = post(f"/api/session/{sid}/calibrate", {"duration": 4})
        print("校准:", json.dumps(cal.get("calibration", {}), ensure_ascii=False)[:300])
        sq = cal.get("signal_quality")
        print("  signal_quality =", json.dumps(sq, ensure_ascii=False))
        assert sq is not None, "校准结果缺少 signal_quality"
        assert sq["frames"] > 0 and "usable_ratio" in sq

        rep = post(f"/api/session/{sid}/finish",
                   {"score": 60, "played_sec": 20, "demo": True})
        r = rep["report"]
        print("报告中 signal_quality =", json.dumps(r.get("signal_quality"), ensure_ascii=False))
        assert r.get("signal_quality") is not None, "报告缺少 signal_quality"
        assert "n_artifact_frames" in r

        print("\nE2E 通过：OSC → 去噪 → SSE → 校准 → 报告")
        return 0
    finally:
        if feeder:
            feeder.stop_flag.set()
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
        if proc.stdout:
            tail = proc.stdout.read().decode("utf-8", "replace")
            if "Traceback" in tail or "Error" in tail:
                print("\n--- 服务日志 ---\n" + tail[-3000:])


if __name__ == "__main__":
    sys.exit(main())
