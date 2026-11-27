#!/usr/bin/env python3
"""v1.9.2 真实浏览器 UI 验收（Edge/Chromium CDP）。

前置：
  1. 使用隔离数据目录启动服务，例如
     FOCUS_FROG_DATA_DIR=.deepworks/tmp/v192/data .venv/bin/uvicorn app.server:app --port 8017
  2. 启动带 remote debugging 的 Edge/Chromium，例如
     Microsoft Edge --headless=new --remote-debugging-port=9333 ...
  3. 运行：
     .venv/bin/python tests/browser_ui_v192.py --base http://127.0.0.1:8017 \
       --cdp http://127.0.0.1:9333 --user-id <fixture-B-user-id>

本脚本只读页面；游戏演示/评估会在隔离测试库中创建测试 Session，不触碰真实档案。
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

try:
    import websocket
except Exception as exc:  # pragma: no cover
    print("SKIP: websocket-client 未安装:", exc)
    raise SystemExit(0)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / ".deepworks" / "tmp" / "v192" / "browser-evidence"


def get_json(url: str) -> Any:
    return json.loads(urllib.request.urlopen(url, timeout=10).read().decode("utf-8"))


class CDP:
    def __init__(self, cdp_base: str, url: str):
        self.base = cdp_base.rstrip("/")
        info = get_json(self.base + "/json/version")
        browser_ws = websocket.create_connection(info["webSocketDebuggerUrl"], timeout=30)
        seq = [0]

        def call(method: str, params: dict | None = None):
            seq[0] += 1
            browser_ws.send(json.dumps({"id": seq[0], "method": method, "params": params or {}}))
            while True:
                msg = json.loads(browser_ws.recv())
                if msg.get("id") == seq[0]:
                    if "error" in msg:
                        raise RuntimeError(msg["error"])
                    return msg.get("result", {})

        target = call("Target.createTarget", {"url": url})["targetId"]
        browser_ws.close()
        deadline = time.time() + 5
        target_info = None
        while time.time() < deadline:
            for item in get_json(self.base + "/json/list"):
                if item.get("id") == target:
                    target_info = item
                    break
            if target_info:
                break
            time.sleep(0.1)
        if not target_info:
            raise RuntimeError("找不到新建页面 target")
        self.tid = target
        self.ws = websocket.create_connection(target_info["webSocketDebuggerUrl"], timeout=45)
        self.seq = 0
        self.call("Page.enable")
        self.call("Runtime.enable")
        self.call("Log.enable")

    def call(self, method: str, params: dict | None = None):
        self.seq += 1
        self.ws.send(json.dumps({"id": self.seq, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.seq:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg.get("result", {})

    def eval(self, expression: str, await_promise: bool = False):
        r = self.call("Runtime.evaluate", {
            "expression": expression, "returnByValue": True,
            "awaitPromise": await_promise, "userGesture": True,
        })
        if "exceptionDetails" in r:
            raise RuntimeError(r["exceptionDetails"].get("text") or r["exceptionDetails"])
        return r.get("result", {}).get("value")

    def preload(self, source: str):
        self.call("Page.addScriptToEvaluateOnNewDocument", {"source": source})

    def viewport(self, width: int, height: int):
        self.call("Emulation.setDeviceMetricsOverride", {
            "width": width, "height": height, "deviceScaleFactor": 1, "mobile": False,
        })

    def goto(self, url: str, wait: float = 1.0):
        self.call("Page.navigate", {"url": url})
        time.sleep(wait)

    def shot(self, path: Path, full: bool = False):
        result = self.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": full})
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(result["data"]))

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass
        try:
            urllib.request.urlopen(self.base + "/json/close/" + self.tid, timeout=5).read()
        except Exception:
            pass


class Runner:
    def __init__(self, base: str, cdp_base: str, out: Path, uid: str | None, session_id: str | None):
        self.base = base.rstrip("/")
        self.p = CDP(cdp_base, self.base + "/index.html")
        self.out = out
        self.uid = uid
        self.session_id = session_id
        self.failures: list[str] = []
        self.passes = 0
        self._install_preload()

    def _install_preload(self):
        if self.uid:
            active = json.dumps({"user_id": self.uid, "nickname": "小满", "avatar": "frog"}, ensure_ascii=False)
            self.p.preload(f"localStorage.setItem('bf-active-user', {json.dumps(active)});"
                           "localStorage.setItem('bf-tutorial-done','1');"
                           "localStorage.setItem('bf-dev-tutorial-done','1');")
        self.p.preload("""
        (() => {
          window.__uiErrors = [];
          window.addEventListener('error', e => window.__uiErrors.push(String(e.message || e.error || 'error')));
          window.addEventListener('unhandledrejection', e => window.__uiErrors.push(String(e.reason || 'rejection')));
          const originalFetch = window.fetch;
          window.__fetches = [];
          window.fetch = function() {
            try { window.__fetches.push(String(arguments[0])); } catch (_) {}
            return originalFetch.apply(this, arguments);
          };
          const OriginalES = window.EventSource;
          window.__es = [];
          window.EventSource = function(url, opts) {
            try { window.__es.push(String(url)); } catch (_) {}
            return new OriginalES(url, opts);
          };
          window.EventSource.prototype = OriginalES.prototype;
        })();
        """)

    def check(self, name: str, fn):
        try:
            fn()
            self.passes += 1
            print("PASS", name)
        except Exception as exc:
            self.failures.append(name + ": " + str(exc))
            print("FAIL", name, "—", exc)

    def page_audit_js(self) -> str:
        return r"""
        (() => {
          const visible = e => {
            if (!e) return false;
            const c = getComputedStyle(e), r = e.getBoundingClientRect();
            return c.display !== 'none' && c.visibility !== 'hidden' && r.width > 1 && r.height > 1;
          };
          const texts = [];
          for (const e of document.querySelectorAll('.btn,.growth-link,.sky-opt,.top-link,.home-link')) {
            if (!visible(e) || !e.textContent.trim()) continue;
            const r = e.getBoundingClientRect(), range = document.createRange();
            range.selectNodeContents(e);
            const t = range.getBoundingClientRect();
            if (!t.width) continue;
            const dx = (t.left + t.width / 2) - (r.left + r.width / 2);
            const dy = (t.top + t.height / 2) - (r.top + r.height / 2);
            if (Math.abs(dx) > 2.5 || Math.abs(dy) > 3.5) {
              texts.push({ text: e.textContent.trim().slice(0, 24), dx: +dx.toFixed(1), dy: +dy.toFixed(1) });
            }
          }
          const homeEls = Array.from(document.querySelectorAll('.home-link,#btn-game-home')).filter(visible);
          const home = homeEls.map(e => e.textContent.trim().replace(/\s+/g, ' '));
          const homeRects = homeEls.map(e => { const r=e.getBoundingClientRect(); return {x:r.x,y:r.y}; });
          const musicEl = document.querySelector('.vinyl-player');
          let music = null;
          if (musicEl) {
            const r = musicEl.getBoundingClientRect(), c = getComputedStyle(musicEl);
            music = { x:r.x, y:r.y, w:r.width, h:r.height, z:c.zIndex, pos:c.position,
                      display:c.display, visible: visible(musicEl) };
          }
          return {
            title: document.title,
            scrollWidth: document.documentElement.scrollWidth,
            innerWidth: innerWidth,
            home, homeRects, music,
            centerFailures: texts,
            errors: window.__uiErrors || [],
          };
        })()
        """

    def audit_page(self, name: str, path: str, width: int, height: int, gate: bool = False) -> dict:
        self.p.viewport(width, height)
        self.p.goto(self.base + path, 1.0 if name not in ("growth", "parent", "dev") else 1.4)
        if gate:
            try:
                self.p.eval("document.getElementById('parent-gate-ok')?.click()")
                time.sleep(0.25)
            except Exception:
                pass
        info = self.p.eval(self.page_audit_js())
        self.check(f"{name} {width}px 无横向滚动", lambda: self._assert(info["scrollWidth"] <= info["innerWidth"] + 1,
                                                                        f"{info['scrollWidth']} > {info['innerWidth']}"))
        self.check(f"{name} {width}px 按钮内容居中", lambda: self._assert(not info["centerFailures"],
                                                                          str(info["centerFailures"])))
        self.check(f"{name} {width}px 无未捕获脚本错误", lambda: self._assert(not info["errors"], str(info["errors"])))
        if name != "index":
            self.check(f"{name} {width}px 有首页入口", lambda: self._assert(any("首页" in x for x in info["home"]),
                                                                          str(info["home"])))
            self.check(f"{name} {width}px 首页入口位于页面上部左侧", lambda: self._assert(
                all(r["x"] < info["innerWidth"] / 2 and r["y"] < 220 for r in info["homeRects"]),
                str(info["homeRects"])))
        if info["music"]:
            self.check(f"{name} {width}px 音乐控件可见且位于上层", lambda: self._assert(
                info["music"]["visible"] and int(info["music"]["z"] or 0) >= 1, str(info["music"])))
        return info

    @staticmethod
    def _assert(condition, message=""):
        if not condition:
            raise AssertionError(message)

    def run_pages(self):
        pages = [
            ("index", "/index.html", False),
            ("profiles", "/profiles.html", False),
            ("calibrate", "/calibrate.html", False),
            ("growth", "/growth.html", False),
            ("parent", "/parent.html", True),
            ("settings", "/settings.html", False),
            ("dev", "/dev.html", False),
        ]
        if self.session_id:
            pages += [
                ("history", f"/history.html?id={self.session_id}", False),
                ("report", f"/report.html?id={self.session_id}", False),
            ]
        for width, height in [(1920, 1080), (1440, 900), (1280, 800), (1024, 768), (800, 600),
                              (1536, 864), (1280, 720), (1152, 720), (960, 600)]:
            for name, path, gate in pages:
                self.audit_page(name, path, width, height, gate)
                if width in (1440, 800) and name in ("index", "profiles", "calibrate", "growth", "parent",
                                                     "settings", "dev", "report", "history"):
                    self.p.shot(self.out / f"after-{name}-{width}.png")

    def game_test(self):
        self.p.viewport(1440, 900)
        self.p.goto(self.base + "/dev.html", 1.2)
        self.p.eval("Array.from(document.querySelectorAll('a')).find(a => a.textContent.includes('无设备试玩')).click()")
        time.sleep(3.0)
        # 关闭教学层，启动倒计时，证明切换侧栏不会重置计时。
        self.p.eval("document.getElementById('tutorial-ok')?.click()")
        time.sleep(5.0)
        before = self.p.eval("""(() => ({
          es: window.__es.slice(),
          sessionPosts: window.__fetches.filter(x => String(x).endsWith('/api/session')).length,
          timer: document.getElementById('timer').textContent,
          score: document.getElementById('score').textContent,
          canvas: +document.getElementById('game-canvas').getBoundingClientRect().width.toFixed(1)
        }))()""")
        self.check("游戏开始后建立且只建立一条游戏流与一条监测流",
                   lambda: self._assert(
                       sum('/stream' in x for x in before["es"]) == 1
                       and sum('/monitor' in x for x in before["es"]) == 1,
                       str(before["es"])))
        self.check("游戏开始后 Canvas 有有效宽度", lambda: self._assert(before["canvas"] > 300, str(before["canvas"])))

        # 四种布局状态截图与几何检查
        states = [("all", None), ("left-off", "left"), ("both-off", "right"), ("right-off", "left"), ("all-again", "right")]
        for label, side in states:
            if side:
                self.p.eval(f"document.querySelector('[data-monitor-show=\"{side}\"]').click()")
                time.sleep(0.3)
            geo = self.p.eval("""(() => {
              const r = e => { if (!e) return null; const b = e.getBoundingClientRect(); return {x:b.x,y:b.y,w:b.width,h:b.height}; };
              const overlap = (a,b) => a && b && !(a.x+a.w <= b.x || b.x+b.w <= a.x || a.y+a.h <= b.y || b.y+b.h <= a.y);
              const music = r(document.querySelector('.vinyl-player'));
              const right = r(document.getElementById('monitor-right'));
              const hud = r(document.querySelector('.hud'));
              const energy = r(document.querySelector('.energy-track'));
              return { cls: document.getElementById('game-layout').className, main: r(document.querySelector('.game-main')),
                       canvas: r(document.getElementById('game-canvas')), music,
                       overlapRight: overlap(music,right), overlapHud: overlap(music,hud), overlapEnergy: overlap(music,energy) };
            })()""")
            self.p.shot(self.out / f"after-game-{label}-1440.png")
            self.check(f"游戏布局 {label} Canvas 宽度有效", lambda g=geo: self._assert(g["canvas"]["w"] > 300, str(g["canvas"])))
            self.check(f"游戏布局 {label} 音乐不覆盖工作台/积分/蓄力", lambda g=geo: self._assert(
                not g["overlapRight"] and not g["overlapHud"] and not g["overlapEnergy"], str(g)))

        # 20 次连续切换
        widths = []
        for i in range(20):
            side = "left" if i % 2 == 0 else "right"
            self.p.eval(f"document.querySelector('[data-monitor-show=\"{side}\"]').click()")
            time.sleep(0.06)
            widths.append(self.p.eval("document.getElementById('game-canvas').getBoundingClientRect().width"))
        after = self.p.eval("""(() => ({
          es: window.__es.slice(),
          sessionPosts: window.__fetches.filter(x => String(x).endsWith('/api/session')).length,
          timer: document.getElementById('timer').textContent,
          score: document.getElementById('score').textContent
        }))()""")
        self.check("连续 20 次侧栏切换画布始终有效", lambda: self._assert(min(widths) > 300, str(min(widths))))
        self.check("连续 20 次侧栏切换不新建 Session/SSE",
                   lambda: self._assert(after["sessionPosts"] == before["sessionPosts"] and after["es"] == before["es"],
                                        f"{before['sessionPosts']}->{after['sessionPosts']} / {before['es']}->{after['es']}"))
        self.check("连续 20 次侧栏切换不重置积分", lambda: self._assert(after["score"] == before["score"], after["score"]))
        self.check("连续 20 次侧栏切换不重置计时", lambda: self._assert(after["timer"] != "01:00" or before["timer"] == "01:00",
                                                                        f"{before['timer']}->{after['timer']}"))

        # 不同窗口及缩放等效宽度：游戏仍可操作，音乐与小屏布局不产生横向滚动
        for width, height in [(1920, 1080), (1280, 800), (1152, 720), (1024, 768), (960, 600), (800, 600)]:
            self.p.viewport(width, height)
            time.sleep(0.5)
            info = self.p.eval("""(() => {
              const r = e => e.getBoundingClientRect();
              const c = document.getElementById('game-canvas'), m = document.querySelector('.game-main');
              const musicEl = document.querySelector('.vinyl-player');
              const mc = getComputedStyle(musicEl), mr = r(musicEl);
              const home = document.getElementById('btn-game-home').getBoundingClientRect();
              return { canvas: r(c).width, main: r(m).width, sw: document.documentElement.scrollWidth,
                       iw: innerWidth, music: {x:mr.x,y:mr.y,w:mr.width,h:mr.height,z:mc.zIndex,visible:mc.display!=='none'&&mc.visibility!=='hidden'},
                       home: {x:home.x,y:home.y} };
            })()""")
            self.check(f"游戏 {width}px 无横向滚动", lambda i=info: self._assert(i["sw"] <= i["iw"] + 1, str(i)))
            self.check(f"游戏 {width}px Canvas 可操作", lambda i=info: self._assert(i["canvas"] > 250, str(i)))
            self.check(f"游戏 {width}px 首页入口在左上", lambda i=info: self._assert(
                i["home"]["x"] < i["iw"] / 2 and i["home"]["y"] < 220, str(i["home"])))
            self.check(f"游戏 {width}px 音乐控件可见", lambda i=info: self._assert(
                i["music"]["visible"] and i["music"]["w"] > 40, str(i["music"])))
            self.p.shot(self.out / f"after-game-{width}.png")

    def run(self):
        self.run_pages()
        self.game_test()
        print(f"\n浏览器验收：{self.passes} passed, {len(self.failures)} failed")
        if self.failures:
            for f in self.failures:
                print(" -", f)
            return 1
        return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8017")
    ap.add_argument("--cdp", default="http://127.0.0.1:9333")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--user-id", default=None)
    ap.add_argument("--session-id", default=None)
    args = ap.parse_args()
    uid = args.user_id
    if not uid:
        fixture = ROOT / ".deepworks/tmp/v192/data/fixture.json"
        if fixture.exists():
            uid = json.loads(fixture.read_text(encoding="utf-8")).get("users", {}).get("B", {}).get("user_id")
    if not args.session_id and uid:
        try:
            req = urllib.request.Request(args.base.rstrip("/") + "/api/player/recent",
                                         headers={"X-User-Id": uid})
            recent = json.loads(urllib.request.urlopen(req, timeout=10).read().decode("utf-8"))
            args.session_id = (recent.get("reports") or [{}])[0].get("session_id")
        except Exception:
            pass
    runner = Runner(args.base, args.cdp, Path(args.out), uid, args.session_id)
    try:
        return runner.run()
    finally:
        runner.p.close()


if __name__ == "__main__":
    raise SystemExit(main())
