# v1.9.4 验收证据

这些截图来自隔离测试服务（端口 8020/8023）和 `.deepworks/` 下的虚构档案，不包含真实用户数据库或脑电隐私数据。

## before/（v1.9.3 基线）

| 文件 | 说明 |
|---|---|
| `before/calibrate-calm-1440.png` | v1.9.3 平静阶段：旧视频未播放，画面为空白卡片 |
| `before/profiles-1440.png` | v1.9.3 头像：72px 圆形、透明留白偏上 |
| `before/parent-1440-top.png` / `before/parent-1440-bottom.png` | v1.9.3 家长中心：图表区与相邻卡片紧贴 |
| `before/game-start-cue-1920.png` | v1.9.3 开始动画：只有水波，小蛙与荷叶画布为空 |
| `before/game-dev-none-1920.png` | v1.9.3 关闭两侧栏后顶部栏被拉到 1836px |
| `before/shop-1440.png` | v1.9.3 商城：旧价 5–8 分 |

## after/（v1.9.4）

| 文件 | 说明 |
|---|---|
| `after/calibrate-calm-1440.png` | 固定低刺激池塘，复用首页小蛙/荷叶/水波 |
| `after/calibrate-tutorial-demo-1440.png` | 预设演示「先看一遍」 |
| `after/calibrate-tutorial-live-1440.png` | 正式教学：确认跳跃、能量条、金色区域 |
| `after/calibrate-done-1440.png` | 校准完成与 v3 协议说明 |
| `after/profiles-1440.png` | 统一头像框、颜色、尺寸与视觉中心 |
| `after/avatar-picker-1440.png` | 头像选择器 56px 统一规格 |
| `after/parent-1440-top.png` / `after/parent-1440-bottom.png` | 20px 纵向节奏与图表留白 |
| `after/game-start-cue-1920.png` | 水波中央的首页同款小蛙与荷叶 |
| `after/game-start-cue-800.png` | 800×600 矮屏转场覆盖视口 |
| `after/game-dev-none-1920-final.png` | 顶部栏/画布 1120px 居中 |
| `after/game-bullet-1920.png` | 子弹时间径向压暗（250ms 过渡） |
| `after/game-rest-1920.png` | 蓄力归零 2 秒：小蛙降低重心休息，状态「休息中」 |
| `after/game-rest-recovered-1920.png` | 蓄力恢复：自动回到准备姿态 |
| `after/game-rest-canvas-1920.png` | 休息姿态画布特写（降低重心与轻微压扁） |
| `after/game-rest-recovered-canvas-1920.png` | 恢复准备姿态画布特写 |
| `after/shop-1440.png` | 逐件定价后的商城 |

## 复现命令

```bash
FOCUS_FROG_DATA_DIR="$PWD/.deepworks/testdata" \
  .venv/bin/python -m uvicorn app.server:app --host 127.0.0.1 --port 8020

PYTHONPATH="$PWD" .venv/bin/python tests/selfcheck_v194.py
node tests/selfcheck_v194_charge.js
node tests/econ_v194.js
PYTHONPATH="$PWD" .venv/bin/python tests/browser_ui_v194.py \
  --base http://127.0.0.1:8020 --cdp http://127.0.0.1:9333 \
  --out .deepworks/tmp/v194/browser --user-id <隔离 fixture B>
PYTHONPATH="$PWD" .venv/bin/python tests/browser_ui_v194_rest.py \
  --base http://127.0.0.1:8020 --cdp http://127.0.0.1:9333
```

浏览器验收需要带 `--remote-debugging-port=9333` 的 Edge/Chromium。截图为 1440×900 或 1920×1080、800×600；完整结果见 `browser-result.json`，归零休息结果见 `rest-result.json`（51 + 8 项通过）。

价格明细见 `price-comparison.csv` 与 `docs/PRICE-v1.9.4.md`；10% vs 15% 的逐行模拟见 `economy-10-vs-15.csv` / `.json`。
