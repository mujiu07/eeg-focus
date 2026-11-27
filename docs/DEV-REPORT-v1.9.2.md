# 专注小蛙 v1.9.2 开发报告：全局 UI 修复与交互一致性

> 基准版本：v1.9.1（2026-11-28）
> 发布版本：v1.9.2（2026-11-28）
> 范围：`web/` 用户界面、布局、导航与交互一致性
> 未修改：脑电算法、校准算法、难度策略、游戏计分公式、Schema 4、账户/报告业务

---

## 1. 结论

v1.9.2 不新增玩法，不改变分数、难度或数据库结构，集中解决四类真实 UI 根因：

1. **侧栏隐藏后的 Grid 自动排布错位**：隐藏左侧波形后，中央主列掉进宽度 0 的第一列，画布被压成 6×6，页面被撑到 2918px 高。
2. **音乐控件使用窗口 fixed 定位**：唱片机固定在窗口右上角，滚动后会覆盖开发者工作台标签页；在 1440/1280 等校屏宽度还会压住页面卡片边缘。
3. **首页重复入口**：开始游戏、装扮、设置、直接校准存在多个同义入口；设备连接/校准没有完全交给开始游戏流程按需引导。
4. **全站返回首页与按钮对齐不一致**：部分页面没有首页入口，部分入口只在右下角；`.btn` 没有统一的 flex 居中规则。

修复后使用一套轻量公共样式和明确容器归属，不引入 UI 框架，也不改变池塘、小蛙、荷叶、天空和黑胶唱片美术。

---

## 2. 发现的问题、证据与根因

### UI-01 侧栏隐藏后中央区域塌陷

**复现**（v1.9.1，1440×900，开发者试玩）：

| 状态 | 主列宽度 | 画布尺寸 | 布局高度 |
|---|---:|---:|---:|
| 左右都显示 | 745.2px | 745.2×384.1px | 903px |
| 仅隐藏左波形 | **0px** | **6×6px** | **2918px** |
| 左右都隐藏 | **0px** | **6×6px** | **2918px** |
| 仅隐藏右工作台 | 900px | 900×463px | 982px |

**根因**：旧 CSS 只做了两件事：

```css
.game-layout.left-off { --mon-left: 0px; }
.game-layout.left-off .monitor-left { display: none; }
```

隐藏的左栏退出 Grid 自动排布后，中央 `.game-main` 被浏览器自动放进第一列（0px），右侧工作台进入第二列；第三列空着。不是 Canvas 比例计算或 ResizeObserver 单独的问题。

**修复**：`web/assets/eeg-monitor.css` 使用显式 `grid-template-areas`：

```css
grid-template-areas: "left main right";
grid-template-columns: var(--mon-left,310px) minmax(420px,900px) var(--mon-right,360px);
.monitor-left { grid-area: left; }
.game-main { grid-area: main; }
.monitor-right { grid-area: right; }
```

`left-off/right-off/both-off` 分别重建为“主列+右栏”“左栏+主列”“主列独占”。中央画布上限从 900px 调到 1120px，两侧都隐藏时真正利用可用空间；`setPanel()` 在下一帧派发 `resize`，游戏页重新计算画布位图和指针比例。

### UI-02 音乐唱片遮挡开发者工作台

**复现**：v1.9.1 游戏页的 `.vinyl-player` 是 `position: fixed; top:16px; right:18px; width:250px; z-index:45`。1440 宽度下右边栏从 x=1082 开始，唱片机横跨 x=1172–1422；滚动 240px 后右侧工作台顶部进入 y=0–146，唱片机覆盖“概览/基线”等标签。

**根因**：控件归属于浏览器窗口，而不是中央游戏容器。只提高/降低 z-index 无法解决滚动时的遮挡。

**修复**：

- `web/game.html` 增加 `.game-media-row` 与 `data-music-host`，音乐控件挂到 `.game-main` 内；
- `web/assets/music.js` 优先挂载到 `[data-music-host]`，没有宿主时才回落到 `document.body`；
- `.game-music-host .vinyl-player` 改为容器内相对定位；
- 非游戏页面在 1101–1519px 使用可展开的小唱片按钮，避免 1440/1280 宽度压住卡片；≤1100px 保持顶部小按钮并修正 z-index，避免被 `.sky-veil` 盖住；1920px 仍有完整播放器。

### UI-03 首页重复入口与必要入口缺失

**修改前**：

- 开始游戏：顶部导航按钮 + 英雄区按钮，跳转/打开同一时长弹窗。
- 小蛙装扮：顶部装扮 chip + 功能导航按钮，打开同一 `DressUp` 面板。
- 设置：只在功能导航，顶部没有。
- 脑电校准：英雄区直接按钮 + 开始游戏内部自动引导。
- 开发者工作台：主要靠首页 Konami 彩蛋/家长页入口，首页没有明确管理入口。

**修改后**：

| 功能 | 修改前 | 修改后 |
|---|---|---|
| 开始游戏 | 导航 + 英雄区双按钮 | 英雄区唯一主按钮；需要档案/校准时时按条件引导 |
| 小蛙装扮 | 顶部 chip + 功能导航 | 功能导航唯一入口；顶部 removed |
| 设置 | 功能导航 | 顶部唯一设置入口 |
| 设备/每日校准 | 独立主按钮 | 开始游戏流程按需引导；档案页“重新校准”和开发者页保留直接入口 |
| 开发者工作台 | 隐藏彩蛋/家长页 | 设置页明确的「开发者工作台」入口；家长页保留；不占儿童主入口 |
| 商城/签到/成就 | 顶部 chip | 保留，属于独立经济/奖励功能，不是主页面重复入口 |

首页导航最终为：`小蛙装扮 / 成长日记 / 家长报告`，顶部为 `当前档案 / 设置`，英雄区为 `开始游戏`。

### UI-04 子页面缺少首页入口

**修改前**：`profiles`、`game`、`settings`、`dev` 没有统一首页入口；growth/parent/history 的首页链接位于右侧导航；calibrate 的返回按钮在右侧；report 只有底部返回。

**修复**：新增公共 `.home-link` 和 `.app-topbar`，所有独立页面顶部左侧有 `🏠 首页`；game 的 home 位于页面配色栏左侧，report 位于页面配色栏左侧；growth/parent/history 使用顶部 app-topbar。正式游戏/校准返回首页前确认并清理 SSE/Session；弹层关闭返回首页。

### UI-05 按钮文字/图标未统一居中

**根因**：旧 `.btn` 只有 padding、font-size、颜色，没有 `display:flex` / `align-items`；`a.btn`、图标 + 多行文本、不同字号按钮在部分页面出现垂直偏移。没有统一的 icon-button / top-link / home-link 规范。

**修复**：新增 `web/assets/ui.css`，给 `.btn` 增加 `inline-flex`、水平/垂直居中、`gap`、`line-height`、`max-width`、focus-visible；统一 `.home-link`、`.top-link`、`.growth-link`、`.mon-small-btn` 等控件的内部对齐；信息卡片、列表项保持左对齐，不机械居中。

### UI-06 窄屏音乐 / 顶栏 / 侧栏

- 1440/1280：音乐缩为可展开小唱片按钮，不占卡片右侧空白。
- 1024/800：音乐按钮留在顶部，修正 `z-index`，不再被环境遮罩层挡住；游戏侧栏在 1220px 以下改为下方堆叠，中央先保证可操作。
- 页面顶部 `app-topbar` 可换行；`page-skybar` 的首页入口与小屏天空切换共处一行，不产生横向滚动。
- 125%/150% 使用等效 CSS 视口（1152/960 等）验证，详见 §5。

### UI-07 开发者页监视线程清理

`dev.html` 的实时监视原先只在点击“停止监视”时关闭 SSE。新增 `pagehide`：先关闭 `watchEs`，再结束后台测试 Session，避免离开页面后残留监视连接。

---

## 3. 修改文件

| 文件 | 修改 |
|---|---|
| `web/assets/ui.css` | 新增全站 UI 规范：顶部栏、首页链接、按钮居中、状态、响应式 |
| `web/index.html` | 合并重复入口；设置移至顶部；移除直接校准；装扮回归单一入口 |
| `web/assets/eeg-monitor.css` | Grid areas、四种侧栏布局、窄屏堆叠、画布上限 1120 |
| `web/assets/eeg-monitor.js` | 侧栏切换后 resize + 重绘；隐藏/暂停/停止语义标题 |
| `web/assets/vinyl.css` | 游戏宿主、宽度断点、小屏可见性/上层、非游戏紧凑控件 |
| `web/assets/music.js` | 优先挂载 `[data-music-host]` |
| `web/game.html` | 首页与确认退出、中央音乐行、画布 1120、清理流程、语义标题 |
| `web/calibrate.html` | 顶部首页、运行时确认、SSE/Session 清理 |
| `web/profiles.html` | 顶部首页/设置；去掉重复设置入口 |
| `web/settings.html` | 顶部首页/开发者工作台 |
| `web/dev.html` | 顶部首页；pagehide 结束后台测试 Session |
| `web/report.html` | 顶部首页（底部保留为长报告便利入口） |
| `web/growth.html` / `parent.html` / `history.html` | 顶部首页栏；保留上一级导航 |
| `app/server.py` | FastAPI `version` 1.9.2 |
| `requirements.txt` | 可选浏览器 UI 回归依赖 `websocket-client` |
| `tests/selfcheck_ui_static.js` | 版本契约更新 |
| `tests/selfcheck_v192_ui_static.js` | 新增 10 项 UI/导航静态契约 |
| `tests/browser_ui_v192.py` | 新增真实 Edge/Chromium CDP 验收 |

---

## 4. 公共 UI 规范

### 4.1 结构

- `.app-topbar` / `.app-topbar__left` / `.app-topbar__actions`：页面顶部左右分组，可换行。
- `.home-link`：全站唯一“首页”视觉；房子图标 + 文字；`min-height:40px`；不用于“返回上一级”。
- `.top-link`：设置等次级管理入口；与首页按钮区分。
- `.ui-page` / `.ui-page__title` / `.ui-page__sub`：新页面可复用内容宽度、标题和副标题。
- `.game-layout`：三栏 Grid 的 `left / main / right` 区域；折叠状态只重排区域，不重建页面。

### 4.2 控件

- `.btn`：`inline-flex`、水平/垂直居中、`gap:.45em`、多行可换行、focus-visible、disabled 不改变尺寸。
- `.btn-primary` / `.btn-ghost` / `.btn-warm`：保留原池塘色和阴影。
- `.btn-danger` / `.btn.danger`：危险操作语义色；当前页面没有新增危险业务操作。
- `.icon-button`：36px 图标按钮规范；现有监控图标继续用专用 `.mon-icon`。
- `.growth-link` / `.mon-small-btn`：胶囊内部居中；标签页/筛选按钮保持固定 padding，不因选中态字重改变尺寸。
- `.ui-state` / `.ui-state--error` / `.ui-loading`：加载、空状态、错误状态的公共外观；已有页面渐进复用。

### 4.3 不改变的内容

- 首页池塘、云、月亮、小蛙、荷叶、水花、天空切换动画保留。
- 黑胶唱片视觉、唱臂动画、切歌/音量/本地状态保留。
- 儿童端继续隐藏实时脑电分、蓄力百分比、BPM、信号质量；开发者面板仍只在 `developerRun` 下创建。

---

## 5. 验收结果

### 5.1 真实浏览器

命令（隔离测试库 `8017`，非真实档案）：

```bash
.venv/bin/python tests/browser_ui_v192.py \
  --base http://127.0.0.1:8017 \
  --cdp http://127.0.0.1:9333 \
  --out .deepworks/tmp/v192/browser-evidence3
```

结果：**463 passed, 0 failed**。

视口矩阵（9 个页面 × 9 个宽度）：1920×1080、1440×900、1280×800、1024×768、800×600，以及 125%/150% 等效宽度 1536×864、1280×720、1152×720、960×600。所有页面：

- 无横向滚动 `scrollWidth <= innerWidth + 1`；
- 按钮内容中心偏差在阈值内；
- 顶部首页入口存在且位于页面上部左侧；
- 无未捕获脚本错误；
- 带音乐的页面控件 `visible` 且 `z-index >= 1`；
- 游戏 1920/1280/1152/1024/960/800 画布宽度 > 250，首页入口左上，音乐控件可见，无横向滚动。

### 5.2 四种侧栏状态

真实游戏演示（1440×900）实测：

| 状态 | 主列 | 画布 |
|---|---:|---:|
| 全部显示 | 745.2px | 745.2×384.1px |
| 仅隐藏左波形 | 1031.2px | 1031.2×530.1px |
| 仅隐藏右工作台 | 1081.2px | 1081.2×555.1px |
| 两侧都隐藏 | 1367.2px | 1120×575px |

- 四种状态都满足 `music` 不与右侧工作台、HUD、蓄力条相交；
- 连续切换 20 次，画布最小宽度 > 300px；
- Session POST / `/stream` / `/monitor` 数量不增加；
- 本局积分不重置，计时不回到开局值；
- 侧栏显示/隐藏不重启游戏、不重新订阅监测。

### 5.3 音乐控件

- 游戏开发者模式：音乐位于中央容器，工作台滚动到顶时不再覆盖“概览/基线/难度/诊断/评估导出”标签。
- 游戏普通儿童模式（隔离库临时有效校准，1440/1024/800）：音乐正常显示；1440 为 250px 播放器，≤1100 为 44px 小唱片；无横向滚动。
- 非游戏 1440/1280：250px 播放器收缩为 48px 唱片按钮；展开面板在 1440 位于卡片右侧空白，不覆盖按钮；1920 恢复完整播放器。

### 5.4 静态与既有回归

- 新增 `tests/selfcheck_v192_ui_static.js`：**10/10**。
- 既有 `tests/selfcheck_ui_static.js`：**15/15**。
- v1.9.1：**12/12**；v1.9.0：**29/29**；v1.8.4：52；v1.8.3：52；v1.8.2：35；v1.8.1：33。
- v1.8.4 UI 17、v1.8.4 单轮 14、静态 UI 15、单轮逻辑 36、v1.8.3 单轮 8、监测 9、去噪全项、计分映射全部通过。
- `py_compile`、`node --check`、`git diff --check` 通过。

### 5.5 真实数据隔离

真实运行服务最终为 `http://127.0.0.1:8010`，FastAPI version `1.9.2`；真实库 `profiles.db` 保持 `integrity_check=ok`、Schema 4、3 个档案/6 个 Session。最终复核 `/api/profiles` 返回 200。

开发早期做 v1.9.1 基线截图时曾误用 8010 的开发者试玩，产生 3 条 `demo=1` 的测试 Session（用户“阿”，2026-11-28 00:59–01:03）。发现后已先创建一致性备份：

```text
/Users/fan/Documents/专注小蛙/backups/profiles-20261128-013506-before-v192-test-session-cleanup-fc4cf.db
```

随后仅按已知 Session ID 删除这 3 条开发测试记录（`rounds` 级联为 0），未删除用户、校准、钱包、成就或历史 Session；清理后真实库恢复为 3 个档案/6 个 Session。正式 UI 验收仍使用 `8017` + `.deepworks/tmp/v192/data` 隔离目录，不触碰真实档案。

### 5.6 截图

- 首页前/后：[compare/home-before-after.png](../outputs/v1.9.2/compare/home-before-after.png)
- 侧栏四状态前/后：[compare/sidebars-4states-before-after.png](../outputs/v1.9.2/compare/sidebars-4states-before-after.png)
- 音乐遮挡修复前/后：[compare/music-workbench-before-after.png](../outputs/v1.9.2/compare/music-workbench-before-after.png)
- 主要页面总览前/后：[compare/pages-sheet-before-after.png](../outputs/v1.9.2/compare/pages-sheet-before-after.png)
- 全尺寸副本：`outputs/v1.9.2/before/`、`outputs/v1.9.2/after/`

---

## 6. 未解决与边界

- 没有真实 Xmuse 真机、Windows 实机或儿童/家长可用性测试；本报告不声称真机/Windows/临床验收通过。
- 125%/150% 使用等效 CSS 视口验证，不是操作系统浏览器工具栏逐项点击；两者在布局断点上等价，但仍需在目标机器复核。
- 1101–1519px 的非游戏页面音乐控件采用小唱片按钮（点击展开），这是为避免覆盖卡片作出的设计决策；完整播放功能保留。
- 1024px 以下开发者工作台允许在中央游戏区下方堆叠；不强行维持不可读的三栏。游戏仍可操作，侧栏可通过顶部按钮/独立滚动访问。
- 弹窗（装扮、商城、签到、成就）是首页内浮层而非独立路由；关闭即返回首页，不额外设置重复首页按钮。
- `report.html` 底部“返回首页/返回开发者模式”作为长报告的可达性辅助保留；顶部统一首页入口仍是唯一的主导航入口。
- 家长确认层仍只是使用场景分隔，不是身份认证；SQLite 与导出文件仍未静态加密。

---

## 7. 自主界面设计决策

1. **首页只保留一个“开始游戏”主按钮**：放在英雄区；顶部导航不再重复。设备/每日校准交给开始游戏流程按条件引导。
2. **“小蛙装扮”回到功能导航**：移除顶部 chip，避免同一 `DressUp.open()` 出现两个入口；装扮、成长日记、家长报告组成三个主要功能链接。
3. **设置放到首页顶部**：与当前档案并列，解决设置既是顶层管理又藏在功能导航中的信息层级冲突；开发者工作台在设置页明确露出，同时保留原 Konami 入口。
4. **侧栏折叠用 grid areas 而不是动画 width**：避免隐藏项自动排布导致中央列掉到 0px；四种状态都有明确结构。
5. **音乐容器优先于窗口**：游戏页挂到 `.game-main`；其他页面在无右侧空间时缩为唱片按钮，保留完整播放/切歌/音量/展开。
6. **统一首页入口但保留上下文动作**：顶部 `.home-link` 是“首页”；家长页/历史页的“家长报告/小蛙日记”是上一级；游戏“退出游戏”是结束当前流程；档案页“选择/切换”仍是档案动作。
7. **不引入框架、不重做美术**：只新增 `ui.css` 和必要容器/类，保留现有池塘视觉与黑胶动画。

---

## 8. 发布检查

- 无 Schema 4 变更；
- 无脑电/校准/难度/计分公式修改；
- 所有自动化测试与真实浏览器布局检查通过；
- 通过既有 Git 身份 `mujiu07 <mujiu07@users.noreply.github.com>` 提交并打 `v1.9.2` 标签；
- 所有测试写入使用隔离数据目录。
