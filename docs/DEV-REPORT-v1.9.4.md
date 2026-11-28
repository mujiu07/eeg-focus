# 专注小蛙 v1.9.4 开发报告

- 版本：`v1.9.4`
- 日期：2026-11-28
- 父版本：`v1.9.3`（commit `88db4e8`）
- 范围：校准引导、游戏反馈、档案头像、局部布局与商城定价；不修改脑电特征、去噪、自适应难度策略、正式计分公式、金币兑换比例或 Schema 4。

## 1. 结论

本版解决了 8 项实际体验问题，并在验收中发现并修复 1 个开发者工作台空值崩溃：

1. **平静校准**：不再依赖未真正播放的外部视频，改为固定低刺激动态池塘（复用首页小蛙/荷叶/水波）；保留 30 秒有效采集和信号异常暂停；校准期间暂停背景音乐，结束/取消后恢复。
2. **专注校准**：先播放 3.6 秒预设演示，再进入 30 秒教学采集；统一「确认跳跃」按钮，区分蓄力等待与金色区域提示，加入点击锁和按键重复保护，明确连续点击不加分。
3. **校准协议**：新增 `daily_v3`，记录实际刺激条件和教学事件；`daily_v2` 每日校准不再与 v3 混用，历史长期参考保留且不覆盖。
4. **档案头像**：统一为 76px/56px 圆角头像框、同色系底板、同一视觉中心；小蛙使用 `FrogArt` 紧凑视口，消除透明留白导致的偏移；头像 ID 与档案关联不变。
5. **开始动画**：修复 `window.PondEffects` 判断导致的静默空画布，水波中央恢复首页同款小蛙和荷叶；不延长等待时间，保留减少动态效果规则。
6. **子弹时间**：背景压暗改为 250ms 径向渐变，中心保持透明，退出时平滑恢复；2.5 秒点击窗口和计分不变。
7. **开发者顶部栏**：关闭一侧或两侧数据栏后，HUD/配色栏/音乐行不再从 900px 拉到 1836px，统一限制在 1120px 并居中；四种组合连续切换不重置计时、不丢积分、不新增 SSE。
8. **商城定价**：按逐件美术复杂度与稀有度重定价，典型 3 分钟玩家约 2–3 局购买普通装扮；已有金币、购买记录和权益不变。
9. **家长中心**：修复图表区与相邻卡片 0 间距、重复硬描边和图表贴边；统一 20px 纵向节奏与 18–20px 内留白。
10. **附带修复**：`/api/dev/workbench` 在 `report.assessment = null` 时触发 `NoneType.get` 500；现在按空字典处理。

真实浏览器验收（隔离服务 8020 / 隔离数据目录）共 **51 项通过，0 失败**；静态与存储回归 **31 项通过**；v1.8.1–v1.9.2 全量静态/单元回归与 v1.9.3 静态视觉检查继续通过。

## 2. 环境与数据安全

- 重新克隆 `https://github.com/mujiu07/eeg-focus`，确认远程 `main = 88db4e8`（v1.9.3），没有 v1.9.4 标签。
- 真实数据库：`/Users/fan/Documents/专注小蛙/profiles.db`。本版全程只读核验，未删除、清空、迁移或重新初始化。
  - 验收前后文件大小 294912 字节、修改时间 15:18 未变；
  - SHA-256 `0d569a66dd058ed68c480fcff5a292ed2dbfa2512a9cd04293dff606a6715c75`；
  - `PRAGMA integrity_check = ok`，2 个档案、7 个 Session，Schema 4。
- 所有自动化测试、模拟游玩、购买测试和截图使用 `FOCUS_FROG_DATA_DIR` 指向仓库内 `.deepworks/` 临时目录，服务端口为 8020/8022/8023；启动后通过 `/api/profiles.storage` 验证 `data_dir` 为隔离目录。
- 未修改全局 Git 配置；仓库级身份与远程核验见第 8 节。

## 3. 逐项根因与修复

### 3.1 平静校准：旧视频没有真正播放

**根因**：v1.9.3 的 `calibrate.html` 保留了 `relax.mp4` 和 `playRelaxVideo()`，但进入校准后只调用了 `playRelaxVideo(false)`，没有任何 `playRelaxVideo(true)` 调用；同时 `video-frame` 被隐藏。结果是「平静观察」阶段实际上是一块空白卡片，只有倒计时和状态文字。问题不是视频素材缺失，而是旧流程未启动它。

**修复**：
- 删除页面中的 `<video>` 与 `relax.mp4` 播放逻辑，新增 `web/assets/calm-pond.js`；
- 用 canvas 绘制固定低刺激池塘：复用 `PondEffects.paintLily` / `paintFrog` 的首页几何，轻微水波、缓慢漂浮、5–8 秒自然眨眼和 6 秒一次的低透明度涟漪；
- 不出现剧情、奖励、闪光、突然变化、追踪任务或外部视频；`prefers-reduced-motion` 下停止漂浮/眨眼/涟漪；
- 保留 30 秒有效帧累计、信号质量徽章、异常帧暂停与最大阶段超时；
- 进入校准调用 `pauseMusicForCalibration()`，以 `bf-music-on` 设置和当前播放状态共同判断；结束、取消或出错调用 `restoreMusicAfterCalibration()`；
- 记录 `stimulus_condition = calm_pond_open_eyes_v1`，明确这是低刺激睁眼观察基线，不是严格无刺激静息脑电。

**证据**：[修改前](../outputs/v1.9.4/before/calibrate-calm-1440.png) / [修改后](../outputs/v1.9.4/after/calibrate-calm-1440.png)。

### 3.2 专注校准：预设演示 + 受控确认跳跃

**根因**：旧教学只有一个自动循环的能量条，点击只累加事件数量，没有演示、没有金色区域提示、没有跳跃反馈，也没有防连点/长按；按钮文案是「点一下，陪小蛙起跳」。

**修复**：
- 进入教学先播放 3.6 秒预设演示：能量条从 15% 涨到 58%，进入金色区域后自动演示一次跳跃；演示不写入 `stage_windows`，不计入 30 秒采集；
- 演示结束后才设置 `tutorial` 窗口起点，开始 30 秒有效采集；
- 采用固定预设进度（起点 15%、金色区域 58–74%、蓄力 26%/秒、点击窗口 2.5 秒），不读取尚未建立的每日基线；
- 按钮统一为「确认跳跃」；蓄力时标题与提示为「看着能量条，耐心等待」，进入金色区域后为「现在，点击一次确认跳跃！」；
- 点击锁 0.9 秒，按钮/能量条/键盘共用；键盘 `e.repeat` 直接返回；长按只产生一次 click；跳跃阶段与冷却阶段不再接受点击；
- 提前点击只记录 `reason=early` 并提示「提前点击不会加分，也不会提高脑电分数」；成功后 `CalmPond.hop()` 播放小蛙跳跃与水花，反馈「跳得好！教学不计分，也不会发商城币」；
- 教学事件记录 `charge / zone_lo / zone_hi / in_zone / accepted / demo / reaction_sec / reason`，随校准记录保存。

**证据**：[演示](../outputs/v1.9.4/after/calibrate-tutorial-demo-1440.png) / [正式教学](../outputs/v1.9.4/after/calibrate-tutorial-live-1440.png) / [完成](../outputs/v1.9.4/after/calibrate-done-1440.png)。

### 3.3 校准协议 v3 与长期参考

- `app/calibration.py`：`PROTOCOL_VERSION = "daily_v3"`，新增 `STIMULUS_CONDITION`；
- `app/server.py`：`CalibrateStart` 增加 `stimulus_condition / teaching`；校验仍要求 `natural → tutorial` 窗口顺序；结果写入 `tutorial_events` 与刺激条件；
- 为不改变 Schema 4，刺激条件、教学事件和教学元数据写入 `source_info` JSON（设备上下文），不新增数据库列；
- `daily_status` 只接受当前 `daily_v3`，因此旧 `daily_v2` 每日校准不再被当作今日校准；这是有意的新旧不可比边界；
- `_ensure_initial_reference` 只在没有 active 参考时创建，已有 v2 长期参考原样保留；若检测到旧协议参考，校准结果返回 `reference_compat.compatible=false`，完成页提示「已保留但不与本次混算，如需新版长期参考请由家长在开发者工作台重新建立」；
- 未修改分位数、最小跨度、映射、难度或计分算法。

### 3.4 档案头像

**根因**：
- 档案头像使用 72px 圆形底，`FrogArt` 的 `viewBox="-40 -37 80 80"` 在 58px 宽的身体外留了大量透明边，导致小蛙看起来偏小且略偏上；
- 其他头像使用 27px 线框图标，与 72px 底和彩色小蛙的比例不一致；
- 选择器 44px、列表 72px、头部 58px 三套尺寸与圆角不统一。

**修复**：
- `FrogArt.svg()` 增加 `compact` 选项，头像使用 `viewBox="-31.5 -30 63 63"`，几何中心与视口中心对齐；
- 新增 `.avatar-badge` 统一底板：浅绿到暖白的同色系渐变、统一描边、统一圆角比例；
- 列表头像 76×76 / 24px 圆角，选择器 56×56 / 18px 圆角；小蛙图 82%，线性图标 40px / 31px，均使用 `display:grid; place-items:center`；
- 保留 `frog/tadpole/lotus/fish/dragonfly/snail` 六个 ID 与 `avatar` 字段，不迁移档案。

**证据**：[修改前头像](../outputs/v1.9.4/before/profiles-1440.png) / [修改后头像](../outputs/v1.9.4/after/profiles-1440.png) / [选择器](../outputs/v1.9.4/after/avatar-picker-1440.png)。

### 3.5 开始动画小蛙缺失

**根因**：`web/assets/pond-effects.js` 用顶层 `const PondEffects = {...}` 声明，浏览器不会把它挂到 `window` 上。`game.html` 的 `paintCueArt()` 先判断 `if (!window.PondEffects || !PondEffects.paintLily) return;`，条件恒真，导致开局/结算卡片上的小蛙和荷叶画布从未绘制；只剩 CSS 水波和数字。

**修复**：改为 `const PE = window.PondEffects || (typeof PondEffects !== "undefined" ? PondEffects : null)`，并用 `PE` 绘制荷叶、阴影、青蛙与装扮层。开始动画的 3-2-1-开始时间不变，卡片仍按原时长淡出；`prefers-reduced-motion` 规则保留；800×600 矮屏增加视口级覆盖，避免动画落到折叠线以下。

**证据**：[修改前（只有水波）](../outputs/v1.9.4/before/game-start-cue-1920.png) / [修改后（小蛙居中）](../outputs/v1.9.4/after/game-start-cue-1920.png) / [800×600](../outputs/v1.9.4/after/game-start-cue-800.png)。

### 3.6 子弹时间渐变

**根因**：`drawBulletFocus()` 每帧直接铺 `rgba(12,30,34,.18)`，进入时瞬间变暗；离开 `BULLET_TIME` 后立即消失，没有过渡。

**修复**：
- 新增 `state.bulletDim`，按 `dt / 0.25` 线性进入/退出（250ms）；
- 压暗改为以青蛙/中央操作区为中心的径向渐变：中心透明，边缘最多 24%；
- 小蛙在遮罩之后绘制，能量条/提示在 DOM 层，保持清晰；减少动态效果时完全关闭；
- 未改 `bulletTimeSec: 2.5`、`fullScoreGraceSec: 0.6`、`maxTimingLoss: 0.10` 或任何输入处理。

**证据**：[子弹时间截图](../outputs/v1.9.4/after/game-bullet-1920.png)。

### 3.7 开发者模式顶部白栏

**根因**：`html.monitor-mode .game-layout` 的中央列是 `minmax(420px, 900px)`；关闭侧栏后列模板变成 `minmax(420px, 1fr)`，`.game-main` 与其中的 HUD 卡片、音乐行、配色栏都随 `1fr` 拉到接近整页宽（1920 下实测 1836px）。

**修复**：
- `html.monitor-mode .game-main { width:100%; max-width:1120px; justify-self:center; }`；
- `html.monitor-mode .page-skybar, .monitor-toggles { max-width:1120px; margin-inline:auto; }`；
- 1120px 与画布上限一致；900px 有侧栏时仍保持 900px。

**验收**：关闭两侧后 HUD/主列/画布/配色栏均为 1120px；四种组合连续切换后计时只前进、积分不变、SSE 连接数 2 不变（游戏流 + 监测流）；画布宽度始终 ≥ 720px（800×600 下 756px）。

**证据**：[修改前](../outputs/v1.9.4/before/game-dev-none-1920.png) / [修改后](../outputs/v1.9.4/after/game-dev-none-1920-final.png)。

### 3.8 商城装扮定价

**根因**：v1.9.3 的价格是 5–18 商城积分，而单局商城积分 = `max(1, floor(游戏积分 / 30))`；3 分钟典型局约 27–36 积分，因此旧价格基本 1 局即可买空普通装扮，经济节奏失效。

**修复**：
- 移除 `PRICE_MULT` 统一倍率，41 件商品逐件定价；
- 价格区间 24–240，分四档：入门 18 件（24–60）、普通 13 件（65–95）、稀有 7 件（120–150）、特殊 3 件（180–240）；
- 不修改 `pointsDivisor=30`、游戏计分、金币兑换或难度；
- 不改变 `bf-owned` / 后端 `inventories` 的 ID，不补收差价，不引入抽奖/限时促销。

**经济模拟**（`tests/score_distribution.js` 同口径，3 分钟，点击反应 0.8s）：

| 画像 | 60s | 180s | 300s |
|---|---:|---:|---:|
| 低专注 48 | 1 | 6 | 11 |
| 偏低 55 | 4 | 17 | 30 |
| 典型 60 | 7 | 27 | 43 |
| 基准 65 | 9 | 33 | 57 |
| 良好 70 | 12 | 42 | 73 |
| 高 85 | 18 | 63 | 106 |
| 间歇 70/45 | 5 | 22 | 37 |

按 33 积分/局估算：入门 1–2 局、普通 2–3 局、稀有 4–5 局、特殊 6–8 局；低收入（约 6 积分/局）分别为 4–10、11–16、20–25、30–40 局。完整 41 件新旧价格对照见 [PRICE-v1.9.4.md](PRICE-v1.9.4.md) 和 [price-comparison.csv](../outputs/v1.9.4/price-comparison.csv)。

### 3.9 家长成长中心留白

**根因**：`#parent-content` 不是 flex/grid 容器，`chart-grid` 没有上下 margin；`.growth-card + .growth-card` 只在两个成长卡相邻时生效，被图表区隔开的两段因此 0 间距。图表卡自身还有 1px 白边 + 阴影，与成长卡形成重复描边；caption 只有 4px 上边距。

**修复**：
- `#parent-content` 改为纵向 flex，统一 `gap:20px`；图表区内部同步 20px；
- 图表卡去掉白色硬描边，使用 18px 20px 20px 内边距和轻投影；
- 图表标题下 10px、图表容器内 2px、caption 上 12px；KPI 14–16px 内边距，定义列表行高 1.7；
- 760px 以下降为 16px 间距，避免小屏过度留白。

**验收**：9 个纵向区块全部 20px 间距（浏览器实测 `[20,20,20,20,20,20,20,20,20]`）；图表卡 `border-top-width=0`、内边距 `18px 20px 20px`。

**证据**：[修改前上部](../outputs/v1.9.4/before/parent-1440-top.png) / [修改前下部](../outputs/v1.9.4/before/parent-1440-bottom.png) / [修改后上部](../outputs/v1.9.4/after/parent-1440-top.png) / [修改后下部](../outputs/v1.9.4/after/parent-1440-bottom.png)。

### 3.10 附带修复：开发者工作台 500

验收时开发者面板显示「工作台读取失败：Internal Server Error」。服务端 traceback 指向 `_workbench_payload`：

```python
simulation=bool((report or {}).get("demo")
                or (report or {}).get("assessment", {}).get("simulation"))
```

当 `report["assessment"]` 显式为 `null` 时，`.get("assessment", {})` 返回 `None`，再 `.get` 触发 `AttributeError`。现在先判断 `isinstance(..., dict)`，空值按 `{}` 处理；工作台恢复正常读取。此为验收中发现的既有边界缺陷，不涉及计分或算法。

## 4. 修改文件

| 文件 | 内容 |
|---|---|
| `app/calibration.py` | `daily_v3`、刺激条件常量 |
| `app/server.py` | 校准请求/结果上下文、参考兼容提示、工作台空值修复、版本 1.9.4 |
| `app/storage.py` | 新校准默认 `method` 跟随当前协议 |
| `web/calibrate.html` | 平静池塘、音乐暂停/恢复、预设演示、确认跳跃、防连点、v3 提交、完成页协议说明 |
| `web/assets/calm-pond.js` | 新增低刺激池塘 canvas |
| `web/game.html` | 开始动画小蛙修复、子弹时间 250ms 渐变、矮屏转场 |
| `web/assets/eeg-monitor.css` | 顶部栏/主列 1120px 居中 |
| `web/profiles.html` | 统一头像容器、尺寸、圆角、居中 |
| `web/assets/frog/frog-art.js` | 头像紧凑视口 |
| `web/assets/dressup.js` | 逐件定价、移除统一倍率 |
| `web/assets/growth.css` | 家长中心间距/描边/内留白 |
| `tests/selfcheck_v194.py` | 新增 31 项静态/存储回归 |
| `tests/browser_ui_v194.py` | 新增 51 项真实浏览器验收 |
| `tests/selfcheck_v182/183/184.py`、`selfcheck_v193_visual.js` | 跟随 v3 与 1.9.4 版本断言 |
| `docs/PRICE-v1.9.4.md`、`outputs/v1.9.4/` | 价格对照与经济证据、前后截图 |

## 5. 验收

### 5.1 真实浏览器（Edge/Chromium CDP，隔离服务 8020）

```bash
PYTHONPATH="$PWD" .venv/bin/python tests/browser_ui_v194.py \
  --base http://127.0.0.1:8020 --cdp http://127.0.0.1:9333 \
  --out .deepworks/tmp/v194/browser --user-id <隔离 fixture B>
```

- **51 passed, 0 failed**；结果存档 [browser-result.json](../outputs/v1.9.4/browser-result.json)。
- 覆盖 1920×1080、1440×900、1280×800、1024×768、800×600：
  - 档案、校准、家长页无横向滚动；
  - 开发者游戏 5 档尺寸无横向滚动，画布占满主列；
  - 商城 1440/800 无横向滚动。
- 头像：5 张档案卡尺寸全部一致，图案中心偏移均为 0px。
- 侧栏切换：HUD/主列/画布/配色栏 1120px；计时 `00:58 → 00:57`，积分 0 不变，SSE 2→2。
- 开局动画小蛙画布不透明像素 2286（70×58 画布），不再空白。
- 家长页 9 个间距均 20px，图表卡 0 硬描边。

### 5.2 静态与存储回归

```bash
FOCUS_FROG_DATA_DIR="$PWD/.deepworks/testdata" PYTHONPATH="$PWD" \
  .venv/bin/python tests/selfcheck_v194.py
```

**31 passed, 0 failed**，覆盖协议、Schema 4、刺激/教学记录、旧参考保留、头像/价格/布局静态契约。

隔离商城购买测试：初始 1000 积分、已拥有 `hat-leaf`；购买 `face-blush`（24 分）返回 `ok`，余额 976，`face-blush` 已拥有，`hat-leaf` 权益保留，未写入真实数据库。

### 5.3 既有回归

| 测试 | 结果 |
|---|---|
| `tests/selfcheck_v181.py` | 33 项通过 |
| `tests/selfcheck_v182.py` | 36 项通过（新增 v2/v3 不混算） |
| `tests/selfcheck_v183.py` | 52 项通过 |
| `tests/selfcheck_v184.py` | 52 项通过 |
| `tests/selfcheck_v190.py` | 29/29 |
| `tests/selfcheck_v191.py` | 12 项通过 |
| `tests/selfcheck_score_mapping.py` | 全部通过 |
| `tests/selfcheck_denoise.py` | 14 类场景全部通过 |
| `tests/selfcheck_round_logic.js` | 36 项通过 |
| `tests/selfcheck_v184_round.js` | 14 项通过 |
| `tests/selfcheck_v184_ui.js` | 17 项通过 |
| `tests/selfcheck_v192_ui_static.js` | 10 项通过 |
| `tests/selfcheck_v193_visual.js` | 11 项通过（同步 1.9.4） |
| `tests/selfcheck_ui_static.js` | 15 项通过（同步 1.9.4 版本） |
| `tests/score_distribution.js` | 计分分布可重复输出 |

`selfcheck_monitor.py` 因本环境没有 EDF 回放样本而跳过，与本次改动无关；`e2e_hardware_denoise.py` 需要真机，未执行。v1.9.3 浏览器脚本硬编码其专用 fixture 用户，本环境未复跑；v1.9.4 新脚本已覆盖同样的 10 个页面与 5 档尺寸中的关键页面。

### 5.4 完整校准流程

隔离手动模拟完成：平静 30 秒 → 演示 → 教学 30 秒 → 结果。完成页显示「今日有效」和 v3 协议说明；`sessionStorage.bf-dev-calib` 记录 `protocol_version = "daily_v3"`；无脚本错误。手动输入恒定导致测试记录标记 `stretched`，这是测试信号平坦所致，不进入真实档案。

## 6. 自主决策

1. **协议版本直接升为 `daily_v3`**，未复用 v2。原因：刺激条件（视频/池塘）与教学操作都已改变，不能伪装成同一协议。旧 v2 每日校准失效需重校一次；旧长期参考保留，不静默覆盖。
2. **刺激条件和教学事件写入 `source_info`**，不新增 Schema 列。避免为元数据做数据库迁移，符合“Schema 4 不变”的约束。
3. **平静阶段移除视频而不是修好旧视频**。固定池塘更符合低刺激、可复现和离线要求，也避免 6.6MB 外部媒体与不可控内容。
4. **教学演示不写入教学窗口**。演示操作不是采集数据；30 秒从演示结束后开始，避免把演示帧混入教学基线。
5. **价格按 41 件逐件定价**，保留 4 档但每件不同，不使用统一倍数；以 3 分钟、33 积分/局作为典型参考，并单独给出低收入可获得性。
6. **附带修复工作台空值崩溃**。它在本次开发者验收中稳定复现且阻断面板读取，属于安全的防御性修复，不改变业务。

## 7. 已知限制

- 本环境没有 Xmuse 真机与 EDF 回放样本，校准/游戏完整流程使用手动模拟；真实硬件下的信号质量、眨眼、运动伪迹和 30 秒有效帧表现仍需真机复核。
- v3 会让旧 `daily_v2` 每日校准显示「今日尚未校准」，用户需要重做一次；这是协议不可比的预期行为。
- 旧长期参考不会自动升级为 v3；需要家长在开发者工作台手动建立新版参考。
- 800×600 下校准页仍需纵向滚动才能看到完整教学卡片底部说明；已保证按钮和关键提示在首屏内，且无横向滚动。
- 商城经济模拟不含真实儿童的信号波动、退出、暂停和失败局；局数区间是规划参考，不是承诺。
- 未删除仓库中历史 `web/assets/relax.mp4` 文件（已无页面引用）；删除二进制资产需单独确认。
- 未推进桌面封装、安装包、v1.9.5 或其他未授权功能。

## 8. Git 发布

- 提交信息：`feat(ux): 优化校准引导、游戏反馈与局部体验 (v1.9.4)`
- 标签：`v1.9.4`
- 提交身份、远程地址、提交哈希、标签指向和真实数据库最终状态在发布后由仓库与远程核验；不使用其他 Agent 或账户身份。
- 如果远程权限或身份校验失败，保留本地成果并报告实际阻塞，不伪造发布成功。
