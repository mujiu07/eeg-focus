# 专注小蛙 v1.9.3 开发报告

- 版本：`v1.9.3`
- 日期：2026-11-28
- 父版本：`v1.9.2`（commit `b6d20e4`）
- 范围：全站视觉一致性修复；不新增功能，不改脑电算法、玩法、校准、自适应难度、计分、商城经济、Schema 4 或档案业务。

## 1. 结论

本版完成了三项收口：

1. **小蛙角色统一**：以首页池塘小蛙为唯一原型，统一档案、成长、校准、报告、成就过场与游戏画布中的角色几何。商城、装扮、游戏继续共享 `PondEffects` 的椭圆青蛙几何。
2. **边框与留白统一**：外层卡片保留轻描边，嵌套子卡改用底色/间距分层，去掉档案、成长、家长、报告、设置、校准说明框中的重复硬描边；商城/装扮可选卡片和开发者工作台保留必要分隔。
3. **图标语义统一**：功能性 Emoji 替换为 24×24、1.8 描边的自然线框图标；商城道具、装扮、金币、礼物和既有成就插画保留独立美术。

真实浏览器验收结果：

| 检查 | 结果 |
|---|---|
| v1.9.3 全页面/弹窗浏览器检查 | **310 passed, 0 failed** |
| v1.9.2 旧 UI 浏览器回归 | **364 passed, 0 failed**（本环境 fixture） |
| 覆盖尺寸 | 1920×1080、1440×900、1280×800、1024×768、800×600 |
| 覆盖页面 | 首页、档案、校准、游戏、报告、历史、商城/装扮、成长、家长、开发者等 10 个页面 |
| 覆盖弹窗 | 商城、装扮、成就、时长选择、新建档案、成就过场，1440/800 两档 |
| 横向滚动/脚本错误/功能性 Emoji | 未发现 |
| 首页以外页面左上角返回入口 | 全部存在 |
| 每只标准小蛙的眼睛与嘴巴 | 全部为 2 眼 + 嘴巴 |
| 子卡重复硬描边 | 未在检查页面发现 |

## 2. 发现的问题与修复

| 问题 | 证据 | 修复 |
|---|---|---|
| 档案页、成长页、报告页、成就过场使用不同青蛙 | 有的使用系统青蛙 Emoji，有的使用旧自绘青蛙；首页池塘青蛙才是产品原型 | 新增 `web/assets/frog/frog-art.js`，统一从 `PondEffects.frogEllipses` / `frogMouth` 读取几何与配色；各页改为 `FrogArt`/共用几何 |
| 全站青蛙看起来只有一只眼 | CSS `.frog-eye` 的 `transform: scaleY()` 动画覆盖了 SVG `transform="translate"`，右眼被移到错误位置 | 新增 `.frog-eye-wrap` 承担 SVG 位移，内层 `.frog-eye` 只负责眨眼动画；静态与成就过场均使用同一结构 |
| 成就过场出现第二套青蛙美术 | `achievement-cinematic.js` 内嵌旧 `FROG_SVG` | 删除旧自绘青蛙，改用 `FrogArt.svg()`；调整 `game.html` 脚本顺序，确保 `FrogArt` 先加载 |
| 成就 burst 阶段眼睛消失 | 旧 CSS 在 burst 阶段切换眼睛显隐，叠加新几何后只剩嘴巴 | 补 `.ach-cine.is-burst .frog-eyes--open` / `.frog-mouth--line` 可见规则；过场最终截图需在本次提交前复核 |
| 功能性 Emoji 风格不统一 | 导航、天空、报告指标、设置、开发者页、成就、签到 Toast 混用 Emoji | 新增 `web/assets/icons/`，统一 `data-icon` 挂载；保留商城/装扮/金币/礼物/成就插画的独立美术 |
| 卡片重复描边、视觉拥挤 | 档案卡、成长统计/KPI、家长 KPI、报告统计、设置状态框、校准提示框出现外层 + 内层硬边 | 新增 `visual-v193.css`；外层保留轻描边，子卡改用半透明底色和留白；报告统计卡去边框；选中卡只保留绿色强调 |
| 最近训练链接出现浏览器默认蓝色下划线 | 报告页 `a.stat` 未继承主题 | 增加 `a.stat { color: inherit; text-decoration: none; }` |
| 校准页重复“信号来源”标签 | 静态结构有重复标签 | 删除重复标签，保留一次语义 |
| 报告统计小蛙过大 | 统计卡内青蛙尺寸与卡片不匹配 | 限制为 42px，并保持“鼓励”姿态 |
| 1024/800 下顶部动作区拥挤 | 小屏 topbar 动作按钮挤压品牌区 | 增加小屏 gap/padding 与动作区换行规则；1024 以下开发者侧栏允许在游戏区下方堆叠 |

## 3. 小蛙统一方案

### 3.1 唯一原型

- 几何来源：`web/assets/pond-effects.js` 的 `PondEffects.frogEllipses` 与 `PondEffects.frogMouth`。
- 固定配色：
  - 深绿：`#346951`
  - 主体绿：`#609b68`
  - 浅绿：`#b9cf94`
  - 肚皮：`#fbf3d9`
  - 眼睛/线条：`#263b33`
- 眼睛：左右两个独立椭圆，保留高光；瞳孔使用深色圆点。
- 嘴巴：默认细弧线；开心/庆祝使用 `FrogArt.svg({ expression: "cheer" })` 或 `"smile"`。
- 首页 `#pondFrogArtwork` 保持原有池塘绘制，不改原型、不改位置、不改动画。

### 3.2 素材目录

```text
web/assets/frog/
  frog-art.js          # 唯一运行时渲染器
  frog-prototype.svg   # 透明背景预览/设计对照
  README.md            # 调用规范与颜色/尺寸说明
```

### 3.3 调用规范

- 静态页面：`<span data-frog="cheer" data-frog-size="96"></span>`，由 `FrogArt.mountAll()` 挂载。
- 动态 DOM：`FrogArt.svg({ expression, className, title })` 返回 SVG 字符串，禁止另写青蛙路径。
- 游戏画布/商城预览：继续使用 `PondEffects` 的同一几何；不为了统一而破坏商城道具坐标。
- 装扮/皮肤：保留现有服装层与配饰层；小蛙本体颜色和眼睛/嘴巴不变，服装位置按原画布坐标继续使用。
- 禁止：系统青蛙 Emoji、另绘不同脸型/眼睛/嘴巴、用 3D 渲染替代 2D 原型。

### 3.4 各页面落点

| 页面/模块 | 统一后 |
|---|---|
| 首页池塘 | 保留 `#pondFrogArtwork`，作为唯一标准 |
| 首页顶栏头像 | `FrogArt` 小尺寸头像 |
| 档案页 | 档案头像、选中徽章、空状态提示统一标准小蛙 |
| 成长页 | 品牌位、场景小蛙、日历/足迹小蛙统一标准小蛙 |
| 校准页 | idle 小蛙 + 月亮图标；不再只有月亮 |
| 报告页 | cheer 小蛙 + 统计卡 42px 小蛙 |
| 成就页/过场 | 15 个成就图标中“青蛙”成就使用标准小蛙；过场使用同一几何 |
| 商城 | 商品图保留独立美术；商品中的小蛙预览共享几何 |
| 装扮 | 服装/配饰保留；预览小蛙共享几何 |
| 游戏 | 游戏画布共享 `PondEffects`；HUD 使用统一图标 |
| 家长/开发者 | 不强行放青蛙；图标与卡片层级统一 |

## 4. 边框、圆角、阴影与留白

新增 `web/assets/visual-v193.css`，核心变量：

```css
--v-line: rgba(52, 105, 81, .14);
--v-line-strong: rgba(52, 105, 81, .22);
--v-card-radius: 20px;
--v-card-shadow: 0 10px 30px rgba(38, 59, 51, .07);
--v-surface-soft: rgba(255, 255, 255, .58);
--v-gap: 18px;
```

落地规则：

- **外层面板**：保留 1px 轻描边 + 柔和阴影，形成页面层级。
- **嵌套子卡**：不再重复 1px 硬边，改用 `background: var(--v-surface-soft)`、内边距和间距区分。
- **档案卡**：非选中卡去硬边；选中卡保留绿色边框/底色作为状态，不叠加第二层描边。
- **成长统计/KPI/详情**：统计块与详情块去重复边线；标题与数值通过字号/颜色分层。
- **家长 KPI**：去掉每个 KPI 的独立硬框，保留卡片内分组。
- **报告统计**：`.stat` 去边框，改用半透明底色；数字、标签、图标三级层次。
- **设置状态框**：`.stat-box` 去硬边，保留分组留白。
- **校准提示**：内层提示去边，保留外层卡片和左侧色条语义。
- **商城/装扮**：可选卡片保留必要边界；选中态用绿色描边 + 轻底色，不再叠加内框。
- **开发者工作台**：保留深色工作台与信息分区，不为了“去边框”牺牲可读性。
- **小屏**：800/1024 下减少卡片 gap，topbar 动作区换行；不出现横向滚动。

## 5. 图标体系统一

- 文件：`web/assets/icons/icons.js`、`web/assets/icons/icons.css`。
- 规格：24×24 viewBox、1.8 描边、`stroke-linecap: round`、`stroke-linejoin: round`、无填充（特殊状态除外）。
- 语义命名：`home`、`chart`、`search`、`family`、`settings`、`sliders`、`tool`、`activity`、`signal`、`eeg`、`gamepad`、`device`、`flask`、`eye`、`clipboard`、`chat`、`lock`、`warning`、`trophy`、`sunrise`、`sun`、`sunset`、`moon`、`hanger`、`tree`、`bookBlue` 等。
- 同一功能在所有页面使用同一名称；尺寸由 CSS 控制，不在页面内写多套 SVG。
- 成就图标保留各自语义插画；只有“青蛙”成就复用标准小蛙。商城道具、装扮、金币、签到礼物不机械替换成线框图标。
- 天空主题：`sky.js` 的 `SKY_ICONS` 统一使用 `Icons.svg`；`index/profiles/settings` 均接入 `sky.css`/`sky.js`。
- 兼容：`Icons.mountAll()` 处理静态 `data-icon`；动态 HTML 通过 `Icons.svg(name)` 返回字符串。

## 6. 验收与产物

### 6.1 自动化

- `tests/browser_ui_v193.py`：真实 Edge/Chromium CDP；10 页面 × 5 尺寸；商城/装扮/成就/时长/新建档案/成就过场截图；检查无横向滚动、无脚本错误、无功能性 Emoji、图标挂载、返回入口、青蛙眼睛/嘴巴、子卡重复硬边框。
- `tests/browser_ui_v192.py`：旧 UI 回归，确保本版没有破坏 v1.9.2 的交互与布局。
- `tests/selfcheck_v193_visual.js`：视觉契约静态检查。
- `tests/selfcheck_ui_static.js`：版本契约与页面结构检查。
- 所有测试使用隔离数据目录；没有向真实 `profiles.db` 写入。

### 6.2 截图

- After 全量：65 张（50 页面 + 12 弹窗 + 1 游戏启动 + 2 错误态）；`outputs/v1.9.3/after/<width>/<page>.png`。
- Before 日间基线：26 张；`outputs/v1.9.3/before/1440/`、`outputs/v1.9.3/before/800/`。
- 前后对比：27 张；`outputs/v1.9.3/compare/<page>-1440.png`、`<page>-800.png`。
- 总览：`outputs/v1.9.3/compare/overview-1440.png`、`overview-800.png`。
- 小蛙对照：`outputs/v1.9.3/compare/frog-lineup.png`。
- 成就过场：`outputs/v1.9.3/after/1440/modal-achievement-cinematic.png`。
- 错误提示态：`outputs/v1.9.3/after/1440/state-history-error.png`、`outputs/v1.9.3/after/800/state-history-error.png`。

### 6.3 数据隔离

- v1.9.3 测试服务：`8017`，数据目录 `.deepworks/tmp/v193/data`。
- v1.9.2 对照服务：`8018`，数据目录 `.deepworks/tmp/v193/before-data`。
- 真实服务：`8010`，真实库 `/Users/fan/Documents/专注小蛙/profiles.db`。
- 真实库抽查：`users=2, sessions=7, rounds=9, calibrations=0, assessments=0, difficulty_profiles=1`；`integrity_check=ok`；Schema 4。该库为应用真实数据，本轮未写入、删除或迁移。
- 本版没有删除、迁移或写入真实库；视觉验收不改变任何档案、难度、经济或成就数据。

## 7. 已知限制与未解决项

- 没有 Xmuse 真机、Windows 实机或真实儿童/家长可用性测试；验收基于本地 macOS + Edge CDP。
- 没有逐项使用真实浏览器 125%/150% 操作系统缩放；使用等效 CSS 视口覆盖主要断点。
- “边框是否拥挤、图标是否足够可爱”仍有主观审美判断；本报告记录的是已识别的硬问题与统一规则。
- 1024px 以下开发者侧栏允许在游戏区下方堆叠；“所有内容都在首屏”不适用于这类长信息页。
- 成就过场在 `prefers-reduced-motion` 下走静态分支，仍保留标准小蛙和奖励信息；未做真实低动态设备测试。
- 本轮未改 Electron/桌面打包；浏览器直接打开 `web/*.html` 与 `8010` 服务模式均可用。
- 已抽查正常加载和历史报告缺 session id 的错误态；未做慢网/API 500 的网络故障注入，加载中/异常态仍沿用既有结构。

## 8. 主要修改文件

- `web/assets/frog/frog-art.js`、`frog-prototype.svg`、`README.md`
- `web/assets/icons/icons.js`、`icons.css`
- `web/assets/visual-v193.css`
- `web/assets/achievement-cinematic.js`、`achievement-cinematic.css`
- `web/assets/achievements.js`、`checkin.js`、`growth-diary.js`、`growth-parent.js`、`sky.js`
- `web/index.html`、`profiles.html`、`growth.html`、`parent.html`、`history.html`
- `web/calibrate.html`、`report.html`、`settings.html`、`dev.html`、`game.html`
- `app/server.py`（版本号 1.9.3）
- `tests/browser_ui_v193.py`、`tests/selfcheck_v193_visual.js`
- `tests/selfcheck_ui_static.js`（版本契约）
- `CHANGELOG.md`、`README.md`、`docs/README-dream-pond-focus-frog.md`、`docs/tech-stack.md`、`docs/PROJECT-DOC-dream-pond-focus-frog.md`、`docs/ARCHITECTURE.md`、`docs/usage-and-privacy.md`
