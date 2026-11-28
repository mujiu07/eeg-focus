#!/usr/bin/env python3
"""v1.9.4 补充：归零休息姿态的真实浏览器验收（隔离服务 8020）。

只验证视觉状态机：有效信号下蓄力为 0 持续 2 秒进入休息、恢复蓄力后回到准备姿态。
使用手动模拟，明确不是真实脑电或临床结论；不写入真实数据库。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from browser_ui_v192 import CDP  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8020")
    ap.add_argument("--cdp", default="http://127.0.0.1:9333")
    ap.add_argument("--out", default=str(ROOT / ".deepworks" / "tmp" / "v194" / "rest"))
    args = ap.parse_args()
    base = args.base.rstrip("/")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cdp = CDP(args.cdp, base + "/index.html")
    passed, failed = 0, []

    def check(name, cond, detail=""):
        nonlocal passed
        if cond:
            passed += 1
            print("PASS", name)
        else:
            failed.append(name)
            print("FAIL", name, detail)

    cdp.viewport(1920, 1080)
    cdp.preload("try{sessionStorage.setItem('bf-dev-testing','1');sessionStorage.setItem('bf-dev-tutorial-done','1')}catch(e){}")
    cdp.goto(base + "/game.html?demo=1&sec=60", 1.5)
    time.sleep(5.0)

    def state():
        return cdp.eval("""(() => ({
          energy: document.getElementById('energy-readout').textContent,
          resting: document.querySelector('.energy-track').classList.contains('resting'),
          lamp: document.getElementById('lamp-text').textContent,
          warn: document.getElementById('warn').classList.contains('show'),
          phase: document.getElementById('energy-zone').hidden ? 'hidden' : 'zone-visible'
        }))()""")

    check("浏览器加载的公共起始蓄力为 10%",
          cdp.eval("window.FocusRound && window.FocusRound.CONFIG.startEnergy") == 10)

    # 先让手动模拟进入稳定的低分状态，等待蓄力自然衰减到 0 并满 2 秒。
    cdp.eval("(()=>{const s=document.getElementById('manual-slider');s.value=30;s.dispatchEvent(new Event('input',{bubbles:true}));})()")
    reached = False
    for _ in range(40):
        time.sleep(1)
        st = state()
        if st["resting"]:
            reached = True
            break
    check("蓄力归零后进入休息姿态", reached, st)
    check("休息时蓄力为 0%", st["energy"] == "0%", st)
    check("休息时状态文案不责备", st["lamp"] == "休息中" and not st["warn"], st)
    check("休息时金色区域仍可见", st["phase"] == "zone-visible", st)
    cdp.shot(out / "game-rest-1920.png")

    # 重新驱动蓄力：应自动退出休息，且不阻塞新的判定链路。
    cdp.eval("(()=>{const s=document.getElementById('manual-slider');s.value=90;s.dispatchEvent(new Event('input',{bubbles:true}));})()")
    time.sleep(1.6)
    st2 = state()
    check("蓄力恢复后退出休息姿态", not st2["resting"], st2)
    check("恢复后蓄力大于 0", st2["energy"] != "0%", st2)
    check("恢复后状态回到准备/专注", st2["lamp"] in ("跟上了", "飘走了"), st2)
    cdp.shot(out / "game-rest-recovered-1920.png")

    (out / "rest-result.json").write_text(json.dumps({
        "rest": st, "recovered": st2, "passed": passed, "failed": failed,
        "note": "manual simulation on isolated data dir; not real EEG",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{passed} passed, {len(failed)} failed")
    cdp.close()
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
