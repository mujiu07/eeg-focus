# AGENTS — 专注小蛙 · 梦境池塘 项目指令

> 适用仓库：`mujiu07/eeg-focus`
> 适用版本：`main` @ `v1.4.16`（2026-11-19）
> 文件位置：`docs/AGENTS-dream-pond-focus-frog.md`
> 使用方式：AI 编码助手在本仓库工作前先读本文件；如工具只识别根目录 `AGENTS.md`，可将其内容复制为根 `AGENTS.md`（保持本文件为唯一事实源，改一处同步另一处）。

---

## 0. 一分钟事实

| 项 | 值 |
|---|---|
| 产品 | 本地脑波专注游戏（儿童向）；专注→蓄力→起跳→报告 |
| 技术 | FastAPI + 原生 HTML/CSS/JS（零构建）+ SSE |
| 运行 | `uvicorn app.server:app --host 127.0.0.1 --port 8000` |
| 页面 | `index` / `calibrate` / `game` / `report` / `dev` |
| 信号源 | `replay`（EDF）/ `manual` / `hardware`（Xmuse OSC）/ `heart`（仅 macOS） |
| 数据 | 脑电与会话仅本机；成长数据仅 `localStorage`；唯一公网是可选的网易云音乐 |
| 已知 | `outputs/sessions/` 不入库；FastAPI `version` 已于 v1.4.16 同步为 `1.4.16` |

## 1. 必读顺序

1. `README.md`（能力、启动、隐私边界）
2. `CHANGELOG.md` 顶部（当前版本与最近变化）
3. `docs/BRIEF-TECH-DESIGN-dream-pond-focus-frog.md`（最短技术全貌）
4. 你要改的模块 + 相邻模块（不要整库通读）
5. 相关文档：`ARCHITECTURE.md`、`tech-stack.md`、`usage-and-privacy.md`、`xmuse-hardware-integration.md`

## 2. 环境与常用命令

```bash
# 首次（Windows 用 start.ps1 / start.bat；macOS 用 start.command 亦可）
python -m venv .venv
.venv/bin/pip install -r requirements.txt

# 启动（开发）
.venv/bin/python -m uvicorn app.server:app --host 127.0.0.1 --port 8000

# 硬件探针（改端口/地址前必跑）
.venv/bin/python scripts/xmuse_osc_probe.py

# 训练与评估（改算法时）
.venv/bin/python scripts/train.py
# 结果写入 outputs/train_report.md
```

- 禁止用 `0.0.0.0` 监听；服务必须只绑 `127.0.0.1`
- 端口冲突时换端口启动，不要杀未知进程
- 无设备验证：首页输入 `↑ ↑ ↓ ↓ ← → ← → B A B A` → 开发者模式 →「无设备试玩 · 1 分钟」

## 3. 代码地图

```
app/      server.py（会话/API/静态）  sources.py（四信号源）  xmuse_osc.py（OSC）
          focus_engine.py（模型+回退+EMA）  features.py（滤波/PSD/特征）
          denoise.py（去趋势/陷波/眨眼修复/坏道掩码/质量评分，仅 hardware）
          heart.py（心率/融合）  export.py（五种导出）  music.py（网易云代理）
web/      index/calibrate/game/report/dev.html + assets/*
scripts/  preprocess.py  train.py  xmuse_osc_probe.py  ncm_login.py  download_data.sh
docs/     产品/架构/技术栈/隐私/硬件/证据/反思/决策
outputs/  models/（入库）  sessions/（不入库，隐私）  train_report.md
```

## 4. 硬性规则（违反即拒绝合并）

1. **隐私红线**：不得新增把脑电、报告、成长数据发往外部的代码；唯一允许的公网访问是 `app/music.py`
2. **零构建**：不引入 npm、打包器、前端框架、CDN 字体/脚本；新前端能力放 `web/assets/`
3. **文案红线**：不写“诊断/治疗/改善注意力/提升智商”；统一“脑波分数（教学映射）”“不构成医疗建议”
4. **接口稳定**：SSE 帧字段只增不改；分隔符兼容 `\r?\n\r?\n`；报告字段保持向后兼容（旧报告无 `score` 时回退 `focus_fused`）
5. **默认值慎重**：OSC 端口默认 `7000,8000`；改默认必须先有探针日志
6. **数据位置**：新增持久化状态优先 `localStorage`，并在 `usage-and-privacy.md` §6 登记键名
7. **不伪造证据**：不编造指标、用户量、测试结果、来源；无法验证就写“未验证”
8. **不动用户数据**：不删除 `outputs/sessions/`、`data/`、`data/music_cookie.txt`；需要清理时先说明并征得同意
9. **特征口径**：去噪只能加在 `prepare_signal` 之前，不得替代或改变 0.5–45 Hz 带通与 11 特征定义；改去噪常数须同步 `denoise-artifacts.md` §5 与 `BRIEF` §6

## 5. 修改流程

```
读文档与代码 → 写清假设与影响面 → 最小改动 → 本地运行验证
  → 更新 CHANGELOG（如行为变化）+ 受影响文档 → 提交（说明版本与范围）
```

- 一次提交只做一件事；提交信息用 `feat:` / `fix:` / `docs:` / `refactor:` / `chore:`
- 不 force push；不 rebase 他人已推送的提交
- 发布版本：`Release vX.Y.Z` 提交 + Git tag，并同步 `CHANGELOG`、`tech-stack` 版本行、`ARCHITECTURE` §10

## 6. 验证清单（按改动类型）

| 改动 | 必做验证 |
|---|---|
| 前端页面/样式 | 100%/125%/150% 缩放各看 30 s；切天空模式；Console 无报错 |
| SSE/会话 | 创建→校准→游戏→报告全链路；断流 10 s 观察自愈；检查 `outputs/sessions/*.json` 帧数与有效帧 |
| 算法/特征 | `scripts/train.py` 重跑，记录新 `train_report.md`；对比旧指标；说明是否改变分数口径 |
| 心率 | mock 链路 + `hrd`（macOS）+ 断流回退；确认 `focus_fused` 与纯 EEG 一致（关闭心率时） |
| 硬件 | 探针 → 校准 → 游戏 → 报告；4 通道合成报文；端口占用/释放 |
| 导出 | 五种格式逐一打开，检查中文、曲线、空数据提示 |
| 成长系统 | 结算只入账一次；刷新保留；成就只播一次；清缓存重置 |
| 文档 | 相对链接可解析；版本/接口/数据键与代码一致 |

## 7. 常见任务配方

**新增成就**
1. 在 `web/assets/achievements.js` 的对应分组加定义（id、条件、名称）
2. 在判定处调用 `record*`，确保只解锁一次并进入播报队列
3. 更新 `usage-and-privacy.md` §3.6 的数量与描述
4. 验证：达成→刷新→不重复播报

**新增装扮/商城物品**
1. `dressup.js` 加 `ITEMS`（类别、价格、图形、获取方式）
2. 成就专属必须 `shop` 不可购买
3. 验证：购买扣分、穿戴、刷新保留、图鉴显示获得时间
4. 若加动效，遵守 `ARCHITECTURE.md` §9（DPI、平滑时钟、亚像素吸附）

**调整计分/定价**
1. 先确认是否改变产品口径（得分=积分）
2. 改 `game.html`（+2/+1）或 `shop.js`（价格）
3. 更新 `CHANGELOG`、`usage-and-privacy.md` §3.6、`DECISIONS` 的对应决策
4. 验证：结算分=积分；余额与购买价一致

**新增 API**
1. `app/server.py` 加路由，错误用中文可读信息
2. 更新 `ARCHITECTURE.md` §5、`usage-and-privacy.md` §4
3. 验证：curl/浏览器直连；不破坏 SSE 契约；不新增外网依赖

## 8. localStorage 键登记

| 键 | 用途 |
|---|---|
| `bf-calib` | 校准基线（1 h） |
| `bf-wallet` | 积分/局数/累计/消费 |
| `bf-checkin` | 每日签到 |
| `bf-achievements` | 成就状态与进度 |
| `bf-owned` / `bf-owned-at` / `bf-outfit` | 已购、获得时间、穿戴 |
| `bf-sky-mode` | 天空模式 |
| `bf-music-*` / `bf-pond-audio` | 音乐与音量偏好 |
| `bf-heart*` | 心率开关、静息、权重 |

新增键必须同步 `usage-and-privacy.md` §6，并使用 `bf-` 前缀。

## 9. 文案规范

- 面向儿童：短句、具体动作、不吓唬（“小蛙在等你”而不是“失败”）
- 面向家长：描述现象与建议，不做因果断言（“本局高于基线的时段占 62%”，而不是“注意力提升了”）
- 面向评审：写清“已验证/未验证”，不把计划写成结果

## 10. 禁止事项

- 禁止把 `data/`、`outputs/sessions/`、cookie、`.env` 提交入库
- 禁止在文档或界面出现“临床有效”“治疗 ADHD”等表述
- 禁止为了通过测试而修改测试期望/伪造数据
- 禁止未经确认删除文件或目录
- 禁止把服务暴露到 `0.0.0.0` 或公网

## 11. 完成定义（DoD）

- [ ] 本地可运行，目标链路实测通过
- [ ] 无新增外网请求（音乐除外）
- [ ] 无新增 npm/构建依赖
- [ ] `CHANGELOG` 与相关文档已更新（行为变化时）
- [ ] 提交信息说明版本与影响面
- [ ] 未验证项已明确标注

## 12. 已知坑

| 坑 | 处理 |
|---|---|
| `scikit-learn` 次版本漂移导致模型加载/推理异常 | 按 `requirements.txt` 的 `<1.7` 约束建环境 |
| Python 3.13+ 无 pyedflib 轮子 | `sources.py` 自动回退 `edfio`，不要硬依赖 |
| SSE 分隔符是 CRLF | 测试脚本用 `\r?\n\r?\n` |
| OSC 报文不带采样率 | 默认 256 Hz，必要时 `XMUSE_OSC_FS` |
| 心率 `hrd` 静息时长时间无输出 | 进程存活时过期阈值放宽到 120 s，不要误判断流 |
| FastAPI 版本字符串落后 | 改版本时同时改 `app = FastAPI(version=...)` 与 tag |
| 画布逐帧抖动 | 按 `ARCHITECTURE.md` §9 的 DPI/时钟/吸附约定 |

## 13. 文档地图

- 快速技术全貌：`BRIEF-TECH-DESIGN-dream-pond-focus-frog.md`
- 决策与验证：`DECISIONS-AND-VERIFICATION-dream-pond-focus-frog.md`
- 测试证据：`EVIDENCE-dream-pond-focus-frog.md`
- 使用/隐私：`usage-and-privacy.md`
- 去噪与伪迹：`denoise-artifacts.md`
- 索引：`README-dream-pond-focus-frog.md`

---

*创建：2026-11-17*
*变更本文件时：同步更新第 0 节的版本与已知项，避免指令与代码脱节*
