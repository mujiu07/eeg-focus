"""
Xmuse 脑电波仪 OSC(UDP) 接收器
=============================

Xmuse Direct / Xmuse Lab 会把脑电数据以 OSC 报文通过 **UDP** 推到本机。
本模块同时监听多个端口，兼容官方资料里出现的全部默认端口：

  * Xmuse Direct 资源默认值：127.0.0.1:7000（DefaultIPAddress / DefaultUdpPort）
  * Xmuse-Coding 示例：/8000/eeg，监听 UDP 8000
  * 多设备示例：8001 / 8002（每台设备一个端口）

地址匹配只要求最后一个路径段是 ``eeg``，因此下面这些写法都能收到：

  /eeg
  /8000/eeg
  /muse/eeg
  /Xmuse/eeg

注意：``/elements/eeg/eeg[0]`` 属于元素信号里的单通道镜像，不在这里消费。

数据窗口：默认 2 s（与 app/features.py 的训练口径一致），步长 0.5 s。
采样率：OSC 报文本身不带采样率，默认按 256 Hz 解释（可用 XMUSE_OSC_FS 覆盖）。
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque

import numpy as np

from . import features

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORTS = "7000,8000"
DEFAULT_FS = 256.0
DEFAULT_CHANNELS = 0  # 0 = 自动推断


def parse_ports(value) -> list[int]:
    """把 "7000,8000" / [7000, 8000] / 7000 统一成端口列表。"""
    if value is None or value == "":
        value = DEFAULT_PORTS
    if isinstance(value, (list, tuple, set)):
        raw = list(value)
    elif isinstance(value, int):
        raw = [value]
    else:
        raw = str(value).replace(";", ",").replace(" ", ",").split(",")
    ports = []
    for item in raw:
        try:
            port = int(str(item).strip())
        except (TypeError, ValueError):
            continue
        if 1 <= port <= 65535 and port not in ports:
            ports.append(port)
    return ports or parse_ports(DEFAULT_PORTS)


def _flatten(args) -> list[float]:
    """OSC 参数可能是 float / int / list / tuple，统一压平为 float 列表。"""
    out: list[float] = []
    for arg in args:
        if isinstance(arg, (list, tuple, np.ndarray)):
            out.extend(_flatten(arg))
        else:
            try:
                out.append(float(arg))
            except (TypeError, ValueError):
                continue
    return out


class XmuseOSCSource:
    """多端口 OSC/UDP 脑电接收器，按窗口产出 (n_ch, n_samples)。"""

    name = "hardware"
    label = "Xmuse 脑电波仪（OSC/UDP）"

    def __init__(
        self,
        host: str | None = None,
        ports=None,
        fs: float | None = None,
        channels: int | None = None,
        window_sec: float | None = None,
        step_sec: float | None = None,
        connect_timeout: float = 8.0,
    ):
        self.host = host or os.getenv("XMUSE_OSC_HOST", DEFAULT_HOST)
        self.ports = parse_ports(ports if ports not in (None, "") else os.getenv("XMUSE_OSC_PORTS"))
        self.fs = float(fs or os.getenv("XMUSE_OSC_FS", DEFAULT_FS))
        self.channels = int(channels or os.getenv("XMUSE_OSC_CHANNELS", DEFAULT_CHANNELS))
        self.window_sec = float(window_sec or features.WINDOW_SEC)
        self.step_sec = float(step_sec or 0.5)
        self.connect_timeout = float(connect_timeout)
        self.ch_names = []

        self._win = max(1, int(round(self.window_sec * self.fs)))
        self._step = max(1, int(round(self.step_sec * self.fs)))

        self._buf: deque[list[float]] = deque(maxlen=self._win)
        self._ready: deque[np.ndarray] = deque(maxlen=2)
        self._cond = threading.Condition()

        self._servers = []
        self._threads = []
        self._bound_ports: list[int] = []
        self._started = False
        self._closed = False
        self._start_error: str | None = None

        self._n_ch: int | None = self.channels or None
        self._last_emit = 0.0
        self._last_packet = 0.0
        self._last_address: str | None = None
        self._last_port: int | None = None
        self._quality: float | None = None
        self._battery: float | None = None
        self._packets = 0
        self._samples = 0
        self._windows = 0

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def start(self):
        """绑定端口并启动后台接收线程（非阻塞）。"""
        if self._started:
            return self

        self._closed = False

        try:
            from pythonosc import dispatcher as osc_dispatcher
            from pythonosc import osc_server
        except ImportError as exc:  # pragma: no cover - 取决于运行环境
            raise RuntimeError(
                "缺少 python-osc，请先执行: pip install -r requirements.txt"
            ) from exc

        errors = []
        for port in self.ports:
            try:
                disp = osc_dispatcher.Dispatcher()
                disp.set_default_handler(
                    lambda address, *args, _port=port: self._on_osc(address, *args, port=_port)
                )
                server = osc_server.ThreadingOSCUDPServer((self.host, port), disp)
            except OSError as exc:
                errors.append(f"UDP {port}: {exc}")
                continue

            thread = threading.Thread(
                target=server.serve_forever,
                name=f"xmuse-osc-{port}",
                daemon=True,
            )
            thread.start()
            self._servers.append(server)
            self._threads.append(thread)
            self._bound_ports.append(port)

        if not self._servers:
            self._start_error = "; ".join(errors) or "没有可用端口"
            raise RuntimeError(
                f"Xmuse OSC 端口绑定失败（{self._start_error}）。"
                "请关闭占用该 UDP 端口的程序，或用 XMUSE_OSC_PORTS 指定其它端口。"
            )

        self._started = True
        return self

    def stop(self):
        self._closed = True
        with self._cond:
            self._cond.notify_all()
        for server in self._servers:
            try:
                server.shutdown()
                server.server_close()
            except Exception:  # noqa: BLE001 - 停止阶段尽力而为
                pass
        for thread in self._threads:
            thread.join(timeout=1.0)
        self._servers.clear()
        self._threads.clear()
        self._started = False

    # ------------------------------------------------------------------
    # OSC 回调
    # ------------------------------------------------------------------
    def _on_osc(self, address, *args, port: int | None = None):
        now = time.time()
        text = str(address or "")
        low = text.lower()
        values = _flatten(args)

        with self._cond:
            self._packets += 1
            self._last_packet = now
            self._last_address = text
            self._last_port = port

            if low.endswith("/eeg") and "/elements/" not in low:
                if values:
                    self._push_values(values, now)
            elif low.endswith("/elements/is_good") or low.endswith("/is_good"):
                if values:
                    self._quality = float(values[0])
            elif low.endswith("/batt") or low.endswith("/battery"):
                if values:
                    self._battery = float(values[0])

    def _push_values(self, values: list[float], now: float):
        """把一条 OSC 报文拆成 1 个或多个样本压入环形缓冲。"""
        if self._n_ch is None:
            if len(values) in (4, 6):
                self._n_ch = len(values)
            elif len(values) > 6 and len(values) % 4 == 0:
                self._n_ch = 4
            else:
                self._n_ch = min(max(len(values), 1), 32)
            self.ch_names = self._default_ch_names(self._n_ch)

        n_ch = self._n_ch
        if n_ch <= 0:
            return

        if len(values) > n_ch and len(values) % n_ch == 0:
            chunks = [values[i:i + n_ch] for i in range(0, len(values), n_ch)]
        else:
            chunks = [(values + [0.0] * n_ch)[:n_ch]]

        for chunk in chunks:
            self._buf.append(chunk)
            self._samples += 1

        if len(self._buf) >= self._win and (now - self._last_emit) >= self.step_sec:
            arr = np.asarray(self._buf, dtype=float).T  # (n_ch, n_samples)
            self._ready.append(arr)
            self._windows += 1
            self._last_emit = now
            self._cond.notify_all()

    @staticmethod
    def _default_ch_names(n_ch: int) -> list[str]:
        base = ["TP9", "AF7", "AF8", "TP10", "AUX1", "AUX2"]
        return [base[i] if i < len(base) else f"CH{i + 1}" for i in range(n_ch)]

    # ------------------------------------------------------------------
    # 供会话/探针读取
    # ------------------------------------------------------------------
    def next_window(self, timeout: float | None = None):
        """阻塞等待一个 2 s 窗口，返回 (seg, meta)。"""
        if not self._started:
            self.start()

        deadline = time.time() + (timeout if timeout is not None else self.connect_timeout)
        with self._cond:
            while not self._ready:
                if self._closed:
                    raise RuntimeError("Xmuse OSC 接收已停止（会话结束）")
                remaining = deadline - time.time()
                if remaining <= 0:
                    age = time.time() - self._last_packet if self._last_packet else None
                    raise RuntimeError(
                        "未收到 Xmuse OSC 脑电数据。请确认：\n"
                        "  1) Xmuse Direct 已连接设备；\n"
                        "  2) 在 Xmuse Direct 的 OSC 输出中填写本机 IP 与端口"
                        f"（当前监听 {self.host}:{self._bound_ports or self.ports}，默认 127.0.0.1:7000）；\n"
                        "  3) 前缀留空或填端口号（地址会变成 /eeg 或 /7000/eeg）。\n"
                        f"已收到报文 {self._packets} 个，最近报文年龄 {age if age is not None else '无'}。"
                    )
                self._cond.wait(remaining)
            seg = self._ready.popleft()

        meta = self.snapshot()
        meta["window"] = self._windows
        meta["samples_in_window"] = int(seg.shape[1])
        return seg, meta

    def snapshot(self) -> dict:
        now = time.time()
        with self._cond:
            age = (now - self._last_packet) if self._last_packet else None
            return {
                "source": self.name,
                "transport": "osc_udp",
                "mode": "xmuse_osc",
                "host": self.host,
                "ports": list(self._bound_ports or self.ports),
                "osc_ports": ",".join(str(p) for p in (self._bound_ports or self.ports)),
                "address": self._last_address,
                "port": self._last_port,
                "fs": self.fs,
                "channels": self._n_ch or 0,
                "ch_names": list(self.ch_names),
                "quality": self._quality,
                "battery": self._battery,
                "packets": self._packets,
                "samples": self._samples,
                "windows": self._windows,
                "last_packet_age": round(age, 3) if age is not None else None,
                "connected": bool(self._started and age is not None and age < 3.0),
            }

    def describe(self) -> dict:
        meta = self.snapshot()
        return {
            "name": self.name,
            "label": self.label,
            "transport": "OSC/UDP",
            "host": meta["host"],
            "ports": meta["ports"],
            "osc_ports": meta["osc_ports"],
            "fs": meta["fs"],
            "channels": meta["channels"],
            "connected": meta["connected"],
            "packets": meta["packets"],
            "samples": meta["samples"],
            "last_packet_age": meta["last_packet_age"],
            "last_error": self._start_error,
        }
