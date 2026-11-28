#!/usr/bin/env python3
"""v1.9.5 静态验收：九宫格头像、旧 ID 兼容与全站可读性契约。

不启动服务、不触碰真实数据库；图片只读取本地素材。
"""
from __future__ import annotations

import hashlib
import re
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import difficulty  # noqa: E402
from app.storage import AVATAR_LABELS, AVATARS, SCHEMA_VERSION, StorageManager  # noqa: E402

passed: list[str] = []
fails: list[str] = []


def check(name: str, cond: bool, detail=""):
    if cond:
        passed.append(name)
        print(f"PASS {name}")
    else:
        fails.append(name)
        print(f"FAIL {name}" + (f" — {detail}" if detail else ""))


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def lum(rgb):
    def f(v):
        v = v / 255
        return v / 12.92 if v <= .03928 else ((v + .055) / 1.055) ** 2.4
    r, g, b = rgb
    return .2126 * f(r) + .7152 * f(g) + .0722 * f(b)


def contrast(a, b):
    x, y = sorted((lum(a), lum(b)), reverse=True)
    return (x + .05) / (y + .05)


def rgb(hexv):
    return tuple(int(hexv[i:i + 2], 16) for i in (1, 3, 5))


def main():
    avatar_dir = ROOT / "web/assets/avatars"
    paths = [avatar_dir / f"avatar_{i:02d}.png" for i in range(1, 10)]
    check("九张头像文件齐全且命名规范", all(p.exists() for p in paths))

    dimensions, centers, hashes = [], [], []
    for p in paths:
        im = Image.open(p).convert("RGBA")
        dimensions.append(im.size)
        alpha = im.getchannel("A")
        bbox = alpha.getbbox()
        centers.append(((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2))
        hashes.append(hashlib.sha256(p.read_bytes()).hexdigest())
    check("头像统一为 512×512", all(s == (512, 512) for s in dimensions), dimensions)
    check("头像背景透明且主体未被白边撑开",
          all(Image.open(p).convert("RGBA").getpixel((0, 0))[3] == 0 for p in paths)
          and all(Image.open(p).convert("RGBA").getpixel((256, 256))[3] > 200 for p in paths))
    check("头像主体中心一致",
          all(abs(x - 256) <= 2 and abs(y - 256) <= 2 for x, y in centers), centers)
    check("九张头像内容不重复", len(set(hashes)) == 9)

    avatars_js = read("web/assets/avatars.js")
    check("公共头像模块列出九个图片 ID",
          all(f'"avatar_{i:02d}"' in avatars_js for i in range(1, 10)))
    check("旧头像 ID 保留兼容映射",
          all(f'{x}:' in avatars_js for x in ("frog", "tadpole", "lotus", "fish", "dragonfly", "snail")))
    check("服务端同时接受旧 ID 与九宫格 ID",
          all(x in AVATARS for x in ("frog", "tadpole", "lotus", "fish", "dragonfly", "snail"))
          and all(x in AVATARS for x in (f"avatar_{i:02d}" for i in range(1, 10)))
          and len(AVATARS) == 15)
    check("头像中文标签完整",
          all(AVATAR_LABELS.get(f"avatar_{i:02d}") for i in range(1, 10)))
    check("头像扩展不改变 Schema", SCHEMA_VERSION == 4)
    with tempfile.TemporaryDirectory() as td:
        store = StorageManager(td)
        legacy_user = store.create_user("旧头像档案", "fish")
        store.update_user(legacy_user["user_id"], nickname="只改昵称")
        kept = store.get_user(legacy_user["user_id"])
        new_user = store.create_user("新头像档案", "avatar_09")
        check("只改昵称不会重写旧头像 ID", kept["avatar"] == "fish", kept["avatar"])
        check("新档案可使用九宫格图片 ID", new_user["avatar"] == "avatar_09", new_user["avatar"])

    profiles = read("web/profiles.html")
    index = read("web/index.html")
    check("档案页使用公共图片头像模块",
          "assets/avatars.js" in profiles and "AvatarArt.markup" in profiles
          and "avatar-img" in profiles)
    check("首页当前档案显示头像",
          "profile-entry-avatar" in index and "Profile.active" in index and "AvatarArt.src" in index)
    check("头像选择器仍为新档案的九张图片",
          "AVATARS.map" in profiles and 'data-avatar="${a.id}"' in profiles)

    # 可读性：所有页面最后加载统一信息层样式。
    pages = ["index", "profiles", "calibrate", "game", "growth", "parent",
             "history", "report", "settings", "dev"]
    linked = {p: read(f"web/{p}.html") for p in pages}
    check("全站页面加载可读性样式",
          all('assets/readability-v195.css' in s for s in linked.values()))
    check("可读性样式位于各页 head 末尾",
          all(s.rfind("readability-v195.css") > s.rfind("visual-v193.css") for s in linked.values()))
    css = read("web/assets/readability-v195.css")
    check("UI 层与动景层有独立堆叠变量",
          "--ui-scene-z" in css and "--ui-content-z" in css and "isolation: isolate" in css)
    check("关键表面使用高不透明度变量",
          "--ui-surface" in css and "--ui-surface-solid" in css
          and ".modal-card" in css and "opacity: .96" not in css)
    check("所有可交互元素有统一键盘聚焦轮廓",
          ":focus-visible" in css and "--ui-ring" in css)
    check("动态背景没有被移除",
          ".bubbles" in css and ".sky-veil" in css and "z-index: var(--ui-scene-z)" in css)
    check("小窗口头像尺寸与两列布局",
          "@media (max-width: 700px)" in css and ".profile-avatar { width: 68px" in css)

    # 关键配色对：普通文字 ≥4.5，暗色模式同样成立。
    pairs = [
        ("白天正文", rgb("#1f3f47"), (255, 255, 255), 4.5),
        ("白天辅助", rgb("#48666e"), (255, 255, 255), 4.5),
        ("夜间正文", rgb("#f2f7fb"), rgb("#0d1b2f"), 4.5),
        ("夜间辅助", rgb("#c3d7e2"), rgb("#0d1b2f"), 4.5),
        ("白天主按钮", (255, 255, 255), rgb("#267d73"), 4.5),
        ("夜间主按钮", rgb("#10222f"), rgb("#9fe3f0"), 4.5),
        ("步骤序号", (255, 255, 255), rgb("#267d5e"), 4.5),
        ("家长页辅助", rgb("#2e4a52"), (255, 255, 255), 4.5),
    ]
    bad = [(n, round(contrast(a, b), 2)) for n, a, b, need in pairs if contrast(a, b) < need]
    check("关键文字/控件配色达到 4.5:1", not bad, bad)

    # 业务红线：只改视觉和头像，不改算法、计分、起点、休息和价格。
    round_js = read("web/assets/focus-round.js")
    check("初始蓄力仍为 10%", "startEnergy: 10" in round_js)
    check("服务端参数版本仍为 v1.9.4", difficulty.PARAMS_VERSION == "v1.9.4")
    check("休息机制仍为 2 秒 / 2.5% 退出",
          "restAfterSec: 2.0" in round_js and "restExitEnergy: 2.5" in round_js)
    dressup = read("web/assets/dressup.js")
    prices = [int(m.group(1)) for m in re.finditer(r'id:\s*"[^"]+",.*?price:\s*(\d+)', dressup, re.S)]
    check("商城价格未被本次改动重定价", prices and min(prices) == 24 and max(prices) == 240)
    check("应用版本提升到 v1.9.5（玩法参数仍为 v1.9.4）", 'version="1.9.5"' in read("app/server.py"))

    print()
    print(f"{len(passed)} passed, {len(fails)} failed")
    if fails:
        print("failed:", ", ".join(fails))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
