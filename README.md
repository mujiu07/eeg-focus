# 专注小蛙 (Brain-Focusing Game MVP)

> 看得见的专注力，玩出来的好状态

一款面向 ADHD 儿童的脑波专注训练小游戏 MVP。核心机制：**脑电信号 → 专注指数 → 个人基线 → "蓄力→跳出"**——只有保持专注才能推动游戏角色前进，把"专注"变成完成游戏动作的必要条件。

基于 PRD-brain-focusing-game-MVP.md 再造，专注引擎由 PhysioNet EEGMAT 数据集（心算专注 vs 背景放松，36 名被试真实脑电）训练而来。

## 快速启动

```bash
# 1. 克隆并安装依赖（Python 3.9+）
git clone https://github.com/mujiu07/eeg-focus.git
cd eeg-focus
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. 获取 EEGMAT 数据集（一次性；含 EDF 脑电样本，约 183MB）
.venv/bin/bash scripts/download_data.sh

# 3. 启动服务
.venv/bin/python -m uvicorn app.server:app --host 127.0.0.1 --port 8000
```

浏览器打开 <http://127.0.0.1:8000>

> **无需数据集也能体验**：不执行第 2 步时，游戏仍可运行（`manual` 手动源）；执行 `scripts/preprocess.py` + `scripts/train.py` 可重建模型。

## 完整用户旅程（演示）

1. **首页** → 点击"进入脑电校准"（或直接"开始游戏"首次会引导先校准）
2. **校准页**：选择演示信号源（默认：真实脑电数据回放·放松段），点击"开始校准"，跟着呼吸球放松 20 秒
   - 服务端实时计算专注指数（模型预测的专注概率，EMA 平滑）
   - 结束后生成**个人专注基线**（校准期间专注指数中位数）
3. **游戏页**：同一被试的**专注段**脑电数据驱动（或手动模式拖动滑块）
   - 专注指数 ≥ 基线 → 蓄力条上升 → 蓄满 → 青蛙跳向下一片荷叶（+1 分）
   - 专注指数 < 基线 → 蓄力条回落，青蛙"跳不动"
4. **报告页**：得分、专注时长占比、专注指数曲线 vs 基线
5. **开发者页**：模型评估报告、信号源切换（72 个 EDF 文件 / 手动 / 硬件占位）、实时监视

## 三种信号源（信号源抽象层）

| 模式 | 说明 | 用途 |
|---|---|---|
| `replay` | EDF 真实数据回放（默认） | 演示"真实脑电驱动"：放松段低专注、心算段高专注，端到端闭环可复现 |
| `manual` | 滑块直接控制专注度 | 无数据环境/机制演示：把滑块拉到右侧青蛙一直跳，拉到左侧就跳不动 |
| `hardware` | 真实脑电头环 | MVP 预留接口（未实现） |

## 专注引擎

- 特征：2s 窗口 × 21 通道 × 11 特征（5 频段绝对/相对功率 + θ/β 比）
- 模型：LogisticRegression（`scripts/train.py`，LOSO 交叉验证）
  - 准确率 0.729 / 平衡准确率 0.640 / AUC 0.731
- 验证示例：放松段专注指数均值 ≈ 0.01，心算专注段 ≈ 0.57 → 区分度明显

## 隐私声明

- **所有数据处理均在本地**：前端零外部资源、后端零外网调用、接口仅监听 `127.0.0.1`
- 脑电数据**不上传任何云端**，可完全断网运行
- 会话记录仅落盘本机 `outputs/sessions/`（不进入本仓库）
- 详见 `docs/usage-and-privacy.md`（含数据清单与清理方法）

## 项目结构

```
eeg-focus/
├── scripts/          # 数据流水线（download/preprocess/train）
├── data/eegmat/      # EEGMAT 数据集（72 个 EDF + 元数据）
├── data/processed/   # features.npz（预处理产物）
├── outputs/          # 模型 joblib、训练报告、会话报告
├── app/              # 后端：FastAPI（专注引擎/信号源/会话流/校准/报告）
└── web/              # 前端：5 个页面 + 原生 JS/Canvas（无构建工具）
```

## 关键技术决策

- **数据本地**：脑电数据仅存本地，无账号体系（符合 PRD：MVP 不上传、儿童敏感数据）
- **零构建前端**：原生 HTML/CSS/JS + Canvas，免费部署、任意静态托管均可
- **SSE 推流**：服务端按 0.5s 步长推专注指数，前端 rAF 游戏循环消费
- **校准即基线**：校准期专注指数中位数作为个人基线阈值（P0 需求）

## 文档

| 文档 | 说明 |
|---|---|
| `docs/usage-and-privacy.md` | 使用说明 + 隐私保障（数据本地处理） |
| `docs/tech-stack.md` | 技术栈（前端/后端/算法/硬件接入） |
| `docs/xmuse-hardware-integration.md` | Xmuse 脑电波仪硬件接入方案（筹备中） |
| `docs/ARCHITECTURE.md` | 架构设计 |
| `docs/PRD-brain-focusing-game-MVP.md` | 产品需求文档 |

## 路线图（对应 PRD）

- [x] P0 脑电校准/基线建立
- [x] P0 专注映射游戏操作（蓄力→跳出）
- [x] 结果报告页、开发者页、设置页（入口）
- [ ] 多孩子账号（可选）
- [ ] 真实脑电头环接入（hardware 源）
- [ ] 家长进度趋势报告（多局汇总）
