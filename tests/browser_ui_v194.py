#!/usr/bin/env python3
"""v1.9.4 真实浏览器体验验收（Edge/Chromium CDP）。

只访问隔离服务（默认 8020）和隔离数据目录；不写真实档案。
覆盖：1920/1440/1280/1024/800 下的档案头像、家长中心留白、校准池塘、
开发者侧栏四种组合与连续切换、开始动画小蛙、子弹时间渐变、商城新价格。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from browser_ui_v192 import CDP  # noqa: E402

SIZES = [(1920, 1080), (1440, 900), (1280, 800), (1024, 768), (800, 600)]
DEFAULT_OUT = ROOT / ".deepworks" / "tmp" / "v194" / "browser"


def get(url):
    return json.loads(urllib.request.urlopen(url, timeout=10).read().decode())


class Runner:
    def __init__(self, base, cdp_base, out, uid):
        self.base = base.rstrip("/")
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.uid = uid
        self.cdp = CDP(cdp_base, self.base + "/index.html")
        self.passed = 0
        self.failed = []
        self.evidence = {}
        self.cdp.preload("try{sessionStorage.setItem('bf-dev-testing','1');sessionStorage.setItem('bf-dev-tutorial-done','1')}catch(e){}"
                         ";try{const OE=window.EventSource;window.__esCount=0;window.EventSource=function(u,c){window.__esCount++;return new OE(u,c)};window.EventSource.prototype=OE.prototype;}catch(e){}")

    def check(self, name, cond, detail=""):
        if cond:
            self.passed += 1
            print("PASS", name)
        else:
            self.failed.append(name)
            print("FAIL", name, detail)

    def shot(self, name):
        self.cdp.shot(self.out / f"{name}.png")

    def inject_profile(self):
        data = get(f"{self.base}/api/profiles/{self.uid}/bootstrap")
        payload = json.dumps({"user_id": data["user"]["user_id"], "nickname": data["user"]["nickname"],
                              "avatar": data["user"]["avatar"], "selected_at": int(time.time() * 1000)},
                             ensure_ascii=False)
        self.cdp.preload("localStorage.setItem('bf-active-user', %s)" % json.dumps(payload))

    def horizontal_ok(self):
        return self.cdp.eval("document.documentElement.scrollWidth <= innerWidth + 1")

    # ---------------------------------------------------------------- pages
    def profiles_and_avatars(self):
        self.cdp.goto(self.base + "/profiles.html", 1.5)
        self.check("档案页无横向滚动", self.horizontal_ok())
        metrics = self.cdp.eval("""(() => {
          const cards = [...document.querySelectorAll('.profile-card')];
          const sizes = cards.map(c => {
            const av = c.querySelector('.profile-avatar').getBoundingClientRect();
            const badge = c.querySelector('.avatar-badge').getBoundingClientRect();
            const svg = c.querySelector('.avatar-badge svg').getBoundingClientRect();
            return {w: Math.round(av.width), h: Math.round(av.height),
                    badge: Math.round(badge.width),
                    cx: Math.round(svg.x + svg.width/2 - (av.x + av.width/2)),
                    cy: Math.round(svg.y + svg.height/2 - (av.y + av.height/2))};
          });
          return {count: cards.length, sizes,
                  radius: getComputedStyle(document.querySelector('.profile-avatar')).borderRadius};
        })()""")
        self.evidence["profiles"] = metrics
        self.check("档案头像存在", metrics["count"] > 0, metrics)
        self.check("头像尺寸一致", len({(x["w"], x["h"], x["badge"]) for x in metrics["sizes"]}) == 1,
                   metrics["sizes"])
        self.check("头像图案视觉居中", all(abs(x["cx"]) <= 1 and abs(x["cy"]) <= 1 for x in metrics["sizes"]),
                   metrics["sizes"])
        self.shot("profiles-1440")
        self.cdp.eval("document.getElementById('btn-new').click()")
        time.sleep(0.4)
        self.shot("avatar-picker-1440")
        self.cdp.eval("document.getElementById('btn-modal-cancel').click()")

    def parent_spacing(self):
        # 只清除本页 gate，不修改服务端数据。
        self.cdp.goto(self.base + "/parent.html", 1.4)
        self.cdp.eval("try{sessionStorage.setItem('bf-parent-ok','1')}catch(e){}")
        self.cdp.goto(self.base + "/parent.html", 1.6)
        time.sleep(1.4)
        self.check("家长页无横向滚动", self.horizontal_ok())
        m = self.cdp.eval("""(() => {
          const kids = [...document.querySelectorAll('#parent-content > *')];
          const gaps = kids.slice(1).map((e,i) => Math.round(e.getBoundingClientRect().top - kids[i].getBoundingClientRect().bottom));
          const boxes = [...document.querySelectorAll('#parent-content .chart-box')].map(e => {
            const c = getComputedStyle(e); return {border: c.borderTopWidth, pad: c.padding};
          });
          return {gaps, boxes, contentVisible: !document.getElementById('parent-content').classList.contains('hidden')};
        })()""")
        self.evidence["parent"] = m
        self.check("家长内容已加载", m["contentVisible"])
        self.check("家长卡片间距至少 16px", m["gaps"] and min(m["gaps"]) >= 16, m["gaps"])
        self.check("图表卡无重复硬描边", all(float(x["border"].replace("px", "")) == 0 for x in m["boxes"]),
                   m["boxes"])
        self.check("图表内部留白 18px+", all("18px" in x["pad"] for x in m["boxes"]), m["boxes"])

    def calibrate_page(self):
        self.cdp.goto(self.base + "/calibrate.html?test=manual", 1.5)
        self.check("校准页无外部视频", self.cdp.eval("!document.querySelector('video')"))
        self.check("校准页存在固定池塘", self.cdp.eval("!!document.getElementById('calm-pond')"))
        self.cdp.eval("document.getElementById('btn-start').click()")
        time.sleep(3.0)
        self.cdp.shot(self.out / "calibrate-calm-1440.png")
        guide = self.cdp.eval("document.getElementById('guide').textContent")
        self.check("平静阶段文案正确", guide.startswith("陪小蛙休息一会儿。自然呼吸"), guide)
        music = self.cdp.eval("window.vinylPlayer ? window.vinylPlayer.debugTime() : null")
        self.evidence["music_during_calm"] = music
        self.check("平静阶段音乐未在播放", not music or not music.get("playing"), music)
        # 取消/离开时恢复音乐设置由 selfcheck_v194 静态契约与手工流程覆盖。

    def game_layout(self):
        self.cdp.viewport(1920, 1080)
        self.cdp.goto(self.base + "/game.html?demo=1&dev=1&sec=60", 2.0)
        self.check("开始动画卡片已出现", self.cdp.eval("document.getElementById('start-cue').classList.contains('show')"))
        cue = self.cdp.eval("""(() => {
          const c = document.querySelector('#start-cue .cue-frog');
          const x = c.getContext('2d');
          const d = x.getImageData(0, 0, c.width, c.height).data;
          let n = 0; for (let i = 3; i < d.length; i += 4) if (d[i] > 10) n++;
          return {w: c.width, h: c.height, opaque: n};
        })()""")
        self.evidence["start_cue_frog"] = cue
        self.check("开始动画水波中央有小蛙", cue["opaque"] > 150, cue)
        self.shot("game-start-cue-1920")
        time.sleep(3.0)
        self.cdp.eval("document.documentElement.classList.add('debug-hud')")
        time.sleep(0.6)
        self.shot("game-dev-both-1920")
        before = self.cdp.eval("({t:timer.textContent,s:score.textContent,streams:window.__esCount||0})")
        self.check("两侧栏打开时顶部栏为 900px",
                   int(self.cdp.eval("Math.round(document.querySelector('.game-main > .card').getBoundingClientRect().width)")) == 900)
        self.cdp.eval("document.getElementById('monitor-hide-left').click()")
        time.sleep(0.5)
        self.cdp.eval("document.getElementById('monitor-hide-right').click()")
        time.sleep(0.8)
        self.shot("game-dev-none-1920")
        after = self.cdp.eval("({t:timer.textContent,s:score.textContent,streams:window.__esCount||0})")
        widths = self.cdp.eval("""(() => {const r=s=>Math.round(document.querySelector(s).getBoundingClientRect().width);
          return {hud:r('.game-main > .card'), main:r('.game-main'), canvas:r('.canvas-wrap'), skybar:r('.page-skybar')};})()""")
        self.evidence["game_none"] = {"widths": widths, "before": before, "after": after}
        self.check("关闭两侧栏后顶部栏不超过 1120px", widths["hud"] <= 1120 and widths["skybar"] <= 1120, widths)
        self.check("关闭侧栏后画布仍为完整宽度", widths["canvas"] >= 1100, widths)
        self.check("切换侧栏不重置计时", before["t"] == after["t"] or after["t"] <= before["t"], (before, after))
        self.check("切换侧栏不丢积分", before["s"] == after["s"], (before, after))
        self.check("切换侧栏不新增 SSE 连接", after["streams"] == before["streams"] and before["streams"] >= 1, (before, after))

        # 连续切换四种组合，检查画布、计时、积分和 SSE 稳定。
        seq = [
            ("both", "document.getElementById('monitor-hide-left').click();document.getElementById('monitor-hide-right').click()"),
            ("left-only", "document.getElementById('monitor-hide-right').click()"),
            ("right-only", "document.getElementById('monitor-hide-left').click();document.getElementById('monitor-hide-right').click()"),
            ("none", "document.getElementById('monitor-hide-left').click()"),
        ]
        stable = True
        for name, js in seq:
            self.cdp.eval(js)
            time.sleep(0.45)
            w = self.cdp.eval("document.querySelector('.canvas-wrap').getBoundingClientRect().width")
            s = self.cdp.eval("score.textContent")
            st = self.cdp.eval("window.__esCount||0")
            if w < 700 or s != before["s"] or st != before["streams"]:
                stable = False
        self.check("连续切换四种侧栏组合保持稳定", stable)
        # 子弹时间渐变
        found = False
        for _ in range(160):
            if self.cdp.eval("state.phase") == "BULLET_TIME":
                found = True
                break
            time.sleep(0.1)
        if found:
            time.sleep(0.3)
            dim = self.cdp.eval("state.bulletDim")
            self.shot("game-bullet-1920")
            self.check("子弹时间渐变达到不透明度目标", dim > 0.9, dim)
        else:
            self.check("进入子弹时间", False, "60s 内未进入金色区域")
        self.cdp.goto(self.base + "/game.html?demo=1&dev=1&sec=60", 2.0)
        time.sleep(3.2)
        self.cdp.eval("document.documentElement.classList.add('debug-hud')")
        self.cdp.eval("document.getElementById('monitor-hide-left').click();document.getElementById('monitor-hide-right').click()")
        time.sleep(0.6)
        self.shot("game-dev-none-1920-final")


    def game_sizes(self):
        for w, h in SIZES:
            self.cdp.viewport(w, h)
            self.cdp.goto(self.base + "/game.html?demo=1&dev=1&sec=60", 1.6)
            # 直接收起两侧面板（小屏默认已收起），验证四种组合中最宽的状态。
            self.cdp.eval("try{document.getElementById('monitor-hide-left')?.click();document.getElementById('monitor-hide-right')?.click()}catch(e){}")
            time.sleep(0.4)
            m = self.cdp.eval("""(() => {const r=s=>{const e=document.querySelector(s);return e?Math.round(e.getBoundingClientRect().width):0};
              return {wrap:r('.wrap'), main:r('.game-main'), hud:r('.game-main > .card'), canvas:r('.canvas-wrap'), skybar:r('.page-skybar')};})()""")
            self.check(f"开发者游戏 {w} 无横向滚动", self.horizontal_ok(), m)
            self.check(f"开发者游戏 {w} 画布占满主列", m["canvas"] >= min(720, w - 60), m)
            if w in (1440, 800):
                self.cdp.shot(self.out / f"game-dev-none-{w}.png")
        self.cdp.viewport(1440, 900)

    def shop_sizes(self):
        for w, h in [(1440, 900), (800, 600)]:
            self.cdp.viewport(w, h)
            self.cdp.goto(self.base + "/index.html", 1.4)
            self.cdp.eval("document.getElementById('shop-open').click()")
            time.sleep(0.6)
            self.check(f"商城 {w} 无横向滚动", self.horizontal_ok())
            self.cdp.shot(self.out / f"shop-{w}.png")

    def shop(self):
        self.cdp.viewport(1440, 900)
        self.cdp.goto(self.base + "/index.html", 1.6)
        self.cdp.eval("document.getElementById('shop-open').click()")
        time.sleep(0.8)
        self.shot("shop-1440")
        prices = self.cdp.eval("""(() => [...document.querySelectorAll('.shop-card__price')]
          .map(e => e.textContent).filter(t => /^\\d+\\s*分$/.test(t.trim())).map(t => parseInt(t)))()""")
        self.evidence["shop_prices"] = prices
        self.check("商城显示新价格", prices and min(prices) >= 24 and max(prices) <= 240, prices)

    def run(self):
        for w, h in SIZES:
            self.cdp.viewport(w, h)
            self.cdp.goto(self.base + "/profiles.html", 1.2)
            self.check(f"档案页 {w} 无横向滚动", self.horizontal_ok())
            self.cdp.goto(self.base + "/calibrate.html", 1.0)
            self.check(f"校准页 {w} 无横向滚动", self.horizontal_ok())
            self.cdp.goto(self.base + "/parent.html", 1.0)
            self.cdp.eval("try{sessionStorage.setItem('bf-parent-ok','1')}catch(e){}")
            self.cdp.goto(self.base + "/parent.html", 1.5)
            time.sleep(1.2)
            self.check(f"家长页 {w} 无横向滚动", self.horizontal_ok())
            if w in (1440, 800):
                self.cdp.shot(self.out / f"parent-{w}.png")
        self.cdp.viewport(1440, 900)
        self.inject_profile()
        self.profiles_and_avatars()
        self.parent_spacing()
        self.calibrate_page()
        self.game_layout()
        self.game_sizes()
        self.shop_sizes()
        self.shop()

    def report(self):
        data = {"passed": self.passed, "failed": self.failed, "evidence": self.evidence}
        (self.out / "result.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"passed": self.passed, "failed": self.failed}, ensure_ascii=False))
        return 1 if self.failed else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8020")
    ap.add_argument("--cdp", default="http://127.0.0.1:9333")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--user-id", default="u_5e38d8e88f9e")
    args = ap.parse_args()
    runner = Runner(args.base, args.cdp, args.out, args.user_id)
    try:
        runner.run()
        return runner.report()
    finally:
        runner.cdp.close()


if __name__ == "__main__":
    raise SystemExit(main())
