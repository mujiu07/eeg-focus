# 梦境池塘 · 使用与说明文档

> 项目：`eeg-focus/`（脑波专注游戏 MVP）
> 版本：MVP（EDF 回放 + 手动 + Xmuse 硬件接入筹备中）
> 日期：2026-10-20
> 隐私承诺：**所有数据在本地处理，不上传任何脑电数据**——本承诺基于代码实现，详见第 5 节。

---

## 1. 这是什么

"梦境池塘"是一款儿童友好的脑波专注游戏桌面应用（纯本地 Web）：

- 戴上脑电设备（或使用 EDF 数据回放 / 手动模拟），系统实时计算"专注度"
- 游戏画面随专注度变化（高专注 → 池塘呈现梦幻效果）
- 附带：专注校准、报告页、开发联调页（dev）

三种信号源（`app/sources.py`）：

| 信号源 | 说明 | 用途 |
|---|---|---|
| `replay` | 回放内置 EDF 脑电数据 | 默认演示、无设备体验 |
| `manual` | 滑块手动调整专注度 | 演示/测试 |
| `hardware` | Xmuse 真机（接入筹备中，见接入方案） | 真实脑电驱动 |

---

## 2. 安装与启动

### 2.1 环境要求

- macOS（当前开发机）或任意装有 Python 3.9+ 的系统
- 浏览器（Chrome / Edge / Safari 均可，无需任何插件）

### 2.2 首次安装

```bash
cd eeg-focus
python3 -m venv .venv                  # 创建虚拟环境
.venv/bin/pip install -r requirements.txt   # 安装依赖（算法+服务依赖，见技术栈文档）
```

### 2.3 启动

```bash
.venv/bin/uvicorn app.server:app --host 127.0.0.1 --port 8000
```

浏览器打开 **http://127.0.0.1:8000** 即可进入首页。

> 启动后终端会持续打印运行日志（uvicorn 默认输出到终端）。

---

## 3. 使用流程

### 3.1 首页（index.html）
- 选择信号源：**回放 EDF / 手动 / 硬件**
- 点击进入校准或游戏

### 3.2 校准（calibrate.html）
- 收集当前状态下"专注/放松"基线，用于调整后续专注度显示
- 校准数据仅在本次会话内存中生效

### 3.3 游戏（game.html）
- 开始后每 0.5 秒收到一帧专注度（`focus` 0–1）
- 画面随专注度变化（梦幻池塘效果）
- 结束可查看报告

### 3.4 报告（report.html）
- 展示本次会话的专注度趋势
- 数据来自本地落盘的会话 JSON（见 5.2）

### 3.5 联调页（dev.html）
- 面向开发者：创建会话、查看实时 SSE 帧、监视原始值
- 普通用户无需使用

---

## 4. 接口一览（开发者）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` 等 | 静态页面（index/calibrate/game/report/dev） |
| GET | `/api/health` | 健康检查（含模型信息） |
| GET | `/api/state` | 运行状态 |
| POST | `/api/session` | 创建会话（指定信号源） |
| POST | `/api/calibrate` | 校准接口 |
| GET | `/api/session/{id}/stream` | **SSE 实时流**（首帧 `hello`，之后每 0.5s `frame`） |
| GET | `/api/session/{id}/report` | 会话报告（本地 JSON） |
| GET | `/api/report/train` | 训练报告（静态 Markdown） |

前端封装统一在 `web/assets/api.js`（REST + SSE，含自愈重连）。

---

## 5. 数据与隐私保障（重要）

### 5.1 隐私承诺（有代码依据）

以下三点均已核实，**不是口头承诺**：

1. **前端零外部资源**：所有页面无任何 `http(s)://` 外链（无 CDN、无字体服务、无统计脚本）
2. **后端零外网调用**：服务代码无 `requests / urllib / httpx / socket` 出站调用
3. **接口全相对路径**：`api.js` 用 `/api/...` 相对地址，只会连到本地 `127.0.0.1:8000`

→ **应用可以完全断网运行**，脑电数据没有任何离开本机的通道。

### 5.2 数据都存哪（全部在本机）

| 数据 | 位置 | 说明 |
|---|---|---|
| EDF 脑电样本 | `data/eegmat/*.edf` | PhysioNet 公开数据集本地副本（回放源） |
| 预处理中间数据 | `data/processed/` | 训练用 |
| 模型文件 | `outputs/models/LogisticRegression.joblib` | 本地训练产物 |
| 会话记录 | `outputs/sessions/{会话id}.json` | 每次会话结束后落盘（专注度时序等） |
| 训练报告 | `outputs/train_report.md` | 模型指标 |
| 运行日志 | 终端 / `.deepworks/tmp/server.log`（开发期） | 无脑电原始数据 |

### 5.3 本地处理链路

```
[EDF 本地文件 / 滑块 / Xmuse蓝牙→Direct]
        ↓（全部在本机）
features 滤波 + Welch 功率谱 → 模型推理
        ↓
SSE 推送（127.0.0.1 回环）→ 浏览器渲染
        ↓
会话报告写入 outputs/sessions/*.json（本地）
```

**没有任何一环经过公网。**

### 5.4 Xmuse 硬件模式的隐私说明（接入后）

- Xmuse 设备 → 蓝牙 → 本机 Xmuse Direct 软件 → **LSL/OSC 均为本机回环协议**（127.0.0.1）
- 原始脑电仅在内存中参与特征计算，报告只存聚合后的专注度时序（`outputs/sessions/*.json`）
- 不会、也不需要把数据发往设备厂商云端

### 5.5 隐私最佳实践

- **断网运行**：无需联网即可完整体验（唯一例外：首次下载 EDF 数据集需联网，一次性的，之后完全离线）
- **清理数据**：删除 `outputs/sessions/` 即可清空所有会话记录；删除 `data/eegmat/` 可移除数据集副本
- **监听范围**：服务只监听 `127.0.0.1`（本机回环），局域网内其他设备无法访问
- **浏览器**：页面无 Cookie、无 localStorage 敏感数据（仅视觉偏好等）；建议使用无痕窗口可获得更强隔离

---

## 6. 常见问题（FAQ）

**Q：为什么需要 EDF 数据？没有设备能玩吗？**
能。默认 `replay` 源直接回放内置 EDF 样本，无需任何硬件。

**Q：我的脑电数据会传到云端/厂商吗？**
不会。第 5 节已给出代码级证据：无外网调用、无外链、断网可用。Xmuse 接入后同样只在本地处理。

**Q：会话记录存在哪、怎么删？**
`outputs/sessions/*.json`。删除该目录即全部清除。

**Q：端口被占用怎么办？**
换端口：`uvicorn app.server:app --host 127.0.0.1 --port 9000`，浏览器访问 `http://127.0.0.1:9000`。

**Q：接入 Xmuse 后，是否需要联网？**
不需要。蓝牙 + LSL/OSC 均为本机连接。

---

## 7. 相关文档

- 技术栈：`docs/tech-stack.md`
- Xmuse 硬件接入方案：`docs/xmuse-hardware-integration.md`
- 服务日志（开发期）：`/Users/fan/脑机/.deepworks/tmp/server.log`
