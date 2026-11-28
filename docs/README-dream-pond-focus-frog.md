# 专注小蛙 · 梦境池塘 — 文档索引

> 游戏名：**专注小蛙 · 梦境池塘**（Dream Pond Focus Frog）
> 代码基线：v1.9.3（2026-11-28；上一基线 v1.9.2/v1.9.1/v1.9.0/v1.8.4/v1.8.3/v1.8.2/v1.8.1/v1.7.0）
> 本目录：`docs/`
> 说明：本文件是 `docs/` 的入口。仓库根目录另有项目总 README。

## 1. 先看哪几篇

| 你是 | 建议顺序 |
|---|---|
| 第一次接触项目 | 根目录 `README.md` → 本文 → `PROJECT-DOC-dream-pond-focus-frog.md` |
| 想跑起来 / 给孩子用 | 根目录 `README.md` → `usage-and-privacy.md` |
| 评审代码与架构 | `BRIEF-TECH-DESIGN-dream-pond-focus-frog.md` → `ARCHITECTURE.md` → `tech-stack.md` |
| 评审课程交付物 | `PROJECT-DOC` → `EVIDENCE` → `AI-USAGE-LOG` → `DECISIONS-AND-VERIFICATION` → `REFLECTION` → `VIBE-CODING` |
| 让 AI 助手改代码 | `AGENTS-dream-pond-focus-frog.md` → 相关模块文档 |
| 接 Xmuse 硬件 | `xmuse-hardware-integration.md` → `tech-stack.md` §5 → `denoise-artifacts.md` |

## 2. 文档清单（按用途分组）

### 2.1 产品与设计

| 文件 | 内容 |
|---|---|
| `PRD-brain-focusing-game-MVP.md` | 原始产品需求（目标用户、问题、P0、范围边界）+「实现现状对照（v1.9.0）」 |
| `PROJECT-DOC-dream-pond-focus-frog.md` | **项目主文档**：提案 + MVP PRD 摘要 + 技术设计 + AI 协作约定（四合一） |
| `research-request-brain-focusing-game.md` | 研究请求（问题清单，非研究结论）+ 当前研究缺口 |

### 2.2 技术与实现

| 文件 | 内容 |
|---|---|
| `BRIEF-TECH-DESIGN-dream-pond-focus-frog.md` | **简要技术设计**：一页全貌、组件、流程、契约、失败模式、风险 |
| `ARCHITECTURE.md` | 架构总览、数据流、API、会话模型、本地状态、动效约定 |
| `tech-stack.md` | 技术栈、前端模块、后端模块、算法链路、硬件、导出、音乐代理 |
| `xmuse-hardware-integration.md` | Xmuse OSC/UDP 接入证据、端口约定、实测与后续 |
| `denoise-artifacts.md` | **去噪与去伪迹**：流程、阈值与依据、接入点、自检与端到端证据、已知局限 |
| `DEV-REPORT-v1.8.4.md` | 开发者工作台、双基线、瓶颈诊断、标准评估、导出与 Schema v4 |
| `DEV-REPORT-v1.9.0.md` | 成长日记、家长中心、评估分段、历史详情、四格式报告与验收 |
| `DEV-REPORT-v1.9.1.md` | 档案 500 根因、旧 Schema 恢复修复、真实库副本验证 |
| `DEV-REPORT-v1.9.2.md` | v1.9.2 全站 UI 修复、侧栏/音乐布局、首页合并、导航审计与浏览器验收 |
| `DEV-REPORT-v1.9.3.md` | v1.9.3 小蛙/图标/边框视觉统一、素材规范与真实浏览器验收 |
| `NAVIGATION-v1.9.2.md` | v1.9.2 页面导航关系图与退出矩阵 |
| `STABILITY-v1.8.4.md` | 30 分钟开发者模式稳定性、资源趋势与限制 |

### 2.3 使用与合规

| 文件 | 内容 |
|---|---|
| `usage-and-privacy.md` | 安装启动、完整使用流程、成长系统、FAQ、数据清单与隐私承诺 |
| `AGENTS-dream-pond-focus-frog.md` | **AI/协作者指令**：必读顺序、命令、红线、验证清单、常见任务配方 |
| `AI-USAGE-LOG-dream-pond-focus-frog.md` | AI 使用日志（含可核验的 Git/测试证据；未留存的历史对话已标注） |

### 2.4 过程与交付

| 文件 | 内容 |
|---|---|
| `EVIDENCE-dream-pond-focus-frog.md` | 测试与验证、缺陷记录、用户反馈、迭代记录、Demo Day 脚本 |
| `DECISIONS-AND-VERIFICATION-dream-pond-focus-frog.md` | 决策记录（D-001–D-028）与验证流水（V-001–V-025），含未修复项 |
| `REFLECTION-dream-pond-focus-frog.md` | 回顾、AI 审计、贡献记录、发布说明 |
| `VIBE-CODING-dream-pond-focus-frog.md` | 从想法到原型的过程、主要迭代、原型链接与反馈 |

## 3. 文档与代码的对应关系

| 文档中的说法 | 可核验位置 |
|---|---|
| 版本号与功能变更 | `CHANGELOG.md`、Git tag `v1.9.3` |
| 模型指标 | `outputs/train_report.md` |
| API 路径 | `app/server.py` 的 `@app.get/post` |
| 本地存储键 | `web/assets/*.js` 中的 `localStorage` 调用 |
| 测试与缺陷 | Git 提交记录 + `EVIDENCE` 中的对照表 |
| 决策与验证 | `DECISIONS-AND-VERIFICATION-dream-pond-focus-frog.md` |
| 贡献统计 | `git shortlog` / `git log --numstat`（2026-11-17 快照） |

## 4. 维护约定

1. 版本发布（`vX.Y.Z`）时同步更新：`CHANGELOG.md`、`tech-stack.md` 的版本行、`ARCHITECTURE.md` §10 版本记录，以及 `app = FastAPI(version=...)`
2. 新增/修改 API 时同步更新 `ARCHITECTURE.md` §5 与 `usage-and-privacy.md` §4
3. 修改隐私相关实现时同步更新 `usage-and-privacy.md` §6 的数据清单
4. 新增成长系统或成就时同步更新 `usage-and-privacy.md` §3.6 与 `EVIDENCE` 的验收项
5. 不使用无法核验的数字：涉及指标、用户量、测试结果时，注明来源或标注"待验证"
6. 修改协作规则时同步更新 `AGENTS-dream-pond-focus-frog.md`；修改接口/算法常数时同步更新 `BRIEF-TECH-DESIGN-dream-pond-focus-frog.md`
7. 新增决策或验证时按编号追加到 `DECISIONS-AND-VERIFICATION-dream-pond-focus-frog.md`，不覆盖历史
