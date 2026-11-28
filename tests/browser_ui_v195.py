#!/usr/bin/env python3
"""v1.9.5 真实浏览器验收：九宫格头像 + 背景可读性。

只访问隔离服务（默认 8020）和隔离数据目录；不写真实档案。
截图与 JSON 证据写入 --out（默认 .deepworks/tmp/v195/browser）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from browser_ui_v192 import CDP  # noqa: E402

DEFAULT_OUT = ROOT / ".deepworks" / "tmp" / "v195" / "browser"
PAGES = ["index", "profiles", "calibrate", "growth", "parent", "dev", "settings", "history", "report"]
MODES = ["day", "dusk", "night"]
IGNORE = (".mon-control", ".monitor-toggles")


def get(url):
    return json.loads(urllib.request.urlopen(url, timeout=10).read().decode())


def lum(rgb):
    def f(v):
        v = v / 255
        return v / 12.92 if v <= .03928 else ((v + .055) / 1.055) ** 2.4
    r, g, b = rgb
    return .2126 * f(r) + .7152 * f(g) + .0722 * f(b)


def contrast(a, b):
    x, y = sorted((lum(a), lum(b)), reverse=True)
    return (x + .05) / (y + .05)


def parse_color(value):
    m = re.match(r"rgba?\(([^)]+)\)", value or "")
    if not m:
        return None
    xs = [float(x.strip()) for x in m.group(1).split(",")]
    return xs[:3], (xs[3] if len(xs) > 3 else 1)


def pixel(img, rect, fx, fy):
    x = max(0, min(img.width - 1, int(rect["x"] + rect["w"] * fx)))
    y = max(0, min(img.height - 1, int(rect["y"] + rect["h"] * fy)))
    return img.getpixel((x, y))[:3]


class Runner:
    def __init__(self, base, cdp, out, uid):
        self.base = base.rstrip("/")
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.uid = uid
        self.cdp = CDP(cdp, self.base + "/index.html")
        self.passed = 0
        self.failed = []
        self.evidence = {"contrast": [], "surfaces": {}, "avatars": {}}
        data = get(f"{self.base}/api/profiles/{self.uid}/bootstrap")
        self.profile = data["user"]
        active = json.dumps({"user_id": self.profile["user_id"], "nickname": self.profile["nickname"],
                             "avatar": self.profile["avatar"], "selected_at": int(time.time() * 1000)},
                            ensure_ascii=False)
        self.cdp.preload(
            "localStorage.setItem('bf-active-user', %s);"
            "localStorage.setItem('bf-tutorial-done','1');"
            "localStorage.setItem('bf-dev-tutorial-done','1');"
            "sessionStorage.setItem('bf-dev-testing','1');"
            "sessionStorage.setItem('bf-parent-ok','1');" % json.dumps(active)
        )
        self.cdp.viewport(1440, 1000)

    def check(self, name, cond, detail=""):
        if cond:
            self.passed += 1
            print(f"PASS {name}")
        else:
            self.failed.append({"name": name, "detail": detail})
            print(f"FAIL {name}" + (f" — {detail}" if detail else ""))

    def shot(self, name):
        self.cdp.shot(self.out / f"{name}.png")

    def horizontal_ok(self):
        return self.cdp.eval("document.documentElement.scrollWidth <= innerWidth + 1")

    def set_mode(self, mode):
        self.cdp.eval(
            f"document.documentElement.dataset.sky='{mode}';"
            "document.documentElement.style.setProperty('--sky-fade','0s');"
            "document.querySelectorAll('.sky-veil').forEach(e=>e.style.transition='none');"
        )
        self.cdp.eval("""(() => {
          let old = document.getElementById('v195-stop-anim');
          if (old) old.remove();
          let s = document.createElement('style');
          s.id = 'v195-stop-anim';
          s.textContent = '*{animation:none!important;transition:none!important}';
          document.head.appendChild(s);
        })()""")
        time.sleep(.5)

    # ------------------------------------------------------------ avatars
    def avatars(self):
        self.cdp.goto(self.base + "/profiles.html", 1.2)
        self.cdp.eval("""(async () => {
          await Promise.all([...document.querySelectorAll('.profile-avatar img')]
            .map(i => i.decode ? i.decode().catch(() => {}) : null));
        })()""", await_promise=True)
        metrics = self.cdp.eval("""(() => {
          const cards = [...document.querySelectorAll('.profile-card')];
          const rows = cards.map(card => {
            const box = card.querySelector('.profile-avatar').getBoundingClientRect();
            const img = card.querySelector('.avatar-badge img');
            const r = img.getBoundingClientRect();
            return {w: Math.round(box.width), h: Math.round(box.height),
                    natural: img.naturalWidth,
                    cx: Math.round(r.x + r.width / 2 - (box.x + box.width / 2)),
                    cy: Math.round(r.y + r.height / 2 - (box.y + box.height / 2))};
          });
          return {count: cards.length, rows,
                  radius: getComputedStyle(document.querySelector('.profile-avatar')).borderRadius};
        })()""")
        self.evidence["avatars"]["profiles"] = metrics
        self.check("档案头像卡存在", metrics["count"] >= 5, metrics)
        self.check("档案头像统一尺寸", len({(r["w"], r["h"]) for r in metrics["rows"]}) == 1, metrics)
        self.check("档案头像图片已加载", all(r["natural"] == 512 for r in metrics["rows"]), metrics)
        self.check("档案头像视觉居中", all(abs(r["cx"]) <= 1 and abs(r["cy"]) <= 1 for r in metrics["rows"]), metrics)
        self.check("档案头像圆角统一", metrics["radius"] in ("24px", "22px"), metrics["radius"])
        self.shot("profiles-day-1440")

        self.cdp.eval("document.getElementById('btn-new').click()")
        time.sleep(.8)
        picker = self.cdp.eval("""(async () => {
          await Promise.all([...document.querySelectorAll('#avatar-pick img')]
            .map(i => i.decode ? i.decode().catch(() => {}) : null));
          return {count: document.querySelectorAll('#avatar-pick .avatar-opt').length,
                  loaded: [...document.querySelectorAll('#avatar-pick img')].filter(i => i.naturalWidth > 0).length,
                  selected: document.querySelectorAll('#avatar-pick .avatar-opt[aria-pressed="true"]').length};
        })()""", await_promise=True)
        self.evidence["avatars"]["picker"] = picker
        self.check("头像选择器展示九张图片", picker == {"count": 9, "loaded": 9, "selected": 1}, picker)
        self.shot("avatar-picker-day-1440")
        self.cdp.eval("document.getElementById('btn-modal-cancel').click()")

        self.cdp.viewport(800, 700)
        self.cdp.goto(self.base + "/profiles.html", 1.0)
        self.check("800px 档案页无横向滚动", self.horizontal_ok())
        self.cdp.viewport(600, 700)
        self.cdp.goto(self.base + "/profiles.html", 1.0)
        small = self.cdp.eval("""(() => {
          const grid = getComputedStyle(document.querySelector('.profile-grid'));
          const card = document.querySelector('.profile-card').getBoundingClientRect();
          const av = document.querySelector('.profile-avatar').getBoundingClientRect();
          return {cols: grid.gridTemplateColumns.split(' ').length, card: Math.round(card.width),
                  avatar: Math.round(av.width)};
        })()""")
        self.check("600px 档案头像两列且居中", small["cols"] == 2 and small["avatar"] == 68, small)
        self.cdp.eval("document.getElementById('btn-new').click()")
        time.sleep(.5)
        modal = self.cdp.eval("(() => { const r = document.querySelector('.modal-card').getBoundingClientRect(); return {w:r.width,h:r.height,iw:innerWidth,ih:innerHeight}; })()")
        self.check("小窗口头像弹窗不溢出", modal["w"] <= modal["iw"] and modal["h"] <= modal["ih"], modal)
        self.shot("avatar-picker-day-600")
        self.cdp.eval("document.getElementById('btn-modal-cancel').click()")
        self.cdp.viewport(1440, 1000)

        # 旧 ID 的现有档案仍显示兼容图片，不修改数据库。
        expected = {"frog": "avatar_01", "tadpole": "avatar_01", "lotus": "avatar_09",
                    "fish": "avatar_08", "dragonfly": "avatar_03", "snail": "avatar_02"}
        self.cdp.goto(self.base + "/profiles.html", 1.0)
        legacy = self.cdp.eval("""(() => {
          return [...document.querySelectorAll('.profile-card')].map(card => ({
            raw: card.dataset.avatarRaw, mapped: card.dataset.avatar,
            src: card.querySelector('.avatar-badge img')?.getAttribute('src')
          }));
        })()""")
        self.evidence["avatars"]["legacy"] = legacy
        ok_legacy = bool(legacy) and all(
            row["mapped"] == expected.get(row["raw"], row["raw"])
            and row["src"] == f"assets/avatars/{row['mapped']}.png" for row in legacy
        )
        self.check("旧头像 ID 映射到九宫格素材", ok_legacy, legacy)

        self.cdp.goto(self.base + "/index.html", 1.0)
        home = self.cdp.eval("""(() => {
          const img = document.getElementById('profile-entry-avatar');
          const name = document.getElementById('profile-entry-name').textContent;
          return {visible: !!img && !img.hidden, natural: img ? img.naturalWidth : 0, name};
        })()""")
        self.evidence["avatars"]["home"] = home
        self.check("首页当前档案显示头像", home["visible"] and home["natural"] == 512, home)
        self.shot("home-avatar-day-1440")

    # -------------------------------------------------------- readability
    def text_audit(self, page, mode, scroll):
        rows = self.cdp.eval("""(() => {
          const out = [];
          const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
          let el = walk.nextNode();
          while (el) {
            let text = '';
            for (const n of el.childNodes || []) if (n.nodeType === 3) text += n.textContent;
            text = text.trim();
            if (text) {
              const r = el.getBoundingClientRect();
              if (r.width >= 3 && r.height >= 3 && r.bottom > 0 && r.top < innerHeight) {
                const s = getComputedStyle(el);
                const top = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
                if (s.visibility !== 'hidden' && s.display !== 'none' && parseFloat(s.opacity) !== 0
                    && (top === el || el.contains(top))
                    && !el.closest('.mon-control') && !el.closest('.monitor-toggles')) {
                  let cls = typeof el.className === 'string' ? el.className.trim().split(' ')[0] : '';
                  out.push({sel: el.id ? '#' + el.id : (cls ? '.' + cls : ''),
                            text: text.slice(0, 55), color: s.color, fill: s.webkitTextFillColor,
                            size: parseFloat(s.fontSize), weight: parseInt(s.fontWeight) || 400,
                            opacity: parseFloat(s.opacity) || 1,
                            rect: {x: r.x, y: r.y, w: r.width, h: r.height}});
                }
              }
            }
            el = walk.nextNode();
          }
          return out;
        })()""")
        self.cdp.eval("""(() => {
          let old = document.getElementById('v195-hide-text');
          if (old) old.remove();
          let s = document.createElement('style');
          s.id = 'v195-hide-text';
          s.textContent = 'html.__v195probe *{color:transparent!important;'
            + '-webkit-text-fill-color:transparent!important;text-shadow:none!important;'
            + 'animation:none!important;transition:none!important}';
          document.head.appendChild(s);
          document.documentElement.classList.add('__v195probe');
        })()""")
        time.sleep(.08)
        shot = self.out / f"bg-{page}-{mode}-{scroll}.png"
        self.cdp.shot(shot)
        img = Image.open(shot).convert("RGB")
        self.cdp.eval("document.getElementById('v195-hide-text')?.remove();document.documentElement.classList.remove('__v195probe')")

        failures = []
        for item in rows:
            if item["fill"] in ("rgba(0, 0, 0, 0)", "transparent"):
                continue
            parsed = parse_color(item["color"])
            if not parsed:
                continue
            fg, alpha = parsed
            alpha *= item["opacity"]
            samples = [pixel(img, item["rect"], fx, fy) for fx, fy in ((.5, .5), (.65, .5), (.8, .5))]
            worst = min(contrast(tuple(alpha * fg[i] + (1 - alpha) * bg[i] for i in range(3)), bg)
                        for bg in samples)
            large = item["size"] >= 24 or (item["size"] >= 18.66 and item["weight"] >= 700)
            need = 3.0 if large else 4.5
            if worst + .01 < need:
                failures.append({**item, "ratio": round(worst, 2), "need": need})
        return failures

    def surfaces(self, page, mode):
        selectors = [".card", ".profile-card", ".modal-card", ".growth-card", ".chart-box",
                     ".parent-kpi", ".stat-box", ".game-guidance", ".hud-item"]
        vals = {}
        for sel in selectors:
            v = self.cdp.eval(
                "(() => { const el=document.querySelector(%s); if(!el) return null;"
                "const s=getComputedStyle(el); const m=s.backgroundColor.match(/rgba?\\(([^)]+)\\)/);"
                "if(!m) return {alpha:1,bg:s.backgroundColor}; const p=m[1].split(',').map(Number);"
                "return {alpha:p.length>3?p[3]:1,bg:s.backgroundColor}; })()" % json.dumps(sel))
            if v:
                vals[sel] = v
        return vals

    def readability(self):
        for page in PAGES:
            for mode in MODES:
                self.cdp.goto(self.base + f"/{page}.html", 1.0)
                self.set_mode(mode)
                for scroll in (0, 600):
                    self.cdp.eval(f"scrollTo(0,{scroll})")
                    time.sleep(.15)
                    failures = self.text_audit(page, mode, scroll)
                    if failures:
                        self.failed.append({"name": f"{page}/{mode}/{scroll} 对比度", "detail": failures[:8]})
                        print(f"FAIL 对比度 {page}/{mode}/{scroll}: {[(f['sel'], f['ratio'], f['text']) for f in failures[:5]]}")
                    else:
                        self.passed += 1
                        print(f"PASS 对比度 {page}/{mode}/{scroll}")
                if page in ("index", "profiles", "game", "growth", "parent", "dev"):
                    self.cdp.goto(self.base + f"/{page}.html", 1.0)
                    self.set_mode(mode)
                    self.shot(f"page-{page}-{mode}-1440")
                self.evidence["surfaces"][f"{page}/{mode}"] = self.surfaces(page, mode)

        # 弹窗单独检查：背景必须完全不透明，文字使用暗色/浅色对应变量。
        for mode in ("day", "night"):
            self.cdp.goto(self.base + "/profiles.html", 1.0)
            self.set_mode(mode)
            self.cdp.eval("document.getElementById('btn-new').click()")
            time.sleep(.4)
            modal = self.surfaces("profiles", mode)
            alpha = (modal.get(".modal-card") or {}).get("alpha", 1)
            self.check(f"{mode} 档案弹窗完全不透明", alpha >= .99, modal.get(".modal-card"))
            self.shot(f"avatar-picker-{mode}-1440")
            self.cdp.eval("document.getElementById('btn-modal-cancel').click()")

    # --------------------------------------------------------------- game
    def game(self):
        for mode in ("day", "night"):
            self.cdp.goto(self.base + "/game.html?demo=1&dev=1&sec=60", 1.0)
            self.set_mode(mode)
            time.sleep(2.6)
            self.cdp.eval("document.documentElement.classList.add('debug-hud')")
            self.cdp.eval("try{document.getElementById('monitor-hide-left')?.click();document.getElementById('monitor-hide-right')?.click()}catch(e){}")
            time.sleep(.4)
            data = self.cdp.eval("""(() => {
              const card = document.querySelector('.tutorial-card');
              const s = card ? getComputedStyle(card) : null;
              const hud = document.querySelector('.hud-item');
              const h = hud ? getComputedStyle(hud) : null;
              return {tutorialBg: s ? s.backgroundColor : null, tutorialColor: s ? s.color : null,
                      hudBg: h ? h.backgroundColor : null, hudColor: h ? h.color : null};
            })()""")
            self.check(f"{mode} 游戏教学卡为不透明浅底",
                       bool(data["tutorialBg"] and data["tutorialBg"].startswith("rgb(")), data)
            self.check(f"{mode} 游戏 HUD 为稳定深底", data["hudBg"] == "rgb(35, 55, 58)", data)
            self.shot(f"game-{mode}-tutorial-1440")
            game_fail = self.text_audit("game", mode, 0)
            if game_fail:
                self.failed.append({"name": f"game/{mode} 对比度", "detail": game_fail[:8]})
                print(f"FAIL 对比度 game/{mode}: {[(f['sel'], f['ratio'], f['text']) for f in game_fail[:5]]}")
            else:
                self.passed += 1
                print(f"PASS 对比度 game/{mode}")
            self.cdp.eval("document.documentElement.classList.remove('debug-hud')")
        # 小窗口游戏无横向滚动
        self.cdp.viewport(800, 600)
        self.cdp.goto(self.base + "/game.html?demo=1&dev=1&sec=60", 1.0)
        self.check("800px 游戏页无横向滚动", self.horizontal_ok())
        self.cdp.viewport(1440, 1000)

    def report(self):
        data = {"passed": self.passed, "failed": self.failed, "evidence": self.evidence}
        (self.out / "result.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"passed": self.passed, "failed": len(self.failed)}, ensure_ascii=False))
        return 1 if self.failed else 0

    def run(self):
        self.avatars()
        self.readability()
        self.game()
        return self.report()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8020")
    ap.add_argument("--cdp", default="http://127.0.0.1:9333")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--user-id", default="u_5e38d8e88f9e")
    args = ap.parse_args()
    runner = Runner(args.base, args.cdp, args.out, args.user_id)
    try:
        return runner.run()
    finally:
        runner.cdp.close()


if __name__ == "__main__":
    raise SystemExit(main())
