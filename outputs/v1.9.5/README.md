# v1.9.5 证据索引

## 头像素材

- `avatars/avatar_01.png` … `avatar_09.png`：9 张独立 512×512 透明 PNG。
- `profiles-avatar-picker-day-1440.png`：白天档案头像选择器。
- `profiles-avatar-picker-night-1440.png`：黑夜档案头像选择器。
- `avatar-picker-day-600.png`：600px 小窗口选择器。
- `home-avatar-day-1440.png` / `home-avatar-night-1440.png`：首页当前档案头像。

## 背景状态

- `backgrounds/day-key-pages.png`：白天首页、档案、校准、成长、家长、开发者。
- `backgrounds/dusk-key-pages.png`：傍晚同组页面。
- `backgrounds/night-key-pages.png`：黑夜同组页面。
- `evidence/page-*.png`：更多逐页截图（1440×1000）。
- `evidence/bg-*.png`：用于对比度计算的“隐藏文字、保留真实背景”截图。

## 游戏

- `evidence/game-day-tutorial-1440.png`：白天教学/HUD。
- `evidence/game-night-tutorial-1440.png`：黑夜教学/HUD。
- `regression-rest/`：v1.9.4 归零休息回归截图。

## 自动验收

- `browser-result.json`：v1.9.5 真实浏览器 74 项检查结果。
- `evidence/result.json`：原始结果（含 surface 透明度采样）。
- `regression-v194/result.json`：v1.9.4 53 项回归结果。

## 复现

```bash
cd /Users/fan/Desktop/脑机/eeg-focus
FOCUS_FROG_DATA_DIR="$PWD/.deepworks/testdata" \
  .venv/bin/uvicorn app.server:app --host 127.0.0.1 --port 8020
# 另开带 remote-debugging-port=9333 的 Edge/Chromium
.venv/bin/python tests/selfcheck_v195.py
.venv/bin/python tests/browser_ui_v195.py \
  --base http://127.0.0.1:8020 --cdp http://127.0.0.1:9333 \
  --out outputs/v1.9.5/evidence
```

真实库不参与测试；8020 使用隔离数据目录。
