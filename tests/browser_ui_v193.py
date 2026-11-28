#!/usr/bin/env python3
"""v1.9.3 全站视觉验收（真实 Edge/Chromium CDP）。

只访问隔离服务（默认 8017）和隔离数据目录；不写入真实档案。
覆盖：1920/1440/1280/1024/800，五类尺寸下的所有页面；
商城、装扮、成就、时长、档案、成就过场等主要弹窗；青蛙几何一致性、图标挂载、边框层级和横向滚动。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_ui_v192 import CDP, get_json  # noqa: E402

DEFAULT_OUT = ROOT / "outputs" / "v1.9.3" / "after"
PAGES = [
    ("index", "/index.html", False, 0),
    ("profiles", "/profiles.html", False, 1),
    ("growth", "/growth.html", False, 2),
    ("parent", "/parent.html", True, 0),
    ("calibrate", "/calibrate.html", False, 1),
    ("settings", "/settings.html", False, 0),
    ("dev", "/dev.html", False, 0),
    ("game", "/game.html?demo=1", False, 0),
    ("report", "/report.html?id=s_472e41_11100900_12", False, 2),
    ("history", "/history.html?id=s_472e41_11100900_12", False, 0),
]
SIZES = [(1920, 1080), (1440, 900), (1280, 800), (1024, 768), (800, 600)]

EMOJI = r"[\u{1F000}-\u{1FAFF}\u2600-\u27BF]"
PAGE_JS = r"""
(() => {
  const visible = e => {
    if (!e) return false;
    const c = getComputedStyle(e), r = e.getBoundingClientRect();
    return c.display !== 'none' && c.visibility !== 'hidden' && r.width > 1 && r.height > 1;
  };
  const emoji = /%s/u;
  const labelled = [...document.querySelectorAll(
    '.home-link,.top-link,.growth-link,.btn,.sky-opt,.section-title,.frog-dot,.logo-badge,.checkbox,.stat .icon,.ach-head__icon'
  )].filter(visible);
  const emojiText = labelled.map(e => e.textContent.trim()).filter(t => t && emoji.test(t));
  const homeEls = [...document.querySelectorAll('.home-link,#btn-game-home')].filter(visible);
  const home = homeEls.map(e => { const r = e.getBoundingClientRect(); return {x:r.x,y:r.y}; });
  const frogs = [...document.querySelectorAll('.frog-art')];
  const frogFailures = frogs.map((f, i) => ({
    i, eyes: f.querySelectorAll('.frog-eye').length, wraps: f.querySelectorAll('.frog-eye-wrap').length,
    mouth: f.querySelectorAll('.frog-mouth').length, boxes: [...f.querySelectorAll('.frog-eye-wrap')].map(w => w.getBoundingClientRect().toJSON())
  })).filter(x => x.eyes !== 2 || x.wraps !== 2 || x.mouth < 1);
  const unmounted = [...document.querySelectorAll('[data-icon]')].filter(e => !e.querySelector('svg')).length;
  const nestedBorders = [];
  for (const el of document.querySelectorAll('.profile-card:not(.is-current),.growth-stat,.parent-kpi,.chart-box,.stat-box,.tutorial-card,.detail-item,.ach-item')) {
    const c = getComputedStyle(el);
    if (parseFloat(c.borderTopWidth) >= 1.5 && c.borderTopStyle !== 'none' &&
        !getComputedStyle(el).borderTopColor.includes('rgba(0, 0, 0, 0)')) {
      nestedBorders.push({ cls: el.className, w: c.borderTopWidth, color: c.borderTopColor });
    }
  }
  return {
    width: innerWidth, scrollWidth: document.documentElement.scrollWidth,
    home, emojiText, frogFailures, frogs: frogs.length, unmounted,
    nestedBorders, errors: window.__v193Errors || [],
    homeFrog: (() => {
      const art = document.getElementById('pondFrogArtwork');
      return art ? { ellipses: art.querySelectorAll('ellipse').length, paths: art.querySelectorAll('path').length } : null;
    })()
  };
})()
""" % EMOJI


class Runner:
    def __init__(self, base: str, cdp: str, out: Path):
        self.base = base.rstrip("/")
        self.out = out
        self.p = CDP(cdp, self.base + "/index.html")
        self.passes = 0
        self.failures: list[str] = []
        self._install()

    def _install(self):
        self.p.preload("""
        localStorage.setItem('bf-active-user', JSON.stringify({user_id:'u_6e1463472e41', nickname:'小满', avatar:'frog'}));
        localStorage.setItem('bf-tutorial-done','1');
        localStorage.setItem('bf-dev-tutorial-done','1');
        localStorage.setItem('bf-sky-mode','day');
        sessionStorage.setItem('bf-dev-testing','1');
        window.__v193Errors = [];
        addEventListener('error', e => window.__v193Errors.push(String(e.message || e.error || 'error')));
        addEventListener('unhandledrejection', e => window.__v193Errors.push(String(e.reason || 'rejection')));
        """)

    def check(self, name, fn):
        try:
            fn()
            self.passes += 1
            print("PASS", name)
        except Exception as exc:
            self.failures.append(name + ": " + str(exc))
            print("FAIL", name, "—", exc)

    @staticmethod
    def _assert(condition, message=""):
        if not condition:
            raise AssertionError(message)

    def page(self, width, height, name, path, gate, frogs):
        self.p.viewport(width, height)
        self.p.goto(self.base + path, 1.2 if name not in ("growth", "parent", "dev") else 1.5)
        if gate:
            self.p.eval("document.getElementById('parent-gate-ok')?.click()")
            time.sleep(.3)
        info = self.p.eval(PAGE_JS)
        self.check(f"{name} {width} 无横向滚动", lambda: self._assert(info["scrollWidth"] <= width + 1, info))
        self.check(f"{name} {width} 无脚本错误", lambda: self._assert(not info["errors"], info["errors"]))
        self.check(f"{name} {width} 无功能性 Emoji", lambda: self._assert(not info["emojiText"], info["emojiText"]))
        self.check(f"{name} {width} 图标全部挂载", lambda: self._assert(info["unmounted"] == 0, info["unmounted"]))
        if name != "index":
            self.check(f"{name} {width} 首页入口在左上", lambda: self._assert(
                info["home"] and all(h["x"] < width / 2 and h["y"] < 230 for h in info["home"]), info["home"]))
        if frogs:
            self.check(f"{name} {width} 小蛙出现", lambda: self._assert(info["frogs"] >= frogs, info["frogs"]))
            self.check(f"{name} {width} 小蛙双眼/嘴巴完整", lambda: self._assert(not info["frogFailures"], info["frogFailures"]))
        if name == "index":
            self.check("首页标准青蛙未被替换", lambda: self._assert(
                info["homeFrog"] and info["homeFrog"]["ellipses"] >= 9 and info["homeFrog"]["paths"] >= 1, info["homeFrog"]))
        if name in ("profiles", "growth", "parent", "settings"):
            self.check(f"{name} {width} 子卡无重复硬描边", lambda: self._assert(not info["nestedBorders"], info["nestedBorders"]))
        self.p.shot(self.out / str(width) / f"{name}.png")
        return info

    def run_pages(self):
        for width, height in SIZES:
            for name, path, gate, frogs in PAGES:
                self.page(width, height, name, path, gate, frogs)
        # 弹窗只在两个关键宽度截取，作为人工视觉审查材料
        for width, height in [(1440, 900), (800, 600)]:
            self.p.viewport(width, height)
            self.p.goto(self.base + "/index.html", 1.0)
            self.p.eval("window.DressUp && DressUp.open()"); time.sleep(.5)
            self.p.shot(self.out / str(width) / "modal-dress.png")
            self.p.eval("document.querySelector('.dress-close')?.click()"); time.sleep(.2)
            self.p.eval("window.Shop && Shop.open()"); time.sleep(.5)
            self.p.shot(self.out / str(width) / "modal-shop.png")
            self.p.eval("document.querySelector('#shop-close')?.click()"); time.sleep(.2)
            self.p.eval("window.Achievements && Achievements.open && Achievements.open()"); time.sleep(.5)
            self.p.shot(self.out / str(width) / "modal-achievements.png")
            self.p.eval("document.querySelector('#ach-close')?.click()"); time.sleep(.2)
            # 时长选择与档案新建也是儿童会看到的主要弹窗
            self.p.goto(self.base + "/index.html", 1.0)
            self.p.eval("document.getElementById('duration-mask')?.classList.remove('hidden')"); time.sleep(.35)
            self.p.shot(self.out / str(width) / "modal-duration.png")
            self.p.eval("document.getElementById('duration-mask')?.classList.add('hidden')"); time.sleep(.2)
            self.p.goto(self.base + "/profiles.html", 1.0)
            self.p.eval("document.getElementById('btn-new')?.click()"); time.sleep(.35)
            self.p.shot(self.out / str(width) / "modal-profile.png")
            self.p.eval("document.getElementById('btn-modal-cancel')?.click()"); time.sleep(.2)
            # 成就过场单独截图；脚本会在这里切到 burst 微笑欢呼阶段
            self.p.goto(self.base + "/game.html?demo=1", 1.2)
            self.p.eval("window.AchievementCinematic && AchievementCinematic.play([{name:'专注小达人',desc:'持续游玩 1 分钟',icon:'star'}])")
            time.sleep(3.8)
            self.p.shot(self.out / str(width) / "modal-achievement-cinematic.png")
            self.p.eval("window.AchievementCinematic && AchievementCinematic.stop()")
            # 历史报告错误态：缺少 session id，用于检查空/错误提示的留白与图标
            self.p.goto(self.base + "/history.html", 1.2)
            self.p.shot(self.out / str(width) / "state-history-error.png")

    def run(self):
        self.run_pages()
        print(f"\nv1.9.3 视觉验收：{self.passes} passed, {len(self.failures)} failed")
        for f in self.failures:
            print(" -", f)
        return 1 if self.failures else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8017")
    ap.add_argument("--cdp", default="http://127.0.0.1:9333")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()
    r = Runner(args.base, args.cdp, Path(args.out))
    try:
        return r.run()
    finally:
        r.p.close()


if __name__ == "__main__":
    raise SystemExit(main())
