# -*- coding: utf-8 -*-
"""回归自测：动态定标分数映射（对齐 app/server.py 的 score_of / MIN_SPAN）。

目的：验证"专注度绝对值很低（如 0.012）"不会直接越过游戏的 45 分达标线，
即历史上 `focus > 0.012` 那种"阈值永真"的误触发路径已经不存在。

运行：python tests/selfcheck_score_mapping.py
不影响服务运行，也不会读写会话数据。
"""
from __future__ import annotations

import sys

MIN_SPAN = 0.10          # 与 app/server.py 的 MIN_SPAN 保持一致
GAME_ON = 45            # web/game.html: scoreSmooth >= 45 进入蓄力
GAME_OFF = 38           # web/game.html: scoreSmooth < 38 退出蓄力（滞回）


def score_of(x, lo, hi):
    """与 app/server.py 的 SessionState.score_of 逐行一致。"""
    if x is None:
        return None
    if hi - lo < 1e-6:
        hi = lo + 0.15
    v = 20.0 + 60.0 * (float(x) - lo) / (hi - lo)
    return round(max(0.0, min(100.0, v)), 1)


def stretch(low, high):
    """与 app/server.py calibrate 里的 MIN_SPAN 扩窗保持一致。"""
    low = max(0.0, min(0.9, low))
    high = min(1.0, max(low, high))
    if high - low < MIN_SPAN:
        mid = (low + high) / 2.0
        low = max(0.0, mid - MIN_SPAN / 2.0)
        high = min(1.0, low + MIN_SPAN)
        if high - low < MIN_SPAN:
            low = max(0.0, high - MIN_SPAN)
    return round(low, 3), round(high, 3)


def main():
    fails = []

    def check(name, cond, detail=""):
        print(("PASS " if cond else "FAIL ") + name + (" — " + detail if detail else ""))
        if not cond:
            fails.append(name)

    # 1) 低基线场景：校准实测 q10/q50/q90 = 0.006/0.012/0.021
    lo, hi = stretch(0.006, 0.021)
    check("低基线扩窗到最小跨度", abs((hi - lo) - MIN_SPAN) < 1e-9, f"[{lo}, {hi}]")

    s_base = score_of(0.012, lo, hi)
    check("基线本身低于达标线", s_base is not None and s_base < GAME_ON, f"score(0.012)={s_base}")
    check("旧阈值 0.012 不再直接达标", s_base < GAME_ON)
    check("q90 仍低于达标线", score_of(0.021, lo, hi) < GAME_ON,
          f"score(0.021)={score_of(0.021, lo, hi)}")
    check("约 0.042 才越过达标线", score_of(0.042, lo, hi) >= GAME_ON,
          f"score(0.042)={score_of(0.042, lo, hi)}")

    # 2) 未校准兜底区间 [0.35, 0.75]
    check("兜底区间下 0.012 得 0 分", score_of(0.012, 0.35, 0.75) == 0.0)
    check("兜底区间下 0.5 仍低于达标线", score_of(0.5, 0.35, 0.75) < GAME_ON,
          f"score(0.5)={score_of(0.5, 0.35, 0.75)}")

    # 3) 钳制与退化保护
    check("上界钳制到 100", score_of(5.0, 0.0, 0.10) == 100.0)
    check("下界钳制到 0", score_of(-5.0, 0.0, 0.10) == 0.0)
    check("零跨度退化保护不除零", score_of(0.5, 0.5, 0.5) == 20.0,
          f"score(0.5,0.5,0.5)={score_of(0.5, 0.5, 0.5)}")

    # 4) 0.25 在低基线区间属于远高于个人基线的异常高值 → 封顶
    check("0.25 在低基线区间封顶", score_of(0.25, lo, hi) == 100.0)

    # 5) 滞回窗口本身合法
    check("滞回带有效", 0 < GAME_OFF < GAME_ON <= 100)

    print()
    if fails:
        print(f"{len(fails)} failed: " + ", ".join(fails))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
