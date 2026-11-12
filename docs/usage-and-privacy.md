# 梦境池塘 · 使用与说明文档

> 项目：`eeg-focus/`（脑波专注游戏 MVP）
> 版本：MVP 0.3（EDF 回放 + 手动 + Xmuse 真机 OSC/UDP）
> 日期：2026-11-12
> 隐私承诺：**脑电数据全部在本地处理，不上传任何脑电数据**——本承诺基于代码实现，详见第 5 节。

---

## 1. 这是什么

"梦境池塘"是一款儿童友好的脑波专注游戏桌面应用（纯本地 Web）：

- 戴上脑电设备（或使用 EDF 数据回放 / 手动模拟），系统实时计算"专注度"
- 游戏画面随专注度变化（高专注 → 池塘呈现梦幻效果）
- 附带：专注校准、报告页、开发联调页（dev）、天空主题与可选背景音乐

三种信号源（`app/sources.py`）：

| 信号源 | 说明 | 用途 |
|---|---|---|
| `replay` | 回放内置 EDF 脑电数据 | 默认演示、无设备体验 |
| `manual` | 滑块手动调整专注度 | 演示/测试 |
| `hardware` | Xmuse 脑电波仪（OSC/UDP 真机接入） | 真实脑电驱动 |

---

## 2. 安装与启动

### 2.1 环境要求

- Windows / macOS / Linux，Python 3.10+
- 浏览器（Chrome / Edge / Safari 均可，无需任何插件）
- 使用真机时另需：Xmuse 设备 + Xmuse Direct（或 Xmuse Lab）软件

### 2.2 首次安装

```bash
cd eeg-focus
python3 -m venv .venv                  # 创建虚拟环境
.venv/bin/pip install -r requirements.txt   # 安装依赖（算法+服务+OSC，见技术栈文档）
```

Windows 可执行 `.\start.ps1` 自动完成环境创建、依赖安装与启动。

### 2.3 启动

```bash
.venv/bin/uvicorn app.server:app --host 127.0.0.1 --port 8000
```

浏览器打开 **http://127.0.0.1:8000** 即可进入首页。

> 启动后终端会持续打印运行日志（uvicorn 默认输出到终端）。

---

## 3. 使用流程

### 3.1 首页（index.html）
- **天空模式**：右上角可切换黎明 / 白天 / 傍晚 / 黑夜 / 跟随系统时间；选择会保存在本机浏览器并对全站生效
- 首页展示动态池塘（青蛙跳跃、鱼群、莲花）与三步玩法说明
- 点击"进入脑电校准"建立基线；点击"开始游戏"选择本局时长
- **游戏时长**：1 / 3 / 5 / 10 分钟，或自定义 1–60 分钟（默认 3 分钟）
- "最近训练"展示最近几局的校准基线
- 左下角黑胶唱片机可播放/暂停背景音乐（见 3.6）

### 3.2 校准（calibrate.html）
- 收集当前状态下"专注/放松"基线，用于调整后续专注度显示
- 可选信号源：EDF 回放 / 手动 / Xmuse 脑电波仪；选 Xmuse 时填写 OSC 端口（默认 8000）
- 基线保存在浏览器本地（localStorage），**1 小时内有效**：期间刷新、关闭标签页或浏览器都无需重新校准
- 超过 1 小时后基线自动失效，进入游戏会引导回到校准页重新校准
- 基线仅存本机浏览器，不上传服务端

### 3.3 游戏（game.html）
- 开始后每 0.5 秒收到一帧专注度（`focus` 0–1）
- 画面随专注度变化（梦幻池塘效果），顶部显示剩余时间、得分与专注状态灯
- 专注度高于基线 → 蓄力上升 → 青蛙跳向下一片荷叶；低于基线 → 蓄力回落
- 超过 3 秒无有效数据 → 自动暂停蓄力，避免旧分数继续驱动游戏
- 结束可查看报告

### 3.4 报告（report.html）
- 展示本次会话的专注度趋势、最高分、高于基线占比、有效数据占比
- 顶部庆祝卡片（撒花与鼓励语）
- **给家长的话**：根据本局数据自动生成表现概述、训练建议与免责声明；无基线或有效数据不足时会明确提示
- 数据来自本地落盘的会话 JSON（见 5.2）

### 3.5 联调页（dev.html）
- 面向开发者：创建会话、查看实时 SSE 帧、监视原始值
- 支持切换信号源（EDF 文件 / 手动 / Xmuse OSC）；Xmuse 默认同时监听 UDP 7000/8000，自定义端口请在校准页填写或设置 `XMUSE_OSC_PORTS`
- 普通用户无需使用

### 3.6 背景音乐（可选）
- 全站左下角黑胶唱片机：唱臂落下 = 播放，抬起 = 暂停并保留进度，左右箭头切歌
- 播放曲目与进度跨页面保留
- 服务端代理网易云公开歌单：`GET /api/music/playlist`、`GET /api/music/url/{track_id}`
- 未登录只能获取歌单前 10 首；登录后可取全量（`NCM_COOKIE` 环境变量或 `data/music_cookie.txt`）
- 不使用音乐时不会产生任何联网请求，也不影响游戏

---

## 4. 接口一览（开发者）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` 等 | 静态页面（index/calibrate/game/report/dev） |
| GET | `/api/health` | 健康检查（含模型信息） |
| GET | `/api/dev/info` | 引擎信息、训练报告、EDF 列表、会话 |
| GET | `/api/dev/current` | 当前信号源配置与最近会话 |
| POST | `/api/dev/source` | 切换全局默认信号源（含 OSC 参数） |
| POST | `/api/session` | 创建会话（可带基线、OSC 参数） |
| GET | `/api/session/{id}/stream` | **SSE 实时流**（首帧 `hello`，之后每 0.5s `frame`） |
| POST | `/api/session/{id}/manual` | 手动模式设置专注度 |
| POST | `/api/session/{id}/calibrate` | 校准采样并建立基线 |
| POST | `/api/session/{id}/finish` | 结束会话并落盘报告 |
| GET | `/api/report/{id}` | 会话报告（内存/本地 JSON） |
| GET | `/api/music/playlist` | 背景音乐歌单（网易云代理） |
| GET | `/api/music/url/{track_id}` | 单曲播放直链（服务端缓存） |

前端封装统一在 `web/assets/api.js`（REST + SSE，含自愈重连）。

---

## 5. 数据与隐私保障（重要）

### 5.1 隐私承诺（有代码依据）

1. **前端零外部静态资源**：所有页面无 CDN、无字体服务、无统计脚本
2. **脑电数据处理链路零外网**：`sources.py` / `features.py` / `focus_engine.py` 不含任何出站调用；服务只监听 `127.0.0.1`
3. **接口全相对路径**：`api.js` 用 `/api/...` 相对地址，只会连到本地 `127.0.0.1:8000`
4. **唯一例外是可选背景音乐**：`app/music.py` 会访问 `music.163.com` 获取公开歌单与直链；只发送曲目/歌单 ID，**不发送任何脑电、会话或个人信息**。不播放音乐时不触发该请求

→ **不使用背景音乐时，应用可以完全断网运行**，脑电数据没有任何离开本机的通道。

### 5.2 数据都存哪（全部在本机）

| 数据 | 位置 | 说明 |
|---|---|---|
| EDF 脑电样本 | `data/eegmat/*.edf` | PhysioNet 公开数据集本地副本（回放源） |
| 预处理中间数据 | `data/processed/` | 训练用 |
| 模型文件 | `outputs/models/LogisticRegression.joblib` | 本地训练产物 |
| 会话记录 | `outputs/sessions/{会话id}.json` | 每次会话结束后落盘（专注度时序等） |
| 训练报告 | `outputs/train_report.md` | 模型指标 |
| 音乐登录凭据（可选） | `data/music_cookie.txt` | 网易云 cookie，已在 `.gitignore` 中忽略 |
| 运行日志 | 终端 / `.deepworks/tmp/server.log`（开发期） | 无脑电原始数据 |

### 5.3 本地处理链路

```
[EDF 本地文件 / 滑块 / Xmuse蓝牙→Direct→OSC/UDP]
        ↓（全部在本机回环）
features 滤波 + Welch 功率谱 → 模型推理 / 频段指标
        ↓
SSE 推送（127.0.0.1 回环）→ 浏览器渲染
        ↓
会话报告写入 outputs/sessions/*.json（本地）
```

**脑电数据处理没有任何一环经过公网。**

### 5.4 Xmuse 硬件模式的隐私说明

- Xmuse 设备 → 蓝牙 → 本机 Xmuse Direct/Lab 软件 → **OSC/UDP 均在本机回环（127.0.0.1）**
- 原始脑电仅在内存中参与特征计算，报告只存聚合后的专注度时序（`outputs/sessions/*.json`）
- 不会、也不需要把数据发往设备厂商云端

### 5.5 隐私最佳实践

- **断网运行**：不播放背景音乐时无需联网即可完整体验（唯一例外：首次下载 EDF 数据集需联网，一次性）
- **清理数据**：删除 `outputs/sessions/` 即可清空所有会话记录；删除 `data/eegmat/` 可移除数据集副本
- **清理音乐凭据**：删除 `data/music_cookie.txt` 或注销 `NCM_COOKIE` 环境变量
- **监听范围**：服务只监听 `127.0.0.1`（本机回环），局域网内其他设备无法访问
- **浏览器**：localStorage 仅保存视觉偏好与校准基线（1 小时有效），不上传服务端

---

## 6. 常见问题（FAQ）

**Q：为什么需要 EDF 数据？没有设备能玩吗？**
能。默认 `replay` 源直接回放内置 EDF 样本，无需任何硬件。

**Q：我的脑电数据会传到云端/厂商吗？**
不会。第 5 节已给出代码级证据：脑电链路无外网调用、无外链。Xmuse 通过本机 OSC/UDP 回环传输。仅可选背景音乐会访问网易云，且不携带脑电数据。

**Q：Xmuse 连上了但游戏一直提示未收到数据？**
1) 确认 Xmuse Direct/Lab 已连接设备；2) OSC 输出目标填 `127.0.0.1`，端口与页面一致（默认 7000/8000）；3) 前缀留空或填端口号（地址变为 `/eeg` 或 `/8000/eeg`）；4) 用 `python scripts/xmuse_osc_probe.py` 抓包确认地址。

**Q：UDP 7000/8000 被占用怎么办？**
关闭占用端口的程序，或在页面/环境变量 `XMUSE_OSC_PORTS` 中改用其它端口（如 `7100`）。

**Q：会话记录存在哪、怎么删？**
`outputs/sessions/*.json`。删除该目录即全部清除。

**Q：服务端口被占用怎么办？**
换端口：`uvicorn app.server:app --host 127.0.0.1 --port 9000`，浏览器访问 `http://127.0.0.1:9000`。

**Q：接入 Xmuse 后，是否需要联网？**
不需要。蓝牙 + OSC/UDP 均为本机连接。

---

## 7. 相关文档

- 更新日志：`CHANGELOG.md`
- 技术栈：`docs/tech-stack.md`
- Xmuse 硬件接入方案与实现：`docs/xmuse-hardware-integration.md`
- 架构：`docs/ARCHITECTURE.md`
- 服务日志（开发期）：`.deepworks/tmp/server.log`（相对项目根目录）
