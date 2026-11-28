# 专注小蛙 v1.9.5 开发报告：九宫格头像与背景可读性

日期：2026-11-28  
基线：`02aee04`（v1.9.4）  
应用版本：`1.9.5`  
玩法参数版本：仍为 `v1.9.4`（本轮不重新定义玩法）  
Schema：4（不变）  
工作区：`/Users/fan/Desktop/脑机/eeg-focus`  
真实数据目录：`/Users/fan/Documents/专注小蛙`

## 1. 范围

本轮只处理两类视觉问题：

1. 用随任务提供的纯头像九宫格替换旧的自绘档案头像；
2. 将全站动态池塘/天空背景与 UI 信息层分离，修复白天、黎明、傍晚、黑夜可读性。

未修改脑电特征、去噪、校准协议、游戏计分、10% 初始蓄力、归零休息、商城价格、Schema 4 或档案业务。游戏内标准小蛙模型与商城装扮权益不变。

## 2. 九宫格头像

### 2.1 素材与裁切

- 源图：1254×1254 RGB，3×3 排列的纯头像贴纸。
- 裁切方式：按每个格子内**非白内容边界**确定 bbox（阈值：RGB 最小通道 < 238），再以 bbox 中心扩展为正方形；边界外留 3px 透明，缩放为 512×512 PNG，透明角保持透明。
- 不截断角色与装饰：皇冠、草帽、耳机、围巾、巫师帽、潜水镜、花朵均完整保留；不在裁切过程中重新绘制头像。
- 统一尺寸 512×512、RGBA、圆角由容器统一裁切；主体透明 bbox 中心与画布中心误差 ≤2px。

实际内容边界（源图像素，左/上/右/下）：

| 文件 | 源 bbox |
|---|---|
| avatar_01.png | 12, 7, 413, 400 |
| avatar_02.png | 426, 7, 828, 402 |
| avatar_03.png | 844, 7, 1245, 401 |
| avatar_04.png | 11, 425, 412, 818 |
| avatar_05.png | 426, 424, 832, 820 |
| avatar_06.png | 843, 426, 1246, 820 |
| avatar_07.png | 12, 842, 411, 1239 |
| avatar_08.png | 426, 842, 828, 1238 |
| avatar_09.png | 844, 842, 1245, 1238 |

### 2.2 文件与 ID

素材目录：`web/assets/avatars/`

| 文件 | 新 ID | 展示名 |
|---|---|---|
| avatar_01.png | `avatar_01` | 小蛙 |
| avatar_02.png | `avatar_02` | 草帽蛙 |
| avatar_03.png | `avatar_03` | 探险蛙 |
| avatar_04.png | `avatar_04` | 音乐蛙 |
| avatar_05.png | `avatar_05` | 围巾蛙 |
| avatar_06.png | `avatar_06` | 皇冠蛙 |
| avatar_07.png | `avatar_07` | 魔法蛙 |
| avatar_08.png | `avatar_08` | 潜水蛙 |
| avatar_09.png | `avatar_09` | 花花蛙 |

旧 ID 继续被后端接受并做显示映射，不删除、不批量重写数据库：

| 旧 ID | 显示素材 |
|---|---|
| `frog` | `avatar_01` |
| `tadpole` | `avatar_01` |
| `lotus` | `avatar_09` |
| `fish` | `avatar_08` |
| `dragonfly` | `avatar_03` |
| `snail` | `avatar_02` |

`web/assets/avatars.js` 是唯一前端映射来源；`app/storage.py` 的 `AVATARS` 同时包含旧 ID 与 9 个新 ID，`AVATAR_LABELS` 补齐中文标签。未添加数据库迁移，Schema 仍为 4。

### 2.3 显示位置

- 新建/编辑档案弹窗：9 张图片选择器，选中态沿用高对比描边。
- 档案列表：76px（小窗口 68px/62px）圆角头像，图片 `object-fit: contain`，视觉中心由透明 bbox 保证。
- 首页当前档案入口：新增 22px 头像；没有活动档案时回退用户图标。
- 旧档案：从 `data-avatar-raw` 读取原始 ID，只映射显示；只改昵称时仍保存原 ID，不因打开编辑而静默改写档案关系。
- 头像独立于商城装扮，不进入 `DressUp` 权益或游戏内模型。

## 3. 全站背景可读性

### 3.1 分层

新增 `web/assets/readability-v195.css`，在所有页面 `<head>` 末尾加载：

- 背景：`.bubbles`、`.sky-veil` 固定在场景层 `z-index: 0`，天空/池塘/动态光照继续运行。
- 信息：`.wrap`、`.growth-page`、`.game-main` 等位于信息层 `z-index: 1`。
- `body` 使用 `isolation: isolate`，避免页面内伪元素与动态场景互相穿透。

### 3.2 统一变量

```css
--ui-text
--ui-text-soft
--ui-surface
--ui-surface-quiet
--ui-surface-solid
--ui-border
--ui-border-strong
--ui-ring
--ui-warning
--ui-danger
--ui-scene-z
--ui-content-z
```

白天/黎明使用深色文字与 96% 左右浅色表面；傍晚/黑夜使用浅色文字与 94% 左右深色表面。关键弹窗使用完全不透明表面；游戏 HUD 保持自有固定深底，不受画布子弹时间渐暗影响。

### 3.3 重点修复

- 首页标题渐变在暗色主题改为浅薄荷/浅蓝；主按钮、步骤序号、签到/成就/商城徽章、顶部入口提高对比。
- 档案卡、编辑弹窗、设置统计块在暗色模式下改为深底浅字；首页当前档案增加头像。
- 校准页标题、提示、教学卡、信号源表单在四套主题下使用稳定承载层。
- 游戏 HUD、蓄力计、教学卡：教学卡保留不透明浅底深字；子弹时间只压暗画布，HUD 和操作提示不在压暗层内。
- 成长日记/家长中心继续使用 v1.9.4 的浅色纸张卡面（夜间仍是高不透明度浅色卡），将辅助文字统一加深，避免浅底浅字；页脚单独加不透明承载卡。
- 开发者工作台、监测面板、图表坐标轴辅助文字提亮；成长/家长图表 canvas 的标签色加深。
- 统一 `:focus-visible` 轮廓；禁用按钮改为中性高不透明表面，不再用 50% 透明度把文字一起淡化。
- 保留 v1.9.3 的边框、留白、图标与角色统一结果；没有取消背景动画。

### 3.4 对比度验收方法

脚本对每个页面/主题执行：

1. 固定当前 `data-sky`，停止动画与过渡；
2. 收集可见文本节点的计算字号、字重、颜色和矩形；
3. 临时把文字设为透明并截图，保留真实背景、图片、渐变和弹窗；
4. 在文字区域内取多个背景采样点，按 WCAG 相对亮度计算最差对比度；
5. 普通文字要求 ≥4.5:1，大号文字/必要图标要求 ≥3:1。

结果：

- 页面/主题自动采样 **2,658** 个可见文本节点，**0** 项低于阈值；
- 游戏 HUD/教学自动采样 **501** 个文本节点，**0** 项低于阈值；
- 开发者滑杆/复合开关文字与图标为组合控件，另做人工截图核验；
- 白天普通文字最低约 4.53:1（设置页顶部开发者入口），夜间辅助文字最低约 5.0:1，具体逐项记录见 `outputs/v1.9.5/evidence/result.json`。

## 4. 验收

### 4.1 自动化

| 测试 | 结果 |
|---|---|
| `tests/selfcheck_v195.py` | 28 passed |
| `tests/browser_ui_v195.py`（隔离 8020 + Edge CDP） | 74 passed |
| `tests/selfcheck_v194.py` | 35 passed |
| `tests/selfcheck_v194_charge.js` | 11 passed |
| `tests/browser_ui_v194.py` | 53 passed |
| `tests/browser_ui_v194_rest.py` | 8 passed |
| v1.8.1 / v1.8.2 / v1.8.3 / v1.8.4 | 33 / 36 / 52 / 53 passed |
| v1.9.0 / v1.9.1 | 29 / 12 passed |
| v1.8.3 单轮 / v1.8.4 单轮 / v1.8.4 UI | 8 / 14 / 17 passed |
| v1.9.2 UI 静态 / v1.9.3 视觉静态 / 基础 UI 静态 | 10 / 11 / 15 passed |
| 单轮逻辑 / 去噪 / 计分映射 | 36 / 全部 / 全部通过 |
| `selfcheck_monitor.py` | 8 项通过；EDF replay 1 项因当前工作区无 EDF 样本阻塞 |

### 4.2 浏览器覆盖

- 尺寸：1920×1080、1440×900、1280×800、1024×768、800×600；档案头像另测 600×700。
- 页面：首页、档案、校准、游戏、成长、家长、开发者、设置、历史、报告。
- 主题：白天、黎明、傍晚、黑夜（“跟随时间”由 `sky.js` 解析到这四个实际状态）。
- 头像：9 张图片全部加载，档案列表尺寸/中心/圆角一致，选择器选中 1 张，首页头像可见，旧 ID 映射正确。
- 弹窗：档案编辑弹窗白天/黑夜完全不透明，小窗口不溢出。
- 游戏：HUD 固定深底，教学卡不透明浅底，800px 无横向滚动；v1.9.4 子弹时间验收继续通过。

### 4.3 证据

- 9 张独立头像：`outputs/v1.9.5/avatars/avatar_01.png` … `avatar_09.png`
- 实际选择器：`outputs/v1.9.5/profiles-avatar-picker-day-1440.png`、`profiles-avatar-picker-night-1440.png`、`avatar-picker-day-600.png`
- 首页头像：`outputs/v1.9.5/home-avatar-night-1440.png`
- 三套主题页面联系表：`outputs/v1.9.5/backgrounds/day-key-pages.png`、`dusk-key-pages.png`、`night-key-pages.png`
- 游戏：`outputs/v1.9.5/evidence/game-day-tutorial-1440.png`、`game-night-tutorial-1440.png`
- 完整逐页截图与 JSON：`outputs/v1.9.5/evidence/`
- 回归截图：`outputs/v1.9.5/regression-v194/`、`outputs/v1.9.5/regression-rest/`

## 5. 数据库与服务

- 测试全程使用 `.deepworks/testdata` 或 8020 隔离服务；未向真实库创建用户、Session 或校准。
- 真实库逻辑计数验收：2 个档案、7 个 Session、0 条校准、Schema 4，`PRAGMA integrity_check=ok`。
- SQLite 在服务启动/连接时会更新 WAL 文件头，数据库文件 SHA-256 不能作为“逻辑数据未变”的唯一证据；以计数、大小和完整性检查为准。
- 8000：发布后重启到 **1.9.5**，使用真实数据目录；8010 保持旧 v1.9.3 服务，未误杀。
- 8020：隔离测试服务，仅用于 v195/v194 浏览器验收。

## 6. Git 发布

- 作者：`mujiu07 <mujiu07@users.noreply.github.com>`
- 远程：`https://github.com/mujiu07/eeg-focus.git`
- 基线：`02aee04`
- 本轮创建并推送 `v1.9.5` 标签；**不移动 `v1.9.4` 或其他已发布标签**，不强制推送 `main`。
- 具体提交哈希与标签目标以发布后的 `git log -1` / `git ls-remote` 为准。

## 7. 限制

- 无 Xmuse 真机与 EDF 回放样本；对比度验收是浏览器合成背景下的静态/动态场景截图，不替代真实设备上的环境光与显示器校准。
- 夜间成长/家长页保留 v1.9.4 的浅色纸张卡面，这是刻意的可读性选择；不是全站纯暗色主题。
- 头像源图是任务提供的位图，已按视觉边界裁切；不包含可编辑矢量源。
- 未推进 v1.9.6、桌面封装或任何后续功能。
