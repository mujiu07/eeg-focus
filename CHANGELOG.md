# 变更日志（CHANGELOG）

## 版本迭代约定

- **v1.0 起**：项目迭代由 **Cuprum0214** 账户提交并推送（SSH key：`id_ed25519_cuprum0214`）。
- 每完成一轮迭代（一批功能/修复），同步完成三件事：
  1. 提交代码（署名 Cuprum0214）；
  2. 打 Git tag（版本号递增，如 v1.0 → v1.1 → v1.2…；重大变更可跳 v2.0）；
  3. 在本文件新增一条版本记录，并推送提交与 tag 到远端。
- 版本号规则：`v<主>.<次>`，每轮迭代次版本 +1；破坏性/重大变更提升主版本。

---

## v1.3.1 — 首页移除荷花 · 游戏画面天空与环境同步（mujiu07）

### 变更

- **首页移除荷花**：删除 `index.html` 中的 `#hLotus` / `#hLotusBud` 图形与 `#heroLotus` 摆放组，并清理 `sky.css` 里对应的荷花摆动动画与明度滤镜，池塘只保留荷叶、小鱼、水花与青蛙。
- **天空色板统一来源**：`sky.js` 新增黎明 / 白天 / 傍晚 / 黑夜四套完整色板（天空、水面、远山、树丛、日月星、云雾、水面反光、荷叶与 HUD 配色），并导出 `window.SkyTheme`；首页 SVG 与游戏画布读取同一份数据，切换模式时一起变化。
- **游戏画面与初始界面同步**：`game.html` 画布改为按当前天空模式重绘天空渐变、太阳 / 黎明低日 / 傍晚落日 / 月亮与夜空星点、云、地平线薄雾、远山、树丛、水面渐变、晨昏水面反光、荷叶与青蛙明度，以及蓄力条与分数文字配色；移除 `sky.css` 中对 `#game-canvas` 的重复压暗滤镜，避免二次变暗。
- 游戏画布首帧底色改用 `--sky-*` 变量，与当前主题一致。

### 验证

- `node --check web/assets/sky.js` 通过；`index / calibrate / game / report / dev` 内联脚本经 `vm.Script` 解析通过。
- 首页 SVG 标签配平检查通过（33 组 `<g>`），页面内已无 `hLotus` / `heroLotus` / `pond-lotus` 残留引用。

---

## v1.3.0 — 全站体验升级：天空主题 / 背景音乐 / 家长报告（mujiu07）

> 说明：本轮提交与推送使用 mujiu07 账户（本机未配置 Cuprum0214 SSH key），版本记录与 tag 仍按上述约定执行。

### 新增

- **全站天空模式**：黎明 / 白天 / 傍晚 / 黑夜 / 跟随系统时间（按日出日落估算自动切换），选择跨页保存；新增 `web/assets/sky.js` + `sky.css`，五个页面统一接入。
- **动态梦境池塘首页**：重做首页场景，青蛙在三片荷叶间跳跃、荷叶弹簧回弹、水花、鱼群与莲花随天空时段变色（`web/assets/hero-pond.js`）。
- **黑胶唱片机背景音乐**：新增 `app/music.py` 代理网易云公开歌单与播放直链（8 分钟缓存、并发探测可播性），新增 `web/assets/music.js` + `vinyl.css`；落针播放/抬针暂停、左右切歌、跨页保留进度。
- **网易云登录（可选）**：新增 `scripts/ncm_login.py`，登录后可取完整歌单；凭据仅存 `data/music_cookie.txt` 或 `NCM_COOKIE` 环境变量。
- **游戏时长选择**：1 / 3 / 5 / 10 分钟或自定义 1–60 分钟（默认 3 分钟），首页弹窗选择后进入游戏。
- **首页“最近训练”**：展示最近几局的校准基线。
- **报告页庆祝卡片与“给家长的话”**：自动生成本局表现概述、训练建议与免责声明；无基线/有效数据不足时给出明确提示。
- **校准基线 1 小时有效**：刷新/关闭页面无需重新校准，首页显示剩余分钟数，过期引导重新校准。

### 变更

- `app/server.py`：新增 `/api/music/playlist`、`/api/music/url/{track_id}`；创建会话支持 `baseline` 参数，保证游戏会话与报告页拿到同一基线。
- 前端 `index / calibrate / game / report / dev` 统一视觉与导航；校准页与开发者页的 Xmuse 端口默认值统一为 `7000,8000`，提示改为 Xmuse Direct 默认口径。
- 开发者页补回 Xmuse OSC 端口输入，并显示引擎当前模式（模型 / 频段回退）与硬件报文、质量信息。
- `.gitignore` 增加 `music_cookie.txt`、`*.cookie`、`.env`、`._*`，防止凭据与 macOS 垃圾文件入库。

### 修复

- 报告页缺少基线时不再留白：隐藏“高于基线占比”并提示重新校准。
- 超过 3 秒无有效数据时暂停蓄力，避免旧分数继续驱动游戏。
- 校准页 default 端口与文档/启动脚本不一致（8000 → 7000,8000）。
- `/api/dev/current` 曾被静态文件挂载抢先匹配而返回 404；调整路由顺序，静态挂载固定在最后注册。

### 验证

- Python 模块编译通过（`app/server.py`、`sources.py`、`focus_engine.py`、`music.py`、`xmuse_osc.py`、`scripts/ncm_login.py`、`scripts/xmuse_osc_probe.py`）。
- 前端内联脚本通过 `node --check`；Xmuse OSC 端口输入、音乐播放器、天空主题资源均已接入五个页面。

---

## v1.2.1 — 端口决策说明补充（mujiu07）

- 在 `docs/xmuse-hardware-integration.md` 增加“端口选择决策记录（默认 7000/8000）”与“变更守则”，固化 AI-Xmuse ToolBox（7000 / 8001）、Xmuse-Coding（8000 / 8001 / 8002）与本机 Xmuse Direct 1.5.11（7000）的证据链。
- `README.md` 的 Xmuse 段落增加指向该节的提醒：修改默认端口必须附真机探针日志，不能只凭单个官方示例。
- 本次为文档补丁，不改运行时代码；默认端口仍为 `7000,8000`。

---

## v1.2 — Xmuse 脑电波仪 OSC/UDP 接入（mujiu07）

- 新增 `app/xmuse_osc.py`：多端口 OSC/UDP 接收（默认 `7000`、`8000`），2 s 窗 / 0.5 s 步长，自动识别 4/6 通道与 `/eeg` 地址后缀，解析 `/elements/is_good` 与 `/batt`。
- `HardwareSource` 从占位改为真实 Xmuse 源；`app/server.py` 放开 hardware 会话、新增 `osc_host/osc_ports/osc_fs/osc_channels`、阻塞接收放入线程池、会话结束释放 UDP 端口、同一时间只保留一个硬件会话。
- `app/focus_engine.py`：4/6 通道自动回退 `β/(θ+α)` 频段指标，21 通道 EDF 回放仍走原 231 维模型。
- 前端 `web/dev.html`、`web/calibrate.html`、`web/game.html` 增加 Xmuse 选项、OSC 端口输入与游戏局间端口交接。
- 新增 `scripts/xmuse_osc_probe.py` 端口探针；`requirements.txt` 增加 `python-osc`，固定 `scikit-learn<1.7` 以匹配模型。
- `start.ps1` 支持自动建 venv、默认 `XMUSE_OSC_HOST=127.0.0.1`、`XMUSE_OSC_PORTS=7000,8000`、`XMUSE_OSC_FS=256`。
- 文档更新：`README.md`、`docs/xmuse-hardware-integration.md`、`docs/tech-stack.md`、`docs/usage-and-privacy.md`。
- 验证：合成 OSC 666 报文窗口 `(4,512)`；频段回退 theta `0.148` / beta `0.98`；HTTP 端到端 `n_valid_frames=4`；连续两局重绑定同一 UDP 端口成功。
- 端口依据：Xmuse Direct 默认 `127.0.0.1:7000`；官方示例另用 `8000/8001/8002`；Xmuse Lab 的 `1234` 是授权桥接，不是脑电流。
- 本轮提交与推送使用 mujiu07 账户（本机未配置 Cuprum0214 SSH key）。

---

## v1.0 — 版本迭代管理启用（Cuprum0214）

- 建立 CHANGELOG 与 Git tag 版本迭代机制。
- 推送通道切换：HTTPS（mujiu07 钥匙串 token）→ SSH（Cuprum0214 专用 key，仓库级 remote 配置）。
- 提交署名切换为 Cuprum0214（仓库级）。
- 授予 Cuprum0214 对 mujiu07/eeg-focus 的 write 协作者权限（邀请已接受）。
- 以 v0.9.0（mujiu07 阶段收官提交 ed4eaae）作为历史基线。

---

## v1.1 — 并入 mujiu07 遗留提交（Cuprum0214）

- 收编远端 mujiu07 遗留提交 `55fdfb6`（2026-10-29 推送）：Windows 支持（`start.ps1`、requirements 更新）、青蛙不透明度修复、校准等待调整、`features.py`/`sources.py`/`preprocess.py` 优化、README 更新。
- 由 Cuprum0214 创建 merge commit `3b03d83` 完成 main 分支收编。

---

## v0.9.0 — 脑波专注游戏 MVP 收官（mujiu07 阶段）

历史基线：mujiu07 账户开发阶段的最终版本。关键变更：

- `955ddef` 数据有效性语义硬化：异常帧 `valid=false` 且 focus/raw 置 null；报告与校准统计只使用有效帧；断流/陈旧信号时前端蓄力暂停并显示“信号中断”横幅。
- `955ddef` 文案诚实化：HUD/首页/报告改为“脑波分数（教学映射）”，README 注明研究边界、LOSO 指标（准确率 0.729 / 平衡准确率 0.640 / AUC 0.731）与混合生理通道说明。
- `d077ee1` 修复青蛙落点几何（贴荷叶上表面）与校准基线算法（取时间后半段有效帧中位数，修复先排序再切段的 bug）。
- `b08a2ab` 青蛙节奏重构：从屏幕中心起跳、落向下一片荷叶、settle 阶段整排荷叶平滑归位。
- `7599bc4` 青蛙锚点对齐荷叶正中心（叶脉交点）。
- `03ff3db` 青蛙下移，底部落在三条叶脉交点。
- `2cf490d` 校准倒计时结束后增加加载进度条。
- `d06b6e5` 静态文件 no-cache，避免浏览器缓存旧页面。
- `ed4eaae` 校准加载文案“稍后”修正为“稍候”。

更早历史见 `git log 92c41e6..ed4eaae`。
