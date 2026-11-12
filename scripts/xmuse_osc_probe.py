r"""
Xmuse OSC 端口探针
==================

在接入 eeg-focus 之前，先用它确认 Xmuse Direct 到底往哪个 UDP 端口、哪个
OSC 地址推数据。

用法（在 eeg-focus 根目录）：

    .\.venv-win\Scripts\python.exe scripts\xmuse_osc_probe.py
    .\.venv-win\Scripts\python.exe scripts\xmuse_osc_probe.py --ports 7000 8000 8001 8002

它会同时监听多个端口，收到报文时打印端口 / OSC 地址 / 通道数 / 样本数。
按 Ctrl+C 退出。

注意：HTTP 服务用的是 TCP 8000，OSC 用的是 UDP 8000，两者可以同时存在。
"""

import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.xmuse_osc import DEFAULT_FS, DEFAULT_HOST, XmuseOSCSource  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Xmuse OSC/UDP 端口探针")
    parser.add_argument("--host", default=os.getenv("XMUSE_OSC_HOST", DEFAULT_HOST))
    parser.add_argument("--ports", nargs="+", type=int, default=[7000, 8000],
                        help="要监听的 UDP 端口（默认 7000 8000）")
    parser.add_argument("--fs", type=float, default=float(os.getenv("XMUSE_OSC_FS", DEFAULT_FS)))
    parser.add_argument("--channels", type=int, default=0, help="0=自动推断")
    args = parser.parse_args()

    source = XmuseOSCSource(
        host=args.host,
        ports=args.ports,
        fs=args.fs,
        channels=args.channels,
        connect_timeout=2.0,
    )
    source.start()
    print(f"[probe] 正在监听 UDP {args.host}:{source.ports}")
    print("[probe] 请打开 Xmuse Direct -> 连接设备 -> 添加 OSC 输出 -> IP 127.0.0.1 / 端口 7000")
    print("[probe] Ctrl+C 退出\n")

    last_key = None
    try:
        while True:
            meta = source.snapshot()
            key = (meta["packets"], meta["port"], meta["address"], meta["channels"])
            if key != last_key:
                last_key = key
                print(
                    f"[{time.strftime('%H:%M:%S')}] packets={meta['packets']} "
                    f"port={meta['port']} address={meta['address']} "
                    f"channels={meta['channels']} samples={meta['samples']} "
                    f"age={meta['last_packet_age']}"
                )
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[probe] 停止")
    finally:
        source.stop()


if __name__ == "__main__":
    main()
