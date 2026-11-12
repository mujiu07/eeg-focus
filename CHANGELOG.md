# 变更日志（CHANGELOG）

## 版本迭代约定

- **v1.0 起**：项目迭代由 **Cuprum0214** 账户提交并推送（SSH key：`id_ed25519_cuprum0214`）。
- 每完成一轮迭代（一批功能/修复），同步完成三件事：
  1. 提交代码（署名 Cuprum0214）；
  2. 打 Git tag（版本号递增，如 v1.0 → v1.1 → v1.2…；重大变更可跳 v2.0）；
  3. 在本文件新增一条版本记录，并推送提交与 tag 到远端。
- 版本号规则：`v<主>.<次>`，每轮迭代次版本 +1；破坏性/重大变更提升主版本。

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
