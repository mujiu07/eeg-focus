"""模拟 Xmuse Direct 的 OSC 推送，用于**无设备**验收去噪链路。

它只发合成脑电（alpha 10 Hz + beta 20 Hz + 噪声），并可按固定节奏注入眨眼，
以便在校准页/游戏页上观察信号质量提示与分数是否被眨眼带偏。

用法（另开一个终端，先启动服务）：
    .\\.venv-win\\Scripts\\python.exe scripts\\mock_osc_feed.py --port 7000 --seconds 120
    .\\.venv-win\\Scripts\\python.exe scripts\\mock_osc_feed.py --blink-every 0      # 不眨眼
    .\\.venv-win\\Scripts\\python.exe scripts\\mock_osc_feed.py --stop-after 30      # 30s 后停发，验证断流提示
    .\\.venv-win\\Scripts\\python.exe scripts\\mock_osc_feed.py --blink-uv 400       # 削顶级眨眼

注意：这是**验收/演示工具**，不是真实设备数据；它的作用是让 4/6 通道链路
在没有 Xmuse 的情况下也能跑完整流程。
"""
import argparse
import socket
import sys
import time

import numpy as np
from pythonosc.osc_message_builder import OscMessageBuilder

# Windows 控制台默认 GBK，中文与 µV 会乱码/报错；统一按 UTF-8 输出。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def build_block(cfg, idx, rng):
    """按绝对样本号生成波形，保证跨包相位连续、眨眼包络不被切断。"""
    n = len(idx)
    t = idx / cfg.fs
    data = np.zeros((cfg.channels, n))
    for i in range(cfg.channels):
        data[i] = (10.0 * np.sin(2 * np.pi * 10 * t + i)
                   + 6.0 * np.sin(2 * np.pi * 20 * t + 2 * i)
                   + rng.normal(0.0, 2.0, n))
    if cfg.blink_every > 0:
        period = int(cfg.blink_every * cfg.fs)
        center = (idx // period) * period + period // 2
        dist = idx - center
        keep = np.abs(dist) < period // 2
        env = np.where(keep, np.exp(-0.5 * (dist / (0.09 * cfg.fs)) ** 2), 0.0)
        for ch in (1, 2):  # AF7 / AF8（前额，真实设备上眨眼主要落在这里）
            if ch < cfg.channels:
                data[ch] += cfg.blink_uv * env
    return data


def main():
    ap = argparse.ArgumentParser(description="Xmuse OSC 模拟推流（验收用）")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7000,
                    help="必须与服务端的 XMUSE_OSC_PORTS 一致（默认 7000）")
    ap.add_argument("--fs", type=float, default=256.0)
    ap.add_argument("--channels", type=int, default=4, choices=[4, 6])
    ap.add_argument("--seconds", type=float, default=120.0, help="0=一直发")
    ap.add_argument("--blink-every", type=float, default=3.0, help="秒；0=不眨眼")
    ap.add_argument("--blink-uv", type=float, default=150.0)
    ap.add_argument("--stop-after", type=float, default=0.0,
                    help="秒；>0 时到点后停发（进程不退），用于验证断流看门狗")
    ap.add_argument("--chunk", type=int, default=8)
    cfg = ap.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rng = np.random.default_rng(7)
    t_total = 0
    sent = 0
    t0 = time.time()
    last_log = 0.0
    stopped = False

    print("[feed] %d ch @ %.0f Hz -> %s:%d，每 %.1fs 一个眨眼（%.0f uV）"
          % (cfg.channels, cfg.fs, cfg.host, cfg.port, cfg.blink_every, cfg.blink_uv))
    print("[feed] Ctrl+C 退出")

    try:
        while True:
            now = time.time() - t0
            if cfg.seconds and now > cfg.seconds:
                break
            if cfg.stop_after and now > cfg.stop_after:
                if not stopped:
                    stopped = True
                    print("[feed] %.0fs 起停止发送（进程保留），用于验证 3 s 断流提示" % now)
                time.sleep(0.2)
                continue

            idx = t_total + np.arange(cfg.chunk)
            t_total += cfg.chunk
            data = build_block(cfg, idx, rng)

            # Xmuse 报文顺序：每个样本的 N 个通道依次排开
            b = OscMessageBuilder(address="/eeg")
            for k in range(cfg.chunk):
                for i in range(cfg.channels):
                    b.add_arg(float(data[i, k]))
            sock.sendto(b.build().dgram, (cfg.host, cfg.port))
            sent += cfg.chunk

            if now - last_log >= 5.0:
                last_log = now
                print("[feed] %5.1fs  sent=%d 样本" % (now, sent))
            time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
    print("[feed] 结束，共发送 %d 样本" % sent)


if __name__ == "__main__":
    main()
